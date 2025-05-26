from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse # type: ignore
from fastapi.templating import Jinja2Templates
from .core import loaders, summaries, processors, forecast # type: ignore
from datetime import datetime, timedelta
import logging
import pandas as pd # For DataFrame operations
import numpy as np # For numeric operations if needed
from pathlib import Path
import asyncio # For concurrent loading if operations become async
import httpx # For async client in load_data_source
from typing import Optional, Dict, Tuple # For optional query parameters and type hints
from .config import settings # Use relative import if config.py is in the same 'app' package
from .core import utils
import time # Import the time module
from apscheduler.schedulers.asyncio import AsyncIOScheduler # For background tasks
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

# --- Custom UTC Formatter for Logging ---
class UTCFormatter(logging.Formatter):
    converter = time.gmtime

# --- Configure Logging ---
# Use path from settings, defaulting to project root if relative path is in settings and .env is not used
if settings.log_file_path.is_absolute():
    LOG_FILE_PATH = settings.log_file_path
else:
    LOG_FILE_PATH = PROJECT_ROOT / settings.log_file_path

# Get the root logger
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO) # Set level for the root logger

# Create formatter
formatter = UTCFormatter(
    fmt="%(asctime)s.%(msecs)03d UTC | %(levelname)-8s | %(name)-25s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# Create file handler and set formatter
file_handler = logging.FileHandler(LOG_FILE_PATH, mode='w') # 'a' appends, 'w' write/overwrite
file_handler.setFormatter(formatter)
root_logger.addHandler(file_handler)

# Create console handler and set formatter (if not already configured by Uvicorn/FastAPI default)
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
root_logger.addHandler(console_handler)

logger = logging.getLogger(__name__)
# ---

# In-memory cache: key -> (DataFrame, actual_source_path_str, cache_timestamp)
data_cache: Dict[Tuple, Tuple[pd.DataFrame, str, datetime]] = {}
# CACHE_EXPIRY_MINUTES is now used by the background task interval and for individual cache item expiry
# if it's a real-time source and the background task hasn't run yet.
CACHE_EXPIRY_MINUTES = settings.background_cache_refresh_interval_minutes


async def load_data_source(
    report_type: str,
    mission_id: str,
    source_preference: Optional[str] = None, # 'local' or 'remote'
    custom_local_path: Optional[str] = None,
    force_refresh: bool = False # New parameter to bypass cache
):
    """Attempts to load data, trying remote then local sources."""
    df = None
    actual_source_path = "Data not loaded" # Initialize with a default

    cache_key = (mission_id, report_type, source_preference, custom_local_path)

    if not force_refresh and cache_key in data_cache:
        cached_df, cached_source_path, cache_timestamp = data_cache[cache_key]

        # Determine if the cached data is from a real-time remote source
        is_realtime_remote_source = "Remote:" in cached_source_path and "output_realtime_missions" in cached_source_path

        if is_realtime_remote_source:
            # For real-time remote sources, check expiry
            if datetime.now() - cache_timestamp < timedelta(minutes=CACHE_EXPIRY_MINUTES):
                logger.info(f"CACHE HIT (valid - real-time): Returning {report_type} for {mission_id} from cache. Original source: {cached_source_path}")
                return cached_df, cached_source_path
            else:
                logger.info(f"Cache hit (expired - real-time) for {report_type} ({mission_id}). Will refresh.")
        else:
            # For past remote missions and all local files, treat cache as always valid (static for app lifecycle)
            logger.info(f"Cache hit (valid - static/local) for {report_type} ({mission_id}). Returning cached data from {cached_source_path}.")
            return cached_df, cached_source_path
    # If we reach here, it's a cache miss (or forced refresh/expired)
    elif force_refresh:
        logger.info(f"Force refresh requested for {report_type} ({mission_id}). Bypassing cache.")

    load_attempted = False
    if source_preference == 'local': # Local-only preference
        load_attempted = True
        if custom_local_path:
            _custom_local_path_str = f"Local (Custom): {Path(custom_local_path) / mission_id}"
            _attempted_custom_local = False
            try:
                logger.info(f"Attempting local load for {report_type} (mission: {mission_id}) from custom path: {custom_local_path}")
                df_attempt = await loaders.load_report(report_type, mission_id, base_path=Path(custom_local_path))
                _attempted_custom_local = True # File was accessed or attempted beyond FNF
                if df_attempt is not None and not df_attempt.empty:
                    df = df_attempt
                    actual_source_path = _custom_local_path_str
                elif _attempted_custom_local and actual_source_path == "Data not loaded": # File accessed but empty
                    actual_source_path = _custom_local_path_str
            except FileNotFoundError:
                logger.warning(f"Custom local file for {report_type} ({mission_id}) not found at {custom_local_path}. Trying default local.")
                df = None # Ensure df is None to trigger default local load
            except Exception as e:
                logger.warning(f"Custom local load failed for {report_type} ({mission_id}) from {custom_local_path}: {e}. Trying default local.")
                if _attempted_custom_local and actual_source_path == "Data not loaded": # Path was attempted, but an error occurred
                    actual_source_path = _custom_local_path_str
                df = None # Ensure df is None to trigger default local load

        if df is None: # If custom path failed, wasn't provided, or yielded no usable data
            _default_local_path_str = f"Local (Default): {settings.local_data_base_path / mission_id}"
            _attempted_default_local = False
            try:
                logger.info(f"Attempting local load for {report_type} (mission: {mission_id}) from default local path: {settings.local_data_base_path}")
                df_attempt = await loaders.load_report(report_type, mission_id, base_path=settings.local_data_base_path)
                _attempted_default_local = True
                if df_attempt is not None and not df_attempt.empty:
                    df = df_attempt
                    actual_source_path = _default_local_path_str
                elif _attempted_default_local and actual_source_path == "Data not loaded": # File accessed but empty
                    actual_source_path = _default_local_path_str
            except FileNotFoundError:
                logger.warning(f"Default local file for {report_type} ({mission_id}) not found at {settings.local_data_base_path}.")
            except Exception as e:
                logger.warning(f"Default local load failed for {report_type} ({mission_id}): {e}.")
                if _attempted_default_local and actual_source_path == "Data not loaded": # Path was attempted, but an error occurred
                    actual_source_path = _default_local_path_str
                df = None # Ensure df is None on other errors
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
        df = None 
        last_accessed_remote_path_if_empty = None # Track if a remote file was found but empty
        for constructed_base_url in remote_base_urls_to_try:
            # THIS IS THE CRUCIAL PART: Ensure client is managed per-attempt
            async with httpx.AsyncClient() as current_client: # Client is created and closed for each URL in the loop
                try:
                    logger.info(f"Attempting remote load for {report_type} (mission: {mission_id}, remote folder: {remote_mission_folder}) from base: {constructed_base_url}")
                    # Pass this specific client to loaders.load_report
                    df_attempt = await loaders.load_report(report_type, mission_id=remote_mission_folder, base_url=constructed_base_url, client=current_client)
                    if df_attempt is not None and not df_attempt.empty:
                        df = df_attempt
                        actual_source_path = f"Remote: {constructed_base_url}/{remote_mission_folder}"
                        logger.info(f"Successfully loaded {report_type} for mission {mission_id} from {actual_source_path}")
                        break # Data found, no need to try other remote paths
                    elif df_attempt is not None: # File found and read, but resulted in an empty DataFrame
                        last_accessed_remote_path_if_empty = f"Remote: {constructed_base_url}/{remote_mission_folder}" # Mark path as "touched"
                        logger.info(f"Remote file found but empty for {report_type} ({mission_id}) from {last_accessed_remote_path_if_empty}. Will try next path or fallback.")
                except httpx.HTTPStatusError as e_http: # Catch HTTPStatusError specifically
                    if e_http.response.status_code == 404 and "output_realtime_missions" in constructed_base_url:
                        logger.info(f"File not found in realtime path (expected for past missions): {constructed_base_url}/{remote_mission_folder} for {report_type} ({mission_id}). Will try next path.")
                    else: # Other HTTP errors or 404s from other paths remain warnings
                        logger.warning(f"Remote load attempt from {constructed_base_url} failed for {report_type} ({mission_id}): {e_http}")
                except Exception as e_remote_attempt: # This will catch the "Cannot open a client instance more than once" if client is misused
                    logger.warning(f"General remote load attempt from {constructed_base_url} failed for {report_type} ({mission_id}): {e_remote_attempt}")

        if df is None or df.empty: # If all remote attempts failed
            logger.warning(f"No usable remote data found for {report_type} ({mission_id}). Falling back to default local.")
            # No external client to close here as it's managed internally or not passed by home route
            _local_fallback_path_str = f"Local (Default Fallback): {settings.local_data_base_path / mission_id}"
            _attempted_local_fallback = False
            try:
                logger.info(f"Attempting fallback local load for {report_type} (mission: {mission_id}) from {settings.local_data_base_path}")
                df_fallback = await loaders.load_report(report_type, mission_id, base_path=settings.local_data_base_path)
                _attempted_local_fallback = True
                if df_fallback is not None and not df_fallback.empty:
                    df = df_fallback
                    actual_source_path = _local_fallback_path_str
                elif _attempted_local_fallback: # Local file accessed but was empty
                    actual_source_path = _local_fallback_path_str
            except FileNotFoundError:
                _msg = f"Fallback local file not found for {report_type} ({mission_id}) at {settings.local_data_base_path / mission_id}"
                logger.info(_msg)
                if last_accessed_remote_path_if_empty and actual_source_path == "Data not loaded": # If a remote file was found but empty, and local fallback FNF
                    actual_source_path = last_accessed_remote_path_if_empty
                elif actual_source_path == "Data not loaded": # If no remote file was touched either
                    actual_source_path = f"Local (Default Fallback): File Not Found - {_local_fallback_path_str.split(':', 1)[1].strip()}"
            except Exception as e_local_fallback: # Other error during local fallback
                logger.error(f"Fallback local load also failed for {report_type} ({mission_id}): {e_local_fallback}")
                if _attempted_local_fallback and actual_source_path == "Data not loaded": # Path was attempted, but an error occurred
                    actual_source_path = _local_fallback_path_str
                df = None # Ensure df is None on other errors
        elif last_accessed_remote_path_if_empty and actual_source_path == "Data not loaded": # If df was populated by remote, but an earlier remote attempt found an empty file
            pass # actual_source_path is already correctly set to the non-empty remote source

    if not load_attempted: # Should not happen with current logic, but as a safeguard
         logger.error(f"No load attempt made for {report_type} ({mission_id}) with preference '{source_preference}'. This is unexpected.")

    if df is not None and not df.empty:
        logger.info(f"CACHE STORE: Storing {report_type} for {mission_id} (from {actual_source_path}) into cache.")
        data_cache[cache_key] = (df, actual_source_path, datetime.now()) # Store with current timestamp

    return df, actual_source_path
# ---

# --- Background Cache Refresh Task ---
scheduler = AsyncIOScheduler()

async def refresh_active_mission_cache():
    logger.info("BACKGROUND TASK: Starting proactive cache refresh for active real-time missions.")
    active_missions = settings.active_realtime_missions
    # Define report types typically found in real-time missions
    # You might want to make this configurable or more dynamic
    realtime_report_types = ["power", "ctd", "weather", "waves", "telemetry", "ais", "errors", "vr2c", "fluorometer"]

    for mission_id in active_missions:
        logger.info(f"BACKGROUND TASK: Refreshing cache for active mission: {mission_id}")
        for report_type in realtime_report_types:
            try:
                # We force refresh and specify 'remote' as source_preference
                # because we are targeting 'output_realtime_missions'
                await load_data_source(
                    report_type,
                    mission_id,
                    source_preference='remote', # Ensure it tries remote (specifically output_realtime_missions first)
                    force_refresh=True
                )
            except Exception as e:
                logger.error(f"BACKGROUND TASK: Error refreshing cache for {report_type} on mission {mission_id}: {e}")
    logger.info("BACKGROUND TASK: Proactive cache refresh for active real-time missions completed.")

# --- FastAPI Lifecycle Events for Scheduler ---
@app.on_event("startup")
async def startup_event():
    scheduler.add_job(refresh_active_mission_cache, 'interval', minutes=settings.background_cache_refresh_interval_minutes, id="active_mission_refresh_job")
    scheduler.start()
    logger.info("APScheduler started for background cache refresh.")
    # Trigger an initial refresh shortly after startup
    asyncio.create_task(refresh_active_mission_cache())

@app.on_event("shutdown")
def shutdown_event():
    scheduler.shutdown()
    logger.info("APScheduler shut down.")

@app.get("/", response_class=HTMLResponse)
async def home(request: Request, mission: str = "m203", hours: int = 72, source: Optional[str] = None, local_path: Optional[str] = None, refresh: bool = False):
    available_missions = list(settings.remote_mission_folder_map.keys())
    
    # Determine if the current mission is an active real-time mission
    is_current_mission_realtime = mission in settings.active_realtime_missions
    # Client will now be managed by each load_data_source call individually
    results = await asyncio.gather(
        load_data_source("power", mission, source_preference=source, custom_local_path=local_path, force_refresh=refresh),
        load_data_source("ctd", mission, source_preference=source, custom_local_path=local_path, force_refresh=refresh),
        load_data_source("weather", mission, source_preference=source, custom_local_path=local_path, force_refresh=refresh),
        load_data_source("waves", mission, source_preference=source, custom_local_path=local_path, force_refresh=refresh),
        # Corrected order to match report_types_order for vr2c and fluorometer
        load_data_source("vr2c", mission, source_preference=source, custom_local_path=local_path, force_refresh=refresh), 
        load_data_source("solar", mission, source_preference=source, custom_local_path=local_path, force_refresh=refresh), # Load solar data
        load_data_source("fluorometer", mission, source_preference=source, custom_local_path=local_path, force_refresh=refresh),
        load_data_source("ais", mission, source_preference=source, custom_local_path=local_path, force_refresh=refresh),
        load_data_source("errors", mission, source_preference=source, custom_local_path=local_path, force_refresh=refresh),
        return_exceptions=True # To handle individual load failures
    )

    # Unpack results and source paths
    data_frames: Dict[str, Optional[pd.DataFrame]] = {}
    source_paths_map: Dict[str, str] = {}
    # Ensure "error_frequency" is NOT in this list for the main page load.
    # This list is for data that populates the status cards and initial summaries.
    report_types_order = ["power", "ctd", "weather", "waves", "vr2c", "solar", "fluorometer", "ais", "errors"]

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
    df_vr2c = data_frames["vr2c"] # New sensor
    df_solar = data_frames["solar"] # New solar data
    df_fluorometer = data_frames["fluorometer"] # C3 Fluorometer

    # Determine the primary display_source_path based on success and priority
    display_source_path = "Data Source: Information unavailable or all loads failed"
    found_primary_path_for_display = False # Flag to break outer loop

    priority_paths = [
        (lambda p: "Remote:" in p and "output_realtime_missions" in p and "Data not loaded" not in p and "Error during load" not in p),
        (lambda p: "Remote:" in p and "output_past_missions" in p and "Data not loaded" not in p and "Error during load" not in p),
        (lambda p: "Local (Custom):" in p and "Data not loaded" not in p and "Error during load" not in p),
        (lambda p: p.startswith("Local (Default") and "Data not loaded" not in p and "Error during load" not in p) # Catches "Local (Default)" and "Local (Default Fallback)"
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
                    path_to_display = path_info.split(":", 1)[1].strip() if ":" in path_info else path_info # Handles "Local (Default)" and "Local (Default Fallback)"
                
                display_source_path = f"Data Source: {path_to_display}"
                found_primary_path_for_display = True # Found our primary display path
                break
        if found_primary_path_for_display:
            break # Exit outer loop once a primary path is found

    # Get status and update info using the refactored summary functions, add mini-trend dataframes

    power_info = summaries.get_power_status(df_power, df_solar) # Pass df_solar
    power_info["mini_trend"] = summaries.get_power_mini_trend(df_power)

    ctd_info = summaries.get_ctd_status(df_ctd)
    ctd_info["mini_trend"] = summaries.get_ctd_mini_trend(df_ctd)

    weather_info = summaries.get_weather_status(df_weather)
    weather_info["mini_trend"] = summaries.get_weather_mini_trend(df_weather)

    wave_info = summaries.get_wave_status(df_waves)
    wave_info["mini_trend"] = summaries.get_wave_mini_trend(df_waves)
    
    vr2c_info = summaries.get_vr2c_status(df_vr2c)
    vr2c_info["mini_trend"] = summaries.get_vr2c_mini_trend(df_vr2c)

    fluorometer_info = summaries.get_fluorometer_status(df_fluorometer)
    fluorometer_info["mini_trend"] = summaries.get_fluorometer_mini_trend(df_fluorometer)
    
    # For AIS and Errors, get summary list and then derive update info from original DFs
    ais_summary_data = summaries.get_ais_summary(df_ais, max_age_hours=hours) if df_ais is not None else []
    ais_update_info = utils.get_df_latest_update_info(df_ais, timestamp_col="LastSeenTimestamp") # Adjust col if needed 
    recent_errors_list = summaries.get_recent_errors(df_errors, max_age_hours=hours)[:20] if df_errors is not None else []
    errors_update_info = utils.get_df_latest_update_info(df_errors, timestamp_col="Timestamp") # Adjust col if needed

    # Flags for template to control collapse state and indicators
    has_ais_data = bool(ais_summary_data)
    has_errors_data = bool(recent_errors_list)

    return templates.TemplateResponse("index.html", {
        "request": request,
        "mission": mission,
        "available_missions": available_missions,
        "is_current_mission_realtime": is_current_mission_realtime, # Pass this to the template
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
        "has_ais_data": has_ais_data, #check
        "has_errors_data": has_errors_data, #check
        "fluorometer_info": fluorometer_info, # C3 Fluorometer
        "vr2c_info": vr2c_info, # Mrx
    })

# --- API Endpoints ---

@app.get("/api/data/{report_type}/{mission_id}")
async def get_report_data_for_plotting(
    report_type: str,
    mission_id: str,
    hours_back: int = 72,
    source: Optional[str] = None, # Add source preference
    local_path: Optional[str] = None, # Add custom local path
    refresh: bool = False # Add refresh parameter
):
    """
    Provides processed time-series data for a given report type,
    suitable for frontend plotting.
    """
    # Unpack the DataFrame and the source path; we only need the DataFrame here
    df, _ = await load_data_source(report_type, mission_id, source_preference=source, custom_local_path=local_path, force_refresh=refresh) # No client passed

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
    elif report_type == "vr2c": # New sensor
        processed_df = processors.preprocess_vr2c_df(df)
    elif report_type == "solar": # New solar panel data
        processed_df = processors.preprocess_solar_df(df)
    elif report_type == "fluorometer": # C3 Fluorometer
        processed_df = processors.preprocess_fluorometer_df(df)
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
    
    # Resample to hourly mean
    hourly_data = numeric_cols.resample('1h').mean().reset_index()

    if report_type == "vr2c" and "PingCount" in hourly_data.columns:
        hourly_data = hourly_data.sort_values(by="Timestamp") # Ensure sorted for correct diff
        hourly_data["PingCountDelta"] = hourly_data["PingCount"].diff()
        # The first PingCountDelta will be NaN, which is fine for plotting (Chart.js handles nulls)
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
    local_path: Optional[str] = None, # Add custom local path for telemetry
    refresh: bool = False, # Add refresh parameter
    force_marine: Optional[bool] = False # New parameter to force marine forecast
):
    """
    Provides a weather forecast.
    If lat and lon are not provided, it attempts to infer them from the latest telemetry data.
    """
    final_lat, final_lon = lat, lon

    if final_lat is None or final_lon is None:
        logger.info(f"Latitude/Longitude not provided for forecast. Attempting to infer from telemetry for mission {mission_id}.")
        # Pass source preference to telemetry loading
        # Unpack the DataFrame and the source path; we only need the DataFrame here, pass refresh. No client passed.
        df_telemetry, _ = await load_data_source("telemetry", mission_id, source_preference=source, custom_local_path=local_path, force_refresh=refresh)

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

    forecast_data = await forecast.get_open_meteo_forecast(final_lat, final_lon, force_marine=force_marine or False)
    if forecast_data is None:
        raise HTTPException(status_code=503, detail="Weather forecast service unavailable or failed to retrieve data.")

    return JSONResponse(content=forecast_data)