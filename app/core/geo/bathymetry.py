"""ETOPO 2022 bathymetry fetch and contour helpers for PDF telemetry maps.

Data source: NOAA NCEI ETOPO 2022 via ERDDAP griddap (dataset ETOPO_2022_v1_15s,
variable z). Only the map bounding box is requested; results are cached under
data_store/bathy_cache/ as .npz files. Longitudes are converted to 0-360 for
the ERDDAP query and back to -180..180 for Cartopy plotting.

Disable contours with feature toggle report_bathymetry_contours=false.
Disk cleanup (TTL + size quota) mirrors weather_map_cache.
"""

from __future__ import annotations

import logging
import math
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, List, Optional

import numpy as np
import pandas as pd
from erddapy import ERDDAP

from ...config import settings

logger = logging.getLogger(__name__)

ETOPO_DEG_STEP = 0.004166667
BATHY_BBOX_PAD_DEG = 0.02
# Half-width of the tiny fallback bbox used by point depth sampling (°).
POINT_DEPTH_HALF_WIDTH_DEG = 0.01
_CACHE_FILENAME_RE = re.compile(
    r"^bathy_(-?\d+(?:\.\d+)?)_(-?\d+(?:\.\d+)?)_(-?\d+(?:\.\d+)?)_(-?\d+(?:\.\d+)?)_(\d+)\.npz$"
)
OCEAN_DEPTH_LEVELS_M = (
    -10,
    -20,
    -50,
    -100,
    -150,
    -200,
    -250,
    -500,
    -750,
    -1000,
    -1500,
    -2000,
    -3000,
    -4000,
    -5000,
)

_cleanup_stats: dict[str, Any] = {
    "last_cleanup_at": None,
    "last_cleanup_summary": None,
}


@dataclass(frozen=True)
class BathyGrid:
    """1-D lon/lat axes and 2-D elevation grid (lat x lon)."""

    longitude: np.ndarray
    latitude: np.ndarray
    z: np.ndarray


def get_bathy_cache_dir() -> Path:
    return Path(getattr(settings, "bathy_cache_dir", Path("data_store/bathy_cache")))


# Backwards-compatible alias for callers/tests that imported the constant.
BATHY_CACHE_DIR = Path("data_store/bathy_cache")


def lon_to_360(lon: float) -> float:
    """Convert longitude to ERDDAP ETOPO 0-360 domain."""
    normalized = lon % 360.0
    return normalized if normalized >= 0 else normalized + 360.0


def lon_to_180(lon: float) -> float:
    """Convert ERDDAP 0-360 longitude back to -180..180 for plotting."""
    normalized = lon % 360.0
    return normalized if normalized <= 180.0 else normalized - 360.0


def bathy_query_bounds(extent: List[float]) -> dict[str, float]:
    """Return padded lat/lon query bounds in -180..180 for the map extent."""
    west, east, south, north = extent
    pad = BATHY_BBOX_PAD_DEG
    return {
        "west": west - pad,
        "east": east + pad,
        "south": south - pad,
        "north": north + pad,
    }


def choose_stride(extent: List[float], *, max_points: int = 400) -> int:
    """Pick griddap index stride so the returned grid stays near max_points per axis."""
    west, east, south, north = extent
    lon_span = max(east - west, 1e-6)
    lat_span = max(north - south, 1e-6)
    n_lat = lat_span / ETOPO_DEG_STEP
    n_lon = lon_span / ETOPO_DEG_STEP
    max_n = max(n_lat, n_lon, 1.0)
    return max(1, int(math.ceil(max_n / max_points)))


def nice_contour_levels(zmin: float, zmax: float, *, target: int = 8) -> list[float]:
    """Return standard ocean depth contour levels (negative meters) within z range."""
    if zmax >= 0:
        zmax = min(zmax, -1.0)
    if zmin >= 0 or zmax >= 0:
        return []

    levels = [level for level in OCEAN_DEPTH_LEVELS_M if zmin <= level <= zmax]
    if len(levels) <= target:
        return sorted(levels)

    step = max(1, len(levels) // target)
    thinned = levels[::step]
    if thinned[-1] != levels[-1]:
        thinned.append(levels[-1])
    return sorted(thinned)


def _column_name(df: pd.DataFrame, prefix: str) -> str:
    matches = [col for col in df.columns if col.lower().startswith(prefix)]
    if not matches:
        raise KeyError(f"No column starting with {prefix!r} in {list(df.columns)}")
    return matches[0]


def _pivot_griddap_dataframe(df: pd.DataFrame) -> BathyGrid:
    lat_col = _column_name(df, "latitude")
    lon_col = _column_name(df, "longitude")
    z_col = "z" if "z" in df.columns else _column_name(df, "z")

    pivot = df.pivot(index=lat_col, columns=lon_col, values=z_col)
    pivot = pivot.sort_index(axis=0).sort_index(axis=1)

    longitude = np.array([lon_to_180(float(lon)) for lon in pivot.columns.values], dtype=float)
    latitude = pivot.index.to_numpy(dtype=float)
    z = pivot.to_numpy(dtype=float)
    return BathyGrid(longitude=longitude, latitude=latitude, z=z)


def _cache_key(extent: List[float], stride: int) -> tuple[float, float, float, float, int]:
    west, east, south, north = extent
    return (
        round(west, 3),
        round(east, 3),
        round(south, 3),
        round(north, 3),
        stride,
    )


def _cache_path(cache_key: tuple[float, float, float, float, int]) -> Path:
    west, east, south, north, stride = cache_key
    filename = f"bathy_{west}_{east}_{south}_{north}_{stride}.npz"
    return get_bathy_cache_dir() / filename


def _load_cached_grid(cache_key: tuple[float, float, float, float, int]) -> Optional[BathyGrid]:
    path = _cache_path(cache_key)
    if not path.exists():
        return None
    try:
        data = np.load(path)
        return BathyGrid(
            longitude=data["longitude"],
            latitude=data["latitude"],
            z=data["z"],
        )
    except Exception as exc:
        logger.warning("Failed to load bathymetry cache %s: %s", path, exc)
        return None


def _save_cached_grid(cache_key: tuple[float, float, float, float, int], grid: BathyGrid) -> None:
    path = _cache_path(cache_key)
    try:
        get_bathy_cache_dir().mkdir(parents=True, exist_ok=True)
        np.savez(path, longitude=grid.longitude, latitude=grid.latitude, z=grid.z)
    except Exception as exc:
        logger.warning("Failed to write bathymetry cache %s: %s", path, exc)


def _fetch_from_erddap(
    bounds: dict[str, float],
    *,
    stride: int,
    timeout: int,
) -> Optional[BathyGrid]:
    server = settings.etopo_erddap_server
    dataset_id = settings.etopo_dataset_id

    erddap = ERDDAP(server=server, protocol="griddap")
    erddap.dataset_id = dataset_id
    erddap.griddap_initialize()
    erddap.response = "csv"
    erddap.variables = ["z"]
    erddap.constraints["latitude>="] = bounds["south"]
    erddap.constraints["latitude<="] = bounds["north"]
    erddap.constraints["longitude>="] = lon_to_360(bounds["west"])
    erddap.constraints["longitude<="] = lon_to_360(bounds["east"])
    erddap.constraints["latitude_step"] = stride
    erddap.constraints["longitude_step"] = stride

    df = erddap.to_pandas(requests_kwargs={"timeout": timeout})
    if df is None or df.empty:
        return None
    return _pivot_griddap_dataframe(df)


@lru_cache(maxsize=32)
def _fetch_cached(cache_key: tuple[float, float, float, float, int]) -> Optional[BathyGrid]:
    cached = _load_cached_grid(cache_key)
    if cached is not None:
        return cached

    west, east, south, north, stride = cache_key
    extent = [west, east, south, north]
    bounds = bathy_query_bounds(extent)
    timeout = int(settings.etopo_request_timeout)

    try:
        grid = _fetch_from_erddap(bounds, stride=stride, timeout=timeout)
    except Exception as exc:
        logger.warning("ETOPO bathymetry fetch failed for %s: %s", cache_key, exc)
        return None

    if grid is None:
        return None

    _save_cached_grid(cache_key, grid)
    return grid


def fetch_etopo_bathymetry(extent: List[float]) -> Optional[BathyGrid]:
    """Fetch ETOPO bathymetry for a map extent; returns None on failure."""
    if not extent or len(extent) != 4:
        return None

    stride = choose_stride(extent)
    cache_key = _cache_key(extent, stride)
    return _fetch_cached(cache_key)


def sample_depth_m_from_grid(grid: BathyGrid, lat: float, lon: float) -> Optional[float]:
    """Nearest-cell water depth (positive meters) from a BathyGrid; None on land/NaN."""
    if grid is None or grid.longitude.size == 0 or grid.latitude.size == 0:
        return None
    if not math.isfinite(lat) or not math.isfinite(lon):
        return None

    lon_idx = int(np.argmin(np.abs(grid.longitude - lon)))
    lat_idx = int(np.argmin(np.abs(grid.latitude - lat)))
    try:
        z = float(grid.z[lat_idx, lon_idx])
    except (IndexError, TypeError, ValueError):
        return None
    if not math.isfinite(z) or z >= 0:
        return None
    return -z


def _parse_bathy_cache_filename(path: Path) -> Optional[tuple[float, float, float, float, int]]:
    """Parse west/east/south/north/stride from a cache filename; None if malformed."""
    match = _CACHE_FILENAME_RE.match(path.name)
    if not match:
        return None
    west, east, south, north, stride = match.groups()
    try:
        return float(west), float(east), float(south), float(north), int(stride)
    except (TypeError, ValueError):
        return None


def _point_in_bbox(lat: float, lon: float, west: float, east: float, south: float, north: float) -> bool:
    return south <= lat <= north and west <= lon <= east


def _load_covering_cached_grid(lat: float, lon: float) -> Optional[BathyGrid]:
    """Return the tightest cached report/point grid whose bbox contains (lat, lon)."""
    root = get_bathy_cache_dir()
    if not root.is_dir():
        return None

    candidates: list[tuple[float, float, Path]] = []
    for path in root.glob("bathy_*.npz"):
        parsed = _parse_bathy_cache_filename(path)
        if parsed is None:
            continue
        west, east, south, north, _stride = parsed
        if not _point_in_bbox(lat, lon, west, east, south, north):
            continue
        area = max(east - west, 1e-9) * max(north - south, 1e-9)
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        candidates.append((area, -mtime, path))

    if not candidates:
        return None

    candidates.sort()  # smallest area first; then newest mtime
    for _area, _neg_mtime, path in candidates:
        try:
            data = np.load(path)
            grid = BathyGrid(
                longitude=data["longitude"],
                latitude=data["latitude"],
                z=data["z"],
            )
        except Exception as exc:
            logger.warning("Failed to load covering bathymetry cache %s: %s", path, exc)
            continue
        depth = sample_depth_m_from_grid(grid, lat, lon)
        if depth is not None:
            return grid
    return None


def fetch_etopo_depth_at(lat: float, lon: float) -> Optional[float]:
    """Approximate water depth (positive meters) at a point from ETOPO 2022.

    Prefers an existing cached report/point grid covering the location (zero
    network). Falls back to a tiny bbox fetch via ``fetch_etopo_bathymetry``.
    Returns None on failure or when the nearest cell is land (z >= 0).
    """
    if not math.isfinite(lat) or not math.isfinite(lon):
        return None
    if abs(lat) > 90.0 or abs(lon) > 180.0:
        return None

    cached_grid = _load_covering_cached_grid(lat, lon)
    if cached_grid is not None:
        depth = sample_depth_m_from_grid(cached_grid, lat, lon)
        if depth is not None:
            return depth

    half = POINT_DEPTH_HALF_WIDTH_DEG
    extent = [lon - half, lon + half, lat - half, lat + half]
    try:
        grid = fetch_etopo_bathymetry(extent)
    except Exception as exc:
        logger.warning("ETOPO point depth fetch failed at (%s, %s): %s", lat, lon, exc)
        return None
    if grid is None:
        return None
    return sample_depth_m_from_grid(grid, lat, lon)


def _iter_npz_entries() -> list[tuple[Path, float, int]]:
    """Return (path, mtime, byte_size) for each .npz under the bathy cache dir."""
    root = get_bathy_cache_dir()
    entries: list[tuple[Path, float, int]] = []
    if not root.is_dir():
        return entries
    for path in root.glob("*.npz"):
        try:
            st = path.stat()
            entries.append((path, st.st_mtime, st.st_size))
        except OSError:
            continue
    return entries


def get_bathy_cache_status() -> dict[str, Any]:
    entries = _iter_npz_entries()
    total_bytes = sum(size for _, _, size in entries)
    max_bytes = int(getattr(settings, "bathy_cache_max_bytes", 0) or 0)
    return {
        "cache_dir": str(get_bathy_cache_dir()),
        "response_files": len(entries),
        "total_bytes": total_bytes,
        "max_bytes": max_bytes,
        "max_age_days": int(getattr(settings, "bathy_cache_max_age_days", 90)),
        "last_cleanup_at": _cleanup_stats["last_cleanup_at"],
        "last_cleanup_summary": _cleanup_stats["last_cleanup_summary"],
    }


def enforce_bathy_cache_quota() -> dict[str, int]:
    """Evict oldest-by-mtime .npz files until under bathy_cache_max_bytes."""
    max_bytes = int(getattr(settings, "bathy_cache_max_bytes", 0) or 0)
    if max_bytes <= 0:
        return {"evicted_files": 0, "freed_bytes": 0}

    entries = _iter_npz_entries()
    total = sum(size for _, _, size in entries)
    if total <= max_bytes:
        return {"evicted_files": 0, "freed_bytes": 0}

    entries.sort(key=lambda item: item[1])  # oldest mtime first
    removed_files = 0
    freed = 0
    for path, _mtime, size in entries:
        if total <= max_bytes:
            break
        try:
            path.unlink()
            removed_files += 1
            freed += size
            total -= size
        except OSError as err:
            logger.warning("Failed to evict bathy cache file %s: %s", path, err)

    if removed_files:
        _fetch_cached.cache_clear()
    return {"evicted_files": removed_files, "freed_bytes": freed}


def purge_bathy_cache(
    *,
    force_all: bool = False,
    max_age_days: Optional[int] = None,
    enforce_quota: bool = True,
) -> dict[str, Any]:
    """Remove stale (or all) bathymetry .npz cache files and optionally enforce size quota."""
    if max_age_days is None:
        max_age_days = int(getattr(settings, "bathy_cache_max_age_days", 90))
    cutoff = time.time() - max(0, max_age_days) * 24 * 60 * 60

    removed_files = 0
    freed_bytes = 0
    for path, mtime, size in _iter_npz_entries():
        if not force_all and mtime >= cutoff:
            continue
        try:
            path.unlink()
            removed_files += 1
            freed_bytes += size
        except OSError as err:
            logger.warning("Failed to remove bathy cache file %s: %s", path, err)

    if removed_files:
        _fetch_cached.cache_clear()

    quota = {"evicted_files": 0, "freed_bytes": 0}
    if enforce_quota:
        quota = enforce_bathy_cache_quota()
        removed_files += quota["evicted_files"]
        freed_bytes += quota["freed_bytes"]

    return {
        "removed_files": removed_files,
        "freed_bytes": freed_bytes,
        "stale_files_removed": removed_files - quota["evicted_files"],
        "quota_evicted_files": quota["evicted_files"],
        "quota_freed_bytes": quota["freed_bytes"],
        "force_all": force_all,
        "max_age_days": max_age_days,
        "status": get_bathy_cache_status(),
    }


def run_bathy_cache_cleanup() -> dict[str, Any]:
    """Always-on disk cleanup: TTL purge + quota (independent of feature toggle)."""
    summary = purge_bathy_cache(force_all=False, enforce_quota=True)
    _cleanup_stats["last_cleanup_at"] = datetime.now(timezone.utc).isoformat()
    _cleanup_stats["last_cleanup_summary"] = {
        k: summary[k]
        for k in (
            "removed_files",
            "freed_bytes",
            "stale_files_removed",
            "quota_evicted_files",
            "quota_freed_bytes",
        )
        if k in summary
    }
    summary["status"] = get_bathy_cache_status()
    logger.debug("Bathymetry cache cleanup complete: %s", _cleanup_stats["last_cleanup_summary"])
    return summary
