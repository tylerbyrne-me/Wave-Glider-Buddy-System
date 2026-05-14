"""Filter mission data, assemble Platypus story, and write weekly PDF reports."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from sqlalchemy import or_
from sqlmodel import Session as SQLModelSession, select

from .. import models, utils
from ..db import get_db_session
from ..processors import (
    preprocess_ais_df,
    preprocess_ctd_df,
    preprocess_error_df,
    preprocess_fluorometer_df,
    preprocess_wave_df,
    preprocess_weather_df,
    telemetry_speed_over_ground_series,
)
from .constants import LOGO_PATH, REPORTS_ROOT
from .styling import WeeklyReportDocTemplate, build_paragraph_styles
from . import sections

logger = logging.getLogger(__name__)


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


def _calculate_power_summary(power_df: pd.DataFrame, solar_df: pd.DataFrame) -> dict:
    summary = {"avg_total_input_W": 0.0, "avg_total_output_W": 0.0, "avg_solar_panel_W": {}}
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
            for i in range(6):
                col_name = f"inputPower_{i}"
                if col_name in solar_df_working.columns:
                    total_panel_wh = solar_df_working[col_name].sum() / 1000
                    summary["avg_solar_panel_W"][f"Panel {i}"] = total_panel_wh / duration_hours_solar
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
    report_start_utc = pd.to_datetime(start_date).tz_localize("UTC") if start_date else None
    report_end_utc = pd.to_datetime(end_date).tz_localize("UTC") + timedelta(days=1) if end_date else None
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
    start_date: Optional[date],
    end_date: Optional[date],
) -> tuple:
    """Return filtered copies (same logic as legacy generate_weekly_report)."""
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
        if start_date:
            telemetry_df_filtered = telemetry_df_filtered[
                telemetry_df_filtered["lastLocationFix"] >= pd.to_datetime(start_date).tz_localize("UTC")
            ]
        if end_date:
            end_date_inclusive = pd.to_datetime(end_date).tz_localize("UTC") + timedelta(days=1)
            telemetry_df_filtered = telemetry_df_filtered[
                telemetry_df_filtered["lastLocationFix"] < end_date_inclusive
            ]

    if not power_df_filtered.empty and "gliderTimeStamp" in power_df_filtered.columns:
        power_df_filtered["gliderTimeStamp"] = utils.parse_timestamp_column(
            power_df_filtered["gliderTimeStamp"], errors="coerce", utc=True
        )
        if start_date:
            power_df_filtered = power_df_filtered[
                power_df_filtered["gliderTimeStamp"] >= pd.to_datetime(start_date).tz_localize("UTC")
            ]
        if end_date:
            end_date_inclusive = pd.to_datetime(end_date).tz_localize("UTC") + timedelta(days=1)
            power_df_filtered = power_df_filtered[power_df_filtered["gliderTimeStamp"] < end_date_inclusive]

    if not solar_df_filtered.empty and "gliderTimeStamp" in solar_df_filtered.columns:
        solar_df_filtered["gliderTimeStamp"] = utils.parse_timestamp_column(
            solar_df_filtered["gliderTimeStamp"], errors="coerce", utc=True
        )
        if start_date:
            solar_df_filtered = solar_df_filtered[
                solar_df_filtered["gliderTimeStamp"] >= pd.to_datetime(start_date).tz_localize("UTC")
            ]
        if end_date:
            end_date_inclusive = pd.to_datetime(end_date).tz_localize("UTC") + timedelta(days=1)
            solar_df_filtered = solar_df_filtered[solar_df_filtered["gliderTimeStamp"] < end_date_inclusive]

    if not ctd_df_filtered.empty:
        ctd_df_processed = preprocess_ctd_df(ctd_df_filtered)
        if not ctd_df_processed.empty and "Timestamp" in ctd_df_processed.columns:
            if start_date:
                ctd_df_processed = ctd_df_processed[
                    ctd_df_processed["Timestamp"] >= pd.to_datetime(start_date).tz_localize("UTC")
                ]
            if end_date:
                end_date_inclusive = pd.to_datetime(end_date).tz_localize("UTC") + timedelta(days=1)
                ctd_df_processed = ctd_df_processed[ctd_df_processed["Timestamp"] < end_date_inclusive]
            ctd_df_filtered = ctd_df_processed

    if not weather_df_filtered.empty:
        weather_df_processed = preprocess_weather_df(weather_df_filtered)
        if not weather_df_processed.empty and "Timestamp" in weather_df_processed.columns:
            if start_date:
                weather_df_processed = weather_df_processed[
                    weather_df_processed["Timestamp"] >= pd.to_datetime(start_date).tz_localize("UTC")
                ]
            if end_date:
                end_date_inclusive = pd.to_datetime(end_date).tz_localize("UTC") + timedelta(days=1)
                weather_df_processed = weather_df_processed[
                    weather_df_processed["Timestamp"] < end_date_inclusive
                ]
            weather_df_filtered = weather_df_processed

    if not wave_df_filtered.empty:
        wave_df_processed = preprocess_wave_df(wave_df_filtered)
        if not wave_df_processed.empty and "Timestamp" in wave_df_processed.columns:
            if start_date:
                wave_df_processed = wave_df_processed[
                    wave_df_processed["Timestamp"] >= pd.to_datetime(start_date).tz_localize("UTC")
                ]
            if end_date:
                end_date_inclusive = pd.to_datetime(end_date).tz_localize("UTC") + timedelta(days=1)
                wave_df_processed = wave_df_processed[wave_df_processed["Timestamp"] < end_date_inclusive]
            wave_df_filtered = wave_df_processed

    if not fluorometer_df_filtered.empty:
        fluorometer_df_processed = preprocess_fluorometer_df(fluorometer_df_filtered)
        if not fluorometer_df_processed.empty and "Timestamp" in fluorometer_df_processed.columns:
            if start_date:
                fluorometer_df_processed = fluorometer_df_processed[
                    fluorometer_df_processed["Timestamp"] >= pd.to_datetime(start_date).tz_localize("UTC")
                ]
            if end_date:
                end_date_inclusive = pd.to_datetime(end_date).tz_localize("UTC") + timedelta(days=1)
                fluorometer_df_processed = fluorometer_df_processed[
                    fluorometer_df_processed["Timestamp"] < end_date_inclusive
                ]
            fluorometer_df_filtered = fluorometer_df_processed

    if not ais_df_filtered.empty:
        ais_df_processed = preprocess_ais_df(ais_df_filtered)
        if not ais_df_processed.empty and "LastSeenTimestamp" in ais_df_processed.columns:
            if start_date:
                ais_df_processed = ais_df_processed[
                    ais_df_processed["LastSeenTimestamp"] >= pd.to_datetime(start_date).tz_localize("UTC")
                ]
            if end_date:
                end_date_inclusive = pd.to_datetime(end_date).tz_localize("UTC") + timedelta(days=1)
                ais_df_processed = ais_df_processed[ais_df_processed["LastSeenTimestamp"] < end_date_inclusive]
            ais_df_filtered = ais_df_processed

    if not error_df_filtered.empty and "timeStamp" in error_df_filtered.columns:
        error_df_filtered["timeStamp"] = utils.parse_timestamp_column(
            error_df_filtered["timeStamp"], errors="coerce", utc=True
        )
        if start_date:
            error_df_filtered = error_df_filtered[
                error_df_filtered["timeStamp"] >= pd.to_datetime(start_date).tz_localize("UTC")
            ]
        if end_date:
            end_date_inclusive = pd.to_datetime(end_date).tz_localize("UTC") + timedelta(days=1)
            error_df_filtered = error_df_filtered[error_df_filtered["timeStamp"] < end_date_inclusive]
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


def _load_instrument_blocks(session: SQLModelSession, mission_id: str) -> List[Tuple[str, List[str]]]:
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

    def _instrument_section_lines(items: List[models.MissionInstrument]) -> List[str]:
        if not items:
            return ["(None)"]
        lines: List[str] = []
        for inst in items:
            inst_name = inst.instrument_name or inst.instrument_identifier
            inst_serial = inst.instrument_serial or "N/A"
            if inst_serial != "N/A":
                lines.append(f"ITEM:{inst_name} ({inst_serial})")
            else:
                lines.append(f"ITEM:{inst_name}")
            sensors = session.exec(
                select(models.MissionSensor).where(models.MissionSensor.instrument_id == inst.id)
            ).all()
            for sensor in sensors:
                lines.append(f"SUB:{sensor.sensor_identifier}")
        return lines

    science_title = "Science computer instruments"
    if science_instruments and getattr(science_instruments[0], "data_logger_serial", None):
        science_title = f"Science computer instruments (SN: {science_instruments[0].data_logger_serial})"

    return [
        ("Platform direct instruments", _instrument_section_lines(platform_instruments)),
        ("Flight computer instruments", _instrument_section_lines(flight_instruments)),
        (science_title, _instrument_section_lines(science_instruments)),
    ]


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
) -> None:
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

    vehicle_name = None
    if not power_df.empty and "vehicleName" in power_df.columns:
        vehicle_name_series = power_df["vehicleName"].dropna()
        if not vehicle_name_series.empty:
            vehicle_name = vehicle_name_series.iloc[0]

    mission_telemetry_summary = _calculate_telemetry_summary(telemetry_df)
    report_period_telemetry_summary = _calculate_telemetry_summary(telemetry_df_filtered)
    report_period_power_summary = _calculate_power_summary(power_df_filtered, solar_df_filtered)
    report_period_ctd_summary = _calculate_ctd_summary(ctd_df_filtered)
    report_period_weather_summary = _calculate_weather_summary(weather_df_filtered)
    report_period_wave_summary = _calculate_wave_summary(wave_df_filtered)
    report_period_error_summary = _calculate_error_summary(error_df_filtered)

    telemetry_note_annotations = _build_mission_note_annotations(
        mission_notes=mission_notes or [],
        telemetry_df_filtered=telemetry_df_filtered,
        start_date=start_date,
        end_date=end_date,
    )

    date_range_str = "From mission start to mission end"
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

    enabled_sensor_cards: List[str] = []
    if mission_overview and mission_overview.enabled_sensor_cards:
        try:
            enabled_sensor_cards = json.loads(mission_overview.enabled_sensor_cards)
        except Exception:  # noqa: BLE001
            enabled_sensor_cards = []
    has_c3_card_enabled = any(
        sensor_name in enabled_sensor_cards for sensor_name in ("fluorometer", "c3")
    ) or not enabled_sensor_cards

    styles = build_paragraph_styles()
    doc = WeeklyReportDocTemplate(
        str(file_path),
        mission_header=mission_header[:200],
        report_title=title_for_pdf,
        generated_utc=generated_utc,
        styles=styles,
    )

    from reportlab.platypus import PageBreak, Paragraph, NextPageTemplate, Spacer

    story: List[Any] = []
    story.extend(
        sections.build_cover(
            title_for_pdf=title_for_pdf,
            platform_name=str(platform_name),
            mission_id=mission_id,
            mission_title=str(mission_title),
            date_range_str=date_range_str,
            generated_utc=generated_utc,
            logo_path=LOGO_PATH,
        )
    )
    story.append(NextPageTemplate("portrait"))
    story.append(PageBreak())
    story.extend(sections.build_toc_intro())
    story.append(PageBreak())

    mission_title_for_fields = (
        sensor_tracker_deployment.title if sensor_tracker_deployment and sensor_tracker_deployment.title else mission_id
    )
    platform_for_fields = (
        sensor_tracker_deployment.platform_name
        if sensor_tracker_deployment and sensor_tracker_deployment.platform_name
        else vehicle_name
    )
    mission_blocks: List[Tuple[str, List[Tuple[str, str]]]] = [
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

    story.append(Paragraph("Mission summary statistics", styles["Heading1"]))
    story.extend(
        sections.build_summary(
            mission_telemetry_summary=mission_telemetry_summary,
            report_period_telemetry_summary=report_period_telemetry_summary,
            report_period_power_summary=report_period_power_summary,
            report_period_ctd_summary=report_period_ctd_summary,
            report_period_weather_summary=report_period_weather_summary,
            report_period_wave_summary=report_period_wave_summary,
            report_period_error_summary=report_period_error_summary,
            mission_goals=mission_goals,
            period_label=date_range_str,
        )
    )
    story.append(PageBreak())

    if "telemetry" in plots_to_include and not telemetry_df_filtered.empty:
        story.append(Paragraph("Telemetry track", styles["Heading1"]))
        story.extend(
            sections.build_telemetry_section(
                telemetry_df_filtered,
                telemetry_note_annotations,
                report_distance_km=float(report_period_telemetry_summary.get("total_distance_km", 0.0)),
            )
        )
        notes_flow = sections.build_mission_notes_section(telemetry_note_annotations)
        if notes_flow:
            story.append(PageBreak())
            story.extend(notes_flow)
            story.append(PageBreak())

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

    if "power" in plots_to_include and not power_df_filtered.empty:
        _append_landscape_section(sections.build_power_section(power_df_filtered, date_range_str))
    if "ctd" in plots_to_include and not ctd_df_filtered.empty:
        _append_landscape_section(sections.build_ctd_section(ctd_df_filtered, date_range_str))
    if "weather" in plots_to_include and not weather_df_filtered.empty:
        _append_landscape_section(sections.build_weather_section(weather_df_filtered, date_range_str))
    if "waves" in plots_to_include and not wave_df_filtered.empty:
        _append_landscape_section(sections.build_waves_section(wave_df_filtered, date_range_str))
    if "c3" in plots_to_include and has_c3_card_enabled and not fluorometer_df_filtered.empty:
        _append_landscape_section(sections.build_c3_section(fluorometer_df_filtered, date_range_str))

    if landscape_any:
        story.append(NextPageTemplate("portrait"))
        story.append(PageBreak())

    if "errors" in plots_to_include and not error_df_filtered.empty:
        story.extend(sections.build_errors_section(error_df_filtered, date_range_str))
        story.append(PageBreak())

    if "ais" in plots_to_include and not ais_df_filtered.empty:
        story.extend(sections.build_ais_section(ais_df_filtered, start_date=start_date, end_date=end_date))

    doc.multiBuild(story)
