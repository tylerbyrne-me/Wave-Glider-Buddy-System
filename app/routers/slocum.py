"""
Slocum dataset listing, map integration, and dashboard chart API.

Provides endpoints to list active/config Slocum datasets, search ERDDAP,
and fetch chart data for the Slocum mission dashboard.
"""
import asyncio
import io
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, List, Literal, Optional

import numpy as np
import pandas as pd

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from ..config import settings
from ..core.auth import get_current_active_user
from ..core import models
from ..core.feature_toggles import is_feature_enabled
from ..core.slocum_erddap_client import fetch_slocum_ctd_data, fetch_slocum_dashboard_data, list_slocum_datasets
from ..core import processors

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/slocum", tags=["Slocum"])

# Cache for full dataset list (ERDDAP list does not change frequently)
_DATASETS_CACHE: dict[str, Any] | None = None
_DATASETS_CACHE_TIME: float = 0
_DATASETS_CACHE_TTL_SECONDS = 300  # 5 minutes

# Cache for dashboard DataFrame per (dataset_id, time_start_str, time_end_str) to avoid
# re-downloading from ERDDAP on every chart request and CSV download.
_CHART_DATA_CACHE: dict[tuple[Any, ...], tuple[pd.DataFrame, float]] = {}
_CHART_DATA_CACHE_TTL_SECONDS = 120  # 2 minutes
# Coalesce concurrent requests for the same time window into one ERDDAP fetch.
_CHART_DATA_IN_FLIGHT: dict[tuple[Any, ...], asyncio.Task] = {}
_CHART_DATA_LOCK: asyncio.Lock | None = None
# Time-window rounding uses settings.slocum_cache_window_minutes for stable cache keys.

def _get_chart_data_lock() -> asyncio.Lock:
    """Lazy-init lock so it's created in the event loop."""
    global _CHART_DATA_LOCK
    if _CHART_DATA_LOCK is None:
        _CHART_DATA_LOCK = asyncio.Lock()
    return _CHART_DATA_LOCK

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


async def _fetch_and_cache_dashboard_df(
    dataset_id: str,
    time_start_str: Optional[str],
    time_end_str: Optional[str],
    cache_key: tuple[Any, ...],
) -> pd.DataFrame | None:
    """Perform one ERDDAP fetch, cache result, and remove from in-flight. Used for coalescing."""
    try:
        df = await asyncio.to_thread(
            fetch_slocum_dashboard_data,
            dataset_id,
            time_start_str,
            time_end_str,
        )
        if df is None or df.empty:
            return None
        processed = processors.preprocess_slocum_dashboard_df(df)
        _CHART_DATA_CACHE[cache_key] = (processed, time.time())
        return processed
    finally:
        _CHART_DATA_IN_FLIGHT.pop(cache_key, None)


async def _get_cached_or_fetch_dashboard_df(
    dataset_id: str,
    time_start_str: Optional[str],
    time_end_str: Optional[str],
) -> pd.DataFrame | None:
    """
    Return processed dashboard DataFrame for the given time window. Uses in-memory cache
    when the same window was recently fetched, and coalesces concurrent requests for
    the same window into a single ERDDAP fetch to avoid connection resets from the server.
    """
    cache_key = (dataset_id, time_start_str, time_end_str)
    now = time.time()
    lock = _get_chart_data_lock()
    async with lock:
        if cache_key in _CHART_DATA_CACHE:
            cached_df, cached_at = _CHART_DATA_CACHE[cache_key]
            if (now - cached_at) < _CHART_DATA_CACHE_TTL_SECONDS:
                return cached_df
        if cache_key in _CHART_DATA_IN_FLIGHT:
            task = _CHART_DATA_IN_FLIGHT[cache_key]
        else:
            task = asyncio.create_task(
                _fetch_and_cache_dashboard_df(
                    dataset_id, time_start_str, time_end_str, cache_key
                )
            )
            _CHART_DATA_IN_FLIGHT[cache_key] = task
    return await task


# CTD cache and coalescing (same pattern as dashboard)
_CTD_DATA_CACHE: dict[tuple[Any, ...], tuple[pd.DataFrame, float]] = {}
_CTD_DATA_TTL_SECONDS = 120
_CTD_DATA_IN_FLIGHT: dict[tuple[Any, ...], asyncio.Task] = {}
_CTD_DATA_LOCK: asyncio.Lock | None = None


def _get_ctd_data_lock() -> asyncio.Lock:
    global _CTD_DATA_LOCK
    if _CTD_DATA_LOCK is None:
        _CTD_DATA_LOCK = asyncio.Lock()
    return _CTD_DATA_LOCK


async def _fetch_and_cache_ctd_df(
    dataset_id: str,
    time_start_str: Optional[str],
    time_end_str: Optional[str],
    cache_key: tuple[Any, ...],
) -> pd.DataFrame | None:
    try:
        df = await asyncio.to_thread(
            fetch_slocum_ctd_data,
            dataset_id,
            time_start_str,
            time_end_str,
        )
        if df is None or df.empty:
            return None
        processed = processors.preprocess_slocum_ctd_df(df)
        _CTD_DATA_CACHE[cache_key] = (processed, time.time())
        return processed
    finally:
        _CTD_DATA_IN_FLIGHT.pop(cache_key, None)


async def _get_cached_or_fetch_ctd_df(
    dataset_id: str,
    time_start_str: Optional[str],
    time_end_str: Optional[str],
) -> pd.DataFrame | None:
    cache_key = (dataset_id, time_start_str, time_end_str)
    now = time.time()
    lock = _get_ctd_data_lock()
    async with lock:
        if cache_key in _CTD_DATA_CACHE:
            cached_df, cached_at = _CTD_DATA_CACHE[cache_key]
            if (now - cached_at) < _CTD_DATA_TTL_SECONDS:
                return cached_df
        if cache_key in _CTD_DATA_IN_FLIGHT:
            task = _CTD_DATA_IN_FLIGHT[cache_key]
        else:
            task = asyncio.create_task(
                _fetch_and_cache_ctd_df(
                    dataset_id, time_start_str, time_end_str, cache_key
                )
            )
            _CTD_DATA_IN_FLIGHT[cache_key] = task
    return await task


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
    global _DATASETS_CACHE, _DATASETS_CACHE_TIME
    now = time.monotonic()
    if _DATASETS_CACHE is not None and (now - _DATASETS_CACHE_TIME) < _DATASETS_CACHE_TTL_SECONDS:
        return _DATASETS_CACHE
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
    _DATASETS_CACHE = response
    _DATASETS_CACHE_TIME = now
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


def _parse_slocum_time_window(
    dataset_id: str,
    hours_back: int,
    is_historical: bool,
    start_date: Optional[str],
    end_date: Optional[str],
) -> tuple[Optional[str], Optional[str], bool]:
    """
    Compute (time_start_str, time_end_str, use_date_range) for chart/CSV.
    Respects historical_slocum_datasets and date range vs hours_back.
    """
    historical_ids = {s.strip() for s in settings.historical_slocum_datasets if s and s.strip()}
    if not is_historical and dataset_id in historical_ids:
        is_historical = True
    use_date_range = bool(start_date and end_date)
    if use_date_range:
        return (start_date.strip() if start_date else None, end_date.strip() if end_date else None, use_date_range)
    if is_historical:
        return (None, None, use_date_range)
    time_end = datetime.now(timezone.utc)
    # Round time_end down to the nearest cache-window minutes so the cache key
    # is stable for that interval (avoids refetching the same 32k+ rows every few seconds).
    window_min = max(1, settings.slocum_cache_window_minutes)
    t = time_end.replace(second=0, microsecond=0)
    time_end = t - timedelta(minutes=t.minute % window_min)
    time_start = time_end - timedelta(hours=hours_back)
    return (time_start.strftime("%Y-%m-%dT%H:%M:%SZ"), time_end.strftime("%Y-%m-%dT%H:%M:%SZ"), use_date_range)


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
    hours_back: int = Query(72, ge=1, le=8760, description="Hours of data (used when start_date/end_date not provided)"),
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
    time_start_str, time_end_str, use_date_range = _parse_slocum_time_window(
        dataset_id, hours_back, is_historical, start_date, end_date
    )
    value_col = _SLOCUM_VARIABLE_TO_COLUMN[variable]
    is_ctd = variable in _SLOCUM_CTD_CHART_VARIABLES
    try:
        if is_ctd:
            processed = await _get_cached_or_fetch_ctd_df(
                dataset_id, time_start_str, time_end_str
            )
        else:
            processed = await _get_cached_or_fetch_dashboard_df(
                dataset_id, time_start_str, time_end_str
            )
    except Exception as e:
        logger.exception("Slocum chart data fetch failed for %s", dataset_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"ERDDAP fetch failed: {str(e)}",
        ) from e

    if processed is None or processed.empty or "Timestamp" not in processed.columns or value_col not in processed.columns:
        return {"data": [], "cache_metadata": _cache_metadata()}

    last_dt = _last_dt_from_processed(processed)
    if last_dt is None:
        return {"data": [], "cache_metadata": _cache_metadata()}

    if use_date_range:
        try:
            start_dt = pd.to_datetime(time_start_str, utc=True)
            end_dt = pd.to_datetime(time_end_str, utc=True)
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
        except Exception:
            return {"data": [], "cache_metadata": _cache_metadata()}
        mask = (processed["Timestamp"] >= start_dt) & (processed["Timestamp"] <= end_dt)
        recent = processed.loc[mask].copy()
    else:
        cutoff = last_dt - timedelta(hours=hours_back)
        recent = processed[processed["Timestamp"] > cutoff].copy()

    if recent.empty:
        return {"data": [], "cache_metadata": _cache_metadata(last_dt.isoformat())}

    recent = recent.set_index("Timestamp")
    series = recent[value_col].astype(float)
    if granularity_minutes and granularity_minutes > 0:
        out_df = series.resample(f"{granularity_minutes}min").mean().reset_index()
    else:
        out_df = series.reset_index()
    out_df = out_df.rename(columns={value_col: "Value"})
    out_df["Timestamp"] = out_df["Timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%S")
    out_df = out_df.replace({np.nan: None})
    return {"data": out_df.to_dict(orient="records"), "cache_metadata": _cache_metadata(last_dt.isoformat())}


@router.get("/csv/{dataset_id}")
async def get_slocum_csv(
    dataset_id: str,
    hours_back: int = Query(72, ge=1, le=8760, description="Hours of data (used when start_date/end_date not provided)"),
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
        processed = await _get_cached_or_fetch_dashboard_df(
            dataset_id, time_start_str, time_end_str
        )
    except Exception as e:
        logger.exception("Slocum CSV fetch failed for %s", dataset_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"ERDDAP fetch failed: {str(e)}",
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

    if use_date_range:
        try:
            start_dt = pd.to_datetime(time_start_str, utc=True)
            end_dt = pd.to_datetime(time_end_str, utc=True)
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
        except Exception:
            return _empty_csv_response()
        mask = (processed["Timestamp"] >= start_dt) & (processed["Timestamp"] <= end_dt)
        recent = processed.loc[mask].copy()
    else:
        cutoff = last_dt - timedelta(hours=hours_back)
        recent = processed[processed["Timestamp"] > cutoff].copy()

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
