"""ETOPO 2022 bathymetry fetch and contour helpers for PDF telemetry maps.

Data source: NOAA NCEI ETOPO 2022 via ERDDAP griddap (dataset ETOPO_2022_v1_15s,
variable z). Only the map bounding box is requested; results are cached under
data_store/bathy_cache/ as .npz files. Longitudes are converted to 0-360 for
the ERDDAP query and back to -180..180 for Cartopy plotting.

Disable contours with feature toggle report_bathymetry_contours=false.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd
from erddapy import ERDDAP

from ...config import settings

logger = logging.getLogger(__name__)

ETOPO_DEG_STEP = 0.004166667
BATHY_BBOX_PAD_DEG = 0.02
BATHY_CACHE_DIR = Path("data_store/bathy_cache")
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


@dataclass(frozen=True)
class BathyGrid:
    """1-D lon/lat axes and 2-D elevation grid (lat x lon)."""

    longitude: np.ndarray
    latitude: np.ndarray
    z: np.ndarray


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
    return BATHY_CACHE_DIR / filename


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
        BATHY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
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
