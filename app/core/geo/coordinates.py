"""Shared latitude/longitude validation for telemetry tracks.

When a glider powers on before GPS lock, platforms often log exact (0, 0).
That point is real geographically (Gulf of Guinea) but is a sentinel for
"no fix" in our Wave Glider / Slocum / future platform pipelines — and it
destroys map extents and track-length calculations.
"""

from __future__ import annotations

import logging
from typing import Any, Optional, Tuple, Union

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

LatLon = Union[float, int, np.floating, np.integer]


def is_null_island(lat: Any, lon: Any) -> bool:
    """True when both coordinates are exactly 0 (GPS-unlock sentinel)."""
    if lat is None or lon is None:
        return False
    try:
        if pd.isna(lat) or pd.isna(lon):
            return False
        return float(lat) == 0.0 and float(lon) == 0.0
    except (TypeError, ValueError):
        return False


def mask_null_island_coordinates(
    df: pd.DataFrame,
    lat_col: str = "Latitude",
    lon_col: str = "Longitude",
) -> pd.DataFrame:
    """
    Set lat/lon to NaN where both are exactly 0.0.

    Preserves the row so non-position sensor columns remain available
    (important for Slocum dashboard bundles). Existing dropna(lat, lon)
    paths then exclude these points from maps and track metrics.
    """
    if df is None or df.empty:
        return df
    if lat_col not in df.columns or lon_col not in df.columns:
        return df

    lat = pd.to_numeric(df[lat_col], errors="coerce")
    lon = pd.to_numeric(df[lon_col], errors="coerce")
    mask = (lat == 0.0) & (lon == 0.0)
    if not mask.any():
        return df

    out = df.copy()
    out.loc[mask, lat_col] = np.nan
    out.loc[mask, lon_col] = np.nan
    logger.debug(
        "Masked %s null-island (0,0) coordinate row(s) in %s/%s",
        int(mask.sum()),
        lat_col,
        lon_col,
    )
    return out


def drop_null_island_rows(
    df: pd.DataFrame,
    lat_col: str = "Latitude",
    lon_col: str = "Longitude",
) -> pd.DataFrame:
    """Return a copy without rows whose lat and lon are both exactly 0.0."""
    if df is None or df.empty:
        return df
    if lat_col not in df.columns or lon_col not in df.columns:
        return df

    lat = pd.to_numeric(df[lat_col], errors="coerce")
    lon = pd.to_numeric(df[lon_col], errors="coerce")
    mask = ~((lat == 0.0) & (lon == 0.0))
    dropped = int((~mask).sum())
    if dropped:
        logger.debug(
            "Dropped %s null-island (0,0) coordinate row(s) from %s/%s",
            dropped,
            lat_col,
            lon_col,
        )
    return df.loc[mask].copy()


def latest_valid_lat_lon(
    df: pd.DataFrame,
    lat_col: str = "Latitude",
    lon_col: str = "Longitude",
    time_col: Optional[str] = "Timestamp",
) -> Tuple[Optional[float], Optional[float], Any]:
    """
    Return the most recent non-null, non-(0,0) lat/lon (and optional timestamp).

    Returns ``(None, None, None)`` when no valid fix exists.
    """
    if df is None or df.empty:
        return None, None, None
    if lat_col not in df.columns or lon_col not in df.columns:
        return None, None, None

    work = mask_null_island_coordinates(df, lat_col=lat_col, lon_col=lon_col)
    work = work.dropna(subset=[lat_col, lon_col])
    if work.empty:
        return None, None, None

    if time_col and time_col in work.columns:
        work = work.sort_values(time_col)
    row = work.iloc[-1]
    ts = row[time_col] if time_col and time_col in work.columns else None
    return float(row[lat_col]), float(row[lon_col]), ts
