import asyncio
import json  # For saving/loading forms to/from JSON
import logging
from datetime import timezone  # Import timezone directly
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import httpx  # For async client in load_data_source
import numpy as np  # For numeric operations if needed
import pandas as pd  # For DataFrame operations # type: ignore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import (  # Added status
    Depends,
    FastAPI,
    HTTPException,
    Request,
    status,
)
from fastapi.responses import HTMLResponse, JSONResponse  # type: ignore
from fastapi.security import OAuth2PasswordRequestForm  # type: ignore
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import (  # type: ignore
    SQLModel,
    inspect,
    select,
)

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
from .routers import station_metadata_router

# --- Conditional import for fcntl ---
IS_UNIX = True
try:
    import fcntl
except ImportError:
    IS_UNIX = False
    fcntl = None  # type: ignore # Make fcntl None on non-Unix systems


app = FastAPI()

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
# ---

# In-memory cache: key -> (data, actual_source_path_str, cache_timestamp).
# 'data' is typically pd.DataFrame, but for 'processed_wave_spectrum'
# it's List[Dict].
# The type hint for data_cache needs to be more generic or use Union.
# For simplicity, keeping as is, but be mindful.
data_cache: Dict[Tuple, Tuple[pd.DataFrame, str, datetime]] = {}
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


# ---
def _initialize_database_and_users():
    """Helper function to contain the DB creation and default user logic."""
    if settings.forms_storage_mode == "sqlite":  # Also implies user data is in SQLite
        create_db_and_tables()

    with SQLModelSession(sqlite_engine) as session:
        inspector = inspect(sqlite_engine)
        if inspector.has_table(models.UserInDB.__tablename__):  # type: ignore
            statement = select(models.UserInDB)
            existing_user = session.exec(statement).first()
            if not existing_user:
                logger.info(
                    "No users found in the database. Creating default users..."
                )
                default_users_data = [
                    {
                        "username": "adminuser",
                        "full_name": "Admin User",
                        "email": "admin@example.com",
                        "password": "adminpass",
                        "role": models.UserRoleEnum.admin,
                        "disabled": False,
                    },
                    {
                        "username": "pilotuser",
                        "full_name": "Pilot User",
                        "email": "pilot@example.com",
                        "password": "pilotpass",
                        "role": models.UserRoleEnum.pilot,
                        "disabled": False,
                    },
                    {
                        "username": "pilot_rt_only",
                        "full_name": "Realtime Pilot",
                        "email": "pilot_rt@example.com",
                        "password": "pilotrtpass",
                        "role": models.UserRoleEnum.pilot,
                        "disabled": False,
                    },
                ]
                for user_data_dict in default_users_data:
                    user_create_model = models.UserCreate(**user_data_dict)
                    auth_utils.add_user_to_db(session, user_create_model)
                logger.info(f"{len(default_users_data)} default users created.")
            else:
                logger.info("Existing users found. Skipping default user creation.")
        else:
            logger.error(
                f"'{models.UserInDB.__tablename__}' table still does not exist "
                "after create_db_and_tables(). DB init failed."
            )


async def load_data_source(
    report_type: str,
    mission_id: str,
    source_preference: Optional[str] = None,  # 'local' or 'remote'
    custom_local_path: Optional[str] = None,
    force_refresh: bool = False,  # New parameter to bypass cache
    current_user: Optional[
        models.UserInDB  # Changed to UserInDB as that's what get_optional_current_user returns
    ] = None,
):
    """Attempts to load data, trying remote then local sources."""
    # df variable will hold the loaded DataFrame.
    # For the 'processed_wave_spectrum' (which is not a direct report_type
    # for this function), this function loads the source DataFrames.
    # The processing and specific caching
    # for the combined spectrum happens in the /api/wave_spectrum endpoint.
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
        if custom_local_path:
            _custom_local_path_str = (
                f"Local (Custom): {Path(custom_local_path) / mission_id}"
            )
            _attempted_custom_local = False
            try:
                logger.debug(
                    f"Attempting local load for {report_type} "
                    f"(mission: {mission_id}) from custom path: {custom_local_path}"
                )
                df_attempt = await loaders.load_report(
                    report_type, mission_id, base_path=Path(custom_local_path)
                )
                _attempted_custom_local = (
                    True  # File was accessed or attempted beyond FNF
                )
                if df_attempt is not None and not df_attempt.empty:
                    df = df_attempt
                    actual_source_path = _custom_local_path_str
                elif (
                    _attempted_custom_local
                    and actual_source_path == "Data not loaded"
                ):  # File accessed but empty
                    actual_source_path = _custom_local_path_str
            except FileNotFoundError:
                logger.warning(
                    f"Custom local file for {report_type} ({mission_id}) not "
                    f"found at {custom_local_path}. Trying default local."
                )
                df = None  # Ensure df is None to trigger default local load
            except Exception as e:
                error_msg = (
                    f"Custom local load failed for {report_type} ({mission_id}) "
                    f"from {custom_local_path}: {e}"
                )
                logger.warning(error_msg + ". Trying default local.")
                if (
                    _attempted_custom_local
                    and actual_source_path == "Data not loaded"
                ):  # Path was attempted, but an error occurred
                    actual_source_path = _custom_local_path_str
                df = None  # Ensure df is None to trigger default local load

        if (
            df is None
        ):  # If custom path failed, wasn't provided, or yielded no usable data
            _default_local_path_str = (
                f"Local (Default): {settings.local_data_base_path / mission_id}"
            )
            _attempted_default_local = False
            try:
                logger.debug(
                    f"Attempting local load for {report_type} "
                    f"(mission: {mission_id}) from default path: {settings.local_data_base_path}"
                )
                df_attempt = await loaders.load_report(
                    report_type, mission_id, base_path=settings.local_data_base_path
                )
                _attempted_default_local = True
                if df_attempt is not None and not df_attempt.empty:
                    df = df_attempt
                    actual_source_path = _default_local_path_str
                elif (
                    _attempted_default_local
                    and actual_source_path == "Data not loaded"
                ):  # File accessed but empty
                    actual_source_path = _default_local_path_str
            except FileNotFoundError:
                logger.warning(
                    f"Default local file for {report_type} ({mission_id}) not "
                    f"found at {settings.local_data_base_path}."
                )
            except Exception as e:
                error_msg = (
                    f"Default local load failed for {report_type} "
                    f"({mission_id}): {e}"
                )
                logger.warning(error_msg + ".")
                if (
                    _attempted_default_local
                    and actual_source_path == "Data not loaded"
                ):  # Path was attempted, but an error occurred
                    actual_source_path = _default_local_path_str
                df = None  # Ensure df is None on other errors
        # If 'local' was preferred and custom_local_path was provided but failed,
        # the above block handles the default local attempt.
        # If local was preferred and even default local fails, df will remain None.

    # Remote-first or default behavior (remote then local fallback)
    elif source_preference == "remote" or source_preference is None:
        load_attempted = True
        remote_mission_folder = settings.remote_mission_folder_map.get(
            mission_id, mission_id
        )

        # Define potential remote base paths to try, in order of preference
        # Ensure no double slashes if settings.remote_data_url ends with /
        base_remote_url = settings.remote_data_url.rstrip("/")
        remote_base_urls_to_try: List[str] = []

        # Role-based access to remote paths.
        # If current_user is None (e.g., background task), assume admin-like
        # full access for refresh.
        # Note: current_user here is UserInDB, which has .role
        # models.User is the Pydantic model for API responses.
        user_role = current_user.role if current_user else models.UserRoleEnum.admin

        if user_role == models.UserRoleEnum.admin:
            remote_base_urls_to_try.extend(
                [
                    f"{base_remote_url}/output_realtime_missions",
                    f"{base_remote_url}/output_past_missions",
                ]
            )
        elif user_role == models.UserRoleEnum.pilot:
            # Pilots can only access real-time missions that are in
            # the active_realtime_missions list
            if mission_id in settings.active_realtime_missions:
                remote_base_urls_to_try.append(
                    f"{base_remote_url}/output_realtime_missions"
                )
            else:
                logger.info(
                    f"Pilot '{current_user.username if current_user else 'N/A'}'"
                    f" - Access to remote data for non-active mission "
                    f"'{mission_id}' restricted."
                )

        df = None
        last_accessed_remote_path_if_empty = (
            None  # Track if a remote file was found but empty
        )

        # If no remote URLs are applicable (e.g., pilot trying to access
        # past mission), this loop won't run.
        for constructed_base_url in remote_base_urls_to_try:
            # THIS IS THE CRUCIAL PART: Ensure client is managed per-attempt
            # Client is created and closed for each URL in the loop
            async with httpx.AsyncClient() as current_client:
                try:
                    logger.debug(
                        f"Attempting remote load for {report_type} (mission: "
                        f"{mission_id}, remote folder: {remote_mission_folder}) "
                        f"from base: {constructed_base_url}"
                    )
                    # Pass this specific client to loaders.load_report
                    df_attempt = await loaders.load_report(
                        report_type,
                        mission_id=remote_mission_folder,
                        base_url=constructed_base_url,
                        client=current_client,
                    )
                    if df_attempt is not None and not df_attempt.empty:
                        df = df_attempt
                        actual_source_path = (
                            f"Remote: {constructed_base_url}/{remote_mission_folder}"
                        )
                        logger.debug(
                            f"Successfully loaded {report_type} for mission "
                            f"{mission_id} from {actual_source_path}"
                        )
                        break  # Data found, no need to try other remote paths
                    elif (
                        df_attempt is not None
                    ):  # File found, read, but resulted in an empty DataFrame
                        last_accessed_remote_path_if_empty = (
                            f"Remote: {constructed_base_url}/{remote_mission_folder}"
                        )
                        logger.debug(
                            f"Remote file found but empty for {report_type} "
                            f"({mission_id}) from {last_accessed_remote_path_if_empty}. Will try next."
                        )
                except (
                    httpx.HTTPStatusError
                ) as e_http:  # Catch HTTPStatusError specifically
                    if (
                        e_http.response.status_code == 404
                        and "output_realtime_missions" in constructed_base_url
                    ):
                        logger.debug(
                            f"File not found in realtime path (expected for "
                            f"past missions): {constructed_base_url}/"
                            f"{remote_mission_folder} for {report_type} "
                            f"({mission_id}). Will try next path."
                        )
                    else:  # Other HTTP errors or 404s remain warnings
                        logger.warning(
                            f"Remote load attempt from {constructed_base_url} "
                            f"failed for {report_type} ({mission_id}): {e_http}"
                        )
                except (
                    Exception
                ) as e_remote_attempt:  # Catch other client errors
                    logger.warning(
                        f"General remote load attempt from {constructed_base_url} "
                        f"failed for {report_type} ({mission_id}): {e_remote_attempt}"
                    )

        if df is None or df.empty:  # If all remote attempts failed
            if not remote_base_urls_to_try and (
                source_preference == "remote" or source_preference is None
            ):
                logger.info(
                    f"No remote paths attempted for {report_type} ({mission_id}) "
                    f"due to role/mission status. Proceeding to local fallback."
                )
            else:
                logger.warning(
                    f"No usable remote data found for {report_type} ({mission_id}). Falling back to default local."
                )
            # No external client to close here as it's managed internally or not passed by home route
            _local_fallback_path_str = f"Local (Default Fallback): {settings.local_data_base_path / mission_id}"
            _attempted_local_fallback = False
            try:
                logger.debug(
                    f"Attempting fallback local load for {report_type} "
                    f"(mission: {mission_id}) from {settings.local_data_base_path}"
                )
                df_fallback = await loaders.load_report(
                    report_type, mission_id, base_path=settings.local_data_base_path
                )
                _attempted_local_fallback = True
                if df_fallback is not None and not df_fallback.empty:
                    df = df_fallback
                    actual_source_path = _local_fallback_path_str
                elif _attempted_local_fallback:  # Local file accessed but was empty
                    actual_source_path = _local_fallback_path_str
            except FileNotFoundError:
                _msg = (
                    f"Fallback local file not found for {report_type} "
                    f"({mission_id}) at {settings.local_data_base_path / mission_id}"
                )
                logger.debug(_msg)
                if (
                    last_accessed_remote_path_if_empty
                    and actual_source_path == "Data not loaded"
                ):  # Remote file empty, local fallback FNF
                    actual_source_path = last_accessed_remote_path_if_empty
                elif (
                    actual_source_path == "Data not loaded"
                ):  # If no remote file was touched either
                    path_part = _local_fallback_path_str.split(':', 1)[1].strip()
                    actual_source_path = (
                        f"Local (Default Fallback): File Not Found - {path_part}"
                    )
            except Exception as e_local_fallback:  # Other error in local fallback
                logger.error(
                    f"Fallback local load failed for {report_type} ({mission_id}): {e_local_fallback}"
                )
                if (
                    _attempted_local_fallback
                    and actual_source_path == "Data not loaded"
                ):  # Path was attempted, but an error occurred
                    actual_source_path = _local_fallback_path_str
                df = None  # Ensure df is None on other errors
        elif (
            last_accessed_remote_path_if_empty
            and actual_source_path == "Data not loaded"
        ):  # df populated by remote, but earlier remote attempt found empty file
            pass  # actual_source_path is already correctly set to the non-empty remote source

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
    logger.info("Application startup event completed.")  # Changed from print


@app.on_event("shutdown")  # Ensure this is also uncommented
def shutdown_event():
    if (
        "scheduler" in globals() and scheduler.running
    ):  # Check if scheduler was initialized and started
        scheduler.shutdown()
    logger.info("APScheduler shut down.")


# --- Authentication Endpoint ---
@app.post("/token", response_model=models.Token)
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    session: SQLModelSession = Depends(get_db_session),  # Inject session
):
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
    return {"access_token": access_token, "token_type": "bearer"}


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
    return templates.TemplateResponse("register.html", {"request": request})


@app.get("/login.html", response_class=HTMLResponse)
async def login_page(request: Request):
    # Serves the login page
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/", response_class=HTMLResponse)  # Protected route
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
    # Attempt to get current user. If no token, actual_current_user is None.
    # JS handles redirect to /login.html if no token.
    actual_current_user: Optional[models.User] = await get_optional_current_user(
        request
    )

    # `available_missions` will now be populated by the client-side JavaScript.
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

    # Unpack results and source paths
    data_frames: Dict[str, Optional[pd.DataFrame]] = {}
    source_paths_map: Dict[str, str] = {}
    # Ensure "error_frequency" is NOT in this list for the main page load.
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

    for i, report_type in enumerate(report_types_order):
        if isinstance(results[i], Exception):
            data_frames[report_type] = None
            source_paths_map[report_type] = "Error during load"
            logger.error(
                f"Exception loading {report_type} for mission {mission}: "
                f"{results[i]}"
            )
        else:
            data_frames[report_type], source_paths_map[report_type] = results[i]

    df_power = data_frames["power"]
    df_ctd = data_frames["ctd"]
    df_weather = data_frames["weather"]
    df_waves = data_frames["waves"]
    df_vr2c = data_frames["vr2c"]  # New sensor
    df_solar = data_frames["solar"]  # New solar data
    df_fluorometer = data_frames["fluorometer"]  # C3 Fluorometer
    df_wg_vm4 = data_frames["wg_vm4"]  # New WG-VM4 data
    df_ais = data_frames["ais"]
    df_errors = data_frames["errors"]
    df_telemetry = data_frames["telemetry"]  # Telemetry data

    # Determine the primary display_source_path based on success and priority
    display_source_path = (
        "Data Source: Information unavailable or all loads failed"
    )
    found_primary_path_for_display = False  # Flag to break outer loop

    priority_paths = [
        (
            lambda p: "Remote:" in p
            and "output_realtime_missions" in p
            and "Data not loaded" not in p
            and "Error during load" not in p
        ),
        (
            lambda p: "Remote:" in p
            and "output_past_missions" in p
            and "Data not loaded" not in p
            and "Error during load" not in p
        ),
        (
            lambda p: "Local (Custom):" in p
            and "Data not loaded" not in p
            and "Error during load" not in p
        ),
        (
            lambda p: p.startswith("Local (Default")
            and "Data not loaded" not in p
            and "Error during load" not in p
        ),  # Catches "Local (Default)" and "Local (Default Fallback)"
    ]
    for check_priority in priority_paths: # Check in defined order or any order
        for report_type in report_types_order:
            path_info = source_paths_map.get(report_type, "")
            if check_priority(path_info):
                # Strip the prefix from path_info
                path_to_display = path_info
                if path_info.startswith("Remote: "):
                    path_to_display = path_info.replace("Remote: ", "", 1).strip()
                elif path_info.startswith("Local (Custom): "):
                    path_to_display = path_info.replace(
                        "Local (Custom): ", "", 1
                    ).strip()
                elif path_info.startswith("Local (Default): "):
                    path_to_display = (
                        path_info.split(":", 1)[1].strip()
                        if ":" in path_info
                        else path_info
                    )  # Handles "Local (Default)" and "Local (Default Fallback)" # noqa

                display_source_path = f"Data Source: {path_to_display}"
                found_primary_path_for_display = True  # Found our primary display path
                break
        if found_primary_path_for_display:
            break  # Exit outer loop once a primary path is found

    # Get status and update info using refactored summary functions,
    # add mini-trend dataframes

    power_info = summaries.get_power_status(df_power, df_solar)  # Pass df_solar
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
    fluorometer_info["mini_trend"] = summaries.get_fluorometer_mini_trend(
        df_fluorometer
    )

    wg_vm4_info = summaries.get_wg_vm4_status(df_wg_vm4)  # Get WG-VM4 summary
    wg_vm4_info["mini_trend"] = summaries.get_wg_vm4_mini_trend(
        df_wg_vm4
    )  # Get WG-VM4 mini trend

    navigation_info = summaries.get_navigation_status(
        df_telemetry
    )  # Get navigation summary
    navigation_info["mini_trend"] = summaries.get_navigation_mini_trend(
        df_telemetry
    )  # Get navigation mini trend

    # For AIS and Errors, get summary list and then derive update info from original DFs
    ais_summary_data = (
        summaries.get_ais_summary(df_ais, max_age_hours=hours)
        if df_ais is not None
        else []
    )
    ais_update_info = utils.get_df_latest_update_info(
        df_ais, timestamp_col="LastSeenTimestamp"
    )  # Adjust col if needed
    recent_errors_list = (
        summaries.get_recent_errors(df_errors, max_age_hours=hours)[:20]
        if df_errors is not None
        else []
    )
    errors_update_info = utils.get_df_latest_update_info(
        df_errors, timestamp_col="Timestamp"
    )  # Adjust col if needed

    # Flags for template to control collapse state and indicators
    has_ais_data = bool(ais_summary_data)
    has_errors_data = bool(recent_errors_list)

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
            "display_source_path": display_source_path,
            "current_local_path": local_path,  # Pass current local_path
            "power_info": power_info,
            "ctd_info": ctd_info,  # This will be the dict from refactored get_ctd_status
            "weather_info": weather_info,  # Dict from refactored get_weather_status
            "wave_info": wave_info,  # Dict from refactored get_wave_status
            "ais_summary_data": ais_summary_data,
            "ais_update_info": ais_update_info,
            "errors_summary_data": recent_errors_list,
            "errors_update_info": errors_update_info,
            "has_ais_data": has_ais_data,  # check
            "has_errors_data": has_errors_data,  # check
            "fluorometer_info": fluorometer_info,  # C3 Fluorometer
            "wg_vm4_info": wg_vm4_info,  # WG-VM4
            "vr2c_info": vr2c_info,  # Mrx
            "navigation_info": navigation_info,
            "current_user": actual_current_user,  # Pass user info to template
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


async def get_example_form_schema(
    form_type: str, mission_id: str, current_user: models.User
) -> models.MissionFormSchema:
    """
    Generates a form schema based on form_type.
    This is where you'd define the structure of different forms.
    For now, it includes a basic example with auto-fill.
    """
    if form_type == "pre_deployment_checklist":
        # Attempt to get latest power status for auto-fill
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

        return models.MissionFormSchema(
            form_type=form_type,
            title="Pre-Deployment Checklist",
            description="Complete this checklist before deploying the Wave Glider.",
            sections=[
                models.FormSection(
                    id="general_checks",
                    title="General System Checks",
                    items=[
                        models.FormItem(
                            id="hull_integrity",
                            label="Hull Integrity Visual Check",
                            item_type=models.FormItemTypeEnum.CHECKBOX,
                            required=True,
                        ),
                        models.FormItem(
                            id="umbilical_check",
                            label="Umbilical Secure and Undamaged",
                            item_type=models.FormItemTypeEnum.CHECKBOX,
                            required=True,
                        ),
                        models.FormItem(
                            id="payload_power",
                            label="Payload Power On",
                            item_type=models.FormItemTypeEnum.CHECKBOX,
                        ),
                    ],
                ),
                models.FormSection(
                    id="power_system",
                    title="Power System",
                    items=[
                        models.FormItem(
                            id="battery_level_auto",
                            label="Current Battery Level (Auto)",
                            item_type=models.FormItemTypeEnum.AUTOFILLED_VALUE,
                            value=battery_percentage_value,
                        ),
                        models.FormItem(
                            id="battery_level_manual",
                            label="Confirm Battery Level Sufficient",
                            item_type=models.FormItemTypeEnum.CHECKBOX,
                            required=True,
                        ),
                        models.FormItem(
                            id="solar_panels_clean",
                            label="Solar Panels Clean",
                            item_type=models.FormItemTypeEnum.CHECKBOX,
                        ),
                    ],
                    section_comment="Ensure all power connections are secure.",
                ),
                models.FormSection(
                    id="comms_check",
                    title="Communications",
                    items=[
                        models.FormItem(
                            id="iridium_status",
                            label="Iridium Comms Check (Signal Strength)",
                            item_type=models.FormItemTypeEnum.TEXT_INPUT,
                            placeholder="e.g., 5 bars",
                        ),
                        models.FormItem(
                            id="rudics_test",
                            label="RUDICS Test Call Successful",
                            item_type=models.FormItemTypeEnum.CHECKBOX,
                        ),
                    ],
                ),
                models.FormSection(
                    id="final_notes",
                    title="Final Notes & Sign-off",
                    items=[
                        models.FormItem(
                            id="deployment_notes",
                            label="Deployment Notes/Observations",
                            item_type=models.FormItemTypeEnum.TEXT_AREA, # noqa
                            placeholder="Any issues or special conditions...",
                        ),
                        models.FormItem(
                            id="sign_off_name",
                            label="Signed Off By (Name)",
                            item_type=models.FormItemTypeEnum.TEXT_INPUT,
                            required=True,
                        ),
                    ],
                ),
            ],
        )
    elif form_type == "pic_handoff_checklist":
        # Attempt to get latest power status for auto-fill
        latest_power_df, _ = await load_data_source(
            "power", mission_id, current_user=current_user
        )
        power_summary_values = summaries.get_power_status(latest_power_df).get(
            "values", {}
        )

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

        # Placeholder for other potential autofills - for now, most are text inputs
        # glider_id_value = mission_id # This is already available
        # total_battery_capacity_value = "2600 Wh" # Example, could be dynamic per glider type later

        return models.MissionFormSchema( # noqa
            form_type=form_type,
            title="PIC Handoff Checklist", # noqa
            description="Pilot in Command (PIC) handoff checklist. Verify each item.",
            sections=[
                models.FormSection(
                    id="general_status",
                    title="Glider & Mission General Status",
                    items=[
                        models.FormItem(
                            id="glider_id_val",
                            label="Glider ID",
                            item_type=models.FormItemTypeEnum.AUTOFILLED_VALUE,
                            value=mission_id,
                        ),
                        models.FormItem(
                            id="current_mos_val",
                            label="Current MOS",
                            item_type=models.FormItemTypeEnum.DROPDOWN,
                            options=["Sue L", "Tyler B", "Matt M", "Adam C"],
                            required=True,
                        ),
                        models.FormItem(
                            id="current_pic_val",
                            label="Current PIC",
                            item_type=models.FormItemTypeEnum.DROPDOWN,
                            options=[
                                "Adam S",
                                "Laura R",
                                "Sue L",
                                "Tyler B",
                                "Adam C",
                                "Poppy K",
                                "LRI",
                                "Matt M",
                                "Noa W",
                                "Nicole N",
                            ],
                            required=True,
                        ),
                        models.FormItem(
                            id="last_pic_val",
                            label="Last PIC",
                            item_type=models.FormItemTypeEnum.DROPDOWN,
                            options=[
                                "Adam S",
                                "Laura R",
                                "Sue L",
                                "Tyler B",
                                "Adam C",
                                "Poppy K",
                                "LRI",
                                "Matt M",
                                "Noa W",
                                "Nicole N",
                            ],
                            required=True,
                        ),
                        models.FormItem(
                            id="mission_status_val",
                            label="Mission Status",
                            item_type=models.FormItemTypeEnum.DROPDOWN,
                            options=[
                                "In Transit",
                                "Avoiding Ship",
                                "Holding for Storm",
                                "Offloading",
                                "In Recovery Hold",
                                "Surveying",
                            ],
                            required=True,
                        ),
                        models.FormItem(
                            id="total_battery_val",
                            label="Total Battery Capacity (Wh)",
                            item_type=models.FormItemTypeEnum.STATIC_TEXT,
                            value="2775 Wh",
                        ),  # Using constant from summaries.py
                        models.FormItem(
                            id="current_battery_wh_val",
                            label="Current Glider Battery (Wh)",
                            item_type=models.FormItemTypeEnum.AUTOFILLED_VALUE,
                            value=current_battery_wh_value,
                        ),
                        models.FormItem(
                            id="percent_battery_val",
                            label="% Battery Remaining",
                            item_type=models.FormItemTypeEnum.AUTOFILLED_VALUE,
                            value=battery_percentage_value,
                        ),
                        models.FormItem(
                            id="tracker_battery_v_val",
                            label="Tracker Battery (V)",
                            item_type=models.FormItemTypeEnum.TEXT_INPUT,
                            placeholder="e.g., 14.94",
                        ),
                        models.FormItem(
                            id="tracker_last_update_val",
                            label="Tracker Last Update",
                            item_type=models.FormItemTypeEnum.TEXT_INPUT,
                            placeholder="e.g., MM-DD-YYYY HH:MM:SS",
                        ),
                        models.FormItem(
                            id="communications_val",
                            label="Communications Mode",
                            item_type=models.FormItemTypeEnum.DROPDOWN,
                            options=["SAT", "CELL"],
                            required=True,  # Assuming this is required
                        ),
                        models.FormItem(
                            id="telemetry_rate_val",
                            label="Telemetry Report Rate (min)",
                            item_type=models.FormItemTypeEnum.TEXT_INPUT,
                            placeholder="e.g., 5",
                        ),
                        models.FormItem(
                            id="navigation_mode_val",
                            label="Navigation Mode",
                            item_type=models.FormItemTypeEnum.DROPDOWN,
                            options=["FSC", "FFB", "FFH", "WC", "FCC"],
                            required=True,  # Assuming this is required
                        ),
                        models.FormItem(
                            id="target_waypoint_val",
                            label="Target Waypoint",
                            item_type=models.FormItemTypeEnum.TEXT_INPUT,
                            placeholder="Enter target waypoint",
                        ),
                        models.FormItem(
                            id="waypoint_details_val",
                            label="Waypoint Start to Finish Details",
                            item_type=models.FormItemTypeEnum.TEXT_INPUT,
                            placeholder="e.g., 90 Degrees, 5km",
                        ),
                        models.FormItem(
                            id="light_status_val",
                            label="Light Status",
                            item_type=models.FormItemTypeEnum.DROPDOWN,
                            options=["ON", "OFF", "AUTO", "N/A"],
                            required=True,
                        ),
                        models.FormItem(
                            id="thruster_status_val",
                            label="Thruster Status",
                            item_type=models.FormItemTypeEnum.DROPDOWN,
                            options=["ON", "OFF", "N/A"],
                            required=True,
                        ),
                        models.FormItem(
                            id="obstacle_avoid_val",
                            label="Obstacle Avoidance",
                            item_type=models.FormItemTypeEnum.DROPDOWN,
                            options=["ON", "OFF", "N/A"],
                            required=True,
                        ),
                        models.FormItem(
                            id="line_follow_val",
                            label="Line Following Status",
                            item_type=models.FormItemTypeEnum.DROPDOWN,
                            options=["ON", "OFF", "N/A"],
                            required=True,
                        ),
                    ],
                ),
                models.FormSection(
                    id="operational_notes",
                    title="Operational Notes & Observations",
                    items=[
                        models.FormItem(
                            id="errors_notes_val",
                            label="Errors / System Messages",
                            item_type=models.FormItemTypeEnum.TEXT_AREA, # noqa
                            placeholder="Describe any errors or system messages...",
                        ),
                        models.FormItem(
                            id="boats_nearby_val",
                            label="Boats Nearby / AIS Contacts",
                            item_type=models.FormItemTypeEnum.TEXT_AREA, # noqa
                            placeholder="Describe nearby vessels or AIS contacts...",
                        ),
                    ],
                ),
                models.FormSection(
                    id="station_ops",
                    title="Station Operations",
                    items=[
                        models.FormItem(
                            id="current_station_val",
                            label="Current Station ID / Name",
                            item_type=models.FormItemTypeEnum.TEXT_INPUT,
                            placeholder="Enter station ID or name",
                        ),
                        models.FormItem(
                            id="offload_status_val",
                            label="Offload Status",
                            item_type=models.FormItemTypeEnum.DROPDOWN,
                            options=[
                                "Connecting to Station",
                                "Connected to Station",
                                "Offloading Data",
                                "Aborting Offload",
                                "N/A",
                            ],
                            required=True,  # Assuming this is required
                        ),
                    ],
                ),
                models.FormSection(
                    id="payload_status",
                    title="Payload Systems Status",
                    items=[
                        models.FormItem(
                            id="payload_airmar_val",
                            label="Airmar Weather",
                            item_type=models.FormItemTypeEnum.DROPDOWN,
                            options=["ON", "OFF", "N/A", "ERROR"],
                            required=True,
                        ),
                        models.FormItem(
                            id="payload_waterspeed_val",
                            label="Water Speed Sensor",
                            item_type=models.FormItemTypeEnum.DROPDOWN,
                            options=["ON", "OFF", "N/A", "ERROR"],
                            required=True,
                        ),
                        models.FormItem(
                            id="payload_ctd_val",
                            label="CTD",
                            item_type=models.FormItemTypeEnum.DROPDOWN,
                            options=["ON", "OFF", "N/A", "ERROR"],
                            required=True,
                        ),
                        models.FormItem(
                            id="payload_gpswaves_val",
                            label="GPSWaves",
                            item_type=models.FormItemTypeEnum.DROPDOWN,
                            options=["ON", "OFF", "N/A", "ERROR"],
                            required=True,
                        ),
                        models.FormItem(
                            id="payload_fluoro_val",
                            label="Fluorometer",
                            item_type=models.FormItemTypeEnum.DROPDOWN,
                            options=["ON", "OFF", "N/A", "ERROR"],
                            required=True,
                        ),
                        models.FormItem(
                            id="payload_mobilerx_val",
                            label="MobileRX (T1)",
                            item_type=models.FormItemTypeEnum.DROPDOWN,
                            options=["ON", "OFF", "N/A", "ERROR"],
                            required=True,
                        ),
                        models.FormItem(
                            id="payload_adcp_val",  # Corrected from vm4 to adcp as per your list order
                            label="ADCP",
                            item_type=models.FormItemTypeEnum.DROPDOWN,
                            options=["ON", "OFF", "N/A", "ERROR"],
                            required=True,
                        ),
                        models.FormItem(
                            id="payload_vm4_val",  # Corrected from adcp to vm4 as per your list order
                            label="VM4",
                            item_type=models.FormItemTypeEnum.DROPDOWN,
                            options=["ON", "OFF", "N/A", "ERROR"],
                            required=True,
                        ),
                        models.FormItem(
                            id="payload_co2pro_val",
                            label="CO2Pro",
                            item_type=models.FormItemTypeEnum.DROPDOWN,
                            options=["ON", "OFF", "N/A", "ERROR"],
                            required=True,
                        ),
                    ],
                ),
            ],
        )
    # Add other form types here
    raise HTTPException(status_code=404, detail=f"Form type '{form_type}' not found.")

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
        schema = await get_example_form_schema(form_type, mission_id, current_user)
        return schema
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


# --- Station Metadata API Endpoints ---
# The Station Metadata API Endpoints are now handled by the station_api sub-application
# mounted at "/api". The routes within station_sub_app.py are defined relative to that mount point
# (e.g., "/station_metadata/").


# --- Admin User Management API Endpoints ---
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

    # Resample to hourly mean (similar to your plotting scripts)
    data_to_resample = recent_data.set_index("Timestamp")
    numeric_cols = data_to_resample.select_dtypes(include=[np.number])
    # Ensure numeric_cols is not empty before resampling
    if numeric_cols.empty:
        logger.info(
            f"No numeric data to resample for {report_type.value}, "
            f"mission {mission_id} after filtering."
        )
        return JSONResponse(content=[])

    # Resample to hourly mean
    hourly_data = numeric_cols.resample("1h").mean().reset_index()

    if report_type == "vr2c" and "PingCount" in hourly_data.columns:
        hourly_data = hourly_data.sort_values(
            by="Timestamp"
        )  # Ensure sorted for correct diff
        hourly_data["PingCountDelta"] = hourly_data["PingCount"].diff()
        # The first PingCountDelta will be NaN, which is fine for plotting (Chart.js handles nulls)
    # Convert Timestamp objects to ISO 8601 strings for JSON serialization
    if "Timestamp" in hourly_data.columns:
        hourly_data["Timestamp"] = hourly_data["Timestamp"].dt.strftime(
            "%Y-%m-%dT%H:%M:%S"
        )

    # Replace NaN with None for JSON compatibility
    hourly_data = hourly_data.replace({np.nan: None})
    return JSONResponse(content=hourly_data.to_dict(orient="records"))


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
    # current_user: models.User = Depends(get_current_active_user) # Remove direct auth dependency for HTML page
):
    # Attempt to get current user, but don't require it for serving the page.
    # The JS on the page will handle auth checks for API calls.
    actual_current_user: Optional[models.User] = await get_optional_current_user(
        request
    )
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
        "view_forms.html", {"request": request, "current_user": current_user}
    )


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
        "view_station_status.html", {"request": request, "current_user": current_user}
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
        "admin_user_management.html", {"request": request, "current_user": current_user}
    )
