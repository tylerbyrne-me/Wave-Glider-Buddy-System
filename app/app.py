import asyncio
import json  # For saving/loading forms to/from JSON
import calendar # For month range calculation
import shutil
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# --- Configure Logging ---
logging.basicConfig(level=logging.INFO, format='%(levelname)-5.5s [%(name)s] %(message)s')

from typing import Annotated, Dict, List, Optional, Tuple 

import httpx  # For async client in load_data_source
import numpy as np  # For numeric operations if needed
import pandas as pd  # For DataFrame operations # type: ignore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import (  # Added status
    BackgroundTasks,
    Depends, UploadFile, File,
    FastAPI, Form,
    HTTPException, Response,
    Query, # Import Query
    Request, Body,
    status, 
)
from pydantic import BaseModel
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, RedirectResponse  # type: ignore
from fastapi_mail import ConnectionConfig, FastMail, MessageSchema
from fastapi.security import OAuth2PasswordRequestForm  # type: ignore
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import (  # type: ignore
    SQLModel,
    inspect,
    select, func, case,
    delete, # Add this import for deletion operations
)
from sqlmodel import Field, Relationship # Add for new models

import csv  # For CSV generation
import io  # For CSV and ICS generation
import ics  # For ICS file generation

from . import auth_utils  # Import the auth_utils module itself for its functions
# Specific user-related functions will be called via auth_utils.func_name(session, ...)
from .auth_utils import (get_current_active_user, get_current_admin_user,
                         get_optional_current_user)
from .config import settings
from .core import models  # type: ignore
from .core import (forecast, loaders, processors, summaries, utils, feature_toggles, template_context) # type: ignore
from . import reporting
from .core.security import create_access_token, verify_password
from .db import SQLModelSession, get_db_session, sqlite_engine
from .forms.form_definitions import get_static_form_schema # Import the new function
from .routers import station_metadata_router, auth as auth_router  # Import auth_router
from .routers import schedule as schedule_router
from .routers import forms as forms_router
from .routers import announcements as announcements_router
from .routers import missions as missions_router
from .routers import payroll as payroll_router
from .routers import home as home_router
from .routers import reporting as reporting_router
from .routers import admin as admin_router
from .routers import error_analysis as error_analysis_router

# --- Conditional import for fcntl ---
IS_UNIX = True
try:
    import fcntl
except ImportError:
    IS_UNIX = False
    fcntl = None  # type: ignore # Make fcntl None on non-Unix systems

# --- New Models (Ideally in app/core/models.py) ---


# --- Mission Info Models (Imported from models.py) ---
# These are just for reference, the actual definitions are in app/core/models.py
# We will import them below.
# class MissionOverview(SQLModel, table=True): ...
# class MissionGoal(SQLModel, table=True): ...
# class MissionNote(SQLModel, table=True): ...
#
# class MissionOverviewUpdate(BaseModel): ...
# class MissionGoalCreate(BaseModel): ...
# class MissionGoalUpdate(BaseModel): ...
# class MissionNoteCreate(BaseModel): ...
# class MissionInfoResponse(BaseModel): ...

# --- Home Page Panel Models ---
# (UpcomingShift, MyTimesheetStatus, and MissionGoalToggle have been moved to app/core/models.py)





# --- End New Models ---

app = FastAPI()

# --- Email Configuration ---
conf = ConnectionConfig(
    MAIL_USERNAME=settings.MAIL_USERNAME,
    MAIL_PASSWORD=settings.MAIL_PASSWORD,
    MAIL_FROM=settings.MAIL_FROM,
    MAIL_PORT=settings.MAIL_PORT,
    MAIL_SERVER=settings.MAIL_SERVER,
    MAIL_STARTTLS=settings.MAIL_STARTTLS,
    MAIL_SSL_TLS=settings.MAIL_SSL_TLS,
    USE_CREDENTIALS=True,
    TEMPLATE_FOLDER=Path(__file__).resolve().parent.parent / "web" / "templates" / "email"
)



# --- Robust path to templates directory ---
# Get the directory of the current file (app.py)
APP_DIR = Path(__file__).resolve().parent
# Go up one level to the project root
PROJECT_ROOT = APP_DIR.parent
# Construct the path to the templates directory
TEMPLATES_DIR = PROJECT_ROOT / "web" / "templates"
from app.core.templates import templates

# --- Define path for local form storage (for testing) ---
DATA_STORE_DIR = PROJECT_ROOT / "data_store"
LOCAL_FORMS_DB_FILE = DATA_STORE_DIR / "submitted_forms.json"

# Include the station_metadata_router.
app.include_router(
    station_metadata_router.router, prefix="/api", tags=["Station Metadata"]
)
# print("DEBUG_PRINT: app.py - station_metadata_router included with prefix /api") # Can be removed

app.mount(
    "/static",
    StaticFiles(directory=str(PROJECT_ROOT / "web" / "static")),
    name="static",
)
app.include_router(
    auth_router.router
)
app.include_router(schedule_router.router)
app.include_router(forms_router.router)
app.include_router(announcements_router.router)
app.include_router(missions_router.router)
app.include_router(payroll_router.router)
app.include_router(home_router.router)
app.include_router(reporting_router.router)
app.include_router(admin_router.router)
app.include_router(error_analysis_router.router)

logger = logging.getLogger(__name__)
logger.info("--- FastAPI application module loaded. This should appear on every server start/reload. ---")

# --- Import template context helper ---
from .core.template_context import get_template_context

# ---

from cachetools import LRUCache

# In-memory cache: key -> (data, actual_source_path_str, cache_timestamp).
# 'data' is typically pd.DataFrame, but for 'processed_wave_spectrum'
# it's List[Dict].
# The type hint for data_cache needs to be more generic or use Union.
# Using LRUCache: key -> (data, actual_source_path_str, cache_timestamp).
data_cache: LRUCache[Tuple, Tuple[pd.DataFrame, str, datetime]] = LRUCache(maxsize=256) # e.g., cache up to 256 items

# CACHE_EXPIRY_MINUTES is now used by the background task interval and for
# individual cache item expiry
# if it's a real-time source and the background task hasn't run yet.
CACHE_EXPIRY_MINUTES = settings.background_cache_refresh_interval_minutes

# In-memory store for submitted forms. This will be populated from a local JSON file on startup.
# Key: (mission_id, form_type, submission_timestamp_iso) -> MissionFormDataResponse
mission_forms_db: Dict[Tuple[str, str, str], models.MissionFormDataResponse] = {}





def create_db_and_tables():
    """
    Creates database tables based on SQLModel definitions if they don't exist.
    """
    logger.info("Creating database and tables if they don't exist...")
    SQLModel.metadata.create_all(sqlite_engine)  # Uses sqlite_engine from db.py
    logger.info("Database and tables checked/created.")

# ---
def _initialize_database_and_users():
    """Helper function to contain the DB creation and default user logic."""
    if settings.forms_storage_mode == "sqlite":  # Also implies user data is in SQLite
        create_db_and_tables()

    with SQLModelSession(sqlite_engine) as session:
        inspector = inspect(sqlite_engine)
        if inspector.has_table(models.UserInDB.__tablename__):  # type: ignore
            # The original logic only created default users if the table was completely empty.
            # This new logic checks for each default user individually, making it robust
            # to adding new default users later.
            
            # Use a local index for default user colors to ensure they get specific ones
            # from the USER_COLORS palette in auth_utils.
            default_user_color_idx = 0
            default_users_data = [
                {
                    "username": "adminuser",
                    "full_name": "Admin User",
                    "email": "admin@example.com",
                    "password": "adminpass",
                    "role": models.UserRoleEnum.admin,
                    "color": auth_utils.USER_COLORS[default_user_color_idx % len(auth_utils.USER_COLORS)],
                    "disabled": False,
                },
                {
                    "username": "pilotuser",
                    "full_name": "Pilot User",
                    "email": "pilot@example.com",
                    "password": "pilotpass",
                    "role": models.UserRoleEnum.pilot,
                    "color": auth_utils.USER_COLORS[(default_user_color_idx + 1) % len(auth_utils.USER_COLORS)],
                    "disabled": False,
                },
                {
                    "username": "pilot_rt_only",
                    "full_name": "Realtime Pilot",
                    "email": "pilot_rt@example.com",
                    "password": "pilotrtpass",
                    "role": models.UserRoleEnum.pilot,
                    "color": auth_utils.USER_COLORS[(default_user_color_idx + 2) % len(auth_utils.USER_COLORS)],
                    "disabled": False,
                },
                {
                    "username": "LRI_PILOT", # Special user for LRI-blocked shifts
                    "full_name": "LRI Piloting Block",
                    "email": "lri@example.com",
                    "password": "lripass", # Password doesn't matter as user is disabled
                    "role": models.UserRoleEnum.pilot, # Can be pilot or a new 'lri' role if needed
                    "color": "#ADD8E6", # Light Blue for LRI blocks
                    "disabled": True, # LRI_PILOT cannot log in
                },
            ]

            # Check for each default user and create if missing
            for user_data_dict in default_users_data:
                existing_user = auth_utils.get_user_from_db(session, user_data_dict["username"])
                if not existing_user:
                    logger.info(f"Default user '{user_data_dict['username']}' not found. Creating...")
                    user_create_model = models.UserCreate(**user_data_dict)
                    auth_utils.add_user_to_db(session, user_create_model)
                else:
                    logger.info(f"Default user '{user_data_dict['username']}' already exists. Skipping.")

            # Reset the color index based on all users, to avoid re-assigning colors on restart
            all_users_statement = select(models.UserInDB)
            all_users_in_db = session.exec(all_users_statement).all()
            auth_utils.next_color_index = len(all_users_in_db)
            logger.info(f"Color index reset to {auth_utils.next_color_index} based on {len(all_users_in_db)} total users.")
        else:
            logger.error(
                f"'{models.UserInDB.__tablename__}' table still does not exist "
                "after create_db_and_tables(). DB init failed."
            )

async def _load_from_local_sources(
    report_type: str, mission_id: str, custom_local_path: Optional[str]
) -> Tuple[Optional[pd.DataFrame], str]:
    """Helper to attempt loading data from local sources (custom then default)."""
    df = None
    actual_source_path = "Data not loaded"
    _attempted_custom_local = False

    if custom_local_path:
        _custom_local_path_str = f"Local (Custom): {Path(custom_local_path) / mission_id}"
        try:
            logger.debug(
                f"Attempting local load for {report_type} (mission: {mission_id}) from custom path: {custom_local_path}"
            )
            df_attempt = await loaders.load_report(report_type, mission_id, base_path=Path(custom_local_path))
            _attempted_custom_local = True
            if df_attempt is not None and not df_attempt.empty:
                return df_attempt, _custom_local_path_str
            elif _attempted_custom_local: # File accessed but empty
                actual_source_path = _custom_local_path_str # Record that this path was tried
        except FileNotFoundError:
            logger.warning(f"Custom local file for {report_type} ({mission_id}) not found at {custom_local_path}. Trying default local.")
        except (IOError, pd.errors.ParserError, pd.errors.EmptyDataError) as e_file_data:
            logger.warning(f"Custom local data load/parse error for {report_type} ({mission_id}) from {custom_local_path}: {e_file_data}. Trying default local.")
            if _attempted_custom_local: # Path was attempted, but an error occurred
                actual_source_path = _custom_local_path_str
        except Exception as e_general: # Catch any other unexpected errors
            logger.error(f"Unexpected error during custom local load for {report_type} ({mission_id}) from {custom_local_path}: {e_general}. Trying default local.", exc_info=True)
            if _attempted_custom_local: # Path was attempted, but an error occurred
                actual_source_path = _custom_local_path_str

    # Try default local if custom failed, wasn't provided, or yielded no usable data
    if df is None:
        _default_local_path_str = f"Local (Default): {settings.local_data_base_path / mission_id}"
        _attempted_default_local = False
        try:
            logger.debug(
                f"Attempting local load for {report_type} (mission: {mission_id}) from default path: {settings.local_data_base_path}"
            )
            df_attempt = await loaders.load_report(report_type, mission_id, base_path=settings.local_data_base_path)
            _attempted_default_local = True
            if df_attempt is not None and not df_attempt.empty:
                return df_attempt, _default_local_path_str
            elif _attempted_default_local and actual_source_path == "Data not loaded": # Default local accessed but empty, and custom wasn't successful
                actual_source_path = _default_local_path_str
        except FileNotFoundError:
            logger.warning(f"Default local file for {report_type} ({mission_id}) not found at {settings.local_data_base_path}.")
            if actual_source_path == "Data not loaded": # If custom also failed with FNF or wasn't tried
                actual_source_path = f"Local (Default): File Not Found - {settings.local_data_base_path / mission_id}"
        except (IOError, pd.errors.ParserError, pd.errors.EmptyDataError) as e_file_data:
            logger.warning(f"Default local data load/parse error for {report_type} ({mission_id}): {e_file_data}.")
            if _attempted_default_local and actual_source_path == "Data not loaded":
                actual_source_path = _default_local_path_str
        except Exception as e_general: # Catch any other unexpected errors
            logger.error(f"Unexpected error during default local load for {report_type} ({mission_id}): {e_general}.", exc_info=True)
            if _attempted_default_local and actual_source_path == "Data not loaded":
                actual_source_path = _default_local_path_str

    return None, actual_source_path


async def _load_from_remote_sources(
    report_type: str, mission_id: str, current_user: Optional[models.User]
) -> Tuple[Optional[pd.DataFrame], str]:
    """Helper to attempt loading data from remote sources based on user role."""
    actual_source_path = "Data not loaded"
    remote_mission_folder = settings.remote_mission_folder_map.get(mission_id, mission_id)
    base_remote_url = settings.remote_data_url.rstrip("/")
    remote_base_urls_to_try: List[str] = []
    user_role = current_user.role if current_user else models.UserRoleEnum.admin

    if user_role == models.UserRoleEnum.admin:
        remote_base_urls_to_try.extend([
            f"{base_remote_url}/output_realtime_missions",
            f"{base_remote_url}/output_past_missions",
        ])
    elif user_role == models.UserRoleEnum.pilot:
        if mission_id in settings.active_realtime_missions:
            remote_base_urls_to_try.append(f"{base_remote_url}/output_realtime_missions")
        else:
            logger.info(f"Pilot '{current_user.username if current_user else 'N/A'}' - Access to remote data for non-active mission '{mission_id}' restricted.")
            return None, "Remote: Access Restricted"

    last_accessed_remote_path_if_empty = None
    for constructed_base_url in remote_base_urls_to_try:
        # Configure client with retries, using RETRY_COUNT from loaders for consistency
        retry_transport = httpx.AsyncHTTPTransport(retries=loaders.RETRY_COUNT)
        async with httpx.AsyncClient(transport=retry_transport) as client: # Manage client per attempt
            try:
                logger.debug(f"Attempting remote load for {report_type} (mission: {mission_id}, remote folder: {remote_mission_folder}) from base: {constructed_base_url}")
                df_attempt = await loaders.load_report(report_type, mission_id=remote_mission_folder, base_url=constructed_base_url, client=client)
                if df_attempt is not None and not df_attempt.empty:
                    actual_source_path = f"Remote: {constructed_base_url}/{remote_mission_folder}"
                    logger.debug(f"Successfully loaded {report_type} for mission {mission_id} from {actual_source_path}")
                    return df_attempt, actual_source_path
                elif df_attempt is not None: # Found but empty
                    last_accessed_remote_path_if_empty = f"Remote: {constructed_base_url}/{remote_mission_folder}"
                    logger.debug(f"Remote file found but empty for {report_type} ({mission_id}) from {last_accessed_remote_path_if_empty}. Will try next.")
            except httpx.HTTPStatusError as e_http:
                if e_http.response.status_code == 404 and "output_realtime_missions" in constructed_base_url:
                    logger.debug(f"File not found in realtime path: {constructed_base_url}/{remote_mission_folder}. Will try next.")
                else:
                    logger.warning(f"Remote load attempt from {constructed_base_url} failed: {e_http}")
            except (httpx.RequestError, pd.errors.ParserError, pd.errors.EmptyDataError) as e_req_parse:
                # Catches network errors, timeouts not covered by HTTPStatusError, and pandas parsing issues
                logger.warning(f"Request or parse error during remote load from {constructed_base_url} for {report_type} ({mission_id}): {e_req_parse}")
            except Exception as e_general_remote: # Catch any other unexpected errors
                logger.error(f"Unexpected general error during remote load from {constructed_base_url} for {report_type} ({mission_id}): {e_general_remote}", exc_info=True)
    
    if last_accessed_remote_path_if_empty: # All attempts failed, but one remote file was found empty
        return None, last_accessed_remote_path_if_empty
    return None, actual_source_path

def _apply_date_filtering(df: pd.DataFrame, report_type: str, start_date: datetime, end_date: datetime) -> pd.DataFrame:
    """
    Apply date filtering to a DataFrame based on the report type and timestamp column.
    Returns the filtered DataFrame.
    """
    # Map report types to their timestamp column names
    timestamp_columns = {
        "telemetry": "lastLocationFix",
        "power": "gliderTimeStamp", 
        "solar": "gliderTimeStamp",
        "ctd": "gliderTimeStamp",
        "weather": "gliderTimeStamp",
        "waves": "gliderTimeStamp",
        "vr2c": "gliderTimeStamp",
        "fluorometer": "gliderTimeStamp",
        "wg_vm4": "gliderTimeStamp",
        "ais": "gliderTimeStamp",
        "errors": "gliderTimeStamp",
    }
    
    timestamp_col = timestamp_columns.get(report_type)
    if not timestamp_col or timestamp_col not in df.columns:
        logger.warning(f"No timestamp column found for {report_type}, skipping date filtering")
        return df
    
    try:
        # Convert timestamp column to datetime if it's not already
        if not pd.api.types.is_datetime64_any_dtype(df[timestamp_col]):
            df[timestamp_col] = pd.to_datetime(df[timestamp_col], format='ISO8601', utc=True)
        
        # Ensure timezone awareness
        if start_date.tzinfo is None:
            start_date = start_date.replace(tzinfo=timezone.utc)
        if end_date.tzinfo is None:
            end_date = end_date.replace(tzinfo=timezone.utc)
        
        # Apply date filtering
        mask = (df[timestamp_col] >= start_date) & (df[timestamp_col] <= end_date)
        filtered_df = df[mask].copy()
        
        logger.info(f"Date filtering applied to {report_type}: {len(df)} -> {len(filtered_df)} records "
                   f"({start_date.isoformat()} to {end_date.isoformat()})")
        
        return filtered_df
        
    except Exception as e:
        logger.error(f"Error applying date filtering to {report_type}: {e}")
        return df


async def load_data_source(
    report_type: str,
    mission_id: str,
    source_preference: Optional[str] = None,  # 'local' or 'remote'
    custom_local_path: Optional[str] = None,
    force_refresh: bool = False,  # New parameter to bypass cache
    current_user: Optional[
        models.User  # Changed from UserInDB to match what get_optional_current_user returns
    ] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
):

    df: Optional[pd.DataFrame] = None
    actual_source_path = "Data not loaded"  # Initialize with a default

    cache_key = (
        report_type,
        mission_id,
        source_preference,
        custom_local_path,
    )  # Swapped order for consistency

    if not force_refresh and cache_key in data_cache:
        cached_df, cached_source_path, cache_timestamp = data_cache[cache_key]

        # Determine if the cached data is from a real-time remote source
        is_realtime_remote_source = (
            "Remote:" in cached_source_path
            and "output_realtime_missions" in cached_source_path
        )

        if is_realtime_remote_source:
            # For real-time remote sources, check expiry
            if datetime.now() - cache_timestamp < timedelta(
                minutes=CACHE_EXPIRY_MINUTES
            ):
                logger.debug(
                    f"CACHE HIT (valid - real-time): Returning {report_type} "
                    f"for {mission_id} from cache. "
                    f"Original source: {cached_source_path}"
                )
                return cached_df, cached_source_path
            else:
                logger.debug(
                    f"Cache hit (expired - real-time) for {report_type} "
                    f"({mission_id}). Will refresh."
                )
        else:
            # For past remote missions and all local files, treat cache as
            # always valid (static for app lifecycle)
            logger.debug(
                f"Cache hit (valid - static/local) for {report_type} "
                f"({mission_id}). Returning cached data from {cached_source_path}."
            )
            return cached_df, cached_source_path
    elif force_refresh:
        logger.info(
            f"Force refresh requested for {report_type} ({mission_id}). Bypassing cache."
        )

    load_attempted = False
    if source_preference == "local":  # Local-only preference
        load_attempted = True
        df, actual_source_path = await _load_from_local_sources(report_type, mission_id, custom_local_path)

    # Remote-first or default behavior (remote then local fallback)
    elif source_preference == "remote" or source_preference is None:
        load_attempted = True
        df, actual_source_path = await _load_from_remote_sources(report_type, mission_id, current_user)
        if df is None: # If remote failed, try local as fallback
            logger.warning(f"Remote preference/attempt failed for {report_type} ({mission_id}). Falling back to default local.")
            # Pass None for custom_local_path to ensure only default is tried as fallback
            df_fallback, path_fallback = await _load_from_local_sources(report_type, mission_id, None)
            if df_fallback is not None:
                df, actual_source_path = df_fallback, path_fallback
            # If actual_source_path from remote attempt was informative (e.g. "Access Restricted" or "File Not Found"), keep it.
            # Otherwise, if local fallback also failed, path_fallback will be more specific.
            elif "Data not loaded" in actual_source_path or "Access Restricted" in actual_source_path or "Remote: File Not Found" in actual_source_path :
                 if path_fallback and "Data not loaded" not in path_fallback : actual_source_path = path_fallback

    # Additional check for pilots trying to access local data for non-active missions
    if (
        current_user
        and current_user.role == models.UserRoleEnum.pilot
        and mission_id not in settings.active_realtime_missions
    ):
        if "Local" in actual_source_path:  # If data was loaded from local
            logger.warning(
                f"Pilot '{current_user.username}' loaded local data for "
                f"non-active mission '{mission_id}'. This might be unintended."
            )
            # To strictly deny:
            # return None, (f"Access denied to local data for non-active "
            #               f"mission '{mission_id}' (Pilot)")

    if not load_attempted:  # Should not happen with current logic, but as a safeguard
        logger.error(
            f"No load attempt for {report_type} ({mission_id}) with pref '{source_preference}'. Unexpected."
        )

    # Note: Date filtering is now handled in the API endpoint after preprocessing
    # to ensure we filter on the correct timestamp column after data transformation

    if df is not None and not df.empty:
        logger.debug(
            f"CACHE STORE: Storing {report_type} for {mission_id} (from {actual_source_path}) into cache."
        )
        data_cache[cache_key] = (
            df,
            actual_source_path,
            datetime.now(),
        )  # Store with current timestamp

    # Ensure df is returned even if it's None, along with actual_source_path
    return df if df is not None else pd.DataFrame(), actual_source_path


# ---

# --- Background Cache Refresh Task (APScheduler instantiation temporarily commented out) ---
scheduler = AsyncIOScheduler()  # Uncomment APScheduler


async def refresh_active_mission_cache():
    logger.info(
        "BACKGROUND TASK: Starting proactive cache refresh for active "
        "real-time missions."
    )
    active_missions = settings.active_realtime_missions
    # Define report types typically found in real-time missions
    # These are the *source* files to refresh. The combined spectrum is
    # processed on demand.
    # Add wave_frequency_spectrum and wave_energy_spectrum to be refreshed by
    # the background task
    # so the /api/wave_spectrum endpoint can use fresh source data for processing.
    # Get database session for checking sensor card configurations
    from .db import SQLModelSession, sqlite_engine
    with SQLModelSession(sqlite_engine) as session:
        for mission_id in active_missions:
            logger.info(
                f"BACKGROUND TASK: Refreshing cache for active mission: {mission_id}"
            )
            
            # Get enabled sensor cards for this mission
            mission_overview = session.get(models.MissionOverview, mission_id)
            enabled_sensor_cards = []
            if mission_overview and mission_overview.enabled_sensor_cards:
                try:
                    enabled_sensor_cards = json.loads(mission_overview.enabled_sensor_cards)
                except json.JSONDecodeError:
                    # Default to all sensors if parsing fails
                    enabled_sensor_cards = ["navigation", "power", "ctd", "weather", "waves", "vr2c", "fluorometer", "wg_vm4", "ais", "errors"]
            else:
                # Default to all sensors if no configuration exists
                enabled_sensor_cards = ["navigation", "power", "ctd", "weather", "waves", "vr2c", "fluorometer", "wg_vm4", "ais", "errors"]
            
            # Map sensor card categories to their corresponding data report types
            sensor_to_report_mapping = {
                "navigation": "telemetry",  # Navigation card uses telemetry data
                "power": "power",
                "ctd": "ctd", 
                "weather": "weather",
                "waves": "waves",
                "vr2c": "vr2c",
                "fluorometer": "fluorometer",
                "wg_vm4": "wg_vm4",
                "ais": "ais",
                "errors": "errors"
            }
            
            # Determine which report types to refresh based on enabled sensor cards
            report_types_to_refresh = []
            for sensor_card in enabled_sensor_cards:
                if sensor_card in sensor_to_report_mapping:
                    report_types_to_refresh.append(sensor_to_report_mapping[sensor_card])
                    # Add solar data if power is enabled
                    if sensor_card == "power" and "solar" not in report_types_to_refresh:
                        report_types_to_refresh.append("solar")
            
            # Always include wave spectrum data if waves is enabled (used for wave analysis)
            if "waves" in enabled_sensor_cards:
                if "wave_frequency_spectrum" not in report_types_to_refresh:
                    report_types_to_refresh.append("wave_frequency_spectrum")
                if "wave_energy_spectrum" not in report_types_to_refresh:
                    report_types_to_refresh.append("wave_energy_spectrum")
            
            logger.info(
                f"BACKGROUND TASK: Refreshing {len(report_types_to_refresh)} data types for mission {mission_id}: {report_types_to_refresh}"
            )
            
            for report_type in report_types_to_refresh:
                try:
                    # We force refresh and specify 'remote' as source_preference
                    # because we are targeting 'output_realtime_missions'
                    await load_data_source(
                        report_type,
                        mission_id,
                        source_preference="remote",  # Ensure it tries remote (specifically output_realtime_missions first)
                        force_refresh=True, # Background task doesn't have a specific user context for this refresh
                        current_user=None,
                    )
                except Exception as e:
                    logger.error(
                        f"BACKGROUND TASK: Error refreshing cache for {report_type} "
                        f"on mission {mission_id}: {e}"
                    )
    
    logger.info(
        "BACKGROUND TASK: Proactive cache refresh for active real-time "
        "missions completed."
    )


# --- Automated Weekly Report Generation Task ---
async def run_weekly_reports_job():
    """Scheduled job to generate a standard weekly report for all active missions."""
    logger.info("AUTOMATED: Kicking off weekly report generation for all active missions.")
    with SQLModelSession(sqlite_engine) as session:
        active_missions = settings.active_realtime_missions
        if not active_missions:
            logger.info("AUTOMATED: No active missions configured. Skipping weekly report generation.")
            return

        for mission_id in active_missions:
            # The helper function is async and handles its own exceptions/logging
            await reporting.create_and_save_weekly_report(mission_id, session)

    logger.info("AUTOMATED: Weekly report generation job finished.")


# --- FastAPI Lifecycle Events for Scheduler ---
@app.on_event("startup")  # Uncomment the startup event
async def startup_event():
    logger.info("Application startup event initiated.")  # Changed from print
    # Create directory for mission plan uploads if it doesn't exist
    MISSION_PLANS_DIR = PROJECT_ROOT / "web" / "static" / "mission_plans"
    MISSION_PLANS_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(f"Mission plans directory checked/created at: {MISSION_PLANS_DIR}")

    scheduler.add_job(
        refresh_active_mission_cache,
        "interval",
        minutes=settings.background_cache_refresh_interval_minutes,
        id="active_mission_refresh_job",
    )
    scheduler.add_job(
        run_weekly_reports_job,
        'cron',
        day_of_week='thu',
        hour=12,
        minute=0,
        timezone='UTC',
        id='weekly_report_job'
    )
    scheduler.start()
    logger.info("APScheduler started for background cache refresh.")
    # Trigger an initial refresh shortly after startup

    # --- Database Initialization with File Lock ---
    # Restore DB initialization and form loading
    lock_file_path = DATA_STORE_DIR / ".db_init.lock"
    try:
        if IS_UNIX and fcntl:  # Only attempt fcntl lock on Unix-like systems
            with open(lock_file_path, "w") as lock_file:
                try:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    logger.info(
                        "Acquired DB initialization lock. This worker will "
                        "initialize the DB."
                    )
                    _initialize_database_and_users()
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                    logger.info(
                        "DB initialization complete. Lock released by this worker."
                    )
                except BlockingIOError:
                    logger.info(
                        "Could not acquire DB initialization lock. Another "
                        "worker is likely initializing."
                    )
                    await asyncio.sleep(5)
                    inspector = inspect(sqlite_engine)
                    if not inspector.has_table(models.UserInDB.__tablename__):
                        logger.warning(
                            "DB tables still not found after waiting for other worker."
                        )
                    else:
                        logger.info(
                            "DB tables found. Assuming another worker "
                            "completed initialization."
                        )
                except Exception as e_lock_init:
                    logger.error(
                        f"Error during locked DB initialization: {e_lock_init}",
                        exc_info=True,
                    )
                    try:
                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                    except Exception:
                        pass
        else:
            logger.info(
                "Non-Unix system or fcntl not available. Proceeding with "
                "DB initialization without file lock."
            )
            _initialize_database_and_users()
    except Exception as e_open_lock:
        logger.error(
            f"Could not open or manage lock file {lock_file_path}: {e_open_lock}",
            exc_info=True,
        )
        logger.warning(
            "Proceeding with DB initialization without file lock due to "
            "error managing lock file."
        )
        _initialize_database_and_users()

    asyncio.create_task(refresh_active_mission_cache())  # Restore cache refresh

    global mission_forms_db  # Restore form loading
    if settings.forms_storage_mode == "local_json":
        if LOCAL_FORMS_DB_FILE.exists():
            try:
                with open(LOCAL_FORMS_DB_FILE, "r") as f:
                    loaded_db_serializable = json.load(f)
                    mission_forms_db = {
                        tuple(json.loads(k)): models.MissionFormDataResponse(**v)
                        for k, v in loaded_db_serializable.items()
                    }
                logger.info(
                    f"Forms database loaded from {LOCAL_FORMS_DB_FILE}. "
                    f"{len(mission_forms_db)} forms loaded."
                )
            except (IOError, json.JSONDecodeError, TypeError) as e:
                logger.error(
                    f"Error loading forms from {LOCAL_FORMS_DB_FILE}: {e}. "
                    "Starting with an empty forms DB."
                )
                mission_forms_db = {}
    elif settings.forms_storage_mode == "sqlite":
        logger.info("Forms storage mode is 'sqlite'. JSON load skipped.")
    logger.info("Application startup event completed.")  


@app.on_event("shutdown") 
def shutdown_event():
    if (
        "scheduler" in globals() and scheduler.running
    ):  # Check if scheduler was initialized and started
        scheduler.shutdown()
    logger.info("APScheduler shut down.")


async def _process_loaded_data_for_home_view(
    results: list, report_types_order: list, hours: int, mission_id: str # Added mission_id
) -> dict:
    """
    Processes the loaded data results, calculates summaries, and determines
    the display source path for the home view.
    """
    data_frames: Dict[str, Optional[pd.DataFrame]] = {}
    source_paths_map: Dict[str, str] = {}

    for i, report_type in enumerate(report_types_order):
        if isinstance(results[i], Exception):
            data_frames[report_type] = None # Ensure it's None, not an empty DataFrame yet
            source_paths_map[report_type] = "Error during load"
            logger.error(
                f"Exception loading {report_type} for mission {mission_id}: {results[i]}"
            )
        else:
            # Ensure results[i] is a tuple of (DataFrame, str)
            if isinstance(results[i], tuple) and len(results[i]) == 2:
                df_loaded, path_loaded = results[i]
                data_frames[report_type] = df_loaded if df_loaded is not None and not df_loaded.empty else None
                source_paths_map[report_type] = path_loaded
            else: # Should not happen if load_data_source is consistent
                data_frames[report_type] = None
                source_paths_map[report_type] = "Unexpected load result format"
                logger.error(f"Unexpected load result format for {report_type} (mission {mission_id}): {results[i]}")


    # Determine the primary display_source_path
    display_source_path = "Information unavailable or all loads failed"
    found_primary_path_for_display = False
    priority_paths_checks = [
        (lambda p: "Remote:" in p and "output_realtime_missions" in p and "Data not loaded" not in p and "Error during load" not in p),
        (lambda p: "Remote:" in p and "output_past_missions" in p and "Data not loaded" not in p and "Error during load" not in p),
        (lambda p: "Local (Custom):" in p and "Data not loaded" not in p and "Error during load" not in p),
        (lambda p: p.startswith("Local (Default") and "Data not loaded" not in p and "Error during load" not in p),
        (lambda p: "File Not Found" in p), # Handle file not found as a specific case
        (lambda p: "Access Restricted" in p) # Handle access restricted
    ]

    for check_priority in priority_paths_checks:
        for report_type in report_types_order:
            path_info = source_paths_map.get(report_type, "")
            if check_priority(path_info):
                display_source_path = path_info # Pass the full, descriptive path info
                found_primary_path_for_display = True
                break
        if found_primary_path_for_display:
            break

    # Calculate summaries only for data that was actually loaded
    # Initialize all sensor info with default empty values
    power_info = {"values": {}, "time_ago_str": "N/A", "latest_timestamp_str": "N/A", "mini_trend": []}
    ctd_info = {"values": {}, "time_ago_str": "N/A", "latest_timestamp_str": "N/A", "mini_trend": []}
    weather_info = {"values": {}, "time_ago_str": "N/A", "latest_timestamp_str": "N/A", "mini_trend": []}
    wave_info = {"values": {}, "time_ago_str": "N/A", "latest_timestamp_str": "N/A", "mini_trend": []}
    vr2c_info = {"values": {}, "time_ago_str": "N/A", "latest_timestamp_str": "N/A", "mini_trend": []}
    fluorometer_info = {"values": {}, "time_ago_str": "N/A", "latest_timestamp_str": "N/A", "mini_trend": []}
    wg_vm4_info = {"values": {}, "time_ago_str": "N/A", "latest_timestamp_str": "N/A", "mini_trend": []}
    navigation_info = {"values": {}, "time_ago_str": "N/A", "latest_timestamp_str": "N/A", "mini_trend": []}
    ais_summary_data = []
    ais_update_info = {"time_ago_str": "N/A", "latest_timestamp_str": "N/A"}
    recent_errors_list = []
    errors_update_info = {"time_ago_str": "N/A", "latest_timestamp_str": "N/A"}

    # Only process data for sensors that were actually loaded
    if "power" in data_frames and data_frames["power"] is not None:
        power_info = summaries.get_power_status(data_frames.get("power"), data_frames.get("solar"))
        power_info["mini_trend"] = summaries.get_power_mini_trend(data_frames.get("power"))

    if "ctd" in data_frames and data_frames["ctd"] is not None:
        ctd_info = summaries.get_ctd_status(data_frames.get("ctd"))
        ctd_info["mini_trend"] = summaries.get_ctd_mini_trend(data_frames.get("ctd"))

    if "weather" in data_frames and data_frames["weather"] is not None:
        weather_info = summaries.get_weather_status(data_frames.get("weather"))
        weather_info["mini_trend"] = summaries.get_weather_mini_trend(data_frames.get("weather"))

    if "waves" in data_frames and data_frames["waves"] is not None:
        wave_info = summaries.get_wave_status(data_frames.get("waves"))
        wave_info["mini_trend"] = summaries.get_wave_mini_trend(data_frames.get("waves"))

    if "vr2c" in data_frames and data_frames["vr2c"] is not None:
        vr2c_info = summaries.get_vr2c_status(data_frames.get("vr2c"))
        vr2c_info["mini_trend"] = summaries.get_vr2c_mini_trend(data_frames.get("vr2c"))

    if "fluorometer" in data_frames and data_frames["fluorometer"] is not None:
        fluorometer_info = summaries.get_fluorometer_status(data_frames.get("fluorometer"))
        fluorometer_info["mini_trend"] = summaries.get_fluorometer_mini_trend(data_frames.get("fluorometer"))

    if "wg_vm4" in data_frames and data_frames["wg_vm4"] is not None:
        wg_vm4_info = summaries.get_wg_vm4_status(data_frames.get("wg_vm4"))
        wg_vm4_info["mini_trend"] = summaries.get_wg_vm4_mini_trend(data_frames.get("wg_vm4"))

    if "telemetry" in data_frames and data_frames["telemetry"] is not None:
        navigation_info = summaries.get_navigation_status(data_frames.get("telemetry"))
        navigation_info["mini_trend"] = summaries.get_navigation_mini_trend(data_frames.get("telemetry"))

    if "ais" in data_frames and data_frames["ais"] is not None:
        ais_summary_data = summaries.get_ais_summary(data_frames.get("ais"), max_age_hours=hours)
        ais_update_info = utils.get_df_latest_update_info(data_frames.get("ais"), timestamp_col="LastSeenTimestamp")

    # Initialize error variables
    recent_errors_list = []
    all_errors_list = []
    errors_update_info = None
    error_analysis = {}
    
    if "errors" in data_frames and data_frames["errors"] is not None:
        logger.info(f"Processing error data: {len(data_frames['errors'])} rows")
        # Get recent errors for text display (24 hours)
        recent_errors_list = summaries.get_recent_errors(data_frames.get("errors"), max_age_hours=hours)[:20]
        errors_update_info = utils.get_df_latest_update_info(data_frames.get("errors"), timestamp_col="Timestamp")
        
        # Enhanced error analysis - use ALL mission errors for graphical analysis
        from .services.error_classification_service import analyze_error_messages, classify_error_message
        from .services.error_analysis_service import ErrorAnalysisService
        
        # Process ALL errors for mission-wide analysis (not just recent 24hrs)
        all_errors_df = data_frames.get("errors")
        if all_errors_df is not None and not all_errors_df.empty:
            # Get all error messages from the entire mission
            all_error_messages = []
            for _, row in all_errors_df.iterrows():
                # Try both column names in case the processor didn't rename it
                error_msg = row.get('ErrorMessage', '') or row.get('error_Message', '')
                if error_msg and str(error_msg).strip():
                    all_error_messages.append(str(error_msg).strip())
            
            # Analyze all mission errors for graphical display
            error_analysis = analyze_error_messages(all_error_messages) if all_error_messages else {}
            
            # Process all errors for the collapsible tab (with classification)
            all_errors_list = []
            for _, row in all_errors_df.iterrows():
                # Convert timestamp to datetime if it's a string
                timestamp = row.get('Timestamp') or row.get('timeStamp')
                if isinstance(timestamp, str):
                    try:
                        from datetime import datetime
                        timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    except (ValueError, AttributeError):
                        timestamp = None
                
                error_dict = {
                    'Timestamp': timestamp,
                    'VehicleName': row.get('VehicleName') or row.get('vehicleName'),
                    'ErrorMessage': row.get('ErrorMessage') or row.get('error_Message'),
                    'SelfCorrected': row.get('SelfCorrected') or row.get('selfCorrected')
                }
                
                # Classify the error
                if error_dict['ErrorMessage']:
                    category, confidence, description = classify_error_message(error_dict['ErrorMessage'])
                    error_dict['category'] = category.value
                    error_dict['confidence'] = confidence
                    error_dict['category_description'] = description
                else:
                    error_dict['category'] = 'unknown'
                    error_dict['confidence'] = 0.0
                    error_dict['category_description'] = 'Unknown error type'
                
                all_errors_list.append(error_dict)
            
            # Sort by timestamp (most recent first)
            from datetime import datetime
            all_errors_list.sort(key=lambda x: x['Timestamp'] if x['Timestamp'] else datetime.min, reverse=True)
            
        else:
            error_analysis = {}
    
    # Add classification to recent errors (for text display) - always process this
    from .services.error_classification_service import classify_error_message
    for error in recent_errors_list:
        if error.get('ErrorMessage'):
            category, confidence, description = classify_error_message(error['ErrorMessage'])
            error['category'] = category.value
            error['confidence'] = confidence
            error['category_description'] = description
        else:
            # Ensure all error objects have the required attributes
            error['category'] = 'unknown'
            error['confidence'] = 0.0
            error['category_description'] = 'Unknown error type'

    return {
        "display_source_path": display_source_path,
        "power_info": power_info,
        "ctd_info": ctd_info,
        "weather_info": weather_info,
        "wave_info": wave_info,
        "vr2c_info": vr2c_info,
        "fluorometer_info": fluorometer_info,
        "wg_vm4_info": wg_vm4_info,
        "navigation_info": navigation_info,
        "ais_summary_data": ais_summary_data,
        "ais_update_info": ais_update_info,
        "recent_errors_list": recent_errors_list,
        "all_errors_list": all_errors_list,
        "errors_update_info": errors_update_info,
        "error_analysis": error_analysis,
        "has_ais_data": bool(ais_summary_data),
        "has_errors_data": bool(recent_errors_list) or bool(error_analysis.get('total_errors', 0) > 0),
    }







# --- Schedule ---
# (All schedule-related endpoints, helpers, and DayPilot references have been moved to app/routers/schedule.py and are now removed from this file.)
# ... existing code ...







# --- Payroll and Timesheet Endpoints ---
# (All payroll, timesheet, pay period, and related HTML endpoints have been moved to app/routers/payroll.py and are now removed from this file.)
# ... existing code ...









@app.get("/", include_in_schema=False)
async def root(request: Request, current_user: models.User = Depends(get_current_active_user), session: SQLModelSession = Depends(get_db_session)):
    mission = request.query_params.get("mission")
    if not mission:
        return RedirectResponse(url="/home.html")

    # Load mission overview data for sensor card configuration
    mission_overview = session.get(models.MissionOverview, mission)
    enabled_sensor_cards = []
    
    if mission_overview:
        logger.info(f"DASHBOARD: Found mission overview for {mission}")
        if mission_overview.enabled_sensor_cards:
            try:
                enabled_sensor_cards = json.loads(mission_overview.enabled_sensor_cards)
                logger.info(f"DASHBOARD: Loaded sensor card config for mission {mission}: {enabled_sensor_cards}")
            except json.JSONDecodeError as e:
                # Default to all sensors if parsing fails
                enabled_sensor_cards = ["navigation", "power", "ctd", "weather", "waves", "vr2c", "fluorometer", "wg_vm4", "ais", "errors"]
                logger.warning(f"DASHBOARD: Failed to parse sensor card config for mission {mission}: {e}. Using defaults: {enabled_sensor_cards}")
        else:
            # Mission overview exists but no sensor card config - update it with minimal sensors
            logger.warning(f"DASHBOARD: Mission overview exists for {mission} but no sensor card config found. Updating with minimal sensor config.")
            
            # Update the existing mission overview with minimal sensor configuration
            default_enabled_sensors = ["navigation", "power", "ctd", "weather", "waves", "ais", "errors"]
            mission_overview.enabled_sensor_cards = json.dumps(default_enabled_sensors)
            
            try:
                session.add(mission_overview)
                session.commit()
                enabled_sensor_cards = default_enabled_sensors
                logger.info(f"DASHBOARD: Updated mission overview for {mission} with sensors: {enabled_sensor_cards}")
            except Exception as e:
                logger.error(f"DASHBOARD: Failed to update mission overview for {mission}: {e}")
                # Fallback to minimal sensors even if database update fails
                enabled_sensor_cards = default_enabled_sensors
    else:
        # No mission overview exists - create a default one with minimal sensors
        logger.warning(f"DASHBOARD: No mission overview found for mission {mission}. Creating default with minimal sensor config.")
        
        # Create a default mission overview with only essential sensors enabled
        default_enabled_sensors = ["navigation", "power", "ctd", "weather", "waves", "ais", "errors"]
        default_mission_overview = models.MissionOverview(
            mission_id=mission,
            enabled_sensor_cards=json.dumps(default_enabled_sensors),
            comments=f"Auto-created default mission overview for {mission} with minimal sensor configuration."
        )
        
        try:
            session.add(default_mission_overview)
            session.commit()
            enabled_sensor_cards = default_enabled_sensors
            logger.info(f"DASHBOARD: Created default mission overview for {mission} with sensors: {enabled_sensor_cards}")
        except Exception as e:
            logger.error(f"DASHBOARD: Failed to create default mission overview for {mission}: {e}")
            # Fallback to minimal sensors even if database creation fails
            enabled_sensor_cards = default_enabled_sensors

    # Define the report types to load for the dashboard based on enabled sensor cards
    # Map sensor card categories to their corresponding data report types
    sensor_to_report_mapping = {
        "navigation": "telemetry",  # Navigation card uses telemetry data
        "power": "power",
        "ctd": "ctd", 
        "weather": "weather",
        "waves": "waves",
        "vr2c": "vr2c",
        "fluorometer": "fluorometer",
        "wg_vm4": "wg_vm4",
        "ais": "ais",
        "errors": "errors"
    }
    
    # Always include solar data if power is enabled (solar is used in power charts)
    report_types_to_load = []
    for sensor_card in enabled_sensor_cards:
        if sensor_card in sensor_to_report_mapping:
            report_types_to_load.append(sensor_to_report_mapping[sensor_card])
            # Add solar data if power is enabled
            if sensor_card == "power" and "solar" not in report_types_to_load:
                report_types_to_load.append("solar")
    
    logger.info(f"DASHBOARD: Loading data for mission {mission} with report types: {report_types_to_load}")
    
    hours = 24  # Default time window for summaries/mini-trends

    # Load only the data sources for enabled sensor cards
    results = await asyncio.gather(
        *[load_data_source(rt, mission, current_user=current_user) for rt in report_types_to_load],
        return_exceptions=True
    )

    # Process the loaded data for summaries and mini-trends
    context = await _process_loaded_data_for_home_view(results, report_types_to_load, hours, mission)
    context.update(get_template_context(
        request=request,
        mission=mission,
        current_user=current_user,
    ))
    
    # Add sensor card configuration to context
    context["enabled_sensor_cards"] = enabled_sensor_cards

    return templates.TemplateResponse("index.html", context)

@app.get("/api/data/{report_type}/{mission_id}")
async def get_report_data_for_plotting(
    report_type: models.ReportTypeEnum,  # Use Enum for path parameter validation
    mission_id: str,
    params: models.ReportDataParams = Depends(),  # Inject Pydantic model for query params
    current_user: models.User = Depends(get_current_active_user),  # Protect API
):
    try:
        # Unpack the DataFrame and the source path; we only need the DataFrame here
        df, _ = await load_data_source(  # type: ignore
            report_type.value,
            mission_id,  # Use .value for Enum
            source_preference=(
                params.source.value if params.source else None
            ),  # Use .value for Enum
            custom_local_path=params.local_path,
            force_refresh=params.refresh,
            current_user=current_user,
            start_date=params.start_date,
            end_date=params.end_date,
        )

        if df is None or df.empty:
            # Return empty list for charts instead of 404 to allow chart to render "no data"
            return JSONResponse(content=[])

        # --- Specific filtering for wave direction outliers BEFORE preprocessing/resampling ---
        if report_type.value == "waves":
            # The raw column name for wave direction is typically 'dp (deg)'
            # This is before processors.preprocess_wave_df renames it.
            raw_wave_direction_col = "dp (deg)"
            if raw_wave_direction_col in df.columns:
                # Convert to numeric, coercing errors. This helps if it's read as object/string.
                df[raw_wave_direction_col] = pd.to_numeric(
                    df[raw_wave_direction_col], errors="coerce"
                )
                # Replace 9999 and -9999 with NaN so they are ignored in mean calculations
                df[raw_wave_direction_col] = df[raw_wave_direction_col].replace(
                    {9999: np.nan, -9999: np.nan}
                )
                logger.info(
                    f"Applied outlier filtering to '{raw_wave_direction_col}' "
                    f"for mission {mission_id}."
                )
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
        elif report_type == "vr2c":  # New sensor
            processed_df = processors.preprocess_vr2c_df(df)
        elif report_type == "solar":  # New solar panel data
            processed_df = processors.preprocess_solar_df(df)
        elif report_type == "fluorometer":  # C3 Fluorometer
            processed_df = processors.preprocess_fluorometer_df(df)
        elif report_type == "wg_vm4":  # WG-VM4 Sensor
            processed_df = processors.preprocess_wg_vm4_df(df)
        elif report_type == "telemetry":  # Telemetry data for charts
            processed_df = processors.preprocess_telemetry_df(df)

        if processed_df.empty or "Timestamp" not in processed_df.columns:
            logger.warning(
                f"No processable data after preprocessing for {report_type.value}, "
                f"mission {mission_id}"
            )
            return JSONResponse(content=[])

        # Determine the most recent timestamp in the data
        max_timestamp = processed_df["Timestamp"].max()

        if pd.isna(max_timestamp):
            logger.warning(
                f"No valid timestamps in processed data for {report_type.value}, "
                f"mission {mission_id} after preprocessing."
            )
            return JSONResponse(content=[])

        # Apply time-based filtering based on whether date range or hours_back is used
        if params.start_date is not None and params.end_date is not None:
            # Use date range filtering - data was already filtered in load_data_source
            # but we need to ensure it's using the correct timestamp column after preprocessing
            if "Timestamp" in processed_df.columns:
                # Ensure timezone awareness for comparison
                start_date_utc = params.start_date.replace(tzinfo=timezone.utc) if params.start_date.tzinfo is None else params.start_date
                end_date_utc = params.end_date.replace(tzinfo=timezone.utc) if params.end_date.tzinfo is None else params.end_date
                
                # Debug logging
                logger.info(f"Date range filtering for {report_type.value}:")
                logger.info(f"  Input dates: {params.start_date} to {params.end_date}")
                logger.info(f"  UTC dates: {start_date_utc} to {end_date_utc}")
                logger.info(f"  Data timestamp range: {processed_df['Timestamp'].min()} to {processed_df['Timestamp'].max()}")
                
                # Apply date range filtering on the processed data
                mask = (processed_df["Timestamp"] >= start_date_utc) & (processed_df["Timestamp"] <= end_date_utc)
                recent_data = processed_df[mask]
                
                logger.info(f"Applied date range filtering to processed {report_type.value}: "
                           f"{len(processed_df)} -> {len(recent_data)} records "
                           f"({start_date_utc.isoformat()} to {end_date_utc.isoformat()})")
            else:
                # Fallback to using all processed data if no Timestamp column
                recent_data = processed_df
        else:
            # Use hours_back filtering (original behavior)
            cutoff_time = max_timestamp - timedelta(hours=params.hours_back)
            recent_data = processed_df[processed_df["Timestamp"] > cutoff_time]
            if recent_data.empty:
                logger.info(
                    f"No data for {report_type.value}, mission {mission_id} within "
                    f"{params.hours_back} hours of its latest data point ({max_timestamp})."
                )
                return JSONResponse(content=[])

        if recent_data.empty:
            logger.info(f"No data remaining after filtering for {report_type.value}, mission {mission_id}")
            return JSONResponse(content=[])

        # Resample data based on user-defined granularity
        data_to_resample = recent_data.set_index("Timestamp")
        numeric_cols = data_to_resample.select_dtypes(include=[np.number])
        # Ensure numeric_cols is not empty before resampling
        if numeric_cols.empty:
            logger.info(
                f"No numeric data to resample for {report_type.value}, "
                f"mission {mission_id} after filtering and before resampling."
            )
            return JSONResponse(content=[])

        # Perform resampling using the specified granularity
        resampled_data = numeric_cols.resample(f"{params.granularity_minutes}min").mean().reset_index()

        if report_type == "vr2c" and "PingCount" in resampled_data.columns:
            resampled_data = resampled_data.sort_values(
                by="Timestamp"
            )  # Ensure sorted for correct diff
            resampled_data["PingCountDelta"] = resampled_data["PingCount"].diff()
            # The first PingCountDelta will be NaN, which is fine for plotting (Chart.js handles nulls)
        # Convert Timestamp objects to ISO 8601 strings for JSON serialization
        if "Timestamp" in resampled_data.columns:
            resampled_data["Timestamp"] = resampled_data["Timestamp"].dt.strftime(
                "%Y-%m-%dT%H:%M:%S"
            )

        # Replace NaN with None for JSON compatibility and return
        resampled_data = resampled_data.replace({np.nan: None})
        return JSONResponse(content=resampled_data.to_dict(orient="records"))
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={"error": str(e), "detail": "See server logs for traceback."}
        )


# ---


@app.get("/api/forecast/{mission_id}")
async def get_weather_forecast(
    mission_id: str,
    params: models.ForecastParams = Depends(),  # Inject Pydantic model for query params
    current_user: models.User = Depends(get_current_active_user),  # Protect API
):
    """
    Provides a weather forecast.
    If lat and lon are not provided, it attempts to infer them from the latest telemetry data.
    """
    final_lat, final_lon = params.lat, params.lon

    if final_lat is None or final_lon is None:
        logger.info(
            f"Lat/Lon not provided for forecast. Inferring from telemetry "
            f"for mission {mission_id}."
        )
        # Pass source preference to telemetry loading
        # Unpack the DataFrame and the source path; we only need the DataFrame here, pass refresh. No client passed.
        df_telemetry, _ = await load_data_source(
            "telemetry",
            mission_id,
            source_preference=(
                params.source.value if params.source else None
            ),  # Use .value for Enum
            custom_local_path=params.local_path,
            force_refresh=params.refresh,
            current_user=current_user,
        )

        if df_telemetry is None or df_telemetry.empty:
            logger.warning(
                f"Telemetry data for mission {mission_id} not found or empty. "
                "Cannot infer location."
            )
        else:
            # Standardize timestamp column before sorting
            # Ensure 'lastLocationFix' is datetime and sort
            if "lastLocationFix" in df_telemetry.columns:
                df_telemetry["lastLocationFix"] = pd.to_datetime(
                    df_telemetry["lastLocationFix"], errors="coerce"
                )
                df_telemetry = df_telemetry.dropna(
                    subset=["lastLocationFix"]
                )  # Remove rows where conversion failed
                if not df_telemetry.empty:
                    latest_telemetry = df_telemetry.sort_values(
                        "lastLocationFix", ascending=False
                    ).iloc[0]
                    # Try to get lat/lon, allowing for different capitalizations
                    inferred_lat = latest_telemetry.get(
                        "latitude"
                    ) or latest_telemetry.get("Latitude")
                    inferred_lon = latest_telemetry.get(
                        "longitude"
                    ) or latest_telemetry.get("Longitude")

                    if not pd.isna(inferred_lat) and not pd.isna(inferred_lon):
                        final_lat, final_lon = float(inferred_lat), float(inferred_lon)
                        logger.info(
                            f"Inferred location for mission {mission_id}: "
                            f"Lat={final_lat}, Lon={final_lon}"
                        )
                    else:
                        logger.warning(
                            f"Could not extract valid lat/lon from latest "
                            f"telemetry for mission {mission_id}."
                        )

    if final_lat is None or final_lon is None:
        raise HTTPException(
            status_code=400,
            detail="Lat/Lon required for forecast and could not be inferred.",
        )

    # For the main forecast display in the Weather section, we fetch general
    # forecast.
    # The 'force_marine' parameter is no longer directly applicable here as we're calling the general forecast.
    forecast_data = await forecast.get_general_meteo_forecast(final_lat, final_lon)

    if forecast_data is None:
        raise HTTPException(
            status_code=503,
            detail="Weather forecast service unavailable or failed to retrieve data.",
        )

    return JSONResponse(content=forecast_data)


@app.get("/api/marine_forecast/{mission_id}")  # New endpoint for marine-specific data
async def get_marine_weather_data(
    mission_id: str,  # mission_id might be used later if lat/lon needs inference for marine
    params: models.ForecastParams = Depends(),
    current_user: models.User = Depends(get_current_active_user),  # Protect API
):
    """Provides marine-specific forecast data (waves, currents)."""
    final_lat, final_lon = params.lat, params.lon

    if final_lat is None or final_lon is None:
        logger.info(
            f"Lat/Lon not provided for marine forecast. Inferring from "
            f"telemetry for mission {mission_id}."
        )
        df_telemetry, _ = await load_data_source(
            "telemetry",
            mission_id,
            source_preference=params.source.value if params.source else None,
            custom_local_path=params.local_path,
            force_refresh=params.refresh,
            current_user=current_user,
        )

        if df_telemetry is None or df_telemetry.empty:
            logger.warning(
                f"Telemetry data for marine forecast (mission {mission_id}) "
                f"not found or empty. Cannot infer location."
            )
        else:
            if "lastLocationFix" in df_telemetry.columns:
                df_telemetry["lastLocationFix"] = pd.to_datetime(
                    df_telemetry["lastLocationFix"], errors="coerce"
                )
                df_telemetry = df_telemetry.dropna(subset=["lastLocationFix"])
                if not df_telemetry.empty:
                    latest_telemetry = df_telemetry.sort_values(
                        "lastLocationFix", ascending=False
                    ).iloc[0]
                    inferred_lat = latest_telemetry.get(
                        "latitude"
                    ) or latest_telemetry.get("Latitude")
                    inferred_lon = latest_telemetry.get(
                        "longitude"
                    ) or latest_telemetry.get("Longitude")

                    if not pd.isna(inferred_lat) and not pd.isna(inferred_lon):
                        final_lat, final_lon = float(inferred_lat), float(inferred_lon)
                        logger.info(
                            f"Inferred location for marine forecast "
                            f"(mission {mission_id}): Lat={final_lat}, Lon={final_lon}"
                        )
                    else:
                        logger.warning(
                            f"Could not extract valid lat/lon from telemetry "
                            f"for marine forecast (mission {mission_id})."
                        )

    if final_lat is None or final_lon is None:
        raise HTTPException(
            status_code=400,
            detail="Latitude and Longitude are required for marine forecast.",
        )

    marine_data = await forecast.get_marine_meteo_forecast(final_lat, final_lon)
    if marine_data is None:
        raise HTTPException(
            status_code=503,
            detail="Marine forecast service unavailable or failed to retrieve data.",
        )
    return JSONResponse(content=marine_data)


# --- NEW API Endpoint for Wave Spectrum Data ---
@app.get("/api/wave_spectrum/{mission_id}")
async def get_wave_spectrum_data(
    mission_id: str,
    timestamp: Optional[
        datetime
    ] = None,  # Optional specific timestamp for the spectrum
    params: models.ForecastParams = Depends(),  # Reusing ForecastParams for source, local_path, refresh
    current_user: models.User = Depends(get_current_active_user),  # Protect API
):
    """
    Provides the latest wave energy spectrum data (Frequency vs. Energy Density).
    Optionally provides the spectrum closest to a given timestamp.
    """
    # Define a unique cache key for the *processed* spectrum data
    spectrum_cache_key = (
        "processed_wave_spectrum",
        mission_id, # Use .value for Enum if params.source is Enum
        params.source.value if params.source else None,
        params.local_path,
    )


    spectral_records = None
    # Check cache first for the processed spectrum list
    if not params.refresh and spectrum_cache_key in data_cache:
        # data_cache stores (data, path, timestamp). Here 'data' is the list of spectral_records.
        cached_spectral_records, cached_source_path_info, cache_timestamp = data_cache[
            spectrum_cache_key
        ]

        is_realtime_source = (
            "Remote:" in cached_source_path_info
            and "output_realtime_missions" in cached_source_path_info
        )

        if is_realtime_source and (
            datetime.now() - cache_timestamp < timedelta(minutes=CACHE_EXPIRY_MINUTES)
        ):
            logger.info(
                f"CACHE HIT (valid - real-time processed spectrum): Returning "
                f"wave spectrum for {mission_id} from cache. Derived from: "
                f"{cached_source_path_info}"
            )
            spectral_records = cached_spectral_records
        elif (
            not is_realtime_source and cached_spectral_records
        ):  # Static source, cache is good if data exists
            logger.info(
                f"CACHE HIT (valid - static processed spectrum): Returning "
                f"wave spectrum for {mission_id} from cache. Derived from: "
                f"{cached_source_path_info}"
            )
            spectral_records = cached_spectral_records
        else:  # Expired real-time or empty static cache
            logger.info(f"Cache for processed spectrum for {mission_id} is expired/invalid. Will re-load.")

    if (
        spectral_records is None
    ):  # Cache miss or expired/forced refresh for processed data
        logger.info(
            f"CACHE MISS (processed spectrum) or refresh for {mission_id}. Loading and processing source files."
        )
        # Use .value for Enum if params.source is Enum
        df_freq, path_freq = await load_data_source( # type: ignore
            "wave_frequency_spectrum",
            mission_id,
            params.source.value if params.source else None,
            params.local_path,
            params.refresh,
            current_user,
        )
        df_energy, path_energy = await load_data_source( # type: ignore
            "wave_energy_spectrum",
            mission_id,
            params.source.value if params.source else None,
            params.local_path,
            params.refresh,
            current_user,
        )

        spectral_records = processors.preprocess_wave_spectrum_dfs(df_freq, df_energy)
        if spectral_records:  # Only cache if processing was successful and yielded data
            data_cache[spectrum_cache_key] = (
                spectral_records,
                f"Combined from {path_freq} and {path_energy}", # noqa
                datetime.now(),
            )

    if not spectral_records:
        logger.warning(
            f"No wave spectral records found or processed for mission {mission_id}."
        )
        return JSONResponse(content={})  # Return empty object

    # Select the target spectrum (latest or closest to timestamp)
    target_spectrum = utils.select_target_spectrum(
        spectral_records, timestamp
    )  # Assuming utils.select_target_spectrum handles this logic

    if (
        not target_spectrum
        or "freq" not in target_spectrum
        or "efth" not in target_spectrum
    ):
        logger.warning(
            f"Selected target spectrum for mission {mission_id} is invalid "
            f"or missing data."
        )
        return JSONResponse(content={})

    spectrum_data = [
        {"x": f, "y": e}
        for f, e in zip(
            target_spectrum.get("freq", []), target_spectrum.get("efth", [])
        )
        if pd.notna(f) and pd.notna(e)
    ]
    return JSONResponse(content=spectrum_data)


# --- HTML Route for Forms ---
@app.get("/mission/{mission_id}/form/{form_type}.html", response_class=HTMLResponse)
async def get_mission_form_page(
    request: Request,
    mission_id: str,
    form_type: str,
    actual_current_user: Optional[models.User] = Depends(get_optional_current_user),
):
    # The `actual_current_user` is now correctly injected by FastAPI.
    # The JS on the page will handle auth checks for API calls.
    username_for_log = (
        actual_current_user.username if actual_current_user else "anonymous"
    )
    logger.info(
        f"Serving HTML form: /mission/{mission_id}/form/{form_type}.html "
        f"for user '{username_for_log}'"
    )
    try:
        template_name = "mission_form.html"
        context = get_template_context(
            request=request,
            mission_id=mission_id,
            form_type=form_type,
            current_user=actual_current_user,  # Pass to template
        )

        response = templates.TemplateResponse(template_name, context)
        logger.info(f"Successfully prepared TemplateResponse for {template_name}.")
        return response
    except Exception as e:
        logger.error(
            f"Error serving HTML form page /mission/{mission_id}/form/{form_type}.html: {e}",
            exc_info=True
            ,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error rendering form page: {str(e)}",
        )


# --- HTML Route for Viewing All Forms (Admin) ---


# --- HTML Route for Station Offload Status Page ---
@app.get("/view_station_status.html", response_class=HTMLResponse)
async def get_view_station_status_page(
    request: Request,
    current_user: Optional[models.User] = Depends(get_optional_current_user),
):
    username_for_log = (
        current_user.username if current_user else "anonymous/unauthenticated"
    )
    user_role_for_log = (
        current_user.role.value if current_user and current_user.role else "N/A"
    )
    logger.info(
        f"User '{username_for_log}' (role: {user_role_for_log}) "
        f"accessing /view_station_status.html."
    )
    return templates.TemplateResponse(
        "view_station_status.html",
        get_template_context(
            request=request,
            current_user=current_user, # Removed show_mission_selector
        )
    )


# --- HTML Route for Admin User Management ---
@app.get("/admin/user_management.html", response_class=HTMLResponse)
async def get_admin_user_management_page(
    request: Request,
    # Changed to optional_current_user. JS will verify admin role via API.
    current_user: Optional[models.User] = Depends(get_optional_current_user),
):
    # This log will show if a user (even non-admin) attempts to load the page.
    # The actual admin check happens when admin_user_management.js calls /api/admin/users.
    username_for_log = (
        current_user.username if current_user else "anonymous/unauthenticated"
    )
    user_role_for_log = (
        current_user.role.value if current_user and current_user.role else "N/A"
    )
    logger.info(
        f"User '{username_for_log}' (role: {user_role_for_log}) accessing "
        f"/admin/user_management.html. JS will verify admin role via API."
    )
    return templates.TemplateResponse(
        "admin_user_management.html",
        get_template_context(
            request=request,
            current_user=current_user, # Removed show_mission_selector
        )
    )

from fastapi.exception_handlers import http_exception_handler as original_http_exception_handler
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.responses import RedirectResponse
from fastapi import Request

@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 401:
        if request.url.path.startswith("/api/"):
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
        else:
            return RedirectResponse(url="/login.html")
    return await original_http_exception_handler(request, exc)
