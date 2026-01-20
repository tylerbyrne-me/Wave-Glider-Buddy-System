import asyncio
import logging

import pandas as pd
from fastapi import APIRouter, Body, Depends, HTTPException, status
from typing import List, Optional
from datetime import datetime
from pathlib import Path
import re
from sqlmodel import Session as SQLModelSession
from sqlmodel import select

from ..core.auth import get_current_admin_user
from ..core import models, utils
from ..core.data_service import get_data_service
from ..core.db import get_db_session
from ..core.reporting import generate_weekly_report

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/reporting",
    tags=["Reporting"],
    dependencies=[Depends(get_current_admin_user)],
)


def _parse_report_timestamp(filename: str) -> Optional[datetime]:
    match = re.search(r"_(\d{4}-\d{2}-\d{2}_\d{6})\.pdf$", filename)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y-%m-%d_%H%M%S")
    except ValueError:
        return None


def _classify_report_type(filename: str) -> str:
    name = filename.lower()
    if "end_of_mission" in name or "endofmission" in name:
        return "end_of_mission"
    if "weekly" in name:
        return "weekly"
    return "other"


@router.get(
    "/missions/{mission_id}/reports",
    response_model=models.MissionReportListResponse,
    summary="List generated reports for a mission.",
)
async def list_mission_reports(
    mission_id: str,
    session: SQLModelSession = Depends(get_db_session),
    current_user: models.User = Depends(get_current_admin_user),
):
    """
    Returns a list of weekly and end-of-mission reports for the given mission.
    """
    report_dir_name = utils.mission_storage_dir_name(mission_id, "reporting")
    report_dir = Path(__file__).resolve().parent.parent.parent / "web" / "static" / "mission_reports" / report_dir_name
    _ = session

    weekly_reports: List[models.MissionReportFile] = []
    end_of_mission_reports: List[models.MissionReportFile] = []

    if report_dir.exists() and report_dir.is_dir():
        for file_path in report_dir.glob("*.pdf"):
            filename = file_path.name
            report_type = _classify_report_type(filename)
            timestamp = _parse_report_timestamp(filename)
            if timestamp is None:
                timestamp = datetime.utcfromtimestamp(file_path.stat().st_mtime)
            url = f"/static/mission_reports/{report_dir_name}/{filename}"
            report_file = models.MissionReportFile(
                filename=filename,
                url=url,
                timestamp=timestamp,
                report_type=report_type,
            )
            if report_type == "end_of_mission":
                end_of_mission_reports.append(report_file)
            elif report_type == "weekly":
                weekly_reports.append(report_file)

    weekly_reports.sort(key=lambda r: r.timestamp or datetime.min, reverse=True)
    end_of_mission_reports.sort(key=lambda r: r.timestamp or datetime.min, reverse=True)

    return models.MissionReportListResponse(
        weekly_reports=weekly_reports,
        end_of_mission_reports=end_of_mission_reports,
    )


@router.post(
    "/missions/{mission_id}/generate-weekly-report",
    response_model=models.MissionOverview,
    summary="Generate and save a weekly PDF report for a mission.",
)
async def generate_mission_report(
    mission_id: str,
    options: models.ReportGenerationOptions = Body(...),
    session: SQLModelSession = Depends(get_db_session),
    current_user: models.User = Depends(get_current_admin_user),
):
    """
    Generates a weekly PDF report containing telemetry and power summaries for the
    specified mission. Restricted to administrators.
    """
    # Use data service (no circular dependency)
    data_service = get_data_service()

    mission_overview = session.exec(
        select(models.MissionOverview).where(models.MissionOverview.mission_id == mission_id)
    ).first()
    
    if not mission_overview:
        logger.info(f"No existing MissionOverview for '{mission_id}'. Creating a new one for the report.")
        mission_overview = models.MissionOverview(mission_id=mission_id)
        
    logger.info(f"Fetching data for '{mission_id}' report, initiated by '{current_user.username}'.")
    try:
        # Use consolidated load_multiple helper for concurrent loading
        report_types = ["telemetry", "power", "ctd", "weather", "waves", "solar", "errors"]
        data_results = await data_service.load_multiple(
            report_types=report_types,
            mission_id=mission_id,
            current_user=current_user
        )
        
        # Extract DataFrames from results (empty DataFrame if error occurred)
        telemetry_df = data_results.get("telemetry", (pd.DataFrame(), "", None))[0]
        power_df = data_results.get("power", (pd.DataFrame(), "", None))[0]
        ctd_df = data_results.get("ctd", (pd.DataFrame(), "", None))[0]
        weather_df = data_results.get("weather", (pd.DataFrame(), "", None))[0]
        wave_df = data_results.get("waves", (pd.DataFrame(), "", None))[0]
        solar_df = data_results.get("solar", (pd.DataFrame(), "", None))[0]
        error_df = data_results.get("errors", (pd.DataFrame(), "", None))[0]
        
        # Log any errors (empty DataFrames indicate errors were caught in load_multiple)
        for report_type in report_types:
            if data_results.get(report_type, (pd.DataFrame(), "", None))[1] == "Error":
                logger.error(f"Error loading {report_type} data for report")

    except Exception as e:
        logger.error(f"An unexpected error occurred during data fetching for report: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to fetch source data.")

    # Fetch mission goals to include in the report
    goals_statement = select(models.MissionGoal).where(models.MissionGoal.mission_id == mission_id).order_by(models.MissionGoal.created_at_utc)
    mission_goals = session.exec(goals_statement).all()
    logger.info(f"Found {len(mission_goals)} goals for mission '{mission_id}' to include in report.")

    report_url = await generate_weekly_report(
        mission_id=mission_id,
        telemetry_df=telemetry_df,
        power_df=power_df,
        solar_df=solar_df,
        ctd_df=ctd_df,
        weather_df=weather_df,
        wave_df=wave_df,
        error_df=error_df,
        mission_goals=mission_goals,
        start_date=options.start_date,
        end_date=options.end_date,
        plots_to_include=options.plots_to_include,
        custom_filename=options.custom_filename,
    )

    if options.save_to_overview:
        mission_overview.weekly_report_url = report_url
        session.add(mission_overview)
        session.commit()
        session.refresh(mission_overview)
        logger.info(f"Successfully generated and saved report for mission '{mission_id}'. URL: {report_url}")
    else:
        # If not saving, we still populate the URL on the returned object for the frontend to use
        # but we do not commit it to the database.
        mission_overview.weekly_report_url = report_url
        logger.info(f"Successfully generated one-off report for mission '{mission_id}'. URL: {report_url}. Not saved to overview.")

    return mission_overview


@router.post(
    "/missions/{mission_id}/generate-report-with-sensor-tracker",
    response_model=models.MissionOverview,
    summary="Generate a report with Sensor Tracker metadata sync.",
)
async def generate_report_with_sensor_tracker(
    mission_id: str,
    report_type: str = Body(..., embed=True, description="Report type: 'weekly' or 'end_of_mission'"),
    force_refresh_sensor_tracker: bool = Body(default=False, embed=True, description="Force refresh Sensor Tracker data"),
    save_to_overview: bool = Body(default=True, embed=True, description="Save report URL to mission overview"),
    session: SQLModelSession = Depends(get_db_session),
    current_user: models.User = Depends(get_current_admin_user),
):
    """
    Generates a report (weekly or end-of-mission) with Sensor Tracker metadata.
    Syncs Sensor Tracker data on-demand before generating the report.
    Restricted to administrators.
    """
    from ..services.sensor_tracker_service import SensorTrackerService, SENSOR_TRACKER_AVAILABLE
    
    logger.info(
        f"Generating {report_type} report for mission '{mission_id}' "
        f"with Sensor Tracker sync (force_refresh={force_refresh_sensor_tracker}), "
        f"initiated by '{current_user.username}'."
    )
    
    # Sync Sensor Tracker data if available
    sensor_tracker_deployment = None
    if SENSOR_TRACKER_AVAILABLE:
        try:
            from ..services.sensor_tracker_sync_service import SensorTrackerSyncService
            
            logger.info(f"Syncing Sensor Tracker data for mission '{mission_id}' (force_refresh={force_refresh_sensor_tracker})")
            
            admin_token = None
            admin_in_db = session.exec(
                select(models.UserInDB).where(
                    models.UserInDB.username == current_user.username
                )
            ).first()
            if admin_in_db:
                admin_token = admin_in_db.sensor_tracker_token

            sync_service = SensorTrackerSyncService(token_override=admin_token)
            sensor_tracker_deployment = await sync_service.get_or_sync_mission(
                mission_id=mission_id,
                force_refresh=force_refresh_sensor_tracker,
                session=session
            )
            
            if sensor_tracker_deployment:
                logger.info(
                    f"Successfully synced Sensor Tracker data for mission '{mission_id}' "
                    f"(deployment ID: {sensor_tracker_deployment.sensor_tracker_deployment_id}, "
                    f"status: {sensor_tracker_deployment.sync_status})"
                )
            else:
                logger.info(f"No Sensor Tracker deployment found or synced for mission '{mission_id}'")
                
        except Exception as e:
            logger.warning(f"Failed to sync Sensor Tracker data for mission '{mission_id}': {e}", exc_info=True)
            # Continue with report generation even if sync fails
    else:
        logger.info("Sensor Tracker service not available. Report will be generated without Sensor Tracker metadata.")
    
    # Use existing report generation logic
    data_service = get_data_service()
    
    mission_overview = session.exec(
        select(models.MissionOverview).where(models.MissionOverview.mission_id == mission_id)
    ).first()
    
    if not mission_overview:
        logger.info(f"No existing MissionOverview for '{mission_id}'. Creating a new one for the report.")
        mission_overview = models.MissionOverview(mission_id=mission_id)
    
    try:
        # Load data sources
        report_types = ["telemetry", "power", "ctd", "weather", "waves", "solar", "errors"]
        data_results = await data_service.load_multiple(
            report_types=report_types,
            mission_id=mission_id,
            current_user=current_user
        )
        
        # Extract DataFrames
        telemetry_df = data_results.get("telemetry", (pd.DataFrame(), "", None))[0]
        power_df = data_results.get("power", (pd.DataFrame(), "", None))[0]
        ctd_df = data_results.get("ctd", (pd.DataFrame(), "", None))[0]
        weather_df = data_results.get("weather", (pd.DataFrame(), "", None))[0]
        wave_df = data_results.get("waves", (pd.DataFrame(), "", None))[0]
        solar_df = data_results.get("solar", (pd.DataFrame(), "", None))[0]
        error_df = data_results.get("errors", (pd.DataFrame(), "", None))[0]
        
        # Log data loading results
        for data_type in report_types:
            result = data_results.get(data_type, (pd.DataFrame(), "", None))
            df, source_path, _ = result[0], result[1], result[2] if len(result) > 2 else None
            
            if result[1] == "Error":
                logger.error(f"Error loading {data_type} data for mission '{mission_id}'")
            elif df is None or df.empty:
                logger.warning(f"No {data_type} data available for mission '{mission_id}' (source: {source_path})")
            else:
                logger.info(f"Loaded {len(df)} {data_type} records for mission '{mission_id}' from {source_path}")
    
    except Exception as e:
        logger.error(f"An unexpected error occurred during data fetching for report: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to fetch source data.")
    
    # Fetch mission goals
    goals_statement = select(models.MissionGoal).where(models.MissionGoal.mission_id == mission_id).order_by(models.MissionGoal.created_at_utc)
    mission_goals = session.exec(goals_statement).all()
    logger.info(f"Found {len(mission_goals)} goals for mission '{mission_id}' to include in report.")
    
    # Determine filename based on report type
    if report_type == "end_of_mission":
        custom_filename = f"End_of_Mission_Report_{mission_id}"
        logger.info(f"Setting custom_filename for end_of_mission report: '{custom_filename}'")
    else:
        custom_filename = None
        logger.info(f"Report type is '{report_type}' - no custom filename")
    
    # Generate report with all plot types included
    plots_to_include = ["telemetry", "power", "solar", "ctd", "weather", "waves", "errors"]
    report_url = await generate_weekly_report(
        mission_id=mission_id,
        telemetry_df=telemetry_df,
        power_df=power_df,
        solar_df=solar_df,
        ctd_df=ctd_df,
        weather_df=weather_df,
        wave_df=wave_df,
        error_df=error_df,
        mission_goals=mission_goals,
        plots_to_include=plots_to_include,
        custom_filename=custom_filename,
        sensor_tracker_deployment=sensor_tracker_deployment,  # Pass Sensor Tracker metadata
    )
    
    if save_to_overview:
        if report_type == "end_of_mission":
            mission_overview.end_of_mission_report_url = report_url
            logger.info(f"Saving end of mission report to end_of_mission_report_url field for mission '{mission_id}': {report_url}")
        else:
            mission_overview.weekly_report_url = report_url
            logger.info(f"Saving weekly report to weekly_report_url field for mission '{mission_id}': {report_url}")
        session.add(mission_overview)
        session.commit()
        session.refresh(mission_overview)
        logger.info(f"Successfully generated and saved {report_type} report for mission '{mission_id}'. URL: {report_url}")
    else:
        if report_type == "end_of_mission":
            mission_overview.end_of_mission_report_url = report_url
        else:
            mission_overview.weekly_report_url = report_url
        logger.info(f"Successfully generated {report_type} report for mission '{mission_id}'. URL: {report_url}. Not saved to overview.")
    
    return mission_overview