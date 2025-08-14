import asyncio
import logging

import pandas as pd
from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlmodel import Session as SQLModelSession
from sqlmodel import select

from ..auth_utils import get_current_admin_user
from ..core import models
from ..db import get_db_session
from ..reporting import generate_weekly_report

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
    # NOTE: We import the main app's data loading function here, inside the endpoint,
    # to avoid circular dependencies at the module level.
    from ..app import load_data_source

    mission_overview = session.exec(
        select(models.MissionOverview).where(models.MissionOverview.mission_id == mission_id)
    ).first()
    
    if not mission_overview:
        logger.info(f"No existing MissionOverview for '{mission_id}'. Creating a new one for the report.")
        mission_overview = models.MissionOverview(mission_id=mission_id)
        
    logger.info(f"Fetching data for '{mission_id}' report, initiated by '{current_user.username}'.")
    try:
        results = await asyncio.gather(
            load_data_source("telemetry", mission_id, current_user=current_user),
            load_data_source("power", mission_id, current_user=current_user),
            load_data_source("ctd", mission_id, current_user=current_user),
            load_data_source("weather", mission_id, current_user=current_user),
            load_data_source("waves", mission_id, current_user=current_user),
            return_exceptions=True,
        )
        telemetry_res, power_res, ctd_res, weather_res, wave_res = results

        telemetry_df = telemetry_res[0] if not isinstance(telemetry_res, Exception) else pd.DataFrame()
        power_df = power_res[0] if not isinstance(power_res, Exception) else pd.DataFrame()
        ctd_df = ctd_res[0] if not isinstance(ctd_res, Exception) else pd.DataFrame()
        weather_df = weather_res[0] if not isinstance(weather_res, Exception) else pd.DataFrame()
        wave_df = wave_res[0] if not isinstance(wave_res, Exception) else pd.DataFrame()

        if isinstance(telemetry_res, Exception): logger.error(f"Error loading telemetry data for report: {telemetry_res}")
        if isinstance(power_res, Exception): logger.error(f"Error loading power data for report: {power_res}")
        if isinstance(ctd_res, Exception): logger.error(f"Error loading ctd data for report: {ctd_res}")
        if isinstance(weather_res, Exception): logger.error(f"Error loading weather data for report: {weather_res}")
        if isinstance(wave_res, Exception): logger.error(f"Error loading wave data for report: {wave_res}")

    except Exception as e:
        logger.error(f"An unexpected error occurred during data fetching for report: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to fetch source data.")

    report_url = generate_weekly_report(
        mission_id=mission_id,
        telemetry_df=telemetry_df,
        power_df=power_df,
        ctd_df=ctd_df,
        weather_df=weather_df,
        wave_df=wave_df,
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