import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import matplotlib.image as mpimg
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from datetime import date, timedelta
import logging
import httpx
import asyncio
import json
import numpy as np

from sqlmodel import Session as SQLModelSession, select
from sqlalchemy import or_

from . import models, utils
from .plotting import (plot_ctd_for_report, plot_errors_for_report,
                          plot_mission_notes_page, plot_power_for_report, plot_summary_page,
                          plot_telemetry_page_with_notes, plot_wave_for_report, plot_weather_for_report,
                          render_text_sections, estimate_text_sections_page_count,
                          plot_table_of_contents_page, plot_c3_for_report,
                          report_pdf_rc_context, REPORT_PDF_FONT_PRIMARY)
from .processors import (
    preprocess_ais_df,
    preprocess_ctd_df,
    preprocess_error_df,
    preprocess_fluorometer_df,
    preprocess_wave_df,
    preprocess_weather_df,
    telemetry_speed_over_ground_series,
)
from .summaries import get_ais_summary, get_ais_summary_stats
from .report_view_model import ReportViewModelInput, build_report_view_model
from .report_renderers import RendererRequest, render_report_with_strategy

logger = logging.getLogger(__name__)

# Define the base output directory for reports
REPORTS_ROOT = Path(__file__).resolve().parent.parent.parent / "web" / "static" / "mission_reports"
REPORTS_ROOT.mkdir(parents=True, exist_ok=True)

# Define the path to the company logo. **Please update 'your_logo_name.png' to your actual logo file name.**
LOGO_PATH = Path(__file__).resolve().parent.parent.parent / "web" / "static" / "images" / "otn_logo.png"


def default_weekly_report_date_window() -> tuple[date, date]:
    """UTC calendar window used for default weekly reports (matches admin UI weekly preset)."""
    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=7)
    return start_date, end_date


# Data types loaded for standard weekly / default admin weekly reports (order stable for caches/logs).
WEEKLY_REPORT_DATA_TYPES: List[str] = [
    "telemetry",
    "power",
    "ctd",
    "weather",
    "waves",
    "solar",
    "fluorometer",
    "ais",
    "errors",
]


class WeeklyReportPreflightError(Exception):
    """Raised when every report dataset is empty after load (PDF cannot be built)."""


def load_mission_notes_for_report(session: SQLModelSession, mission_id: str) -> List[models.MissionNote]:
    """Mission notes flagged for inclusion in PDF reports, oldest first."""
    statement = (
        select(models.MissionNote)
        .where(
            models.MissionNote.mission_id == mission_id,
            models.MissionNote.include_in_report == True,  # noqa: E712
        )
        .order_by(models.MissionNote.created_at_utc.asc())
    )
    return session.exec(statement).all()


async def generate_weekly_report_pdf_for_mission(
    session: SQLModelSession,
    mission_id: str,
    *,
    current_user: Optional[models.User],
    options: models.ReportGenerationOptions,
    mission_overview: Optional[models.MissionOverview],
) -> str:
    """Load weekly report inputs and return the generated PDF URL path (does not commit).

    Shared by the admin ``generate-weekly-report`` API and ``create_and_save_weekly_report`` (cron).
    Uses the same ``load_multiple`` scope, date-window rules, and ``ReportGenerationOptions`` as the
    admin route when the same ``options`` instance is passed.
    """
    from .data_service import get_data_service

    data_service = get_data_service()
    data_results = await data_service.load_multiple(
        report_types=WEEKLY_REPORT_DATA_TYPES,
        mission_id=mission_id,
        current_user=current_user,
    )

    telemetry_df = data_results.get("telemetry", (pd.DataFrame(), "", None))[0]
    power_df = data_results.get("power", (pd.DataFrame(), "", None))[0]
    ctd_df = data_results.get("ctd", (pd.DataFrame(), "", None))[0]
    weather_df = data_results.get("weather", (pd.DataFrame(), "", None))[0]
    wave_df = data_results.get("waves", (pd.DataFrame(), "", None))[0]
    solar_df = data_results.get("solar", (pd.DataFrame(), "", None))[0]
    fluorometer_df = data_results.get("fluorometer", (pd.DataFrame(), "", None))[0]
    ais_df = data_results.get("ais", (pd.DataFrame(), "", None))[0]
    error_df = data_results.get("errors", (pd.DataFrame(), "", None))[0]

    for report_type in WEEKLY_REPORT_DATA_TYPES:
        if data_results.get(report_type, (pd.DataFrame(), "", None))[1] == "Error":
            logger.error("Error loading %s data for mission '%s'.", report_type, mission_id)

    frames = [telemetry_df, power_df, solar_df, ctd_df, weather_df, wave_df, fluorometer_df, ais_df, error_df]
    if all(f.empty for f in frames):
        raise WeeklyReportPreflightError(f"No report data available for mission '{mission_id}'.")

    source_path = next(
        (
            result[1]
            for result in data_results.values()
            if isinstance(result, tuple) and len(result) > 1 and result[1] and result[1] != "Error"
        ),
        "Unknown",
    )

    goals_statement = select(models.MissionGoal).where(models.MissionGoal.mission_id == mission_id).order_by(models.MissionGoal.created_at_utc)
    mission_goals = session.exec(goals_statement).all()
    mission_notes = load_mission_notes_for_report(session, mission_id)

    sensor_tracker_deployment = session.exec(
        select(models.SensorTrackerDeployment).where(models.SensorTrackerDeployment.mission_id == mission_id)
    ).first()

    selected_start_date = options.start_date
    selected_end_date = options.end_date
    if selected_start_date is None and selected_end_date is None:
        selected_start_date, selected_end_date = default_weekly_report_date_window()
        logger.info(
            "Weekly report default UTC date window for mission '%s': %s -> %s",
            mission_id,
            selected_start_date.isoformat(),
            selected_end_date.isoformat(),
        )

    return await generate_weekly_report_with_renderer(
        renderer=options.report_renderer,
        mission_id=mission_id,
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
        start_date=selected_start_date,
        end_date=selected_end_date,
        plots_to_include=list(options.plots_to_include),
        custom_filename=options.custom_filename,
        sensor_tracker_deployment=sensor_tracker_deployment,
        mission_overview=mission_overview,
        source_path=source_path,
    )


def _calculate_telemetry_summary(df: pd.DataFrame) -> dict:
    """
    Calculates summary statistics from a telemetry DataFrame for reporting.
    Handles distance traveled and average speed. Uses a vectorized Haversine
    formula for performance.
    """
    summary = {"total_distance_km": 0.0, "avg_speed_knots": 0.0}
    if df.empty or len(df) < 2:
        return summary

    if "lastLocationFix" not in df.columns:
        return summary

    # Ensure timestamp column is comparable (mixed str/Timestamp can raise TypeError on sort).
    df_working = df.copy()
    df_working["lastLocationFix"] = utils.parse_timestamp_column(
        df_working["lastLocationFix"], errors="coerce", utc=True
    )
    df_clean = df_working.dropna(
        subset=["latitude", "longitude", "lastLocationFix"]
    ).sort_values(by="lastLocationFix").copy()
    if len(df_clean) < 2:
        return summary

    # Vectorized Haversine distance calculation
    R = 6371  # Earth radius in kilometers
    lat1 = np.radians(df_clean['latitude'].shift().iloc[1:])
    lon1 = np.radians(df_clean['longitude'].shift().iloc[1:])
    lat2 = np.radians(df_clean['latitude'].iloc[1:])
    lon2 = np.radians(df_clean['longitude'].iloc[1:])

    dlon = lon2 - lon1
    dlat = lat2 - lat1

    a = np.sin(dlat / 2)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2)**2
    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
    distances = R * c
    summary["total_distance_km"] = distances.sum()

    # Calculate average speed (raw or preprocessed column name)
    sog = telemetry_speed_over_ground_series(df_clean)
    if sog is not None and sog.notna().any():
        summary["avg_speed_knots"] = float(sog.mean())

    return summary

def _calculate_power_summary(power_df: pd.DataFrame, solar_df: pd.DataFrame) -> dict:
    """
    Calculates summary statistics from power and solar DataFrames for reporting.
    Computes average power rates in Watts over the report period.
    """
    summary = {
        "avg_total_input_W": 0.0,
        "avg_total_output_W": 0.0,
        "avg_solar_panel_W": {}
    }

    if not power_df.empty and 'gliderTimeStamp' in power_df.columns and len(power_df) > 1:
        power_df_working = power_df.copy()
        power_df_working['gliderTimeStamp'] = utils.parse_timestamp_column(
            power_df_working['gliderTimeStamp'], errors='coerce', utc=True
        )
        power_df_working = power_df_working.dropna(subset=['gliderTimeStamp']).sort_values('gliderTimeStamp')
        duration_hours = 0
        if len(power_df_working) > 1:
            duration_hours = (power_df_working['gliderTimeStamp'].max() - power_df_working['gliderTimeStamp'].min()).total_seconds() / 3600
        if duration_hours > 0:
            # These are in mWh, so sum and convert to Wh, then divide by hours for avg Watts
            if 'solarPowerGenerated' in power_df_working.columns:
                total_input_wh = power_df_working['solarPowerGenerated'].sum() / 1000
                summary["avg_total_input_W"] = total_input_wh / duration_hours
            
            if 'outputPortPower' in power_df_working.columns:
                total_output_wh = power_df_working['outputPortPower'].sum() / 1000
                summary["avg_total_output_W"] = total_output_wh / duration_hours

    if not solar_df.empty and 'gliderTimeStamp' in solar_df.columns and len(solar_df) > 1:
        solar_df_working = solar_df.copy()
        solar_df_working['gliderTimeStamp'] = utils.parse_timestamp_column(
            solar_df_working['gliderTimeStamp'], errors='coerce', utc=True
        )
        solar_df_working = solar_df_working.dropna(subset=['gliderTimeStamp']).sort_values('gliderTimeStamp')
        duration_hours_solar = 0
        if len(solar_df_working) > 1:
            duration_hours_solar = (solar_df_working['gliderTimeStamp'].max() - solar_df_working['gliderTimeStamp'].min()).total_seconds() / 3600
        if duration_hours_solar > 0:
            for i in range(6): # Panels 0-5
                col_name = f'inputPower_{i}'
                if col_name in solar_df_working.columns:
                    # These are in mWh
                    total_panel_wh = solar_df_working[col_name].sum() / 1000
                    avg_panel_w = total_panel_wh / duration_hours_solar
                    summary["avg_solar_panel_W"][f"Panel {i}"] = avg_panel_w
    
    return summary

def _calculate_ctd_summary(df: pd.DataFrame) -> dict:
    """Calculates summary statistics for CTD data for the report period."""
    summary = {}
    if df.empty:
        return summary
    
    for col in ["WaterTemperature", "Salinity", "Conductivity"]:
        if col in df.columns and pd.api.types.is_numeric_dtype(df[col]):
            series = df[col].dropna()
            if not series.empty:
                summary[col] = {
                    "avg": series.mean(),
                    "min": series.min(),
                    "max": series.max(),
                }
    return summary

def _calculate_weather_summary(df: pd.DataFrame) -> dict:
    """Calculates summary statistics for Weather data for the report period."""
    summary = {}
    if df.empty:
        return summary

    for col in ["AirTemperature", "WindSpeed", "BarometricPressure"]:
        if col in df.columns and pd.api.types.is_numeric_dtype(df[col]):
            series = df[col].dropna()
            if not series.empty:
                summary[col] = {
                    "avg": series.mean(),
                    "min": series.min(),
                    "max": series.max(),
                }
    if "WindGust" in df.columns and pd.api.types.is_numeric_dtype(df["WindGust"]):
        series = df["WindGust"].dropna()
        if not series.empty:
            summary["WindGust"] = {"max": series.max()}
            
    return summary

def _calculate_wave_summary(df: pd.DataFrame) -> dict:
    """Calculates summary statistics for Wave data for the report period."""
    summary = {}
    if df.empty:
        return summary

    for col in ["SignificantWaveHeight", "WavePeriod"]:
        if col in df.columns and pd.api.types.is_numeric_dtype(df[col]):
            series = df[col].dropna()
            if not series.empty:
                summary[col] = {
                    "avg": series.mean(),
                    "min": series.min(),
                    "max": series.max(),
                }
    return summary

def _calculate_error_summary(df: pd.DataFrame) -> dict:
    """Calculates summary statistics for vehicle errors for the report period."""
    summary = {"total_errors": 0, "by_severity": {}}
    if df.empty or 'errorSeverity' not in df.columns:
        return summary
    
    summary["total_errors"] = len(df)
    if not df['errorSeverity'].isnull().all():
        summary["by_severity"] = df['errorSeverity'].value_counts().to_dict()
        
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
    """Build the per-note annotation records used by the telemetry-track page.

    The notes panel and the on-map lettered markers share these records, so
    each entry carries the full note text plus a stable letter label assigned
    in chronological order. Long text is no longer truncated here — the panel
    paginates and overflow is sent to the appendix.
    """
    if not mission_notes or telemetry_df_filtered.empty:
        return []
    if "lastLocationFix" not in telemetry_df_filtered.columns:
        return []

    telemetry_points = telemetry_df_filtered.dropna(
        subset=["lastLocationFix", "latitude", "longitude"]
    ).copy()
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
    report_end_utc = (
        pd.to_datetime(end_date).tz_localize("UTC") + timedelta(days=1) if end_date else None
    )

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

    # Letter assignment (cluster-aware: A, A1, A2, B, ...) is delegated to
    # plotting.assign_note_letters at render time so the markers and the
    # notes page stay in sync.
    return annotations


async def generate_weekly_report_with_renderer(
    *,
    renderer: str,
    mission_id: str,
    telemetry_df: pd.DataFrame,
    power_df: pd.DataFrame,
    solar_df: pd.DataFrame,
    ctd_df: pd.DataFrame,
    weather_df: pd.DataFrame,
    wave_df: pd.DataFrame,
    fluorometer_df: pd.DataFrame,
    ais_df: pd.DataFrame,
    error_df: pd.DataFrame,
    mission_goals: Optional[List[models.MissionGoal]] = None,
    mission_notes: Optional[List[models.MissionNote]] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    plots_to_include: Optional[List[str]] = None,
    custom_filename: Optional[str] = None,
    sensor_tracker_deployment: Optional[models.SensorTrackerDeployment] = None,
    mission_overview: Optional[models.MissionOverview] = None,
    source_path: Optional[str] = None,
) -> str:
    def _apply_date_filter(
        df: pd.DataFrame,
        *,
        timestamp_column: str,
        start: Optional[date],
        end: Optional[date],
    ) -> pd.DataFrame:
        if df.empty or timestamp_column not in df.columns:
            return df
        filtered = df.copy()
        filtered[timestamp_column] = utils.parse_timestamp_column(
            filtered[timestamp_column], errors="coerce", utc=True
        )
        if start:
            filtered = filtered[filtered[timestamp_column] >= pd.to_datetime(start).tz_localize("UTC")]
        if end:
            end_inclusive = pd.to_datetime(end).tz_localize("UTC") + timedelta(days=1)
            filtered = filtered[filtered[timestamp_column] < end_inclusive]
        return filtered

    ais_for_view_model = preprocess_ais_df(ais_df.copy()) if not ais_df.empty else ais_df.copy()
    ais_for_view_model = _apply_date_filter(
        ais_for_view_model,
        timestamp_column="LastSeenTimestamp",
        start=start_date,
        end=end_date,
    )
    error_for_view_model = preprocess_error_df(error_df.copy()) if not error_df.empty else error_df.copy()
    error_for_view_model = _apply_date_filter(
        error_for_view_model,
        timestamp_column="Timestamp",
        start=start_date,
        end=end_date,
    )

    mission_title = (
        sensor_tracker_deployment.title
        if sensor_tracker_deployment and sensor_tracker_deployment.title
        else mission_id
    )
    platform_name = (
        sensor_tracker_deployment.platform_name
        if sensor_tracker_deployment and sensor_tracker_deployment.platform_name
        else "Unknown"
    )
    view_model_input = ReportViewModelInput(
        mission_id=mission_id,
        mission_title=mission_title,
        platform_name=platform_name,
        source_path=source_path or "Unknown",
        start_date=start_date,
        end_date=end_date,
        mission_goals=mission_goals or [],
        sensor_tracker_deployment=sensor_tracker_deployment,
        ais_df=ais_for_view_model,
        error_df=error_for_view_model,
    )
    view_model = build_report_view_model(view_model_input)

    report_dir_name = utils.mission_storage_dir_name(mission_id, "reporting")
    report_dir = REPORTS_ROOT / report_dir_name
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    filename_base = f"hybrid_{utils.sanitize_path_segment(mission_id)}_{timestamp}"

    legacy_plots = list(plots_to_include or [])
    external_append_sections: List[str] = []
    if renderer == "hybrid_html":
        legacy_plots = [plot_name for plot_name in legacy_plots if plot_name not in {"errors", "ais"}]
        external_append_sections = ["Vehicle Errors", "AIS Report"]

    async def _run_legacy_renderer() -> str:
        return await generate_weekly_report(
            mission_id=mission_id,
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
            plots_to_include=legacy_plots,
            custom_filename=custom_filename,
            sensor_tracker_deployment=sensor_tracker_deployment,
            mission_overview=mission_overview,
            source_path=source_path,
            external_append_sections=external_append_sections,
        )

    request = RendererRequest(
        renderer=renderer,
        report_dir=report_dir,
        report_filename_base=filename_base,
        view_model=view_model,
    )
    return await render_report_with_strategy(
        request=request,
        reports_root=REPORTS_ROOT,
        run_legacy_renderer=_run_legacy_renderer,
    )


async def generate_weekly_report(
    mission_id: str,
    telemetry_df: pd.DataFrame,
    power_df: pd.DataFrame,
    solar_df: pd.DataFrame,
    ctd_df: pd.DataFrame,
    weather_df: pd.DataFrame,
    wave_df: pd.DataFrame,
    fluorometer_df: pd.DataFrame,
    ais_df: pd.DataFrame,
    error_df: pd.DataFrame,
    mission_goals: Optional[List[models.MissionGoal]] = None,
    mission_notes: Optional[List[models.MissionNote]] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    plots_to_include: Optional[List[str]] = None,
    custom_filename: Optional[str] = None,
    sensor_tracker_deployment: Optional[models.SensorTrackerDeployment] = None,
    mission_overview: Optional[models.MissionOverview] = None,
    source_path: Optional[str] = None,
    external_append_sections: Optional[List[str]] = None,
) -> str:
    """
    Generates a weekly PDF report for a mission with telemetry and power plots.

    Args:
        mission_id: The ID of the mission.
        telemetry_df: DataFrame with telemetry data.
        power_df: DataFrame with power data.
        solar_df: DataFrame with solar data.
        ctd_df: DataFrame with CTD data.
        weather_df: DataFrame with weather data.
        wave_df: DataFrame with wave data.
        fluorometer_df: DataFrame with C3 fluorometer data.
        ais_df: DataFrame with AIS data.
        error_df: DataFrame with vehicle error data.
        start_date: Optional start date for filtering data.
        end_date: Optional end date for filtering data.
        plots_to_include: List of plot types to include (e.g., ['telemetry', 'power']).
        custom_filename: A custom base name for the report file.

    Returns:
        The URL path to the generated PDF report.
    """
    report_timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    safe_mission_id = utils.sanitize_path_segment(mission_id)
    report_dir_name = utils.mission_storage_dir_name(mission_id, "reporting")
    report_dir = REPORTS_ROOT / report_dir_name
    report_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Generating report for mission '{mission_id}' with custom_filename: '{custom_filename}'")
    
    if custom_filename and custom_filename.strip():
        # Sanitize the custom filename to allow only safe characters
        safe_base_name = "".join(c for c in custom_filename if c.isalnum() or c in (' ', '_', '-')).strip() or "report"
        
        logger.info(f"Processed custom_filename to safe_base_name: '{safe_base_name}'")
        
        # Determine title based on filename pattern
        if "end_of_mission" in safe_base_name.lower() or "endofmission" in safe_base_name.lower():
            title_for_pdf = "End of Mission Report"
            logger.info(f"Detected end of mission report - setting title to: '{title_for_pdf}'")
        elif "weekly" in safe_base_name.lower():
            title_for_pdf = "Weekly Mission Report"
            logger.info(f"Detected weekly report - setting title to: '{title_for_pdf}'")
        else:
            title_for_pdf = f"Mission Report: {safe_base_name.replace('_', ' ').title()}"
            logger.info(f"Using generic title: '{title_for_pdf}'")
        
        base_name = safe_base_name.replace(' ', '_')
        if safe_mission_id not in base_name:
            base_name = f"{base_name}_{safe_mission_id}"
        filename = f"{base_name}_{report_timestamp}.pdf"
        logger.info(f"Generated filename: '{filename}'")
    else:
        title_for_pdf = "Weekly Mission Report"
        filename = f"weekly_report_{safe_mission_id}_{report_timestamp}.pdf"
        logger.info(f"No custom_filename provided - using default weekly report. Filename: '{filename}'")

    file_path = report_dir / filename
    url_path = f"/static/mission_reports/{report_dir_name}/{filename}"

    if plots_to_include is None:
        plots_to_include = ["telemetry", "power", "ctd", "weather", "waves", "c3", "errors", "ais"]

    # Create copies to avoid modifying the original dataframes and to define the filtered variables
    telemetry_df_filtered = telemetry_df.copy()
    power_df_filtered = power_df.copy()
    solar_df_filtered = solar_df.copy()
    ctd_df_filtered = ctd_df.copy()
    weather_df_filtered = weather_df.copy()
    wave_df_filtered = wave_df.copy()
    fluorometer_df_filtered = fluorometer_df.copy()
    ais_df_filtered = ais_df.copy()
    error_df_filtered = error_df.copy()

    # Filter dataframes based on the provided date range if they are not empty
    # Use robust parser to handle mixed formats (ISO 8601 and 12hr AM/PM)
    if not telemetry_df_filtered.empty and 'lastLocationFix' in telemetry_df_filtered.columns:
        telemetry_df_filtered['lastLocationFix'] = utils.parse_timestamp_column(
            telemetry_df_filtered['lastLocationFix'], errors='coerce', utc=True
        )
        if start_date:
            telemetry_df_filtered = telemetry_df_filtered[telemetry_df_filtered['lastLocationFix'] >= pd.to_datetime(start_date).tz_localize('UTC')]
        if end_date:
            end_date_inclusive = pd.to_datetime(end_date).tz_localize('UTC') + timedelta(days=1)
            telemetry_df_filtered = telemetry_df_filtered[telemetry_df_filtered['lastLocationFix'] < end_date_inclusive]

    if not power_df_filtered.empty and 'gliderTimeStamp' in power_df_filtered.columns:
        power_df_filtered['gliderTimeStamp'] = utils.parse_timestamp_column(
            power_df_filtered['gliderTimeStamp'], errors='coerce', utc=True
        )
        if start_date:
            power_df_filtered = power_df_filtered[power_df_filtered['gliderTimeStamp'] >= pd.to_datetime(start_date).tz_localize('UTC')]
        if end_date:
            end_date_inclusive = pd.to_datetime(end_date).tz_localize('UTC') + timedelta(days=1)
            power_df_filtered = power_df_filtered[power_df_filtered['gliderTimeStamp'] < end_date_inclusive]

    if not solar_df_filtered.empty and 'gliderTimeStamp' in solar_df_filtered.columns:
        solar_df_filtered['gliderTimeStamp'] = utils.parse_timestamp_column(
            solar_df_filtered['gliderTimeStamp'], errors='coerce', utc=True
        )
        if start_date:
            solar_df_filtered = solar_df_filtered[solar_df_filtered['gliderTimeStamp'] >= pd.to_datetime(start_date).tz_localize('UTC')]
        if end_date:
            end_date_inclusive = pd.to_datetime(end_date).tz_localize('UTC') + timedelta(days=1)
            solar_df_filtered = solar_df_filtered[solar_df_filtered['gliderTimeStamp'] < end_date_inclusive]

    # Preprocess and filter CTD data
    if not ctd_df_filtered.empty:
        ctd_df_processed = preprocess_ctd_df(ctd_df_filtered)
        if not ctd_df_processed.empty and 'Timestamp' in ctd_df_processed.columns:
            if start_date:
                ctd_df_processed = ctd_df_processed[ctd_df_processed['Timestamp'] >= pd.to_datetime(start_date).tz_localize('UTC')]
            if end_date:
                end_date_inclusive = pd.to_datetime(end_date).tz_localize('UTC') + timedelta(days=1)
                ctd_df_processed = ctd_df_processed[ctd_df_processed['Timestamp'] < end_date_inclusive]
            ctd_df_filtered = ctd_df_processed

    # Preprocess and filter Weather data
    if not weather_df_filtered.empty:
        weather_df_processed = preprocess_weather_df(weather_df_filtered)
        if not weather_df_processed.empty and 'Timestamp' in weather_df_processed.columns:
            if start_date:
                weather_df_processed = weather_df_processed[weather_df_processed['Timestamp'] >= pd.to_datetime(start_date).tz_localize('UTC')]
            if end_date:
                end_date_inclusive = pd.to_datetime(end_date).tz_localize('UTC') + timedelta(days=1)
                weather_df_processed = weather_df_processed[weather_df_processed['Timestamp'] < end_date_inclusive]
            weather_df_filtered = weather_df_processed

    # Preprocess and filter Wave data
    if not wave_df_filtered.empty:
        wave_df_processed = preprocess_wave_df(wave_df_filtered)
        if not wave_df_processed.empty and 'Timestamp' in wave_df_processed.columns:
            if start_date:
                wave_df_processed = wave_df_processed[wave_df_processed['Timestamp'] >= pd.to_datetime(start_date).tz_localize('UTC')]
            if end_date:
                end_date_inclusive = pd.to_datetime(end_date).tz_localize('UTC') + timedelta(days=1)
                wave_df_processed = wave_df_processed[wave_df_processed['Timestamp'] < end_date_inclusive]
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
                ais_df_processed = ais_df_processed[
                    ais_df_processed["LastSeenTimestamp"] < end_date_inclusive
                ]
            ais_df_filtered = ais_df_processed

    # Filter Error data
    if not error_df_filtered.empty and 'timeStamp' in error_df_filtered.columns:
        error_df_filtered['timeStamp'] = utils.parse_timestamp_column(
            error_df_filtered['timeStamp'], errors='coerce', utc=True
        )
        if start_date:
            error_df_filtered = error_df_filtered[error_df_filtered['timeStamp'] >= pd.to_datetime(start_date).tz_localize('UTC')]
        if end_date:
            end_date_inclusive = pd.to_datetime(end_date).tz_localize('UTC') + timedelta(days=1)
            error_df_filtered = error_df_filtered[error_df_filtered['timeStamp'] < end_date_inclusive]
    if not error_df_filtered.empty:
        error_df_filtered = preprocess_error_df(error_df_filtered)

    # Extract vehicle name from power data
    vehicle_name = None
    if not power_df.empty and 'vehicleName' in power_df.columns:
        # Get the first non-null vehicle name from the entire (unfiltered) power dataframe
        vehicle_name_series = power_df['vehicleName'].dropna()
        if not vehicle_name_series.empty:
            vehicle_name = vehicle_name_series.iloc[0]

    # Calculate telemetry summaries for the report
    mission_telemetry_summary = _calculate_telemetry_summary(telemetry_df)
    report_period_telemetry_summary = _calculate_telemetry_summary(telemetry_df_filtered)

    # Calculate all other summaries for the report period
    report_period_power_summary = _calculate_power_summary(power_df_filtered, solar_df_filtered)
    report_period_ctd_summary = _calculate_ctd_summary(ctd_df_filtered)
    report_period_weather_summary = _calculate_weather_summary(weather_df_filtered)
    report_period_wave_summary = _calculate_wave_summary(wave_df_filtered)
    report_period_error_summary = _calculate_error_summary(error_df_filtered)

    logger.info(f"Generating weekly report for mission '{mission_id}' at {file_path}")

    telemetry_note_annotations = _build_mission_note_annotations(
        mission_notes=mission_notes or [],
        telemetry_df_filtered=telemetry_df_filtered,
        start_date=start_date,
        end_date=end_date,
    )

    date_range_str = "From mission start to mission end"
    if start_date and end_date:
        date_range_str = f"From: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"
    elif start_date:
        date_range_str = f"From: {start_date.strftime('%Y-%m-%d')} to mission end"
    elif end_date:
        date_range_str = f"From mission start to {end_date.strftime('%Y-%m-%d')}"

    enabled_sensor_cards: List[str] = []
    if mission_overview and mission_overview.enabled_sensor_cards:
        try:
            enabled_sensor_cards = json.loads(mission_overview.enabled_sensor_cards)
        except Exception:
            enabled_sensor_cards = []
    has_c3_card_enabled = any(
        sensor_name in enabled_sensor_cards
        for sensor_name in ("fluorometer", "c3")
    ) or not enabled_sensor_cards

    def _field_lines(fields: List[tuple]) -> List[str]:
        lines = [f"{label}: {value}" for label, value in fields if value]
        return lines or ["(No information available)"]

    def _build_mission_details_sections() -> List[Dict[str, Any]]:
        mission_title = sensor_tracker_deployment.title if sensor_tracker_deployment and sensor_tracker_deployment.title else mission_id
        platform_name = sensor_tracker_deployment.platform_name if sensor_tracker_deployment and sensor_tracker_deployment.platform_name else vehicle_name
        return [
            {
                "heading": f"{mission_title} / {platform_name or 'Unknown Platform'}",
                "lines": _field_lines([
                    ("Start time", sensor_tracker_deployment.start_time.strftime("%Y-%m-%d %H:%M:%S UTC") if sensor_tracker_deployment and sensor_tracker_deployment.start_time else None),
                    ("End time", sensor_tracker_deployment.end_time.strftime("%Y-%m-%d %H:%M:%S UTC") if sensor_tracker_deployment and sensor_tracker_deployment.end_time else None),
                    ("Deployment Description", sensor_tracker_deployment.deployment_comment if sensor_tracker_deployment else None),
                    ("Sea/Region", sensor_tracker_deployment.sea_name if sensor_tracker_deployment else None),
                    ("Mission Goals", "; ".join(goal.description for goal in (mission_goals or [])) if mission_goals else None),
                    ("Agencies", sensor_tracker_deployment.agencies if sensor_tracker_deployment else None),
                    ("Roles", sensor_tracker_deployment.agencies_role if sensor_tracker_deployment else None),
                    ("Acknowledgements", sensor_tracker_deployment.acknowledgement if sensor_tracker_deployment else None),
                ]),
            }
        ]

    with report_pdf_rc_context(), PdfPages(file_path) as pdf:
        mission_details_sections = _build_mission_details_sections() + [
            {
                "heading": "Deployment and Recovery Details",
                "lines": _field_lines([
                    ("Deployment Cruise", sensor_tracker_deployment.deployment_cruise if sensor_tracker_deployment else None),
                    ("Recovery Cruise", sensor_tracker_deployment.recovery_cruise if sensor_tracker_deployment else None),
                    ("Deployment Personnel", sensor_tracker_deployment.deployment_personnel if sensor_tracker_deployment else None),
                    ("Recovery Personnel", sensor_tracker_deployment.recovery_personnel if sensor_tracker_deployment else None),
                    ("Program and Technical", sensor_tracker_deployment.program if sensor_tracker_deployment else None),
                ]),
            },
            {
                "heading": "Publication, Attribution, and Data",
                "lines": _field_lines([
                    ("Publisher", sensor_tracker_deployment.publisher_name if sensor_tracker_deployment else None),
                    ("Publisher Email", sensor_tracker_deployment.publisher_email if sensor_tracker_deployment else None),
                    ("Publisher URL", sensor_tracker_deployment.publisher_url if sensor_tracker_deployment else None),
                    ("Publisher Country", sensor_tracker_deployment.publisher_country if sensor_tracker_deployment else None),
                    ("Data Repository", sensor_tracker_deployment.data_repository_link if sensor_tracker_deployment else None),
                    ("Creator", sensor_tracker_deployment.creator_name if sensor_tracker_deployment else None),
                    ("Creator Email", sensor_tracker_deployment.creator_email if sensor_tracker_deployment else None),
                    ("Creator URL", sensor_tracker_deployment.creator_url if sensor_tracker_deployment else None),
                    ("Contributer", sensor_tracker_deployment.contributor_name if sensor_tracker_deployment else None),
                    ("Contributer Role", sensor_tracker_deployment.contributor_role if sensor_tracker_deployment else None),
                    ("Contributer Email", sensor_tracker_deployment.contributors_email if sensor_tracker_deployment else None),
                    ("Remote Data Source", source_path),
                ]),
            },
        ]
        section_entries: List[Dict[str, Any]] = [
            {"title": "Title Page", "page_count": 1},
            {"title": "Table of Contents", "page_count": 1},
            {"title": "Mission Details", "page_count": estimate_text_sections_page_count(mission_details_sections)},
            {"title": "Glider Instruments and Sensors", "page_count": 1 if sensor_tracker_deployment is not None else 0},
            {"title": "Summary Statistics", "page_count": 1},
            {"title": "Telemetry Map", "page_count": 1 if "telemetry" in plots_to_include and not telemetry_df_filtered.empty else 0},
            {"title": "Mission Notes", "page_count": 1 if "telemetry" in plots_to_include and not telemetry_df_filtered.empty and bool(telemetry_note_annotations) else 0},
            {"title": "Power", "page_count": 1 if "power" in plots_to_include and not power_df_filtered.empty else 0},
            {"title": "CTD", "page_count": 1 if "ctd" in plots_to_include and not ctd_df_filtered.empty else 0},
            {"title": "Weather", "page_count": 1 if "weather" in plots_to_include and not weather_df_filtered.empty else 0},
            {"title": "Waves", "page_count": 1 if "waves" in plots_to_include and not wave_df_filtered.empty else 0},
            {"title": "C3", "page_count": 1 if "c3" in plots_to_include and has_c3_card_enabled and not fluorometer_df_filtered.empty else 0},
            {"title": "Vehicle Errors", "page_count": 1 if "errors" in plots_to_include and not error_df_filtered.empty else 0},
            {"title": "AIS Report", "page_count": 1 if "ais" in plots_to_include and not ais_df_filtered.empty else 0},
        ]
        for section_name in (external_append_sections or []):
            section_entries.append({"title": section_name, "page_count": 1})
        running_page = 1
        toc_entries: List[Dict[str, Any]] = []
        for entry in section_entries:
            count = int(entry["page_count"])
            if count <= 0:
                continue
            toc_entries.append({"title": entry["title"], "page_number": running_page})
            running_page += count
        total_pages = running_page - 1
        page_num = 0

        def add_footer_and_save(fig_to_save):
            """Adds a page number footer to the figure and saves it to the PDF."""
            nonlocal page_num
            page_num += 1
            # Add footer text to the bottom right of the figure.
            fig_to_save.text(
                0.95,
                0.01,
                f"Page {page_num} of {total_pages}",
                ha="right",
                va="bottom",
                size=8,
                color="gray",
                family=REPORT_PDF_FONT_PRIMARY,
            )
            pdf.savefig(fig_to_save)
            plt.close(fig_to_save)

        # --- Page 1: Title Page ---
        fig = plt.figure(figsize=(8.27, 11.69))  # A4 size

        # Start drawing from the top of the page.
        current_y = 0.90
        fig.text(0.5, current_y, title_for_pdf, ha="center", size=24, weight="bold", wrap=True, family=REPORT_PDF_FONT_PRIMARY)

        # --- Add Logo Below Title ---
        if LOGO_PATH.exists():
            try:
                logo_img = mpimg.imread(LOGO_PATH)
                # Define logo dimensions as a fraction of the figure size
                logo_width = 0.2
                logo_height = 0.1
                # Calculate position to center it horizontally
                logo_left = 0.5 - (logo_width / 2)
                # Position it vertically below the title, with padding
                logo_bottom = current_y - logo_height - 0.05

                ax_logo = fig.add_axes([logo_left, logo_bottom, logo_width, logo_height], zorder=1)
                ax_logo.imshow(logo_img)
                ax_logo.axis('off')  # Hide the axes ticks and labels
                
                # Update current_y to be below the logo for the next text element
                current_y = logo_bottom - 0.05
            except Exception as e:
                logger.warning(f"Could not load or place logo on report: {e}")
                current_y -= 0.20  # Leave a gap if logo fails
        else:
            current_y -= 0.15  # Leave a gap if no logo

        platform_name = sensor_tracker_deployment.platform_name if sensor_tracker_deployment and sensor_tracker_deployment.platform_name else (vehicle_name or "Unknown")
        mission_title = sensor_tracker_deployment.title if sensor_tracker_deployment and sensor_tracker_deployment.title else mission_id
        fig.text(0.5, current_y, f"Platform Name: {platform_name}", ha="center", size=18, wrap=True, family=REPORT_PDF_FONT_PRIMARY)

        current_y -= 0.07
        fig.text(0.5, current_y, f"mID: {mission_id}    Mission Title: {mission_title}", ha="center", size=14, wrap=True, family=REPORT_PDF_FONT_PRIMARY)
        current_y -= 0.05

        fig.text(0.5, current_y, date_range_str, ha="center", size=16, wrap=True, family=REPORT_PDF_FONT_PRIMARY)
        current_y -= 0.05
        fig.text(
            0.5,
            current_y,
            f"Generated on: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
            ha="center",
            size=12,
            wrap=True,
            family=REPORT_PDF_FONT_PRIMARY,
        )

        add_footer_and_save(fig)

        # --- Page 2: Table of Contents ---
        plot_table_of_contents_page(add_footer_and_save, toc_entries)

        # --- Mission Details (includes deployment/recovery and publication blocks) ---
        render_text_sections(add_footer_and_save, page_title="Mission Details", sections=mission_details_sections)

        # --- Mission Summary ---
        try:
            plot_summary_page(
                add_footer_and_save,
                mission_telemetry_summary,
                report_period_telemetry_summary,
                report_period_power_summary,
                report_period_ctd_summary,
                report_period_weather_summary,
                report_period_wave_summary,
                report_period_error_summary,
                mission_goals=mission_goals,
            )
        except Exception as e:
            logger.error(f"Failed to generate summary page for mission '{mission_id}': {e}", exc_info=True)
            fig_err = plt.figure(figsize=(8.27, 11.69))
            fig_err.text(0.5, 0.5, f"Error generating summary page:\n{e}", ha='center', va='center', color='red', wrap=True, family=REPORT_PDF_FONT_PRIMARY)
            add_footer_and_save(fig_err)

        # --- Sensor Tracker Metadata (if available) ---
        if sensor_tracker_deployment:
            try:
                # Deployment mission code for instrument rows (matches missions router lookups)
                mission_base = utils.deployment_mission_code_from_mission_id(mission_id)

                from ..core.db import get_db_session
                session_gen = get_db_session()
                session = next(session_gen)
                try:
                    instruments = session.exec(
                        select(models.MissionInstrument).where(
                            or_(
                                models.MissionInstrument.mission_id == mission_id,
                                models.MissionInstrument.mission_id == mission_base,
                            )
                        ).order_by(
                            models.MissionInstrument.data_logger_type,
                            models.MissionInstrument.is_platform_direct,
                            models.MissionInstrument.instrument_identifier
                        )
                    ).all()

                    logger.info(f"Found {len(instruments)} instruments for mission '{mission_id}' (base: '{mission_base}')")

                    flight_instruments = []
                    science_instruments = []
                    platform_instruments = []

                    for inst in instruments:
                        if inst.is_platform_direct:
                            platform_instruments.append(inst)
                        elif inst.data_logger_type == "flight":
                            flight_instruments.append(inst)
                        elif inst.data_logger_type == "science":
                            science_instruments.append(inst)

                    logger.info(f"Instrument groups - Flight: {len(flight_instruments)}, Science: {len(science_instruments)}, Platform: {len(platform_instruments)}")

                    def _instrument_section_lines(items: List[models.MissionInstrument]) -> List[str]:
                        """Build the bullet/sub-bullet lines for an instrument group."""
                        if not items:
                            return ["(None)"]
                        lines: List[str] = []
                        for inst in items:
                            inst_name = inst.instrument_name or inst.instrument_identifier
                            inst_serial = inst.instrument_serial or "N/A"
                            if inst_serial != "N/A":
                                lines.append(f"• {inst_name} ({inst_serial})")
                            else:
                                lines.append(f"• {inst_name}")
                            sensors = session.exec(
                                select(models.MissionSensor).where(
                                    models.MissionSensor.instrument_id == inst.id
                                )
                            ).all()
                            for sensor in sensors:
                                lines.append(f"    └ {sensor.sensor_identifier}")
                        return lines

                    science_title = "Science Computer Instruments"
                    if science_instruments and getattr(science_instruments[0], "data_logger_serial", None):
                        science_title = f"Science Computer Instruments (SN: {science_instruments[0].data_logger_serial})"

                    base_sections: List[Dict[str, Any]] = [
                        {"heading": "Platform Direct Instruments", "lines": _instrument_section_lines(platform_instruments)},
                        {"heading": "Flight Computer Instruments", "lines": _instrument_section_lines(flight_instruments)},
                        {"heading": science_title, "lines": _instrument_section_lines(science_instruments)},
                    ]
                    render_text_sections(
                        add_footer_and_save,
                        page_title="Glider Instrument and Sensors",
                        sections=base_sections,
                    )
                finally:
                    session.close()

            except Exception as e:
                logger.error(f"Failed to generate Sensor Tracker metadata page for mission '{mission_id}': {e}", exc_info=True)
                fig_err = plt.figure(figsize=(8.27, 11.69))
                fig_err.text(0.5, 0.5, f"Error generating Sensor Tracker metadata:\n{e}", ha='center', va='center', color='red', wrap=True, family=REPORT_PDF_FONT_PRIMARY)
                add_footer_and_save(fig_err)

        # --- Page 4: Telemetry Track ---
        if "telemetry" in plots_to_include and not telemetry_df_filtered.empty:
            try:
                fig_telemetry = plt.figure(figsize=(8.27, 11.69))
                plot_telemetry_page_with_notes(
                    fig_telemetry,
                    telemetry_df_filtered,
                    note_annotations=telemetry_note_annotations,
                )
                add_footer_and_save(fig_telemetry)
                if telemetry_note_annotations:
                    plot_mission_notes_page(
                        add_footer_and_save,
                        telemetry_note_annotations,
                    )
            except Exception as e:
                logger.error(f"Failed to generate telemetry plot for mission '{mission_id}': {e}", exc_info=True)
                fig_err = plt.figure(figsize=(8.27, 11.69))
                fig_err.text(0.5, 0.5, f"Error generating telemetry plot:\n{e}", ha='center', va='center', color='red', wrap=True, family=REPORT_PDF_FONT_PRIMARY)
                add_footer_and_save(fig_err)
        else:
            logger.warning(f"Telemetry data for mission '{mission_id}' is empty or not selected. Skipping telemetry plot.")

        # --- Page 4: Power Summary ---
        if "power" in plots_to_include and not power_df_filtered.empty:
            try:
                fig_power, ax_power = plt.subplots(figsize=(11.69, 8.27)) # A4 landscape
                plot_power_for_report(ax_power, power_df_filtered)
                fig_power.tight_layout(pad=2.0)
                add_footer_and_save(fig_power)
            except Exception as e:
                logger.error(f"Failed to generate power plot for mission '{mission_id}': {e}", exc_info=True)
                fig_err = plt.figure(figsize=(8.27, 11.69))
                fig_err.text(0.5, 0.5, f"Error generating power plot:\n{e}", ha='center', va='center', color='red', wrap=True, family=REPORT_PDF_FONT_PRIMARY)
                add_footer_and_save(fig_err)
        else:
            logger.warning(f"Power data for mission '{mission_id}' is empty or not selected. Skipping power plot.")

        # --- Page 5: CTD Summary ---
        if "ctd" in plots_to_include and not ctd_df_filtered.empty:
            try:
                fig_ctd = plt.figure(figsize=(11.69, 8.27)) # A4 landscape
                plot_ctd_for_report(fig_ctd, ctd_df_filtered)
                fig_ctd.tight_layout(rect=[0, 0.03, 1, 0.95]) # Adjust for suptitle
                add_footer_and_save(fig_ctd)
            except Exception as e:
                logger.error(f"Failed to generate CTD plot for mission '{mission_id}': {e}", exc_info=True)
                fig_err = plt.figure(figsize=(8.27, 11.69))
                fig_err.text(0.5, 0.5, f"Error generating CTD plot:\n{e}", ha='center', va='center', color='red', wrap=True, family=REPORT_PDF_FONT_PRIMARY)
                add_footer_and_save(fig_err)
        else:
            logger.warning(f"CTD data for mission '{mission_id}' is empty or not selected. Skipping CTD plot.")

        # --- Page 6: Weather Summary ---
        if "weather" in plots_to_include and not weather_df_filtered.empty:
            try:
                fig_weather = plt.figure(figsize=(11.69, 8.27)) # A4 landscape
                plot_weather_for_report(fig_weather, weather_df_filtered)
                fig_weather.tight_layout(rect=[0, 0.03, 1, 0.95]) # Adjust for suptitle
                add_footer_and_save(fig_weather)
            except Exception as e:
                logger.error(f"Failed to generate weather plot for mission '{mission_id}': {e}", exc_info=True)
                fig_err = plt.figure(figsize=(8.27, 11.69))
                fig_err.text(0.5, 0.5, f"Error generating weather plot:\n{e}", ha='center', va='center', color='red', wrap=True, family=REPORT_PDF_FONT_PRIMARY)
                add_footer_and_save(fig_err)
        else:
            logger.warning(f"Weather data for mission '{mission_id}' is empty or not selected. Skipping weather plot.")

        # --- Page 7: Wave Summary ---
        if "waves" in plots_to_include and not wave_df_filtered.empty:
            try:
                fig_wave = plt.figure(figsize=(11.69, 8.27)) # A4 landscape
                plot_wave_for_report(fig_wave, wave_df_filtered)
                fig_wave.tight_layout(rect=[0, 0.03, 1, 0.95]) # Adjust for suptitle
                add_footer_and_save(fig_wave)
            except Exception as e:
                logger.error(f"Failed to generate wave plot for mission '{mission_id}': {e}", exc_info=True)
                fig_err = plt.figure(figsize=(8.27, 11.69))
                fig_err.text(0.5, 0.5, f"Error generating wave plot:\n{e}", ha='center', va='center', color='red', wrap=True, family=REPORT_PDF_FONT_PRIMARY)
                add_footer_and_save(fig_err)
        else:
            logger.warning(f"Wave data for mission '{mission_id}' is empty or not selected. Skipping wave plot.")

        # --- C3 Fluorometer Report ---
        if "c3" in plots_to_include and has_c3_card_enabled and not fluorometer_df_filtered.empty:
            try:
                fig_c3 = plt.figure(figsize=(11.69, 8.27))
                plot_c3_for_report(fig_c3, fluorometer_df_filtered)
                fig_c3.tight_layout(rect=[0, 0.03, 1, 0.95])
                add_footer_and_save(fig_c3)
            except Exception as e:
                logger.error(f"Failed to generate C3 plot for mission '{mission_id}': {e}", exc_info=True)
                fig_err = plt.figure(figsize=(8.27, 11.69))
                fig_err.text(0.5, 0.5, f"Error generating C3 plot:\n{e}", ha='center', va='center', color='red', wrap=True, family=REPORT_PDF_FONT_PRIMARY)
                add_footer_and_save(fig_err)
        elif "c3" in plots_to_include and not has_c3_card_enabled:
            logger.info("C3 section skipped for mission '%s': fluorometer sensor card not active.", mission_id)

        # --- Page 8: Error Report ---
        if "errors" in plots_to_include and not error_df_filtered.empty:
            try:
                plot_errors_for_report(add_footer_and_save, error_df_filtered)
            except Exception as e:
                logger.error(f"Failed to generate error plot for mission '{mission_id}': {e}", exc_info=True)
                fig_err = plt.figure(figsize=(8.27, 11.69))
                fig_err.text(0.5, 0.5, f"Error generating error plot:\n{e}", ha='center', va='center', color='red', wrap=True, family=REPORT_PDF_FONT_PRIMARY)
                add_footer_and_save(fig_err)
        else:
            logger.warning(f"Error data for mission '{mission_id}' is empty or not selected. Skipping error plot.")

        if "ais" in plots_to_include and not ais_df_filtered.empty:
            ais_stats = get_ais_summary_stats(ais_df_filtered, max_age_hours=24 * 365)
            ais_targets = get_ais_summary(ais_df_filtered, max_age_hours=24 * 365)[:25]
            generated_at_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            target_lines: List[str] = []
            for row in ais_targets:
                seen_time = row.get("LastSeenTimestamp")
                if seen_time is not None and pd.notna(seen_time):
                    seen_text = pd.to_datetime(seen_time, utc=True).strftime("%Y-%m-%d %H:%M:%S UTC")
                else:
                    seen_text = "N/A"
                target_lines.append(
                    f"{seen_text} | {row.get('ShipName', 'Unknown')} | MMSI {row.get('MMSI', 'N/A')} | "
                    f"{row.get('Category', 'N/A')} | {row.get('Destination', 'N/A')}"
                )
            ais_sections = [
                {
                    "heading": f"From {start_date.strftime('%Y-%m-%d') if start_date else 'mission start'} to {end_date.strftime('%Y-%m-%d') if end_date else 'mission end'}",
                    "lines": [
                        f"AIS report generated: {generated_at_utc}",
                        f"Total vessels: {ais_stats.get('total_vessels', 0)}",
                        f"Class A: {ais_stats.get('class_a_count', 0)}",
                        f"Class B: {ais_stats.get('class_b_count', 0)}",
                        f"Hazardous: {ais_stats.get('hazardous_count', 0)}",
                    ],
                },
                {
                    "heading": "AIS Targets",
                    "lines": target_lines or ["(No targets available)"],
                },
            ]
            render_text_sections(add_footer_and_save, page_title="AIS Report", sections=ais_sections)
    return url_path


async def create_and_save_weekly_report(mission_id: str, session: SQLModelSession):
    """
    Loads data, generates a standard weekly report, and saves the URL to the database.
    Designed to be called by an automated scheduler.

    Delegates to :func:`generate_weekly_report_pdf_for_mission` with default
    ``ReportGenerationOptions`` — the same pipeline as
    ``POST /api/reporting/missions/{mission_id}/generate-weekly-report`` when the admin
    accepts default options.
    """
    logger.info(f"AUTOMATED: Starting weekly report generation for mission '{mission_id}'.")
    try:
        options = models.ReportGenerationOptions()
        mission_overview = session.exec(
            select(models.MissionOverview).where(models.MissionOverview.mission_id == mission_id)
        ).first()
        report_url = await generate_weekly_report_pdf_for_mission(
            session,
            mission_id,
            current_user=None,
            options=options,
            mission_overview=mission_overview,
        )
        if not mission_overview:
            mission_overview = models.MissionOverview(mission_id=mission_id)
        mission_overview.weekly_report_url = report_url
        session.add(mission_overview)
        session.commit()
        logger.info(
            "AUTOMATED: Successfully generated and saved weekly report for mission '%s'. URL: %s",
            mission_id,
            report_url,
        )
    except Exception as e:
        logger.error(f"AUTOMATED: Failed to generate weekly report for mission '{mission_id}': {e}", exc_info=True)

