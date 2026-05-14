"""Mission PDF report generation (ReportLab + matplotlib charts)."""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, List, Optional

import pandas as pd
from sqlalchemy import and_, func, or_
from sqlmodel import Session as SQLModelSession, select

from .. import models, utils
from .builder import write_weekly_mission_pdf
from .constants import LOGO_PATH, REPORTS_ROOT

logger = logging.getLogger(__name__)


def default_weekly_report_date_window() -> tuple[date, date]:
    """UTC calendar window used for default weekly reports (matches admin UI weekly preset)."""
    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=7)
    return start_date, end_date


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
    """Mission notes flagged for PDF reports, oldest first.

    Matches both folder-style mission ids (e.g. ``m219-SV3-1121``) and deployment
    codes (e.g. ``m219``) so notes stored under either key appear on the map and
    the Mission notes section.
    """
    mission_base = utils.deployment_mission_code_from_mission_id(mission_id)
    statement = (
        select(models.MissionNote)
        .where(
            or_(
                models.MissionNote.mission_id == mission_id,
                models.MissionNote.mission_id == mission_base,
            ),
            models.MissionNote.include_in_report == True,  # noqa: E712
        )
        .order_by(models.MissionNote.created_at_utc.asc())
    )
    return session.exec(statement).all()


def load_mission_goals_for_report(session: SQLModelSession, mission_id: str) -> List[models.MissionGoal]:
    """Mission goals for PDF reports, matching folder-style ids and deployment codes (e.g. m219-SV3-1121 vs m219)."""
    mission_base = utils.deployment_mission_code_from_mission_id(mission_id)
    statement = (
        select(models.MissionGoal)
        .where(
            or_(
                models.MissionGoal.mission_id == mission_id,
                models.MissionGoal.mission_id == mission_base,
            )
        )
        .order_by(models.MissionGoal.created_at_utc)
    )
    return session.exec(statement).all()


def load_offload_logs_for_report(
    session: SQLModelSession,
    mission_id: str,
    start_date: Optional[date],
    end_date: Optional[date],
) -> List[models.OffloadLog]:
    """Operator **station offload sheet** rows for the weekly PDF (truth source).

    Only ``offload_logs`` with ``created_by_source == 'user'`` are included. Automated
    WG-VM4 CSV/parser rows (``created_by_source == 'parser'``) are **excluded** so the PDF is not
    driven by parser ingest or other VM4 dashboard side effects.

    Mission scoping for user rows:

    - **Preferred:** ``parser_session_ref`` shaped like
      ``{mission_id}:station_offload_sheet:{station_id}``, set on sheet POST when the client sends
      ``mission_id`` (same value as the dashboard mission context).
    - **Also:** ``parser_run_id`` / ``parser_session_ref`` prefix match (for merged or legacy rows
      that already carry WG-VM4 parser-style ids).
    - **Legacy fallback:** empty parser fields and ``station_metadata.last_offload_by_glider`` in
      the mission alias set (set by a separate station PUT after sheet submit in ``wg_vm4.js``;
      prefer ``mission_id`` on the sheet POST so the log row alone is authoritative).

    The report window uses the same UTC inclusive/exclusive bounds as
    ``_filter_report_dataframes`` (end date is inclusive through end-of-day UTC).
    """
    mid = mission_id.strip()
    if not mid:
        return []
    mission_base = utils.deployment_mission_code_from_mission_id(mid)
    dep = session.exec(
        select(models.SensorTrackerDeployment).where(
            or_(
                models.SensorTrackerDeployment.mission_id == mid,
                models.SensorTrackerDeployment.mission_id == mission_base,
            )
        )
    ).first()
    folder_mission_id = dep.mission_id if dep and dep.mission_id else None
    prefixes = utils.mission_ids_for_offload_parser_trace_matching(
        mid, sensor_tracker_folder_mission_id=folder_mission_id
    )

    colon_clauses: List[Any] = []
    for p in prefixes:
        colon_clauses.append(models.OffloadLog.parser_run_id.startswith(f"{p}:"))
        colon_clauses.append(models.OffloadLog.parser_session_ref.startswith(f"{p}:"))

    mission_match = or_(*colon_clauses)
    if mid == mission_base:
        mission_match = or_(
            mission_match,
            models.OffloadLog.parser_run_id.startswith(f"{mission_base}-"),
            models.OffloadLog.parser_session_ref.startswith(f"{mission_base}-"),
        )

    event_ts = func.coalesce(
        models.OffloadLog.offload_end_time_utc,
        models.OffloadLog.offload_start_time_utc,
        models.OffloadLog.log_timestamp_utc,
    )

    parser_trace_match = mission_match
    parser_run_blank = or_(
        models.OffloadLog.parser_run_id.is_(None),
        models.OffloadLog.parser_run_id == "",
    )
    parser_session_blank = or_(
        models.OffloadLog.parser_session_ref.is_(None),
        models.OffloadLog.parser_session_ref == "",
    )
    alias_lower = [p.lower() for p in prefixes if p]
    station_sheet_match = and_(
        models.OffloadLog.created_by_source == "user",
        parser_run_blank,
        parser_session_blank,
        models.StationMetadata.last_offload_by_glider.isnot(None),
        func.lower(models.StationMetadata.last_offload_by_glider).in_(alias_lower),
    )
    mission_or_sheet = or_(parser_trace_match, station_sheet_match)
    operator_sheet_only = models.OffloadLog.created_by_source == "user"

    filters: List[Any] = [and_(operator_sheet_only, mission_or_sheet)]
    if start_date is not None:
        filters.append(
            event_ts >= datetime.combine(start_date, time.min, tzinfo=timezone.utc)
        )
    if end_date is not None:
        end_exclusive = datetime.combine(end_date, time.min, tzinfo=timezone.utc) + timedelta(days=1)
        filters.append(event_ts < end_exclusive)

    statement = (
        select(models.OffloadLog)
        .join(models.StationMetadata, models.OffloadLog.station_id == models.StationMetadata.station_id)
        .where(and_(*filters))
        .order_by(event_ts.desc())
    )
    rows = list(session.exec(statement).all())
    window_start = (
        datetime.combine(start_date, time.min, tzinfo=timezone.utc).isoformat()
        if start_date is not None
        else "open"
    )
    window_end_excl = (
        (datetime.combine(end_date, time.min, tzinfo=timezone.utc) + timedelta(days=1)).isoformat()
        if end_date is not None
        else "open"
    )
    logger.info(
        "Weekly report offload query mission_id=%r: matched %s operator sheet row(s) "
        "(created_by_source=user only; parser ingest excluded); parser_trace_prefixes=%s; "
        "utc_event_ts>=%s and utc_event_ts<%s (end date inclusive through end-of-day UTC).",
        mission_id,
        len(rows),
        prefixes,
        window_start,
        window_end_excl,
    )
    return rows


async def generate_weekly_report_pdf_for_mission(
    session: SQLModelSession,
    mission_id: str,
    *,
    current_user: Optional[models.User],
    options: models.ReportGenerationOptions,
    mission_overview: Optional[models.MissionOverview],
) -> str:
    """Load weekly report inputs and return the generated PDF URL path (does not commit)."""
    from ..data_service import get_data_service

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

    mission_goals = load_mission_goals_for_report(session, mission_id)
    mission_notes = load_mission_notes_for_report(session, mission_id)

    mission_base_for_dep = utils.deployment_mission_code_from_mission_id(mission_id)
    sensor_tracker_deployment = session.exec(
        select(models.SensorTrackerDeployment).where(
            or_(
                models.SensorTrackerDeployment.mission_id == mission_id,
                models.SensorTrackerDeployment.mission_id == mission_base_for_dep,
            )
        )
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

    offload_logs = load_offload_logs_for_report(
        session, mission_id, selected_start_date, selected_end_date
    )

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
        start_date=selected_start_date,
        end_date=selected_end_date,
        plots_to_include=list(options.plots_to_include),
        custom_filename=options.custom_filename,
        sensor_tracker_deployment=sensor_tracker_deployment,
        mission_overview=mission_overview,
        source_path=source_path,
        offload_logs=offload_logs,
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
    offload_logs: Optional[List[models.OffloadLog]] = None,
) -> str:
    """Generate a weekly (or custom) mission PDF and return its URL path under /static/..."""
    report_timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    safe_mission_id = utils.sanitize_path_segment(mission_id)
    report_dir_name = utils.mission_storage_dir_name(mission_id, "reporting")
    report_dir = REPORTS_ROOT / report_dir_name
    report_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Generating report for mission '%s' with custom_filename: '%s'", mission_id, custom_filename)

    if custom_filename and custom_filename.strip():
        safe_base_name = (
            "".join(c for c in custom_filename if c.isalnum() or c in (" ", "_", "-")).strip() or "report"
        )
        if "end_of_mission" in safe_base_name.lower() or "endofmission" in safe_base_name.lower():
            title_for_pdf = "End of Mission Report"
        elif "weekly" in safe_base_name.lower():
            title_for_pdf = "Weekly Mission Report"
        else:
            title_for_pdf = f"Mission Report: {safe_base_name.replace('_', ' ').title()}"
        base_name = safe_base_name.replace(" ", "_")
        if safe_mission_id not in base_name:
            base_name = f"{base_name}_{safe_mission_id}"
        filename = f"{base_name}_{report_timestamp}.pdf"
    else:
        title_for_pdf = "Weekly Mission Report"
        filename = f"weekly_report_{safe_mission_id}_{report_timestamp}.pdf"

    file_path = report_dir / filename
    url_path = f"/static/mission_reports/{report_dir_name}/{filename}"

    if plots_to_include is None:
        plots_to_include = ["telemetry", "power", "ctd", "weather", "waves", "c3", "errors", "ais", "wg_vm4"]

    write_weekly_mission_pdf(
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
        offload_logs=offload_logs or [],
    )
    return url_path


async def create_and_save_weekly_report(mission_id: str, session: SQLModelSession):
    """Loads data, generates a standard weekly report, and saves the URL to the database."""
    logger.info("AUTOMATED: Starting weekly report generation for mission '%s'.", mission_id)
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
        logger.error("AUTOMATED: Failed to generate weekly report for mission '%s': %s", mission_id, e, exc_info=True)


__all__ = [
    "REPORTS_ROOT",
    "LOGO_PATH",
    "WEEKLY_REPORT_DATA_TYPES",
    "WeeklyReportPreflightError",
    "default_weekly_report_date_window",
    "load_mission_goals_for_report",
    "load_mission_notes_for_report",
    "load_offload_logs_for_report",
    "generate_weekly_report_pdf_for_mission",
    "generate_weekly_report",
    "create_and_save_weekly_report",
]
