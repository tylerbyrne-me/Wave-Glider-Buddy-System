"""
Pure helpers and orchestration for Slocum daily pilot checklist autofill.

Computes flight/energy/science snapshots from ERDDAP checklist + CTD bundles and
optional Open-Meteo forecasts. Reference values come from SlocumDeployment JSON.
"""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import pandas as pd

logger = logging.getLogger(__name__)

CHECKLIST_FORM_TYPE = "slocum_daily_checklist"
CHECKLIST_FORM_TITLE = "Slocum Daily Pilot Checklist"
CHECKLIST_HOURS_BACK = 48
STORM_FORECAST_HOURS = 72
DENSITY_RANGE_THRESHOLD_KG_M3 = 6.0
LEAK_RANGE_SPIKE_THRESHOLD_V = 0.5
VMG_GOOD_THRESHOLD_M_S = 0.15

# Canonical admin-managed reference keys on SlocumDeployment.checklist_reference_values
CHECKLIST_REFERENCE_KEYS: tuple[str, ...] = (
    "battery_pack",
    "glider_depth_class",
    "endurance_amphr_total",
    "min_voltage",
    "max_voltage",
    "max_vacuum",
    "vacuum_at_depth",
    "vacuum_at_surface",
    "amphr_per_day_budget",
    "expected_mission_file",
    "expected_script",
    "argos_id",
    "u_alt_min_depth",
)

# Battery pack presets (coulomb_amphr endurance + voltage envelope).
BATTERY_PACK_PRESETS: dict[str, dict[str, Any]] = {
    "lithium_primary": {
        "label": "Lithium Primary",
        "endurance_amphr_total": 550,
        "min_voltage": 12.0,
        "max_voltage": 15.25,
    },
    "lithium_primary_extended": {
        "label": "Lithium Primary Extended",
        "endurance_amphr_total": 800,
        "min_voltage": 12.0,
        "max_voltage": 15.25,
    },
    "lithium_ion": {
        "label": "Lithium Ion",
        "endurance_amphr_total": 215,
        "min_voltage": 12.5,
        "max_voltage": 16.5,
    },
    "lithium_ion_extended": {
        "label": "Lithium Ion Extended",
        "endurance_amphr_total": 300,
        "min_voltage": 12.5,
        "max_voltage": 16.5,
    },
}

# Shallow vs deep vacuum envelope (mmHg). Surface is higher due to air-bladder inflation.
GLIDER_DEPTH_PRESETS: dict[str, dict[str, Any]] = {
    "shallow": {
        "label": "Shallow",
        "vacuum_at_depth": 6.0,
        "vacuum_at_surface": 8.0,
        "max_vacuum": 8.0,
    },
    "deep": {
        "label": "Deep",
        "vacuum_at_depth": 7.0,
        "vacuum_at_surface": 9.0,
        "max_vacuum": 9.0,
    },
}

# Near-surface depth threshold (m) for interpreting vacuum against surface vs depth refs.
VACUUM_SURFACE_DEPTH_M = 2.0


def list_checklist_presets() -> dict[str, Any]:
    """Public preset catalog for admin UI / docs."""
    return {
        "battery_packs": [
            {"id": key, **{k: v for k, v in spec.items()}}
            for key, spec in BATTERY_PACK_PRESETS.items()
        ],
        "glider_depth_classes": [
            {"id": key, **{k: v for k, v in spec.items()}}
            for key, spec in GLIDER_DEPTH_PRESETS.items()
        ],
    }


def apply_checklist_presets(refs: dict[str, Any]) -> dict[str, Any]:
    """
    Expand battery_pack / glider_depth_class preset ids into numeric reference fields.

    Explicit numeric values already present on ``refs`` win over preset defaults.
    """
    out = dict(refs or {})

    def _missing(key: str) -> bool:
        value = out.get(key)
        if value is None:
            return True
        if isinstance(value, str) and not value.strip():
            return True
        return False

    pack_id = str(out.get("battery_pack") or "").strip()
    if pack_id in BATTERY_PACK_PRESETS:
        pack = BATTERY_PACK_PRESETS[pack_id]
        for key in ("endurance_amphr_total", "min_voltage", "max_voltage"):
            if _missing(key):
                out[key] = pack[key]

    depth_id = str(out.get("glider_depth_class") or "").strip()
    if depth_id in GLIDER_DEPTH_PRESETS:
        depth = GLIDER_DEPTH_PRESETS[depth_id]
        for key in ("vacuum_at_depth", "vacuum_at_surface", "max_vacuum"):
            if _missing(key):
                out[key] = depth[key]
        if _missing("max_vacuum") and not _missing("vacuum_at_surface"):
            out["max_vacuum"] = out["vacuum_at_surface"]
    return out


def parse_checklist_reference_values(raw: Optional[str]) -> dict[str, Any]:
    """Parse JSON text from SlocumDeployment.checklist_reference_values into a dict."""
    if not raw or not str(raw).strip():
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        logger.warning("Invalid checklist_reference_values JSON; ignoring.")
        return {}
    if not isinstance(parsed, dict):
        return {}
    cleaned = {str(k): v for k, v in parsed.items() if v is not None and str(v).strip() != ""}
    return apply_checklist_presets(cleaned)

def format_reference_display(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.3g}" if abs(value) < 1000 else f"{value:.2f}"
    return str(value)


def _fmt_num(value: Any, digits: int = 2) -> str:
    if value is None or (isinstance(value, float) and (math.isnan(value) or math.isinf(value))):
        return "N/A"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return "N/A"
    return f"{num:.{digits}f}"


def _latest_valid(series: pd.Series) -> Optional[float]:
    if series is None or series.empty:
        return None
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if numeric.empty:
        return None
    return float(numeric.iloc[-1])


def _value_near_hours_ago(df: pd.DataFrame, column: str, hours_ago: float = 24.0) -> Optional[float]:
    if df is None or df.empty or "Timestamp" not in df.columns or column not in df.columns:
        return None
    work = df.dropna(subset=["Timestamp"]).copy()
    if work.empty:
        return None
    work[column] = pd.to_numeric(work[column], errors="coerce")
    work = work.dropna(subset=[column])
    if work.empty:
        return None
    end_ts = pd.Timestamp(work["Timestamp"].max())
    if end_ts.tzinfo is None:
        end_ts = end_ts.tz_localize("UTC")
    target = end_ts - timedelta(hours=hours_ago)
    deltas = (pd.to_datetime(work["Timestamp"], utc=True) - target).abs()
    idx = int(deltas.to_numpy().argmin())
    return float(work.iloc[idx][column])


def _latest_valid_with_time(
    df: pd.DataFrame,
    column: str,
) -> tuple[Optional[float], Optional[pd.Timestamp]]:
    if df is None or df.empty or column not in df.columns or "Timestamp" not in df.columns:
        return None, None
    work = df.dropna(subset=["Timestamp"]).copy()
    work[column] = pd.to_numeric(work[column], errors="coerce")
    work = work.dropna(subset=[column])
    if work.empty:
        return None, None
    work = work.sort_values("Timestamp")
    row = work.iloc[-1]
    ts = pd.Timestamp(row["Timestamp"])
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return float(row[column]), ts


def _value_near_hours_ago_with_time(
    df: pd.DataFrame,
    column: str,
    hours_ago: float = 24.0,
) -> tuple[Optional[float], Optional[pd.Timestamp]]:
    if df is None or df.empty or "Timestamp" not in df.columns or column not in df.columns:
        return None, None
    work = df.dropna(subset=["Timestamp"]).copy()
    work[column] = pd.to_numeric(work[column], errors="coerce")
    work = work.dropna(subset=[column])
    if work.empty:
        return None, None
    end_ts = pd.Timestamp(work["Timestamp"].max())
    if end_ts.tzinfo is None:
        end_ts = end_ts.tz_localize("UTC")
    target = end_ts - timedelta(hours=hours_ago)
    deltas = (pd.to_datetime(work["Timestamp"], utc=True) - target).abs()
    idx = int(deltas.to_numpy().argmin())
    row = work.iloc[idx]
    ts = pd.Timestamp(row["Timestamp"])
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return float(row[column]), ts


def _fmt_iso_z(ts: Optional[pd.Timestamp]) -> str:
    if ts is None:
        return ""
    return ts.isoformat().replace("+00:00", "Z")


def compute_amphr_usage_rate(
    latest_amphr: Optional[float],
    prior_amphr: Optional[float],
    hours_elapsed: float = 24.0,
) -> Optional[float]:
    """Amphr per day from coulomb counter delta over ``hours_elapsed``."""
    if latest_amphr is None or prior_amphr is None:
        return None
    if hours_elapsed <= 0:
        return None
    delta = latest_amphr - prior_amphr
    if delta < 0:
        # Counter reset or missing prior — do not invent a negative rate
        return None
    return float(delta * (24.0 / hours_elapsed))


def compute_days_left(
    endurance_amphr: Optional[float],
    latest_amphr: Optional[float],
    amphr_per_day: Optional[float],
) -> Optional[float]:
    if endurance_amphr is None or latest_amphr is None or amphr_per_day is None:
        return None
    if amphr_per_day <= 0:
        return None
    remaining = endurance_amphr - latest_amphr
    if remaining < 0:
        return 0.0
    return float(remaining / amphr_per_day)


def compute_projected_end_date(
    days_left: Optional[float],
    as_of: Optional[datetime] = None,
) -> Optional[str]:
    if days_left is None:
        return None
    base = as_of or datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    projected = base + timedelta(days=float(days_left))
    return projected.date().isoformat()


def compute_commanded_vs_measured(
    commanded: Optional[float],
    measured: Optional[float],
    *,
    unit: str = "",
) -> dict[str, Any]:
    delta = None
    if commanded is not None and measured is not None:
        delta = measured - commanded
    unit_bit = f" {unit}" if unit else ""
    return {
        "commanded": commanded,
        "measured": measured,
        "delta": delta,
        "display": (
            f"c={_fmt_num(commanded)}{unit_bit} | m={_fmt_num(measured)}{unit_bit} | "
            f"Δ={_fmt_num(delta)}{unit_bit}"
            if commanded is not None or measured is not None
            else "N/A (no samples in window)"
        ),
    }


def compute_signed_commanded_vs_measured(
    measured: pd.Series,
    commanded: pd.Series,
    *,
    sign_series: Optional[pd.Series] = None,
    unit: str = "°",
    climb_label: str = "climb",
    dive_label: str = "dive",
) -> dict[str, Any]:
    """
    Split by sign (+ climb / − dive). Default sign series is measured (pitch); for
    oil/ballast pass ``sign_series=m_pitch`` so averages are over climb vs dive phases.
    """
    empty = {
        "climb_measured": None,
        "climb_commanded": None,
        "dive_measured": None,
        "dive_commanded": None,
        "display": "N/A (no samples in window)",
        "source_label": None,
    }
    if measured is None or commanded is None:
        return empty
    m = pd.to_numeric(measured, errors="coerce")
    c = pd.to_numeric(commanded, errors="coerce")
    sign = pd.to_numeric(sign_series if sign_series is not None else measured, errors="coerce")
    frame = pd.DataFrame({"m": m, "c": c, "sign": sign}).dropna(subset=["m", "sign"])
    if frame.empty:
        return empty

    climb = frame[frame["sign"] > 0]
    dive = frame[frame["sign"] < 0]

    climb_m = float(climb["m"].mean()) if not climb.empty else None
    climb_c = float(climb["c"].dropna().mean()) if not climb.empty and climb["c"].notna().any() else None
    dive_m = float(dive["m"].mean()) if not dive.empty else None
    dive_c = float(dive["c"].dropna().mean()) if not dive.empty and dive["c"].notna().any() else None

    parts: list[str] = []
    if climb_m is not None:
        parts.append(
            f"{climb_label} m={_fmt_num(climb_m, 1)}{unit} c={_fmt_num(climb_c, 1)}{unit}"
        )
    if dive_m is not None:
        parts.append(
            f"{dive_label} m={_fmt_num(dive_m, 1)}{unit} c={_fmt_num(dive_c, 1)}{unit}"
        )
    return {
        "climb_measured": climb_m,
        "climb_commanded": climb_c,
        "dive_measured": dive_m,
        "dive_commanded": dive_c,
        "display": " | ".join(parts) if parts else "N/A (no signed samples)",
        "source_label": None,
    }


def compute_roll_stats(series: pd.Series) -> dict[str, Any]:
    """24h (window) roll avg / min / max in degrees. + starboard, − port."""
    numeric = pd.to_numeric(series, errors="coerce").dropna() if series is not None else pd.Series(dtype=float)
    if numeric.empty:
        return {
            "avg": None,
            "min": None,
            "max": None,
            "display": "N/A (no samples in window)",
        }
    avg = float(numeric.mean())
    vmin = float(numeric.min())
    vmax = float(numeric.max())
    return {
        "avg": avg,
        "min": vmin,
        "max": vmax,
        "display": (
            f"avg {_fmt_num(avg, 1)}° | "
            f"min {_fmt_num(vmin, 1)}° (port) | "
            f"max {_fmt_num(vmax, 1)}° (starboard)"
        ),
    }


def compute_leak_channel_stats(
    series: pd.Series,
    spike_threshold_v: float = LEAK_RANGE_SPIKE_THRESHOLD_V,
) -> dict[str, Any]:
    numeric = pd.to_numeric(series, errors="coerce").dropna() if series is not None else pd.Series(dtype=float)
    if numeric.empty:
        return {
            "min": None,
            "max": None,
            "latest": None,
            "range": None,
            "spike_flag": False,
            "display": "N/A",
        }
    vmin = float(numeric.min())
    vmax = float(numeric.max())
    latest = float(numeric.iloc[-1])
    vrange = vmax - vmin
    spike_flag = vrange >= float(spike_threshold_v)
    return {
        "min": vmin,
        "max": vmax,
        "latest": latest,
        "range": vrange,
        "spike_flag": spike_flag,
        "display": (
            f"latest={_fmt_num(latest, 3)} V | min={_fmt_num(vmin, 3)} | "
            f"max={_fmt_num(vmax, 3)} | range={_fmt_num(vrange, 3)}"
            + (" | SPIKE" if spike_flag else " | OK")
        ),
    }


def compute_density_range(
    series: pd.Series,
    threshold_kg_m3: float = DENSITY_RANGE_THRESHOLD_KG_M3,
) -> dict[str, Any]:
    numeric = pd.to_numeric(series, errors="coerce").dropna() if series is not None else pd.Series(dtype=float)
    if numeric.empty:
        return {
            "min": None,
            "max": None,
            "range": None,
            "over_threshold": False,
            "display": "N/A",
        }
    vmin = float(numeric.min())
    vmax = float(numeric.max())
    vrange = vmax - vmin
    over = vrange > float(threshold_kg_m3)
    return {
        "min": vmin,
        "max": vmax,
        "range": vrange,
        "over_threshold": over,
        "display": (
            f"{_fmt_num(vmin, 1)}–{_fmt_num(vmax, 1)} kg/m³ "
            f"(range {_fmt_num(vrange, 2)}; {'> ' if over else '≤ '}"
            f"{threshold_kg_m3:g} threshold)"
        ),
    }


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def _gps_lat_lon_cols(df: pd.DataFrame) -> tuple[Optional[str], Optional[str]]:
    lat_col = "MGpsLat" if "MGpsLat" in df.columns and df["MGpsLat"].notna().any() else (
        "Latitude" if "Latitude" in df.columns else None
    )
    lon_col = "MGpsLon" if "MGpsLon" in df.columns and df["MGpsLon"].notna().any() else (
        "Longitude" if "Longitude" in df.columns else None
    )
    return lat_col, lon_col


def _latest_valid_waypoint(df: pd.DataFrame) -> tuple[Optional[float], Optional[float]]:
    if "CWptLat" not in df.columns or "CWptLon" not in df.columns:
        return None, None
    work = df[["CWptLat", "CWptLon"]].copy()
    work["CWptLat"] = pd.to_numeric(work["CWptLat"], errors="coerce")
    work["CWptLon"] = pd.to_numeric(work["CWptLon"], errors="coerce")
    work = work.dropna()
    # Drop zeros / implausible placeholders
    work = work[(work["CWptLat"].abs() > 0.01) & (work["CWptLon"].abs() > 0.01)]
    work = work[(work["CWptLat"].abs() <= 90) & (work["CWptLon"].abs() <= 180)]
    if work.empty:
        return None, None
    row = work.iloc[-1]
    return float(row["CWptLat"]), float(row["CWptLon"])


def compute_course_progress_vmg(df: pd.DataFrame) -> dict[str, Any]:
    """
    Prefer VMG toward commanded waypoint (closing rate). Else net GPS progress rate.

    True VMG needs a destination; with ``c_wpt_*`` we use approach-rate over the window.
    """
    empty = {
        "speed_m_s": None,
        "distance_m": None,
        "hours": None,
        "meets_threshold": None,
        "mode": None,
        "display": "N/A (no GPS samples in window)",
    }
    if df is None or df.empty or "Timestamp" not in df.columns:
        return empty

    lat_col, lon_col = _gps_lat_lon_cols(df)
    if not lat_col or not lon_col:
        return empty

    work = df.dropna(subset=["Timestamp", lat_col, lon_col]).copy()
    if len(work) < 2:
        return empty
    work = work.sort_values("Timestamp")
    start = work.iloc[0]
    end = work.iloc[-1]
    try:
        lat1, lon1 = float(start[lat_col]), float(start[lon_col])
        lat2, lon2 = float(end[lat_col]), float(end[lon_col])
    except (TypeError, ValueError):
        return empty
    if any(math.isnan(v) for v in (lat1, lon1, lat2, lon2)):
        return empty

    t0 = pd.Timestamp(start["Timestamp"])
    t1 = pd.Timestamp(end["Timestamp"])
    if t0.tzinfo is None:
        t0 = t0.tz_localize("UTC")
    if t1.tzinfo is None:
        t1 = t1.tz_localize("UTC")
    hours = max(0.0, (t1 - t0).total_seconds() / 3600.0)
    if hours <= 0:
        return empty

    wpt_lat, wpt_lon = _latest_valid_waypoint(df)
    if wpt_lat is not None and wpt_lon is not None:
        dist_start = _haversine_m(lat1, lon1, wpt_lat, wpt_lon)
        dist_end = _haversine_m(lat2, lon2, wpt_lat, wpt_lon)
        closed_m = dist_start - dist_end  # positive = approached waypoint
        speed = closed_m / (hours * 3600.0)
        meets = speed >= VMG_GOOD_THRESHOLD_M_S
        return {
            "speed_m_s": speed,
            "distance_m": closed_m,
            "hours": hours,
            "meets_threshold": meets,
            "mode": "waypoint_vmg",
            "display": (
                f"VMG {_fmt_num(speed, 3)} m/s toward wpt "
                f"({_fmt_num(wpt_lat, 4)}, {_fmt_num(wpt_lon, 4)}) over {_fmt_num(hours, 1)} h "
                f"(closed {_fmt_num(closed_m / 1000.0, 2)} km; "
                f"{'≥' if meets else '<'} {VMG_GOOD_THRESHOLD_M_S} m/s)"
            ),
        }

    # Fallback: net GPS displacement rate (not waypoint VMG)
    distance_m = _haversine_m(lat1, lon1, lat2, lon2)
    speed = distance_m / (hours * 3600.0)
    meets = speed >= VMG_GOOD_THRESHOLD_M_S
    return {
        "speed_m_s": speed,
        "distance_m": distance_m,
        "hours": hours,
        "meets_threshold": meets,
        "mode": "net_gps_progress",
        "display": (
            f"Net GPS progress {_fmt_num(speed, 3)} m/s over {_fmt_num(hours, 1)} h "
            f"(net {_fmt_num(distance_m / 1000.0, 2)} km; not waypoint VMG — no c_wpt; "
            f"{'≥' if meets else '<'} {VMG_GOOD_THRESHOLD_M_S} m/s)"
        ),
    }


# Back-compat alias used by older tests / callers
def compute_speed_made_good(df: pd.DataFrame) -> dict[str, Any]:
    return compute_course_progress_vmg(df)


def resolve_buoyancy_columns(
    df: pd.DataFrame,
    depth_class: Optional[str] = None,
) -> tuple[Optional[str], Optional[str], str]:
    """
    Prefer ballast when present; if both oil and ballast exist, use depth_class hint.
    Returns (measured_col, commanded_col, source_label).
    """
    has_ballast = (
        "MBallastPumped" in df.columns
        and df["MBallastPumped"].notna().any()
    )
    has_oil = "MDeOilVol" in df.columns and df["MDeOilVol"].notna().any()
    depth = (depth_class or "").strip().lower()

    if has_ballast and has_oil:
        if depth == "deep":
            return "MDeOilVol", "CDeOilVol", "m_de_oil_vol"
        return "MBallastPumped", "CBallastPumped", "m_ballast_pumped"
    if has_ballast:
        return "MBallastPumped", "CBallastPumped", "m_ballast_pumped"
    if has_oil:
        return "MDeOilVol", "CDeOilVol", "m_de_oil_vol"
    return None, None, "m_de_oil_vol / m_ballast_pumped"


def summarize_storm_outlook(
    general_forecast: Optional[dict[str, Any]],
    marine_forecast: Optional[dict[str, Any]],
    hours: int = STORM_FORECAST_HOURS,
) -> str:
    """Build a short storm-outlook string from Open-Meteo hourly payloads."""
    parts: list[str] = []
    n = max(1, int(hours))

    if general_forecast and isinstance(general_forecast.get("hourly"), dict):
        hourly = general_forecast["hourly"]
        wind = (hourly.get("windspeed_10m") or [])[:n]
        precip = (hourly.get("precipitation") or [])[:n]
        wind_vals = [float(v) for v in wind if v is not None]
        precip_vals = [float(v) for v in precip if v is not None]
        if wind_vals:
            parts.append(f"max wind {_fmt_num(max(wind_vals), 1)} kn")
        if precip_vals:
            parts.append(f"max precip {_fmt_num(max(precip_vals), 2)} mm/h")

    if marine_forecast and isinstance(marine_forecast.get("hourly"), dict):
        hourly = marine_forecast["hourly"]
        waves = (hourly.get("wave_height") or [])[:n]
        wave_vals = [float(v) for v in waves if v is not None]
        if wave_vals:
            parts.append(f"max wave {_fmt_num(max(wave_vals), 1)} m")

    if not parts:
        return "Forecast unavailable"
    return f"Next {hours}h: " + "; ".join(parts)


def build_checklist_autofill_snapshot(
    checklist_df: Optional[pd.DataFrame],
    ctd_df: Optional[pd.DataFrame],
    references: Optional[dict[str, Any]] = None,
    *,
    storm_summary: Optional[str] = None,
    pilot_username: Optional[str] = None,
    dataset_id: Optional[str] = None,
) -> dict[str, str]:
    """
    Return a flat map of form item id → display string for checklist autofill.

    Pure computation; I/O (ERDDAP / forecast) happens in the router.
    """
    refs = references or {}
    df = checklist_df if checklist_df is not None else pd.DataFrame()
    ctd = ctd_df if ctd_df is not None else pd.DataFrame()

    latest_ts = None
    if not df.empty and "Timestamp" in df.columns and df["Timestamp"].notna().any():
        latest_ts = pd.Timestamp(df["Timestamp"].max())
        if latest_ts.tzinfo is None:
            latest_ts = latest_ts.tz_localize("UTC")

    voltage = _latest_valid(df["MBattery"]) if "MBattery" in df.columns else None
    vacuum = _latest_valid(df["MVacuum"]) if "MVacuum" in df.columns else None
    water_depth = _latest_valid(df["MWaterDepth"]) if "MWaterDepth" in df.columns else None
    depth_rate = (
        _latest_valid(df["MDepthRateAvgFinal"]) if "MDepthRateAvgFinal" in df.columns else None
    )

    amphr_latest, amphr_latest_ts = _latest_valid_with_time(df, "MCoulombAmphrTotal")
    amphr_prior, amphr_prior_ts = _value_near_hours_ago_with_time(df, "MCoulombAmphrTotal", 24.0)
    hours_for_rate = 24.0
    if amphr_latest_ts is not None and amphr_prior_ts is not None:
        hours_for_rate = max(
            0.5,
            (amphr_latest_ts - amphr_prior_ts).total_seconds() / 3600.0,
        )
    amphr_rate = compute_amphr_usage_rate(amphr_latest, amphr_prior, hours_for_rate)

    endurance = None
    try:
        if refs.get("endurance_amphr_total") is not None:
            endurance = float(refs["endurance_amphr_total"])
    except (TypeError, ValueError):
        endurance = None

    days_left = compute_days_left(endurance, amphr_latest, amphr_rate)
    as_of = latest_ts.to_pydatetime() if latest_ts is not None else datetime.now(timezone.utc)
    end_date = compute_projected_end_date(days_left, as_of=as_of)

    pitch = compute_signed_commanded_vs_measured(
        df["MPitch"] if "MPitch" in df.columns else pd.Series(dtype=float),
        df["CPitch"] if "CPitch" in df.columns else pd.Series(dtype=float),
        unit="°",
        climb_label="climb (+)",
        dive_label="dive (−)",
    )
    fin = compute_commanded_vs_measured(
        _latest_valid(df["CFin"]) if "CFin" in df.columns else None,
        _latest_valid(df["MFin"]) if "MFin" in df.columns else None,
    )
    battpos = compute_commanded_vs_measured(
        _latest_valid(df["CBattpos"]) if "CBattpos" in df.columns else None,
        _latest_valid(df["MBattpos"]) if "MBattpos" in df.columns else None,
    )

    depth_class = str(refs.get("glider_depth_class") or "").strip()
    meas_col, cmd_col, buoy_label = resolve_buoyancy_columns(df, depth_class)
    if meas_col and cmd_col:
        oil = compute_signed_commanded_vs_measured(
            df[meas_col],
            df[cmd_col] if cmd_col in df.columns else pd.Series(dtype=float),
            sign_series=df["MPitch"] if "MPitch" in df.columns else None,
            unit=" cc",
            climb_label="climb (+)",
            dive_label="dive (−)",
        )
        oil_display = f"{buoy_label}: {oil['display']}"
    else:
        oil_display = "N/A (no ballast/oil samples in window)"

    roll = compute_roll_stats(df["MRoll"] if "MRoll" in df.columns else pd.Series(dtype=float))

    bms_pitch = _latest_valid(df["MBmsPitchCurrent"]) if "MBmsPitchCurrent" in df.columns else None
    bms_aft = _latest_valid(df["MBmsAftCurrent"]) if "MBmsAftCurrent" in df.columns else None
    bms_ebay = _latest_valid(df["MBmsEbayCurrent"]) if "MBmsEbayCurrent" in df.columns else None
    bms_pitch_mean = (
        float(pd.to_numeric(df["MBmsPitchCurrent"], errors="coerce").dropna().mean())
        if "MBmsPitchCurrent" in df.columns and df["MBmsPitchCurrent"].notna().any()
        else None
    )
    bms_aft_mean = (
        float(pd.to_numeric(df["MBmsAftCurrent"], errors="coerce").dropna().mean())
        if "MBmsAftCurrent" in df.columns and df["MBmsAftCurrent"].notna().any()
        else None
    )
    bms_ebay_mean = (
        float(pd.to_numeric(df["MBmsEbayCurrent"], errors="coerce").dropna().mean())
        if "MBmsEbayCurrent" in df.columns and df["MBmsEbayCurrent"].notna().any()
        else None
    )
    if bms_pitch is None and bms_aft is None and bms_ebay is None:
        bms_display = "N/A (no samples in window / not on dataset)"
    else:
        bms_display = (
            f"latest pitch={_fmt_num(bms_pitch, 3)} A aft={_fmt_num(bms_aft, 3)} A "
            f"ebay={_fmt_num(bms_ebay, 3)} A | "
            f"24h mean pitch={_fmt_num(bms_pitch_mean, 3)} aft={_fmt_num(bms_aft_mean, 3)} "
            f"ebay={_fmt_num(bms_ebay_mean, 3)}"
        )

    leak_main = compute_leak_channel_stats(
        df["MLeakdetectVoltage"] if "MLeakdetectVoltage" in df.columns else pd.Series(dtype=float)
    )
    leak_fwd = compute_leak_channel_stats(
        df["MLeakdetectVoltageForward"]
        if "MLeakdetectVoltageForward" in df.columns
        else pd.Series(dtype=float)
    )
    leak_sci = compute_leak_channel_stats(
        df["MLeakdetectVoltageScience"]
        if "MLeakdetectVoltageScience" in df.columns
        else pd.Series(dtype=float)
    )
    any_spike = bool(leak_main["spike_flag"] or leak_fwd["spike_flag"] or leak_sci["spike_flag"])
    leak_display = (
        f"main: {leak_main['display']} || forward: {leak_fwd['display']} || "
        f"science: {leak_sci['display']}"
        + (" — REVIEW SPIKES" if any_spike else "")
    )

    density_series = (
        df["Density"]
        if "Density" in df.columns and df["Density"].notna().any()
        else (ctd["Density"] if "Density" in ctd.columns else pd.Series(dtype=float))
    )
    density = compute_density_range(density_series)
    vmg = compute_course_progress_vmg(df)

    ctd_latest = None
    if not ctd.empty and "Timestamp" in ctd.columns and ctd["Timestamp"].notna().any():
        ctd_ts = pd.Timestamp(ctd["Timestamp"].max())
        if ctd_ts.tzinfo is None:
            ctd_ts = ctd_ts.tz_localize("UTC")
        ctd_latest = ctd_ts.isoformat().replace("+00:00", "Z")

    min_voltage_ref = format_reference_display(refs.get("min_voltage"))
    max_voltage_ref = format_reference_display(refs.get("max_voltage"))
    vacuum_depth_ref = refs.get("vacuum_at_depth")
    vacuum_surface_ref = refs.get("vacuum_at_surface", refs.get("max_vacuum"))
    max_vacuum_ref = format_reference_display(refs.get("max_vacuum") or vacuum_surface_ref)
    amphr_budget_ref = format_reference_display(refs.get("amphr_per_day_budget"))
    endurance_ref = format_reference_display(refs.get("endurance_amphr_total"))
    depth_class_label = (
        GLIDER_DEPTH_PRESETS.get(depth_class, {}).get("label")
        if depth_class in GLIDER_DEPTH_PRESETS
        else None
    )
    pack_id = str(refs.get("battery_pack") or "").strip()
    pack_label = (
        BATTERY_PACK_PRESETS.get(pack_id, {}).get("label")
        if pack_id in BATTERY_PACK_PRESETS
        else None
    )

    voltage_display = _fmt_num(voltage, 2)
    if voltage is not None and (refs.get("min_voltage") is not None or refs.get("max_voltage") is not None):
        try:
            parts: list[str] = []
            ok = True
            if refs.get("min_voltage") is not None:
                ok = ok and voltage >= float(refs["min_voltage"])
                parts.append(f"≥ {min_voltage_ref}")
            if refs.get("max_voltage") is not None:
                ok = ok and voltage <= float(refs["max_voltage"])
                parts.append(f"≤ {max_voltage_ref}")
            envelope = " / ".join(parts) if parts else ""
            label_bit = f"; {pack_label}" if pack_label else ""
            voltage_display = (
                f"{voltage_display} V (ref {envelope}{label_bit}; {'OK' if ok else 'OUT OF RANGE'})"
            )
        except (TypeError, ValueError):
            voltage_display = f"{voltage_display} V (ref {min_voltage_ref}–{max_voltage_ref})"
    elif voltage is not None:
        voltage_display = f"{voltage_display} V"
    else:
        voltage_display = "N/A (no samples in window)"

    vacuum_display = _fmt_num(vacuum, 2)
    depth_m = _latest_valid(df["MDepth"]) if "MDepth" in df.columns else None
    if vacuum is not None and (vacuum_depth_ref is not None or vacuum_surface_ref is not None):
        try:
            surface_limit = float(vacuum_surface_ref) if vacuum_surface_ref is not None else None
            depth_expect = float(vacuum_depth_ref) if vacuum_depth_ref is not None else None
            near_surface = depth_m is not None and depth_m <= VACUUM_SURFACE_DEPTH_M
            expected = surface_limit if near_surface and surface_limit is not None else depth_expect
            ok = True
            if surface_limit is not None and vacuum > surface_limit:
                ok = False
            elif expected is not None:
                ok = abs(vacuum - expected) <= 1.5
            ctx = "surface" if near_surface else "depth"
            class_bit = f"; {depth_class_label}" if depth_class_label else ""
            vacuum_display = (
                f"{vacuum_display} mmHg "
                f"(~{format_reference_display(depth_expect)} @depth / "
                f"~{format_reference_display(surface_limit)} @surface"
                f"{class_bit}; {ctx} check {'OK' if ok else 'REVIEW'})"
            )
        except (TypeError, ValueError):
            vacuum_display = f"{vacuum_display} (ref ≤ {max_vacuum_ref})"
    elif vacuum is not None and refs.get("max_vacuum") is not None:
        try:
            ok = vacuum <= float(refs["max_vacuum"])
            vacuum_display = f"{vacuum_display} (ref ≤ {max_vacuum_ref}; {'OK' if ok else 'HIGH'})"
        except (TypeError, ValueError):
            vacuum_display = f"{vacuum_display} (ref {max_vacuum_ref})"
    elif vacuum is not None:
        vacuum_display = f"{vacuum_display} mmHg"
    else:
        vacuum_display = "N/A (no samples in window)"

    if amphr_latest is not None:
        coulomb_latest_display = (
            f"{_fmt_num(amphr_latest, 3)} Ah @ {_fmt_iso_z(amphr_latest_ts)}"
        )
    else:
        coulomb_latest_display = "N/A (no coulomb samples in window)"
    if amphr_prior is not None:
        coulomb_prior_display = (
            f"{_fmt_num(amphr_prior, 3)} Ah @ {_fmt_iso_z(amphr_prior_ts)} (~24h prior)"
        )
    else:
        coulomb_prior_display = "N/A (no coulomb sample ~24h prior)"

    amphr_rate_display = _fmt_num(amphr_rate, 3)
    if amphr_rate is None:
        amphr_rate_display = "N/A (need latest + ~24h prior coulomb)"
    elif refs.get("amphr_per_day_budget") is not None:
        amphr_rate_display = (
            f"{amphr_rate_display} Ah/day over {_fmt_num(hours_for_rate, 1)} h "
            f"(budget {amphr_budget_ref})"
        )
    else:
        amphr_rate_display = f"{amphr_rate_display} Ah/day over {_fmt_num(hours_for_rate, 1)} h"

    if days_left is not None:
        days_left_display = f"{_fmt_num(days_left, 1)} days (endurance ref {endurance_ref})"
    elif amphr_latest is None or amphr_rate is None or endurance is None:
        days_left_display = "N/A (need endurance ref + amphr rate)"
    else:
        days_left_display = "N/A"

    depth_rate_display = (
        f"{_fmt_num(depth_rate, 3)} m/s"
        if depth_rate is not None
        else "N/A (no samples in window)"
    )
    water_depth_display = (
        f"{_fmt_num(water_depth, 1)} m"
        if water_depth is not None
        else "N/A (no samples in window)"
    )

    return {
        "pilot_val": pilot_username or "N/A",
        "dataset_id_val": dataset_id or "N/A",
        "last_data_time_val": (
            latest_ts.isoformat().replace("+00:00", "Z") if latest_ts is not None else "N/A"
        ),
        "expected_mission_file_ref_val": format_reference_display(refs.get("expected_mission_file")),
        "course_vmg_val": vmg["display"],
        "storm_outlook_val": storm_summary or "Forecast unavailable",
        "voltage_val": voltage_display,
        "coulomb_prior_val": coulomb_prior_display,
        "coulomb_latest_val": coulomb_latest_display,
        "amphr_rate_val": amphr_rate_display,
        "days_left_val": days_left_display,
        "end_date_val": end_date or "N/A",
        "endurance_ref_val": f"{endurance_ref} Ah",
        "vacuum_val": vacuum_display,
        "roll_val": roll["display"],
        "pitch_val": pitch["display"],
        "fin_val": fin["display"],
        "oil_vol_val": oil_display,
        "battpos_val": battpos["display"],
        "depth_rate_val": depth_rate_display,
        "water_depth_val": water_depth_display,
        "bms_currents_val": bms_display,
        "leakdetect_val": leak_display,
        "density_range_val": density["display"],
        "u_alt_min_depth_ref_val": format_reference_display(refs.get("u_alt_min_depth")),
        "expected_script_ref_val": format_reference_display(refs.get("expected_script")),
        "ctd_freshness_val": ctd_latest or "N/A",
        "argos_id_ref_val": format_reference_display(refs.get("argos_id")),
    }


async def load_checklist_autofill_values(
    dataset_id: str,
    references: Optional[dict[str, Any]] = None,
    *,
    pilot_username: Optional[str] = None,
    include_forecast: bool = True,
    hours_back: int = CHECKLIST_HOURS_BACK,
    is_historical: bool = False,
) -> dict[str, str]:
    """
    Fetch checklist/CTD data (+ optional forecast) and return autofill display map.
    """
    from ..core.geo.forecast import get_general_meteo_forecast, get_marine_meteo_forecast
    from ..core.slocum_cache_service import get_cached_or_fetch_bundle_df
    from ..core.slocum_mirror_service import is_historical_dataset

    if not is_historical and is_historical_dataset(dataset_id):
        is_historical = True

    checklist_df = await get_cached_or_fetch_bundle_df(
        dataset_id,
        "checklist",
        None,
        None,
        hours_back=hours_back,
        is_historical=is_historical,
        context="interactive",
    )
    if checklist_df is None:
        checklist_df = pd.DataFrame()

    ctd_df = await get_cached_or_fetch_bundle_df(
        dataset_id,
        "ctd",
        None,
        None,
        hours_back=min(hours_back, 24),
        is_historical=is_historical,
        context="interactive",
    )
    if ctd_df is None:
        ctd_df = pd.DataFrame()

    storm_summary = None
    if include_forecast and not is_historical and not checklist_df.empty:
        lat = _latest_valid(checklist_df["Latitude"]) if "Latitude" in checklist_df.columns else None
        lon = _latest_valid(checklist_df["Longitude"]) if "Longitude" in checklist_df.columns else None
        if lat is not None and lon is not None and not (math.isnan(lat) or math.isnan(lon)):
            try:
                general = await get_general_meteo_forecast(lat, lon)
                marine = await get_marine_meteo_forecast(lat, lon)
                storm_summary = summarize_storm_outlook(general, marine)
            except Exception as err:
                logger.warning("Checklist storm outlook failed for %s: %s", dataset_id, err)
                storm_summary = "Forecast unavailable"

    return build_checklist_autofill_snapshot(
        checklist_df,
        ctd_df,
        references,
        storm_summary=storm_summary,
        pilot_username=pilot_username,
        dataset_id=dataset_id,
    )
