"""Filter mission data, assemble Platypus story, and write mission PDF reports.

``write_mission_pdf`` is the single assembly entry. Modes:
- ``weekly``: cover → TOC → mission details → one ``build_summary`` block → telemetry/charts/errors/AIS.
- ``end_of_mission``: front matter (executive summary + full-track map) → one block per ISO week
  (week summary, telemetry with ``KeepTogether``, sensor charts, WG-VM4 offloads for that week)
  → back matter (mission-wide AIS + errors). WG-VM4 rows are not repeated in back matter.

Section flowables live in ``sections``; page geometry and running headers in ``styling``.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from sqlalchemy import or_
from sqlmodel import Session as SQLModelSession, select

from .. import models, utils
from ..infra.db import get_db_session
from ..data.processors import (
    preprocess_ais_df,
    preprocess_ctd_df,
    preprocess_error_df,
    preprocess_fluorometer_df,
    preprocess_wave_df,
    preprocess_weather_df,
    telemetry_speed_over_ground_series,
)
from .constants import REPORTS_ROOT
from .common import build_platform_cover_flowables, get_report_logo_path
from .styling import WeeklyReportDocTemplate, build_paragraph_styles
from . import sections
from .week_windows import compute_iso_week_windows, resolve_mission_time_bounds
from ..data.summaries import get_ais_summary_stats, theoretical_max_wh

logger = logging.getLogger(__name__)


def _previous_report_date_window(start: date, end: date) -> tuple[date, date]:
    """UTC inclusive window immediately before ``start`` … ``end``."""
    days = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)
    return prev_start, prev_end


def _power_trend(current: float, previous: Optional[float]) -> Optional[str]:
    if previous is None:
        return None
    if current > previous:
        return "up"
    if current < previous:
        return "down"
    return None


def _prior_power_summary_for_window(
    *,
    power_df: pd.DataFrame,
    solar_df: pd.DataFrame,
    telemetry_df: pd.DataFrame,
    ctd_df: pd.DataFrame,
    weather_df: pd.DataFrame,
    wave_df: pd.DataFrame,
    fluorometer_df: pd.DataFrame,
    ais_df: pd.DataFrame,
    error_df: pd.DataFrame,
    start_date: date,
    end_date: date,
    battery_max_wh: Optional[float] = None,
) -> dict:
    _, p_prev, s_prev, _, _, _, _, _, _ = _filter_report_dataframes(
        telemetry_df=telemetry_df,
        power_df=power_df,
        solar_df=solar_df,
        ctd_df=ctd_df,
        weather_df=weather_df,
        wave_df=wave_df,
        fluorometer_df=fluorometer_df,
        ais_df=ais_df,
        error_df=error_df,
        start_date=start_date,
        end_date=end_date,
    )
    return _calculate_power_summary(p_prev, s_prev, battery_max_wh=battery_max_wh)


def _calculate_telemetry_summary(df: pd.DataFrame) -> dict:
    summary = {"total_distance_km": 0.0, "avg_speed_knots": 0.0}
    if df.empty or len(df) < 2:
        return summary
    if "lastLocationFix" not in df.columns:
        return summary
    df_working = df.copy()
    df_working["lastLocationFix"] = utils.parse_timestamp_column(
        df_working["lastLocationFix"], errors="coerce", utc=True
    )
    df_clean = df_working.dropna(subset=["latitude", "longitude", "lastLocationFix"]).sort_values(
        by="lastLocationFix"
    ).copy()
    if len(df_clean) < 2:
        return summary
    R = 6371
    lat1 = np.radians(df_clean["latitude"].shift().iloc[1:])
    lon1 = np.radians(df_clean["longitude"].shift().iloc[1:])
    lat2 = np.radians(df_clean["latitude"].iloc[1:])
    lon2 = np.radians(df_clean["longitude"].iloc[1:])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
    distances = R * c
    summary["total_distance_km"] = distances.sum()
    sog = telemetry_speed_over_ground_series(df_clean)
    if sog is not None and sog.notna().any():
        summary["avg_speed_knots"] = float(sog.mean())
    return summary


_SOLAR_PANEL_RAW_COLUMNS: tuple[tuple[str, str], ...] = (
    ("panelPower1", "Panel 1"),
    ("panelPower3", "Panel 2"),
    ("panelPower4", "Panel 3"),
)


def _empty_power_analytics() -> dict:
    return {
        "net_energy_wh": 0.0,
        "avg_daily_solar_wh": 0.0,
        "avg_daily_draw_wh": 0.0,
        "estimated_hours_to_depletion": None,
        "estimated_hours_to_full": None,
        "slope_wh_per_hour": None,
        "daily_budgets": [],
        "peak_solar_day": None,
        "estimated_lifetime_label": "N/A",
    }


def _calculate_power_analytics(
    power_df: pd.DataFrame,
    solar_df: pd.DataFrame,
    battery_max_wh: float,
    *,
    soc_floor_pct: float = 15.0,
    trend_hours: float = 24.0,
) -> dict:
    """Extended power analytics for report KPIs and chart trendlines."""
    analytics = _empty_power_analytics()
    if power_df.empty or "gliderTimeStamp" not in power_df.columns:
        return analytics

    power_working = power_df.copy()
    power_working["gliderTimeStamp"] = utils.parse_timestamp_column(
        power_working["gliderTimeStamp"], errors="coerce", utc=True
    )
    power_working = power_working.dropna(subset=["gliderTimeStamp"]).sort_values("gliderTimeStamp")
    if len(power_working) < 2:
        return analytics

    solar_wh_series = (
        pd.to_numeric(power_working.get("solarPowerGenerated"), errors="coerce").fillna(0) / 1000.0
    )
    draw_wh_series = (
        pd.to_numeric(power_working.get("outputPortPower"), errors="coerce").fillna(0) / 1000.0
    )
    battery_wh_series = (
        pd.to_numeric(power_working.get("totalBatteryPower"), errors="coerce")
    ) / 1000.0

    total_solar_wh = float(solar_wh_series.sum())
    total_draw_wh = float(draw_wh_series.sum())
    analytics["net_energy_wh"] = total_solar_wh - total_draw_wh

    day_index = power_working["gliderTimeStamp"].dt.floor("D")
    daily_solar = solar_wh_series.groupby(day_index).sum()
    daily_draw = draw_wh_series.groupby(day_index).sum()
    daily_budgets = []
    for day, solar_wh in daily_solar.items():
        daily_budgets.append(
            {
                "date": day.date().isoformat(),
                "solar_wh": float(solar_wh),
                "draw_wh": float(daily_draw.get(day, 0.0)),
            }
        )
    analytics["daily_budgets"] = daily_budgets

    num_days = max(len(daily_solar), 1)
    analytics["avg_daily_solar_wh"] = total_solar_wh / num_days
    analytics["avg_daily_draw_wh"] = total_draw_wh / num_days

    if not daily_solar.empty:
        peak_day = daily_solar.idxmax()
        analytics["peak_solar_day"] = peak_day.date().isoformat()

    trend_cutoff = power_working["gliderTimeStamp"].max() - timedelta(hours=trend_hours)
    trend_df = power_working[power_working["gliderTimeStamp"] >= trend_cutoff].copy()
    if len(trend_df) >= 2 and battery_wh_series.notna().any():
        trend_battery = (
            pd.to_numeric(trend_df.get("totalBatteryPower"), errors="coerce") / 1000.0
        ).dropna()
        trend_times = trend_df.loc[trend_battery.index, "gliderTimeStamp"]
        if len(trend_battery) >= 2:
            hours_since_start = (
                trend_times - trend_times.iloc[0]
            ).dt.total_seconds().to_numpy(dtype=float) / 3600.0
            slope, intercept = np.polyfit(hours_since_start, trend_battery.to_numpy(dtype=float), 1)
            analytics["slope_wh_per_hour"] = float(slope)
            current_wh = float(battery_wh_series.dropna().iloc[-1])
            floor_wh = battery_max_wh * (soc_floor_pct / 100.0)
            if slope < -0.01:
                hours_to_floor = (current_wh - floor_wh) / abs(slope)
                if hours_to_floor > 0:
                    analytics["estimated_hours_to_depletion"] = float(hours_to_floor)
                    analytics["estimated_lifetime_label"] = (
                        f"{hours_to_floor:.0f} h to {soc_floor_pct:.0f}% SoC"
                    )
            elif slope > 0.01:
                hours_to_full = (battery_max_wh - current_wh) / slope
                if hours_to_full > 0:
                    analytics["estimated_hours_to_full"] = float(hours_to_full)
                    analytics["estimated_lifetime_label"] = (
                        f"Charging — full in ~{hours_to_full:.0f} h"
                    )
            else:
                analytics["estimated_lifetime_label"] = "Stable"

    return analytics


def _calculate_power_summary(
    power_df: pd.DataFrame,
    solar_df: pd.DataFrame,
    *,
    battery_max_wh: Optional[float] = None,
) -> dict:
    summary = {"avg_total_input_W": 0.0, "avg_total_output_W": 0.0, "avg_solar_panel_W": {}}
    summary.update(_empty_power_analytics())
    if not power_df.empty and "gliderTimeStamp" in power_df.columns and len(power_df) > 1:
        power_df_working = power_df.copy()
        power_df_working["gliderTimeStamp"] = utils.parse_timestamp_column(
            power_df_working["gliderTimeStamp"], errors="coerce", utc=True
        )
        power_df_working = power_df_working.dropna(subset=["gliderTimeStamp"]).sort_values("gliderTimeStamp")
        duration_hours = 0.0
        if len(power_df_working) > 1:
            duration_hours = (
                power_df_working["gliderTimeStamp"].max() - power_df_working["gliderTimeStamp"].min()
            ).total_seconds() / 3600
        if duration_hours > 0:
            if "solarPowerGenerated" in power_df_working.columns:
                total_input_wh = power_df_working["solarPowerGenerated"].sum() / 1000
                summary["avg_total_input_W"] = total_input_wh / duration_hours
            if "outputPortPower" in power_df_working.columns:
                total_output_wh = power_df_working["outputPortPower"].sum() / 1000
                summary["avg_total_output_W"] = total_output_wh / duration_hours
    if not solar_df.empty and "gliderTimeStamp" in solar_df.columns and len(solar_df) > 1:
        solar_df_working = solar_df.copy()
        solar_df_working["gliderTimeStamp"] = utils.parse_timestamp_column(
            solar_df_working["gliderTimeStamp"], errors="coerce", utc=True
        )
        solar_df_working = solar_df_working.dropna(subset=["gliderTimeStamp"]).sort_values("gliderTimeStamp")
        duration_hours_solar = 0.0
        if len(solar_df_working) > 1:
            duration_hours_solar = (
                solar_df_working["gliderTimeStamp"].max() - solar_df_working["gliderTimeStamp"].min()
            ).total_seconds() / 3600
        if duration_hours_solar > 0:
            for col_name, panel_label in _SOLAR_PANEL_RAW_COLUMNS:
                if col_name in solar_df_working.columns:
                    total_panel_wh = solar_df_working[col_name].sum() / 1000
                    summary["avg_solar_panel_W"][panel_label] = total_panel_wh / duration_hours_solar
    if battery_max_wh is not None:
        summary.update(
            _calculate_power_analytics(power_df, solar_df, battery_max_wh)
        )
    return summary


def _calculate_ctd_summary(df: pd.DataFrame) -> dict:
    summary: dict = {}
    if df.empty:
        return summary
    for col in ["WaterTemperature", "Salinity", "Conductivity"]:
        if col in df.columns and pd.api.types.is_numeric_dtype(df[col]):
            series = df[col].dropna()
            if not series.empty:
                summary[col] = {"avg": series.mean(), "min": series.min(), "max": series.max()}
    return summary


def _calculate_weather_summary(df: pd.DataFrame) -> dict:
    summary: dict = {}
    if df.empty:
        return summary
    for col in ["AirTemperature", "WindSpeed", "BarometricPressure"]:
        if col in df.columns and pd.api.types.is_numeric_dtype(df[col]):
            series = df[col].dropna()
            if not series.empty:
                summary[col] = {"avg": series.mean(), "min": series.min(), "max": series.max()}
    if "WindGust" in df.columns and pd.api.types.is_numeric_dtype(df["WindGust"]):
        series = df["WindGust"].dropna()
        if not series.empty:
            summary["WindGust"] = {"max": series.max()}
    return summary


def _calculate_wave_summary(df: pd.DataFrame) -> dict:
    summary: dict = {}
    if df.empty:
        return summary
    for col in ["SignificantWaveHeight", "WavePeriod"]:
        if col in df.columns and pd.api.types.is_numeric_dtype(df[col]):
            series = df[col].dropna()
            if not series.empty:
                summary[col] = {"avg": series.mean(), "min": series.min(), "max": series.max()}
    return summary


def _calculate_error_summary(df: pd.DataFrame) -> dict:
    summary: dict = {"total_errors": 0, "by_severity": {}}
    if df.empty:
        return summary
    summary["total_errors"] = len(df)
    col = None
    if "errorSeverity" in df.columns and not df["errorSeverity"].isnull().all():
        col = df["errorSeverity"]
    elif "parsed_severity" in df.columns and not df["parsed_severity"].isnull().all():
        col = df["parsed_severity"]
    if col is not None:
        summary["by_severity"] = col.fillna("Unknown").astype(str).value_counts().to_dict()
    return summary


def _normalize_note_event_time(note: models.MissionNote) -> datetime:
    parsed_prefix_time = utils.parse_mission_note_datetime_prefix(note.content)
    event_time = parsed_prefix_time or note.created_at_utc
    if event_time.tzinfo is None or event_time.tzinfo.utcoffset(event_time) is None:
        return event_time.replace(tzinfo=timezone.utc)
    return event_time.astimezone(timezone.utc)


def _build_mission_note_annotations(
    mission_notes: List[models.MissionNote],
    telemetry_df_filtered: pd.DataFrame,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    start_utc: Optional[datetime] = None,
    end_utc_exclusive: Optional[datetime] = None,
    max_annotations: int = 24,
) -> List[Dict[str, Any]]:
    if not mission_notes or telemetry_df_filtered.empty:
        return []
    if "lastLocationFix" not in telemetry_df_filtered.columns:
        return []
    telemetry_points = telemetry_df_filtered.dropna(subset=["lastLocationFix", "latitude", "longitude"]).copy()
    if telemetry_points.empty:
        return []
    telemetry_points["lastLocationFix"] = utils.parse_timestamp_column(
        telemetry_points["lastLocationFix"], errors="coerce", utc=True
    )
    telemetry_points = telemetry_points.dropna(subset=["lastLocationFix"])
    if telemetry_points.empty:
        return []
    telemetry_points = telemetry_points.sort_values("lastLocationFix")
    report_start_utc = _utc_lower_bound(start_date, start_utc)
    report_end_utc = _utc_upper_exclusive(end_date, end_utc_exclusive)
    annotations: List[Dict[str, Any]] = []
    for note in mission_notes:
        if hasattr(note, "include_in_report") and not note.include_in_report:
            continue
        event_time = _normalize_note_event_time(note)
        if report_start_utc and event_time < report_start_utc:
            continue
        if report_end_utc and event_time >= report_end_utc:
            continue
        time_deltas = (telemetry_points["lastLocationFix"] - event_time).abs()
        nearest_idx = time_deltas.idxmin()
        nearest_point = telemetry_points.loc[nearest_idx]
        note_text = utils.strip_mission_note_datetime_prefix(note.content)
        if not note_text:
            note_text = note.content
        note_text = note_text.strip()
        annotations.append(
            {
                "note_id": note.id,
                "latitude": float(nearest_point["latitude"]),
                "longitude": float(nearest_point["longitude"]),
                "event_time": event_time,
                "matched_telemetry_time": nearest_point["lastLocationFix"],
                "full_note_text": note_text,
                "created_by_username": note.created_by_username,
            }
        )
    annotations.sort(key=lambda item: item["event_time"])
    if len(annotations) > max_annotations:
        logger.info(
            "Truncating mission note annotations from %s to %s entries to keep map readable.",
            len(annotations),
            max_annotations,
        )
        annotations = annotations[-max_annotations:]
    return annotations


def _field_pairs(fields: List[tuple]) -> List[Tuple[str, str]]:
    return [(label, str(value)) for label, value in fields if value]


def _utc_lower_bound(
    start_date: Optional[date],
    start_utc: Optional[datetime],
) -> Optional[pd.Timestamp]:
    if start_utc is not None:
        ts = pd.Timestamp(start_utc)
        return ts.tz_localize("UTC") if ts.tz is None else ts.tz_convert("UTC")
    if start_date is not None:
        return pd.to_datetime(start_date).tz_localize("UTC")
    return None


def _utc_upper_exclusive(
    end_date: Optional[date],
    end_utc_exclusive: Optional[datetime],
) -> Optional[pd.Timestamp]:
    if end_utc_exclusive is not None:
        ts = pd.Timestamp(end_utc_exclusive)
        return ts.tz_localize("UTC") if ts.tz is None else ts.tz_convert("UTC")
    if end_date is not None:
        return pd.to_datetime(end_date).tz_localize("UTC") + timedelta(days=1)
    return None


def _filter_report_dataframes(
    *,
    telemetry_df: pd.DataFrame,
    power_df: pd.DataFrame,
    solar_df: pd.DataFrame,
    ctd_df: pd.DataFrame,
    weather_df: pd.DataFrame,
    wave_df: pd.DataFrame,
    fluorometer_df: pd.DataFrame,
    ais_df: pd.DataFrame,
    error_df: pd.DataFrame,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    start_utc: Optional[datetime] = None,
    end_utc_exclusive: Optional[datetime] = None,
) -> tuple:
    """Return filtered copies (UTC inclusive lower bound, exclusive upper bound)."""
    lower = _utc_lower_bound(start_date, start_utc)
    upper = _utc_upper_exclusive(end_date, end_utc_exclusive)
    telemetry_df_filtered = telemetry_df.copy()
    power_df_filtered = power_df.copy()
    solar_df_filtered = solar_df.copy()
    ctd_df_filtered = ctd_df.copy()
    weather_df_filtered = weather_df.copy()
    wave_df_filtered = wave_df.copy()
    fluorometer_df_filtered = fluorometer_df.copy()
    ais_df_filtered = ais_df.copy()
    error_df_filtered = error_df.copy()

    if not telemetry_df_filtered.empty and "lastLocationFix" in telemetry_df_filtered.columns:
        telemetry_df_filtered["lastLocationFix"] = utils.parse_timestamp_column(
            telemetry_df_filtered["lastLocationFix"], errors="coerce", utc=True
        )
        if lower is not None:
            telemetry_df_filtered = telemetry_df_filtered[telemetry_df_filtered["lastLocationFix"] >= lower]
        if upper is not None:
            telemetry_df_filtered = telemetry_df_filtered[telemetry_df_filtered["lastLocationFix"] < upper]

    if not power_df_filtered.empty and "gliderTimeStamp" in power_df_filtered.columns:
        power_df_filtered["gliderTimeStamp"] = utils.parse_timestamp_column(
            power_df_filtered["gliderTimeStamp"], errors="coerce", utc=True
        )
        if lower is not None:
            power_df_filtered = power_df_filtered[power_df_filtered["gliderTimeStamp"] >= lower]
        if upper is not None:
            power_df_filtered = power_df_filtered[power_df_filtered["gliderTimeStamp"] < upper]

    if not solar_df_filtered.empty and "gliderTimeStamp" in solar_df_filtered.columns:
        solar_df_filtered["gliderTimeStamp"] = utils.parse_timestamp_column(
            solar_df_filtered["gliderTimeStamp"], errors="coerce", utc=True
        )
        if lower is not None:
            solar_df_filtered = solar_df_filtered[solar_df_filtered["gliderTimeStamp"] >= lower]
        if upper is not None:
            solar_df_filtered = solar_df_filtered[solar_df_filtered["gliderTimeStamp"] < upper]

    if not ctd_df_filtered.empty:
        ctd_df_processed = preprocess_ctd_df(ctd_df_filtered)
        if not ctd_df_processed.empty and "Timestamp" in ctd_df_processed.columns:
            if lower is not None:
                ctd_df_processed = ctd_df_processed[ctd_df_processed["Timestamp"] >= lower]
            if upper is not None:
                ctd_df_processed = ctd_df_processed[ctd_df_processed["Timestamp"] < upper]
            ctd_df_filtered = ctd_df_processed

    if not weather_df_filtered.empty:
        weather_df_processed = preprocess_weather_df(weather_df_filtered)
        if not weather_df_processed.empty and "Timestamp" in weather_df_processed.columns:
            if lower is not None:
                weather_df_processed = weather_df_processed[weather_df_processed["Timestamp"] >= lower]
            if upper is not None:
                weather_df_processed = weather_df_processed[weather_df_processed["Timestamp"] < upper]
            weather_df_filtered = weather_df_processed

    if not wave_df_filtered.empty:
        wave_df_processed = preprocess_wave_df(wave_df_filtered)
        if not wave_df_processed.empty and "Timestamp" in wave_df_processed.columns:
            if lower is not None:
                wave_df_processed = wave_df_processed[wave_df_processed["Timestamp"] >= lower]
            if upper is not None:
                wave_df_processed = wave_df_processed[wave_df_processed["Timestamp"] < upper]
            wave_df_filtered = wave_df_processed

    if not fluorometer_df_filtered.empty:
        fluorometer_df_processed = preprocess_fluorometer_df(fluorometer_df_filtered)
        if not fluorometer_df_processed.empty and "Timestamp" in fluorometer_df_processed.columns:
            if lower is not None:
                fluorometer_df_processed = fluorometer_df_processed[
                    fluorometer_df_processed["Timestamp"] >= lower
                ]
            if upper is not None:
                fluorometer_df_processed = fluorometer_df_processed[
                    fluorometer_df_processed["Timestamp"] < upper
                ]
            fluorometer_df_filtered = fluorometer_df_processed

    if not ais_df_filtered.empty:
        ais_df_processed = preprocess_ais_df(ais_df_filtered)
        if not ais_df_processed.empty and "LastSeenTimestamp" in ais_df_processed.columns:
            if lower is not None:
                ais_df_processed = ais_df_processed[ais_df_processed["LastSeenTimestamp"] >= lower]
            if upper is not None:
                ais_df_processed = ais_df_processed[ais_df_processed["LastSeenTimestamp"] < upper]
            ais_df_filtered = ais_df_processed

    if not error_df_filtered.empty and "timeStamp" in error_df_filtered.columns:
        error_df_filtered["timeStamp"] = utils.parse_timestamp_column(
            error_df_filtered["timeStamp"], errors="coerce", utc=True
        )
        if lower is not None:
            error_df_filtered = error_df_filtered[error_df_filtered["timeStamp"] >= lower]
        if upper is not None:
            error_df_filtered = error_df_filtered[error_df_filtered["timeStamp"] < upper]
    if not error_df_filtered.empty:
        error_df_filtered = preprocess_error_df(error_df_filtered)

    return (
        telemetry_df_filtered,
        power_df_filtered,
        solar_df_filtered,
        ctd_df_filtered,
        weather_df_filtered,
        wave_df_filtered,
        fluorometer_df_filtered,
        ais_df_filtered,
        error_df_filtered,
    )


def _sensor_bullet_label(sensor: models.MissionSensor) -> str:
    return sensor.sensor_identifier or ""


def _instrument_row_from_model(
    inst: models.MissionInstrument,
    sensors: Optional[List[models.MissionSensor]] = None,
) -> Dict[str, Any]:
    bullets = [_sensor_bullet_label(s) for s in (sensors or []) if _sensor_bullet_label(s)]
    return {
        "name": inst.instrument_identifier or "",
        "description": inst.instrument_long_name or inst.instrument_short_name or "",
        "manufacturer": inst.instrument_manufacturer or "",
        "serial": inst.instrument_serial or "",
        "sensor_bullets": bullets,
    }


def _instrument_section_rows(
    session: SQLModelSession,
    items: List[models.MissionInstrument],
) -> List[Dict[str, Any]]:
    if not items:
        return []
    rows: List[Dict[str, Any]] = []
    for inst in items:
        sensors = session.exec(
            select(models.MissionSensor).where(models.MissionSensor.instrument_id == inst.id)
        ).all()
        rows.append(_instrument_row_from_model(inst, sensors))
    return rows


def _load_instrument_blocks(
    session: SQLModelSession, mission_id: str
) -> List[Tuple[str, List[Dict[str, Any]]]]:
    mission_base = utils.deployment_mission_code_from_mission_id(mission_id)
    instruments = session.exec(
        select(models.MissionInstrument)
        .where(
            or_(
                models.MissionInstrument.mission_id == mission_id,
                models.MissionInstrument.mission_id == mission_base,
            )
        )
        .order_by(
            models.MissionInstrument.data_logger_type,
            models.MissionInstrument.is_platform_direct,
            models.MissionInstrument.instrument_identifier,
        )
    ).all()
    flight_instruments: List[models.MissionInstrument] = []
    science_instruments: List[models.MissionInstrument] = []
    platform_instruments: List[models.MissionInstrument] = []
    for inst in instruments:
        if inst.is_platform_direct:
            platform_instruments.append(inst)
        elif inst.data_logger_type == "flight":
            flight_instruments.append(inst)
        elif inst.data_logger_type == "science":
            science_instruments.append(inst)

    science_title = "Science computer instruments"
    if science_instruments and getattr(science_instruments[0], "data_logger_serial", None):
        science_title = f"Science computer instruments (SN: {science_instruments[0].data_logger_serial})"

    return [
        ("Platform direct instruments", _instrument_section_rows(session, platform_instruments)),
        ("Flight computer instruments", _instrument_section_rows(session, flight_instruments)),
        (science_title, _instrument_section_rows(session, science_instruments)),
    ]


def _offload_log_event_utc(log: models.OffloadLog) -> Optional[datetime]:
    raw = log.offload_end_time_utc or log.offload_start_time_utc or log.log_timestamp_utc
    if raw is None:
        return None
    if isinstance(raw, datetime):
        ts = raw
    else:
        try:
            ts = pd.to_datetime(raw, utc=True).to_pydatetime()
        except Exception:  # noqa: BLE001
            return None
    if ts.tzinfo is None or ts.tzinfo.utcoffset(ts) is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _filter_offload_logs_for_window(
    offload_rows: Sequence[models.OffloadLog],
    start_utc: Optional[datetime],
    end_utc_exclusive: Optional[datetime],
) -> List[models.OffloadLog]:
    """Keep operator offload rows whose event time falls in [start_utc, end_utc_exclusive)."""
    if not offload_rows:
        return []
    matched: List[models.OffloadLog] = []
    for log in offload_rows:
        event_ts = _offload_log_event_utc(log)
        if event_ts is None:
            continue
        if start_utc is not None and event_ts < start_utc:
            continue
        if end_utc_exclusive is not None and event_ts >= end_utc_exclusive:
            continue
        matched.append(log)
    return matched


def _sensor_card_flags(
    mission_overview: Optional[models.MissionOverview],
) -> tuple[bool, bool]:
    enabled_sensor_cards: List[str] = []
    if mission_overview and mission_overview.enabled_sensor_cards:
        try:
            enabled_sensor_cards = json.loads(mission_overview.enabled_sensor_cards)
        except Exception:  # noqa: BLE001
            enabled_sensor_cards = []
    has_c3 = (
        any(s in enabled_sensor_cards for s in ("fluorometer", "c3")) or not enabled_sensor_cards
    )
    normalized = {str(c).strip().lower() for c in enabled_sensor_cards}
    has_wg_vm4 = ("wg_vm4" in normalized) or not enabled_sensor_cards
    return has_c3, has_wg_vm4


def _mission_blocks_from_deployment(
    *,
    mission_id: str,
    sensor_tracker_deployment: Optional[models.SensorTrackerDeployment],
    mission_goals: Optional[List[models.MissionGoal]],
    vehicle_name: Optional[str],
    source_path: Optional[str],
) -> List[Tuple[str, List[Tuple[str, str]]]]:
    mission_title_for_fields = (
        sensor_tracker_deployment.title
        if sensor_tracker_deployment and sensor_tracker_deployment.title
        else mission_id
    )
    platform_for_fields = (
        sensor_tracker_deployment.platform_name
        if sensor_tracker_deployment and sensor_tracker_deployment.platform_name
        else vehicle_name
    )
    return [
        (
            f"{mission_title_for_fields} / {platform_for_fields or 'Unknown platform'}",
            _field_pairs(
                [
                    (
                        "Start time",
                        sensor_tracker_deployment.start_time.strftime("%Y-%m-%d %H:%M:%S UTC")
                        if sensor_tracker_deployment and sensor_tracker_deployment.start_time
                        else None,
                    ),
                    (
                        "End time",
                        sensor_tracker_deployment.end_time.strftime("%Y-%m-%d %H:%M:%S UTC")
                        if sensor_tracker_deployment and sensor_tracker_deployment.end_time
                        else None,
                    ),
                    (
                        "Deployment description",
                        sensor_tracker_deployment.deployment_comment if sensor_tracker_deployment else None,
                    ),
                    ("Sea/Region", sensor_tracker_deployment.sea_name if sensor_tracker_deployment else None),
                    (
                        "Mission goals",
                        "; ".join(goal.description for goal in (mission_goals or [])) if mission_goals else None,
                    ),
                    ("Agencies", sensor_tracker_deployment.agencies if sensor_tracker_deployment else None),
                    ("Roles", sensor_tracker_deployment.agencies_role if sensor_tracker_deployment else None),
                    (
                        "Acknowledgements",
                        sensor_tracker_deployment.acknowledgement if sensor_tracker_deployment else None,
                    ),
                ]
            ),
        ),
        (
            "Deployment and recovery",
            _field_pairs(
                [
                    ("Deployment cruise", sensor_tracker_deployment.deployment_cruise if sensor_tracker_deployment else None),
                    ("Recovery cruise", sensor_tracker_deployment.recovery_cruise if sensor_tracker_deployment else None),
                    (
                        "Deployment personnel",
                        sensor_tracker_deployment.deployment_personnel if sensor_tracker_deployment else None,
                    ),
                    (
                        "Recovery personnel",
                        sensor_tracker_deployment.recovery_personnel if sensor_tracker_deployment else None,
                    ),
                    ("Program and technical", sensor_tracker_deployment.program if sensor_tracker_deployment else None),
                ]
            ),
        ),
        (
            "Publication, attribution, and data",
            _field_pairs(
                [
                    ("Publisher", sensor_tracker_deployment.publisher_name if sensor_tracker_deployment else None),
                    ("Publisher email", sensor_tracker_deployment.publisher_email if sensor_tracker_deployment else None),
                    ("Publisher URL", sensor_tracker_deployment.publisher_url if sensor_tracker_deployment else None),
                    (
                        "Publisher country",
                        sensor_tracker_deployment.publisher_country if sensor_tracker_deployment else None,
                    ),
                    (
                        "Data repository",
                        sensor_tracker_deployment.data_repository_link if sensor_tracker_deployment else None,
                    ),
                    ("Creator", sensor_tracker_deployment.creator_name if sensor_tracker_deployment else None),
                    ("Creator email", sensor_tracker_deployment.creator_email if sensor_tracker_deployment else None),
                    ("Creator URL", sensor_tracker_deployment.creator_url if sensor_tracker_deployment else None),
                    ("Contributor", sensor_tracker_deployment.contributor_name if sensor_tracker_deployment else None),
                    ("Contributor role", sensor_tracker_deployment.contributor_role if sensor_tracker_deployment else None),
                    (
                        "Contributor email",
                        sensor_tracker_deployment.contributors_email if sensor_tracker_deployment else None,
                    ),
                    ("Remote data source", source_path),
                ]
            ),
        ),
    ]


def _append_landscape_sections(
    story: List[Any],
    *,
    plots_to_include: List[str],
    power_df: pd.DataFrame,
    solar_df: pd.DataFrame,
    battery_max_wh: float,
    ctd_df: pd.DataFrame,
    weather_df: pd.DataFrame,
    wave_df: pd.DataFrame,
    fluorometer_df: pd.DataFrame,
    period_label: str,
    has_c3_card_enabled: bool,
    has_wg_vm4_card_enabled: bool,
    fluorometer_channel_map: Optional[dict],
    offload_rows: List[models.OffloadLog],
    include_wg_vm4: bool,
) -> None:
    from reportlab.platypus import NextPageTemplate, PageBreak

    landscape_any = False

    def _append_landscape_section(section_flow: List[Any]) -> None:
        nonlocal landscape_any
        if not section_flow:
            return
        if not landscape_any:
            story.append(NextPageTemplate("landscape"))
            story.append(PageBreak())
            landscape_any = True
        else:
            story.append(PageBreak())
        story.extend(section_flow)

    if "power" in plots_to_include and not power_df.empty:
        _append_landscape_section(
            sections.build_power_section(
                power_df,
                period_label,
                solar_df=solar_df,
                battery_max_wh=battery_max_wh,
            )
        )
    if "ctd" in plots_to_include and not ctd_df.empty:
        _append_landscape_section(sections.build_ctd_section(ctd_df, period_label))
    if "weather" in plots_to_include and not weather_df.empty:
        _append_landscape_section(sections.build_weather_section(weather_df, period_label))
    if "waves" in plots_to_include and not wave_df.empty:
        _append_landscape_section(sections.build_waves_section(wave_df, period_label))
    if "c3" in plots_to_include and has_c3_card_enabled and not fluorometer_df.empty:
        _append_landscape_section(
            sections.build_c3_section(
                fluorometer_df,
                period_label,
                channel_map=fluorometer_channel_map,
            )
        )
    if include_wg_vm4 and "wg_vm4" in plots_to_include and has_wg_vm4_card_enabled and offload_rows:
        _append_landscape_section(
            sections.build_wg_vm4_offloads_landscape_section(offload_rows, period_label)
        )

    if landscape_any:
        from reportlab.platypus import NextPageTemplate, PageBreak

        story.append(NextPageTemplate("portrait"))
        story.append(PageBreak())


def _build_period_block(
    story: List[Any],
    *,
    styles: dict,
    mission_id: str,
    plots_to_include: List[str],
    period_label: str,
    telemetry_df_filtered: pd.DataFrame,
    power_df_filtered: pd.DataFrame,
    solar_df_filtered: pd.DataFrame,
    ctd_df_filtered: pd.DataFrame,
    weather_df_filtered: pd.DataFrame,
    wave_df_filtered: pd.DataFrame,
    fluorometer_df_filtered: pd.DataFrame,
    ais_df_filtered: pd.DataFrame,
    error_df_filtered: pd.DataFrame,
    mission_notes: Optional[List[models.MissionNote]],
    start_date: Optional[date],
    end_date: Optional[date],
    start_utc: Optional[datetime],
    end_utc_exclusive: Optional[datetime],
    week_header_flowables: Optional[List[Any]],
    telemetry_compact: bool,
    include_ais: bool,
    include_errors: bool,
    include_wg_vm4: bool,
    has_c3_card_enabled: bool,
    has_wg_vm4_card_enabled: bool,
    fluorometer_channel_map: Optional[dict],
    offload_rows: List[models.OffloadLog],
    battery_max_wh: float,
) -> None:
    from reportlab.platypus import PageBreak, Paragraph

    report_period_telemetry_summary = _calculate_telemetry_summary(telemetry_df_filtered)
    telemetry_note_annotations = _build_mission_note_annotations(
        mission_notes=mission_notes or [],
        telemetry_df_filtered=telemetry_df_filtered,
        start_date=start_date,
        end_date=end_date,
        start_utc=start_utc,
        end_utc_exclusive=end_utc_exclusive,
    )

    if week_header_flowables:
        story.extend(week_header_flowables)
        story.append(PageBreak())

    if "telemetry" in plots_to_include and not telemetry_df_filtered.empty:
        story.extend(
            sections.build_telemetry_section(
                telemetry_df_filtered,
                telemetry_note_annotations,
                report_distance_km=float(report_period_telemetry_summary.get("total_distance_km", 0.0)),
                section_title="Telemetry",
                compact=telemetry_compact,
                keep_together=True,
            )
        )
        notes_flow = sections.build_mission_notes_section(telemetry_note_annotations)
        if notes_flow:
            story.append(PageBreak())
            story.extend(notes_flow)

    _append_landscape_sections(
        story,
        plots_to_include=plots_to_include,
        power_df=power_df_filtered,
        solar_df=solar_df_filtered,
        battery_max_wh=battery_max_wh,
        ctd_df=ctd_df_filtered,
        weather_df=weather_df_filtered,
        wave_df=wave_df_filtered,
        fluorometer_df=fluorometer_df_filtered,
        period_label=period_label,
        has_c3_card_enabled=has_c3_card_enabled,
        has_wg_vm4_card_enabled=has_wg_vm4_card_enabled,
        fluorometer_channel_map=fluorometer_channel_map,
        offload_rows=offload_rows,
        include_wg_vm4=include_wg_vm4,
    )

    if include_errors and "errors" in plots_to_include and not error_df_filtered.empty:
        story.extend(sections.build_errors_section(error_df_filtered, period_label))
        story.append(PageBreak())

    if include_ais and "ais" in plots_to_include and not ais_df_filtered.empty:
        story.extend(
            sections.build_ais_section(
                ais_df_filtered,
                start_date=start_date,
                end_date=end_date,
            )
        )


def _build_back_matter(
    story: List[Any],
    *,
    plots_to_include: List[str],
    mission_date_range_str: str,
    ais_df: pd.DataFrame,
    error_df: pd.DataFrame,
    start_date: Optional[date],
    end_date: Optional[date],
) -> None:
    """EOM-only closing sections. WG-VM4 offloads are rendered per ISO week, not here."""
    from reportlab.platypus import PageBreak

    if "ais" in plots_to_include and not ais_df.empty:
        story.extend(
            sections.build_ais_section(
                ais_df,
                start_date=start_date,
                end_date=end_date,
            )
        )
        story.append(PageBreak())

    if "errors" in plots_to_include and not error_df.empty:
        story.extend(sections.build_errors_section(error_df, mission_date_range_str))


def write_mission_pdf(
    *,
    file_path: Path,
    mission_id: str,
    title_for_pdf: str,
    telemetry_df: pd.DataFrame,
    power_df: pd.DataFrame,
    solar_df: pd.DataFrame,
    ctd_df: pd.DataFrame,
    weather_df: pd.DataFrame,
    wave_df: pd.DataFrame,
    fluorometer_df: pd.DataFrame,
    ais_df: pd.DataFrame,
    error_df: pd.DataFrame,
    mission_goals: Optional[List[models.MissionGoal]],
    mission_notes: Optional[List[models.MissionNote]],
    start_date: Optional[date],
    end_date: Optional[date],
    plots_to_include: List[str],
    sensor_tracker_deployment: Optional[models.SensorTrackerDeployment],
    mission_overview: Optional[models.MissionOverview],
    source_path: Optional[str],
    offload_logs: Optional[List[models.OffloadLog]] = None,
    report_mode: Literal["weekly", "end_of_mission"] = "weekly",
) -> None:
    """Build and write the mission PDF. See module docstring for weekly vs end-of-mission layout."""
    from reportlab.platypus import PageBreak, Paragraph, NextPageTemplate

    offload_rows = list(offload_logs or [])
    is_eom = report_mode == "end_of_mission"

    if not telemetry_df.empty and "lastLocationFix" in telemetry_df.columns:
        telemetry_df = telemetry_df.copy()
        telemetry_df["lastLocationFix"] = utils.parse_timestamp_column(
            telemetry_df["lastLocationFix"], errors="coerce", utc=True
        )

    vehicle_name = None
    if not power_df.empty and "vehicleName" in power_df.columns:
        vehicle_name_series = power_df["vehicleName"].dropna()
        if not vehicle_name_series.empty:
            vehicle_name = vehicle_name_series.iloc[0]

    mission_start_dt, mission_end_dt = resolve_mission_time_bounds(
        sensor_tracker_start=(
            sensor_tracker_deployment.start_time if sensor_tracker_deployment else None
        ),
        sensor_tracker_end=(
            sensor_tracker_deployment.end_time if sensor_tracker_deployment else None
        ),
        telemetry_df=telemetry_df,
    )
    mission_date_range_str = (
        f"{mission_start_dt.strftime('%Y-%m-%d %H:%M')} – "
        f"{mission_end_dt.strftime('%Y-%m-%d %H:%M')} UTC"
    )

    date_range_str = mission_date_range_str if is_eom else "From mission start to mission end"
    if not is_eom:
        if start_date and end_date:
            date_range_str = f"{start_date.isoformat()} → {end_date.isoformat()} (UTC dates, inclusive window)"
        elif start_date:
            date_range_str = f"From {start_date.isoformat()} (UTC) to mission end"
        elif end_date:
            date_range_str = f"From mission start to {end_date.isoformat()} (UTC)"

    platform_name = (
        sensor_tracker_deployment.platform_name
        if sensor_tracker_deployment and sensor_tracker_deployment.platform_name
        else (vehicle_name or "Unknown")
    )
    mission_title = (
        sensor_tracker_deployment.title
        if sensor_tracker_deployment and sensor_tracker_deployment.title
        else mission_id
    )
    generated_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    mission_header = f"{mission_id} · {platform_name} · {date_range_str}"

    has_c3_card_enabled, has_wg_vm4_card_enabled = _sensor_card_flags(mission_overview)
    fluorometer_channel_map = (
        sensor_tracker_deployment.fluorometer_channel_map
        if sensor_tracker_deployment and has_c3_card_enabled
        else None
    )
    battery_apu = (
        getattr(mission_overview, "battery_apu_count", None) if mission_overview else None
    )
    battery_max_wh = theoretical_max_wh(battery_apu)

    mission_telemetry_summary = _calculate_telemetry_summary(telemetry_df)
    mission_power_summary = _calculate_power_summary(
        power_df, solar_df, battery_max_wh=battery_max_wh
    )
    mission_ctd_summary = _calculate_ctd_summary(
        preprocess_ctd_df(ctd_df) if not ctd_df.empty else ctd_df
    )
    mission_weather_summary = _calculate_weather_summary(
        preprocess_weather_df(weather_df) if not weather_df.empty else weather_df
    )
    mission_wave_summary = _calculate_wave_summary(
        preprocess_wave_df(wave_df) if not wave_df.empty else wave_df
    )
    mission_error_summary = _calculate_error_summary(
        preprocess_error_df(error_df) if not error_df.empty else error_df
    )
    ais_stats = get_ais_summary_stats(ais_df, max_age_hours=24 * 365) if not ais_df.empty else {}

    styles = build_paragraph_styles()
    doc = WeeklyReportDocTemplate(
        str(file_path),
        mission_header=mission_header[:200],
        report_title=title_for_pdf,
        generated_utc=generated_utc,
        styles=styles,
    )

    story: List[Any] = []
    story.extend(
        build_platform_cover_flowables(
            title=title_for_pdf,
            platform_name=str(platform_name),
            mission_id=mission_id,
            mission_title=str(mission_title),
            date_range_str=date_range_str,
            generated_utc=generated_utc,
            logo_path=get_report_logo_path(),
        )
    )
    story.append(NextPageTemplate("portrait"))
    story.append(PageBreak())
    story.extend(sections.build_toc_intro())
    story.append(PageBreak())

    mission_blocks = _mission_blocks_from_deployment(
        mission_id=mission_id,
        sensor_tracker_deployment=sensor_tracker_deployment,
        mission_goals=mission_goals,
        vehicle_name=vehicle_name,
        source_path=source_path,
    )
    md_main = sections.build_mission_details_sections(mission_blocks[:2])
    md_pub = sections.build_mission_details_sections(mission_blocks[2:])
    if md_main or md_pub:
        story.append(Paragraph("Mission details", styles["Heading1"]))
        if md_main:
            story.extend(md_main)
        if md_pub:
            if md_main:
                story.append(PageBreak())
            story.extend(md_pub)
        story.append(PageBreak())

    if sensor_tracker_deployment:
        session_gen = get_db_session()
        session = next(session_gen)
        try:
            blocks = _load_instrument_blocks(session, mission_id)
            inst_flow = sections.build_instruments_page(blocks)
            if inst_flow:
                story.append(Paragraph("Glider instruments and sensors", styles["Heading1"]))
                story.extend(inst_flow)
                story.append(PageBreak())
        finally:
            session.close()

    if is_eom:
        story.append(Paragraph("Executive summary", styles["Heading1"]))
        story.extend(
            sections.build_executive_summary(
                mission_telemetry_summary=mission_telemetry_summary,
                report_period_power_summary=mission_power_summary,
                report_period_ctd_summary=mission_ctd_summary,
                report_period_weather_summary=mission_weather_summary,
                report_period_wave_summary=mission_wave_summary,
                report_period_error_summary=mission_error_summary,
                ais_total_vessels=int(ais_stats.get("total_vessels", 0)),
                mission_goals=mission_goals,
                mission_date_range_str=mission_date_range_str,
            )
        )
        story.append(PageBreak())

        if "telemetry" in plots_to_include and not telemetry_df.empty:
            story.append(Paragraph("Mission telemetry overview", styles["Heading1"]))
            full_notes = _build_mission_note_annotations(
                mission_notes=mission_notes or [],
                telemetry_df_filtered=telemetry_df,
            )
            story.extend(
                sections.build_telemetry_section(
                    telemetry_df,
                    full_notes,
                    report_distance_km=float(mission_telemetry_summary.get("total_distance_km", 0.0)),
                    section_title="Telemetry",
                    compact=False,
                    keep_together=True,
                )
            )
            story.append(PageBreak())

        windows = compute_iso_week_windows(mission_start_dt, mission_end_dt)
        prev_week_power_summary: Optional[dict] = None
        for window in windows:
            (
                t_f,
                p_f,
                s_f,
                c_f,
                w_f,
                wa_f,
                fl_f,
                _ais_f,
                e_f,
            ) = _filter_report_dataframes(
                telemetry_df=telemetry_df,
                power_df=power_df,
                solar_df=solar_df,
                ctd_df=ctd_df,
                weather_df=weather_df,
                wave_df=wave_df,
                fluorometer_df=fluorometer_df,
                ais_df=ais_df,
                error_df=error_df,
                start_utc=window.start_utc,
                end_utc_exclusive=window.end_utc_exclusive,
            )
            if t_f.empty:
                story.extend(sections.build_week_skipped_stub(week_label=window.label))
                story.append(PageBreak())
                continue

            week_offload_rows = _filter_offload_logs_for_window(
                offload_rows,
                window.start_utc,
                window.end_utc_exclusive,
            )

            week_summary = sections.build_week_summary_header(
                week_label=window.label,
                mission_telemetry_summary=mission_telemetry_summary,
                report_period_telemetry_summary=_calculate_telemetry_summary(t_f),
                report_period_power_summary=_calculate_power_summary(
                    p_f, s_f, battery_max_wh=battery_max_wh
                ),
                report_period_ctd_summary=_calculate_ctd_summary(c_f),
                report_period_weather_summary=_calculate_weather_summary(w_f),
                report_period_wave_summary=_calculate_wave_summary(wa_f),
                report_period_error_summary=_calculate_error_summary(e_f),
                period_label=window.label,
                prior_power_summary=prev_week_power_summary,
            )
            _build_period_block(
                story,
                styles=styles,
                mission_id=mission_id,
                plots_to_include=plots_to_include,
                period_label=window.label,
                telemetry_df_filtered=t_f,
                power_df_filtered=p_f,
                solar_df_filtered=s_f,
                ctd_df_filtered=c_f,
                weather_df_filtered=w_f,
                wave_df_filtered=wa_f,
                fluorometer_df_filtered=fl_f,
                ais_df_filtered=pd.DataFrame(),
                error_df_filtered=e_f,
                mission_notes=mission_notes,
                start_date=None,
                end_date=None,
                start_utc=window.start_utc,
                end_utc_exclusive=window.end_utc_exclusive,
                week_header_flowables=week_summary,
                telemetry_compact=False,
                include_ais=False,
                include_errors=False,
                include_wg_vm4=True,
                has_c3_card_enabled=has_c3_card_enabled,
                has_wg_vm4_card_enabled=has_wg_vm4_card_enabled,
                fluorometer_channel_map=fluorometer_channel_map,
                offload_rows=week_offload_rows,
                battery_max_wh=battery_max_wh,
            )
            prev_week_power_summary = _calculate_power_summary(
                p_f, s_f, battery_max_wh=battery_max_wh
            )
            story.append(PageBreak())

        _build_back_matter(
            story,
            plots_to_include=plots_to_include,
            mission_date_range_str=mission_date_range_str,
            ais_df=ais_df,
            error_df=error_df,
            start_date=None,
            end_date=None,
        )
    else:
        (
            telemetry_df_filtered,
            power_df_filtered,
            solar_df_filtered,
            ctd_df_filtered,
            weather_df_filtered,
            wave_df_filtered,
            fluorometer_df_filtered,
            ais_df_filtered,
            error_df_filtered,
        ) = _filter_report_dataframes(
            telemetry_df=telemetry_df,
            power_df=power_df,
            solar_df=solar_df,
            ctd_df=ctd_df,
            weather_df=weather_df,
            wave_df=wave_df,
            fluorometer_df=fluorometer_df,
            ais_df=ais_df,
            error_df=error_df,
            start_date=start_date,
            end_date=end_date,
        )

        report_period_telemetry_summary = _calculate_telemetry_summary(telemetry_df_filtered)
        prior_power_summary: Optional[dict] = None
        if start_date and end_date:
            prev_start, prev_end = _previous_report_date_window(start_date, end_date)
            prior_power_summary = _prior_power_summary_for_window(
                power_df=power_df,
                solar_df=solar_df,
                telemetry_df=telemetry_df,
                ctd_df=ctd_df,
                weather_df=weather_df,
                wave_df=wave_df,
                fluorometer_df=fluorometer_df,
                ais_df=ais_df,
                error_df=error_df,
                start_date=prev_start,
                end_date=prev_end,
                battery_max_wh=battery_max_wh,
            )
        story.append(Paragraph("Mission summary statistics", styles["Heading1"]))
        story.extend(
            sections.build_summary(
                mission_telemetry_summary=mission_telemetry_summary,
                report_period_telemetry_summary=report_period_telemetry_summary,
                report_period_power_summary=_calculate_power_summary(
                    power_df_filtered, solar_df_filtered, battery_max_wh=battery_max_wh
                ),
                report_period_ctd_summary=_calculate_ctd_summary(ctd_df_filtered),
                report_period_weather_summary=_calculate_weather_summary(weather_df_filtered),
                report_period_wave_summary=_calculate_wave_summary(wave_df_filtered),
                report_period_error_summary=_calculate_error_summary(error_df_filtered),
                mission_goals=mission_goals,
                period_label=date_range_str,
                prior_power_summary=prior_power_summary,
            )
        )
        story.append(PageBreak())

        _build_period_block(
            story,
            styles=styles,
            mission_id=mission_id,
            plots_to_include=plots_to_include,
            period_label=date_range_str,
            telemetry_df_filtered=telemetry_df_filtered,
            power_df_filtered=power_df_filtered,
            solar_df_filtered=solar_df_filtered,
            ctd_df_filtered=ctd_df_filtered,
            weather_df_filtered=weather_df_filtered,
            wave_df_filtered=wave_df_filtered,
            fluorometer_df_filtered=fluorometer_df_filtered,
            ais_df_filtered=ais_df_filtered,
            error_df_filtered=error_df_filtered,
            mission_notes=mission_notes,
            start_date=start_date,
            end_date=end_date,
            start_utc=None,
            end_utc_exclusive=None,
            week_header_flowables=None,
            telemetry_compact=False,
            include_ais=True,
            include_errors=True,
            include_wg_vm4=True,
            has_c3_card_enabled=has_c3_card_enabled,
            has_wg_vm4_card_enabled=has_wg_vm4_card_enabled,
            fluorometer_channel_map=fluorometer_channel_map,
            offload_rows=offload_rows,
            battery_max_wh=battery_max_wh,
        )

    doc.multiBuild(story)


def write_weekly_mission_pdf(
    *,
    file_path: Path,
    mission_id: str,
    title_for_pdf: str,
    telemetry_df: pd.DataFrame,
    power_df: pd.DataFrame,
    solar_df: pd.DataFrame,
    ctd_df: pd.DataFrame,
    weather_df: pd.DataFrame,
    wave_df: pd.DataFrame,
    fluorometer_df: pd.DataFrame,
    ais_df: pd.DataFrame,
    error_df: pd.DataFrame,
    mission_goals: Optional[List[models.MissionGoal]],
    mission_notes: Optional[List[models.MissionNote]],
    start_date: Optional[date],
    end_date: Optional[date],
    plots_to_include: List[str],
    sensor_tracker_deployment: Optional[models.SensorTrackerDeployment],
    mission_overview: Optional[models.MissionOverview],
    source_path: Optional[str],
    offload_logs: Optional[List[models.OffloadLog]] = None,
    report_mode: Literal["weekly", "end_of_mission"] = "weekly",
) -> None:
    """Backward-compatible alias for write_mission_pdf."""
    write_mission_pdf(
        file_path=file_path,
        mission_id=mission_id,
        title_for_pdf=title_for_pdf,
        telemetry_df=telemetry_df,
        power_df=power_df,
        solar_df=solar_df,
        ctd_df=ctd_df,
        weather_df=weather_df,
        wave_df=wave_df,
        fluorometer_df=fluorometer_df,
        ais_df=ais_df,
        error_df=error_df,
        mission_goals=mission_goals,
        mission_notes=mission_notes,
        start_date=start_date,
        end_date=end_date,
        plots_to_include=plots_to_include,
        sensor_tracker_deployment=sensor_tracker_deployment,
        mission_overview=mission_overview,
        source_path=source_path,
        offload_logs=offload_logs,
        report_mode=report_mode,
    )
