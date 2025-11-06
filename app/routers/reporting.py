import asyncio
import logging

import pandas as pd
from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlmodel import Session as SQLModelSession
from sqlmodel import select

from ..core.auth import get_current_admin_user
from ..core import models
from ..core.data_service import get_data_service
from ..core.db import get_db_session
from ..core.reporting import generate_weekly_report

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/reporting",
    tags=["Reporting"],
    dependencies=[Depends(get_current_admin_user)],
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