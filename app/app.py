from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from .core import loaders, summaries, processors, forecast
from datetime import datetime, timedelta
import logging
import pandas as pd # For DataFrame operations
import numpy as np # For numeric operations if needed
from pathlib import Path
import asyncio # For concurrent loading if operations become async
from typing import Optional # For optional query parameters
from .config import settings # Use relative import if config.py is in the same 'app' package

app = FastAPI()

# --- Robust path to templates directory ---
# Get the directory of the current file (app.py)
APP_DIR = Path(__file__).resolve().parent
# Go up one level to the project root
PROJECT_ROOT = APP_DIR.parent
# Construct the path to the templates directory
TEMPLATES_DIR = PROJECT_ROOT / "web" / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# If remote folder names differ from the simple mission IDs (e.g., "m203")
REMOTE_MISSION_FOLDER_MAP = {
    "m203": "m203-SV3-1070 (C34164NS)",
    # Add other mappings here from your cli.py or as needed
}

# Consider making load_report in mission_core async if it involves I/O
# For this example, we'll assume load_report remains synchronous for now,
# but show how to adapt if it were async.

def load_data_source(report_type: str, mission_id: str):
    """Attempts to load data, trying remote then local sources."""
    try:
        # Try remote URL first
        logger.info(f"Attempting local load for {report_type} (mission: {mission_id}) from {settings.local_data_base_path}")
        # Pass base_path to core.loaders.load_report
        return loaders.load_report(report_type, mission_id, base_path=settings.local_data_base_path)
    except FileNotFoundError:
        logger.warning(f"Local file for {report_type} ({mission_id}) not found at {settings.local_data_base_path}. Falling back to remote.")
    except Exception as e:
        logger.warning(f"Local load failed for {report_type} ({mission_id}): {e}. Falling back to remote.")

    # Fallback to remote if local fails or not found
    try:
        # Use the mapping for remote folder names
        remote_mission_folder = REMOTE_MISSION_FOLDER_MAP.get(mission_id, mission_id)
        logger.info(f"Attempting remote load for {report_type} (mission: {mission_id}, remote folder: {remote_mission_folder}) from {settings.remote_data_url}")
        # Pass base_url to core.loaders.load_report
        return loaders.load_report(report_type, mission_id=remote_mission_folder, base_url=settings.remote_data_url)
    except Exception as e_remote:
        logger.error(f"Remote load also failed for {report_type} ({mission_id}): {e_remote}")
        # Return None or an empty DataFrame, or raise a custom error
        return None # Or pd.DataFrame() if preferred to avoid None checks later

@app.get("/", response_class=HTMLResponse)
async def home(request: Request, mission: str = "m203", hours: int = 72):
    # If load_report (and thus load_data_source) were async:
    # results = await asyncio.gather(
    #     load_data_source("power", mission),
    #     load_data_source("ctd", mission),
    #     load_data_source("weather", mission),
    #     load_data_source("waves", mission),
    #     load_data_source("ais", mission),
    #     load_data_source("errors", mission),
    #     return_exceptions=True # To handle individual load failures
    # )
    # df_power, df_ctd, df_weather, df_waves, df_ais, df_errors = results
    # Then check if any result is an exception or None

    # Synchronous loading (current approach)
    df_power = load_data_source("power", mission)
    df_ctd = load_data_source("ctd", mission)
    df_weather = load_data_source("weather", mission)
    df_waves = load_data_source("waves", mission)
    df_ais = load_data_source("ais", mission)
    df_errors = load_data_source("errors", mission)

    # Get status using the new standardized functions
    # The keys in these dicts now match our defined standard
    power_status = summaries.get_power_status(df_power) if df_power is not None and not df_power.empty else None
    ctd_status = summaries.get_ctd_status(df_ctd) if df_ctd is not None and not df_ctd.empty else None
    weather_status = summaries.get_weather_status(df_weather) if df_weather is not None and not df_weather.empty else None
    wave_status = summaries.get_wave_status(df_waves) if df_waves is not None and not df_waves.empty else None
    ais_summary_data = summaries.get_ais_summary(df_ais, max_age_hours=hours) if df_ais is not None else [] 
    recent_errors_list = summaries.get_recent_errors(df_errors, max_age_hours=hours)[:20] if df_errors is not None else []

    return templates.TemplateResponse("index.html", {
        "request": request,
        "mission": mission,
        "power": power_status if power_status else "Data unavailable",
        "ctd": ctd_status if ctd_status else "Data unavailable",
        "weather": weather_status if weather_status else "Data unavailable",
        "waves": wave_status if wave_status else "Data unavailable",
        "ais": ais_summary_data if ais_summary_data is not None else "Data unavailable",
        "errors": recent_errors_list if recent_errors_list is not None else [], # recent_errors can be an empty list
    })

# --- API Endpoints ---

@app.get("/api/data/{report_type}/{mission_id}")
async def get_report_data_for_plotting(
    report_type: str,
    mission_id: str,
    hours_back: int = 72
):
    """
    Provides processed time-series data for a given report type,
    suitable for frontend plotting.
    """
    df = load_data_source(report_type, mission_id)

    if df is None or df.empty:
        raise HTTPException(status_code=404, detail=f"Data not found for {report_type}, mission {mission_id}")

    # Preprocess based on report type
    # This mirrors the preprocessing steps in your plotting.py and summaries.py
    if report_type == "power":
        processed_df = processors.preprocess_power_df(df)
    elif report_type == "ctd":
        processed_df = processors.preprocess_ctd_df(df)
    elif report_type == "weather":
        processed_df = processors.preprocess_weather_df(df)
    elif report_type == "waves":
        processed_df = processors.preprocess_wave_df(df)
    # Add other report types as needed
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported report type: {report_type}")

    if processed_df.empty or "Timestamp" not in processed_df.columns:
        raise HTTPException(status_code=404, detail=f"No processable data after preprocessing for {report_type}, mission {mission_id}")

    # Filter by time
    recent_data = processed_df[processed_df["Timestamp"] > datetime.now() - timedelta(hours=hours_back)]
    if recent_data.empty:
        return [] # Return empty list if no recent data, or raise 404

    # Resample to hourly mean (similar to your plotting scripts)
    data_to_resample = recent_data.set_index("Timestamp")
    numeric_cols = data_to_resample.select_dtypes(include=[np.number])
    hourly_data = numeric_cols.resample('1h').mean().reset_index() # reset_index to make Timestamp a column again

    return JSONResponse(content=hourly_data.to_dict(orient="records"))


@app.get("/api/forecast/{mission_id}")
async def get_weather_forecast(
    mission_id: str,
    lat: Optional[float] = None,
    lon: Optional[float] = None
):
    """
    Provides a weather forecast.
    If lat and lon are not provided, it attempts to infer them from the latest telemetry data.
    """
    final_lat, final_lon = lat, lon

    if final_lat is None or final_lon is None:
        logger.info(f"Latitude/Longitude not provided for forecast. Attempting to infer from telemetry for mission {mission_id}.")
        df_telemetry = load_data_source("telemetry", mission_id)

        if df_telemetry is None or df_telemetry.empty:
            logger.warning(f"Telemetry data for mission {mission_id} not found or empty. Cannot infer location.")
        else:
            # Ensure 'lastLocationFix' is datetime and sort
            if "lastLocationFix" in df_telemetry.columns:
                df_telemetry["lastLocationFix"] = pd.to_datetime(df_telemetry["lastLocationFix"], errors="coerce")
                df_telemetry = df_telemetry.dropna(subset=["lastLocationFix"]) # Remove rows where conversion failed
                if not df_telemetry.empty:
                    latest_telemetry = df_telemetry.sort_values("lastLocationFix", ascending=False).iloc[0]
                    # Try to get lat/lon, allowing for different capitalizations
                    inferred_lat = latest_telemetry.get("latitude") or latest_telemetry.get("Latitude")
                    inferred_lon = latest_telemetry.get("longitude") or latest_telemetry.get("Longitude")

                    if not pd.isna(inferred_lat) and not pd.isna(inferred_lon):
                        final_lat, final_lon = float(inferred_lat), float(inferred_lon)
                        logger.info(f"Inferred location for mission {mission_id}: Lat={final_lat}, Lon={final_lon}")
                    else:
                        logger.warning(f"Could not extract valid lat/lon from latest telemetry for mission {mission_id}.")

    if final_lat is None or final_lon is None:
        raise HTTPException(status_code=400, detail="Latitude and Longitude are required for forecast and could not be inferred from telemetry.")

    forecast_data = forecast.get_open_meteo_forecast(final_lat, final_lon)
    if forecast_data is None:
        raise HTTPException(status_code=503, detail="Weather forecast service unavailable or failed to retrieve data.")

    return JSONResponse(content=forecast_data)