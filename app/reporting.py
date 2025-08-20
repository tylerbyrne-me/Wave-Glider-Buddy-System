import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import cartopy.crs as ccrs
from pathlib import Path
from datetime import datetime
from typing import Optional, List
from datetime import date, timedelta
import logging
import httpx
import asyncio
import json
from geopy.distance import geodesic

from sqlmodel import Session as SQLModelSession, select

from .core import models
from .core.plotting import (plot_ctd_for_report, plot_power_for_report, plot_summary_page, plot_telemetry_for_report, plot_wave_for_report, plot_weather_for_report)
from .core.processors import preprocess_ctd_df, preprocess_wave_df, preprocess_weather_df

logger = logging.getLogger(__name__)

# Define the output directory for reports
REPORTS_DIR = Path(__file__).resolve().parent.parent / "web" / "static" / "mission_reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# # Define paths to local geodata files
# GEODATA_DIR = Path(__file__).resolve().parent / "geodata"
# NCEI_SEA_FILE = GEODATA_DIR / "Intersect_EEZ_IHO_v5_20241010.shp"
# OCEANS_FILE = GEODATA_DIR / "ne_10m_ocean.shp"

# async def _get_region_info(lat: float, lon: float) -> Optional[dict]:
#     """
#     Gets the marine region for a lat/lon using a three-step fallback process:
#     1. Local NCEI Sea Names shapefile (fine-grained)
#     2. MarineRegions.org API (authoritative gazetteer)
#     3. Local Natural Earth oceans shapefile (coarse fallback)
#     """
#     if lat is None or lon is None or pd.isna(lat) or pd.isna(lon):
#         return None

#     point = gpd.GeoDataFrame(geometry=[Point(lon, lat)], crs="EPSG:4326")

#     # Step 1: NCEI Sea Names (high-resolution local file)
#     try:
#         if NCEI_SEA_FILE.exists():
#             seas = gpd.read_file(NCEI_SEA_FILE)
#             # Explicitly set the CRS for the shapefile to match the point's CRS, resolving the warning.
#             seas = seas.set_crs("EPSG:4326")
#             match = gpd.sjoin(point, seas, how="left", predicate="intersects")
#             # NOTE: The column name 'GEONAME' is an assumption based on common EEZ shapefiles.
#             # If you get a new KeyError, inspect the shapefile's columns with `print(seas.columns)`.
#             name = match.iloc[0]["GEONAME"] if not match.empty and not pd.isna(match.iloc[0]["GEONAME"]) else None
#             if name:
#                 logger.info(f"Region for ({lat}, {lon}) found in NCEI file: {name}")
#                 return {"source": "NCEI Sea Names", "area": name}
#     except Exception as e:
#         # Provide a more detailed error log, especially for KeyErrors.
#         logger.warning(f"Could not perform NCEI shapefile lookup for ({lat}, {lon}). Error: {e}. Check shapefile path and column names (e.g., 'GEONAME').")

#     # Step 2: Marine Regions API (remote fallback)
#     try:
#         url = f"https://www.marineregions.org/rest/getGazetteerRecordsByLatLon.json/{round(lat, 4)}/{round(lon, 4)}/"
#         async with httpx.AsyncClient() as client:
#             resp = await client.get(url, timeout=10.0)
#             if resp.status_code == 200:
#                 data = resp.json()
#                 if data and isinstance(data, list):
#                     name = data[0].get("preferredGazetteerName")
#                     logger.info(f"Region for ({lat}, {lon}) found via MarineRegions API: {name}")
#                     return {"source": "MarineRegions API", "area": name}
#     except Exception as e:
#         logger.warning(f"Could not perform MarineRegions API lookup for ({lat}, {lon}): {e}")

#     # Step 3: Natural Earth (coarse local fallback)
#     try:
#         if OCEANS_FILE.exists():
#             oceans = gpd.read_file(OCEANS_FILE)
#             # Best practice to also set CRS for the fallback file.
#             oceans = oceans.set_crs("EPSG:4326")
#             match = gpd.sjoin(point, oceans, how="left", predicate="intersects")
#             name = match.iloc[0]["name"] if not match.empty and not pd.isna(match.iloc[0]["name"]) else None
#             if name:
#                 logger.info(f"Region for ({lat}, {lon}) found in Natural Earth file: {name}")
#                 return {"source": "Natural Earth", "area": name}
#     except Exception as e:
#         logger.warning(f"Could not perform Natural Earth shapefile lookup for ({lat}, {lon}). Error: {e}")

#     return {"source": None, "area": None}

def _calculate_telemetry_summary(df: pd.DataFrame) -> dict:
    """
    Calculates summary statistics from a telemetry DataFrame for reporting.
    Handles distance traveled and average speed.
    """
    summary = {"total_distance_km": 0.0, "avg_speed_knots": 0.0}
    if df.empty or len(df) < 2:
        return summary

    # Ensure data is clean and sorted for distance calculation
    df_clean = df.dropna(subset=['latitude', 'longitude', 'lastLocationFix']).sort_values(by='lastLocationFix').copy()
    if len(df_clean) < 2:
        return summary

    # Calculate distance between consecutive points
    df_clean['prev_lat'] = df_clean['latitude'].shift(1)
    df_clean['prev_lon'] = df_clean['longitude'].shift(1)
    
    # Calculate distances for rows where previous values exist
    distances = df_clean.iloc[1:].apply(
        lambda row: geodesic((row['latitude'], row['longitude']), (row['prev_lat'], row['prev_lon'])).km,
        axis=1
    )
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

async def generate_weekly_report(
    mission_id: str,
    telemetry_df: pd.DataFrame,
    power_df: pd.DataFrame,
    solar_df: pd.DataFrame,
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
        solar_df: DataFrame with solar data.
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
    solar_df_filtered = solar_df.copy()
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

    if not solar_df_filtered.empty and 'gliderTimeStamp' in solar_df_filtered.columns:
        solar_df_filtered['gliderTimeStamp'] = pd.to_datetime(solar_df_filtered['gliderTimeStamp'], utc=True)
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

    # Extract vehicle name from power data
    vehicle_name = None
    if not power_df.empty and 'vehicleName' in power_df.columns:
        # Get the first non-null vehicle name from the entire (unfiltered) power dataframe
        vehicle_name_series = power_df['vehicleName'].dropna()
        if not vehicle_name_series.empty:
            vehicle_name = vehicle_name_series.iloc[0]

    # # --- New section for Marine Regions ---
    # start_region_name = None
    # end_region_name = None
    # if not telemetry_df_filtered.empty:
    #     # Ensure we have at least one row for start and one for end (could be the same)
    #     start_coords = telemetry_df_filtered.iloc[0]
    #     end_coords = telemetry_df_filtered.iloc[-1]
        
    #     # Fetch region names concurrently
    #     region_results = await asyncio.gather(
    #         _get_region_info(start_coords.get('latitude'), start_coords.get('longitude')),
    #         _get_region_info(end_coords.get('latitude'), end_coords.get('longitude')),
    #         return_exceptions=True
    #     )
        
    #     start_region_info = region_results[0] if not isinstance(region_results[0], Exception) else None
    #     end_region_info = region_results[1] if not isinstance(region_results[1], Exception) else None

    #     if isinstance(region_results[0], Exception): logger.error(f"Exception fetching start region: {region_results[0]}")
    #     if isinstance(region_results[1], Exception): logger.error(f"Exception fetching end region: {region_results[1]}")

    #     start_region_name = start_region_info.get('area') if start_region_info else None
    #     end_region_name = end_region_info.get('area') if end_region_info else None

    # # Construct the display string for the region(s)
    # unique_regions = list(filter(None, sorted(list(set([start_region_name, end_region_name])))))
    # if unique_regions:
    #     region_display_str = " to ".join(unique_regions)
    # else:
    #     region_display_str = None

    # Calculate telemetry summaries for the report
    mission_telemetry_summary = _calculate_telemetry_summary(telemetry_df)
    report_period_telemetry_summary = _calculate_telemetry_summary(telemetry_df_filtered)

    # Calculate all other summaries for the report period
    report_period_power_summary = _calculate_power_summary(power_df_filtered, solar_df_filtered)
    report_period_ctd_summary = _calculate_ctd_summary(ctd_df_filtered)
    report_period_weather_summary = _calculate_weather_summary(weather_df_filtered)
    report_period_wave_summary = _calculate_wave_summary(wave_df_filtered)

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
        current_y = 0.70
        fig.text(0.5, current_y, title_for_pdf, ha='center', size=24, weight='bold', wrap=True)

        current_y -= 0.10
        fig.text(0.5, current_y, f"Mission: {mission_id}", ha='center', size=20, wrap=True)
        
        if vehicle_name:
            current_y -= 0.04
            fig.text(0.5, current_y, f"Vehicle: {vehicle_name}", ha='center', size=16, wrap=True)

        current_y -= 0.05
        fig.text(0.5, current_y, date_range_str, ha='center', size=16, wrap=True)
        current_y -= 0.04
        fig.text(0.5, current_y, f"Generated on: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}", ha='center', size=12, wrap=True)

        pdf.savefig(fig)
        plt.close(fig)

        # --- Page 2: Mission Summary ---
        try:
            fig_summary = plt.figure(figsize=(8.27, 11.69)) # A4 portrait
            plot_summary_page(fig_summary, mission_telemetry_summary, report_period_telemetry_summary, report_period_power_summary, report_period_ctd_summary, report_period_weather_summary, report_period_wave_summary)
            pdf.savefig(fig_summary)
            plt.close(fig_summary)
        except Exception as e:
            logger.error(f"Failed to generate summary page for mission '{mission_id}': {e}", exc_info=True)
            fig_err = plt.figure(figsize=(8.27, 11.69))
            fig_err.text(0.5, 0.5, f"Error generating summary page:\n{e}", ha='center', va='center', color='red', wrap=True)
            pdf.savefig(fig_err)
            plt.close(fig_err)

        # --- Page 3: Telemetry Track ---
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

        # --- Page 4: Power Summary ---
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

        # --- Page 5: CTD Summary ---
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

        # --- Page 6: Weather Summary ---
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

        # --- Page 7: Wave Summary ---
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
        solar_df, _ = await load_data_source("solar", mission_id, current_user=None)
        ctd_df, _ = await load_data_source("ctd", mission_id, current_user=None)
        weather_df, _ = await load_data_source("weather", mission_id, current_user=None)
        wave_df, _ = await load_data_source("waves", mission_id, current_user=None)

        # Generate report with default (weekly) naming
        report_url = await generate_weekly_report(
            mission_id=mission_id, telemetry_df=telemetry_df, power_df=power_df, solar_df=solar_df, ctd_df=ctd_df, weather_df=weather_df, wave_df=wave_df
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
