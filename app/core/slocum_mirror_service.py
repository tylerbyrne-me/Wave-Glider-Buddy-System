"""
Persistent parquet mirror for Slocum ERDDAP data.

Stores processed dashboard and CTD DataFrames on disk so all gunicorn workers
share the same cache. A leader-worker sync job incrementally appends new rows.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from ..config import settings
from ..core.slocum_bundle_registry import (
    DEFAULT_MIRROR_BUNDLES,
    get_bundle_spec,
    list_bundle_names,
    preprocess_bundle_df,
)
from ..core.slocum_erddap_client import fetch_dataset_time_extent, fetch_slocum_data
from ..core.utils import (
    promote_orphan_tmp_file,
    resolve_data_path,
    slocum_mission_key,
    write_parquet_file_atomic,
)
from .geo.coordinates import mask_null_island_coordinates

logger = logging.getLogger(__name__)

# Compatible alias; registry is the source of truth for registered bundle names.
BundleName = str

_MEMORY_CACHE: dict[tuple[str, str], tuple[pd.DataFrame, float]] = {}
_SYNC_LOCKS: dict[str, asyncio.Lock] = {}


def _get_sync_lock(dataset_id: str) -> asyncio.Lock:
    if dataset_id not in _SYNC_LOCKS:
        _SYNC_LOCKS[dataset_id] = asyncio.Lock()
    return _SYNC_LOCKS[dataset_id]


def get_mirror_root() -> Path:
    root = resolve_data_path(getattr(settings, "slocum_mirror_dir", Path("data_store/slocum_cache")))
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_dataset_dir(dataset_id: str) -> Path:
    safe_id = dataset_id.replace("/", "_").replace("\\", "_")
    path = get_mirror_root() / safe_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _parquet_path(dataset_id: str, bundle: BundleName) -> Path:
    spec = get_bundle_spec(bundle)
    return _safe_dataset_dir(dataset_id) / f"{spec.name}.parquet"


def _meta_path(dataset_id: str) -> Path:
    return _safe_dataset_dir(dataset_id) / "meta.json"


def is_historical_dataset(dataset_id: str) -> bool:
    """
    True when ``dataset_id`` is listed in config ``historical_slocum_datasets``,
    or shares a ``mission_key`` with any listed historical id (realtime/delayed siblings).
    """
    if not dataset_id or not str(dataset_id).strip():
        return False
    trimmed = str(dataset_id).strip()
    historical_ids = {s.strip() for s in settings.historical_slocum_datasets if s and s.strip()}
    if trimmed in historical_ids:
        return True
    key = slocum_mission_key(trimmed)
    if not key:
        return False
    historical_keys = {slocum_mission_key(hid) for hid in historical_ids if slocum_mission_key(hid)}
    return key in historical_keys


def _read_meta(dataset_id: str) -> dict[str, Any]:
    path = _meta_path(dataset_id)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as err:
        logger.warning("Failed to read Slocum mirror meta for %s: %s", dataset_id, err)
        return {}


def _write_meta(dataset_id: str, meta: dict[str, Any]) -> None:
    path = _meta_path(dataset_id)
    path.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def invalidate_memory_cache(dataset_id: Optional[str] = None) -> None:
    if dataset_id is None:
        _MEMORY_CACHE.clear()
        return
    keys_to_remove = [key for key in _MEMORY_CACHE if key[0] == dataset_id]
    for key in keys_to_remove:
        _MEMORY_CACHE.pop(key, None)


def _load_parquet_from_disk(dataset_id: str, bundle: BundleName) -> pd.DataFrame:
    path = _parquet_path(dataset_id, bundle)
    # Recover dirs left with only *.parquet.tmp after a failed rename.
    promote_orphan_tmp_file(path)
    if not path.is_file():
        return pd.DataFrame()
    try:
        df = pd.read_parquet(path)
        if "Timestamp" in df.columns:
            df["Timestamp"] = pd.to_datetime(df["Timestamp"], utc=True)
        return df
    except Exception as err:
        logger.warning("Failed to read Slocum mirror %s/%s: %s", dataset_id, bundle, err)
        return pd.DataFrame()


def load_mirror_df(dataset_id: str, bundle: BundleName) -> pd.DataFrame:
    """Load a mirror bundle with per-worker memory cache keyed by file mtime."""
    path = _parquet_path(dataset_id, bundle)
    cache_key = (dataset_id, bundle)
    mtime = path.stat().st_mtime if path.is_file() else 0.0
    cached = _MEMORY_CACHE.get(cache_key)
    if cached is not None and cached[1] == mtime:
        return cached[0].copy()
    df = _load_parquet_from_disk(dataset_id, bundle)
    # Re-stat after possible orphan promotion.
    mtime = path.stat().st_mtime if path.is_file() else 0.0
    _MEMORY_CACHE[cache_key] = (df.copy(), mtime)
    return df


def _save_parquet(dataset_id: str, bundle: BundleName, df: pd.DataFrame) -> None:
    if df.empty:
        return
    write_parquet_file_atomic(df, _parquet_path(dataset_id, bundle))
    invalidate_memory_cache(dataset_id)


def _merge_mirror_frames(existing: pd.DataFrame, new_rows: pd.DataFrame) -> pd.DataFrame:
    if existing is None or existing.empty:
        return new_rows.copy() if new_rows is not None else pd.DataFrame()
    if new_rows is None or new_rows.empty:
        return existing.copy()
    merged = pd.concat([existing, new_rows], ignore_index=True)
    if "Timestamp" not in merged.columns:
        return merged
    merged["Timestamp"] = pd.to_datetime(merged["Timestamp"], utc=True)
    merged = merged.drop_duplicates(subset=["Timestamp"], keep="last")
    return merged.sort_values("Timestamp").reset_index(drop=True)


def _trim_retention(df: pd.DataFrame, retention_hours: int) -> pd.DataFrame:
    if df.empty or "Timestamp" not in df.columns or retention_hours <= 0:
        return df
    max_ts = df["Timestamp"].max()
    if pd.isna(max_ts):
        return df
    cutoff = max_ts - pd.Timedelta(hours=retention_hours)
    return df.loc[df["Timestamp"] >= cutoff].reset_index(drop=True)


def _last_timestamp(df: pd.DataFrame) -> Optional[datetime]:
    if df.empty or "Timestamp" not in df.columns:
        return None
    max_ts = df["Timestamp"].max()
    if pd.isna(max_ts):
        return None
    if hasattr(max_ts, "to_pydatetime"):
        return max_ts.to_pydatetime().replace(tzinfo=timezone.utc)
    return pd.to_datetime(max_ts, utc=True).to_pydatetime()


def _iso_z(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _round_time_end(now: Optional[datetime] = None) -> datetime:
    time_end = now or datetime.now(timezone.utc)
    window_min = max(1, settings.slocum_cache_window_minutes)
    t = time_end.replace(second=0, microsecond=0)
    return t - timedelta(minutes=t.minute % window_min)


def _decimation_minutes_for_window(hours: float, *, is_historical: bool) -> Optional[int]:
    configured = getattr(settings, "slocum_erddap_decimation_minutes", 15)
    if configured <= 0:
        return None
    if is_historical or hours > 48:
        return configured
    return None


def clear_mirror_bundle(dataset_id: str, bundle: BundleName) -> bool:
    """Delete a mirror parquet file and drop its memory cache entry. Returns True if a file was removed."""
    path = _parquet_path(dataset_id, bundle)
    removed = False
    if path.is_file():
        path.unlink()
        removed = True
    invalidate_memory_cache(dataset_id)
    return removed


async def _fetch_raw_bundle(
    dataset_id: str,
    bundle: BundleName,
    time_start: str,
    time_end: str,
    decimation_minutes: Optional[int],
) -> pd.DataFrame:
    """Fetch and preprocess one registered bundle from ERDDAP."""
    spec = get_bundle_spec(bundle)
    effective_decimation = decimation_minutes if spec.allow_decimation else None
    raw = await asyncio.to_thread(
        fetch_slocum_data,
        dataset_id,
        time_start,
        time_end,
        list(spec.erddap_variables),
        None,
        False,
        effective_decimation,
    )
    return preprocess_bundle_df(spec.name, raw)


def _compute_sync_window(
    dataset_id: str,
    existing_df: pd.DataFrame,
    *,
    hours_back: int,
    is_historical: bool,
) -> tuple[str, str, Optional[int]]:
    overlap_hours = max(0, getattr(settings, "slocum_sync_overlap_hours", 2))
    retention_hours = max(hours_back, getattr(settings, "slocum_mirror_retention_hours", 72))

    if is_historical:
        _, max_dt = fetch_dataset_time_extent(dataset_id)
        if max_dt is None:
            raise ValueError(f"Could not determine time extent for historical dataset {dataset_id}")
        time_end = max_dt
        min_dt, _ = fetch_dataset_time_extent(dataset_id)
        if min_dt is not None:
            time_start = min_dt
        else:
            time_start = time_end - timedelta(hours=hours_back)
        decimation = _decimation_minutes_for_window(
            (time_end - time_start).total_seconds() / 3600,
            is_historical=True,
        )
        return _iso_z(time_start), _iso_z(time_end), decimation

    time_end = _round_time_end()
    last_ts = _last_timestamp(existing_df)
    if last_ts is not None:
        time_start = last_ts - timedelta(hours=overlap_hours)
    else:
        time_start = time_end - timedelta(hours=retention_hours)
    decimation = _decimation_minutes_for_window(retention_hours, is_historical=False)
    return _iso_z(time_start), _iso_z(time_end), decimation


async def sync_dataset_mirror(
    dataset_id: str,
    *,
    hours_back: Optional[int] = None,
    force: bool = False,
    rebuild_ctd: bool = False,
) -> dict[str, Any]:
    """
    Incrementally sync dashboard + CTD bundles for one dataset into the parquet mirror.

    When ``rebuild_ctd`` (or ``force``) is True, the CTD parquet is cleared and
    re-fetched for the full retention window without server-side decimation.
    """
    warm_hours = hours_back if hours_back is not None else getattr(settings, "slocum_warm_hours", 24)
    is_historical = is_historical_dataset(dataset_id)
    meta = _read_meta(dataset_id)
    if is_historical and meta.get("archived") and not force and not rebuild_ctd:
        return {"dataset_id": dataset_id, "skipped": True, "reason": "archived"}

    sync_summary: dict[str, Any] = {
        "dataset_id": dataset_id,
        "bundles": {},
        "sync_timestamp": datetime.now(timezone.utc).isoformat(),
    }

    do_rebuild_ctd = bool(rebuild_ctd or force)
    if do_rebuild_ctd and "ctd" in DEFAULT_MIRROR_BUNDLES:
        cleared = clear_mirror_bundle(dataset_id, "ctd")
        sync_summary["ctd_cleared"] = cleared

    # Rebuild any mirrored bundle whose schema version changed (e.g. checklist
    # switched off ERDDAP decimation so Plot-it can show every sample).
    stored_versions = meta.get("bundle_schema_versions") or {}
    if not isinstance(stored_versions, dict):
        stored_versions = {}
    rebuilt_for_schema: list[str] = []
    for bundle in DEFAULT_MIRROR_BUNDLES:
        if do_rebuild_ctd and bundle == "ctd":
            continue
        spec = get_bundle_spec(bundle)
        if stored_versions.get(bundle) == spec.schema_version:
            continue
        if clear_mirror_bundle(dataset_id, bundle):
            rebuilt_for_schema.append(bundle)
    if rebuilt_for_schema:
        sync_summary["schema_rebuild_cleared"] = rebuilt_for_schema

    for bundle in DEFAULT_MIRROR_BUNDLES:
        spec = get_bundle_spec(bundle)
        existing = load_mirror_df(dataset_id, bundle)
        # Full-window rebuild after clear uses empty existing → retention/historical span
        time_start, time_end, decimation = _compute_sync_window(
            dataset_id,
            existing,
            hours_back=warm_hours,
            is_historical=is_historical,
        )
        effective_decimation = decimation if spec.allow_decimation else None
        try:
            fetched = await _fetch_raw_bundle(dataset_id, bundle, time_start, time_end, effective_decimation)
        except Exception as err:
            logger.warning("SLOCUM MIRROR: fetch failed for %s/%s: %s", dataset_id, bundle, err)
            sync_summary["bundles"][bundle] = {
                "error": str(err),
                "decimation_minutes": effective_decimation,
            }
            continue

        merged = _merge_mirror_frames(existing, fetched)
        if not is_historical:
            merged = _trim_retention(merged, getattr(settings, "slocum_mirror_retention_hours", 72))
        try:
            await asyncio.to_thread(_save_parquet, dataset_id, bundle, merged)
        except (PermissionError, OSError) as err:
            # Do not fail the whole sync/request: serve existing mirror bytes.
            logger.warning(
                "SLOCUM MIRROR: could not write %s/%s: %s",
                dataset_id,
                bundle,
                err,
            )
            sync_summary["bundles"][bundle] = {
                "error": f"write_failed: {err}",
                "fetched_rows": len(fetched),
                "decimation_minutes": effective_decimation,
            }
            continue
        last_ts = _last_timestamp(merged)
        sync_summary["bundles"][bundle] = {
            "rows": len(merged),
            "last_data_timestamp": last_ts.isoformat() if last_ts else None,
            "fetched_rows": len(fetched),
            "decimation_minutes": effective_decimation,
            "time_start": time_start,
            "time_end": time_end,
        }

    meta.update(
        {
            "dataset_id": dataset_id,
            "is_historical": is_historical,
            "last_sync_timestamp": sync_summary["sync_timestamp"],
            "archived": is_historical,
            "bundle_schema_versions": {
                name: get_bundle_spec(name).schema_version for name in DEFAULT_MIRROR_BUNDLES
            },
        }
    )
    latest_ts: Optional[datetime] = None
    for bundle in DEFAULT_MIRROR_BUNDLES:
        bundle_last = _last_timestamp(load_mirror_df(dataset_id, bundle))
        if bundle_last and (latest_ts is None or bundle_last > latest_ts):
            latest_ts = bundle_last
    if latest_ts:
        meta["last_data_timestamp"] = latest_ts.isoformat()
    _write_meta(dataset_id, meta)
    return sync_summary


def inspect_mirror_dataset(dataset_id: str, *, hours_back: int = 72) -> dict[str, Any]:
    """
    Admin diagnostics for mirror parquet bundles: row counts, column non-nulls,
    sliced time ranges, and CTD science/profile availability.
    """
    from ..core.slocum_cache_service import slice_processed_df

    meta = _read_meta(dataset_id)
    hours = max(1, min(8760, int(hours_back or 72)))
    bundles_out: dict[str, Any] = {}

    for bundle in list_bundle_names():
        path = _parquet_path(dataset_id, bundle)
        df = load_mirror_df(dataset_id, bundle) if path.is_file() else pd.DataFrame()
        file_mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc) if path.is_file() else None
        sliced = (
            slice_processed_df(df, hours_back=hours, use_date_range=False, time_start_str=None, time_end_str=None)
            if not df.empty
            else pd.DataFrame()
        )
        col_counts: dict[str, int] = {}
        for col in sliced.columns:
            if col == "Timestamp":
                continue
            col_counts[col] = int(pd.to_numeric(sliced[col], errors="coerce").notna().sum()) if col in sliced.columns else 0

        first_ts = sliced["Timestamp"].min() if not sliced.empty and "Timestamp" in sliced.columns else None
        last_ts = sliced["Timestamp"].max() if not sliced.empty and "Timestamp" in sliced.columns else None
        entry: dict[str, Any] = {
            "cached": path.is_file(),
            "file_modification_time": file_mtime.isoformat() if file_mtime else None,
            "mirror_rows": len(df),
            "rows_in_window": len(sliced),
            "hours_back": hours,
            "time_start": first_ts.isoformat() if first_ts is not None and not pd.isna(first_ts) else None,
            "time_end": last_ts.isoformat() if last_ts is not None and not pd.isna(last_ts) else None,
            "column_nonnull": col_counts,
        }
        if bundle == "ctd" and not sliced.empty:
            science_cols = [c for c in ("Temperature", "Conductivity", "Density", "Salinity") if c in sliced.columns]
            if science_cols:
                science_mask = sliced[science_cols].apply(pd.to_numeric, errors="coerce").notna().any(axis=1)
                entry["science_rows"] = int(science_mask.sum())
            else:
                entry["science_rows"] = 0
            depth_nonnull = int(pd.to_numeric(sliced["Depth"], errors="coerce").notna().sum()) if "Depth" in sliced.columns else 0
            pressure_nonnull = int(pd.to_numeric(sliced["Pressure"], errors="coerce").notna().sum()) if "Pressure" in sliced.columns else 0
            entry["depth_nonnull"] = depth_nonnull
            entry["pressure_nonnull"] = pressure_nonnull
        bundles_out[bundle] = entry

    return {
        "dataset_id": dataset_id,
        "is_historical": is_historical_dataset(dataset_id),
        "meta": meta,
        "bundles": bundles_out,
    }


async def ensure_mirror_synced(
    dataset_id: str,
    *,
    hours_back: Optional[int] = None,
    max_stale_seconds: int = 300,
) -> None:
    """Sync mirror when missing or stale (used on read path for cold starts)."""
    meta = _read_meta(dataset_id)
    dashboard_path = _parquet_path(dataset_id, "dashboard")
    if not dashboard_path.is_file():
        await sync_dataset_mirror(dataset_id, hours_back=hours_back, force=True)
        return
    last_sync = meta.get("last_sync_timestamp")
    if not last_sync:
        await sync_dataset_mirror(dataset_id, hours_back=hours_back)
        return
    try:
        last_sync_dt = datetime.fromisoformat(last_sync.replace("Z", "+00:00"))
    except ValueError:
        await sync_dataset_mirror(dataset_id, hours_back=hours_back)
        return
    age_seconds = (datetime.now(timezone.utc) - last_sync_dt.astimezone(timezone.utc)).total_seconds()
    if age_seconds > max_stale_seconds and not is_historical_dataset(dataset_id):
        async with _get_sync_lock(dataset_id):
            meta = _read_meta(dataset_id)
            last_sync = meta.get("last_sync_timestamp")
            if last_sync:
                try:
                    last_sync_dt = datetime.fromisoformat(last_sync.replace("Z", "+00:00"))
                    age_seconds = (datetime.now(timezone.utc) - last_sync_dt.astimezone(timezone.utc)).total_seconds()
                except ValueError:
                    age_seconds = max_stale_seconds + 1
            if age_seconds > max_stale_seconds:
                await sync_dataset_mirror(dataset_id, hours_back=hours_back)


async def sync_active_slocum_mirrors(hours_back: Optional[int] = None) -> int:
    """Sync all configured active + historical datasets (leader scheduler job)."""
    dataset_ids = [
        d.strip()
        for d in (*settings.active_slocum_datasets, *settings.historical_slocum_datasets)
        if d and d.strip()
    ]
    synced = 0
    warm_hours = hours_back if hours_back is not None else getattr(settings, "slocum_warm_hours", 24)
    for dataset_id in dataset_ids:
        try:
            await sync_dataset_mirror(dataset_id, hours_back=warm_hours)
            synced += 1
        except Exception as err:
            logger.warning("SLOCUM MIRROR: sync failed for %s: %s", dataset_id, err)
    return synced


def get_mirror_cache_status(dataset_id: str) -> dict[str, Any]:
    """Return cache status for registered mirror bundles."""
    meta = _read_meta(dataset_id)
    status: dict[str, Any] = {}
    for bundle in list_bundle_names():
        path = _parquet_path(dataset_id, bundle)
        df = load_mirror_df(dataset_id, bundle) if path.is_file() else pd.DataFrame()
        last_ts = _last_timestamp(df)
        file_mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc) if path.is_file() else None
        status[bundle] = {
            "cached": path.is_file(),
            "cache_timestamp": file_mtime.isoformat() if file_mtime else None,
            "last_data_timestamp": last_ts.isoformat() if last_ts else meta.get("last_data_timestamp"),
            "row_count": len(df),
        }
    return status


def _safe_dataset_id(dataset_id: str) -> str:
    return dataset_id.replace("/", "_").replace("\\", "_")


def configured_mirror_dataset_ids() -> set[str]:
    """Safe directory names for datasets still listed in active/historical config."""
    return {
        _safe_dataset_id(dataset_id.strip())
        for dataset_id in (*settings.active_slocum_datasets, *settings.historical_slocum_datasets)
        if dataset_id and dataset_id.strip()
    }


def purge_orphan_mirrors() -> dict[str, Any]:
    """
    Remove slocum_cache directories for dataset IDs no longer in active/historical config.

    Does not delete mirrors for datasets still configured (including full historical
    CTD mirrors). Safe to run on the overage-cleanup cadence.
    """
    root = getattr(settings, "slocum_mirror_dir", Path("data_store/slocum_cache"))
    if not root.is_dir():
        return {"removed_dirs": 0, "freed_bytes": 0, "removed_dataset_ids": []}

    keep = configured_mirror_dataset_ids()
    removed_ids: list[str] = []
    freed_bytes = 0

    for path in sorted(root.iterdir(), key=lambda p: p.name):
        if not path.is_dir():
            continue
        if path.name in keep:
            continue
        dir_freed = 0
        try:
            for child in path.rglob("*"):
                if child.is_file():
                    try:
                        dir_freed += child.stat().st_size
                        child.unlink()
                    except OSError as err:
                        logger.warning("Failed to remove orphan mirror file %s: %s", child, err)
            # Remove nested dirs then the dataset dir
            for child in sorted(path.rglob("*"), key=lambda p: len(p.parts), reverse=True):
                if child.is_dir():
                    try:
                        child.rmdir()
                    except OSError:
                        pass
            path.rmdir()
        except OSError as err:
            logger.warning("Failed to remove orphan mirror dir %s: %s", path, err)
            continue
        invalidate_memory_cache(path.name)
        removed_ids.append(path.name)
        freed_bytes += dir_freed
        logger.info("SLOCUM MIRROR: removed orphan dataset dir %s (freed_bytes=%s)", path.name, dir_freed)

    return {
        "removed_dirs": len(removed_ids),
        "freed_bytes": freed_bytes,
        "removed_dataset_ids": removed_ids,
    }


def dashboard_df_to_track_df(dashboard_df: pd.DataFrame) -> pd.DataFrame:
    """Extract map-ready track columns from a processed dashboard DataFrame."""
    if dashboard_df is None or dashboard_df.empty:
        return pd.DataFrame(columns=["Timestamp", "Latitude", "Longitude", "Depth"])
    cols = ["Timestamp"]
    rename: dict[str, str] = {}
    if "Latitude" in dashboard_df.columns:
        cols.append("Latitude")
    if "Longitude" in dashboard_df.columns:
        cols.append("Longitude")
    depth_col = "MDepth" if "MDepth" in dashboard_df.columns else None
    if depth_col:
        cols.append(depth_col)
    track = dashboard_df.loc[:, [c for c in cols if c in dashboard_df.columns]].copy()
    if depth_col:
        track = track.rename(columns={depth_col: "Depth"})
    elif "Depth" not in track.columns:
        track["Depth"] = pd.NA
    if "Latitude" in track.columns and "Longitude" in track.columns:
        track = mask_null_island_coordinates(track)
    return track.dropna(subset=["Latitude", "Longitude"], how="any")
