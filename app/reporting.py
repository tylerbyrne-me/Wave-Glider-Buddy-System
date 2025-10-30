import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import matplotlib.image as mpimg
import cartopy.crs as ccrs
from pathlib import Path
from datetime import datetime
from typing import Optional, List
from datetime import date, timedelta
import logging
import httpx
import asyncio
import json
import numpy as np

from sqlmodel import Session as SQLModelSession, select

from .core import models, utils
from .core.plotting import (plot_ctd_for_report, plot_errors_for_report,
                          plot_power_for_report, plot_summary_page, plot_telemetry_for_report, plot_wave_for_report, plot_weather_for_report)
from .core.processors import preprocess_ctd_df, preprocess_wave_df, preprocess_weather_df

logger = logging.getLogger(__name__)

# Define the output directory for reports
REPORTS_DIR = Path(__file__).resolve().parent.parent / "web" / "static" / "mission_reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# Define the path to the company logo. **Please update 'your_logo_name.png' to your actual logo file name.**
LOGO_PATH = Path(__file__).resolve().parent.parent / "web" / "static" / "images" / "otn_logo.png"

def _calculate_telemetry_summary(df: pd.DataFrame) -> dict:
    """
    Calculates summary statistics from a telemetry DataFrame for reporting.
    Handles distance traveled and average speed. Uses a vectorized Haversine
    formula for performance.
    """
    summary = {"total_distance_km": 0.0, "avg_speed_knots": 0.0}
    if df.empty or len(df) < 2:
        return summary

    # Ensure data is clean and sorted for distance calculation
    df_clean = df.dropna(
        subset=['latitude', 'longitude', 'lastLocationFix']
    ).sort_values(by='lastLocationFix').copy()
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

    # Calculate average speed
    if 'speedOverGround' in df_clean.columns and not df_clean['speedOverGround'].isnull().all():
        summary["avg_speed_knots"] = df_clean['speedOverGround'].mean()

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
        power_df = power_df.sort_values('gliderTimeStamp')
        duration_hours = (power_df['gliderTimeStamp'].max() - power_df['gliderTimeStamp'].min()).total_seconds() / 3600
        if duration_hours > 0:
            # These are in mWh, so sum and convert to Wh, then divide by hours for avg Watts
            if 'solarPowerGenerated' in power_df.columns:
                total_input_wh = power_df['solarPowerGenerated'].sum() / 1000
                summary["avg_total_input_W"] = total_input_wh / duration_hours
            
            if 'outputPortPower' in power_df.columns:
                total_output_wh = power_df['outputPortPower'].sum() / 1000
                summary["avg_total_output_W"] = total_output_wh / duration_hours

    if not solar_df.empty and 'gliderTimeStamp' in solar_df.columns and len(solar_df) > 1:
        solar_df = solar_df.sort_values('gliderTimeStamp')
        duration_hours_solar = (solar_df['gliderTimeStamp'].max() - solar_df['gliderTimeStamp'].min()).total_seconds() / 3600
        if duration_hours_solar > 0:
            for i in range(6): # Panels 0-5
                col_name = f'inputPower_{i}'
                if col_name in solar_df.columns:
                    # These are in mWh
                    total_panel_wh = solar_df[col_name].sum() / 1000
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

async def generate_weekly_report(
    mission_id: str,
    telemetry_df: pd.DataFrame,
    power_df: pd.DataFrame,
    solar_df: pd.DataFrame,
    ctd_df: pd.DataFrame,
    weather_df: pd.DataFrame,
    wave_df: pd.DataFrame,
    error_df: pd.DataFrame,
    mission_goals: Optional[List[models.MissionGoal]] = None,
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
        solar_df: DataFrame with solar data.
        ctd_df: DataFrame with CTD data.
        weather_df: DataFrame with weather data.
        wave_df: DataFrame with wave data.
        error_df: DataFrame with vehicle error data.
        start_date: Optional start date for filtering data.
        end_date: Optional end date for filtering data.
        plots_to_include: List of plot types to include (e.g., ['telemetry', 'power']).
        custom_filename: A custom base name for the report file.

    Returns:
        The URL path to the generated PDF report.
    """
    report_timestamp = datetime.utcnow().strftime("%Y-%m-%d_%H%M%S")
    
    if custom_filename and custom_filename.strip():
        # Sanitize the custom filename to allow only safe characters
        safe_base_name = "".join(c for c in custom_filename if c.isalnum() or c in (' ', '_', '-')).strip() or "report"
        title_for_pdf = f"User Generated Report: {safe_base_name}"
        filename = f"{safe_base_name.replace(' ', '_')}_{report_timestamp}.pdf"
    else:
        title_for_pdf = "Weekly Mission Report"
        filename = f"weekly_report_{mission_id}_{report_timestamp}.pdf"

    file_path = REPORTS_DIR / filename
    url_path = f"/static/mission_reports/{filename}"

    if plots_to_include is None:
        plots_to_include = ["telemetry", "power"]

    # Create copies to avoid modifying the original dataframes and to define the filtered variables
    telemetry_df_filtered = telemetry_df.copy()
    power_df_filtered = power_df.copy()
    solar_df_filtered = solar_df.copy()
    ctd_df_filtered = ctd_df.copy()
    weather_df_filtered = weather_df.copy()
    wave_df_filtered = wave_df.copy()
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

    date_range_str = "Full Mission History"
    if start_date and end_date:
        date_range_str = f"From: {start_date.strftime('%Y-%m-%d')} To: {end_date.strftime('%Y-%m-%d')}"
    elif start_date:
        date_range_str = f"From: {start_date.strftime('%Y-%m-%d')}"
    elif end_date:
        date_range_str = f"To: {end_date.strftime('%Y-%m-%d')}"

    with PdfPages(file_path) as pdf:
        # --- Calculate total pages for the footer ---
        page_count_list = [
            True,  # Title page
            True,  # Summary page
            "telemetry" in plots_to_include and not telemetry_df_filtered.empty,
            "power" in plots_to_include and not power_df_filtered.empty,
            "ctd" in plots_to_include and not ctd_df_filtered.empty,
            "weather" in plots_to_include and not weather_df_filtered.empty,
            "waves" in plots_to_include and not wave_df_filtered.empty,
            "errors" in plots_to_include and not error_df_filtered.empty,
        ]
        total_pages = sum(page_count_list)
        page_num = 0

        def add_footer_and_save(fig_to_save):
            """Adds a page number footer to the figure and saves it to the PDF."""
            nonlocal page_num
            page_num += 1
            # Add footer text to the bottom right of the figure.
            fig_to_save.text(0.95, 0.01, f'Page {page_num} of {total_pages}', ha='right', va='bottom', size=8, color='gray')
            pdf.savefig(fig_to_save)
            plt.close(fig_to_save)

        # --- Page 1: Title Page ---
        fig = plt.figure(figsize=(8.27, 11.69))  # A4 size

        # Start drawing from the top of the page.
        current_y = 0.90
        fig.text(0.5, current_y, title_for_pdf, ha='center', size=24, weight='bold', wrap=True)

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

        fig.text(0.5, current_y, f"Mission: {mission_id}", ha='center', size=20, wrap=True)

        current_y -= 0.07
        if vehicle_name:
            fig.text(0.5, current_y, f"Vehicle: {vehicle_name}", ha='center', size=16, wrap=True)
            current_y -= 0.05

        fig.text(0.5, current_y, date_range_str, ha='center', size=16, wrap=True)
        current_y -= 0.05
        fig.text(0.5, current_y, f"Generated on: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}", ha='center', size=12, wrap=True)

        add_footer_and_save(fig)

        # --- Page 2: Mission Summary ---
        try:
            fig_summary = plt.figure(figsize=(8.27, 11.69)) # A4 portrait
            plot_summary_page(fig_summary, mission_telemetry_summary, report_period_telemetry_summary, report_period_power_summary, report_period_ctd_summary, report_period_weather_summary, report_period_wave_summary, report_period_error_summary, mission_goals=mission_goals)
            add_footer_and_save(fig_summary)
        except Exception as e:
            logger.error(f"Failed to generate summary page for mission '{mission_id}': {e}", exc_info=True)
            fig_err = plt.figure(figsize=(8.27, 11.69))
            fig_err.text(0.5, 0.5, f"Error generating summary page:\n{e}", ha='center', va='center', color='red', wrap=True)
            add_footer_and_save(fig_err)

        # --- Page 3: Telemetry Track ---
        if "telemetry" in plots_to_include and not telemetry_df_filtered.empty:
            try:
                fig_telemetry = plt.figure(figsize=(8.27, 11.69))
                ax_telemetry = fig_telemetry.add_subplot(1, 1, 1, projection=ccrs.PlateCarree())
                plot_telemetry_for_report(ax_telemetry, telemetry_df_filtered)
                fig_telemetry.tight_layout(pad=3.0)
                add_footer_and_save(fig_telemetry)
            except Exception as e:
                logger.error(f"Failed to generate telemetry plot for mission '{mission_id}': {e}", exc_info=True)
                fig_err = plt.figure(figsize=(8.27, 11.69))
                fig_err.text(0.5, 0.5, f"Error generating telemetry plot:\n{e}", ha='center', va='center', color='red', wrap=True)
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
                fig_err.text(0.5, 0.5, f"Error generating power plot:\n{e}", ha='center', va='center', color='red', wrap=True)
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
                fig_err.text(0.5, 0.5, f"Error generating CTD plot:\n{e}", ha='center', va='center', color='red', wrap=True)
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
                fig_err.text(0.5, 0.5, f"Error generating weather plot:\n{e}", ha='center', va='center', color='red', wrap=True)
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
                fig_err.text(0.5, 0.5, f"Error generating wave plot:\n{e}", ha='center', va='center', color='red', wrap=True)
                add_footer_and_save(fig_err)
        else:
            logger.warning(f"Wave data for mission '{mission_id}' is empty or not selected. Skipping wave plot.")

        # --- Page 8: Error Report ---
        if "errors" in plots_to_include and not error_df_filtered.empty:
            try:
                fig_error = plt.figure(figsize=(8.27, 11.69)) # A4 portrait
                plot_errors_for_report(fig_error, error_df_filtered)
                fig_error.tight_layout(rect=[0, 0.03, 1, 0.95])
                add_footer_and_save(fig_error)
            except Exception as e:
                logger.error(f"Failed to generate error plot for mission '{mission_id}': {e}", exc_info=True)
                fig_err = plt.figure(figsize=(8.27, 11.69))
                fig_err.text(0.5, 0.5, f"Error generating error plot:\n{e}", ha='center', va='center', color='red', wrap=True)
                add_footer_and_save(fig_err)
        else:
            logger.warning(f"Error data for mission '{mission_id}' is empty or not selected. Skipping error plot.")
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
        # Load data sources, providing empty DataFrames as a fallback if a source is missing.
        telemetry_res = await load_data_source("telemetry", mission_id, current_user=None)
        power_res = await load_data_source("power", mission_id, current_user=None)
        solar_res = await load_data_source("solar", mission_id, current_user=None)
        ctd_res = await load_data_source("ctd", mission_id, current_user=None)
        weather_res = await load_data_source("weather", mission_id, current_user=None)
        wave_res = await load_data_source("waves", mission_id, current_user=None)
        error_res = await load_data_source("errors", mission_id, current_user=None)

        telemetry_df = telemetry_res[0] if telemetry_res else pd.DataFrame()
        power_df = power_res[0] if power_res else pd.DataFrame()
        solar_df = solar_res[0] if solar_res else pd.DataFrame()
        ctd_df = ctd_res[0] if ctd_res else pd.DataFrame()
        weather_df = weather_res[0] if weather_res else pd.DataFrame()
        wave_df = wave_res[0] if wave_res else pd.DataFrame()
        error_df = error_res[0] if error_res else pd.DataFrame()

        # Fetch mission goals
        goals_statement = select(models.MissionGoal).where(models.MissionGoal.mission_id == mission_id).order_by(models.MissionGoal.created_at_utc)
        mission_goals = session.exec(goals_statement).all()

        # Generate report with default (weekly) naming
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
