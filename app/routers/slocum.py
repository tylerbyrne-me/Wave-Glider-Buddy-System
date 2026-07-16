"""
Slocum dataset listing, map integration, and dashboard chart API.

Provides endpoints to list active/config Slocum datasets, search ERDDAP,
and fetch chart data for the Slocum mission dashboard.
"""
import asyncio
import io
import logging
import math
import time
from datetime import datetime, timedelta, timezone
from typing import Any, List, Literal, Optional

import matplotlib
matplotlib.use("Agg")
from matplotlib.colors import to_hex
import cmocean.cm as cmo
import numpy as np
import pandas as pd

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from ..config import settings
from ..core.auth import get_current_active_user, get_current_admin_user, require_platform_access
from ..core import models
from ..core.infra.feature_toggles import is_feature_enabled
from ..core.slocum_erddap_client import fetch_slocum_ctd_data, fetch_slocum_dashboard_data, list_slocum_datasets
from ..core.slocum_cache_service import (
    datasets_cache_ttl_seconds,
    get_cached_or_fetch_bundle_df,
    get_cached_or_fetch_ctd_df,
    get_cached_or_fetch_dashboard_df,
    get_datasets_cache,
    parse_slocum_time_window,
    set_datasets_cache,
    slice_processed_df,
)
from ..core.slocum_mirror_service import (
    dashboard_df_to_track_df,
    get_mirror_cache_status,
    inspect_mirror_dataset,
    load_mirror_df,
    sync_dataset_mirror,
)
from ..core.slocum_overage_cache import (
    OverageRangeError,
    OverageResult,
    get_overage_cache_status,
    purge_overage_entries,
)
from ..core.data import processors
from ..core.data.slocum_summaries import build_slocum_sensor_summaries
from ..core.infra.db import get_db_session, SQLModelSession

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/slocum",
    tags=["Slocum"],
    dependencies=[Depends(require_platform_access("slocum"))],
)

ERDDAP_REQUEST_TIMEOUT = 35  # Slightly above client timeout for asyncio.wait_for


def _dataset_row_to_dict(row: pd.Series) -> dict[str, Any]:
    """Convert a DataFrame row to a JSON-serializable dict."""
    out: dict[str, Any] = {}
    for k in row.index:
        v = row[k]
        if pd.isna(v):
            out[str(k)] = None
        elif hasattr(v, "isoformat"):
            out[str(k)] = v.isoformat()
        else:
            out[str(k)] = str(v)
    return out


# Map query variable to processed column name for chart API
def _build_datasets_response(df: pd.DataFrame | None, active_ids: list[str]) -> dict[str, Any]:
    """Build {active, available} response from DataFrame and active IDs."""
    if df is None or df.empty:
        active_list = [
            {"datasetID": did, "title": did, "institution": None, "minTime": None, "maxTime": None}
            for did in active_ids
        ]
        return {"active": active_list, "available": []}
    records = df.to_dict(orient="records")
    available = [_dataset_row_to_dict(pd.Series(r)) for r in records]
    dataset_id_col = "datasetID"
    if dataset_id_col not in df.columns and len(df.columns):
        dataset_id_col = df.columns[0]
    id_to_meta = {str(r.get(dataset_id_col, "")): r for r in records}
    active_list = []
    for did in active_ids:
        if did in id_to_meta:
            active_list.append(_dataset_row_to_dict(pd.Series(id_to_meta[did])))
        else:
            active_list.append({
                "datasetID": did,
                "title": did,
                "institution": None,
                "minTime": None,
                "maxTime": None,
            })
    available_only = [r for r in available if str(r.get("datasetID", "")) not in set(active_ids)]
    return {"active": active_list, "available": available_only}


@router.get("/datasets")
async def get_slocum_datasets(
    current_user: models.User = Depends(get_current_active_user),
):
    """
    Return combined list of Slocum datasets: active (from config) and available (from ERDDAP).
    Active datasets are those listed in settings.active_slocum_datasets; they appear first
    with metadata from ERDDAP when possible. Response is cached for 5 minutes.
    """
    if not is_feature_enabled("slocum_platform"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Slocum platform is disabled (feature_toggles.slocum_platform).",
        )
    active_ids = [s.strip() for s in settings.active_slocum_datasets if s and s.strip()]
    cached_response, cached_at = get_datasets_cache()
    now = time.monotonic()
    if cached_response is not None and (now - cached_at) < datasets_cache_ttl_seconds():
        return cached_response
    try:
        df = await asyncio.wait_for(
            asyncio.to_thread(list_slocum_datasets, None),
            timeout=ERDDAP_REQUEST_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.warning("ERDDAP dataset list timed out")
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="ERDDAP server did not respond in time. Try again later.",
        ) from None
    except Exception as e:
        logger.exception("Slocum list_slocum_datasets failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"ERDDAP dataset list failed: {str(e)}",
        ) from e
    response = _build_datasets_response(df, active_ids)
    set_datasets_cache(response, now)
    return response


@router.get("/available_datasets", response_model=List[str])
async def get_available_datasets(
    current_user: models.User = Depends(get_current_active_user),
):
    """Get list of active Slocum dataset IDs (from config). Mirrors /api/available_missions."""
    if not is_feature_enabled("slocum_platform"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Slocum platform is disabled (feature_toggles.slocum_platform).",
        )
    return [m for m in settings.active_slocum_datasets if m and m.strip()]


@router.get("/available_historical_datasets", response_model=List[str])
async def get_available_historical_datasets(
    current_user: models.User = Depends(get_current_active_user),
):
    """Get list of historical Slocum dataset IDs (from config). Mirrors /api/available_historical_missions."""
    if not is_feature_enabled("slocum_platform"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Slocum platform is disabled (feature_toggles.slocum_platform).",
        )
    return [m for m in settings.historical_slocum_datasets if m and m.strip()]


@router.get("/datasets/search")
async def search_slocum_datasets(
    q: str = Query(..., min_length=1, description="Search term for dataset title"),
    current_user: models.User = Depends(get_current_active_user),
):
    """Search ERDDAP for Slocum datasets by title (case-insensitive)."""
    if not is_feature_enabled("slocum_platform"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Slocum platform is disabled (feature_toggles.slocum_platform).",
        )
    try:
        df = await asyncio.wait_for(
            asyncio.to_thread(list_slocum_datasets, q),
            timeout=ERDDAP_REQUEST_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.warning("ERDDAP dataset search timed out")
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="ERDDAP server did not respond in time. Try again later.",
        ) from None
    except Exception as e:
        logger.exception("Slocum search failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"ERDDAP search failed: {str(e)}",
        ) from e
    if df is None or df.empty:
        return {"datasets": []}
    records = df.to_dict(orient="records")
    datasets = [_dataset_row_to_dict(pd.Series(r)) for r in records]
    return {"datasets": datasets}


# Map query variable to processed column name for chart API
_parse_slocum_time_window = parse_slocum_time_window
_get_cached_or_fetch_dashboard_df = get_cached_or_fetch_dashboard_df
_get_cached_or_fetch_ctd_df = get_cached_or_fetch_ctd_df

_SLOCUM_VARIABLE_TO_COLUMN = {
    "m_depth": "MDepth",
    "m_altitude": "MAltitude",
    "m_raw_altitude": "MRawAltitude",
    "m_water_depth": "MWaterDepth",
    "c_pitch": "CPitch",
    "m_pitch": "MPitch",
    "m_roll": "MRoll",
    "c_heading": "CHeading",
    "m_heading": "MHeading",
    "c_fin": "CFin",
    "m_fin": "MFin",
    "m_battery": "MBattery",
    "m_coulomb_amphr_total": "MCoulombAmphrTotal",
    "conductivity": "Conductivity",
    "temperature": "Temperature",
    "pressure": "Pressure",
    "salinity": "Salinity",
    "density": "Density",
}

_SLOCUM_CTD_CHART_VARIABLES = ("conductivity", "temperature", "pressure", "salinity", "density")

# CTD depth-vs-time profile variables for Chart.js scatter + cmocean color grading
_SLOCUM_PROFILE_VARIABLES = {
    "temperature": {"column": "Temperature", "unit": "°C"},
    "conductivity": {"column": "Conductivity", "unit": "S m-1"},
    "density": {"column": "Density", "unit": "kg m-3"},
}
_PROFILE_COLORMAP_STOPS = 64
_PROFILE_MAX_POINTS = 15000


def _colormap_hex_stops(cmap, n: int = _PROFILE_COLORMAP_STOPS) -> list[str]:
    """Sample a matplotlib/cmocean colormap into hex stops for client-side coloring."""
    if n < 2:
        return [to_hex(cmap(0.5))]
    return [to_hex(cmap(i / (n - 1))) for i in range(n)]


# Generated once at import; sent to the client with profile-data responses
_SLOCUM_PROFILE_COLORMAPS: dict[str, list[str]] = {
    "temperature": _colormap_hex_stops(cmo.thermal),
    "conductivity": _colormap_hex_stops(cmo.haline),
    "density": _colormap_hex_stops(cmo.dense),
}

# Processed DataFrame column (PascalCase) -> CSV header (snake_case)
_SLOCUM_CSV_COLUMN_RENAME = {
    "MDepth": "m_depth",
    "MAltitude": "m_altitude",
    "MRawAltitude": "m_raw_altitude",
    "MWaterDepth": "m_water_depth",
    "CPitch": "c_pitch",
    "MPitch": "m_pitch",
    "MRoll": "m_roll",
    "CHeading": "c_heading",
    "MHeading": "m_heading",
    "CFin": "c_fin",
    "MFin": "m_fin",
    "MBattery": "m_battery",
    "MCoulombAmphrTotal": "m_coulomb_amphr_total",
}

_SLOCUM_CHART_VARIABLES = [
    "m_depth", "m_altitude", "m_raw_altitude", "m_water_depth",
    "c_pitch", "m_pitch", "m_roll",
    "c_heading", "m_heading", "c_fin", "m_fin",
    "m_battery", "m_coulomb_amphr_total",
    "conductivity", "temperature", "pressure", "salinity", "density",
]

# Reused in chart-data and CSV empty responses
_EMPTY_CACHE_METADATA = {"cache_timestamp": None, "last_data_timestamp": None, "file_modification_time": None}


def _cache_metadata(last_data_timestamp: Optional[str] = None) -> dict[str, Any]:
    """Build cache_metadata dict for chart/CSV responses."""
    return {**_EMPTY_CACHE_METADATA, "last_data_timestamp": last_data_timestamp}


def _merge_overage_metadata(
    base: dict[str, Any],
    overage_meta: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Attach overage/mirror source fields without breaking existing clients."""
    out = dict(base)
    if not overage_meta:
        return out
    for key in (
        "data_source",
        "requested_range",
        "normalized_range",
        "cache_created_at",
        "cache_expires_at",
        "cache_key",
        "bundle",
    ):
        if key in overage_meta:
            out[key] = overage_meta[key]
    return out


async def _load_bundle_result(
    dataset_id: str,
    bundle: str,
    *,
    hours_back: int,
    is_historical: bool,
    start_date: Optional[str],
    end_date: Optional[str],
) -> OverageResult:
    """Load one bundle via mirror/overage; raise HTTPException for range/validation errors."""
    time_start_str, time_end_str, _use_date_range = _parse_slocum_time_window(
        dataset_id, hours_back, is_historical, start_date, end_date
    )
    try:
        result = await get_cached_or_fetch_bundle_df(
            dataset_id,
            bundle,
            time_start_str,
            time_end_str,
            hours_back=hours_back,
            is_historical=is_historical,
            context="interactive",
            return_metadata=True,
        )
    except OverageRangeError as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err)) from err
    if not isinstance(result, OverageResult):
        df = result if isinstance(result, pd.DataFrame) else pd.DataFrame()
        return OverageResult(df=df if df is not None else pd.DataFrame(), metadata={"data_source": "mirror"})
    return result


def _resample_series(
    processed: pd.DataFrame,
    value_col: str,
    granularity_minutes: Optional[int],
) -> list[dict[str, Any]]:
    if processed.empty or value_col not in processed.columns:
        return []
    recent = processed.set_index("Timestamp")
    series = recent[value_col].astype(float)
    if granularity_minutes and granularity_minutes > 0:
        out_df = series.resample(f"{granularity_minutes}min").mean().reset_index()
    else:
        out_df = series.reset_index()
    out_df = out_df.rename(columns={value_col: "Value"})
    out_df["Timestamp"] = out_df["Timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%S")
    out_df = out_df.replace({np.nan: None})
    return out_df.to_dict(orient="records")


def _last_dt_from_processed(processed: pd.DataFrame) -> Optional[datetime]:
    """Extract last Timestamp from processed dashboard DataFrame as timezone-aware datetime."""
    if processed.empty or "Timestamp" not in processed.columns:
        return None
    max_ts = processed["Timestamp"].max()
    if pd.isna(max_ts):
        return None
    if hasattr(max_ts, "to_pydatetime"):
        last_dt = max_ts.to_pydatetime()
    else:
        last_dt = pd.to_datetime(max_ts, utc=True)
    if last_dt.tzinfo is None:
        last_dt = last_dt.replace(tzinfo=timezone.utc)
    return last_dt


# Single source for CSV empty/header-only content (must match _SLOCUM_CSV_COLUMN_RENAME keys)
_SLOCUM_CSV_EMPTY_HEADER = "Timestamp,m_depth,m_altitude,m_raw_altitude,m_water_depth,c_pitch,m_pitch,m_roll,c_heading,m_heading,c_fin,m_fin,m_battery,m_coulomb_amphr_total\n"


@router.get("/cache-status/{dataset_id}")
async def get_slocum_cache_status(
    dataset_id: str,
    current_user: models.User = Depends(get_current_active_user),
):
    """Mirror cache status for Slocum dashboard/CTD bundles (frontend polling)."""
    if not is_feature_enabled("slocum_platform"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Slocum platform is disabled.")
    status_payload = get_mirror_cache_status(dataset_id)
    return status_payload


@router.get("/sensor-summaries/{dataset_id}")
async def get_slocum_sensor_summaries(
    dataset_id: str,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """
    Left-nav sensor card summaries (values + mini_trend) for enabled Slocum cards.
    Used for soft refresh when mirror cache advances without a full page reload.
    """
    if not is_feature_enabled("slocum_platform"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Slocum platform is disabled.")

    # Import here to avoid circular import at module load (home imports slocum_summaries only).
    from .home import _resolve_slocum_enabled_sensor_cards

    enabled_cards = _resolve_slocum_enabled_sensor_cards(
        session,
        dataset_id,
        username=current_user.username if current_user else "system",
    )
    summaries = build_slocum_sensor_summaries(dataset_id, enabled_cards)
    return summaries.get("sensors") or {}


@router.get("/cache-inspect/{dataset_id}")
async def inspect_slocum_dataset_cache(
    dataset_id: str,
    hours_back: int = Query(72, ge=1, le=8760),
    current_admin: models.User = Depends(get_current_admin_user),
):
    """
    Admin Cached Dataset Inspector: mirror row counts, column non-nulls, and
    profile-ready science point counts for the selected hours window.
    """
    if not is_feature_enabled("slocum_platform"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Slocum platform is disabled.")

    report = inspect_mirror_dataset(dataset_id, hours_back=hours_back)
    report["overage"] = get_overage_cache_status(dataset_id)

    # Profile point count from the current mirror (no ERDDAP round-trip)
    try:
        ctd_df = load_mirror_df(dataset_id, "ctd")
        sliced = slice_processed_df(
            ctd_df,
            hours_back=hours_back,
            use_date_range=False,
            time_start_str=None,
            time_end_str=None,
        )
        profile = _build_profile_payload(sliced)
        report["profile"] = {
            "points": len(profile.get("points") or []),
            "ranges": profile.get("ranges") or {},
            "units": profile.get("units") or {},
        }
    except Exception as err:
        logger.warning("Cache inspect profile summary failed for %s: %s", dataset_id, err)
        report["profile"] = {"points": 0, "error": str(err)}

    return report


@router.post("/mirror/{dataset_id}/sync")
async def force_sync_slocum_mirror(
    dataset_id: str,
    rebuild_ctd: bool = Query(
        True,
        description="Clear and re-fetch CTD without ERDDAP orderByClosest so dive profiles are preserved.",
    ),
    hours_back: Optional[int] = Query(None, ge=1, le=8760),
    current_admin: models.User = Depends(get_current_admin_user),
):
    """Admin: force an ERDDAP mirror sync (optionally rebuild undecimated CTD)."""
    if not is_feature_enabled("slocum_platform"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Slocum platform is disabled.")
    try:
        summary = await sync_dataset_mirror(
            dataset_id,
            hours_back=hours_back,
            force=True,
            rebuild_ctd=rebuild_ctd,
        )
    except Exception as err:
        logger.exception("Forced Slocum mirror sync failed for %s", dataset_id)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(err)) from err
    logger.info(
        "Admin '%s' forced mirror sync for %s (rebuild_ctd=%s)",
        current_admin.username,
        dataset_id,
        rebuild_ctd,
    )
    return summary


@router.get("/overage-cache/status")
async def get_slocum_overage_cache_status(
    dataset_id: Optional[str] = Query(None),
    current_admin: models.User = Depends(get_current_admin_user),
):
    """Admin: list temporary overage-cache entries and hit/miss counters."""
    if not is_feature_enabled("slocum_platform"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Slocum platform is disabled.")
    return get_overage_cache_status(dataset_id)


@router.post("/overage-cache/purge")
async def purge_slocum_overage_cache(
    dataset_id: Optional[str] = Query(None, description="Limit purge to one dataset; omit for all."),
    force_all: bool = Query(False, description="Remove valid entries too (not only expired)."),
    current_admin: models.User = Depends(get_current_admin_user),
):
    """Admin: purge expired/corrupt overage entries (or wipe a dataset's temporary cache)."""
    if not is_feature_enabled("slocum_platform"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Slocum platform is disabled.")
    summary = purge_overage_entries(dataset_id=dataset_id, force_all=force_all)
    logger.info(
        "Admin '%s' purged Slocum overage cache (dataset_id=%s, force_all=%s, removed=%s)",
        current_admin.username,
        dataset_id,
        force_all,
        summary.get("removed_files"),
    )
    return summary


def _profile_depth_series(df: pd.DataFrame) -> pd.Series:
    """Prefer Depth (m); fall back to Pressure (dbar ≈ m) for science samples without Depth."""
    if "Depth" in df.columns:
        depth = pd.to_numeric(df["Depth"], errors="coerce")
    else:
        depth = pd.Series(np.nan, index=df.index, dtype=float)
    if "Pressure" in df.columns:
        pressure = pd.to_numeric(df["Pressure"], errors="coerce")
        depth = depth.fillna(pressure)
    return depth


def _nice_colorbar_range(series: pd.Series) -> dict[str, Optional[int]]:
    """
    Robust color-scale bounds for profile charts.

    Uses the central 2nd–98th percentile so outliers (e.g. zeroed conductivity)
    do not flatten the cmocean gradient, then snaps outward to whole-number
    colorbar labels (e.g. 10, 36, 1024).
    """
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return {"min": None, "max": None}

    if len(values) >= 8:
        lo = float(values.quantile(0.02))
        hi = float(values.quantile(0.98))
    else:
        lo = float(values.min())
        hi = float(values.max())

    if not math.isfinite(lo) or not math.isfinite(hi):
        return {"min": None, "max": None}
    if lo > hi:
        lo, hi = hi, lo
    if lo == hi:
        # Degenerate span: pad by 1 unit around the value
        center = lo
        lo = center - 0.5
        hi = center + 0.5

    nice_min = int(math.floor(lo))
    nice_max = int(math.ceil(hi))
    if nice_min == nice_max:
        nice_max = nice_min + 1
    return {"min": nice_min, "max": nice_max}


def _build_profile_payload(sliced: pd.DataFrame) -> dict[str, Any]:
    """
    Build Chart.js-ready profile payload from a sliced CTD DataFrame.
    Depth uses Depth with Pressure fallback; rows without depth are dropped.
    Decimates by stride when the window exceeds _PROFILE_MAX_POINTS (mean
    resampling would destroy vertical profile structure).
    """
    empty = {
        "points": [],
        "ranges": {key: {"min": None, "max": None} for key in _SLOCUM_PROFILE_VARIABLES},
        "colormaps": dict(_SLOCUM_PROFILE_COLORMAPS),
        "units": {key: cfg["unit"] for key, cfg in _SLOCUM_PROFILE_VARIABLES.items()},
    }
    if sliced is None or sliced.empty or "Timestamp" not in sliced.columns:
        return empty

    work = sliced.copy()
    work["depth"] = _profile_depth_series(work)
    work = work.dropna(subset=["depth"])
    if work.empty:
        return empty

    for key, cfg in _SLOCUM_PROFILE_VARIABLES.items():
        col = cfg["column"]
        if col in work.columns:
            work[key] = pd.to_numeric(work[col], errors="coerce")
        else:
            work[key] = np.nan

    # Keep rows that have at least one profile variable
    value_cols = list(_SLOCUM_PROFILE_VARIABLES.keys())
    work = work.dropna(subset=value_cols, how="all")
    if work.empty:
        return empty

    if len(work) > _PROFILE_MAX_POINTS:
        stride = int(np.ceil(len(work) / _PROFILE_MAX_POINTS))
        work = work.iloc[::stride].copy()

    ts = pd.to_datetime(work["Timestamp"], utc=True, errors="coerce")
    valid_ts = ts.notna()
    work = work.loc[valid_ts].copy()
    ts = ts.loc[valid_ts]
    if work.empty:
        return empty

    out = pd.DataFrame({
        "t": ts.dt.strftime("%Y-%m-%dT%H:%M:%S"),
        "depth": work["depth"].astype(float),
    })
    for key in value_cols:
        out[key] = work[key].astype(float)
    out = out.replace({np.nan: None})
    points = out.to_dict(orient="records")

    ranges: dict[str, dict[str, Optional[int]]] = {}
    for key in value_cols:
        ranges[key] = _nice_colorbar_range(work[key])

    return {
        "points": points,
        "ranges": ranges,
        "colormaps": dict(_SLOCUM_PROFILE_COLORMAPS),
        "units": {key: cfg["unit"] for key, cfg in _SLOCUM_PROFILE_VARIABLES.items()},
    }


@router.get("/profile-data/{dataset_id}")
async def get_slocum_profile_data(
    dataset_id: str,
    hours_back: int = Query(24, ge=1, le=8760),
    is_historical: bool = Query(False),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    current_user: models.User = Depends(get_current_active_user),
):
    """
    CTD depth-vs-time profile points for Chart.js scatter charts.
    Returns temperature, conductivity, and density with cmocean colormap stops.
    Time-mean resampling is not applied (it would destroy profile structure);
    large windows are stride-decimated instead.
    """
    if not is_feature_enabled("slocum_platform"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Slocum platform is disabled.")

    try:
        ctd_result = await _load_bundle_result(
            dataset_id,
            "ctd",
            hours_back=hours_back,
            is_historical=is_historical,
            start_date=start_date,
            end_date=end_date,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Slocum profile data fetch failed for %s", dataset_id)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Data fetch failed: {str(e)}") from e

    sliced = ctd_result.df if ctd_result.df is not None else pd.DataFrame()
    if sliced.empty:
        payload = _build_profile_payload(pd.DataFrame())
        payload["cache_metadata"] = _merge_overage_metadata(_cache_metadata(), ctd_result.metadata)
        return payload

    last_dt = _last_dt_from_processed(sliced)
    payload = _build_profile_payload(sliced)
    payload["cache_metadata"] = _merge_overage_metadata(
        _cache_metadata(last_dt.isoformat() if last_dt else None),
        ctd_result.metadata,
    )
    return payload


@router.get("/chart-data-bulk/{dataset_id}")
async def get_slocum_chart_data_bulk(
    dataset_id: str,
    variables: str = Query(..., description="Comma-separated variable names"),
    hours_back: int = Query(24, ge=1, le=8760),
    granularity_minutes: Optional[int] = Query(15, ge=0, le=60),
    is_historical: bool = Query(False),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    current_user: models.User = Depends(get_current_active_user),
):
    """Fetch multiple Slocum chart variables in one request (one mirror read, one resample pass)."""
    if not is_feature_enabled("slocum_platform"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Slocum platform is disabled.")

    requested = [v.strip() for v in variables.split(",") if v.strip()]
    invalid = [v for v in requested if v not in _SLOCUM_CHART_VARIABLES]
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown variables: {', '.join(invalid)}",
        )

    ctd_vars = [v for v in requested if v in _SLOCUM_CTD_CHART_VARIABLES]
    dash_vars = [v for v in requested if v not in _SLOCUM_CTD_CHART_VARIABLES]

    try:
        dashboard_result = None
        ctd_result = None
        if dash_vars:
            dashboard_result = await _load_bundle_result(
                dataset_id,
                "dashboard",
                hours_back=hours_back,
                is_historical=is_historical,
                start_date=start_date,
                end_date=end_date,
            )
        if ctd_vars:
            ctd_result = await _load_bundle_result(
                dataset_id,
                "ctd",
                hours_back=hours_back,
                is_historical=is_historical,
                start_date=start_date,
                end_date=end_date,
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Slocum bulk chart data fetch failed for %s", dataset_id)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Data fetch failed: {str(e)}") from e

    series: dict[str, list[dict[str, Any]]] = {}
    last_dt: Optional[datetime] = None
    source_meta: dict[str, Any] = {}

    if dash_vars and dashboard_result is not None and not dashboard_result.df.empty:
        sliced = dashboard_result.df
        last_dt = _last_dt_from_processed(sliced)
        source_meta = dashboard_result.metadata or source_meta
        for variable in dash_vars:
            value_col = _SLOCUM_VARIABLE_TO_COLUMN[variable]
            series[variable] = _resample_series(sliced, value_col, granularity_minutes)

    if ctd_vars and ctd_result is not None and not ctd_result.df.empty:
        sliced = ctd_result.df
        ctd_last = _last_dt_from_processed(sliced)
        if ctd_last and (last_dt is None or ctd_last > last_dt):
            last_dt = ctd_last
        source_meta = ctd_result.metadata or source_meta
        for variable in ctd_vars:
            value_col = _SLOCUM_VARIABLE_TO_COLUMN[variable]
            series[variable] = _resample_series(sliced, value_col, granularity_minutes)

    for variable in requested:
        series.setdefault(variable, [])

    return {
        "series": series,
        "cache_metadata": _merge_overage_metadata(
            _cache_metadata(last_dt.isoformat() if last_dt else None),
            source_meta,
        ),
    }


@router.get("/chart-data/{dataset_id}")
async def get_slocum_chart_data(
    dataset_id: str,
    variable: Literal[
        "m_depth", "m_altitude", "m_raw_altitude", "m_water_depth",
        "c_pitch", "m_pitch", "m_roll",
        "c_heading", "m_heading", "c_fin", "m_fin",
        "m_battery", "m_coulomb_amphr_total",
        "conductivity", "temperature", "pressure", "salinity", "density",
    ] = Query(..., description="Variable to plot"),
    hours_back: int = Query(24, ge=1, le=8760, description="Hours of data (used when start_date/end_date not provided)"),
    granularity_minutes: Optional[int] = Query(15, ge=0, le=60, description="Resampling interval (minutes). 0 = show all data (no resampling)."),
    is_historical: bool = Query(False, description="If true, fetch full dataset and show last N hours from data end (like WG historical)."),
    start_date: Optional[str] = Query(None, description="Start time ISO 8601 (e.g. 2025-08-01T00:00:00Z). Use with end_date for date range."),
    end_date: Optional[str] = Query(None, description="End time ISO 8601 (e.g. 2025-08-31T23:59:59Z). Use with start_date for date range."),
    current_user: models.User = Depends(get_current_active_user),
):
    """
    Fetch Slocum ERDDAP data for one dashboard variable and return resampled series
    for charting. Supports dashboard variables and CTD (conductivity, temperature, pressure, salinity, density).
    """
    if not is_feature_enabled("slocum_platform"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Slocum platform is disabled (feature_toggles.slocum_platform).",
        )
    value_col = _SLOCUM_VARIABLE_TO_COLUMN[variable]
    is_ctd = variable in _SLOCUM_CTD_CHART_VARIABLES
    try:
        result = await _load_bundle_result(
            dataset_id,
            "ctd" if is_ctd else "dashboard",
            hours_back=hours_back,
            is_historical=is_historical,
            start_date=start_date,
            end_date=end_date,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Slocum chart data fetch failed for %s", dataset_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Data fetch failed: {str(e)}",
        ) from e

    recent = result.df if result.df is not None else pd.DataFrame()
    if recent.empty or "Timestamp" not in recent.columns or value_col not in recent.columns:
        return {
            "data": [],
            "cache_metadata": _merge_overage_metadata(_cache_metadata(), result.metadata),
        }

    last_dt = _last_dt_from_processed(recent)
    data = _resample_series(recent, value_col, granularity_minutes)
    return {
        "data": data,
        "cache_metadata": _merge_overage_metadata(
            _cache_metadata(last_dt.isoformat() if last_dt else None),
            result.metadata,
        ),
    }


@router.get("/csv/{dataset_id}")
async def get_slocum_csv(
    dataset_id: str,
    hours_back: int = Query(24, ge=1, le=8760, description="Hours of data (used when start_date/end_date not provided)"),
    granularity_minutes: Optional[int] = Query(15, ge=0, le=60, description="Resampling interval (minutes). 0 = show all data (no resampling)."),
    is_historical: bool = Query(False, description="If true, fetch full dataset and trim to last N hours from data end."),
    start_date: Optional[str] = Query(None, description="Start time ISO 8601. Use with end_date for date range."),
    end_date: Optional[str] = Query(None, description="End time ISO 8601. Use with start_date for date range."),
    current_user: models.User = Depends(get_current_active_user),
):
    """
    Download Slocum dashboard data (all variables) as CSV for the same time window and
    granularity as the chart controls. Uses same auth and feature toggle as chart-data.
    """
    if not is_feature_enabled("slocum_platform"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Slocum platform is disabled (feature_toggles.slocum_platform).",
        )
    time_start_str, time_end_str, use_date_range = _parse_slocum_time_window(
        dataset_id, hours_back, is_historical, start_date, end_date
    )
    try:
        dash_result = await _load_bundle_result(
            dataset_id,
            "dashboard",
            hours_back=hours_back,
            is_historical=is_historical,
            start_date=start_date,
            end_date=end_date,
        )
        processed = dash_result.df
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Slocum CSV fetch failed for %s", dataset_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Data fetch failed: {str(e)}",
        ) from e

    def _empty_csv_response() -> StreamingResponse:
        buf = io.StringIO()
        buf.write(_SLOCUM_CSV_EMPTY_HEADER)
        buf.seek(0)
        filename = f"slocum_{dataset_id}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
        return StreamingResponse(
            io.BytesIO(buf.getvalue().encode("utf-8")),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    if processed is None or processed.empty or "Timestamp" not in processed.columns:
        return _empty_csv_response()

    last_dt = _last_dt_from_processed(processed)
    if last_dt is None:
        return _empty_csv_response()

    recent = slice_processed_df(
        processed,
        hours_back=hours_back,
        use_date_range=use_date_range,
        time_start_str=time_start_str,
        time_end_str=time_end_str,
    )
    if recent.empty:
        return _empty_csv_response()

    recent = recent.set_index("Timestamp")
    numeric_cols = [c for c in recent.columns if c in _SLOCUM_CSV_COLUMN_RENAME]
    if not numeric_cols:
        numeric_cols = recent.select_dtypes(include=["number"]).columns.tolist()
    if granularity_minutes and granularity_minutes > 0:
        out_df = recent[numeric_cols].resample(f"{granularity_minutes}min").mean().reset_index()
    else:
        out_df = recent[numeric_cols].reset_index()
    out_df["Timestamp"] = out_df["Timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%S")
    out_df = out_df.rename(columns=_SLOCUM_CSV_COLUMN_RENAME)
    output = io.StringIO()
    out_df.to_csv(output, index=False)
    output.seek(0)
    filename = f"slocum_{dataset_id}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/data/{variable}/{dataset_id}")
async def get_slocum_data_shim(
    dataset_id: str,
    variable: Literal[
        "m_depth", "m_altitude", "m_raw_altitude", "m_water_depth",
        "c_pitch", "m_pitch", "m_roll",
        "c_heading", "m_heading", "c_fin", "m_fin",
        "m_battery", "m_coulomb_amphr_total",
        "conductivity", "temperature", "pressure", "salinity", "density",
    ],
    hours_back: int = Query(72, ge=1, le=8760),
    granularity_minutes: Optional[int] = Query(15, ge=0, le=60),
    is_historical: bool = Query(False),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    current_user: models.User = Depends(get_current_active_user),
):
    """WG-style shim: ``/api/slocum/data/{variable}/{dataset_id}`` mirrors ``/api/data/{type}/{mission}``."""
    return await get_slocum_chart_data(
        dataset_id=dataset_id,
        variable=variable,
        hours_back=hours_back,
        granularity_minutes=granularity_minutes,
        is_historical=is_historical,
        start_date=start_date,
        end_date=end_date,
        current_user=current_user,
    )


@router.get("/forecast/{dataset_id}")
async def get_slocum_forecast(
    dataset_id: str,
    lat: Optional[float] = Query(None),
    lon: Optional[float] = Query(None),
    is_historical: bool = Query(False),
    current_user: models.User = Depends(get_current_active_user),
):
    """Open-Meteo forecast at dataset last known position (mirrors WG ``/api/forecast``)."""
    if not is_feature_enabled("slocum_platform"):
        raise HTTPException(status_code=403, detail="Slocum platform is disabled.")
    if is_historical:
        raise HTTPException(status_code=400, detail="Forecasts are not available for historical datasets.")
    final_lat, final_lon = lat, lon
    if final_lat is None or final_lon is None:
        time_start, time_end, _ = _parse_slocum_time_window(dataset_id, 24, False, None, None)
        processed = await _get_cached_or_fetch_dashboard_df(
            dataset_id, time_start, time_end, hours_back=24
        )
        track_df = dashboard_df_to_track_df(processed) if processed is not None else pd.DataFrame()
        if not track_df.empty and "Latitude" in track_df.columns:
            last = track_df.dropna(subset=["Latitude", "Longitude"]).iloc[-1]
            final_lat, final_lon = float(last["Latitude"]), float(last["Longitude"])
    if final_lat is None or final_lon is None:
        raise HTTPException(status_code=400, detail="Lat/lon required and could not be inferred from track.")
    from ..core.geo import forecast as geo_forecast
    forecast_data = await geo_forecast.get_general_meteo_forecast(final_lat, final_lon)
    if forecast_data is None:
        raise HTTPException(status_code=503, detail="Forecast service unavailable.")
    return forecast_data


@router.get("/marine_forecast/{dataset_id}")
async def get_slocum_marine_forecast(
    dataset_id: str,
    lat: Optional[float] = Query(None),
    lon: Optional[float] = Query(None),
    is_historical: bool = Query(False),
    current_user: models.User = Depends(get_current_active_user),
):
    """Marine forecast at dataset last known position (mirrors WG ``/api/marine_forecast``)."""
    if not is_feature_enabled("slocum_platform"):
        raise HTTPException(status_code=403, detail="Slocum platform is disabled.")
    if is_historical:
        raise HTTPException(status_code=400, detail="Marine forecasts are not available for historical datasets.")
    final_lat, final_lon = lat, lon
    if final_lat is None or final_lon is None:
        time_start, time_end, _ = _parse_slocum_time_window(dataset_id, 24, False, None, None)
        processed = await _get_cached_or_fetch_dashboard_df(
            dataset_id, time_start, time_end, hours_back=24
        )
        track_df = dashboard_df_to_track_df(processed) if processed is not None else pd.DataFrame()
        if not track_df.empty:
            last = track_df.dropna(subset=["Latitude", "Longitude"]).iloc[-1]
            final_lat, final_lon = float(last["Latitude"]), float(last["Longitude"])
    if final_lat is None or final_lon is None:
        raise HTTPException(status_code=400, detail="Lat/lon required and could not be inferred from track.")
    from ..core.geo import forecast as geo_forecast
    marine_data = await geo_forecast.get_marine_meteo_forecast(final_lat, final_lon)
    if marine_data is None:
        raise HTTPException(status_code=503, detail="Marine forecast service unavailable.")
    return marine_data
