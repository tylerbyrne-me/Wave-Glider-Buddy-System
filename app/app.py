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
from cachetools import LRUCache # Import LRUCache
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

import io # For CSV and ICS generation
import csv # For CSV generation
import ics # For ICS file generation

from . import \
    auth_utils  # Import the auth_utils module itself for its functions
# Specific user-related functions will be called via auth_utils.func_name(session, ...)
from .auth_utils import (get_current_active_user, get_current_admin_user,
                         get_optional_current_user)
from .config import settings
from .core import models  # type: ignore
from .core import (forecast, loaders, processors, summaries, utils)  # type: ignore
from .core.security import create_access_token, verify_password
from .db import SQLModelSession, get_db_session, sqlite_engine
from .forms.form_definitions import get_static_form_schema # Import the new function
from .routers import station_metadata_router

# --- Conditional import for fcntl ---
IS_UNIX = True
try:
    import fcntl
except ImportError:
    IS_UNIX = False
    fcntl = None  # type: ignore # Make fcntl None on non-Unix systems

# --- New Models (Ideally in app/core/models.py) ---

class Announcement(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    content: str
    created_by_username: str
    created_at_utc: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_active: bool = Field(default=True)
    acknowledgements: List["AnnouncementAcknowledgement"] = Relationship(back_populates="announcement")

class AnnouncementAcknowledgement(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    announcement_id: int = Field(foreign_key="announcement.id")
    user_id: int = Field(foreign_key="users.id")
    acknowledged_at_utc: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    announcement: "Announcement" = Relationship(back_populates="acknowledgements")
    # The user relationship is not strictly needed for back-population here,
    # but can be useful for other queries.
    # user: "UserInDB" = Relationship()

class AnnouncementCreate(SQLModel):
    content: str

class AnnouncementRead(SQLModel):
    id: int
    content: str
    created_by_username: str
    created_at_utc: datetime
    is_active: bool

class AnnouncementReadForUser(AnnouncementRead):
    is_acknowledged_by_user: bool = False

class AcknowledgedByInfo(SQLModel):
    username: str
    acknowledged_at_utc: datetime

class AnnouncementReadWithAcks(AnnouncementRead):
    acknowledged_by: List[AcknowledgedByInfo] = []

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
class UpcomingShift(SQLModel):
    mission_id: str
    start_time_utc: datetime
    end_time_utc: datetime

class MyTimesheetStatus(SQLModel):
    current_period_status: str
    hours_this_period: float

class MissionGoalToggle(BaseModel):
    is_completed: bool





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
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

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

logger = logging.getLogger(__name__)
logger.info("--- FastAPI application module loaded. This should appear on every server start/reload. ---")
# ---

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



# --- Helper function to save forms to local JSON (for testing) ---
def _save_forms_to_local_json():
    """Saves the current mission_forms_db to a local JSON file."""
    if (
        settings.forms_storage_mode == "local_json"
    ):  # Only run if mode is local_json
        # NOTE: This local JSON storage is for development/testing purposes only.
        # For production, use a proper database.
        DATA_STORE_DIR.mkdir(parents=True, exist_ok=True)
        # Convert tuple keys to string keys for JSON compatibility
        serializable_db = {
            json.dumps(list(k)): v.model_dump(mode="json")
            for k, v in mission_forms_db.items()
        }
        try:
            with open(LOCAL_FORMS_DB_FILE, "w") as f:
                json.dump(serializable_db, f, indent=4)
            logger.info(f"Forms database saved to {LOCAL_FORMS_DB_FILE}")
        except IOError as e:
            logger.error(
                f"Error saving forms database to {LOCAL_FORMS_DB_FILE}: {e}"
            )
        except TypeError as e:
            logger.error(
                f"TypeError saving forms database (serialization issue): {e}"
            )
    elif settings.forms_storage_mode == "sqlite":
        logger.debug("Forms storage mode is 'sqlite'. JSON save skipped.")
    else:
        logger.warning(
            f"Unknown forms_storage_mode: {settings.forms_storage_mode}. "
            "Forms not saved to JSON."
        )


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

async def load_data_source(
    report_type: str,
    mission_id: str,
    source_preference: Optional[str] = None,  # 'local' or 'remote'
    custom_local_path: Optional[str] = None,
    force_refresh: bool = False,  # New parameter to bypass cache
    current_user: Optional[
        models.User  # Changed from UserInDB to match what get_optional_current_user returns
    ] = None,
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
    realtime_report_types = [
        "power",
        "ctd",
        "weather",
        "waves",
        "telemetry",
        "ais",
        "errors",
        "vr2c",
        "fluorometer",
        "wg_vm4",
        "wave_frequency_spectrum",
        "wave_energy_spectrum",
    ]

    for mission_id in active_missions:
        logger.info(
            f"BACKGROUND TASK: Refreshing cache for active mission: {mission_id}"
        )
        for report_type in realtime_report_types:
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

    # Calculate summaries
    # Ensure that even if a df is None, the summary function is called to get the default shell
    power_info = summaries.get_power_status(data_frames.get("power"), data_frames.get("solar"))
    power_info["mini_trend"] = summaries.get_power_mini_trend(data_frames.get("power"))

    ctd_info = summaries.get_ctd_status(data_frames.get("ctd"))
    ctd_info["mini_trend"] = summaries.get_ctd_mini_trend(data_frames.get("ctd"))

    weather_info = summaries.get_weather_status(data_frames.get("weather"))
    weather_info["mini_trend"] = summaries.get_weather_mini_trend(data_frames.get("weather"))

    wave_info = summaries.get_wave_status(data_frames.get("waves"))
    wave_info["mini_trend"] = summaries.get_wave_mini_trend(data_frames.get("waves"))

    vr2c_info = summaries.get_vr2c_status(data_frames.get("vr2c"))
    vr2c_info["mini_trend"] = summaries.get_vr2c_mini_trend(data_frames.get("vr2c"))

    fluorometer_info = summaries.get_fluorometer_status(data_frames.get("fluorometer"))
    fluorometer_info["mini_trend"] = summaries.get_fluorometer_mini_trend(data_frames.get("fluorometer"))

    wg_vm4_info = summaries.get_wg_vm4_status(data_frames.get("wg_vm4"))
    wg_vm4_info["mini_trend"] = summaries.get_wg_vm4_mini_trend(data_frames.get("wg_vm4"))

    navigation_info = summaries.get_navigation_status(data_frames.get("telemetry"))
    navigation_info["mini_trend"] = summaries.get_navigation_mini_trend(data_frames.get("telemetry"))

    ais_summary_data = summaries.get_ais_summary(data_frames.get("ais"), max_age_hours=hours)
    ais_update_info = utils.get_df_latest_update_info(data_frames.get("ais"), timestamp_col="LastSeenTimestamp")

    recent_errors_list = summaries.get_recent_errors(data_frames.get("errors"), max_age_hours=hours)[:20]
    errors_update_info = utils.get_df_latest_update_info(data_frames.get("errors"), timestamp_col="Timestamp")

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
        "errors_update_info": errors_update_info,
        "has_ais_data": bool(ais_summary_data),
        "has_errors_data": bool(recent_errors_list),
    }

async def _get_mission_info(mission_id: str, session: SQLModelSession) -> models.MissionInfoResponse:
    """Helper to fetch all info (overview, goals, notes) for a mission."""
    overview = session.get(models.MissionOverview, mission_id)

    goals_stmt = select(models.MissionGoal).where(models.MissionGoal.mission_id == mission_id).order_by(models.MissionGoal.id)
    goals = session.exec(goals_stmt).all()

    notes_stmt = select(models.MissionNote).where(models.MissionNote.mission_id == mission_id).order_by(models.MissionNote.created_at_utc.desc())
    notes = session.exec(notes_stmt).all()

    return models.MissionInfoResponse(
        overview=overview,
        goals=goals,
        notes=notes
    )

# --- Authentication Endpoint ---
@app.post("/token") # Removed response_model to allow setting cookies on the Response
async def login_for_access_token(
    response: Response, # Inject the Response object
    form_data: OAuth2PasswordRequestForm = Depends(),
    session: SQLModelSession = Depends(get_db_session),  # Inject session
):
    """Authenticates user and returns a token in the body and sets a secure cookie."""
    user_in_db = auth_utils.get_user_from_db(
        session, form_data.username
    )  # Pass session
    if not user_in_db or not verify_password(
        form_data.password, user_in_db.hashed_password
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if user_in_db.disabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Inactive user"
        )

    logger.info(
        f"User '{user_in_db.username}' authenticated successfully. Issuing token."
    )
    access_token = create_access_token(
        data={"sub": user_in_db.username, "role": user_in_db.role.value}
    )

    # Set the access token in an HttpOnly cookie
    response.set_cookie(
        key="access_token_cookie",
        value=access_token,
        httponly=True,  # Prevents client-side JS from accessing the cookie
        samesite="lax", # Recommended for security
        # secure=True, # In production with HTTPS, this should be True
        # max_age=... # Optionally set an expiry
    )

    # Also return the token in the response body for client-side JS that needs it
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/logout")
async def logout_user(response: Response):
    """Clears the authentication cookie."""
    response.delete_cookie(key="access_token_cookie")
    return {"message": "Logged out successfully"}

# --- Registration Endpoint ---
@app.post("/register", response_model=models.User)
async def register_new_user(
    user_in: models.UserCreate,
    current_admin: models.User = Depends(
        get_current_admin_user
    ),  # Add admin protection
    session: SQLModelSession = Depends(get_db_session),  # Inject session
):
    logger.info(f"Attempting to register new user: {user_in.username}")
    try:
        created_user_in_db = auth_utils.add_user_to_db(
            session, user_in
        )  # Pass session
        # Return User model, not UserInDB (which includes hashed_password)
        return models.User.model_validate(created_user_in_db.model_dump())
    except HTTPException as e:  # Catch username already exists error
        logger.warning(f"Registration failed for {user_in.username}: {e.detail}")
        raise e  # Re-raise the HTTPException


@app.get("/register.html", response_class=HTMLResponse)
async def register_page(
    request: Request,
):
    # Serves the registration page
    return templates.TemplateResponse(
        "register.html", {"request": request}
    )

@app.get("/login.html", response_class=HTMLResponse)
async def login_page(request: Request):
    # Serves the login page
    return templates.TemplateResponse("login.html", {"request": request, "show_mission_selector": False})


@app.get("/", response_class=HTMLResponse)  # Protected route
async def home(
    request: Request,
    mission: Optional[str] = Query(None),
    hours: int = 72,
    source: Optional[str] = None,
    local_path: Optional[str] = None,
    refresh: bool = False,
    actual_current_user: Optional[models.User] = Depends(get_optional_current_user),
):
    # Determine the default mission if not provided in the URL
    if mission is None:
        # Prioritize the first mission from the sorted active list
        if settings.active_realtime_missions:
            mission = sorted(settings.active_realtime_missions)[0]
            logger.info(f"No mission specified, defaulting to first active mission: {mission}")
        # Fallback to the first mission from the sorted list of all missions
        elif settings.remote_mission_folder_map:
            all_missions = sorted(list(settings.remote_mission_folder_map.keys()))
            mission = all_missions[0]
            logger.info(f"No active missions, defaulting to first available mission: {mission}")
        else:
            # If no missions are configured at all, this is a critical error.
            logger.error("CRITICAL: No missions are configured in settings (active_realtime_missions or remote_mission_folder_map). Cannot load dashboard.")
            raise HTTPException(status_code=500, detail="No missions configured in application settings. Please contact an administrator.")
        
    available_missions_for_template = []  # Pass an empty list initially.

    # Determine if the current mission is an active real-time mission
    is_current_mission_realtime = mission in settings.active_realtime_missions
    results = await asyncio.gather(
        load_data_source(
            "power", mission, source, local_path, refresh, actual_current_user
        ),
        load_data_source(
            "ctd", mission, source, local_path, refresh, actual_current_user
        ),
        load_data_source(
            "weather", mission, source, local_path, refresh, actual_current_user
        ),
        load_data_source(
            "waves", mission, source, local_path, refresh, actual_current_user
        ),
        # Corrected order to match report_types_order for vr2c and fluorometer
        load_data_source(
            "vr2c", mission, source, local_path, refresh, actual_current_user
        ),
        load_data_source(
            "solar", mission, source, local_path, refresh, actual_current_user
        ),
        load_data_source(
            "fluorometer", mission, source, local_path, refresh, actual_current_user
        ),
        load_data_source(
            "wg_vm4", mission, source, local_path, refresh, actual_current_user
        ),  # Added WG-VM4
        load_data_source(
            "ais", mission, source, local_path, refresh, actual_current_user
        ),
        load_data_source(
            "errors", mission, source, local_path, refresh, actual_current_user
        ),
        load_data_source(
            "telemetry", mission, source, local_path, refresh, actual_current_user
        ),
        return_exceptions=True,  # To handle individual load failures
    )

    # This list populates status cards and initial summaries.
    report_types_order = [
        "power",
        "ctd",
        "weather",
        "waves",
        "vr2c",
        "solar",
        "fluorometer",
        "wg_vm4",
        "ais",
        "errors",
        "telemetry",
    ]

    # Process loaded data using the helper function
    processed_home_data = await _process_loaded_data_for_home_view(
        results, report_types_order, hours, mission # Pass mission_id
    )

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "mission": mission,
            "available_missions": available_missions_for_template,
            "is_current_mission_realtime": is_current_mission_realtime,
            "current_source_preference": source,  # User's preference (local/remote)
            "default_local_data_path": str(
                settings.local_data_base_path
            ),
            "current_local_path": local_path,  # Pass current local_path
            **processed_home_data, # Unpack all processed data into the context
            "current_user": actual_current_user,  # Pass user info to template
            # show_mission_selector removed, banner handles its own mission selector

        },
    )


# --- API Endpoint for Available Missions ---
@app.get("/api/available_missions", response_model=List[str])
async def get_available_missions_for_user(
    current_user: models.User = Depends(get_current_active_user),  # Protected
):
    logger.info(
        f"Fetching available missions for user: {current_user.username}, "
        f"role: {current_user.role.value}"
    )
    if current_user.role == models.UserRoleEnum.admin:
        return sorted(list(settings.remote_mission_folder_map.keys()))
    elif current_user.role == models.UserRoleEnum.pilot:
        return sorted(settings.active_realtime_missions)
    return []  # Should ideally not be reached if roles are enforced


# --- API Endpoint for Current User Details ---
@app.get("/api/users/me", response_model=models.User)
async def read_users_me(current_user: models.User = Depends(get_current_active_user)):
    """
    Fetch details for the currently authenticated user.
    """
    return current_user


# --- Form Endpoints ---


async def populate_form_schema_with_dynamic_data(
    schema: models.MissionFormSchema, mission_id: str, current_user: models.User
) -> models.MissionFormSchema:
    """
    Populates a given static form schema with dynamic data (e.g., auto-filled values).
    """
    # Example: Auto-fill for pre_deployment_checklist
    if schema.form_type == "pre_deployment_checklist":
        latest_power_df, _ = await load_data_source(
            "power", mission_id, current_user=current_user
        )
        power_summary = summaries.get_power_status(latest_power_df)
        battery_percentage_value = "N/A"
        if (
            power_summary
            and power_summary.get("values")
            and power_summary["values"].get("BatteryPercentage") is not None
        ):
            battery_percentage_value = (
                f"{power_summary['values']['BatteryPercentage']:.1f}%"
            )
        
        for section in schema.sections:
            if section.id == "power_system":
                for item in section.items:
                    if item.id == "battery_level_auto":
                        item.value = battery_percentage_value
                        break # Found item, exit inner loop
                break # Found section, exit outer loop

    # Example: Auto-fill for pic_handoff_checklist
    elif schema.form_type == "pic_handoff_checklist":
        latest_power_df, _ = await load_data_source(
            "power", mission_id, current_user=current_user
        )
        power_summary = summaries.get_power_status(latest_power_df)
        # Check if power_summary is a dictionary before trying to get 'values'
        # Also check if the value associated with 'values' is not None
        if isinstance(power_summary, dict) and power_summary.get("values") is not None:
            power_summary_values = power_summary["values"] # Get the actual values dict
        else:
            power_summary_values = {} # Default to empty dict if summary is not a dict or 'values' is None

        current_battery_wh_value = (
            f"{power_summary_values.get('BatteryWattHours', 'N/A'):.0f} Wh"
            if pd.notna(power_summary_values.get("BatteryWattHours"))
            else "N/A"
        )
        battery_percentage_value = (
            f"{power_summary_values.get('BatteryPercentage', 'N/A'):.0f}%"
            if pd.notna(power_summary_values.get("BatteryPercentage"))
            else "N/A"
        )
        for section in schema.sections:
            if section.id == "general_status":
                for item in section.items:
                    if item.id == "glider_id_val":
                        item.value = mission_id
                    elif item.id == "current_battery_wh_val":
                        item.value = current_battery_wh_value
                    elif item.id == "percent_battery_val":
                        item.value = battery_percentage_value
    # Add more auto-fill logic for other forms/fields as needed
    return schema


# fmt: off
@app.get(
    "/api/forms/{mission_id}/template/{form_type}",
    response_model=models.MissionFormSchema,
)
async def get_form_template_for_mission(
    mission_id: str,
    form_type: str,  # Later, this could be an Enum
    current_user: models.User = Depends(get_current_active_user),
):
# fmt: on
    logger.info(
        f"User '{current_user.username}' requesting form template "
        f"'{form_type}' for mission '{mission_id}'."
    )
    try:
        # 1. Get static schema structure
        static_schema = get_static_form_schema(form_type) # Call the new function
        # 2. Populate with dynamic data
        populated_schema = await populate_form_schema_with_dynamic_data(static_schema, mission_id, current_user)
        return populated_schema
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(
            f"Error generating form schema for {form_type} on mission "
            f"{mission_id}: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail="Could not generate form schema."
        )

# fmt: off
@app.post(
    "/api/forms/{mission_id}",
    response_model=models.MissionFormDataResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_mission_form(
    mission_id: str,  # Path parameter
    form_data_in: models.MissionFormDataCreate,  # Request body
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),  # Inject DB session
):
# fmt: on
    logger.info(
        f"User '{current_user.username}' submitting form "
        f"'{form_data_in.form_type}' for mission '{mission_id}'."
    )
    if form_data_in.mission_id != mission_id:
        raise HTTPException(
            status_code=400,
            detail="Mission ID in path does not match mission ID in form data.",
        )

    submission_ts = datetime.now(timezone.utc)  # Use the directly imported timezone
    form_response = models.MissionFormDataResponse(
        **form_data_in.model_dump(),
        submitted_by_username=current_user.username,
        submission_timestamp=submission_ts,
    )

    if settings.forms_storage_mode == "local_json":
        # Store in our in-memory DB (for local_json mode)
        form_key_json = (mission_id, form_data_in.form_type, submission_ts.isoformat())
        mission_forms_db[form_key_json] = form_response
        _save_forms_to_local_json()  # Save to local file if mode is local_json
        logger.info(
            f"Form '{form_data_in.form_type}' (mission '{mission_id}') "
            f"submitted by '{current_user.username}' and saved to JSON. "
            f"Key: {form_key_json}"
        )
    elif settings.forms_storage_mode == "sqlite":
        try:
            # Convert the Pydantic response model (which might have List[FormSection])
            # to a dictionary. model_dump() will convert nested Pydantic models
            # (like FormSection and FormItem) into dicts automatically.
            form_data_dict = form_response.model_dump()

            # Create the SubmittedForm instance using the dictionary.
            # Since SubmittedForm.sections_data is List[dict], this is fine.
            db_form_entry = models.SubmittedForm(**form_data_dict)
            session.add(db_form_entry)
            session.commit()
            session.refresh(db_form_entry)
            logger.info(
                f"Form '{db_form_entry.form_type}' (mission '{db_form_entry.mission_id}') submitted by '{db_form_entry.submitted_by_username}' and saved to SQLite DB with ID: {db_form_entry.id}"
            )
        except Exception as e:
            logger.error(
                f"Error saving form '{form_data_in.form_type}' to SQLite DB: "
                f"{e}",
                exc_info=True,
            )
            session.rollback()  # Rollback in case of error
            raise HTTPException(
                status_code=500, detail="Failed to save form to database."
            )

        # --- Update StationMetadata for WG-VM4 Offload Log ---
        if form_data_in.form_type == "wg_vm4_offload_log":
            logger.info(
                f"Processing wg_vm4_offload_log for mission '{mission_id}'. "
                f"Form sections: {len(form_data_in.sections_data)}"
            )
            offloaded_station_id: Optional[str] = None
            found_station_id_field_in_payload = (
                False  # Flag to check if the field itself was present
            )
            for section in form_data_in.sections_data:
                # logger.debug(
                #     f"  Checking section ID '{section.id}', Title: "
                #     f"'{section.title}', Items: {len(section.items)}"
                # )
                for item in section.items:
                    # logger.debug(
                    #     f"    Item ID: '{item.id}', Label: '{item.label}', "
                    #     f"Value: '{item.value}'"
                    # )
                    if (
                        item.id == "station_id_for_offload"
                    ):  # Check if the field ID matches
                        found_station_id_field_in_payload = True
                        if (
                            item.value and str(item.value).strip()
                        ):  # Check if the value is not None and not an empty string
                            offloaded_station_id = str(item.value).strip()
                            logger.info(
                                f"    Found 'station_id_for_offload' in section "
                                f"'{section.id}' with value: {offloaded_station_id}"
                            )
                        else:
                            logger.warning(
                                f"    Found 'station_id_for_offload' in section "
                                f"'{section.id}' but value is empty/None."
                            )
                        break  # Found field, no need to check other items
                if (
                    found_station_id_field_in_payload
                ):  # If field found (even if value empty), break sections loop
                    break

            if (
                offloaded_station_id
            ):  # This means the field was found AND it had a non-empty value
                station_metadata_to_update = session.get(
                    models.StationMetadata, offloaded_station_id
                )
                if station_metadata_to_update:
                    station_metadata_to_update.last_offload_by_glider = (
                        mission_id  # The glider performing the offload
                    )
                    station_metadata_to_update.last_offload_timestamp_utc = (
                        submission_ts  # Timestamp of this form submission
                    )
                    session.add(station_metadata_to_update)
                    session.commit()
                    session.refresh(station_metadata_to_update)
                    logger.info(
                        f"Updated StationMetadata for '{offloaded_station_id}' "
                        f"with last offload by '{mission_id}' at "
                        f"{submission_ts.isoformat()}"
                    )
                else:
                    logger.warning(
                        f"WG-VM4 offload log for station "
                        f"'{offloaded_station_id}', but no matching "
                        f"StationMetadata found."
                    )
            elif (
                found_station_id_field_in_payload
            ):  # Field found, but value was empty/None
                logger.warning(
                    f"WG-VM4 offload log for mission '{mission_id}', but "
                    f"'station_id_for_offload' field had empty value."
                )
            else:  # "station_id_for_offload" field not found in payload
                logger.warning(
                    f"WG-VM4 offload log for mission '{mission_id}', but "
                    f"'station_id_for_offload' field was missing."
                )
    else:
        logger.warning(
            f"Unknown forms_storage_mode: {settings.forms_storage_mode}. Form not saved."
        )

    return form_response


@app.get("/api/forms/all", response_model=List[models.SubmittedForm])
async def get_all_submitted_forms(
    session: SQLModelSession = Depends(get_db_session),
    current_user: models.User = Depends(
        get_current_active_user
    ),  # Changed to active_user
):
    """
    Retrieves submitted forms from the database.
    Admins get all forms. Pilots get forms from the last 72 hours.
    Forms are ordered by submission_timestamp descending.
    """
    logger.info(
        f"User '{current_user.username}' (role: {current_user.role.value}) "
        f"requesting submitted forms."
    )

    statement = select(models.SubmittedForm)

    if current_user.role == models.UserRoleEnum.pilot:
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=72)
        statement = statement.where(
            models.SubmittedForm.submission_timestamp > cutoff_time
        )
        logger.info(
            f"Pilot user: Filtering forms submitted after "
            f"{cutoff_time.strftime('%Y-%m-%d %H:%M:%S UTC')}."
        )

    # For both admin and pilot, order by most recent first
    statement = statement.order_by(models.SubmittedForm.submission_timestamp.desc())

    forms = session.exec(statement).all()

    logger.info(
        f"Returning {len(forms)} forms for user '{current_user.username}' "
        f"(role: {current_user.role.value})."
    )

    return forms

@app.get("/api/forms/id/{form_db_id}", response_model=models.SubmittedForm)
async def get_submitted_form_by_id(
    form_db_id: int,
    session: SQLModelSession = Depends(get_db_session),
    current_user: models.User = Depends(get_current_active_user)
):
    logger.info(f"User '{current_user.username}' requesting submitted form with DB ID: {form_db_id}")
    db_form = session.get(models.SubmittedForm, form_db_id)
    if not db_form:
        raise HTTPException(status_code=404, detail="Form not found")
    # Add any role-based access control if necessary, e.g., pilots can only see recent forms
    # For now, any authenticated user can fetch by ID if they know it.
    return db_form

@app.get("/api/forms/pic_handoffs/my", response_model=List[models.SubmittedForm])
async def get_my_pic_handoff_submissions(
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session)
):
    logger.info(f"User '{current_user.username}' requesting their PIC Handoff submissions.")
    statement = select(models.SubmittedForm).where(
        models.SubmittedForm.form_type == "pic_handoff_checklist",
        models.SubmittedForm.submitted_by_username == current_user.username
    ).order_by(models.SubmittedForm.submission_timestamp.desc())
    forms = session.exec(statement).all()
    logger.info(f"Returning {len(forms)} PIC Handoff forms for user '{current_user.username}'.")
    return forms

@app.get("/api/forms/pic_handoffs/recent", response_model=List[models.SubmittedForm])
async def get_recent_pic_handoff_submissions(
    current_user: models.User = Depends(get_current_active_user), # Still require auth to view any
    session: SQLModelSession = Depends(get_db_session)
):
    logger.info(f"User '{current_user.username}' requesting recent PIC Handoff submissions (last 24h).")
    twenty_four_hours_ago = datetime.now(timezone.utc) - timedelta(hours=24)
    statement = select(models.SubmittedForm).where(
        models.SubmittedForm.form_type == "pic_handoff_checklist",
        models.SubmittedForm.submission_timestamp >= twenty_four_hours_ago
    ).order_by(models.SubmittedForm.submission_timestamp.desc())
    forms = session.exec(statement).all()
    logger.info(f"Returning {len(forms)} recent PIC Handoff forms.")
    return forms

# --- Schedule ---

@app.get("/schedule.html", response_class=HTMLResponse)
async def read_schedule_page(
    request: Request, # Allow optional user
    current_user: Annotated[Optional[models.User], Depends(get_optional_current_user)]
):
    """
    Serves the daily shift schedule page.
    """
    if current_user:
        logger.info(f"User '{current_user.username}' accessing schedule page.")
    else:
        # If no user, redirect to login. Schedule page requires authentication.
        # The JS checkAuth() also handles this, but adding a server-side check
        # prevents rendering the page content for unauthenticated users.
        # Note: This requires get_optional_current_user to be called first.
        if not current_user:
             logger.info("Anonymous user attempted to access schedule page. Redirecting to login.")
             # You could add a redirect here, but the client-side checkAuth() is often sufficient
             # for simple cases and avoids needing to pass the request object to the dependency.
             # Let's rely on client-side checkAuth for now, as it's already implemented.
             pass # Rely on client-side checkAuth()

        logger.info("Anonymous user accessing schedule page (relying on client-side auth check).")

    # For now, the page is static. Future enhancements might pass dynamic schedule data.
    return templates.TemplateResponse(
        "schedule.html",
        {"request": request, "current_user": current_user}, # Removed show_mission_selector
    )  # Pass current_user

@app.get("/api/schedule/events", response_model=List[models.ScheduleEvent])
async def get_schedule_events_api(
    start_date: Optional[datetime] = Query(None, alias="start"), # Accept start date
    end_date: Optional[datetime] = Query(None, alias="end"),     # Accept end date

    current_user: models.User = Depends(get_current_active_user), # Ensure user is authenticated
    # session: SQLModelSession = Depends(get_db_session) # Already injected by get_current_active_user
    session: SQLModelSession = Depends(get_db_session)
):
    """
    API endpoint to provide events for the DayPilot Scheduler.
    """
    logger.info(f"User '{current_user.username}' requesting schedule events.")
    if start_date and end_date:
        # Ensure dates are timezone-aware (assume UTC if naive, or convert if already aware)
        if start_date.tzinfo is None:
            start_date = start_date.replace(tzinfo=timezone.utc)
        if end_date.tzinfo is None:
            end_date = end_date.replace(tzinfo=timezone.utc)
        logger.info(f"Fetching events for range: {start_date.isoformat()} to {end_date.isoformat()}")
        statement = select(models.ShiftAssignment).where(
            models.ShiftAssignment.start_time_utc < end_date, # Events that start before the query range ends
            models.ShiftAssignment.end_time_utc > start_date    # Events that end after the query range starts
        )
    else:
        now = datetime.now(timezone.utc)
        # Default to a wide range if not specified, e.g., this month +/- 1 month
        # Or rely on client to always send a range. For now, let's fetch all if no range.
        logger.info(f"No date range provided, fetching all events (or implement a default server-side range).")
        statement = select(models.ShiftAssignment)

    db_assignments = session.exec(statement).all() # Fetch shifts

    # Fetch unavailability events for the same range
    unavailability_statement = select(models.UserUnavailability)
    if start_date and end_date:
        unavailability_statement = unavailability_statement.where(
            models.UserUnavailability.start_time_utc < end_date,
            models.UserUnavailability.end_time_utc > start_date
        )
    db_unavailabilities = session.exec(unavailability_statement).all()

    response_events = []

    # Process Shift Assignments
    lri_pilot_user = auth_utils.get_user_from_db(session, "LRI_PILOT") # Fetch LRI_PILOT once
    for assignment in db_assignments:
        # Fetch the user to get the username for the event text
        user = session.get(models.UserInDB, assignment.user_id)
        username_display = user.username if user else "Unknown User"
        user_color = user.color if user and user.color else "#DDDDDD" # Default grey if no color assigned

        # Determine if the current user can edit this shift
        is_editable = (current_user.id == user.id) if user else False
        # Admins can edit/delete any shift
        event_group_id = None # Initialize groupId

        event_type = "shift"
        display_type = "auto"
        all_day = False
        event_text = username_display
        event_back_color = user_color

        if lri_pilot_user and assignment.user_id == lri_pilot_user.id:
            event_type = "lri_block"
            event_text = "LRI Block"
            event_back_color = lri_pilot_user.color # Use LRI's specific color
            display_type = "block" # Display as a solid block
            all_day = False # Treat as a timed event to show in the main grid
            is_editable = current_user.role == models.UserRoleEnum.admin # Only admin can edit/delete LRI blocks
            event_group_id = str(lri_pilot_user.id) # Group all LRI blocks
        else:
            # For regular shifts, admins can edit/delete any
            if current_user.role == models.UserRoleEnum.admin:
                is_editable = True
            # Group regular shifts by the user who owns them
            if user:
                event_group_id = str(user.id)

        # Allow shifts and LRI blocks to visually overlap/merge
        event_overlap = False
        if event_type in ["shift", "lri_block"]:
            event_overlap = True

        response_events.append(
            models.ScheduleEvent(
                id=str(assignment.id),
                text=event_text,
                start=assignment.start_time_utc, # Already a UTC datetime, just pass it
                end=assignment.end_time_utc,     # Already a UTC datetime, pass it as is
                resource=assignment.resource_id,
                backColor=event_back_color,
                type=event_type,
                editable=is_editable,
                startEditable=False,
                durationEditable=False,
                resourceEditable=False,
                overlap=event_overlap,
                groupId=event_group_id,
                display=display_type,
                allDay=all_day,
                user_role=user.role if user else None, # This needs to be False to show in main container
                user_color=user_color
            )
        )
    
    # Process Canadian Holidays
    holidays = _get_canadian_holidays(start_date.date(), end_date.date())
    for holiday_date, holiday_name in holidays:
        response_events.append(
            models.ScheduleEvent(
                id=f"holiday-{holiday_date.strftime('%Y%m%d')}", # Unique ID for holiday
                text=f"Holiday: {holiday_name}",
                start=datetime.combine(holiday_date, datetime.min.time(), tzinfo=timezone.utc),
                end=datetime.combine(holiday_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc),
                resource="", # No specific resource
                backColor="#D3D3D3", # Light grey for holidays
                type="holiday",
                editable=False, # Holidays are not editable
                startEditable=False,
                durationEditable=False,
                resourceEditable=False,
                overlap=False,
                groupId=None, # Holidays don't need grouping
                display="background", # Display as a background event
                allDay=False, # Mark as a timed event to show in main container
                user_role=None,
                user_color="#D3D3D3"
            )
        )
    
    # Process User Unavailabilities
    for unavailability in db_unavailabilities:
        user = session.get(models.UserInDB, unavailability.user_id)
        username_display = user.username if user else "Unknown User"
        # Use distinct colors for unavailability based on role
        unavailability_color = "#FFD700" if user and user.role == models.UserRoleEnum.admin else "#808080" # Gold for Admin, Grey for Pilot
        
        # Determine if the current user can edit this unavailability
        is_editable = (current_user.id == user.id) if user else False
        if current_user.role == models.UserRoleEnum.admin:
            is_editable = True

        response_events.append(
            models.ScheduleEvent(
                id=f"unavail-{unavailability.id}", # Prefix to distinguish from shifts
                text=f"UNAVAILABLE: {username_display} ({unavailability.reason or 'No Reason'})",
                start=unavailability.start_time_utc,
                end=unavailability.end_time_utc,
                resource="", # Unavailability doesn't belong to a specific slot resource
                backColor=unavailability_color,
                type="unavailability", # Explicitly mark as unavailability
                editable=is_editable, # Only owner or admin can edit/delete
                startEditable=False, # Not draggable
                durationEditable=False, # Not resizable
                resourceEditable=False, # Not movable
                overlap=False, # Unavailability should not overlap with shifts (handled by logic)
                groupId=str(user.id) if user else None, # Group unavailability by user
                display="block", # Display as a solid block event
                allDay=True, # Mark as an all-day event
                user_role=user.role if user else None,
                user_color=unavailability_color
            )
        )
    logger.info(f"Returning {len(response_events)} events from database.")
    return response_events


@app.post("/api/schedule/shifts", response_model=models.ScheduleEvent, status_code=status.HTTP_201_CREATED)
async def create_schedule_event_api(
    event_in: models.ScheduleEventCreate, # Use the new model from models.py
    current_user: models.User = Depends(get_current_active_user), # This is for regular shifts
    session: SQLModelSession = Depends(get_db_session)
):
    logger.info(f"User '{current_user.username}' creating event. Client data: {event_in}")

    final_start_dt: datetime
    final_end_dt: datetime
    final_resource_id: str = event_in.resource 

    if event_in.resource.startswith("SLOT_"):
        # Spreadsheet-like view: event_in.start is the day, resource is the slot
        try:
            day_date_str = event_in.start.split("T")[0] # "YYYY-MM-DD"
            day_dt = datetime.fromisoformat(day_date_str).replace(tzinfo=timezone.utc)

            slot_parts = event_in.resource.split("_") # SLOT_HH_MM (DayPilot uses MM for month, not minutes here)
            start_hour = int(slot_parts[1])
            # The second part of the slot ID is the *end* hour of the slot, which is the start of the next slot.
            # For a 3-hour slot starting at start_hour:
            end_hour_calc = (start_hour + 3) % 24 

            final_start_dt = day_dt.replace(hour=start_hour, minute=0, second=0, microsecond=0)
            
            # Calculate end_dt based on 3-hour duration
            final_end_dt = final_start_dt + timedelta(hours=3)

        except (IndexError, ValueError) as e:
            logger.error(f"Error parsing SLOT resource ID '{event_in.resource}' or date '{event_in.start}': {e}")
            raise HTTPException(status_code=400, detail="Invalid slot or date format from client.")
    else: # Existing views (Weekly Hourly, Daily Hourly, Monthly Daily)
        final_start_dt = datetime.fromisoformat(event_in.start.replace("Z", "+00:00"))
        final_end_dt = datetime.fromisoformat(event_in.end.replace("Z", "+00:00"))

        logger.info(f"create_schedule_event_api - Received slot: start={final_start_dt.isoformat()}, end={final_end_dt.isoformat()}");

    # --- Basic Validation ---
    duration_hours = (final_end_dt - final_start_dt).total_seconds() / 3600
    
    # The frontend's getSlotForTime function is the source of truth for valid slots.
    # We just validate that it's a 3-hour block starting on the hour.
    if not (abs(duration_hours - 3) < 0.01 and final_start_dt.minute == 0 and final_start_dt.second == 0):
        logger.warning(f"Invalid shift slot attempted: Start time must be on the hour and duration must be 3 hours. Received start: {final_start_dt}, end: {final_end_dt}")
        raise HTTPException(status_code=400, detail="Invalid shift slot. Must be a 3-hour block starting on a designated hour.")

    # Fetch the UserInDB instance to get the user's database ID
    user_in_db = auth_utils.get_user_from_db(session, current_user.username)
    if not user_in_db:
        # This should ideally not happen if get_current_active_user succeeded
        logger.error(f"Consistency error: User '{current_user.username}' found by token but not in DB for event creation.")
        raise HTTPException(status_code=500, detail="User not found in database.")

    # Check for overlaps
    overlap_statement = select(models.ShiftAssignment).where(
        models.ShiftAssignment.resource_id == final_resource_id, # Use final_resource_id
        models.ShiftAssignment.start_time_utc < final_end_dt,   # Use final_end_dt
        models.ShiftAssignment.end_time_utc > final_start_dt     # Use final_start_dt
    )
    existing_assignment = session.exec(overlap_statement).first() # This now correctly checks for overlaps with LRI blocks too
    if existing_assignment:
        logger.warning(f"Overlap detected for resource {final_resource_id} at {final_start_dt}")
        raise HTTPException(status_code=409, detail="This shift slot is already taken.")

    db_assignment = models.ShiftAssignment(
        user_id=user_in_db.id, # Use user_in_db.id
        start_time_utc=final_start_dt,
        end_time_utc=final_end_dt,
        resource_id=final_resource_id,
        # event_text=current_user.username # Optionally store username directly
    )
    session.add(db_assignment)
    session.commit()
    session.refresh(db_assignment)
    logger.info(f"ShiftAssignment created with ID {db_assignment.id} for user {current_user.username}")
    user_assigned_color = user_in_db.color if user_in_db and user_in_db.color else "#DDDDDD"

    return models.ScheduleEvent(
        id=str(db_assignment.id),
        text=current_user.username, # For display
        start=db_assignment.start_time_utc,
        end=db_assignment.end_time_utc,
        resource=db_assignment.resource_id, # This is the ISO string of the start time
        groupId=str(user_in_db.id), # Group regular shifts by user ID for potential merging
        backColor=user_assigned_color # Return the color for immediate display
    )
    # The return models.ScheduleEvent(**response_event_data) was a leftover from previous version, removed.

@app.post("/api/schedule/lri_blocks", response_model=List[models.ScheduleEvent], status_code=status.HTTP_201_CREATED)
async def create_lri_blocks_api(
    block_in: models.LRIBlockCreate, # New model for LRI block creation
    current_admin: models.User = Depends(get_current_admin_user), # Only admins can create LRI blocks
    session: SQLModelSession = Depends(get_db_session)
):
    logger.info(f"Admin '{current_admin.username}' creating LRI blocks from {block_in.start_date} to {block_in.end_date}.")

    lri_pilot_user = auth_utils.get_user_from_db(session, "LRI_PILOT")
    if not lri_pilot_user:
        raise HTTPException(status_code=500, detail="LRI_PILOT user not found in database. Please ensure it's initialized.")

    created_events = []
    current_date = block_in.start_date
    
    # Valid UTC start hours corresponding to local 23:00, 02:00, 05:00, etc. assuming ADT (UTC-3)
    valid_start_hours_utc = [2, 5, 8, 11, 14, 17, 20, 23]

    while current_date <= block_in.end_date:
        # Determine if it's a weekday or weekend
        is_weekday = current_date.weekday() < 5 # Monday is 0, Friday is 4

        # Get Canadian holidays for the current year
        holidays_for_year = {h[0] for h in _get_canadian_holidays(current_date, current_date)} # Just need the date part
        is_holiday = current_date in holidays_for_year

        hours_to_block = []
        if is_weekday and not is_holiday:
            # Weekdays: 23:00 - 11:00 local time
            # Assuming ADT (UTC-3):
            # 23:00 local -> 02:00 UTC (next day)
            # 02:00 local -> 05:00 UTC
            # 05:00 local -> 08:00 UTC
            # 08:00 local -> 11:00 UTC
            hours_to_block = [2, 5, 8, 11] # UTC hours
        elif not is_weekday or is_holiday: # Weekends or Holidays
            # All shifts
            hours_to_block = valid_start_hours_utc # All 3-hour UTC blocks
        
        for hour_utc in hours_to_block:
            # Construct UTC datetime for the start of the shift
            shift_start_utc = datetime.combine(current_date, datetime.min.time(), tzinfo=timezone.utc).replace(hour=hour_utc)
            shift_end_utc = shift_start_utc + timedelta(hours=3)

            # Check for overlaps before creating
            overlap_statement = select(models.ShiftAssignment).where(
                models.ShiftAssignment.resource_id == shift_start_utc.isoformat(), # Use ISO string as resource ID
                models.ShiftAssignment.start_time_utc < shift_end_utc,
                models.ShiftAssignment.end_time_utc > shift_start_utc
            )
            existing_assignment = session.exec(overlap_statement).first()
            if existing_assignment:
                logger.warning(f"Skipping LRI block for {shift_start_utc.isoformat()} due to existing assignment.")
                continue # Skip this slot if already taken

            db_assignment = models.ShiftAssignment(
                user_id=lri_pilot_user.id,
                start_time_utc=shift_start_utc,
                end_time_utc=shift_end_utc,
                resource_id=shift_start_utc.isoformat(), # Use ISO string as resource ID
            )
            session.add(db_assignment)
            session.commit()
            session.refresh(db_assignment)
            logger.info(f"LRI ShiftAssignment created with ID {db_assignment.id} for {shift_start_utc.isoformat()}")
            
            created_events.append(
                models.ScheduleEvent(
                    id=str(db_assignment.id),
                    text="LRI Block",
                    start=db_assignment.start_time_utc,
                    end=db_assignment.end_time_utc,
                    resource=db_assignment.resource_id,
                    backColor=lri_pilot_user.color,
                    type="lri_block",
                    editable=True, # Admin can delete
                    startEditable=False,
                    durationEditable=False,
                    resourceEditable=False,
                    overlap=False,
                    groupId=str(lri_pilot_user.id), # Group all LRI blocks
                    display="block",
                    allDay=False,
                    user_role=lri_pilot_user.role,
                    user_color=lri_pilot_user.color
                )
            )
        current_date += timedelta(days=1)
    
    return created_events

@app.delete("/api/schedule/lri_blocks/{shift_assignment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lri_block_api(
    shift_assignment_id: int,
    current_admin: models.User = Depends(get_current_admin_user), # Only admins can delete LRI blocks
    session: SQLModelSession = Depends(get_db_session)
):
    logger.info(f"Admin '{current_admin.username}' attempting to delete LRI block ID: {shift_assignment_id}")
    
    lri_pilot_user = auth_utils.get_user_from_db(session, "LRI_PILOT")
    if not lri_pilot_user:
        raise HTTPException(status_code=500, detail="LRI_PILOT user not found.")

    db_assignment = session.get(models.ShiftAssignment, shift_assignment_id)
    if not db_assignment:
        raise HTTPException(status_code=404, detail="LRI block not found.")

    # Ensure it's actually an LRI block before deleting
    if db_assignment.user_id != lri_pilot_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this shift (not an LRI block).")

    session.delete(db_assignment)
    session.commit()
    logger.info(f"LRI block ID {shift_assignment_id} deleted successfully.")
    return

@app.post("/api/schedule/unavailability", response_model=models.UserUnavailabilityResponse, status_code=status.HTTP_201_CREATED)
async def create_unavailability_api(
    unavailability_in: models.UserUnavailabilityCreate,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session)
):
    logger.info(f"User '{current_user.username}' creating unavailability: {unavailability_in}")

    # Fetch the UserInDB instance to get the user's database ID
    user_in_db = auth_utils.get_user_from_db(session, current_user.username)
    if not user_in_db:
        raise HTTPException(status_code=500, detail="User not found in database.")

    # Basic validation: end date must not be before start date.
    if unavailability_in.start_time_utc > unavailability_in.end_time_utc:
        raise HTTPException(status_code=400, detail="End date cannot be before start date.")

    # Adjust end date to be exclusive for full-day events.
    # The user selects the last day they are unavailable. We add one day to make the range correct.
    exclusive_end_time = unavailability_in.end_time_utc + timedelta(days=1)

    # Check for overlaps with existing shifts for the current user
    overlap_statement = select(models.ShiftAssignment).where(
        models.ShiftAssignment.user_id == user_in_db.id,
        models.ShiftAssignment.start_time_utc < exclusive_end_time,
        models.ShiftAssignment.end_time_utc > unavailability_in.start_time_utc
    )
    existing_shift_overlap = session.exec(overlap_statement).first()
    if existing_shift_overlap:
        raise HTTPException(status_code=409, detail="Cannot block out time that overlaps with your existing shifts.")

    db_unavailability = models.UserUnavailability(
        user_id=user_in_db.id,
        start_time_utc=unavailability_in.start_time_utc,
        end_time_utc=exclusive_end_time, # Store the exclusive end time
        reason=unavailability_in.reason,
    )
    session.add(db_unavailability)
    session.commit()
    session.refresh(db_unavailability)
    logger.info(f"UserUnavailability created with ID {db_unavailability.id} for user {current_user.username}")

    return models.UserUnavailabilityResponse(
        id=db_unavailability.id,
        user_id=db_unavailability.user_id,
        username=current_user.username,
        user_role=current_user.role,
        user_color=user_in_db.color,
        start_time_utc=db_unavailability.start_time_utc,
        end_time_utc=db_unavailability.end_time_utc,
        reason=db_unavailability.reason,
        created_at_utc=db_unavailability.created_at_utc
    )

@app.delete("/api/schedule/unavailability/{unavailability_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_unavailability_api(
    unavailability_id: int,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session)
):
    logger.info(f"User '{current_user.username}' attempting to delete unavailability ID: {unavailability_id}")
    db_unavailability = session.get(models.UserUnavailability, unavailability_id)
    if not db_unavailability:
        raise HTTPException(status_code=404, detail="Unavailability entry not found.")

    # Authorization: Only the owner or an admin can delete
    if db_unavailability.user_id != current_user.id and current_user.role != models.UserRoleEnum.admin:
        raise HTTPException(status_code=403, detail="Not authorized to delete this unavailability entry.")

    session.delete(db_unavailability)
    session.commit()
    logger.info(f"Unavailability ID {unavailability_id} deleted successfully.")
    return


@app.delete("/api/schedule/clear_range", status_code=status.HTTP_204_NO_CONTENT)
async def clear_range_api(
    start_date: date = Query(...),
    end_date: date = Query(...),
    current_admin: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session)
):
    """
    Admin-only endpoint to clear all shifts, LRI blocks, and unavailability
    entries that overlap with the specified date range.
    """
    logger.info(f"Admin '{current_admin.username}' attempting to clear all shifts and blocks from {start_date} to {end_date}")

    start_of_range_utc = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
    end_of_range_utc = datetime.combine(end_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)

    # Delete ShiftAssignments (any shift that overlaps with the target day)
    shift_delete_statement = delete(models.ShiftAssignment).where(
        models.ShiftAssignment.start_time_utc < end_of_range_utc,
        models.ShiftAssignment.end_time_utc > start_of_range_utc
    )
    shifts_deleted_result = session.exec(shift_delete_statement)
    shifts_deleted_count = shifts_deleted_result.rowcount
    logger.info(f"Deleted {shifts_deleted_count} shift assignments for range {start_date} to {end_date}.")

    # Delete UserUnavailabilities (any unavailability that overlaps with the target day)
    unavailability_delete_statement = delete(models.UserUnavailability).where(
        models.UserUnavailability.start_time_utc < end_of_range_utc,
        models.UserUnavailability.end_time_utc > start_of_range_utc
    )
    unavailabilities_deleted_result = session.exec(unavailability_delete_statement)
    unavailabilities_deleted_count = unavailabilities_deleted_result.rowcount
    logger.info(f"Deleted {unavailabilities_deleted_count} unavailability entries for range {start_date} to {end_date}.")

    session.commit()
    return

@app.get("/api/schedule/events/{shift_assignment_id}/pic_handoffs", response_model=List[models.PicHandoffLinkInfo])
async def get_pic_handoffs_for_shift(
    shift_assignment_id: int,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session)
):
    logger.info(f"User '{current_user.username}' requesting PIC Handoffs for shift ID {shift_assignment_id}.")

    shift_assignment = session.get(models.ShiftAssignment, shift_assignment_id)
    if not shift_assignment:
        raise HTTPException(status_code=404, detail="Shift assignment not found.")
    
    logger.info(f"Shift ID {shift_assignment_id} details: StartUTC='{shift_assignment.start_time_utc.isoformat()}', EndUTC='{shift_assignment.end_time_utc.isoformat()}'")

    # Query SubmittedForm table
    statement = select(models.SubmittedForm).where(
        models.SubmittedForm.form_type == "pic_handoff_checklist", # Specific form type
        models.SubmittedForm.submission_timestamp >= shift_assignment.start_time_utc,
        models.SubmittedForm.submission_timestamp <= shift_assignment.end_time_utc
    ).order_by(models.SubmittedForm.submission_timestamp.desc())

    # For debugging: Log all PIC Handoffs to check their timestamps and form_types
    all_pic_handoffs_debug_stmt = select(models.SubmittedForm).where(models.SubmittedForm.form_type == "pic_handoff_checklist").order_by(models.SubmittedForm.submission_timestamp.desc())
    all_pic_handoffs_in_db = session.exec(all_pic_handoffs_debug_stmt).all()
    logger.debug(f"Total 'pic_handoff_checklist' forms in DB: {len(all_pic_handoffs_in_db)}")
    for f_debug in all_pic_handoffs_in_db[:5]: # Log first 5 for brevity
        logger.debug(f"  Debug - Form ID: {f_debug.id}, Mission: {f_debug.mission_id}, Timestamp: {f_debug.submission_timestamp.isoformat()}, Type: {f_debug.form_type}")
        # Optional: Filter by submitted_by_username if it must match the shift's user
        # user_of_shift = session.get(models.UserInDB, shift_assignment.user_id)
        # if user_of_shift:
        #     statement = statement.where(models.SubmittedForm.submitted_by_username == user_of_shift.username)

    submitted_forms = session.exec(statement).all()
    logger.info(f"Query for shift {shift_assignment_id} (time range: {shift_assignment.start_time_utc.isoformat()} to {shift_assignment.end_time_utc.isoformat()}) found {len(submitted_forms)} matching 'pic_handoff_checklist' forms within the timeframe.")
    if not submitted_forms and all_pic_handoffs_in_db:
        logger.warning("No forms found for the specific shift time range, but 'pic_handoff_checklist' forms exist in general. Please verify timestamps and ensure they are UTC and overlap with the shift period.")


    handoff_links = []
    for form in submitted_forms:
        handoff_links.append(
            models.PicHandoffLinkInfo(
                form_db_id=form.id, # type: ignore
                mission_id=form.mission_id,
                form_title=form.form_title, # Or a static "PIC Handoff"
                submitted_by_username=form.submitted_by_username,
                submission_timestamp=form.submission_timestamp
            )
        )
    logger.info(f"Found {len(handoff_links)} PIC Handoff forms for shift {shift_assignment_id} across all missions.")
    return handoff_links

@app.get("/api/schedule/my-upcoming-shifts", response_model=List[UpcomingShift])
async def get_my_upcoming_shifts(
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session)
):
    """
    Gets the current user's upcoming shifts (next 5).
    """
    user_in_db = auth_utils.get_user_from_db(session, current_user.username)
    if not user_in_db:
        raise HTTPException(status_code=404, detail="Current user not found in database.")

    now_utc = datetime.now(timezone.utc)
    
    statement = select(
        models.ShiftAssignment.resource_id.label("mission_id"),
        models.ShiftAssignment.start_time_utc,
        models.ShiftAssignment.end_time_utc
    ).where(
        models.ShiftAssignment.user_id == user_in_db.id,
        models.ShiftAssignment.start_time_utc > now_utc
    ).order_by(models.ShiftAssignment.start_time_utc).limit(5)

    results = session.exec(statement).all()
    return [UpcomingShift.model_validate(row) for row in results]


@app.delete("/api/schedule/shifts/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule_event_api(
    event_id: str,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session)
):
    logger.info(f"User '{current_user.username}' attempting to delete event ID: {event_id}")
    
    # Handle Unavailability events first, as they have a prefixed ID
    if event_id.startswith("unavail-"):
        try:
            unavailability_id = int(event_id.split("-")[1])
            return await delete_unavailability_api(unavailability_id, current_user, session)
        except (ValueError, IndexError):
            raise HTTPException(status_code=400, detail="Invalid unavailability event ID format.")

    # Handle ShiftAssignment events (both regular shifts and LRI blocks)
    try:
        assignment_id = int(event_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid shift event ID format.")

    db_assignment = session.get(models.ShiftAssignment, assignment_id)

    if not db_assignment:
        logger.warning(f"Shift assignment ID {assignment_id} not found for deletion.")
        raise HTTPException(status_code=404, detail="Shift assignment not found.")

    # Authorization check
    is_admin = current_user.role == models.UserRoleEnum.admin
    
    # Fetch the UserInDB instance for the current user to get their DB ID
    user_in_db_for_auth = auth_utils.get_user_from_db(session, current_user.username)
    if not user_in_db_for_auth:
        logger.error(f"Consistency error: User '{current_user.username}' not found in DB for auth.")
        raise HTTPException(status_code=500, detail="User not found in database for authorization.")

    # Check if it's an LRI block
    lri_pilot_user = auth_utils.get_user_from_db(session, "LRI_PILOT")
    is_lri_block = lri_pilot_user and db_assignment.user_id == lri_pilot_user.id

    if is_lri_block:
        if not is_admin:
            logger.warning(f"Non-admin user '{current_user.username}' attempted to delete LRI block ID {assignment_id}.")
            raise HTTPException(status_code=403, detail="Only administrators can delete LRI blocks.")
        # Admin is allowed to proceed
    elif db_assignment.user_id != user_in_db_for_auth.id and not is_admin:
        # It's a regular shift, but user is not the owner and not an admin
        owner = session.get(models.UserInDB, db_assignment.user_id)
        owner_username = owner.username if owner else "unknown"
        logger.warning(f"User '{current_user.username}' not authorized to delete event ID {event_id} owned by '{owner_username}'.")
        raise HTTPException(status_code=403, detail="Not authorized to delete this event.")
    
    # If we reach here, the user is authorized to delete the shift assignment
    session.delete(db_assignment)
    session.commit()
    logger.info(f"Shift assignment ID {assignment_id} deleted successfully by '{current_user.username}'.")
    return


# --- Download Schedule Endpoint ---
@app.get("/api/schedule/download")
async def download_schedule_data(
    start_date: date, # FastAPI will parse YYYY-MM-DD to datetime.date
    end_date: date,
    format: str = Query(..., pattern="^(ics|csv)$"), 
    user_scope: str = Query("all_users", pattern="^(all_users|my_shifts)$"), # New parameter
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session)
):
    logger.info(f"User '{current_user.username}' requested schedule download. Format: {format}, Range: {start_date} to {end_date}, Scope: {user_scope}")
    
    if start_date > end_date:
        raise HTTPException(status_code=400, detail="Start date cannot be after end date.")

    # Convert date to datetime for querying (start of day for start_date, end of day for end_date)
    start_datetime_utc = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
    # Add 1 day to end_date to include the whole day, then take min.time()
    end_datetime_utc = datetime.combine(end_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)

    statement = select(models.ShiftAssignment).where(
        models.ShiftAssignment.start_time_utc >= start_datetime_utc,
        models.ShiftAssignment.start_time_utc < end_datetime_utc 
    )

    user_in_db_for_filter = None
    if user_scope == "my_shifts":
        user_in_db_for_filter = auth_utils.get_user_from_db(session, current_user.username)
        if not user_in_db_for_filter:
            logger.error(f"Could not find UserInDB for current_user {current_user.username} when filtering for 'my_shifts'. This should not happen if user is authenticated.")
            # This case is unlikely if get_current_active_user works, but as a safeguard:
            raise HTTPException(status_code=404, detail="Current user details not found for filtering.")
        statement = statement.where(models.ShiftAssignment.user_id == user_in_db_for_filter.id)

    statement = statement.order_by(models.ShiftAssignment.start_time_utc)

    db_assignments = session.exec(statement).all()

    # Fetch user details for all assignments efficiently
    # This is still useful even for "my_shifts" if we want to display the username, or for "all_users"
    user_ids = {assign.user_id for assign in db_assignments}
    users_map = {}
    if user_ids:
        users_stmt = select(models.UserInDB).where(models.UserInDB.id.in_(user_ids))
        db_users = session.exec(users_stmt).all()
        users_map = {user.id: user for user in db_users}

    filename_suffix = ""
    if user_scope == "my_shifts" and user_in_db_for_filter:
        filename_suffix = f"_{user_in_db_for_filter.username.replace(' ', '_')}"
    filename_base = f"schedule_{start_date.strftime('%Y%m%d')}_to_{end_date.strftime('%Y%m%d')}{filename_suffix}"

    if format == "ics":
        cal = ics.Calendar()
        for assignment in db_assignments:
            user = users_map.get(assignment.user_id)
            username = user.username if user else "Unknown User"
            
            slot_name_display = assignment.resource_id 
            if assignment.resource_id.startswith("SLOT_"):
                try:
                    parts = assignment.resource_id.split("_") 
                    slot_start_hour = int(parts[1])
                    slot_end_hour = (slot_start_hour + 3) % 24 
                    slot_name_display = f"{slot_start_hour:02d}:00-{slot_end_hour:02d}:00"
                except (IndexError, ValueError):
                    pass # Keep original resource_id if parsing fails

            event_name = f"Shift: {username} ({slot_name_display})"
            
            ics_event = ics.Event()
            ics_event.name = event_name
            ics_event.begin = assignment.start_time_utc # Already UTC datetime
            ics_event.end = assignment.end_time_utc     # Already UTC datetime
            ics_event.description = f"Shift assigned to {username} for time slot {slot_name_display} on {assignment.start_time_utc.strftime('%Y-%m-%d')}."
            cal.events.add(ics_event)
        
        content = str(cal)
        media_type = "text/calendar"
        filename = f"{filename_base}.ics"

    elif format == "csv":
        output = io.StringIO()
        csv_writer = csv.writer(output)
        headers = ["Subject", "Start Date", "Start Time", "End Date", "End Time", "Assigned To", "Time Slot ID", "Description"]
        csv_writer.writerow(headers)

        for assignment in db_assignments:
            user = users_map.get(assignment.user_id)
            username = user.username if user else "Unknown User"
            slot_name_display = assignment.resource_id
            if assignment.resource_id.startswith("SLOT_"):
                try:
                    parts = assignment.resource_id.split("_")
                    slot_start_hour = int(parts[1]); slot_end_hour = (slot_start_hour + 3) % 24
                    slot_name_display = f"{slot_start_hour:02d}:00-{slot_end_hour:02d}:00"
                except: pass
            subject = f"Shift: {username} ({slot_name_display})"
            description = f"Shift for {username} covering time slot {slot_name_display} on {assignment.start_time_utc.strftime('%Y-%m-%d')}."
            csv_writer.writerow([subject, assignment.start_time_utc.strftime("%Y-%m-%d"), assignment.start_time_utc.strftime("%H:%M:%S UTC"), assignment.end_time_utc.strftime("%Y-%m-%d"), assignment.end_time_utc.strftime("%H:%M:%S UTC"), username, assignment.resource_id, description])
        content = output.getvalue()
        media_type = "text/csv"
        filename = f"{filename_base}.csv"
        output.close()
    else: # Should not be reached due to Query(pattern=...)
        raise HTTPException(status_code=400, detail="Invalid format specified.")

    return StreamingResponse(io.BytesIO(content.encode("utf-8")), media_type=media_type, headers={"Content-Disposition": f"attachment; filename=\"{filename}\""})

# --- Admin User Management API Endpoints ---

def _get_canadian_holidays(start_date: date, end_date: date) -> List[Tuple[date, str]]:
    """
    Returns a list of Canadian federal holidays within the given date range.
    Hardcoded for simplicity to avoid external API dependencies.
    """
    holidays = []
    # Common Federal Holidays (dates might shift slightly for some)
    # For 2025
    if start_date.year <= 2025 <= end_date.year:
        holidays.extend([
            (date(2025, 1, 1), "New Year's Day"),
            (date(2025, 4, 18), "Good Friday"),
            (date(2025, 5, 19), "Victoria Day"),
            (date(2025, 7, 1), "Canada Day"),
            (date(2025, 9, 1), "Labour Day"),
            (date(2025, 10, 13), "Thanksgiving Day"),
            (date(2025, 11, 11), "Remembrance Day"),
            (date(2025, 12, 25), "Christmas Day"),
            (date(2025, 12, 26), "Boxing Day"),
        ])
    # For 2026
    if start_date.year <= 2026 <= end_date.year:
        holidays.extend([
            (date(2026, 1, 1), "New Year's Day"),
            (date(2026, 4, 3), "Good Friday"),
            (date(2026, 5, 18), "Victoria Day"),
            (date(2026, 7, 1), "Canada Day"),
            (date(2026, 9, 7), "Labour Day"),
            (date(2026, 10, 12), "Thanksgiving Day"),
            (date(2026, 11, 11), "Remembrance Day"),
            (date(2026, 12, 25), "Christmas Day"),
            (date(2026, 12, 26), "Boxing Day"),
        ])
    # Add more years as needed

    # Filter holidays to only include those within the requested range
    filtered_holidays = [
        (h_date, h_name)
        for h_date, h_name in holidays
        if start_date <= h_date <= end_date
    ]
    return filtered_holidays


# --- Payroll and Timesheet Endpoints ---

@app.get("/api/pay_periods/open", response_model=List[models.PayPeriod])
async def get_open_pay_periods(
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session)
):
    """
    Get a list of pay periods that are currently open for submission, filtering out
    any periods for which the user already has an active 'submitted' or 'approved' timesheet.
    """
    # Get the current user's DB entry
    user_in_db = auth_utils.get_user_from_db(session, current_user.username)
    if not user_in_db:
        raise HTTPException(status_code=404, detail="Current user not found in database.")

    # Find pay periods for which the user has an active, non-rejected timesheet
    submitted_periods_stmt = select(models.Timesheet.pay_period_id).where(
        models.Timesheet.user_id == user_in_db.id,
        models.Timesheet.is_active == True,
        models.Timesheet.status.in_([models.TimesheetStatusEnum.SUBMITTED, models.TimesheetStatusEnum.APPROVED])
    )
    submitted_period_ids = session.exec(submitted_periods_stmt).all()

    # Fetch all open pay periods and filter out the ones already submitted.
    open_periods_stmt = select(models.PayPeriod).where(
        models.PayPeriod.status == models.PayPeriodStatusEnum.OPEN
    ).order_by(models.PayPeriod.start_date.desc())
    if submitted_period_ids:
        open_periods_stmt = open_periods_stmt.where(models.PayPeriod.id.notin_(submitted_period_ids))
    
    return session.exec(open_periods_stmt).all()

@app.get("/api/timesheets/calculate", response_model=dict)
async def calculate_timesheet_hours(
    pay_period_id: int,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session)
):
    """
    Calculates the total shift hours for the current user within a given pay period.
    """
    pay_period = session.get(models.PayPeriod, pay_period_id)
    if not pay_period:
        raise HTTPException(status_code=404, detail="Pay period not found.")

    user_in_db = auth_utils.get_user_from_db(session, current_user.username)
    if not user_in_db:
        raise HTTPException(status_code=404, detail="Current user not found in database.")

    start_datetime = datetime.combine(pay_period.start_date, datetime.min.time(), tzinfo=timezone.utc)
    end_datetime = datetime.combine(pay_period.end_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)

    shift_statement = select(models.ShiftAssignment).where(
        models.ShiftAssignment.user_id == user_in_db.id,
        models.ShiftAssignment.start_time_utc >= start_datetime,
        models.ShiftAssignment.end_time_utc < end_datetime
    )
    shifts = session.exec(shift_statement).all()

    total_hours = sum(
        (shift.end_time_utc - shift.start_time_utc).total_seconds() / 3600
        for shift in shifts
    )

    return {"calculated_hours": round(total_hours, 2)}

@app.post("/api/timesheets", response_model=models.Timesheet, status_code=status.HTTP_201_CREATED)
async def submit_timesheet(
    timesheet_in: models.TimesheetCreate,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session)
):
    """
    Submits a new, active timesheet for the current user for a specific pay period.
    If an active timesheet already exists (e.g., a rejected one), it will be
    deactivated, and this new submission will become the active one.
    """
    user_in_db = auth_utils.get_user_from_db(session, current_user.username)
    if not user_in_db:
        raise HTTPException(status_code=404, detail="Current user not found in database.")

    # Deactivate any previously active timesheet for this user and pay period
    existing_active_timesheet_stmt = select(models.Timesheet).where(
        models.Timesheet.user_id == user_in_db.id,
        models.Timesheet.pay_period_id == timesheet_in.pay_period_id,
        models.Timesheet.is_active == True
    )
    existing_active_timesheet = session.exec(existing_active_timesheet_stmt).first()

    if existing_active_timesheet:
        # If the existing active timesheet is approved or submitted, block resubmission.
        if existing_active_timesheet.status in [models.TimesheetStatusEnum.APPROVED, models.TimesheetStatusEnum.SUBMITTED]:
             raise HTTPException(status_code=409, detail="An active timesheet for this pay period is already submitted or approved.")
        
        # If it's rejected, we can proceed. Deactivate the old one.
        logger.info(f"Deactivating previous timesheet (ID: {existing_active_timesheet.id}) for user '{current_user.username}' for pay period {timesheet_in.pay_period_id}.")
        existing_active_timesheet.is_active = False
        session.add(existing_active_timesheet)

    # Create a new, active timesheet record.
    logger.info(f"User '{current_user.username}' submitting a new active timesheet for pay period {timesheet_in.pay_period_id}.")

    db_timesheet = models.Timesheet.model_validate(timesheet_in.model_dump() | {"user_id": user_in_db.id})
    session.add(db_timesheet)
    session.commit()
    session.refresh(db_timesheet)
    return db_timesheet

@app.get("/api/timesheets/my_submissions", response_model=List[models.TimesheetRead])
async def get_my_timesheet_submissions(
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session)
):
    """
    Gets all of the current user's timesheet submissions (active and inactive),
    ordered by pay period and then by submission date.
    """
    user_in_db = auth_utils.get_user_from_db(session, current_user.username)
    if not user_in_db:
        raise HTTPException(status_code=404, detail="Current user not found in database.")

    # Join Timesheet with PayPeriod to order by pay period start date
    statement = select(models.Timesheet, models.PayPeriod).join(models.PayPeriod).where(
        models.Timesheet.user_id == user_in_db.id
    ).order_by(
        models.PayPeriod.start_date.desc(), 
        models.Timesheet.submission_timestamp.desc()
    )
    
    results = session.exec(statement).all()
    return [models.TimesheetRead.model_validate(ts.model_dump() | {"username": user_in_db.username, "pay_period_name": pp.name}) for ts, pp in results]

@app.get("/api/timesheets/my-timesheet-status", response_model=MyTimesheetStatus)
async def get_my_timesheet_status_for_home_panel(
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session)
):
    """
    Gets a summary of the user's timesheet status for the current/most recent pay period.
    """
    user_in_db = auth_utils.get_user_from_db(session, current_user.username)
    if not user_in_db:
        raise HTTPException(status_code=404, detail="Current user not found in database.")

    # Find the most recent pay period that is currently open
    now = date.today()
    current_pay_period = session.exec(
        select(models.PayPeriod)
        .where(models.PayPeriod.start_date <= now, models.PayPeriod.end_date >= now, models.PayPeriod.status == models.PayPeriodStatusEnum.OPEN)
        .order_by(models.PayPeriod.start_date.desc())
    ).first()

    if not current_pay_period:
        return MyTimesheetStatus(current_period_status="No Open Period", hours_this_period=0.0)

    # Check the user's timesheet status for this period
    timesheet_status = "Not Submitted"
    active_timesheet = session.exec(
        select(models.Timesheet).where(
            models.Timesheet.user_id == user_in_db.id,
            models.Timesheet.pay_period_id == current_pay_period.id,
            models.Timesheet.is_active == True
        )
    ).first()

    if active_timesheet:
        timesheet_status = active_timesheet.status.value.capitalize()

    # Calculate hours logged in this period
    start_datetime = datetime.combine(current_pay_period.start_date, datetime.min.time(), tzinfo=timezone.utc)
    end_datetime = datetime.combine(current_pay_period.end_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
    shifts = session.exec(select(models.ShiftAssignment).where(models.ShiftAssignment.user_id == user_in_db.id, models.ShiftAssignment.start_time_utc >= start_datetime, models.ShiftAssignment.end_time_utc < end_datetime)).all()
    total_hours = sum((shift.end_time_utc - shift.start_time_utc).total_seconds() / 3600 for shift in shifts)

    return MyTimesheetStatus(current_period_status=f"{current_pay_period.name}: {timesheet_status}", hours_this_period=total_hours)


@app.get("/api/admin/timesheets/{timesheet_id}/history", response_model=List[models.TimesheetRead])
async def admin_get_timesheet_history(
    timesheet_id: int,
    current_admin: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session)
):
    """
    Admin-only endpoint to retrieve the full submission history for a specific
    timesheet entry (i.e., all versions for that user and pay period).
    """
    # First, get the reference timesheet to find the user_id and pay_period_id
    ref_timesheet = session.get(models.Timesheet, timesheet_id)
    if not ref_timesheet:
        raise HTTPException(status_code=404, detail="Timesheet not found.")

    logger.info(f"Admin '{current_admin.username}' requesting history for timesheet ID {timesheet_id} (user_id: {ref_timesheet.user_id}, pay_period_id: {ref_timesheet.pay_period_id}).")

    # Now, query for all timesheets with the same user_id and pay_period_id
    history_stmt = select(models.Timesheet).where(
        models.Timesheet.user_id == ref_timesheet.user_id,
        models.Timesheet.pay_period_id == ref_timesheet.pay_period_id
    ).order_by(models.Timesheet.submission_timestamp.desc())
    
    history_timesheets = session.exec(history_stmt).all()

    user = session.get(models.UserInDB, ref_timesheet.user_id)
    pay_period = session.get(models.PayPeriod, ref_timesheet.pay_period_id)
    
    if not user or not pay_period:
        raise HTTPException(status_code=500, detail="Could not retrieve associated user or pay period.")

    return [models.TimesheetRead.model_validate(ts.model_dump() | {"username": user.username, "pay_period_name": pay_period.name}) for ts in history_timesheets]

@app.patch("/api/admin/timesheets/{timesheet_id}", response_model=models.Timesheet)
async def admin_update_timesheet_status(
    timesheet_id: int,
    timesheet_update: models.TimesheetUpdate,
    background_tasks: BackgroundTasks,
    current_admin: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session)
):
    """
    Admin-only endpoint to update the status and add reviewer notes to a timesheet.
    """
    logger.info(f"Admin '{current_admin.username}' attempting to update timesheet ID: {timesheet_id} with data: {timesheet_update.model_dump(exclude_unset=True)}")

    db_timesheet = session.get(models.Timesheet, timesheet_id)
    if not db_timesheet:
        raise HTTPException(status_code=404, detail="Timesheet not found.")

    update_data = timesheet_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_timesheet, key, value)
    
    # If status is being changed to APPROVED or REJECTED, ensure reviewer_notes are present
    if timesheet_update.status in [models.TimesheetStatusEnum.APPROVED, models.TimesheetStatusEnum.REJECTED] and not db_timesheet.reviewer_notes:
        raise HTTPException(status_code=400, detail="Reviewer notes are required when approving or rejecting a timesheet.")

    session.add(db_timesheet)
    session.commit()
    session.refresh(db_timesheet)

    # --- Send Email Notification on Status Change ---
    if timesheet_update.status in [models.TimesheetStatusEnum.APPROVED, models.TimesheetStatusEnum.REJECTED]:
        user_to_notify = session.get(models.UserInDB, db_timesheet.user_id)
        pay_period = session.get(models.PayPeriod, db_timesheet.pay_period_id)

        if user_to_notify and user_to_notify.email and pay_period:
            subject = f"Update on your timesheet for {pay_period.name}"
            
            email_context = {
                "user_name": user_to_notify.full_name or user_to_notify.username,
                "pay_period_name": pay_period.name,
                "status": db_timesheet.status.value,
                "reviewer_notes": db_timesheet.reviewer_notes,
                "is_approved": db_timesheet.status == models.TimesheetStatusEnum.APPROVED,
                "is_rejected": db_timesheet.status == models.TimesheetStatusEnum.REJECTED,
            }

            message = MessageSchema(
                subject=subject,
                recipients=[user_to_notify.email],
                template_body=email_context,
                subtype="html"
            )

            fm = FastMail(conf)
            background_tasks.add_task(fm.send_message, message, template_name="timesheet_status_update.html")
            logger.info(f"Queued email notification for user '{user_to_notify.username}' for timesheet ID {db_timesheet.id}.")
        elif not (user_to_notify and user_to_notify.email):
             logger.warning(f"Could not send email for timesheet {db_timesheet.id}: User '{user_to_notify.username if user_to_notify else 'N/A'}' does not have an email address configured.")

    return db_timesheet

# New model for the home page status panel
class TimesheetStatusForUser(SQLModel):
    pay_period_name: str
    status: models.TimesheetStatusEnum
    reviewer_notes: Optional[str] = None
    submission_timestamp: datetime

@app.get("/api/timesheets/my_status", response_model=List[TimesheetStatusForUser])
async def get_my_timesheet_statuses(
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session)
):
    """
    Gets the status of the current user's most recent *active* timesheet submission
    for each pay period they have submitted for.
    """
    user_in_db = auth_utils.get_user_from_db(session, current_user.username)
    if not user_in_db:
        raise HTTPException(status_code=404, detail="Current user not found in database.")

    # Get all *active* timesheets for the user, ordered by most recent submission
    timesheet_stmt = (
        select(models.Timesheet)
        .where(models.Timesheet.user_id == user_in_db.id, models.Timesheet.is_active == True)
        .order_by(models.Timesheet.submission_timestamp.desc())
    )
    active_timesheets = session.exec(timesheet_stmt).all()

    # To avoid N+1 queries, fetch the relevant pay periods and map them
    pay_period_ids = {ts.pay_period_id for ts in active_timesheets}
    pay_periods_map = {p.id: p for p in session.exec(select(models.PayPeriod).where(models.PayPeriod.id.in_(pay_period_ids))).all()} if pay_period_ids else {}

    response_list = []
    for ts in active_timesheets:
        pay_period = pay_periods_map.get(ts.pay_period_id)
        if pay_period:
            response_list.append(
                TimesheetStatusForUser(
                    pay_period_name=pay_period.name,
                    status=ts.status,
                    reviewer_notes=ts.reviewer_notes,
                    submission_timestamp=ts.submission_timestamp
                )
            )
    
    return response_list[:5] # Return the status for the 5 most recent pay periods

# --- Admin Payroll Endpoints ---

class PayPeriodUpdate(SQLModel):
    name: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    status: Optional[models.PayPeriodStatusEnum] = None

@app.get("/api/admin/pay_periods", response_model=List[models.PayPeriod])
async def admin_get_pay_periods(
    current_admin: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session)
):
    statement = select(models.PayPeriod).order_by(models.PayPeriod.start_date.desc())
    return session.exec(statement).all()

@app.post("/api/admin/pay_periods", response_model=models.PayPeriod, status_code=status.HTTP_201_CREATED)
async def admin_create_pay_period(
    pay_period_in: models.PayPeriodCreate,
    current_admin: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session)
):
    if pay_period_in.start_date > pay_period_in.end_date:
        raise HTTPException(status_code=400, detail="Start date cannot be after end date.")
    
    db_pay_period = models.PayPeriod.model_validate(pay_period_in)
    session.add(db_pay_period)
    session.commit()
    session.refresh(db_pay_period)
    return db_pay_period

@app.patch("/api/admin/pay_periods/{period_id}", response_model=models.PayPeriod)
async def admin_update_pay_period(
    period_id: int,
    pay_period_update: PayPeriodUpdate,
    current_admin: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session)
):
    db_pay_period = session.get(models.PayPeriod, period_id)
    if not db_pay_period:
        raise HTTPException(status_code=404, detail="Pay period not found.")

    update_data = pay_period_update.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No update data provided.")
    
    # Validate dates if they are being updated
    new_start = update_data.get("start_date", db_pay_period.start_date)
    new_end = update_data.get("end_date", db_pay_period.end_date)
    if new_start > new_end:
        raise HTTPException(status_code=400, detail="Start date cannot be after end date.")

    for key, value in update_data.items():
        setattr(db_pay_period, key, value)
    
    session.add(db_pay_period)
    session.commit()
    session.refresh(db_pay_period)
    return db_pay_period

@app.delete("/api/admin/pay_periods/{period_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_delete_pay_period(
    period_id: int,
    current_admin: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session)
):
    db_pay_period = session.get(models.PayPeriod, period_id)
    if not db_pay_period:
        raise HTTPException(status_code=404, detail="Pay period not found.")

    # Check for associated timesheets before deleting
    timesheet_check_stmt = select(models.Timesheet).where(models.Timesheet.pay_period_id == period_id).limit(1)
    if session.exec(timesheet_check_stmt).first():
        raise HTTPException(status_code=409, detail="Cannot delete pay period with submitted timesheets.")

    session.delete(db_pay_period)
    session.commit()
    return
@app.get("/api/admin/timesheets", response_model=List[models.TimesheetRead])
async def admin_get_timesheets(
    pay_period_id: int,
    current_admin: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session)
):
    """
    Retrieves all *active* submitted timesheets for a given pay period.
    """
    timesheet_stmt = select(models.Timesheet).where(
        models.Timesheet.pay_period_id == pay_period_id,
        models.Timesheet.is_active == True
    )
    timesheets = session.exec(timesheet_stmt).all()

    user_ids = {ts.user_id for ts in timesheets}
    users = {u.id: u for u in session.exec(select(models.UserInDB).where(models.UserInDB.id.in_(user_ids))).all()}
    
    pay_period = session.get(models.PayPeriod, pay_period_id)
    pay_period_name = pay_period.name if pay_period else "Unknown Period"

    response_data = []
    for ts in timesheets:
        user = users.get(ts.user_id)
        response_data.append(
            models.TimesheetRead(
                id=ts.id,
                user_id=ts.user_id,
                username=user.username if user else "Unknown",
                pay_period_id=ts.pay_period_id,
                pay_period_name=pay_period_name,
                calculated_hours=ts.calculated_hours,
                adjusted_hours=ts.adjusted_hours,
                notes=ts.notes,
                reviewer_notes=ts.reviewer_notes,
                status=ts.status,
                submission_timestamp=ts.submission_timestamp,
                is_active=ts.is_active
            )
        )
    return response_data

@app.get("/api/admin/reports/monthly_timesheet_summary", response_class=StreamingResponse)
async def get_monthly_timesheet_summary_report(
    year: int = Query(..., ge=2020, le=2100),
    month: int = Query(..., ge=1, le=12),
    current_admin: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session)
):
    """
    Admin-only endpoint to generate a CSV summary report of all active, approved
    timesheets for pay periods ending within a given month and year.
    """
    logger.info(f"Admin '{current_admin.username}' requesting monthly timesheet summary for {year}-{month:02d}.")

    try:
        start_of_month = date(year, month, 1)
        # calendar.monthrange(year, month) returns (weekday of first day, number of days in month)
        _, num_days = calendar.monthrange(year, month)
        end_of_month = date(year, month, num_days)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid year or month.")

    # Find pay periods that end within the selected month
    pay_periods_in_month_stmt = select(models.PayPeriod).where(
        models.PayPeriod.end_date >= start_of_month,
        models.PayPeriod.end_date <= end_of_month
    )
    pay_periods_in_month = session.exec(pay_periods_in_month_stmt).all()
    pay_period_ids = [pp.id for pp in pay_periods_in_month]

    # Find all active, approved timesheets for those pay periods
    approved_timesheets_stmt = select(models.Timesheet).where(
        models.Timesheet.pay_period_id.in_(pay_period_ids),
        models.Timesheet.status == models.TimesheetStatusEnum.APPROVED,
        models.Timesheet.is_active == True
    ).order_by(models.Timesheet.submission_timestamp)
    
    approved_timesheets = session.exec(approved_timesheets_stmt).all()

    # Eager load related data to prevent N+1 queries
    user_ids = {ts.user_id for ts in approved_timesheets}
    users_map = {u.id: u for u in session.exec(select(models.UserInDB).where(models.UserInDB.id.in_(user_ids))).all()} if user_ids else {}
    pay_periods_map = {pp.id: pp for pp in pay_periods_in_month}

    # Generate CSV
    output = io.StringIO()
    csv_writer = csv.writer(output)
    headers = [
        "Timesheet ID", "Pilot Username", "Full Name", "Pay Period Name", "Pay Period End Date",
        "Calculated Hours", "Adjusted Hours", "Final Approved Hours", "Status", "Submission Timestamp (UTC)", "Reviewer Notes"
    ]
    csv_writer.writerow(headers)

    total_hours = 0.0

    for ts in approved_timesheets:
        user = users_map.get(ts.user_id)
        pay_period = pay_periods_map.get(ts.pay_period_id)
        final_hours = ts.adjusted_hours if ts.adjusted_hours is not None else ts.calculated_hours
        total_hours += final_hours

        row = [ts.id, user.username if user else "Unknown", user.full_name if user else "Unknown", pay_period.name if pay_period else "Unknown", pay_period.end_date.isoformat() if pay_period else "Unknown", f"{ts.calculated_hours:.2f}", f"{ts.adjusted_hours:.2f}" if ts.adjusted_hours is not None else "", f"{final_hours:.2f}", ts.status.value, ts.submission_timestamp.isoformat(), ts.reviewer_notes or ""]
        csv_writer.writerow(row)
    
    # Add a summary row at the end
    csv_writer.writerow([]) # Blank row
    csv_writer.writerow(["", "", "", "", "", "", "Total Approved Hours:", f"{total_hours:.2f}"])

    output.seek(0)
    content = output.getvalue()
    filename = f"approved_timesheets_summary_{year}-{month:02d}.csv"
    return StreamingResponse(io.BytesIO(content.encode("utf-8")), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename=\"{filename}\""})

class MonthlyChartData(BaseModel):
    pilot_name: str
    total_hours: float

@app.get("/api/admin/reports/monthly_summary_chart", response_model=List[MonthlyChartData])
async def get_monthly_summary_chart_data(
    year: int = Query(..., ge=2020, le=2100),
    month: int = Query(..., ge=1, le=12),
    current_admin: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session)
):
    """
    Admin-only endpoint to generate data for a monthly summary chart of approved hours per pilot.
    """
    logger.info(f"Admin '{current_admin.username}' requesting monthly summary chart data for {year}-{month:02d}.")

    try:
        start_of_month = date(year, month, 1)
        _, num_days = calendar.monthrange(year, month)
        end_of_month = date(year, month, num_days)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid year or month.")

    pay_periods_in_month_stmt = select(models.PayPeriod.id).where(
        models.PayPeriod.end_date >= start_of_month,
        models.PayPeriod.end_date <= end_of_month
    )
    pay_period_ids = session.exec(pay_periods_in_month_stmt).all()

    if not pay_period_ids:
        return []

    final_hours_expression = case(
        (models.Timesheet.adjusted_hours.isnot(None), models.Timesheet.adjusted_hours),
        else_=models.Timesheet.calculated_hours
    )

    summary_stmt = (
        select(models.UserInDB.username, func.sum(final_hours_expression).label("total_hours"))
        .join(models.Timesheet, models.UserInDB.id == models.Timesheet.user_id)
        .where(
            models.Timesheet.pay_period_id.in_(pay_period_ids),
            models.Timesheet.status == models.TimesheetStatusEnum.APPROVED,
            models.Timesheet.is_active == True
        )
        .group_by(models.UserInDB.username)
        .order_by(func.sum(final_hours_expression).desc())
    )
    
    results = session.exec(summary_stmt).all()

    return [MonthlyChartData(pilot_name=username, total_hours=round(total_hours, 2)) for username, total_hours in results if total_hours is not None]

# --- Timesheet functions ---

@app.get("/api/admin/timesheets/export_csv", response_class=StreamingResponse)
async def export_timesheets_csv(
    pay_period_id: int,
    current_admin: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session)
):
    """
    Admin-only endpoint to export all submitted timesheets for a given pay period to CSV.
    """
    logger.info(f"Admin '{current_admin.username}' requesting CSV export for pay period ID: {pay_period_id}")

    timesheet_stmt = select(models.Timesheet).where(models.Timesheet.pay_period_id == pay_period_id)
    timesheets = session.exec(timesheet_stmt).all()

    pay_period = session.get(models.PayPeriod, pay_period_id)
    if not pay_period:
        raise HTTPException(status_code=404, detail="Pay period not found.")
    
    # Fetch all users involved in these timesheets to avoid N+1 queries
    user_ids = {ts.user_id for ts in timesheets}
    users = {u.id: u for u in session.exec(select(models.UserInDB).where(models.UserInDB.id.in_(user_ids))).all()}

    output = io.StringIO()
    csv_writer = csv.writer(output)

    headers = [
        "Timesheet ID", "Pilot Username", "Pay Period Name", "Pay Period Start", "Pay Period End",
        "Calculated Hours", "Adjusted Hours", "Final Hours", "Pilot Notes", "Reviewer Notes", "Status", "Submission Timestamp (UTC)"
    ]
    csv_writer.writerow(headers)

    for ts in timesheets:
        user = users.get(ts.user_id)
        username = user.username if user else "Unknown"
        final_hours = ts.adjusted_hours if ts.adjusted_hours is not None else ts.calculated_hours

        row = [
            ts.id, username, pay_period.name, pay_period.start_date.isoformat(), pay_period.end_date.isoformat(),
            f"{ts.calculated_hours:.2f}", f"{ts.adjusted_hours:.2f}" if ts.adjusted_hours is not None else "", f"{final_hours:.2f}",
            ts.notes or "", ts.reviewer_notes or "", ts.status.value, ts.submission_timestamp.isoformat()
        ]
        csv_writer.writerow(row)

    output.seek(0)
    filename = f"timesheets_{pay_period.name.replace(' ', '_').replace('-', '_')}.csv"
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename=\"{filename}\""})

# --- HTML Routes for Payroll ---

@app.get("/payroll/submit.html", response_class=HTMLResponse)
async def get_payroll_submit_page(
    request: Request,
    current_user: Optional[models.User] = Depends(get_optional_current_user)
):
    return templates.TemplateResponse(
        "payroll_submit.html",
        {"request": request, "current_user": current_user},
    )

@app.get("/payroll/my_timesheets.html", response_class=HTMLResponse)
async def get_my_timesheets_page(
    request: Request,
    current_user: Optional[models.User] = Depends(get_optional_current_user)
):
    return templates.TemplateResponse(
        "my_timesheets.html",
        {"request": request, "current_user": current_user},
    )
@app.get("/admin/pay_periods.html", response_class=HTMLResponse)
async def get_admin_pay_periods_page(
    request: Request,
    current_user: Optional[models.User] = Depends(get_optional_current_user)
):
    return templates.TemplateResponse(
        "admin_pay_periods.html",
        {"request": request, "current_user": current_user},
    )

@app.get("/admin/timesheets.html", response_class=HTMLResponse)
async def get_admin_view_timesheets_page(
    request: Request,
    current_user: Optional[models.User] = Depends(get_optional_current_user)
):
    return templates.TemplateResponse(
        "admin_view_timesheets.html",
        {"request": request, "current_user": current_user},
    )

@app.get("/admin/reports.html", response_class=HTMLResponse)
async def get_admin_reports_page(
    request: Request,
    current_user: Optional[models.User] = Depends(get_optional_current_user)
):
    return templates.TemplateResponse(
        "admin_reports.html",
        {"request": request, "current_user": current_user},
    )
# --- Home ---
@app.get("/home.html", response_class=HTMLResponse)
async def get_home_page(
    request: Request,
    current_user: Optional[models.User] = Depends(get_optional_current_user),
    session: SQLModelSession = Depends(get_db_session)
):
    """
    Serves the main home/splash page with tabbed views for all active missions.
    """
    logger.info(f"--- GET /home.html endpoint entered by user: {current_user.username if current_user else 'Anonymous'} ---")
    if not current_user:
        # If the user is not authenticated, redirect them to the login page.
        # The page requires server-side rendering with user data.
        logger.info("User not authenticated for /home.html, redirecting to login.")
        return RedirectResponse(url="/login.html?source=home", status_code=status.HTTP_302_FOUND)

    # 1. Get the list of missions considered "active" from settings.
    statically_active_missions = sorted(list(set(settings.active_realtime_missions)))
    logger.info(f"Found statically active missions in settings: {statically_active_missions}")

    # 2. Find which of those active missions actually have an overview in the database.
    if not statically_active_missions:
        logger.warning("The 'active_realtime_missions' list in settings is empty. No missions to display.")
        missions_to_display = []
    else:
        overview_missions_stmt = select(models.MissionOverview.mission_id).where(
            models.MissionOverview.mission_id.in_(statically_active_missions)
        ).order_by(models.MissionOverview.mission_id)
        
        # Execute the query and log the raw result for debugging
        mission_id_rows = session.exec(overview_missions_stmt).all()
        logger.info(f"Database query for overviews returned {len(mission_id_rows)} rows for the active missions.")

        # When selecting a single column, session.exec().all() returns a list of scalars (e.g., ['m209', 'm210']).
        # The previous list comprehension [row[0] for row in mission_id_rows] was incorrectly taking the first character of each string.
        # The correct approach is to just use the returned list directly.
        missions_to_display = mission_id_rows
        logger.info(f"After processing, the final list of mission IDs to display is: {missions_to_display}")
    
    # 3. Fetch mission info (overview, goals, notes) for the final list of missions.
    active_mission_data = {}
    if missions_to_display:
        for mission_id in missions_to_display:
            active_mission_data[mission_id] = await _get_mission_info(mission_id, session)
    elif statically_active_missions:
        logger.warning(
            "No mission overviews will be displayed. This is because no 'MissionOverview' entries were found in the database "
            "for any of the active missions listed in settings. Please verify the 'mission_id' in the 'missionoverview' "
            "table matches an entry in 'active_realtime_missions'."
        )
    
    return templates.TemplateResponse(
        "home.html",
        {
            "request": request, 
            "current_user": current_user,
            "active_missions": missions_to_display, # Pass the final list
            "active_mission_data": active_mission_data,
        },
    )

@app.get("/admin/announcements.html", response_class=HTMLResponse)
async def get_admin_announcements_page(
    request: Request,
    current_user: Optional[models.User] = Depends(get_optional_current_user)
):
    """
    Serves the admin page for managing announcements.
    JS on the page will verify admin role for API calls.
    """
    username_for_log = (
        current_user.username if current_user else "anonymous/unauthenticated"
    )
    logger.info(
        f"User '{username_for_log}' accessing /admin/announcements.html. JS will verify admin role."
    )
    return templates.TemplateResponse(
        "admin_announcements.html",
        {"request": request, "current_user": current_user},
    )

@app.get("/admin/mission_overviews.html", response_class=HTMLResponse)
async def get_admin_mission_overviews_page(
    request: Request,
    current_user: Optional[models.User] = Depends(get_optional_current_user)
):
    """
    Serves the admin page for managing mission overviews.
    JS on the page will verify admin role for API calls.
    """
    username_for_log = (
        current_user.username if current_user else "anonymous/unauthenticated"
    )
    logger.info(
        f"User '{username_for_log}' accessing /admin/mission_overviews.html. JS will verify admin role."
    )
    return templates.TemplateResponse(
        "admin_mission_overviews.html",
        {"request": request, "current_user": current_user},
    )

# --- Mission Info API Endpoints ---

@app.post("/api/missions/{mission_id}/overview/upload_plan", response_model=dict)
async def upload_mission_plan_file(
    mission_id: str,
    file: UploadFile = File(...),
    current_admin: models.User = Depends(get_current_admin_user),
):
    """
    Uploads a mission plan document (PDF, DOC, DOCX) for a specific mission.
    Admin only.
    """
    logger.info(f"Admin '{current_admin.username}' uploading plan for mission '{mission_id}'. Filename: {file.filename}")

    # Basic validation for file type
    allowed_content_types = [
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ]
    if file.content_type not in allowed_content_types:
        raise HTTPException(status_code=400, detail="Invalid file type. Only PDF, DOC, and DOCX are allowed.")

    # Sanitize filename
    file_extension = Path(file.filename).suffix
    safe_filename = f"{mission_id}_plan{file_extension}"
    
    # Define paths
    mission_plans_dir = Path(__file__).resolve().parent.parent / "web" / "static" / "mission_plans"
    file_path = mission_plans_dir / safe_filename
    
    try:
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    finally:
        file.file.close()

    file_url = f"/static/mission_plans/{safe_filename}"
    logger.info(f"Mission plan for '{mission_id}' saved to '{file_path}'. URL: {file_url}")
    
    return {"file_url": file_url}

@app.get("/api/missions/{mission_id}/info", response_model=models.MissionInfoResponse)
async def get_mission_info_api(
    mission_id: str,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session)
):
    """Gets all overview, goals, and notes for a specific mission."""
    logger.info(f"User '{current_user.username}' requesting info for mission '{mission_id}'.")
    return await _get_mission_info(mission_id, session)

@app.put("/api/missions/{mission_id}/overview", response_model=models.MissionOverview)
async def create_or_update_mission_overview(
    mission_id: str,
    overview_in: models.MissionOverviewUpdate,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session)
):
    """Creates or updates the mission overview."""
    logger.info(f"User '{current_user.username}' updating overview for mission '{mission_id}'.")
    db_overview = session.get(models.MissionOverview, mission_id)
    if not db_overview:
        db_overview = models.MissionOverview(mission_id=mission_id, **overview_in.model_dump(exclude_unset=True))
    else:
        update_data = overview_in.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(db_overview, key, value)
        # Manually trigger updated_at_utc timestamp
        db_overview.updated_at_utc = datetime.now(timezone.utc)

    session.add(db_overview)
    session.commit()
    session.refresh(db_overview)
    return db_overview

@app.post("/api/missions/{mission_id}/goals", response_model=models.MissionGoal, status_code=status.HTTP_201_CREATED)
async def create_mission_goal(
    mission_id: str,
    goal_in: models.MissionGoalCreate,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session)
):
    """Creates a new mission goal."""
    logger.info(f"User '{current_user.username}' creating goal for mission '{mission_id}': {goal_in.description}")
    db_goal = models.MissionGoal(mission_id=mission_id, description=goal_in.description)
    session.add(db_goal)
    session.commit()
    session.refresh(db_goal)
    return db_goal

@app.put("/api/missions/goals/{goal_id}", response_model=models.MissionGoal)
async def update_mission_goal(
    goal_id: int,
    goal_update: models.MissionGoalUpdate,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session)
):
    """Updates a mission goal (e.g., marks it as complete or changes description)."""
    db_goal = session.get(models.MissionGoal, goal_id)
    if not db_goal:
        raise HTTPException(status_code=404, detail="Mission goal not found.")

    update_data = goal_update.model_dump(exclude_unset=True)

    if "is_completed" in update_data:
        db_goal.is_completed = update_data["is_completed"]
        if db_goal.is_completed:
            db_goal.completed_by_username = current_user.username
            db_goal.completed_at_utc = datetime.now(timezone.utc)
        else:
            db_goal.completed_by_username = None
            db_goal.completed_at_utc = None

    if "description" in update_data and update_data["description"] is not None:
        db_goal.description = update_data["description"]

    session.add(db_goal)
    session.commit()
    session.refresh(db_goal)
    logger.info(f"User '{current_user.username}' updated goal ID {goal_id}.")
    return db_goal

@app.delete("/api/missions/goals/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mission_goal(
    goal_id: int,
    current_admin: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session)
):
    """Deletes a mission goal (Admin only)."""
    db_goal = session.get(models.MissionGoal, goal_id)
    if not db_goal:
        raise HTTPException(status_code=404, detail="Mission goal not found.")
    session.delete(db_goal)
    session.commit()
    logger.info(f"Admin '{current_admin.username}' deleted goal ID {goal_id}.")
    return

@app.post("/api/missions/{mission_id}/goals/{goal_id}/toggle", response_model=models.MissionGoal)
async def toggle_mission_goal_completion(
    mission_id: str,
    goal_id: int,
    goal_toggle: MissionGoalToggle,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """Toggles the completion status of a mission goal."""
    db_goal = session.get(models.MissionGoal, goal_id)
    if not db_goal:
        raise HTTPException(status_code=404, detail="Mission goal not found.")

    if db_goal.mission_id != mission_id:
        raise HTTPException(
            status_code=400,
            detail=f"Goal ID {goal_id} does not belong to mission '{mission_id}'.",
        )

    logger.info(
        f"User '{current_user.username}' toggling goal ID {goal_id} to completed={goal_toggle.is_completed}."
    )

    db_goal.is_completed = goal_toggle.is_completed
    if goal_toggle.is_completed:
        db_goal.completed_by_username = current_user.username
        db_goal.completed_at_utc = datetime.now(timezone.utc)
    else:
        db_goal.completed_by_username = None
        db_goal.completed_at_utc = None

    session.add(db_goal)
    session.commit()
    session.refresh(db_goal)
    return db_goal

@app.post("/api/missions/{mission_id}/notes", response_model=models.MissionNote, status_code=status.HTTP_201_CREATED)
async def create_mission_note(
    mission_id: str,
    note_in: models.MissionNoteCreate,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session)
):
    """Creates a new mission note."""
    logger.info(f"User '{current_user.username}' creating note for mission '{mission_id}'.")
    db_note = models.MissionNote(
        mission_id=mission_id,
        content=note_in.content,
        created_by_username=current_user.username
    )
    session.add(db_note)
    session.commit()
    session.refresh(db_note)
    return db_note

@app.delete("/api/missions/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mission_note(
    note_id: int,
    current_admin: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session)
):
    """Deletes a mission note (Admin only)."""
    db_note = session.get(models.MissionNote, note_id)
    if not db_note:
        raise HTTPException(status_code=404, detail="Mission note not found.")
    session.delete(db_note)
    session.commit()
    logger.info(f"Admin '{current_admin.username}' deleted note ID {note_id}.")
    return

# --- Announcement API Endpoints ---

@app.post("/api/admin/announcements", response_model=AnnouncementRead, status_code=status.HTTP_201_CREATED)
async def create_announcement(
    announcement_in: AnnouncementCreate,
    current_admin: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session)
):
    logger.info(f"Admin '{current_admin.username}' creating new announcement.")
    if not announcement_in.content.strip():
        raise HTTPException(status_code=400, detail="Announcement content cannot be empty.")
    
    db_announcement = Announcement(
        content=announcement_in.content,
        created_by_username=current_admin.username
    )
    session.add(db_announcement)
    session.commit()
    session.refresh(db_announcement)
    return db_announcement

@app.get("/api/announcements/active", response_model=List[AnnouncementReadForUser])
async def get_active_announcements(
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session)
):
    active_announcements_stmt = select(Announcement).where(Announcement.is_active == True).order_by(Announcement.created_at_utc.desc())
    active_announcements = session.exec(active_announcements_stmt).all()

    user_in_db = auth_utils.get_user_from_db(session, current_user.username)
    if not user_in_db:
        raise HTTPException(status_code=404, detail="Current user not found in database.")

    user_acks_stmt = select(AnnouncementAcknowledgement.announcement_id).where(AnnouncementAcknowledgement.user_id == user_in_db.id)
    user_acked_ids = set(session.exec(user_acks_stmt).all())

    response_list = []
    for ann in active_announcements:
        ann_data = AnnouncementReadForUser.model_validate(ann)
        ann_data.is_acknowledged_by_user = ann.id in user_acked_ids
        response_list.append(ann_data)
    
    return response_list

@app.post("/api/announcements/{announcement_id}/ack", status_code=status.HTTP_204_NO_CONTENT)
async def acknowledge_announcement(
    announcement_id: int,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session)
):
    user_in_db = auth_utils.get_user_from_db(session, current_user.username)
    if not user_in_db:
        raise HTTPException(status_code=404, detail="Current user not found in database.")

    # Check if announcement exists
    announcement = session.get(Announcement, announcement_id)
    if not announcement or not announcement.is_active:
        raise HTTPException(status_code=404, detail="Active announcement not found.")

    # Check if already acknowledged
    existing_ack_stmt = select(AnnouncementAcknowledgement).where(
        AnnouncementAcknowledgement.announcement_id == announcement_id,
        AnnouncementAcknowledgement.user_id == user_in_db.id
    )
    if session.exec(existing_ack_stmt).first():
        logger.warning(f"User '{current_user.username}' tried to re-acknowledge announcement ID {announcement_id}.")
        return # Return success even if already acknowledged

    new_ack = AnnouncementAcknowledgement(announcement_id=announcement_id, user_id=user_in_db.id)
    session.add(new_ack)
    session.commit()
    logger.info(f"User '{current_user.username}' acknowledged announcement ID {announcement_id}.")
    return

@app.get("/api/admin/announcements/all", response_model=List[AnnouncementReadWithAcks])
async def admin_get_all_announcements(
    current_admin: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session)
):
    all_announcements = session.exec(select(Announcement).order_by(Announcement.created_at_utc.desc())).all()
    response_list = []
    for ann in all_announcements:
        ann_data = AnnouncementReadWithAcks.model_validate(ann)
        ack_list = []
        for ack in ann.acknowledgements:
            user = session.get(models.UserInDB, ack.user_id)
            if user:
                ack_list.append(AcknowledgedByInfo(username=user.username, acknowledged_at_utc=ack.acknowledged_at_utc))
        ann_data.acknowledged_by = sorted(ack_list, key=lambda x: x.acknowledged_at_utc)
        response_list.append(ann_data)
    return response_list

@app.delete("/api/admin/announcements/{announcement_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_announcement(
    announcement_id: int,
    current_admin: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session)
):
    db_announcement = session.get(Announcement, announcement_id)
    if not db_announcement:
        raise HTTPException(status_code=404, detail="Announcement not found.")
    db_announcement.is_active = False
    session.add(db_announcement)
    session.commit()
    logger.info(f"Admin '{current_admin.username}' archived announcement ID {announcement_id}.")
    return

@app.put("/api/admin/announcements/{announcement_id}", response_model=AnnouncementRead)
async def edit_announcement(
    announcement_id: int,
    announcement_update: AnnouncementCreate,
    current_admin: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session)
):
    """
    Admin-only endpoint to edit the content of an existing announcement.
    """
    logger.info(f"Admin '{current_admin.username}' editing announcement ID {announcement_id}.")
    
    db_announcement = session.get(Announcement, announcement_id)
    if not db_announcement:
        raise HTTPException(status_code=404, detail="Announcement not found.")

    if not announcement_update.content.strip():
        raise HTTPException(status_code=400, detail="Announcement content cannot be empty.")

    db_announcement.content = announcement_update.content
    session.add(db_announcement)
    session.commit()
    session.refresh(db_announcement)
    return db_announcement

@app.get("/api/admin/users", response_model=List[models.User])
async def admin_list_users(
    current_admin: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session),  # Inject session
):
    """Lists all users. Admin only."""
    logger.info(f"Admin '{current_admin.username}' requesting list of all users.")
    return auth_utils.list_all_users_from_db(session)  # Pass session


@app.put("/api/admin/users/{username}", response_model=models.User)
async def admin_update_user(
    username: str,
    user_update: models.UserUpdateForAdmin,
    current_admin: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session),  # Inject session
):
    """
    Updates a user's details (full name, email, role, disabled status).
    Admin only.
    """
    update_data_str = user_update.model_dump(exclude_unset=True)
    logger.info(f"Admin '{current_admin.username}' updating user '{username}' with: {update_data_str}")

    # Basic safety: Prevent admin from disabling/demoting the last active admin (themselves)
    if username == current_admin.username:
        if user_update.disabled is True or (
            user_update.role and user_update.role != models.UserRoleEnum.admin
        ):
            # Query active admins from DB
            stmt = select(models.UserInDB).where(
                models.UserInDB.role == models.UserRoleEnum.admin,
                models.UserInDB.disabled == False,
            )
            active_admins = session.exec(stmt).all()
            if len(active_admins) == 1 and active_admins[0].username == username:
                logger.error(
                    f"Admin '{current_admin.username}' attempted to disable or "
                    f"demote themselves as the sole active admin."
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Cannot disable or demote the only active administrator.",
                )

    updated_user_in_db = auth_utils.update_user_details_in_db(
        session, username, user_update
    )  # Pass session
    if not updated_user_in_db:
        logger.warning(
            f"Admin '{current_admin.username}' failed to update "
            f"non-existent user '{username}'."
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    # Convert UserInDB to User for the response
    return models.User.model_validate(updated_user_in_db.model_dump())


@app.put("/api/admin/users/{username}/password")
async def admin_change_user_password(
    username: str,
    password_update: models.PasswordUpdate,
    current_admin: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session),  # Inject session
):
    """Changes a user's password. Admin only."""
    logger.info(
        f"Admin '{current_admin.username}' attempting to change password for "
        f"user '{username}'."
    )
    success = auth_utils.update_user_password_in_db(
        session, username, password_update.new_password
    )  # Pass session
    if not success:
        logger.warning(
            f"Admin '{current_admin.username}' failed to change password for "
            f"non-existent user '{username}'."
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    return {"message": "Password updated successfully"}


# --- API Endpoints ---


@app.get("/api/data/{report_type}/{mission_id}")
async def get_report_data_for_plotting(
    report_type: models.ReportTypeEnum,  # Use Enum for path parameter validation
    mission_id: str,
    params: models.ReportDataParams = Depends(),  # Inject Pydantic model for query params
    current_user: models.User = Depends(get_current_active_user),  # Protect API
):
    """
    Provides processed time-series data for a given report type,
    suitable for frontend plotting.
    """
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

    # Calculate the cutoff time based on the most recent data point
    cutoff_time = max_timestamp - timedelta(hours=params.hours_back)
    recent_data = processed_df[processed_df["Timestamp"] > cutoff_time]
    if recent_data.empty:  # hours_back was used in cutoff_time, not directly here
        logger.info(
            f"No data for {report_type.value}, mission {mission_id} within "
            f"{params.hours_back} hours of its latest data point ({max_timestamp})."
        )
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
        context = {
            "request": request,
            "mission_id": mission_id,
            "form_type": form_type,
            "current_user": actual_current_user,  # Pass to template
        }

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
@app.get("/view_forms.html", response_class=HTMLResponse)
async def get_view_forms_page(
    request: Request,
    current_user: Optional[models.User] = Depends(
        get_optional_current_user
    ),  # Allow any authenticated user
):
    # If no user (not logged in), JS will redirect via checkAuth().
    # If user is present, their role will be available to the template.
    username_for_log = (
        current_user.username if current_user else "anonymous/unauthenticated"
    )
    user_role_for_log = current_user.role.value if current_user else "N/A"
    logger.info(
        f"User '{username_for_log}' (role: {user_role_for_log}) "
        f"accessing /view_forms.html."
    )
    return templates.TemplateResponse(
        "view_forms.html",
        {
            "request": request,
            "current_user": current_user, # Removed show_mission_selector
        },    )


@app.get("/my_pic_handoffs.html", response_class=HTMLResponse)
async def get_my_pic_handoffs_page(
    request: Request,
    current_user: Optional[models.User] = Depends(get_optional_current_user)
):
    logger.info(f"User '{current_user.username if current_user else 'anonymous'}' accessing /my_pic_handoffs.html.")
    return templates.TemplateResponse(
        "my_pic_handoffs.html", # Removed show_mission_selector
        {"request": request, "current_user": current_user},
    )
@app.get("/view_pic_handoffs.html", response_class=HTMLResponse)
async def get_view_pic_handoffs_page(
    request: Request,
    current_user: Optional[models.User] = Depends(get_optional_current_user)
):
    logger.info(f"User '{current_user.username if current_user else 'anonymous'}' accessing /view_pic_handoffs.html.")
    return templates.TemplateResponse( # Removed show_mission_selector
        "view_pic_handoffs.html",
        {"request": request, "current_user": current_user},
    )
# Ensure this is the last line or that other routes are defined before it if they share a common prefix.
# Example: if you had a catch-all, it should be last.

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
        {
            "request": request,
            "current_user": current_user, # Removed show_mission_selector
        },    )


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
        {
            "request": request,
            "current_user": current_user, # Removed show_mission_selector
        },
    )
