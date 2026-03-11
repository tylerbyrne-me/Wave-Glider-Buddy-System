"""
ESS (Extreme Sea State) waypoint computation for the figure-8 (bow-tie) pattern.
Uses geodesic math so coordinates are suitable for pilot upload in decimal degrees.
"""

from typing import Any, Optional, Tuple

from geographiclib.geodesic import Geodesic

from .constants import ESS_PATTERN_LONG_LEG_M, ESS_PATTERN_SHORT_LEG_M


def _destination(lat: float, lon: float, bearing_deg: float, distance_m: float) -> Tuple[float, float]:
    """Return (lat, lon) of the point reached from (lat, lon) by traveling distance_m at bearing_deg (0-360)."""
    result = Geodesic.WGS84.Direct(lat, lon, bearing_deg, distance_m)
    return result["lat2"], result["lon2"]


def compute_ess_waypoints(
    lat: float,
    lon: float,
    wave_direction_deg: float,
    short_leg_m: Optional[float] = None,
    long_leg_m: Optional[float] = None,
) -> dict[str, Any]:
    """
    Compute WP1–WP4 for the ESS figure-8 pattern from an origin and wave direction (from).

    Wave direction is the direction waves are coming from (0–360). WP1 = origin;
    WP2 = short leg into waves; WP3 = long leg perpendicular; WP4 = short leg from WP3.

    short_leg_m: length of short legs in metres (default from constants).
    long_leg_m: length of long leg in metres (default from constants).

    Returns:
        Dict with current_location, wp1, wp2, wp3, wp4; each has "lat" and "lon" (decimal degrees).
    """
    short_m = float(short_leg_m) if short_leg_m is not None else ESS_PATTERN_SHORT_LEG_M
    long_m = float(long_leg_m) if long_leg_m is not None else ESS_PATTERN_LONG_LEG_M
    wave = float(wave_direction_deg) % 360.0
    bearing_into_waves = wave
    bearing_long_leg = (wave + 90.0) % 360.0

    wp1 = (lat, lon)
    wp2 = _destination(lat, lon, bearing_into_waves, short_m)
    wp3 = _destination(lat, lon, bearing_long_leg, long_m)
    wp4 = _destination(wp3[0], wp3[1], bearing_into_waves, short_m)

    return {
        "current_location": {"lat": round(lat, 6), "lon": round(lon, 6)},
        "wp1": {"lat": round(wp1[0], 6), "lon": round(wp1[1], 6)},
        "wp2": {"lat": round(wp2[0], 6), "lon": round(wp2[1], 6)},
        "wp3": {"lat": round(wp3[0], 6), "lon": round(wp3[1], 6)},
        "wp4": {"lat": round(wp4[0], 6), "lon": round(wp4[1], 6)},
    }
