import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import cartopy.crs as ccrs
from pathlib import Path
from datetime import datetime
from typing import Optional, List
from datetime import date, timedelta
import logging

from sqlmodel import Session as SQLModelSession, select

from .core import models
from .core.plotting import (plot_ctd_for_report, plot_power_for_report, plot_telemetry_for_report, plot_wave_for_report, plot_weather_for_report)
from .core.processors import preprocess_ctd_df, preprocess_wave_df, preprocess_weather_df

logger = logging.getLogger(__name__)

# Define the output directory for reports
REPORTS_DIR = Path(__file__).resolve().parent.parent / "web" / "static" / "mission_reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

def generate_weekly_report(
    mission_id: str,
    telemetry_df: pd.DataFrame,
    power_df: pd.DataFrame,
    ctd_df: pd.DataFrame,
    weather_df: pd.DataFrame,
    wave_df: pd.DataFrame,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    plots_to_include: Optional[List[str]] = None,
    custom_filename: Optional[str] = None,
) -> str:
    """
    Generates a weekly PDF report for a mission with telemetry and power plots.

    Args:
        mission_id: The ID of the mission.
        telemetry_df: DataFrame with telemetry data.
        power_df: DataFrame with power data.
        ctd_df: DataFrame with CTD data.
        weather_df: DataFrame with weather data.
        wave_df: DataFrame with wave data.
        start_date: Optional start date for filtering data.
        end_date: Optional end date for filtering data.
        plots_to_include: List of plot types to include (e.g., ['telemetry', 'power']).
        custom_filename: A custom base name for the report file.

    Returns:
        The URL path to the generated PDF report.
    """
    report_date = datetime.utcnow().strftime("%Y-%m-%d")
    
    if custom_filename and custom_filename.strip():
        # Sanitize the custom filename to allow only safe characters
        safe_base_name = "".join(c for c in custom_filename if c.isalnum() or c in (' ', '_', '-')).strip() or "report"
        title_for_pdf = f"User Generated Report: {safe_base_name}"
        filename = f"{safe_base_name.replace(' ', '_')}_{report_date}.pdf"
    else:
        title_for_pdf = "Weekly Mission Report"
        filename = f"weekly_report_{mission_id}_{report_date}.pdf"

    file_path = REPORTS_DIR / filename
    url_path = f"/static/mission_reports/{filename}"

    if plots_to_include is None:
        plots_to_include = ["telemetry", "power"]

    # Create copies to avoid modifying the original dataframes and to define the filtered variables
    telemetry_df_filtered = telemetry_df.copy()
    power_df_filtered = power_df.copy()
    ctd_df_filtered = ctd_df.copy()
    weather_df_filtered = weather_df.copy()
    wave_df_filtered = wave_df.copy()

    # Filter dataframes based on the provided date range if they are not empty
    if not telemetry_df_filtered.empty and 'lastLocationFix' in telemetry_df_filtered.columns:
        telemetry_df_filtered['lastLocationFix'] = pd.to_datetime(telemetry_df_filtered['lastLocationFix'], utc=True)
        if start_date:
            telemetry_df_filtered = telemetry_df_filtered[telemetry_df_filtered['lastLocationFix'] >= pd.to_datetime(start_date).tz_localize('UTC')]
        if end_date:
            end_date_inclusive = pd.to_datetime(end_date).tz_localize('UTC') + timedelta(days=1)
            telemetry_df_filtered = telemetry_df_filtered[telemetry_df_filtered['lastLocationFix'] < end_date_inclusive]

    if not power_df_filtered.empty and 'gliderTimeStamp' in power_df_filtered.columns:
        power_df_filtered['gliderTimeStamp'] = pd.to_datetime(power_df_filtered['gliderTimeStamp'], utc=True)
        if start_date:
            power_df_filtered = power_df_filtered[power_df_filtered['gliderTimeStamp'] >= pd.to_datetime(start_date).tz_localize('UTC')]
        if end_date:
            end_date_inclusive = pd.to_datetime(end_date).tz_localize('UTC') + timedelta(days=1)
            power_df_filtered = power_df_filtered[power_df_filtered['gliderTimeStamp'] < end_date_inclusive]

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

    logger.info(f"Generating weekly report for mission '{mission_id}' at {file_path}")

    date_range_str = "Full Mission History"
    if start_date and end_date:
        date_range_str = f"From: {start_date.strftime('%Y-%m-%d')} To: {end_date.strftime('%Y-%m-%d')}"
    elif start_date:
        date_range_str = f"From: {start_date.strftime('%Y-%m-%d')}"
    elif end_date:
        date_range_str = f"To: {end_date.strftime('%Y-%m-%d')}"

    with PdfPages(file_path) as pdf:
        # --- Page 1: Title Page ---
        fig = plt.figure(figsize=(8.27, 11.69)) # A4 size
        fig.text(0.5, 0.6, title_for_pdf, ha='center', size=24, weight='bold')
        fig.text(0.5, 0.5, f"Mission: {mission_id}", ha='center', size=20)
        fig.text(0.5, 0.45, date_range_str, ha='center', size=16)
        fig.text(0.5, 0.4, f"Generated on: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}", ha='center', size=12)        
        pdf.savefig(fig)
        plt.close(fig)

        # --- Page 2: Telemetry Track ---
        if "telemetry" in plots_to_include and not telemetry_df_filtered.empty:
            try:
                fig_telemetry = plt.figure(figsize=(8.27, 11.69))
                ax_telemetry = fig_telemetry.add_subplot(1, 1, 1, projection=ccrs.PlateCarree())
                plot_telemetry_for_report(ax_telemetry, telemetry_df_filtered)
                fig_telemetry.tight_layout(pad=3.0)
                pdf.savefig(fig_telemetry)
                plt.close(fig_telemetry)
            except Exception as e:
                logger.error(f"Failed to generate telemetry plot for mission '{mission_id}': {e}", exc_info=True)
                fig_err = plt.figure(figsize=(8.27, 11.69))
                fig_err.text(0.5, 0.5, f"Error generating telemetry plot:\n{e}", ha='center', va='center', color='red', wrap=True)
                pdf.savefig(fig_err)
                plt.close(fig_err)
        else:
            logger.warning(f"Telemetry data for mission '{mission_id}' is empty or not selected. Skipping telemetry plot.")

        # --- Page 3: Power Summary ---
        if "power" in plots_to_include and not power_df_filtered.empty:
            try:
                fig_power, ax_power = plt.subplots(figsize=(11.69, 8.27)) # A4 landscape
                plot_power_for_report(ax_power, power_df_filtered)
                fig_power.tight_layout(pad=2.0)
                pdf.savefig(fig_power)
                plt.close(fig_power)
            except Exception as e:
                logger.error(f"Failed to generate power plot for mission '{mission_id}': {e}", exc_info=True)
                fig_err = plt.figure(figsize=(8.27, 11.69))
                fig_err.text(0.5, 0.5, f"Error generating power plot:\n{e}", ha='center', va='center', color='red', wrap=True)
                pdf.savefig(fig_err)
                plt.close(fig_err)
        else:
            logger.warning(f"Power data for mission '{mission_id}' is empty or not selected. Skipping power plot.")

        # --- Page 4: CTD Summary ---
        if "ctd" in plots_to_include and not ctd_df_filtered.empty:
            try:
                fig_ctd = plt.figure(figsize=(11.69, 8.27)) # A4 landscape
                plot_ctd_for_report(fig_ctd, ctd_df_filtered)
                fig_ctd.tight_layout(rect=[0, 0.03, 1, 0.95]) # Adjust for suptitle
                pdf.savefig(fig_ctd)
                plt.close(fig_ctd)
            except Exception as e:
                logger.error(f"Failed to generate CTD plot for mission '{mission_id}': {e}", exc_info=True)
                fig_err = plt.figure(figsize=(8.27, 11.69))
                fig_err.text(0.5, 0.5, f"Error generating CTD plot:\n{e}", ha='center', va='center', color='red', wrap=True)
                pdf.savefig(fig_err)
                plt.close(fig_err)
        else:
            logger.warning(f"CTD data for mission '{mission_id}' is empty or not selected. Skipping CTD plot.")

        # --- Page 5: Weather Summary ---
        if "weather" in plots_to_include and not weather_df_filtered.empty:
            try:
                fig_weather = plt.figure(figsize=(11.69, 8.27)) # A4 landscape
                plot_weather_for_report(fig_weather, weather_df_filtered)
                fig_weather.tight_layout(rect=[0, 0.03, 1, 0.95]) # Adjust for suptitle
                pdf.savefig(fig_weather)
                plt.close(fig_weather)
            except Exception as e:
                logger.error(f"Failed to generate weather plot for mission '{mission_id}': {e}", exc_info=True)
                fig_err = plt.figure(figsize=(8.27, 11.69))
                fig_err.text(0.5, 0.5, f"Error generating weather plot:\n{e}", ha='center', va='center', color='red', wrap=True)
                pdf.savefig(fig_err)
                plt.close(fig_err)
        else:
            logger.warning(f"Weather data for mission '{mission_id}' is empty or not selected. Skipping weather plot.")

        # --- Page 6: Wave Summary ---
        if "waves" in plots_to_include and not wave_df_filtered.empty:
            try:
                fig_wave = plt.figure(figsize=(11.69, 8.27)) # A4 landscape
                plot_wave_for_report(fig_wave, wave_df_filtered)
                fig_wave.tight_layout(rect=[0, 0.03, 1, 0.95]) # Adjust for suptitle
                pdf.savefig(fig_wave)
                plt.close(fig_wave)
            except Exception as e:
                logger.error(f"Failed to generate wave plot for mission '{mission_id}': {e}", exc_info=True)
                fig_err = plt.figure(figsize=(8.27, 11.69))
                fig_err.text(0.5, 0.5, f"Error generating wave plot:\n{e}", ha='center', va='center', color='red', wrap=True)
                pdf.savefig(fig_err)
                plt.close(fig_err)
        else:
            logger.warning(f"Wave data for mission '{mission_id}' is empty or not selected. Skipping wave plot.")

    return url_path


async def create_and_save_weekly_report(mission_id: str, session: SQLModelSession):
    """
    Loads data, generates a standard weekly report, and saves the URL to the database.
    Designed to be called by an automated scheduler.
    """
    # NOTE: We import the main app's data loading function here, inside the function,
    # to avoid circular dependencies at the module level.
    from .app import load_data_source

    logger.info(f"AUTOMATED: Starting weekly report generation for mission '{mission_id}'.")
    try:
        # Load data with default settings, no user context needed for automated task
        telemetry_df, _ = await load_data_source("telemetry", mission_id, current_user=None)
        power_df, _ = await load_data_source("power", mission_id, current_user=None)
        ctd_df, _ = await load_data_source("ctd", mission_id, current_user=None)
        weather_df, _ = await load_data_source("weather", mission_id, current_user=None)
        wave_df, _ = await load_data_source("waves", mission_id, current_user=None)

        # Generate report with default (weekly) naming
        report_url = generate_weekly_report(
            mission_id=mission_id, telemetry_df=telemetry_df, power_df=power_df, ctd_df=ctd_df, weather_df=weather_df, wave_df=wave_df
        )

        # Get or create MissionOverview
        mission_overview = session.exec(
            select(models.MissionOverview).where(models.MissionOverview.mission_id == mission_id)
        ).first()
        if not mission_overview:
            mission_overview = models.MissionOverview(mission_id=mission_id)

        mission_overview.weekly_report_url = report_url
        session.add(mission_overview)
        session.commit()
        logger.info(f"AUTOMATED: Successfully generated and saved weekly report for mission '{mission_id}'. URL: {report_url}")
    except Exception as e:
        logger.error(f"AUTOMATED: Failed to generate weekly report for mission '{mission_id}': {e}", exc_info=True)
