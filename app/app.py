from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse # type: ignore
from fastapi.templating import Jinja2Templates
from .core import loaders, summaries, processors, forecast
from datetime import datetime, timedelta
import logging
import pandas as pd # For DataFrame operations
import numpy as np # For numeric operations if needed
from pathlib import Path
import asyncio # For concurrent loading if operations become async
import httpx # For async client in load_data_source
from typing import Optional # For optional query parameters
from .config import settings # Use relative import if config.py is in the same 'app' package
from .core import utils
app = FastAPI()

# --- Robust path to templates directory ---
# Get the directory of the current file (app.py)
APP_DIR = Path(__file__).resolve().parent
# Go up one level to the project root
PROJECT_ROOT = APP_DIR.parent
# Construct the path to the templates directory
TEMPLATES_DIR = PROJECT_ROOT / "web" / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Mount the static files directory
app.mount("/static", StaticFiles(directory=str(PROJECT_ROOT / "web" / "static")), name="static")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
# ---
async def load_data_source(
    report_type: str,
    mission_id: str,
    client: Optional[httpx.AsyncClient] = None,
    source_preference: Optional[str] = None, # 'local' or 'remote'
    custom_local_path: Optional[str] = None
):
    """Attempts to load data, trying remote then local sources."""
    df = None
    actual_source_path = "Data not loaded" # Initialize with a default
    load_attempted = False

    if source_preference == 'local': # Local-only preference
        load_attempted = True
        if custom_local_path:
            try:
                logger.info(f"Attempting local load for {report_type} (mission: {mission_id}) from custom path: {custom_local_path}")
                df = await loaders.load_report(report_type, mission_id, base_path=Path(custom_local_path), client=None)
                if df is not None and not df.empty:
                    # Assuming loaders.load_report uses mission_id to find a subfolder or file within custom_local_path
                    actual_source_path = f"Local (Custom): {Path(custom_local_path) / mission_id}"
            except FileNotFoundError:
                logger.warning(f"Custom local file for {report_type} ({mission_id}) not found at {custom_local_path}. Trying default local.")
                df = None # Ensure df is None to trigger default local load
            except Exception as e:
                logger.warning(f"Custom local load failed for {report_type} ({mission_id}) from {custom_local_path}: {e}. Trying default local.")
                df = None # Ensure df is None to trigger default local load
        
        if df is None: # If custom path failed or wasn't provided
            try:
                logger.info(f"Attempting local load for {report_type} (mission: {mission_id}) from default local path: {settings.local_data_base_path}")
                df = await loaders.load_report(report_type, mission_id, base_path=settings.local_data_base_path, client=None)
                if df is not None and not df.empty:
                    actual_source_path = f"Local (Default): {settings.local_data_base_path / mission_id}"
            except FileNotFoundError:
                logger.warning(f"Default local file for {report_type} ({mission_id}) not found at {settings.local_data_base_path}.")
            except Exception as e:
                logger.warning(f"Default local load failed for {report_type} ({mission_id}): {e}.")
        # If 'local' was preferred and custom_local_path was provided but failed,
        # the above block handles the default local attempt.
        # If local was preferred and even default local fails, df will remain None.

    # Remote-first or default behavior (remote then local fallback)
    elif source_preference == 'remote' or source_preference is None:
        load_attempted = True
        remote_mission_folder = settings.remote_mission_folder_map.get(mission_id, mission_id)
        
        # Define potential remote base paths to try, in order of preference
        # Ensure no double slashes if settings.remote_data_url ends with /
        base_remote_url = settings.remote_data_url.rstrip('/') 
        remote_base_urls_to_try = [
            f"{base_remote_url}/output_realtime_missions", # No trailing slash
            f"{base_remote_url}/output_past_missions"  # No trailing slash
        ]
        
        # df is already None or potentially loaded from a previous 'local' only preference if logic were different
        # For remote-first, we ensure df starts as None for the remote attempts.
        df = None 
        for constructed_base_url in remote_base_urls_to_try:
            # The `async with` block for remote_client was here but not used due to indentation.
            # loaders.load_report is called with client=None below.
            try:
                logger.info(f"Attempting remote load for {report_type} (mission: {mission_id}, remote folder: {remote_mission_folder}) from base: {constructed_base_url} (client=None)")
                df_attempt = await loaders.load_report(report_type, mission_id=remote_mission_folder, base_url=constructed_base_url, client=None)
                if df_attempt is not None and not df_attempt.empty:
                    df = df_attempt
                    actual_source_path = f"Remote: {constructed_base_url}/{remote_mission_folder}"
                    logger.info(f"Successfully loaded {report_type} for mission {mission_id} from {actual_source_path}")
                    break # Data found, no need to try other remote paths
            except httpx.HTTPStatusError as e_http: # Catch HTTPStatusError specifically
                if e_http.response.status_code == 404 and "output_realtime_missions" in constructed_base_url:
                    logger.info(f"File not found in realtime path (expected for past missions): {constructed_base_url}/{remote_mission_folder} for {report_type} ({mission_id}). Will try next path.")
                else: # Other HTTP errors or 404s from other paths remain warnings
                    logger.warning(f"Remote load attempt from {constructed_base_url} (client=None) failed for {report_type} ({mission_id}): {e_http}")
            except Exception as e_remote_attempt:
                logger.warning(f"General remote load attempt from {constructed_base_url} (client=None) failed for {report_type} ({mission_id}): {e_remote_attempt}")
        
        if df is None or df.empty: # If all remote attempts failed
            logger.warning(f"All remote load attempts failed for {report_type} ({mission_id}). Falling back to default local.")
            # For local fallback, pass client=None.
            # The `client` parameter to load_data_source is not used in the home route anymore.
            if client: await client.aclose() # Close if an external client was passed and not used for remote.
            try:
                logger.info(f"Attempting fallback local load for {report_type} (mission: {mission_id}) from {settings.local_data_base_path}")
                df = await loaders.load_report(report_type, mission_id, base_path=settings.local_data_base_path, client=None)
            except Exception as e_local_fallback:
                logger.error(f"Fallback local load also failed for {report_type} ({mission_id}): {e_local_fallback}")

    if not load_attempted: # Should not happen with current logic, but as a safeguard
         logger.error(f"No load attempt made for {report_type} ({mission_id}) with preference '{source_preference}'. This is unexpected.")
    # Ensure any externally passed client is closed if this function didn't use it for remote and it wasn't closed already.
    # This is a bit tricky because the home route no longer passes a client.
    # The `client` parameter to `load_data_source` is now effectively unused by the main `home` route.
    # If it were to be used by another part of the system that *does* pass a client,
    # that calling code would be responsible for managing that client's lifecycle.
    # For now, the explicit `if client: await client.aclose()` in the fallback sections handles it if it was passed.    
    return df, actual_source_path
# ---
@app.get("/", response_class=HTMLResponse)
async def home(request: Request, mission: str = "m203", hours: int = 72, source: Optional[str] = None, local_path: Optional[str] = None):
    available_missions = list(settings.remote_mission_folder_map.keys())
    # Client will now be managed by each load_data_source call individually
    results = await asyncio.gather(
        load_data_source("power", mission, source_preference=source, custom_local_path=local_path),
        load_data_source("ctd", mission, source_preference=source, custom_local_path=local_path),
        load_data_source("weather", mission, source_preference=source, custom_local_path=local_path),
        load_data_source("waves", mission, source_preference=source, custom_local_path=local_path),
        load_data_source("ais", mission, source_preference=source, custom_local_path=local_path),
        load_data_source("errors", mission, source_preference=source, custom_local_path=local_path),
        return_exceptions=True # To handle individual load failures
    )

    # Unpack results and source paths
    data_frames: Dict[str, Optional[pd.DataFrame]] = {}
    source_paths_map: Dict[str, str] = {}
    report_types_order = ["power", "ctd", "weather", "waves", "ais", "errors"]

    for i, report_type in enumerate(report_types_order):
        if isinstance(results[i], Exception):
            data_frames[report_type] = None
            source_paths_map[report_type] = "Error during load"
            logger.error(f"Exception loading {report_type} for mission {mission}: {results[i]}")
        else:
            data_frames[report_type], source_paths_map[report_type] = results[i]

    df_power = data_frames["power"]
    df_ctd = data_frames["ctd"]
    df_weather = data_frames["weather"]
    df_waves = data_frames["waves"]
    df_ais = data_frames["ais"]
    df_errors = data_frames["errors"]

    # Determine the primary display_source_path based on success and priority
    display_source_path = "Data Source: Information unavailable or all loads failed"
    found_primary_path_for_display = False # Flag to break outer loop

    priority_paths = [
        (lambda p: "Remote:" in p and "output_realtime_missions" in p),
        (lambda p: "Remote:" in p and "output_past_missions" in p),
        (lambda p: "Local (Custom):" in p and "Data not loaded" not in p),
        (lambda p: "Local (Default):" in p and "Data not loaded" not in p)
    ]
    for check_priority in priority_paths:
        for report_type in report_types_order: # Check in defined order if needed, or any order
            path_info = source_paths_map.get(report_type, "")
            if check_priority(path_info):
                # Strip the prefix from path_info
                path_to_display = path_info
                if path_info.startswith("Remote: "):
                    path_to_display = path_info.replace("Remote: ", "", 1).strip()
                elif path_info.startswith("Local (Custom): "):
                    path_to_display = path_info.replace("Local (Custom): ", "", 1).strip()
                elif path_info.startswith("Local (Default): "):
                    path_to_display = path_info.replace("Local (Default): ", "", 1).strip()
                
                display_source_path = f"Data Source: {path_to_display}"
                found_primary_path_for_display = True # Found our primary display path
                break
        if found_primary_path_for_display:
            break # Exit outer loop once a primary path is found

    # Get status and update info using the refactored summary functions
    power_info = summaries.get_power_status(df_power)
    ctd_info = summaries.get_ctd_status(df_ctd) # Assuming you refactor this
    weather_info = summaries.get_weather_status(df_weather) # Assuming you refactor this
    wave_info = summaries.get_wave_status(df_waves) # Assuming you refactor this
    
    # For AIS and Errors, get summary list and then derive update info from original DFs
    ais_summary_data = summaries.get_ais_summary(df_ais, max_age_hours=hours) if df_ais is not None else []
    ais_update_info = utils.get_df_latest_update_info(df_ais, timestamp_col="LastSeenTimestamp") # Adjust col if needed 
    recent_errors_list = summaries.get_recent_errors(df_errors, max_age_hours=hours)[:20] if df_errors is not None else []
    errors_update_info = utils.get_df_latest_update_info(df_errors, timestamp_col="Timestamp") # Adjust col if needed

    # --- Add this debugging block ---
    logger.info("--- Debugging Template Context ---")
    logger.info(f"Type of power_info: {type(power_info)}")
    if isinstance(power_info, dict):
        logger.info(f"Keys in power_info: {list(power_info.keys())}")
        if "values" in power_info:
            logger.info(f"Type of power_info['values']: {type(power_info['values'])}")
            if isinstance(power_info["values"], dict):
                logger.info(f"Keys in power_info['values']: {list(power_info['values'].keys())}")
            else:
                logger.info(f"Content of power_info['values']: {power_info['values']}")
        else:
            logger.info("'values' key NOT found in power_info. power_info content: %s", power_info)
    else:
        logger.info(f"power_info is not a dictionary. Content: {power_info}")
    # --- End of debugging block ---

    return templates.TemplateResponse("index.html", {
        "request": request,
        "mission": mission,
        "available_missions": available_missions,
        "current_source_preference": source, # User's preference (local/remote)
        "default_local_data_path": str(settings.local_data_base_path), # Pass default path
        "display_source_path": display_source_path, # The determined actual source path
        "current_local_path": local_path, # Pass current local_path
        "power_info": power_info,
        "ctd_info": ctd_info, # This will be the dict from refactored get_ctd_status
        "weather_info": weather_info, # Dict from refactored get_weather_status
        "wave_info": wave_info, # Dict from refactored get_wave_status
        "ais_summary_data": ais_summary_data,
        "ais_update_info": ais_update_info,
        "errors_summary_data": recent_errors_list,
        "errors_update_info": errors_update_info,
    })

# --- API Endpoints ---

@app.get("/api/data/{report_type}/{mission_id}")
async def get_report_data_for_plotting(
    report_type: str,
    mission_id: str,
    hours_back: int = 72,
    source: Optional[str] = None, # Add source preference
    local_path: Optional[str] = None # Add custom local path
):
    """
    Provides processed time-series data for a given report type,
    suitable for frontend plotting.
    """
    # Unpack the DataFrame and the source path; we only need the DataFrame here
    df, _ = await load_data_source(report_type, mission_id, source_preference=source, custom_local_path=local_path)

    if df is None or df.empty:
        # Return empty list for charts instead of 404 to allow chart to render "no data"
        return JSONResponse(content=[]) 

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
        # Should not happen if report_type is validated by frontend, but good practice
        raise HTTPException(status_code=400, detail=f"Unsupported report type for plotting: {report_type}")

    if processed_df.empty or "Timestamp" not in processed_df.columns:
        logger.warning(f"No processable data after preprocessing for {report_type}, mission {mission_id}")
        return JSONResponse(content=[])

    # Determine the most recent timestamp in the data
    max_timestamp = processed_df["Timestamp"].max()

    if pd.isna(max_timestamp):
        logger.warning(f"No valid timestamps found in processed data for {report_type}, mission {mission_id} after preprocessing.")
        return JSONResponse(content=[])

    # Calculate the cutoff time based on the most recent data point
    cutoff_time = max_timestamp - timedelta(hours=hours_back)
    recent_data = processed_df[processed_df["Timestamp"] > cutoff_time]
    if recent_data.empty:
        logger.info(f"No data found for {report_type}, mission {mission_id} within {hours_back} hours of its latest data point ({max_timestamp}).")
        return JSONResponse(content=[])
        
    
    # Resample to hourly mean (similar to your plotting scripts)
    data_to_resample = recent_data.set_index("Timestamp")
    numeric_cols = data_to_resample.select_dtypes(include=[np.number])
    # Ensure numeric_cols is not empty before resampling
    if numeric_cols.empty:
        logger.info(f"No numeric data to resample for {report_type}, mission {mission_id} after filtering.")
        return JSONResponse(content=[])
    hourly_data = numeric_cols.resample('1h').mean().reset_index() # reset_index to make Timestamp a column again

    # Convert Timestamp objects to ISO 8601 strings for JSON serialization
    if "Timestamp" in hourly_data.columns:
        hourly_data["Timestamp"] = hourly_data["Timestamp"].dt.strftime('%Y-%m-%dT%H:%M:%S')

    # Replace NaN with None for JSON compatibility
    hourly_data = hourly_data.replace({np.nan: None})
    return JSONResponse(content=hourly_data.to_dict(orient="records"))
# ---
@app.get("/api/forecast/{mission_id}")
async def get_weather_forecast(
    mission_id: str,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    source: Optional[str] = None, # Add source preference for telemetry
    local_path: Optional[str] = None # Add custom local path for telemetry
):
    """
    Provides a weather forecast.
    If lat and lon are not provided, it attempts to infer them from the latest telemetry data.
    """
    final_lat, final_lon = lat, lon

    if final_lat is None or final_lon is None:
        logger.info(f"Latitude/Longitude not provided for forecast. Attempting to infer from telemetry for mission {mission_id}.")
        # Pass source preference to telemetry loading
        # Unpack the DataFrame and the source path; we only need the DataFrame here
        df_telemetry, _ = await load_data_source("telemetry", mission_id, source_preference=source, custom_local_path=local_path)

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