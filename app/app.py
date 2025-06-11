from fastapi import FastAPI, Request, HTTPException, Depends, status # Added status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse # type: ignore
from fastapi.templating import Jinja2Templates
from fastapi.security import OAuth2PasswordRequestForm
from .core import loaders, summaries, processors, forecast # type: ignore
from datetime import datetime, timedelta
import logging
import pandas as pd # For DataFrame operations
import numpy as np # For numeric operations if needed
from pathlib import Path
import asyncio
import httpx # For async client in load_data_source
from typing import Optional, Dict, Tuple, List # For optional query parameters and type hints
from .config import settings # Use relative import if config.py is in the same 'app' package
from .core import models
from .core.security import create_access_token, verify_password, get_password_hash
from .auth_utils import get_user_from_db, add_user_to_db, get_current_active_user, get_current_admin_user, get_current_pilot_user, get_optional_current_user # Added add_user_to_db
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

# In-memory cache: key -> (data, actual_source_path_str, cache_timestamp).
# 'data' is typically pd.DataFrame, but for 'processed_wave_spectrum' it's List[Dict].
# The type hint for data_cache needs to be more generic or use Union. For simplicity, keeping as is, but be mindful.
data_cache: Dict[Tuple, Tuple[pd.DataFrame, str, datetime]] = {}
# CACHE_EXPIRY_MINUTES is now used by the background task interval and for individual cache item expiry
# if it's a real-time source and the background task hasn't run yet.
CACHE_EXPIRY_MINUTES = settings.background_cache_refresh_interval_minutes


async def load_data_source(
    report_type: str,
    mission_id: str,
    source_preference: Optional[str] = None, # 'local' or 'remote'
    custom_local_path: Optional[str] = None,
    force_refresh: bool = False, # New parameter to bypass cache
    current_user: Optional[models.User] = None # Added current_user, make it optional for now for background task
):
    """Attempts to load data, trying remote then local sources."""
      # df variable will hold the loaded DataFrame.
    # For the 'processed_wave_spectrum' (which is not a direct report_type for this function),
    # this function loads the source DataFrames. The processing and specific caching
    # for the combined spectrum happens in the /api/wave_spectrum endpoint.
    df: Optional[pd.DataFrame] = None
    actual_source_path = "Data not loaded" # Initialize with a default

    cache_key = (report_type, mission_id, source_preference, custom_local_path) # Swapped order for consistency


    if not force_refresh and cache_key in data_cache:
        cached_df, cached_source_path, cache_timestamp = data_cache[cache_key]

        # Determine if the cached data is from a real-time remote source
        is_realtime_remote_source = "Remote:" in cached_source_path and "output_realtime_missions" in cached_source_path

        if is_realtime_remote_source:
            # For real-time remote sources, check expiry
            if datetime.now() - cache_timestamp < timedelta(minutes=CACHE_EXPIRY_MINUTES):
                logger.debug(f"CACHE HIT (valid - real-time): Returning {report_type} for {mission_id} from cache. Original source: {cached_source_path}")
                return cached_df, cached_source_path
            else:
                logger.debug(f"Cache hit (expired - real-time) for {report_type} ({mission_id}). Will refresh.")
        else:
            # For past remote missions and all local files, treat cache as always valid (static for app lifecycle)
            logger.debug(f"Cache hit (valid - static/local) for {report_type} ({mission_id}). Returning cached data from {cached_source_path}.")
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
                logger.debug(f"Attempting local load for {report_type} (mission: {mission_id}) from custom path: {custom_local_path}")
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
                error_msg = f"Custom local load failed for {report_type} ({mission_id}) from {custom_local_path}: {e}"
                logger.warning(error_msg + ". Trying default local.")
                # You could also raise an HTTPException here if you want to stop further attempts
                # raise HTTPException(status_code=500, detail=error_msg)
                if _attempted_custom_local and actual_source_path == "Data not loaded": # Path was attempted, but an error occurred
                    actual_source_path = _custom_local_path_str
                df = None # Ensure df is None to trigger default local load

        if df is None: # If custom path failed, wasn't provided, or yielded no usable data
            _default_local_path_str = f"Local (Default): {settings.local_data_base_path / mission_id}"
            _attempted_default_local = False
            try:
                logger.debug(f"Attempting local load for {report_type} (mission: {mission_id}) from default local path: {settings.local_data_base_path}")
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
                error_msg = f"Default local load failed for {report_type} ({mission_id}): {e}"
                logger.warning(error_msg + ".")
                # You could also raise an HTTPException here if you want to stop further attempts
                # raise HTTPException(status_code=500, detail=error_msg)
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
        remote_base_urls_to_try: List[str] = []

        # Role-based access to remote paths
        # If current_user is None (e.g. background task), assume admin-like full access for refresh
        user_role = current_user.role if current_user else models.UserRoleEnum.admin

        if user_role == models.UserRoleEnum.admin:
            remote_base_urls_to_try.extend([
                f"{base_remote_url}/output_realtime_missions",
                f"{base_remote_url}/output_past_missions"
            ])
        elif user_role == models.UserRoleEnum.pilot:
            # Pilots can only access real-time missions that are in the active_realtime_missions list
            if mission_id in settings.active_realtime_missions:
                remote_base_urls_to_try.append(f"{base_remote_url}/output_realtime_missions")
            else:
                logger.info(f"Pilot '{current_user.username if current_user else 'N/A'}' - Access to remote data for non-active mission '{mission_id}' restricted.")
        
        df = None 
        last_accessed_remote_path_if_empty = None # Track if a remote file was found but empty

        # If no remote URLs are applicable (e.g., pilot trying to access past mission), this loop won't run.
        for constructed_base_url in remote_base_urls_to_try:
            # THIS IS THE CRUCIAL PART: Ensure client is managed per-attempt
            async with httpx.AsyncClient() as current_client: # Client is created and closed for each URL in the loop
                try:
                    logger.debug(f"Attempting remote load for {report_type} (mission: {mission_id}, remote folder: {remote_mission_folder}) from base: {constructed_base_url}")
                    # Pass this specific client to loaders.load_report
                    df_attempt = await loaders.load_report(report_type, mission_id=remote_mission_folder, base_url=constructed_base_url, client=current_client)
                    if df_attempt is not None and not df_attempt.empty:
                        df = df_attempt
                        actual_source_path = f"Remote: {constructed_base_url}/{remote_mission_folder}"
                        logger.debug(f"Successfully loaded {report_type} for mission {mission_id} from {actual_source_path}")
                        break # Data found, no need to try other remote paths
                    elif df_attempt is not None: # File found and read, but resulted in an empty DataFrame
                        last_accessed_remote_path_if_empty = f"Remote: {constructed_base_url}/{remote_mission_folder}" # Mark path as "touched"
                        logger.debug(f"Remote file found but empty for {report_type} ({mission_id}) from {last_accessed_remote_path_if_empty}. Will try next path or fallback.")
                except httpx.HTTPStatusError as e_http: # Catch HTTPStatusError specifically
                    if e_http.response.status_code == 404 and "output_realtime_missions" in constructed_base_url:
                        logger.debug(f"File not found in realtime path (expected for past missions): {constructed_base_url}/{remote_mission_folder} for {report_type} ({mission_id}). Will try next path.")
                    else: # Other HTTP errors or 404s from other paths remain warnings
                        logger.warning(f"Remote load attempt from {constructed_base_url} failed for {report_type} ({mission_id}): {e_http}")
                except Exception as e_remote_attempt: # This will catch the "Cannot open a client instance more than once" if client is misused
                    logger.warning(f"General remote load attempt from {constructed_base_url} failed for {report_type} ({mission_id}): {e_remote_attempt}")

        if df is None or df.empty: # If all remote attempts failed
            if not remote_base_urls_to_try and (source_preference == 'remote' or source_preference is None):
                 logger.info(f"No remote paths were attempted for {report_type} ({mission_id}) due to role restrictions or mission status. Proceeding to local fallback if applicable.")
            else:
                logger.warning(f"No usable remote data found for {report_type} ({mission_id}). Falling back to default local.")
            # No external client to close here as it's managed internally or not passed by home route
            _local_fallback_path_str = f"Local (Default Fallback): {settings.local_data_base_path / mission_id}"
            _attempted_local_fallback = False
            try:
                logger.debug(f"Attempting fallback local load for {report_type} (mission: {mission_id}) from {settings.local_data_base_path}")
                df_fallback = await loaders.load_report(report_type, mission_id, base_path=settings.local_data_base_path)
                _attempted_local_fallback = True
                if df_fallback is not None and not df_fallback.empty:
                    df = df_fallback
                    actual_source_path = _local_fallback_path_str
                elif _attempted_local_fallback: # Local file accessed but was empty
                    actual_source_path = _local_fallback_path_str
            except FileNotFoundError:
                _msg = f"Fallback local file not found for {report_type} ({mission_id}) at {settings.local_data_base_path / mission_id}"
                logger.debug(_msg)
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

    # Additional check for pilots trying to access local data for non-active missions
    if current_user and current_user.role == models.UserRoleEnum.pilot and mission_id not in settings.active_realtime_missions:
        if "Local" in actual_source_path: # If data was loaded from local
            logger.warning(f"Pilot '{current_user.username}' loaded local data for non-active mission '{mission_id}'. This might be unintended depending on policy.")
            # To strictly deny:
            # return None, f"Access denied to local data for non-active mission '{mission_id}' (Pilot)"

    if not load_attempted: # Should not happen with current logic, but as a safeguard
         logger.error(f"No load attempt made for {report_type} ({mission_id}) with preference '{source_preference}'. This is unexpected.")

    if df is not None and not df.empty:
        logger.debug(f"CACHE STORE: Storing {report_type} for {mission_id} (from {actual_source_path}) into cache.")
        data_cache[cache_key] = (df, actual_source_path, datetime.now()) # Store with current timestamp

    return df, actual_source_path
# ---

# --- Background Cache Refresh Task ---
scheduler = AsyncIOScheduler()

async def refresh_active_mission_cache():
    logger.info("BACKGROUND TASK: Starting proactive cache refresh for active real-time missions.")
    active_missions = settings.active_realtime_missions
    # Define report types typically found in real-time missions
    # These are the *source* files to refresh. The combined spectrum is processed on demand.
    # Add wave_frequency_spectrum and wave_energy_spectrum to be refreshed by the background task
    # so the /api/wave_spectrum endpoint can use fresh source data for processing.
    realtime_report_types = ["power", "ctd", "weather", "waves", "telemetry", "ais", "errors", "vr2c", "fluorometer", "wave_frequency_spectrum", "wave_energy_spectrum"]

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
                    force_refresh=True,
                    current_user=None # Background task doesn't have a specific user context for this refresh
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


# --- Authentication Endpoint ---
@app.post("/token", response_model=models.Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    user_in_db = get_user_from_db(form_data.username)
    if not user_in_db or not verify_password(form_data.password, user_in_db.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if user_in_db.disabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Inactive user")

    logger.info(f"User '{user_in_db.username}' authenticated successfully. Issuing token.")
    access_token = create_access_token(
        data={"sub": user_in_db.username, "role": user_in_db.role.value}
    )
    return {"access_token": access_token, "token_type": "bearer"}

# --- Registration Endpoint ---
@app.post("/register", response_model=models.User)
async def register_new_user(
        user_in: models.UserCreate,
        current_admin: models.User = Depends(get_current_admin_user) # Add admin protection
    ):
    logger.info(f"Attempting to register new user: {user_in.username}")
    try:
        created_user_in_db = add_user_to_db(user_in)
        # Return User model, not UserInDB (which includes hashed_password)
        return models.User.model_validate(created_user_in_db)
    except HTTPException as e: # Catch username already exists error
        logger.warning(f"Registration failed for {user_in.username}: {e.detail}")
        raise e # Re-raise the HTTPException

@app.get("/register.html", response_class=HTMLResponse)
async def register_page(
    request: Request
    # current_user: models.User = Depends(get_current_admin_user) # REMOVE Protection for serving the HTML page
):
    # Serves the registration page
    return templates.TemplateResponse("register.html", {"request": request})

@app.get("/login.html", response_class=HTMLResponse)
async def login_page(request: Request):
    # Serves the login page
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/", response_class=HTMLResponse) # Protected route
async def home(
    request: Request,
    mission: str = "m203",
    hours: int = 72,
    source: Optional[str] = None,
    local_path: Optional[str] = None,
    refresh: bool = False,
    # The user dependency is now handled by calling get_optional_current_user(request)
    # No direct Depends() for current_user in the signature for this HTML route.
):
    # Attempt to get the current user. If no token, current_user will be None.
    # The JavaScript will handle redirecting to /login.html if no token is found.
    # For rendering the initial page, we need to determine available_missions.
    actual_current_user: Optional[models.User] = await get_optional_current_user(request)

    # `available_missions` will now be populated by the client-side JavaScript.
    available_missions_for_template = [] # Pass an empty list initially.

    # Determine if the current mission is an active real-time mission
    is_current_mission_realtime = mission in settings.active_realtime_missions
    # Client will now be managed by each load_data_source call individually
    results = await asyncio.gather(
        load_data_source("power", mission, source, local_path, refresh, actual_current_user),
        load_data_source("ctd", mission, source, local_path, refresh, actual_current_user),
        load_data_source("weather", mission, source, local_path, refresh, actual_current_user),
        load_data_source("waves", mission, source, local_path, refresh, actual_current_user),
        # Corrected order to match report_types_order for vr2c and fluorometer
        load_data_source("vr2c", mission, source, local_path, refresh, actual_current_user),
        load_data_source("solar", mission, source, local_path, refresh, actual_current_user),
        load_data_source("fluorometer", mission, source, local_path, refresh, actual_current_user),
        load_data_source("ais", mission, source, local_path, refresh, actual_current_user),
        load_data_source("errors", mission, source, local_path, refresh, actual_current_user),
        load_data_source("telemetry", mission, source, local_path, refresh, actual_current_user),
        return_exceptions=True # To handle individual load failures
    )

    # Unpack results and source paths
    data_frames: Dict[str, Optional[pd.DataFrame]] = {}
    source_paths_map: Dict[str, str] = {}
    # Ensure "error_frequency" is NOT in this list for the main page load. Add "telemetry"
    # This list is for data that populates the status cards and initial summaries.
    report_types_order = ["power", "ctd", "weather", "waves", "vr2c", "solar", "fluorometer", "ais", "errors", "telemetry"]

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
    df_telemetry = data_frames["telemetry"] # Telemetry data

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

    navigation_info = summaries.get_navigation_status(df_telemetry) # Get navigation summary
    navigation_info["mini_trend"] = summaries.get_navigation_mini_trend(df_telemetry) # Get navigation mini trend
    
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
        "available_missions": available_missions_for_template, # Pass the empty list
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
        "navigation_info": navigation_info, # Add navigation info to template context
        "current_user": actual_current_user, # Pass user info to template
    })

# --- API Endpoint for Available Missions ---
@app.get("/api/available_missions", response_model=List[str])
async def get_available_missions_for_user(
    current_user: models.User = Depends(get_current_active_user) # Protected
):
    logger.info(f"Fetching available missions for user: {current_user.username}, role: {current_user.role.value}")
    if current_user.role == models.UserRoleEnum.admin:
        return sorted(list(settings.remote_mission_folder_map.keys()))
    elif current_user.role == models.UserRoleEnum.pilot:
        return sorted(settings.active_realtime_missions)
    return [] # Should ideally not be reached if roles are enforced

# --- API Endpoint for Current User Details ---
@app.get("/api/users/me", response_model=models.User)
async def read_users_me(current_user: models.User = Depends(get_current_active_user)):
    """
    Fetch details for the currently authenticated user.
    """
    return current_user

# --- API Endpoints ---


@app.get("/api/data/{report_type}/{mission_id}")
async def get_report_data_for_plotting(
    report_type: models.ReportTypeEnum, # Use Enum for path parameter validation
    mission_id: str,
    params: models.ReportDataParams = Depends(), # Inject Pydantic model for query params
    current_user: models.User = Depends(get_current_active_user) # Protect API
):
    """
    Provides processed time-series data for a given report type,
    suitable for frontend plotting.
    """    
    # Unpack the DataFrame and the source path; we only need the DataFrame here
    df, _ = await load_data_source(
        report_type.value, mission_id, # Use .value for Enum
        source_preference=params.source.value if params.source else None, # Use .value for Enum
        custom_local_path=params.local_path,
        force_refresh=params.refresh,
        current_user=current_user
    )

    if df is None or df.empty:
        # Return empty list for charts instead of 404 to allow chart to render "no data"
        return JSONResponse(content=[]) 

    # --- Specific filtering for wave direction outliers BEFORE preprocessing/resampling ---
    if report_type.value == "waves":
        # The raw column name for wave direction is typically 'dp (deg)'
        # This is before processors.preprocess_wave_df renames it.
        raw_wave_direction_col = 'dp (deg)'
        if raw_wave_direction_col in df.columns:
            # Convert to numeric, coercing errors. This helps if it's read as object/string.
            df[raw_wave_direction_col] = pd.to_numeric(df[raw_wave_direction_col], errors='coerce')
            # Replace 9999 and -9999 with NaN so they are ignored in mean calculations
            df[raw_wave_direction_col] = df[raw_wave_direction_col].replace({9999: np.nan, -9999: np.nan})
            logger.info(f"Applied outlier filtering to '{raw_wave_direction_col}' for mission {mission_id}.")
    # --- End specific filtering ---

    # Preprocess based on report type
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
    elif report_type == "telemetry": # Telemetry data for charts
        processed_df = processors.preprocess_telemetry_df(df)

    if processed_df.empty or "Timestamp" not in processed_df.columns:
        logger.warning(f"No processable data after preprocessing for {report_type}, mission {mission_id}")
        return JSONResponse(content=[])

    # Determine the most recent timestamp in the data
    max_timestamp = processed_df["Timestamp"].max()

    if pd.isna(max_timestamp):
        logger.warning(f"No valid timestamps found in processed data for {report_type}, mission {mission_id} after preprocessing.")
        return JSONResponse(content=[])

    # Calculate the cutoff time based on the most recent data point
    cutoff_time = max_timestamp - timedelta(hours=params.hours_back)
    recent_data = processed_df[processed_df["Timestamp"] > cutoff_time]
    if recent_data.empty: # hours_back was used in cutoff_time, not directly here
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
    params: models.ForecastParams = Depends(), # Inject Pydantic model for query params
    current_user: models.User = Depends(get_current_active_user) # Protect API
):
    """
    Provides a weather forecast.
    If lat and lon are not provided, it attempts to infer them from the latest telemetry data.
    """
    final_lat, final_lon = params.lat, params.lon

    if final_lat is None or final_lon is None:
        logger.info(f"Latitude/Longitude not provided for forecast. Attempting to infer from telemetry for mission {mission_id}.")
        # Pass source preference to telemetry loading
        # Unpack the DataFrame and the source path; we only need the DataFrame here, pass refresh. No client passed.
        df_telemetry, _ = await load_data_source(
            "telemetry",
            mission_id,
            source_preference=params.source.value if params.source else None, # Use .value for Enum
            custom_local_path=params.local_path,
            force_refresh=params.refresh,
            current_user=current_user
        )

        if df_telemetry is None or df_telemetry.empty:
            logger.warning(f"Telemetry data for mission {mission_id} not found or empty. Cannot infer location.")
        else:
            # Standardize timestamp column before sorting
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

    # For the main forecast display in the Weather section, we fetch general forecast.
    # The 'force_marine' parameter is no longer directly applicable here as we're calling the general forecast.
    forecast_data = await forecast.get_general_meteo_forecast(final_lat, final_lon)
    
    if forecast_data is None:
        raise HTTPException(status_code=503, detail="Weather forecast service unavailable or failed to retrieve data.")

    return JSONResponse(content=forecast_data)

@app.get("/api/marine_forecast/{mission_id}") # New endpoint for marine-specific data
async def get_marine_weather_data(
    mission_id: str, # mission_id might be used later if lat/lon needs inference for marine
    params: models.ForecastParams = Depends(),
    current_user: models.User = Depends(get_current_active_user) # Protect API
):
    """Provides marine-specific forecast data (waves, currents)."""
    final_lat, final_lon = params.lat, params.lon

    if final_lat is None or final_lon is None:
        logger.info(f"Latitude/Longitude not provided for marine forecast. Attempting to infer from telemetry for mission {mission_id}.")
        df_telemetry, _ = await load_data_source(
            "telemetry",
            mission_id,
            source_preference=params.source.value if params.source else None,
            custom_local_path=params.local_path,
            force_refresh=params.refresh,
            current_user=current_user
        )

        if df_telemetry is None or df_telemetry.empty:
            logger.warning(f"Telemetry data for marine forecast (mission {mission_id}) not found or empty. Cannot infer location.")
        else:
            if "lastLocationFix" in df_telemetry.columns:
                df_telemetry["lastLocationFix"] = pd.to_datetime(df_telemetry["lastLocationFix"], errors="coerce")
                df_telemetry = df_telemetry.dropna(subset=["lastLocationFix"])
                if not df_telemetry.empty:
                    latest_telemetry = df_telemetry.sort_values("lastLocationFix", ascending=False).iloc[0]
                    inferred_lat = latest_telemetry.get("latitude") or latest_telemetry.get("Latitude")
                    inferred_lon = latest_telemetry.get("longitude") or latest_telemetry.get("Longitude")

                    if not pd.isna(inferred_lat) and not pd.isna(inferred_lon):
                        final_lat, final_lon = float(inferred_lat), float(inferred_lon)
                        logger.info(f"Inferred location for marine forecast (mission {mission_id}): Lat={final_lat}, Lon={final_lon}")
                    else:
                        logger.warning(f"Could not extract valid lat/lon from latest telemetry for marine forecast (mission {mission_id}).")

    if final_lat is None or final_lon is None:
        raise HTTPException(status_code=400, detail="Latitude and Longitude are required for marine forecast.")

    marine_data = await forecast.get_marine_meteo_forecast(final_lat, final_lon)
    if marine_data is None:
        raise HTTPException(status_code=503, detail="Marine forecast service unavailable or failed to retrieve data.")
    return JSONResponse(content=marine_data)

# --- NEW API Endpoint for Wave Spectrum Data ---
@app.get("/api/wave_spectrum/{mission_id}")
async def get_wave_spectrum_data(
    mission_id: str,
    timestamp: Optional[datetime] = None, # Optional specific timestamp for the spectrum
    params: models.ForecastParams = Depends(), # Reusing ForecastParams for source, local_path, refresh
    current_user: models.User = Depends(get_current_active_user) # Protect API
):
    """
    Provides the latest wave energy spectrum data (Frequency vs. Energy Density).
    Optionally provides the spectrum closest to a given timestamp.
    """
    # Define a unique cache key for the *processed* spectrum data
    spectrum_cache_key = ('processed_wave_spectrum', mission_id, params.source.value if params.source else None, params.local_path)

    spectral_records = None
    # Check cache first for the processed spectrum list
    if not params.refresh and spectrum_cache_key in data_cache:
        # data_cache stores (data, path, timestamp). Here 'data' is the list of spectral_records.
        cached_spectral_records, cached_source_path_info, cache_timestamp = data_cache[spectrum_cache_key]
        
        is_realtime_source = "Remote:" in cached_source_path_info and "output_realtime_missions" in cached_source_path_info
        
        if is_realtime_source and (datetime.now() - cache_timestamp < timedelta(minutes=CACHE_EXPIRY_MINUTES)):
            logger.info(f"CACHE HIT (valid - real-time processed spectrum): Returning wave spectrum for {mission_id} from cache. Derived from: {cached_source_path_info}")
            spectral_records = cached_spectral_records
        elif not is_realtime_source and cached_spectral_records: # Static source, cache is good if data exists
            logger.info(f"CACHE HIT (valid - static processed spectrum): Returning wave spectrum for {mission_id} from cache. Derived from: {cached_source_path_info}")
            spectral_records = cached_spectral_records
        else: # Expired real-time or empty static cache
            logger.info(f"Cache for processed spectrum for {mission_id} is expired or invalid. Will re-load and process.")

    if spectral_records is None: # Cache miss or expired/forced refresh for processed data
        logger.info(f"CACHE MISS (processed spectrum) or refresh for {mission_id}. Loading and processing source files.")
        df_freq, path_freq = await load_data_source("wave_frequency_spectrum", mission_id, params.source.value if params.source else None, params.local_path, params.refresh, current_user)
        df_energy, path_energy = await load_data_source("wave_energy_spectrum", mission_id, params.source.value if params.source else None, params.local_path, params.refresh, current_user)

        spectral_records = processors.preprocess_wave_spectrum_dfs(df_freq, df_energy)
        if spectral_records: # Only cache if processing was successful and yielded data
            data_cache[spectrum_cache_key] = (spectral_records, f"Combined from {path_freq} and {path_energy}", datetime.now())

    if not spectral_records:
        logger.warning(f"No wave spectral records found or processed for mission {mission_id}.")
        return JSONResponse(content={}) # Return empty object

    # Select the target spectrum (latest or closest to timestamp)
    target_spectrum = utils.select_target_spectrum(spectral_records, timestamp) # Assuming utils.select_target_spectrum handles this logic

    if not target_spectrum or 'freq' not in target_spectrum or 'efth' not in target_spectrum:
        logger.warning(f"Selected target spectrum for mission {mission_id} is invalid or missing data.")
        return JSONResponse(content={})

    spectrum_data = [{"x": f, "y": e} for f, e in zip(target_spectrum.get('freq', []), target_spectrum.get('efth', [])) if pd.notna(f) and pd.notna(e)]
    return JSONResponse(content=spectrum_data)