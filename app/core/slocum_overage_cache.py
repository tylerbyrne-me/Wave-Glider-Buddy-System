"""
Shared-disk 24-hour overage cache for Slocum requests outside the rolling mirror.

Sensor/data-type agnostic: bundles are identified by the registry name
(dashboard, ctd, future sensors). Interactive windows up to 31 days reuse a
normalized full-window parquet entry for TTL hours; reports may request full
deployment windows. Expired entries are never served; a leader cleanup job
removes them from disk.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Literal, Optional

import pandas as pd

from ..config import settings
from ..core.slocum_bundle_registry import get_bundle_spec
from ..core.slocum_mirror_service import (
    _decimation_minutes_for_window,
    _fetch_raw_bundle,
    _last_timestamp,
    _merge_mirror_frames,
    ensure_mirror_synced,
    load_mirror_df,
)
from ..core.utils import cross_process_file_lock, replace_path_with_retries

logger = logging.getLogger(__name__)

RequestContext = Literal["interactive", "report"]
DataSource = Literal["mirror", "overage_cache", "erddap_overage"]

_IN_FLIGHT: dict[str, asyncio.Task] = {}
_IN_FLIGHT_LOCK: asyncio.Lock | None = None
_STATS = {
    "hits": 0,
    "misses": 0,
    "fetches": 0,
    "expired_reads": 0,
    "evictions": 0,
}


@dataclass(frozen=True)
class OverageRequest:
    dataset_id: str
    bundle: str
    start_utc: datetime
    end_utc: datetime
    context: RequestContext = "interactive"


@dataclass
class OverageResult:
    df: pd.DataFrame
    metadata: dict[str, Any]


class OverageRangeError(ValueError):
    """Raised when an interactive request exceeds configured max days."""


def _get_in_flight_lock() -> asyncio.Lock:
    global _IN_FLIGHT_LOCK
    if _IN_FLIGHT_LOCK is None:
        _IN_FLIGHT_LOCK = asyncio.Lock()
    return _IN_FLIGHT_LOCK


def get_overage_root() -> Path:
    root = Path(getattr(settings, "slocum_overage_cache_dir", Path("data_store/slocum_overage_cache")))
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_id(value: str) -> str:
    return value.replace("/", "_").replace("\\", "_").strip()


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def normalize_overage_window(start_utc: datetime, end_utc: datetime) -> tuple[datetime, datetime]:
    """Snap the complete requested window to UTC hour boundaries (inclusive floor/ceil)."""
    start = _ensure_utc(start_utc).replace(minute=0, second=0, microsecond=0)
    end = _ensure_utc(end_utc)
    # Ceil to next hour unless already on the hour
    if end.minute or end.second or end.microsecond:
        end = (end.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))
    else:
        end = end.replace(minute=0, second=0, microsecond=0)
    if end <= start:
        end = start + timedelta(hours=1)
    return start, end


def _iso_z(dt: datetime) -> str:
    return _ensure_utc(dt).strftime("%Y-%m-%dT%H:%M:%SZ")


def validate_overage_request(request: OverageRequest) -> tuple[datetime, datetime]:
    """Validate bounds and interactive max days; return normalized window."""
    start = _ensure_utc(request.start_utc)
    end = _ensure_utc(request.end_utc)
    if end <= start:
        raise OverageRangeError("end_utc must be after start_utc.")
    span_days = (end - start).total_seconds() / 86400.0
    max_days = int(getattr(settings, "slocum_overage_interactive_max_days", 31))
    if request.context == "interactive" and span_days > max_days + 1e-9:
        raise OverageRangeError(
            f"Interactive requests are limited to {max_days} days. "
            f"Requested window is {span_days:.1f} days. Use a shorter range or a report job."
        )
    get_bundle_spec(request.bundle)  # validates bundle name
    return normalize_overage_window(start, end)


def build_overage_cache_key(
    dataset_id: str,
    bundle: str,
    norm_start: datetime,
    norm_end: datetime,
    *,
    decimation_minutes: Optional[int],
) -> str:
    spec = get_bundle_spec(bundle)
    payload = "|".join(
        [
            dataset_id.strip(),
            spec.name,
            _iso_z(norm_start),
            _iso_z(norm_end),
            spec.schema_version,
            str(decimation_minutes if decimation_minutes else 0),
            "allow_decimation" if spec.allow_decimation else "no_decimation",
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _bundle_dir(dataset_id: str, bundle: str) -> Path:
    path = get_overage_root() / _safe_id(dataset_id) / get_bundle_spec(bundle).name
    path.mkdir(parents=True, exist_ok=True)
    return path


def _entry_paths(dataset_id: str, bundle: str, cache_key: str) -> tuple[Path, Path, Path]:
    base = _bundle_dir(dataset_id, bundle) / cache_key
    return base.with_suffix(".parquet"), base.with_suffix(".json"), base.with_suffix(".lock")


def _ttl_hours() -> int:
    return max(1, int(getattr(settings, "slocum_overage_ttl_hours", 24)))


def _max_bytes() -> int:
    return max(0, int(getattr(settings, "slocum_overage_max_bytes", 10 * 1024 * 1024 * 1024)))


def _read_sidecar(meta_path: Path) -> Optional[dict[str, Any]]:
    if not meta_path.is_file():
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception as err:
        logger.warning("Corrupt overage sidecar %s: %s", meta_path, err)
        return None


def _is_entry_valid(meta: dict[str, Any], *, now: Optional[datetime] = None) -> bool:
    now = now or datetime.now(timezone.utc)
    expires_raw = meta.get("expires_at")
    if not expires_raw:
        return False
    try:
        expires = datetime.fromisoformat(str(expires_raw).replace("Z", "+00:00"))
    except ValueError:
        return False
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires > now.astimezone(timezone.utc)


def _load_cached_entry(parquet_path: Path, meta_path: Path) -> Optional[tuple[pd.DataFrame, dict[str, Any]]]:
    meta = _read_sidecar(meta_path)
    if meta is None or not parquet_path.is_file():
        return None
    if not _is_entry_valid(meta):
        _STATS["expired_reads"] += 1
        return None
    try:
        df = pd.read_parquet(parquet_path)
        if "Timestamp" in df.columns:
            df["Timestamp"] = pd.to_datetime(df["Timestamp"], utc=True)
        return df, meta
    except Exception as err:
        logger.warning("Failed to read overage parquet %s: %s", parquet_path, err)
        return None


def _atomic_write_entry(
    parquet_path: Path,
    meta_path: Path,
    df: pd.DataFrame,
    meta: dict[str, Any],
) -> None:
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_parquet = parquet_path.with_suffix(".parquet.tmp")
    tmp_meta = meta_path.with_suffix(".json.tmp")
    df.to_parquet(tmp_parquet, index=False)
    byte_size = tmp_parquet.stat().st_size
    meta = {**meta, "byte_size": byte_size, "row_count": int(len(df))}
    tmp_meta.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    replace_path_with_retries(tmp_parquet, parquet_path)
    replace_path_with_retries(tmp_meta, meta_path)


def mirror_covers_window(dataset_id: str, bundle: str, start_utc: datetime, end_utc: datetime) -> bool:
    """True when the rolling mirror has rows spanning the full requested interval."""
    df = load_mirror_df(dataset_id, bundle)
    if df.empty or "Timestamp" not in df.columns:
        return False
    ts = pd.to_datetime(df["Timestamp"], utc=True)
    mirror_min = ts.min()
    mirror_max = ts.max()
    if pd.isna(mirror_min) or pd.isna(mirror_max):
        return False
    start = _ensure_utc(start_utc)
    end = _ensure_utc(end_utc)
    # Small grace (1 minute) for rounding differences at mirror edges.
    grace = timedelta(minutes=1)
    return mirror_min <= (start + grace) and mirror_max >= (end - grace)


def _slice_df(df: pd.DataFrame, start_utc: datetime, end_utc: datetime) -> pd.DataFrame:
    if df is None or df.empty or "Timestamp" not in df.columns:
        return pd.DataFrame()
    out = df.copy()
    out["Timestamp"] = pd.to_datetime(out["Timestamp"], utc=True)
    start = _ensure_utc(start_utc)
    end = _ensure_utc(end_utc)
    mask = (out["Timestamp"] >= start) & (out["Timestamp"] <= end)
    return out.loc[mask].sort_values("Timestamp").reset_index(drop=True)


def _decimation_for_request(bundle: str, start: datetime, end: datetime) -> Optional[int]:
    spec = get_bundle_spec(bundle)
    if not spec.allow_decimation:
        return None
    hours = max(0.0, (_ensure_utc(end) - _ensure_utc(start)).total_seconds() / 3600.0)
    return _decimation_minutes_for_window(hours, is_historical=hours > 48)


async def _fetch_overage_window(
    dataset_id: str,
    bundle: str,
    norm_start: datetime,
    norm_end: datetime,
    decimation_minutes: Optional[int],
) -> pd.DataFrame:
    return await _fetch_raw_bundle(
        dataset_id,
        bundle,
        _iso_z(norm_start),
        _iso_z(norm_end),
        decimation_minutes,
    )


def _merge_for_response(
    mirror_df: pd.DataFrame,
    overage_df: pd.DataFrame,
    start_utc: datetime,
    end_utc: datetime,
) -> pd.DataFrame:
    merged = _merge_mirror_frames(mirror_df, overage_df)
    return _slice_df(merged, start_utc, end_utc)


def _iter_sidecars() -> Iterator[Path]:
    root = get_overage_root()
    if not root.is_dir():
        return iter(())
    return root.rglob("*.json")


def list_overage_entries(dataset_id: Optional[str] = None) -> list[dict[str, Any]]:
    """List overage sidecars (valid and expired) for admin/status APIs."""
    entries: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    for meta_path in _iter_sidecars():
        if meta_path.name.endswith(".tmp"):
            continue
        meta = _read_sidecar(meta_path)
        if not meta:
            continue
        if dataset_id and meta.get("dataset_id") != dataset_id:
            continue
        parquet_path = meta_path.with_suffix(".parquet")
        entry = {
            **meta,
            "meta_path": str(meta_path),
            "parquet_path": str(parquet_path),
            "exists": parquet_path.is_file(),
            "expired": not _is_entry_valid(meta, now=now),
        }
        entries.append(entry)
    entries.sort(key=lambda e: str(e.get("expires_at") or ""), reverse=True)
    return entries


def get_overage_cache_status(dataset_id: Optional[str] = None) -> dict[str, Any]:
    entries = list_overage_entries(dataset_id)
    total_bytes = sum(int(e.get("byte_size") or 0) for e in entries if e.get("exists") and not e.get("expired"))
    valid = [e for e in entries if not e.get("expired") and e.get("exists")]
    return {
        "cache_dir": str(get_overage_root()),
        "ttl_hours": _ttl_hours(),
        "max_bytes": _max_bytes(),
        "entry_count": len(valid),
        "expired_count": sum(1 for e in entries if e.get("expired")),
        "total_bytes": total_bytes,
        "stats": dict(_STATS),
        "entries": entries if dataset_id else entries[:100],
    }


def purge_overage_entries(
    *,
    dataset_id: Optional[str] = None,
    force_all: bool = False,
) -> dict[str, Any]:
    """Remove expired/corrupt/orphan entries; optionally wipe all for a dataset."""
    removed = 0
    freed = 0
    now = datetime.now(timezone.utc)
    root = get_overage_root()
    for meta_path in list(_iter_sidecars()):
        if meta_path.name.endswith(".tmp"):
            continue
        meta = _read_sidecar(meta_path)
        parquet_path = meta_path.with_suffix(".parquet")
        lock_path = meta_path.with_suffix(".lock")
        should_remove = False
        if meta is None:
            should_remove = True
        elif dataset_id and meta.get("dataset_id") != dataset_id:
            continue
        elif force_all and (dataset_id is None or meta.get("dataset_id") == dataset_id):
            should_remove = True
        elif not _is_entry_valid(meta, now=now):
            should_remove = True
        elif not parquet_path.is_file():
            should_remove = True
        if should_remove:
            for path in (parquet_path, meta_path, lock_path):
                if path.is_file():
                    try:
                        size = path.stat().st_size if path.suffix == ".parquet" else 0
                        path.unlink()
                        removed += 1
                        freed += size
                        _STATS["evictions"] += 1
                    except OSError as err:
                        logger.warning("Failed to remove overage file %s: %s", path, err)

    # Remove orphan tmp files and empty dirs
    if root.is_dir():
        for tmp in root.rglob("*.tmp"):
            try:
                tmp.unlink()
                removed += 1
            except OSError:
                pass
        for dirpath, dirnames, filenames in os.walk(root, topdown=False):
            if not dirnames and not filenames:
                try:
                    Path(dirpath).rmdir()
                except OSError:
                    pass

    enforce_overage_quota()
    return {"removed_files": removed, "freed_bytes": freed, "status": get_overage_cache_status(dataset_id)}


def enforce_overage_quota() -> int:
    """Evict oldest-expiring valid entries until under max_bytes. Returns files removed."""
    max_bytes = _max_bytes()
    if max_bytes <= 0:
        return 0
    entries = [e for e in list_overage_entries() if not e.get("expired") and e.get("exists")]
    total = sum(int(e.get("byte_size") or 0) for e in entries)
    if total <= max_bytes:
        return 0
    # Evict soonest-to-expire first
    entries.sort(key=lambda e: str(e.get("expires_at") or ""))
    removed = 0
    for entry in entries:
        if total <= max_bytes:
            break
        for key in ("parquet_path", "meta_path"):
            path = Path(entry[key])
            if path.is_file():
                size = path.stat().st_size if path.suffix == ".parquet" else 0
                try:
                    path.unlink()
                    total -= size
                    removed += 1
                    _STATS["evictions"] += 1
                except OSError:
                    pass
        lock_path = Path(entry["meta_path"]).with_suffix(".lock")
        if lock_path.is_file():
            try:
                lock_path.unlink()
            except OSError:
                pass
    return removed


async def get_bundle_dataframe(
    request: OverageRequest,
    *,
    ensure_mirror: bool = True,
) -> OverageResult:
    """
    Return a DataFrame covering the requested window using:
    1) rolling mirror when it fully covers the window
    2) shared 24h overage cache for normalized windows
    3) bounded ERDDAP fetch written into the overage cache
    """
    requested_start = _ensure_utc(request.start_utc)
    requested_end = _ensure_utc(request.end_utc)
    norm_start, norm_end = validate_overage_request(request)
    bundle = get_bundle_spec(request.bundle).name
    dataset_id = request.dataset_id

    if ensure_mirror:
        try:
            await ensure_mirror_synced(dataset_id, hours_back=getattr(settings, "slocum_warm_hours", 24))
        except Exception as err:
            logger.warning("Mirror sync before overage load failed for %s: %s", dataset_id, err)

    mirror_df = load_mirror_df(dataset_id, bundle)
    if mirror_covers_window(dataset_id, bundle, requested_start, requested_end):
        sliced = _slice_df(mirror_df, requested_start, requested_end)
        return OverageResult(
            df=sliced,
            metadata={
                "data_source": "mirror",
                "dataset_id": dataset_id,
                "bundle": bundle,
                "requested_range": {"start": _iso_z(requested_start), "end": _iso_z(requested_end)},
                "normalized_range": {"start": _iso_z(norm_start), "end": _iso_z(norm_end)},
                "cache_created_at": None,
                "cache_expires_at": None,
                "row_count": len(sliced),
            },
        )

    decimation = _decimation_for_request(bundle, norm_start, norm_end)
    cache_key = build_overage_cache_key(
        dataset_id, bundle, norm_start, norm_end, decimation_minutes=decimation
    )
    parquet_path, meta_path, lock_path = _entry_paths(dataset_id, bundle, cache_key)

    cached = _load_cached_entry(parquet_path, meta_path)
    if cached is not None:
        _STATS["hits"] += 1
        overage_df, meta = cached
        merged = _merge_for_response(mirror_df, overage_df, requested_start, requested_end)
        return OverageResult(
            df=merged,
            metadata={
                "data_source": "overage_cache",
                "dataset_id": dataset_id,
                "bundle": bundle,
                "requested_range": {"start": _iso_z(requested_start), "end": _iso_z(requested_end)},
                "normalized_range": {"start": _iso_z(norm_start), "end": _iso_z(norm_end)},
                "cache_key": cache_key,
                "cache_created_at": meta.get("created_at"),
                "cache_expires_at": meta.get("expires_at"),
                "row_count": len(merged),
            },
        )

    _STATS["misses"] += 1

    async with _get_in_flight_lock():
        task = _IN_FLIGHT.get(cache_key)
        if task is None:
            task = asyncio.create_task(
                _populate_overage_entry(
                    dataset_id=dataset_id,
                    bundle=bundle,
                    norm_start=norm_start,
                    norm_end=norm_end,
                    decimation_minutes=decimation,
                    cache_key=cache_key,
                    parquet_path=parquet_path,
                    meta_path=meta_path,
                    lock_path=lock_path,
                    context=request.context,
                )
            )
            _IN_FLIGHT[cache_key] = task

    try:
        overage_df, meta = await task
    finally:
        async with _get_in_flight_lock():
            current = _IN_FLIGHT.get(cache_key)
            if current is task:
                _IN_FLIGHT.pop(cache_key, None)

    merged = _merge_for_response(mirror_df, overage_df, requested_start, requested_end)
    return OverageResult(
        df=merged,
        metadata={
            "data_source": meta.get("populated_from", "erddap_overage"),
            "dataset_id": dataset_id,
            "bundle": bundle,
            "requested_range": {"start": _iso_z(requested_start), "end": _iso_z(requested_end)},
            "normalized_range": {"start": _iso_z(norm_start), "end": _iso_z(norm_end)},
            "cache_key": cache_key,
            "cache_created_at": meta.get("created_at"),
            "cache_expires_at": meta.get("expires_at"),
            "row_count": len(merged),
        },
    )


async def _populate_overage_entry(
    *,
    dataset_id: str,
    bundle: str,
    norm_start: datetime,
    norm_end: datetime,
    decimation_minutes: Optional[int],
    cache_key: str,
    parquet_path: Path,
    meta_path: Path,
    lock_path: Path,
    context: RequestContext,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    # Acquire cross-process lock, then re-check disk before hitting ERDDAP.
    def _precheck() -> Optional[tuple[pd.DataFrame, dict[str, Any]]]:
        with cross_process_file_lock(lock_path):
            cached = _load_cached_entry(parquet_path, meta_path)
            if cached is not None:
                _STATS["hits"] += 1
                df, meta = cached
                return df, {**meta, "populated_from": "overage_cache"}
            return None

    try:
        existing = await asyncio.to_thread(_precheck)
    except TimeoutError:
        logger.warning("Overage lock timeout for %s/%s; continuing with fetch", dataset_id, bundle)
        existing = None
    if existing is not None:
        return existing

    _STATS["fetches"] += 1
    fetched = await _fetch_overage_window(
        dataset_id, bundle, norm_start, norm_end, decimation_minutes
    )
    if fetched is None:
        fetched = pd.DataFrame()
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=_ttl_hours())
    meta = {
        "dataset_id": dataset_id,
        "bundle": bundle,
        "cache_key": cache_key,
        "normalized_start": _iso_z(norm_start),
        "normalized_end": _iso_z(norm_end),
        "decimation_minutes": decimation_minutes,
        "schema_version": get_bundle_spec(bundle).schema_version,
        "context": context,
        "created_at": now.isoformat(),
        "expires_at": expires.isoformat(),
        "source": "erddap",
        "populated_from": "erddap_overage",
        "last_data_timestamp": (
            _last_timestamp(fetched).isoformat() if _last_timestamp(fetched) else None
        ),
    }

    def _locked_write() -> tuple[pd.DataFrame, dict[str, Any]]:
        with cross_process_file_lock(lock_path):
            cached = _load_cached_entry(parquet_path, meta_path)
            if cached is not None:
                df, existing_meta = cached
                return df, {**existing_meta, "populated_from": "overage_cache"}
            if fetched.empty:
                return fetched, {**meta, "row_count": 0, "byte_size": 0}
            _atomic_write_entry(parquet_path, meta_path, fetched, meta)
            enforce_overage_quota()
            return fetched, meta

    return await asyncio.to_thread(_locked_write)


async def resolve_time_window_dataframe(
    *,
    dataset_id: str,
    bundle: str,
    hours_back: int,
    is_historical: bool,
    start_date: Optional[str],
    end_date: Optional[str],
    context: RequestContext = "interactive",
) -> OverageResult:
    """Convenience wrapper used by routers: parse window then load via overage/mirror."""
    from ..core.slocum_cache_service import parse_slocum_time_window

    time_start_str, time_end_str, use_date_range = parse_slocum_time_window(
        dataset_id, hours_back, is_historical, start_date, end_date
    )
    if not time_start_str or not time_end_str:
        raise OverageRangeError("Could not resolve a bounded time window for this request.")
    start = datetime.fromisoformat(time_start_str.replace("Z", "+00:00"))
    end = datetime.fromisoformat(time_end_str.replace("Z", "+00:00"))
    # When hours_back mode was used, parse_slocum_time_window already bounded the window.
    # For historical hours_back, end may be dataset max time.
    request = OverageRequest(
        dataset_id=dataset_id,
        bundle=bundle,
        start_utc=start,
        end_utc=end,
        context=context,
    )
    result = await get_bundle_dataframe(request)
    result.metadata["use_date_range"] = use_date_range
    result.metadata["hours_back"] = hours_back
    return result
