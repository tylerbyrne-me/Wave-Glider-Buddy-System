import asyncio
import json  # For saving/loading forms to/from JSON
import calendar # For month range calculation
import shutil
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# --- Configure Logging ---
logging.basicConfig(level=logging.INFO, format='%(levelname)-5.5s [%(name)s] %(message)s')

# Configure dedicated loggers for different data types
def setup_dedicated_loggers():
    """Set up dedicated loggers for user activity, cache stats, and mission usage"""
    
    # User Activity Logger
    user_activity_logger = logging.getLogger('user_activity')
    user_activity_handler = logging.FileHandler('logs/user_activity.log')
    user_activity_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
    user_activity_logger.addHandler(user_activity_handler)
    user_activity_logger.setLevel(logging.INFO)
    user_activity_logger.propagate = False
    
    # Cache Statistics Logger
    cache_stats_logger = logging.getLogger('cache_stats')
    cache_stats_handler = logging.FileHandler('logs/cache_statistics.log')
    cache_stats_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
    cache_stats_logger.addHandler(cache_stats_handler)
    cache_stats_logger.setLevel(logging.INFO)
    cache_stats_logger.propagate = False
    
    # Mission Usage Logger
    mission_usage_logger = logging.getLogger('mission_usage')
    mission_usage_handler = logging.FileHandler('logs/mission_usage.log')
    mission_usage_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
    mission_usage_logger.addHandler(mission_usage_handler)
    mission_usage_logger.setLevel(logging.INFO)
    mission_usage_logger.propagate = False
    
    return user_activity_logger, cache_stats_logger, mission_usage_logger

# Create logs directory if it doesn't exist
import os
os.makedirs('logs', exist_ok=True)

# Initialize dedicated loggers
user_activity_logger, cache_stats_logger, mission_usage_logger = setup_dedicated_loggers()

from typing import Annotated, Dict, List, Optional, Tuple, Any
from collections import defaultdict 

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

from .core import auth  # Import the auth module itself for its functions
# Specific user-related functions will be called via auth.func_name(session, ...)
from .core.auth import (get_current_active_user, get_current_admin_user,
                         get_optional_current_user)
from .config import settings
from .core import models  # type: ignore
from .core import (forecast, loaders, processors, summaries, utils, feature_toggles, template_context, reporting) # type: ignore
from .core.security import create_access_token, verify_password
from .core.db import SQLModelSession, get_db_session, sqlite_engine
from .core.scheduler import set_scheduler
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
from .routers import sensor_csv as sensor_csv_router
from .routers import map_router, live_kml_router
from .routers import knowledge_base as knowledge_base_router
from .routers import user_notes as user_notes_router
from .routers import shared_tips as shared_tips_router
from .routers import chatbot as chatbot_router

# Admin imports
from .core.admin_sqladmin import setup_sqladmin

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
app.include_router(sensor_csv_router.router)
app.include_router(map_router.router)
app.include_router(live_kml_router.router)
app.include_router(knowledge_base_router.router)
app.include_router(user_notes_router.router)
app.include_router(shared_tips_router.router)
app.include_router(chatbot_router.router)

# SQLAdmin will be initialized in startup_event with the app instance
# No need to mount separately - it's integrated into the app during setup

logger = logging.getLogger(__name__)
logger.info("--- FastAPI application module loaded. This should appear on every server start/reload. ---")

# --- Import template context helper ---
from .core.template_context import get_template_context

# ---

# Import cache and utilities from data_service (no circular dependency - app imports from core)
from .core.data_service import (
    data_cache,
    CACHE_STRATEGIES,
    CACHE_EXPIRY_MINUTES,
    user_activity,
    user_sessions,
    cache_stats,
    create_time_aware_cache_key,
    get_cache_strategy,
    is_static_data_source,
    trim_data_to_range,
    update_cache_stats,
    update_user_activity,
    load_data_with_overlap,
)

# In-memory store for submitted forms. This will be populated from a local JSON file on startup.
# Key: (mission_id, form_type, submission_timestamp_iso) -> MissionFormDataResponse
mission_forms_db: Dict[Tuple[str, str, str], models.MissionFormDataResponse] = {}


# --- Enhanced Caching Utilities ---
# NOTE: Cache utilities are now in app.core.data_service
# These are imported above for backward compatibility with app.py functions


async def initialize_startup_cache():
    """
    Initialize cache with all active mission data on startup.
    This ensures all data is available immediately without user-triggered loading.
    """
    logger.info("STARTUP: Initializing comprehensive data cache...")
    
    # Check feature toggle status
    local_data_loading_enabled = feature_toggles.is_feature_enabled("local_data_loading")
    logger.info(f"STARTUP: Local data loading feature toggle: {'ENABLED' if local_data_loading_enabled else 'DISABLED'}")
    
    # Get all active missions, filtering out empty strings
    active_missions = [m for m in settings.active_realtime_missions if m and m.strip()]
    if not active_missions:
        logger.warning("STARTUP: No valid active real-time missions found. Skipping cache initialization.")
        return 0
    logger.info(f"STARTUP: Caching data for {len(active_missions)} active missions: {active_missions}")
    
    # Get all incremental report types
    incremental_types = [report_type for report_type, strategy in CACHE_STRATEGIES.items() 
                        if strategy.get("incremental", False)]
    
    logger.info(f"STARTUP: Caching {len(incremental_types)} incremental data types: {incremental_types}")
    
    # Cache data for each mission and report type
    total_cached = 0
    for mission_id in active_missions:
        logger.info(f"STARTUP: Caching data for mission {mission_id}")
        
        for report_type in incremental_types:
            try:
                # Determine source preference: try local first if feature toggle is enabled
                source_pref_for_cache = "remote"  # Default
                if feature_toggles.is_feature_enabled("local_data_loading"):
                    source_pref_for_cache = "local"
                
                # Load data for the last 24 hours to get a good baseline
                cache_key = create_time_aware_cache_key(
                    report_type, mission_id, None, None, 24, source_pref_for_cache, None
                )
                
                # Check if already cached
                if cache_key in data_cache:
                    logger.debug(f"STARTUP: {report_type} for {mission_id} already cached")
                    continue
                
                # Determine source preference: try local first if feature toggle is enabled
                if feature_toggles.is_feature_enabled("local_data_loading"):
                    # Try local first during startup if feature is enabled
                    # Use system access mode to bypass admin check during startup
                    logger.info(f"STARTUP: Local data loading enabled, attempting local load for {report_type} ({mission_id})")
                    df, source_path, _ = await load_data_with_overlap(
                        report_type, mission_id, 
                        start_date=None, end_date=None, hours_back=24,
                        overlap_hours=CACHE_STRATEGIES[report_type]["overlap_hours"],
                        source_preference="local", custom_local_path=None, 
                        current_user=None, allow_system_access=True
                    )
                    
                    # If local failed, try remote as fallback
                    if df is None or df.empty:
                        logger.info(f"STARTUP: Local load failed for {report_type} ({mission_id}), trying remote fallback")
                    else:
                        logger.info(f"STARTUP: Successfully loaded {report_type} ({mission_id}) from local: {source_path}")
                        df, source_path, _ = await load_data_with_overlap(
                            report_type, mission_id, 
                            start_date=None, end_date=None, hours_back=24,
                            overlap_hours=CACHE_STRATEGIES[report_type]["overlap_hours"],
                            source_preference="remote", custom_local_path=None, current_user=None
                        )
                else:
                    # Feature toggle disabled, use remote only
                    df, source_path, _ = await load_data_with_overlap(
                        report_type, mission_id, 
                        start_date=None, end_date=None, hours_back=24,
                        overlap_hours=CACHE_STRATEGIES[report_type]["overlap_hours"],
                        source_preference="remote", custom_local_path=None, current_user=None
                    )
                
                if not df.empty:
                    # Store in cache with proper datetime conversion
                    last_timestamp = None
                    if hasattr(df.index, 'max') and not df.empty:
                        max_ts = df.index.max()
                        if hasattr(max_ts, 'to_pydatetime'):
                            last_timestamp = max_ts.to_pydatetime()
                        elif isinstance(max_ts, (int, float)):
                            last_timestamp = datetime.fromtimestamp(max_ts, tz=timezone.utc)
                        else:
                            last_timestamp = pd.to_datetime(max_ts, utc=True)
                    
                    data_cache[cache_key] = (
                        df, source_path, datetime.now(timezone.utc), 
                        last_timestamp, None  # file_modification_time not available during startup
                    )
                    total_cached += 1
                    logger.debug(f"STARTUP: Cached {report_type} for {mission_id} ({len(df)} records)")
                else:
                    # Only log at debug level - missing data is expected for some missions/report types
                    logger.debug(f"STARTUP: No data found for {report_type} on {mission_id}")
                    
            except Exception as e:
                logger.error(f"STARTUP: Error caching {report_type} for {mission_id}: {e}")
                continue
    
    logger.info(f"STARTUP: Cache initialization complete. Cached {total_cached} data sources.")
    return total_cached

# NOTE: update_user_activity is now in app.core.data_service
# Imported above for backward compatibility

def get_active_users(minutes_threshold: int = 30) -> List[str]:
    """Get list of users who have been active within the threshold"""
    now = datetime.now(timezone.utc)
    threshold_time = now - timedelta(minutes=minutes_threshold)
    
    active_users = []
    for user_id, last_activity in user_activity.items():
        if last_activity >= threshold_time:
            active_users.append(user_id)
    
    return active_users

def update_cache_stats(
    report_type: str, 
    mission_id: str, 
    cache_hit: bool, 
    data_size_mb: float = 0.0,
    is_refresh: bool = False
) -> None:
    """Update cache statistics"""
    cache_stats["total_requests"] += 1
    
    if cache_hit:
        cache_stats["hits"] += 1
        cache_stats["by_report_type"][report_type]["hits"] += 1
        cache_stats["by_mission"][mission_id]["hits"] += 1
    else:
        cache_stats["misses"] += 1
        cache_stats["by_report_type"][report_type]["misses"] += 1
        cache_stats["by_mission"][mission_id]["misses"] += 1
    
    if is_refresh:
        cache_stats["refreshes"] += 1
        cache_stats["by_report_type"][report_type]["refreshes"] += 1
        cache_stats["by_mission"][mission_id]["refreshes"] += 1
    
    if data_size_mb > 0:
        cache_stats["data_volume_mb"] += data_size_mb
        cache_stats["by_report_type"][report_type]["data_volume_mb"] += data_size_mb
        cache_stats["by_mission"][mission_id]["data_volume_mb"] += data_size_mb
    
    # Log cache statistics
    hit_rate = (cache_stats["hits"] / cache_stats["total_requests"] * 100) if cache_stats["total_requests"] > 0 else 0
    cache_stats_logger.info(f"CACHE_STATS: report_type={report_type}, mission_id={mission_id}, "
                           f"cache_hit={cache_hit}, data_size_mb={data_size_mb:.2f}, "
                           f"is_refresh={is_refresh}, overall_hit_rate={hit_rate:.2f}%")

def get_cache_stats() -> Dict[str, Any]:
    """Get current cache statistics"""
    total_requests = cache_stats["total_requests"]
    hit_rate = (cache_stats["hits"] / total_requests * 100) if total_requests > 0 else 0
    miss_rate = (cache_stats["misses"] / total_requests * 100) if total_requests > 0 else 0
    
    return {
        "overall": {
            "hits": cache_stats["hits"],
            "misses": cache_stats["misses"],
            "refreshes": cache_stats["refreshes"],
            "total_requests": total_requests,
            "hit_rate_percent": round(hit_rate, 2),
            "miss_rate_percent": round(miss_rate, 2),
            "data_volume_mb": round(cache_stats["data_volume_mb"], 2),
            "last_reset": cache_stats["last_reset"].isoformat(),
            "cache_size": len(data_cache),
            "cache_max_size": data_cache.maxsize
        },
        "by_report_type": dict(cache_stats["by_report_type"]),
        "by_mission": dict(cache_stats["by_mission"]),
        "active_users": {
            "count": len(get_active_users()),
            "users": get_active_users(),
            "sessions": {k: v for k, v in user_sessions.items() if k in get_active_users()}
        }
    }

def generate_usage_summary_report() -> Dict[str, Any]:
    """Generate a summary report from the dedicated log files"""
    try:
        import os
        from collections import defaultdict, Counter
        
        summary = {
            "user_activity": {"total_sessions": 0, "total_activities": 0, "unique_users": set()},
            "mission_usage": {"total_requests": 0, "missions_accessed": set(), "report_types_accessed": set()},
            "cache_performance": {"total_requests": 0, "hits": 0, "misses": 0, "hit_rate": 0.0},
            "log_files": {"user_activity": False, "cache_statistics": False, "mission_usage": False}
        }
        
        # Check if log files exist and get basic stats
        log_files = {
            "user_activity": "logs/user_activity.log",
            "cache_statistics": "logs/cache_statistics.log", 
            "mission_usage": "logs/mission_usage.log"
        }
        
        for log_type, log_path in log_files.items():
            if os.path.exists(log_path):
                summary["log_files"][log_type] = True
                with open(log_path, 'r') as f:
                    lines = f.readlines()
                    summary[f"{log_type}_count"] = len(lines)
        
        # Get current in-memory stats
        current_stats = get_cache_stats()
        summary["current_cache_stats"] = current_stats
        
        return summary
        
    except Exception as e:
        logger.error(f"Error generating usage summary report: {e}")
        return {"error": str(e)}


def get_latest_timestamp_from_cache(
    report_type: str,
    mission_id: str,
    source_preference: Optional[str] = None,
    custom_local_path: Optional[str] = None
) -> Optional[datetime]:
    """
    Get the latest timestamp from the cache for a given report type and mission.
    Checks all cache entries (full dataset, hours_back variations) to find the absolute latest.
    
    Args:
        report_type: Type of report (e.g., 'power', 'ctd', 'telemetry')
        mission_id: Mission identifier
        source_preference: 'local' or 'remote'
        custom_local_path: Custom local path if specified
        
    Returns:
        The latest timestamp found in any cache entry, or None if not found
    """
    latest_timestamp = None
    
    # Check multiple cache key variations to find the latest timestamp
    # Priority: full_dataset > specific hours_back entries
    cache_keys_to_check = [
        create_time_aware_cache_key(report_type, mission_id, None, None, None, source_preference, custom_local_path),  # Full dataset
    ]
    
    # Also check common hours_back values (24, 48, 72 hours) as they might have newer data
    for hours in [24, 48, 72, 168]:
        cache_keys_to_check.append(
            create_time_aware_cache_key(report_type, mission_id, None, None, hours, source_preference, custom_local_path)
        )
    
    for cache_key in cache_keys_to_check:
        if cache_key in data_cache:
            cached_df, _, _, last_data_timestamp, _ = data_cache[cache_key]
            
            # Use the stored last_data_timestamp first
            if last_data_timestamp is not None:
                if latest_timestamp is None or last_data_timestamp > latest_timestamp:
                    latest_timestamp = last_data_timestamp
            # Fallback: calculate from DataFrame if last_data_timestamp not available
            elif cached_df is not None and not cached_df.empty and "Timestamp" in cached_df.columns:
                try:
                    df_timestamp = cached_df["Timestamp"].max()
                    if pd.notna(df_timestamp):
                        if isinstance(df_timestamp, pd.Timestamp):
                            df_timestamp = df_timestamp.to_pydatetime()
                        elif not isinstance(df_timestamp, datetime):
                            df_timestamp = pd.to_datetime(df_timestamp, utc=True)
                        
                        if latest_timestamp is None or df_timestamp > latest_timestamp:
                            latest_timestamp = df_timestamp
                except Exception as e:
                    logger.debug(f"Error extracting timestamp from cache for {report_type}/{mission_id}: {e}")
    
    return latest_timestamp


def trim_data_to_range(
    df: pd.DataFrame, 
    start_date: Optional[datetime], 
    end_date: Optional[datetime], 
    hours_back: Optional[int]
) -> pd.DataFrame:
    """
    Trim the cached data to the exact requested range.
    
    NOTE: This function is kept for backward compatibility but delegates to 
    app.core.data_service.trim_data_to_range which has the updated logic.
    
    Args:
        df: DataFrame to trim
        start_date: Start date for trimming
        end_date: End date for trimming
        hours_back: Hours back from the last recorded data point (not from now)
        
    Returns:
        Trimmed DataFrame
    """
    # Delegate to the data_service version which has the updated logic
    from app.core.data_service import trim_data_to_range as data_service_trim
    return data_service_trim(df, start_date, end_date, hours_back)


def merge_data_with_overlap(
    new_df: pd.DataFrame, 
    existing_df: pd.DataFrame, 
    last_known_timestamp: datetime
) -> pd.DataFrame:
    """
    Merge new data with existing data, handling overlap to prevent gaps.
    
    Args:
        new_df: Newly loaded data
        existing_df: Previously cached data
        last_known_timestamp: Last known timestamp from existing data
        
    Returns:
        Merged DataFrame with duplicates removed
    """
    if existing_df.empty:
        return new_df
    
    if new_df.empty:
        return existing_df
    
    # Combine dataframes
    combined_df = pd.concat([existing_df, new_df], ignore_index=True)
    
    # Remove duplicates based on timestamp, keeping the most recent
    if "Timestamp" in combined_df.columns:
        combined_df = combined_df.drop_duplicates(subset=["Timestamp"], keep="last")
        combined_df = combined_df.sort_values("Timestamp").reset_index(drop=True)
    
    return combined_df





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
            # from the USER_COLORS palette in auth.
            # SECURITY: Default user credentials are now loaded from .env via settings
            default_user_color_idx = 0
            default_users_data = [
                {
                    "username": settings.default_admin_username,
                    "full_name": "Admin User",
                    "email": settings.default_admin_email,
                    "password": settings.default_admin_password,
                    "role": models.UserRoleEnum.admin,
                    "color": auth.USER_COLORS[default_user_color_idx % len(auth.USER_COLORS)],
                    "disabled": False,
                },
                {
                    "username": settings.default_pilot_username,
                    "full_name": "Pilot User",
                    "email": settings.default_pilot_email,
                    "password": settings.default_pilot_password,
                    "role": models.UserRoleEnum.pilot,
                    "color": auth.USER_COLORS[(default_user_color_idx + 1) % len(auth.USER_COLORS)],
                    "disabled": False,
                },
                {
                    "username": settings.default_pilot_rt_username,
                    "full_name": "Realtime Pilot",
                    "email": settings.default_pilot_rt_email,
                    "password": settings.default_pilot_rt_password,
                    "role": models.UserRoleEnum.pilot,
                    "color": auth.USER_COLORS[(default_user_color_idx + 2) % len(auth.USER_COLORS)],
                    "disabled": False,
                },
                {
                    "username": settings.default_lri_pilot_username, # Special user for LRI-blocked shifts
                    "full_name": "LRI Piloting Block",
                    "email": settings.default_lri_pilot_email,
                    "password": settings.default_lri_pilot_password, # Password doesn't matter as user is disabled
                    "role": models.UserRoleEnum.pilot, # Can be pilot or a new 'lri' role if needed
                    "color": "#ADD8E6", # Light Blue for LRI blocks
                    "disabled": True, # LRI_PILOT cannot log in
                },
            ]

            # Check for each default user and create if missing
            # SECURITY: Validate that passwords are set in .env before creating users
            for user_data_dict in default_users_data:
                username = user_data_dict["username"]
                password = user_data_dict["password"]
                
                # Skip LRI_PILOT password check since it's disabled anyway
                if username != settings.default_lri_pilot_username and not password:
                    logger.warning(
                        f"SECURITY WARNING: Password for default user '{username}' not set in .env. "
                        f"Skipping creation of this user. Set DEFAULT_{username.upper()}_PASSWORD in .env file."
                    )
                    continue
                
                existing_user = auth.get_user_from_db(session, username)
                if not existing_user:
                    logger.info(f"Default user '{username}' not found. Creating...")
                    user_create_model = models.UserCreate(**user_data_dict)
                    auth.add_user_to_db(session, user_create_model)
                else:
                    logger.info(f"Default user '{username}' already exists.")
                    # Update password if it's set in .env (allows syncing .env passwords to existing users)
                    if password:
                        logger.info(f"Updating password for existing default user '{username}' from .env configuration.")
                        auth.update_user_password_in_db(session, username, password)
                    else:
                        logger.info(f"Skipping password update for '{username}' - no password set in .env.")

            # Reset the color index based on all users, to avoid re-assigning colors on restart
            all_users_statement = select(models.UserInDB)
            all_users_in_db = session.exec(all_users_statement).all()
            auth.next_color_index = len(all_users_in_db)
            logger.info(f"Color index reset to {auth.next_color_index} based on {len(all_users_in_db)} total users.")
        else:
            logger.error(
                f"'{models.UserInDB.__tablename__}' table still does not exist "
                "after create_db_and_tables(). DB init failed."
            )

async def _load_from_local_sources(
    report_type: str, mission_id: str, custom_local_path: Optional[str],
    current_user: Optional[models.User] = None,
    allow_system_access: bool = False
) -> Tuple[Optional[pd.DataFrame], str, Optional[datetime]]:
    """
    Helper to attempt loading data from local sources (custom then default).
    
    Local data loading is restricted to admin users only and requires the
    'local_data_loading' feature toggle to be enabled.
    """
    # Check if local data loading is enabled
    if not feature_toggles.is_feature_enabled("local_data_loading"):
        logger.info("Local data loading is disabled via feature toggle.")
        return None, "Local (Disabled): Feature toggle not enabled", None
    
    # Admin check: skip if system access is allowed (for startup/system operations)
    if not allow_system_access:
        if not current_user or current_user.role != models.UserRoleEnum.admin:
            logger.warning(
                f"Non-admin user '{current_user.username if current_user else 'anonymous'}' "
                f"attempted to load local data for {report_type} ({mission_id}). Access denied."
            )
            return None, "Local (Restricted): Admin access required", None
    else:
        logger.info(f"System access allowed for local data loading: {report_type} ({mission_id})")
    
    df = None
    actual_source_path = "Data not loaded"
    _attempted_custom_local = False

    if custom_local_path:
        _custom_local_path_str = f"Local (Custom): {Path(custom_local_path) / mission_id}"
        try:
            logger.info(
                f"Attempting local load for {report_type} (mission: {mission_id}) from custom path: {custom_local_path}"
            )
            df_attempt, file_mod_time = await loaders.load_report(report_type, mission_id, base_path=Path(custom_local_path))
            _attempted_custom_local = True
            if df_attempt is not None and not df_attempt.empty:
                return df_attempt, _custom_local_path_str, file_mod_time
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
            logger.info(
                f"Attempting local load for {report_type} (mission: {mission_id}) from default path: {settings.local_data_base_path}"
            )
            df_attempt, file_mod_time = await loaders.load_report(report_type, mission_id, base_path=settings.local_data_base_path)
            _attempted_default_local = True
            if df_attempt is not None and not df_attempt.empty:
                return df_attempt, _default_local_path_str, file_mod_time
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

    return None, actual_source_path, None


async def _load_from_remote_sources(
    report_type: str, mission_id: str, current_user: Optional[models.User]
) -> Tuple[Optional[pd.DataFrame], str, Optional[datetime]]:
    """Helper to attempt loading data from remote sources based on user role."""
    actual_source_path = "Data not loaded"
    remote_mission_folder = settings.remote_mission_folder_map.get(mission_id, mission_id)
    base_remote_url = settings.remote_data_url.rstrip("/")
    remote_base_urls_to_try: List[str] = []
    user_role = current_user.role if current_user else models.UserRoleEnum.admin

    if user_role in [models.UserRoleEnum.admin, models.UserRoleEnum.pilot]:
        remote_base_urls_to_try.extend([
            f"{base_remote_url}/output_realtime_missions",
            f"{base_remote_url}/output_past_missions",
        ])

    last_accessed_remote_path_if_empty = None
    for constructed_base_url in remote_base_urls_to_try:
        # Configure client with retries, using RETRY_COUNT from loaders for consistency
        retry_transport = httpx.AsyncHTTPTransport(retries=loaders.RETRY_COUNT)
        async with httpx.AsyncClient(transport=retry_transport) as client: # Manage client per attempt
            try:
                logger.debug(f"Attempting remote load for {report_type} (mission: {mission_id}, remote folder: {remote_mission_folder}) from base: {constructed_base_url}")
                df_attempt, file_mod_time = await loaders.load_report(report_type, mission_id=remote_mission_folder, base_url=constructed_base_url, client=client)
                if df_attempt is not None and not df_attempt.empty:
                    actual_source_path = f"Remote: {constructed_base_url}/{remote_mission_folder}"
                    logger.debug(f"Successfully loaded {report_type} for mission {mission_id} from {actual_source_path}")
                    return df_attempt, actual_source_path, file_mod_time
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
        return None, last_accessed_remote_path_if_empty, None
    return None, actual_source_path, None

def _apply_date_filtering(df: pd.DataFrame, report_type: str, start_date: datetime, end_date: datetime) -> pd.DataFrame:
    """
    Apply date filtering to a DataFrame based on the report type and timestamp column.
    Returns the filtered DataFrame.
    """
    # Map report types to their raw timestamp column names (before preprocessing)
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
        "ais": "lastSeenTimestamp",  # Fixed: AIS uses lastSeenTimestamp
        "errors": "gliderTimeStamp",
        "wave_frequency_spectrum": "timeStamp",  # Wave spectrum uses timeStamp
        "wave_energy_spectrum": "timeStamp",    # Wave spectrum uses timeStamp
    }
    
    # First try the specific timestamp column for this report type
    timestamp_col = timestamp_columns.get(report_type)
    
    # If the specific column doesn't exist, try to find any timestamp-like column
    if not timestamp_col or timestamp_col not in df.columns:
        for col in df.columns:
            lower_col = col.lower()
            if "time" in lower_col or col in [
                "timeStamp",
                "gliderTimeStamp", 
                "lastLocationFix",
                "lastSeenTimestamp",
            ]:
                timestamp_col = col
                break
    
    if not timestamp_col or timestamp_col not in df.columns:
        logger.warning(f"No timestamp column found for {report_type}, skipping date filtering. Available columns: {df.columns.tolist()}")
        return df
    
    try:
        # Convert timestamp column to datetime if it's not already
        if not pd.api.types.is_datetime64_any_dtype(df[timestamp_col]):
            # Use robust parser to handle mixed formats (ISO 8601 and 12hr AM/PM)
            df[timestamp_col] = utils.parse_timestamp_column(
                df[timestamp_col], errors='coerce', utc=True
            )
        
        # Remove rows with invalid timestamps (NaT) and epoch dates before filtering
        # This prevents 1969 epoch dates from appearing in results
        valid_timestamps_mask = df[timestamp_col].notna()
        
        # Filter out epoch dates (typically 1970-01-01 or 1969-12-31) which indicate parsing failures
        # Use the minimum valid timestamp constant from utils
        min_valid_date = utils.MIN_VALID_TIMESTAMP
        valid_timestamps_mask = valid_timestamps_mask & (df[timestamp_col] >= min_valid_date)
        
        invalid_count = (~valid_timestamps_mask).sum()
        if invalid_count > 0:
            logger.warning(
                f"Removing {invalid_count} rows with invalid timestamps (NaT or pre-2000 dates) "
                f"from {report_type} (column: {timestamp_col})"
            )
        df = df[valid_timestamps_mask].copy()
        
        # Check if any valid data remains
        if df.empty:
            logger.warning(f"All timestamps invalid for {report_type} after parsing. Returning empty DataFrame.")
            return df
            
        # Ensure timezone awareness
        if start_date.tzinfo is None:
            start_date = start_date.replace(tzinfo=timezone.utc)
        if end_date.tzinfo is None:
            end_date = end_date.replace(tzinfo=timezone.utc)
        
        # Apply date filtering
        mask = (df[timestamp_col] >= start_date) & (df[timestamp_col] <= end_date)
        filtered_df = df[mask].copy()
        
        # Calculate actual date range for logging (exclude NaT values)
        if not filtered_df.empty:
            actual_start = filtered_df[timestamp_col].min()
            actual_end = filtered_df[timestamp_col].max()
            logger.info(f"Date filtering applied to {report_type}: {len(df)} -> {len(filtered_df)} records "
                       f"({actual_start.isoformat()} to {actual_end.isoformat()})")
        else:
            logger.info(f"Date filtering applied to {report_type}: {len(df)} -> {len(filtered_df)} records "
                       f"(requested: {start_date.isoformat()} to {end_date.isoformat()}, no matching data)")
        
        return filtered_df
        
    except Exception as e:
        logger.warning(f"Error applying date filtering to {report_type}: {e}. Proceeding without time filtering.")
        return df


async def load_data_source(
    report_type: str,
    mission_id: str,
    source_preference: Optional[str] = None,  # 'local' or 'remote'
    custom_local_path: Optional[str] = None,
    force_refresh: bool = False,  # New parameter to bypass cache
    current_user: Optional[models.User] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    hours_back: Optional[int] = None,
):
    """
    Enhanced load_data_source with time-aware caching and overlap-based gap prevention.
    
    This is now a wrapper around the DataService for backward compatibility.
    New code should use DataService directly to avoid circular dependencies.
    
    Args:
        report_type: Type of report to load
        mission_id: Mission identifier
        source_preference: 'local' or 'remote'
        custom_local_path: Custom local path if specified
        force_refresh: Bypass cache and force refresh
        current_user: Current user for access control
        start_date: Start date for time range
        end_date: End date for time range
        hours_back: Hours back from now
        
    Returns:
        Tuple of (DataFrame, source_path, file_modification_time)
    """
    # Import here to avoid circular dependency at module level
    from .core.data_service import get_data_service
    
    data_service = get_data_service()
    return await data_service.load(
        report_type=report_type,
        mission_id=mission_id,
        source_preference=source_preference,
        custom_local_path=custom_local_path,
        force_refresh=force_refresh,
        current_user=current_user,
        start_date=start_date,
        end_date=end_date,
        hours_back=hours_back,
    )


async def load_data_with_overlap(
    report_type: str,
    mission_id: str,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    hours_back: Optional[int] = None,
    overlap_hours: int = 1,
    source_preference: Optional[str] = None,
    custom_local_path: Optional[str] = None,
    current_user: Optional[models.User] = None,
    allow_system_access: bool = False
) -> Tuple[pd.DataFrame, str, Optional[datetime]]:
    """
    Load data with overlap to prevent gaps.
    
    Args:
        report_type: Type of report to load
        mission_id: Mission identifier
        start_date: Start date for time range
        end_date: End date for time range
        hours_back: Hours back from now
        overlap_hours: Hours of overlap to add
        source_preference: 'local' or 'remote'
        custom_local_path: Custom local path if specified
        current_user: Current user for access control
        
    Returns:
        Tuple of (DataFrame, source_path)
    """
    
    # Calculate the actual range to fetch (with overlap)
    if start_date and end_date:
        # Extend range by overlap_hours
        actual_start = start_date - timedelta(hours=overlap_hours)
        actual_end = end_date + timedelta(hours=overlap_hours)
    elif hours_back:
        # Extend hours_back by overlap - always use UTC
        actual_hours = hours_back + overlap_hours
        actual_start = datetime.now(timezone.utc) - timedelta(hours=actual_hours)
        actual_end = datetime.now(timezone.utc)
    else:
        # Full dataset - no overlap needed
        actual_start = None
        actual_end = None
    
    # Load data using existing logic but with extended range
    df: Optional[pd.DataFrame] = None
    actual_source_path = "Data not loaded"
    
    load_attempted = False
    file_modification_time = None
    if source_preference == "local":  # Local-only preference (admin only, feature toggle required)
        load_attempted = True
        df, actual_source_path, file_modification_time = await _load_from_local_sources(report_type, mission_id, custom_local_path, current_user, allow_system_access=allow_system_access)
    elif source_preference == "remote" or source_preference is None:
        # Default behavior: remote-only (no local fallback)
        # Local is never used as default - only when explicitly requested by admin
        load_attempted = True
        df, actual_source_path, file_modification_time = await _load_from_remote_sources(report_type, mission_id, current_user)
        if df is None:
            # Only log at debug level to reduce noise - remote failures are expected when data isn't available
            logger.debug(f"Remote load failed for {report_type} ({mission_id}). No local fallback (remote-only mode).")
    
    if not load_attempted:
        logger.error(f"No load attempt for {report_type} ({mission_id}) with pref '{source_preference}'. Unexpected.")
    
    # Apply time filtering to the extended range using raw timestamp column names
    if df is not None and not df.empty and actual_start and actual_end:
        df = _apply_date_filtering(df, report_type, actual_start, actual_end)
    
    return df if df is not None else pd.DataFrame(), actual_source_path, file_modification_time


async def load_incremental_data_with_overlap(
    report_type: str,
    mission_id: str,
    last_known_timestamp: datetime,
    overlap_hours: int = 1,
    source_preference: Optional[str] = None,
    custom_local_path: Optional[str] = None,
    current_user: Optional[models.User] = None
) -> Tuple[pd.DataFrame, str, Optional[datetime]]:
    """
    Load only new data since last_known_timestamp, but with overlap to prevent gaps.
    
    Args:
        report_type: Type of report to load
        mission_id: Mission identifier
        last_known_timestamp: Last known timestamp from existing data
        overlap_hours: Hours of overlap to add
        source_preference: 'local' or 'remote'
        custom_local_path: Custom local path if specified
        current_user: Current user for access control
        
    Returns:
        Tuple of (DataFrame, source_path, file_modification_time)
    """
    
    # Start from overlap_hours before last known timestamp
    # Ensure last_known_timestamp is a datetime object
    if isinstance(last_known_timestamp, (int, float)):
        # Convert from timestamp to datetime
        last_known_timestamp = datetime.fromtimestamp(last_known_timestamp, tz=timezone.utc)
    elif hasattr(last_known_timestamp, 'to_pydatetime'):
        # Convert pandas timestamp to datetime
        last_known_timestamp = last_known_timestamp.to_pydatetime()
    elif not isinstance(last_known_timestamp, datetime):
        # Try to parse as datetime
        last_known_timestamp = pd.to_datetime(last_known_timestamp, utc=True)
    
    start_time = last_known_timestamp - timedelta(hours=overlap_hours)
    end_time = datetime.now(timezone.utc)
    
    # Load the extended range
    new_df, source_path, file_modification_time = await load_data_with_overlap(
        report_type, mission_id, 
        start_date=start_time, 
        end_date=end_time,
        overlap_hours=0,  # Already applied above
        source_preference=source_preference,
        custom_local_path=custom_local_path,
        current_user=current_user
    )
    
    # Get existing cached data to merge with
    cache_key = create_time_aware_cache_key(
        report_type, mission_id, None, None, None, source_preference, custom_local_path
    )
    
    if cache_key in data_cache:
        existing_df, _, _, _, _ = data_cache[cache_key]
        # Merge with overlap handling
        merged_df = merge_data_with_overlap(new_df, existing_df, last_known_timestamp)
        return merged_df, source_path, file_modification_time
    else:
        # No existing data to merge with
        return new_df, source_path, file_modification_time


# ---

# --- Background Cache Refresh Task (APScheduler instantiation temporarily commented out) ---
scheduler = AsyncIOScheduler()  # Uncomment APScheduler


async def refresh_active_mission_cache():
    """
    Smart background cache refresh that only refreshes stale data for active users.
    Uses data-type specific cache strategies and incremental loading.
    """
    logger.info(
        "BACKGROUND TASK: Starting smart cache refresh for active real-time missions."
    )
    
    # Get active users (last 30 minutes)
    active_users = get_active_users(minutes_threshold=30)
    if not active_users:
        logger.info("BACKGROUND TASK: No active users found. Skipping cache refresh.")
        mission_usage_logger.info("BACKGROUND_REFRESH: No active users found. Skipping cache refresh.")
        return
    
    logger.info(f"BACKGROUND TASK: Found {len(active_users)} active users: {active_users}")
    mission_usage_logger.info(f"BACKGROUND_REFRESH: Found {len(active_users)} active users: {active_users}")
    
    # Get missions accessed by active users
    active_missions = set()
    for user_id in active_users:
        if user_id in user_sessions:
            active_missions.update(user_sessions[user_id]["missions_accessed"])
    
    # Filter out historical missions - only refresh active real-time missions
    # Historical missions are those NOT in settings.active_realtime_missions
    # Also handle "1071-m169" format by extracting base mission ID (e.g., "m169")
    # Filter out empty strings from active_realtime_missions
    active_realtime_missions_set = set(m for m in settings.active_realtime_missions if m and m.strip())
    
    # Filter missions: only include those that are in active_realtime_missions
    # Handle both "m169" and "1071-m169" formats
    filtered_missions = []
    for mission_id in active_missions:
        # Extract base mission ID (e.g., "m169" from "1071-m169" or just "m169")
        base_mission_id = mission_id.split('-')[-1] if '-' in mission_id else mission_id
        
        # Check if this is an active real-time mission
        if base_mission_id in active_realtime_missions_set or mission_id in active_realtime_missions_set:
            filtered_missions.append(mission_id)
        else:
            logger.debug(f"BACKGROUND TASK: Skipping historical mission {mission_id} (not in active_realtime_missions)")
    
    # Fallback to configured active missions if no user activity or all missions were historical
    if not filtered_missions:
        # Filter out empty strings from configured active missions
        filtered_missions = [m for m in settings.active_realtime_missions if m and m.strip()]
        logger.info("BACKGROUND TASK: No active real-time missions from user activity. Using configured active missions.")
    else:
        logger.info(f"BACKGROUND TASK: Refreshing data for active real-time missions: {filtered_missions}")
    
    # Final check: ensure we have valid missions to refresh
    if not filtered_missions:
        logger.info("BACKGROUND TASK: No valid active real-time missions configured. Skipping cache refresh.")
        return
    
    active_missions = filtered_missions
    
    # Get database session for checking sensor card configurations
    from .core.db import SQLModelSession, sqlite_engine
    with SQLModelSession(sqlite_engine) as session:
        for mission_id in active_missions:
            logger.info(f"BACKGROUND TASK: Checking cache for active mission: {mission_id}")
            
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
                "navigation": "telemetry",
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
            
            # Determine which report types to check based on enabled sensor cards
            report_types_to_check = []
            for sensor_card in enabled_sensor_cards:
                if sensor_card in sensor_to_report_mapping:
                    report_types_to_check.append(sensor_to_report_mapping[sensor_card])
                    # Add solar data if power is enabled
                    if sensor_card == "power" and "solar" not in report_types_to_check:
                        report_types_to_check.append("solar")
            
            # Always include wave spectrum data if waves is enabled
            if "waves" in enabled_sensor_cards:
                if "wave_frequency_spectrum" not in report_types_to_check:
                    report_types_to_check.append("wave_frequency_spectrum")
                if "wave_energy_spectrum" not in report_types_to_check:
                    report_types_to_check.append("wave_energy_spectrum")
            
            # Check each report type and only refresh if stale
            refreshed_count = 0
            for report_type in report_types_to_check:
                try:
                    # Check if data needs refreshing
                    cache_key = create_time_aware_cache_key(
                        report_type, mission_id, None, None, None, "remote", None
                    )
                    
                    needs_refresh = False
                    if cache_key not in data_cache:
                        # No cached data - needs initial load
                        needs_refresh = True
                        logger.debug(f"BACKGROUND TASK: No cached data for {report_type} ({mission_id}) - will load")
                    else:
                        # Check if cached data is stale
                        cached_df, cached_source_path, cache_timestamp, last_data_timestamp, _ = data_cache[cache_key]
                        cache_strategy = get_cache_strategy(report_type)
                        
                        # Skip static data sources
                        if is_static_data_source(cached_source_path, report_type, mission_id):
                            logger.debug(f"BACKGROUND TASK: Skipping static data source {report_type} ({mission_id})")
                            continue
                        
                        # For incremental data types, always refresh to check for new data
                        # This ensures cache_timestamp is updated and frontend can detect refresh cycles
                        if cache_strategy.get("incremental", False):
                            # Always refresh incremental data types to check for updates
                            needs_refresh = True
                            logger.debug(f"BACKGROUND TASK: Refreshing incremental data type {report_type} ({mission_id}) to check for updates")
                        else:
                            # For non-incremental data, check expiry
                            expiry_minutes = cache_strategy["expiry_minutes"]
                            # Always use UTC for datetime operations
                            now = datetime.now(timezone.utc)
                            if cache_timestamp.tzinfo is None:
                                # If cache timestamp is naive, localize to UTC for comparison
                                cache_timestamp = cache_timestamp.replace(tzinfo=timezone.utc)
                            
                            # Only check expiry if expiry_minutes is set (None means no expiry, use incremental loading)
                            if expiry_minutes is not None and now - cache_timestamp > timedelta(minutes=expiry_minutes):
                                needs_refresh = True
                                logger.debug(f"BACKGROUND TASK: Cached data for {report_type} ({mission_id}) is stale - will refresh")
                    
                    if needs_refresh:
                        # Use smart loading - will try incremental first if possible
                        # This will update cache_timestamp even if no new data is found
                        await load_data_source(
                            report_type,
                            mission_id,
                            source_preference="remote",
                            force_refresh=False,  # Let the smart caching decide
                            current_user=None,
                        )
                        refreshed_count += 1
                        logger.info(f"BACKGROUND TASK: Refreshed {report_type} for {mission_id} (cache timestamp updated)")
                        mission_usage_logger.info(f"BACKGROUND_REFRESH: Refreshed {report_type} for {mission_id}")
                    else:
                        logger.debug(f"BACKGROUND TASK: Cached data for {report_type} ({mission_id}) is still fresh")
                        
                except Exception as e:
                    logger.error(
                        f"BACKGROUND TASK: Error checking/refreshing cache for {report_type} "
                        f"on mission {mission_id}: {e}"
                    )
    
    logger.info(
                f"BACKGROUND TASK: Refreshed {refreshed_count}/{len(report_types_to_check)} "
                f"data types for mission {mission_id}"
            )
    
    logger.info("BACKGROUND TASK: Smart cache refresh completed.")


async def smart_background_refresh():
    """
    Enhanced background refresh that only refreshes data that's actually stale
    and likely to be viewed by users.
    """
    logger.info("BACKGROUND TASK: Starting smart background refresh.")
    
    # Get active missions
    active_missions = settings.active_realtime_missions
    
    for mission_id in active_missions:
        logger.info(f"BACKGROUND TASK: Smart refresh for mission {mission_id}")
        
        # Check each data type and only refresh if needed
        for report_type, strategy in CACHE_STRATEGIES.items():
            # Skip if this is not a real-time data type
            if not strategy["incremental"]:
                continue
                
            try:
                # Check if we have recent data for this report type
                cache_key = create_time_aware_cache_key(
                    report_type, mission_id, None, None, 24, "remote", None  # Last 24 hours
                )
                
                needs_refresh = False
                if cache_key not in data_cache:
                    needs_refresh = True
                else:
                    cached_df, cached_source_path, cache_timestamp, last_data_timestamp, _ = data_cache[cache_key]
                    
                    # Skip static data
                    if is_static_data_source(cached_source_path, report_type, mission_id):
                        continue
                    
                    # Check if data is stale - always use UTC
                    # Only check expiry if expiry_minutes is set (None means no expiry, use incremental loading)
                    expiry_minutes = strategy["expiry_minutes"]
                    if expiry_minutes is not None:
                        now = datetime.now(timezone.utc)
                        if cache_timestamp.tzinfo is None:
                            # If cache timestamp is naive, localize to UTC for comparison
                            cache_timestamp = cache_timestamp.replace(tzinfo=timezone.utc)
                        if now - cache_timestamp > timedelta(minutes=expiry_minutes):
                            needs_refresh = True
                
                if needs_refresh:
                    # Load recent data with overlap
                    await load_data_source(
                        report_type, mission_id, 
                        hours_back=24,  # Last 24 hours
                        source_preference="remote",
                        current_user=None
                    )
                    logger.debug(f"BACKGROUND TASK: Refreshed {report_type} for {mission_id}")
                    
            except Exception as e:
                logger.error(f"BACKGROUND TASK: Error refreshing {report_type} for {mission_id}: {e}")
    
    logger.info("BACKGROUND TASK: Smart background refresh completed.")


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
            from .core.reporting import create_and_save_weekly_report
            await create_and_save_weekly_report(mission_id, session)

    logger.info("AUTOMATED: Weekly report generation job finished.")


# --- FastAPI Lifecycle Events for Scheduler ---
@app.on_event("startup")  # Uncomment the startup event
async def startup_event():
    logger.info("Application startup event initiated.")  # Changed from print
    
    # Setup admin interfaces
    try:
        # Setup SQLAdmin (doesn't require Redis)
        # Focus: Core operational models (Users, Stations, Missions, Timesheets, etc.)
        # Pass the app instance as SQLAdmin requires it for initialization
        setup_sqladmin(app)
        logger.info("SQLAdmin configured successfully at /admin (admin-only, authenticated)")
    except Exception as e:
        logger.error(f"Error setting up admin interfaces: {e}", exc_info=True)
    
    # Create directory for mission plan uploads if it doesn't exist
    MISSION_PLANS_DIR = PROJECT_ROOT / "web" / "static" / "mission_plans"
    MISSION_PLANS_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(f"Mission plans directory checked/created at: {MISSION_PLANS_DIR}")

    # Step 1: Sync remote data to local storage
    logger.info("STARTUP: Syncing remote data to local storage...")
    try:
        from .core.sync_service import sync_all_realtime_missions
        sync_results = await sync_all_realtime_missions()
        total_successful = sum(r["successful"] for r in sync_results.values())
        total_failed = sum(r["failed"] for r in sync_results.values())
        logger.info(
            f"STARTUP: Sync complete - {total_successful} files synced, {total_failed} failed. "
            f"Results: {sync_results}"
        )
    except Exception as e:
        logger.error(f"STARTUP: Error syncing data to local storage: {e}", exc_info=True)
        # Continue anyway - may have some local data or can fall back to remote
    
    # Step 2: Initialize cache from local storage (faster than remote)
    logger.info("STARTUP: Initializing cache from local storage...")
    try:
        cached_count = await initialize_startup_cache()
        logger.info(f"STARTUP: Successfully cached {cached_count} data sources from local storage")
    except Exception as e:
        logger.error(f"STARTUP: Error initializing cache: {e}", exc_info=True)

    # Add background refresh using configured interval (default: 10 minutes from .env)
    scheduler.add_job(
        refresh_active_mission_cache,
        "interval",
        minutes=settings.background_cache_refresh_interval_minutes,
        id="active_mission_refresh_job",
    )
    logger.info(f"Background cache refresh scheduled every {settings.background_cache_refresh_interval_minutes} minutes")
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
    # Register scheduler for access by other modules
    set_scheduler(scheduler)
    logger.info("APScheduler started for minimal background cache refresh.")

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
    results: list, report_types_order: list, hours: int, mission_id: str, current_user: Optional[models.User] = None
) -> dict:
    """
    Processes the loaded data results, calculates summaries, and determines
    the display source path for the home view.
    """
    data_frames: Dict[str, Optional[pd.DataFrame]] = {}
    source_paths_map: Dict[str, str] = {}
    file_mod_times_map: Dict[str, Optional[datetime]] = {}

    for i, report_type in enumerate(report_types_order):
        if isinstance(results[i], Exception):
            data_frames[report_type] = None # Ensure it's None, not an empty DataFrame yet
            source_paths_map[report_type] = "Error during load"
            file_mod_times_map[report_type] = None
            logger.error(
                f"Exception loading {report_type} for mission {mission_id}: {results[i]}"
            )
        else:
            # Ensure results[i] is a tuple of (DataFrame, str)
            if isinstance(results[i], tuple) and len(results[i]) == 3:
                df_loaded, path_loaded, file_mod_time_loaded = results[i]
                data_frames[report_type] = df_loaded if df_loaded is not None and not df_loaded.empty else None
                source_paths_map[report_type] = path_loaded
                file_mod_times_map[report_type] = file_mod_time_loaded
            elif isinstance(results[i], tuple) and len(results[i]) == 2:
                # Backward compatibility: handle old 2-tuple format
                df_loaded, path_loaded = results[i]
                data_frames[report_type] = df_loaded if df_loaded is not None and not df_loaded.empty else None
                source_paths_map[report_type] = path_loaded
                file_mod_times_map[report_type] = None
            else: # Should not happen if load_data_source is consistent
                data_frames[report_type] = None
                file_mod_times_map[report_type] = None
                source_paths_map[report_type] = "Unexpected load result format"
                logger.error(f"Unexpected load result format for {report_type} (mission {mission_id}): {results[i]}")


    # Determine the primary display_source_path
    display_source_path = "Information unavailable or all loads failed"
    found_primary_path_for_display = False
    priority_paths_checks = [
        (lambda p: "Remote:" in p and "output_realtime_missions" in p and "Data not loaded" not in p and "Error during load" not in p),
        # (lambda p: "Remote:" in p and "output_past_missions" in p and "Data not loaded" not in p and "Error during load" not in p),  # Commented out - focusing on active missions only
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

    # Get file modification times for each report type (when source file was last updated)
    from .core.data_service import get_cache_timestamp
    
    # Determine source preference from source_paths_map (check if any path indicates remote)
    source_preference = None
    for path in source_paths_map.values():
        if "Remote:" in path:
            source_preference = "remote"
            break
        elif "Local:" in path:
            source_preference = "local"
    
    # Only process data for sensors that were actually loaded
    if "power" in data_frames and data_frames["power"] is not None:
        power_file_mod_time = file_mod_times_map.get("power") or get_cache_timestamp("power", mission_id, source_preference)
        power_info = summaries.get_power_status(data_frames.get("power"), data_frames.get("solar"), power_file_mod_time)
        power_info["mini_trend"] = summaries.get_power_mini_trend(data_frames.get("power"))

    if "ctd" in data_frames and data_frames["ctd"] is not None:
        ctd_file_mod_time = file_mod_times_map.get("ctd") or get_cache_timestamp("ctd", mission_id, source_preference)
        ctd_info = summaries.get_ctd_status(data_frames.get("ctd"), ctd_file_mod_time)
        ctd_info["mini_trend"] = summaries.get_ctd_mini_trend(data_frames.get("ctd"))

    if "weather" in data_frames and data_frames["weather"] is not None:
        weather_file_mod_time = file_mod_times_map.get("weather") or get_cache_timestamp("weather", mission_id, source_preference)
        weather_info = summaries.get_weather_status(data_frames.get("weather"), weather_file_mod_time)
        weather_info["mini_trend"] = summaries.get_weather_mini_trend(data_frames.get("weather"))

    if "waves" in data_frames and data_frames["waves"] is not None:
        wave_file_mod_time = file_mod_times_map.get("waves") or get_cache_timestamp("waves", mission_id, source_preference)
        wave_info = summaries.get_wave_status(data_frames.get("waves"), wave_file_mod_time)
        wave_info["mini_trend"] = summaries.get_wave_mini_trend(data_frames.get("waves"))

    if "vr2c" in data_frames and data_frames["vr2c"] is not None:
        vr2c_file_mod_time = file_mod_times_map.get("vr2c") or get_cache_timestamp("vr2c", mission_id, source_preference)
        vr2c_info = summaries.get_vr2c_status(data_frames.get("vr2c"), vr2c_file_mod_time)
        vr2c_info["mini_trend"] = summaries.get_vr2c_mini_trend(data_frames.get("vr2c"))

    if "fluorometer" in data_frames and data_frames["fluorometer"] is not None:
        fluorometer_file_mod_time = file_mod_times_map.get("fluorometer") or get_cache_timestamp("fluorometer", mission_id, source_preference)
        fluorometer_info = summaries.get_fluorometer_status(data_frames.get("fluorometer"), fluorometer_file_mod_time)
        fluorometer_info["mini_trend"] = summaries.get_fluorometer_mini_trend(data_frames.get("fluorometer"))

    if "wg_vm4" in data_frames and data_frames["wg_vm4"] is not None:
        wg_vm4_file_mod_time = file_mod_times_map.get("wg_vm4") or get_cache_timestamp("wg_vm4", mission_id, source_preference)
        wg_vm4_info = summaries.get_wg_vm4_status(data_frames.get("wg_vm4"), wg_vm4_file_mod_time)
        wg_vm4_info["mini_trend"] = summaries.get_wg_vm4_mini_trend(data_frames.get("wg_vm4"))

    if "telemetry" in data_frames and data_frames["telemetry"] is not None:
        telemetry_file_mod_time = file_mod_times_map.get("telemetry") or get_cache_timestamp("telemetry", mission_id, source_preference)
        navigation_info = summaries.get_navigation_status(data_frames.get("telemetry"), telemetry_file_mod_time)
        navigation_info["mini_trend"] = summaries.get_navigation_mini_trend(data_frames.get("telemetry"))

    # Initialize AIS list variable (will be populated if AIS data exists)
    all_ais_list = []
    
    if "ais" in data_frames and data_frames["ais"] is not None:
        ais_summary_data = summaries.get_ais_summary(data_frames.get("ais"), max_age_hours=hours)
        ais_summary_stats = summaries.get_ais_summary_stats(data_frames.get("ais"), max_age_hours=hours)
        # Use file modification time (when source file was last updated) for "last data"
        ais_file_mod_time = file_mod_times_map.get("ais")
        if ais_file_mod_time is not None:
            ais_update_info = {
                "latest_timestamp_str": ais_file_mod_time.strftime("%Y-%m-%d %H:%M:%S UTC"),
                "time_ago_str": summaries.time_ago(ais_file_mod_time)
            }
        else:
            # Fall back to get_cache_timestamp if file_mod_times_map doesn't have it
            ais_file_mod_time = get_cache_timestamp("ais", mission_id, source_preference)
            if ais_file_mod_time is not None:
                ais_update_info = {
                    "latest_timestamp_str": ais_file_mod_time.strftime("%Y-%m-%d %H:%M:%S UTC"),
                    "time_ago_str": summaries.time_ago(ais_file_mod_time)
                }
            else:
                # Fall back to max timestamp in data if file modification time not available
                ais_update_info = utils.get_df_latest_update_info(data_frames.get("ais"), timestamp_col="LastSeenTimestamp")
        
        # Process all AIS data for the collapsible tab
        from .core.processors import preprocess_ais_df
        all_ais_df = preprocess_ais_df(data_frames.get("ais"))
        if not all_ais_df.empty:
            # Get the latest record for each MMSI
            latest_by_mmsi = (
                all_ais_df.dropna(subset=["MMSI"])
                .sort_values("LastSeenTimestamp", ascending=False)
                .groupby("MMSI")
                .first()
                .reset_index()
            )
            
            # Import vessel categories here to avoid circular imports
            from .core.vessel_categories import get_vessel_category, is_hazardous_vessel, get_ais_class_info
            
            # Clear and populate all_ais_list (already initialized above)
            all_ais_list.clear()
            for _, row in latest_by_mmsi.iterrows():
                # Get vessel category information
                ship_cargo_type = row.get("ShipCargoType")
                category, group, color = get_vessel_category(ship_cargo_type)
                is_hazardous = is_hazardous_vessel(ship_cargo_type)
                
                # Get AIS class information
                ais_class = row.get("AISClass")
                ais_class_display, ais_class_color = get_ais_class_info(ais_class)
                
                vessel = {
                    "ShipName": row.get("ShipName", "Unknown"),
                    "MMSI": int(row["MMSI"]) if pd.notna(row["MMSI"]) else None,
                    "SpeedOverGround": row.get("SpeedOverGround"),
                    "CourseOverGround": row.get("CourseOverGround"),
                    "LastSeenTimestamp": row["LastSeenTimestamp"],
                    # Enhanced fields
                    "AISClass": ais_class,
                    "AISClassDisplay": ais_class_display,
                    "AISClassColor": ais_class_color,
                    "ShipCargoType": ship_cargo_type,
                    "Category": category,
                    "Group": group,
                    "CategoryColor": color,
                    "IsHazardous": is_hazardous,
                    "Heading": row.get("Heading"),
                    "NavigationStatus": row.get("NavigationStatus"),
                    "CallSign": row.get("CallSign"),
                    "Destination": row.get("Destination"),
                    "ETA": row.get("ETA"),
                    "Length": row.get("Length"),
                    "Breadth": row.get("Breadth"),
                    "Latitude": row.get("Latitude"),
                    "Longitude": row.get("Longitude"),
                    "IMONumber": row.get("IMONumber"),
                    "Dimension": row.get("Dimension"),
                    "RateOfTurn": row.get("RateOfTurn"),
                }
                all_ais_list.append(vessel)
            
            # Sort by timestamp (most recent first)
            all_ais_list.sort(key=lambda x: x['LastSeenTimestamp'] if x['LastSeenTimestamp'] else datetime.min, reverse=True)
    
    # Initialize error variables
    recent_errors_list = []
    all_errors_list = []
    errors_update_info = None
    error_analysis = {}
    
    if "errors" in data_frames and data_frames["errors"] is not None:
        logger.info(f"Processing error data: {len(data_frames['errors'])} rows")
        # Get recent errors for text display (24 hours)
        recent_errors_list = summaries.get_recent_errors(data_frames.get("errors"), max_age_hours=hours)[:20]
        # Use cache timestamp (when data was fetched) instead of max timestamp in data
        errors_cache_timestamp = get_cache_timestamp("errors", mission_id, source_preference)
        if errors_cache_timestamp is not None:
            errors_update_info = {
                "latest_timestamp_str": errors_cache_timestamp.strftime("%Y-%m-%d %H:%M:%S UTC"),
                "time_ago_str": summaries.time_ago(errors_cache_timestamp)
            }
            logger.debug(f"Errors 'last data' using cache timestamp: {errors_update_info['latest_timestamp_str']}")
        else:
            logger.debug(f"Errors cache timestamp not found for mission {mission_id}, source_preference {source_preference}, falling back to data timestamp")
            # Fall back to max timestamp in data if cache timestamp not available
            # Preprocess the errors data first to ensure "Timestamp" column exists
            from .core.processors import preprocess_error_df
            try:
                errors_df_processed = preprocess_error_df(data_frames.get("errors"))
                if not errors_df_processed.empty and "Timestamp" in errors_df_processed.columns:
                    errors_update_info = utils.get_df_latest_update_info(errors_df_processed, timestamp_col="Timestamp")
                else:
                    errors_update_info = {"latest_timestamp_str": "N/A", "time_ago_str": "N/A"}
            except Exception as e:
                logger.warning(f"Error preprocessing errors data for timestamp info: {e}")
                errors_update_info = {"latest_timestamp_str": "N/A", "time_ago_str": "N/A"}
        
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
        "ais_summary_stats": ais_summary_stats if 'ais_summary_stats' in locals() else None,
        "ais_update_info": ais_update_info,
        "all_ais_list": all_ais_list,
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
    """Active mission dashboard."""
    mission = request.query_params.get("mission")
    if not mission:
        return RedirectResponse(url="/home.html")
    
    # Reuse shared dashboard rendering logic
    return await _render_dashboard(request, mission, current_user, session, is_historical=False)


async def _render_dashboard(request: Request, mission: str, current_user: models.User, session: SQLModelSession, is_historical: bool = False):
    """Shared dashboard rendering logic for both active and historical missions."""

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
        "wg_vm4_info": "wg_vm4_info",  # WG-VM4 info data for automatic offload logging
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
    
    # Always include WG-VM4 info data for automatic offload logging (background processing)
    if "wg_vm4_info" not in report_types_to_load:
        report_types_to_load.append("wg_vm4_info")
    
    logger.info(f"DASHBOARD: Loading data for mission {mission} with report types: {report_types_to_load}")
    
    hours = 24  # Default time window for summaries/mini-trends

    # Load only the data sources for enabled sensor cards
    results = await asyncio.gather(
        *[load_data_source(rt, mission, current_user=current_user) for rt in report_types_to_load],
        return_exceptions=True
    )

    # Process WG-VM4 info data for automatic offload logging
    # Skip processing for historical missions to prevent overwriting current offload logs
    if "wg_vm4_info" in report_types_to_load and not is_historical:
        try:
            from .core.wg_vm4_station_service import process_wg_vm4_info_for_mission
            from .core.processors import preprocess_wg_vm4_info_df
            
            # Find the WG-VM4 info data in results
            wg_vm4_info_index = report_types_to_load.index("wg_vm4_info")
            wg_vm4_info_result = results[wg_vm4_info_index]
            
            if not isinstance(wg_vm4_info_result, Exception) and wg_vm4_info_result is not None:
                # Unpack the tuple from load_data_source (dataframe, source_path, file_mod_time)
                if isinstance(wg_vm4_info_result, tuple) and len(wg_vm4_info_result) == 3:
                    df, source_path, _ = wg_vm4_info_result
                elif isinstance(wg_vm4_info_result, tuple) and len(wg_vm4_info_result) == 2:
                    # Backward compatibility
                    df, source_path = wg_vm4_info_result
                else:
                    logger.error(f"Unexpected wg_vm4_info_result format: {wg_vm4_info_result}")
                    df, source_path = None, None
                if df is not None and not df.empty:
                    # Preprocess the data
                    processed_df = preprocess_wg_vm4_info_df(df)
                    
                    # Process for automatic offload logging
                    stats = process_wg_vm4_info_for_mission(session, processed_df, mission)
                    logger.info(f"WG-VM4 auto-processing for mission {mission}: {stats}")
                    
                    # Load and attach Vemco VM4 Remote Health to offload logs when available
                    try:
                        from .core.wg_vm4_station_service import attach_remote_health_to_offload_logs
                        from .core.processors import preprocess_wg_vm4_remote_health_df
                        remote_health_result = await load_data_source("wg_vm4_remote_health", mission, current_user=current_user)
                        if isinstance(remote_health_result, tuple) and len(remote_health_result) >= 2:
                            rh_df = remote_health_result[0]
                            if rh_df is not None and not rh_df.empty:
                                rh_processed = preprocess_wg_vm4_remote_health_df(rh_df)
                                health_stats = attach_remote_health_to_offload_logs(session, rh_processed)
                                logger.info(f"WG-VM4 remote health attached for mission {mission}: {health_stats}")
                    except Exception as rh_err:
                        logger.debug(f"WG-VM4 remote health not loaded or attach failed for mission {mission}: {rh_err}")
                else:
                    logger.debug(f"No WG-VM4 info data available for mission {mission}")
            else:
                logger.debug(f"WG-VM4 info data loading failed for mission {mission}")
        except Exception as e:
            logger.error(f"Error processing WG-VM4 info data for mission {mission}: {e}")
    elif "wg_vm4_info" in report_types_to_load and is_historical:
        logger.info(f"Skipping WG-VM4 offload log processing for historical mission {mission} to prevent overwriting current logs")

    # Process the loaded data for summaries and mini-trends
    context = await _process_loaded_data_for_home_view(results, report_types_to_load, hours, mission, current_user)
    context.update(get_template_context(
        request=request,
        mission=mission,
        current_user=current_user,
    ))
    
    # Add sensor card configuration to context
    context["enabled_sensor_cards"] = enabled_sensor_cards
    
    # Determine if this is a realtime mission (only for active missions)
    is_realtime = mission in settings.active_realtime_missions if not is_historical else False
    context["is_current_mission_realtime"] = is_realtime
    context["is_historical_mission"] = is_historical

    return templates.TemplateResponse("index.html", context)


@app.get("/historical", include_in_schema=False)
async def historical_dashboard(request: Request, current_user: models.User = Depends(get_current_active_user), session: SQLModelSession = Depends(get_db_session)):
    """Historical mission dashboard - same as root but for past missions without cache refresh."""
    mission = request.query_params.get("mission")
    if not mission:
        return RedirectResponse(url="/home.html")
    
    # Reuse the same logic as root endpoint but mark as historical
    return await _render_dashboard(request, mission, current_user, session, is_historical=True)

@app.get("/api/data/{report_type}/{mission_id}")
async def get_report_data_for_plotting(
    report_type: models.ReportTypeEnum,  # Use Enum for path parameter validation
    mission_id: str,
    params: models.ReportDataParams = Depends(),  # Inject Pydantic model for query params
    current_user: models.User = Depends(get_current_active_user),  # Protect API
):
    try:
        # Unpack the DataFrame, source path, and file modification time
        # Also get cache metadata for frontend sync
        df, source_path, file_mod_time = await load_data_source(  # type: ignore
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
            hours_back=params.hours_back,  # Pass hours_back parameter for time-aware caching
        )
        
        # Get cache metadata for this request
        # Note: create_time_aware_cache_key and data_cache are already imported at top of file
        cache_key = create_time_aware_cache_key(
            report_type.value, mission_id, params.start_date, params.end_date,
            params.hours_back, params.source.value if params.source else None,
            params.local_path
        )
        
        # Extract cache timestamps if available
        cache_timestamp = None
        last_data_timestamp = None
        if cache_key in data_cache:
            _, _, cache_timestamp, last_data_timestamp, _ = data_cache[cache_key]

        if df is None or df.empty:
            # Return empty data with cache metadata for charts instead of 404
            response_data = {
                "data": [],
                "cache_metadata": {
                    "cache_timestamp": cache_timestamp.isoformat() if cache_timestamp else None,
                    "last_data_timestamp": last_data_timestamp.isoformat() if last_data_timestamp else None,
                    "file_modification_time": file_mod_time.isoformat() if file_mod_time else None,
                }
            }
            response = JSONResponse(content=response_data)
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
            return response

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
            # Return empty data with cache metadata
            response_data = {
                "data": [],
                "cache_metadata": {
                    "cache_timestamp": cache_timestamp.isoformat() if cache_timestamp else None,
                    "last_data_timestamp": last_data_timestamp.isoformat() if last_data_timestamp else None,
                    "file_modification_time": file_mod_time.isoformat() if file_mod_time else None,
                }
            }
            response = JSONResponse(content=response_data)
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
            return response

        # Determine the most recent timestamp in the data
        max_timestamp = processed_df["Timestamp"].max()

        if pd.isna(max_timestamp):
            logger.warning(
                f"No valid timestamps in processed data for {report_type.value}, "
                f"mission {mission_id} after preprocessing."
            )
            # Return empty data with cache metadata
            response_data = {
                "data": [],
                "cache_metadata": {
                    "cache_timestamp": cache_timestamp.isoformat() if cache_timestamp else None,
                    "last_data_timestamp": last_data_timestamp.isoformat() if last_data_timestamp else None,
                    "file_modification_time": file_mod_time.isoformat() if file_mod_time else None,
                }
            }
            response = JSONResponse(content=response_data)
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
            return response

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
            # Use hours_back filtering - filter based on last recorded data timestamp, not "now"
            # This allows historical missions to display their last 24 hours of data
            # even if that data is from days, weeks, or months ago
            # max_timestamp is already calculated above (line 2084)
            
            # Ensure max_timestamp is a datetime object
            if hasattr(max_timestamp, 'to_pydatetime'):
                last_data_timestamp = max_timestamp.to_pydatetime()
            elif isinstance(max_timestamp, (int, float)):
                last_data_timestamp = datetime.fromtimestamp(max_timestamp, tz=timezone.utc)
            elif not isinstance(max_timestamp, datetime):
                last_data_timestamp = pd.to_datetime(max_timestamp, utc=True)
            else:
                last_data_timestamp = max_timestamp
            
            # Ensure timezone awareness
            if last_data_timestamp.tzinfo is None:
                last_data_timestamp = last_data_timestamp.replace(tzinfo=timezone.utc)
            
            # Calculate cutoff from the last data point, not from now
            cutoff_time = last_data_timestamp - timedelta(hours=params.hours_back)
            recent_data = processed_df[processed_df["Timestamp"] > cutoff_time]
            if recent_data.empty:
                logger.info(
                    f"No data for {report_type.value}, mission {mission_id} within "
                    f"{params.hours_back} hours of last recorded data (cutoff: {cutoff_time}, last data: {last_data_timestamp})."
                )
                # Return empty data with cache metadata
                response_data = {
                    "data": [],
                    "cache_metadata": {
                        "cache_timestamp": cache_timestamp.isoformat() if cache_timestamp else None,
                        "last_data_timestamp": last_data_timestamp.isoformat() if last_data_timestamp else None,
                        "file_modification_time": file_mod_time.isoformat() if file_mod_time else None,
                    }
                }
                response = JSONResponse(content=response_data)
                response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
                response.headers["Pragma"] = "no-cache"
                response.headers["Expires"] = "0"
                return response

        if recent_data.empty:
            logger.info(f"No data remaining after filtering for {report_type.value}, mission {mission_id}")
            # Return empty data with cache metadata
            response_data = {
                "data": [],
                "cache_metadata": {
                    "cache_timestamp": cache_timestamp.isoformat() if cache_timestamp else None,
                    "last_data_timestamp": last_data_timestamp.isoformat() if last_data_timestamp else None,
                    "file_modification_time": file_mod_time.isoformat() if file_mod_time else None,
                }
            }
            response = JSONResponse(content=response_data)
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
            return response

        # Resample data based on user-defined granularity
        data_to_resample = recent_data.set_index("Timestamp")
        numeric_cols = data_to_resample.select_dtypes(include=[np.number])
        # Ensure numeric_cols is not empty before resampling
        if numeric_cols.empty:
            logger.info(
                f"No numeric data to resample for {report_type.value}, "
                f"mission {mission_id} after filtering and before resampling."
            )
            # Return empty data with cache metadata
            response_data = {
                "data": [],
                "cache_metadata": {
                    "cache_timestamp": cache_timestamp.isoformat() if cache_timestamp else None,
                    "last_data_timestamp": last_data_timestamp.isoformat() if last_data_timestamp else None,
                    "file_modification_time": file_mod_time.isoformat() if file_mod_time else None,
                }
            }
            response = JSONResponse(content=response_data)
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
            return response

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

        # Replace NaN with None for JSON compatibility
        resampled_data = resampled_data.replace({np.nan: None})
        
        # Prepare response with data and cache metadata
        response_data = {
            "data": resampled_data.to_dict(orient="records"),
            "cache_metadata": {
                "cache_timestamp": cache_timestamp.isoformat() if cache_timestamp else None,
                "last_data_timestamp": last_data_timestamp.isoformat() if last_data_timestamp else None,
                "file_modification_time": file_mod_time.isoformat() if file_mod_time else None,
            }
        }
        
        # Add cache-busting headers to prevent browser caching
        response = JSONResponse(content=response_data)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        
        return response
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={"error": str(e), "detail": "See server logs for traceback."}
        )


# ---


@app.get("/api/cache-status/{mission_id}")
async def get_cache_status(
    mission_id: str,
    current_user: models.User = Depends(get_current_active_user),
):
    """
    Get cache status for all report types for a mission.
    Used by frontend to detect when data has been updated.
    """
    # Note: create_time_aware_cache_key, data_cache, and CACHE_STRATEGIES are already imported at top of file
    
    cache_status = {}
    
    # Check cache status for all incremental report types
    for report_type in CACHE_STRATEGIES.keys():
        # Try to find cache entry (check common time ranges)
        cache_timestamp = None
        last_data_timestamp = None
        
        # Check multiple possible cache keys (different time ranges)
        # Also check with "remote" source preference since that's what background refresh uses
        for hours_back in [None, 24, 72]:
            for source_pref in [None, "remote"]:
                cache_key = create_time_aware_cache_key(
                    report_type, mission_id, None, None, hours_back, source_pref, None
                )
                if cache_key in data_cache:
                    _, _, cache_timestamp, last_data_timestamp, _ = data_cache[cache_key]
                    break
            if cache_timestamp:
                break
        
        cache_status[report_type] = {
            "cache_timestamp": cache_timestamp.isoformat() if cache_timestamp else None,
            "last_data_timestamp": last_data_timestamp.isoformat() if last_data_timestamp else None,
            "cached": cache_timestamp is not None,
        }
    
    response = JSONResponse(content=cache_status)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.get("/api/forecast/{mission_id}")
async def get_weather_forecast(
    mission_id: str,
    params: models.ForecastParams = Depends(),  # Inject Pydantic model for query params
    current_user: models.User = Depends(get_current_active_user),  # Protect API
):
    """
    Provides a weather forecast.
    If lat and lon are not provided, it attempts to infer them from the latest telemetry data.
    Forecasts are not provided for historical missions.
    """
    # Skip forecasting for historical missions
    if params.is_historical:
        logger.info(f"Skipping weather forecast for historical mission {mission_id}")
        raise HTTPException(
            status_code=400,
            detail="Weather forecasts are not available for historical missions.",
        )
    
    final_lat, final_lon = params.lat, params.lon

    if final_lat is None or final_lon is None:
        logger.info(
            f"Lat/Lon not provided for forecast. Inferring from telemetry "
            f"for mission {mission_id}."
        )
        # Pass source preference to telemetry loading
        # Unpack the DataFrame and the source path; we only need the DataFrame here, pass refresh. No client passed.
        df_telemetry, _, _ = await load_data_source(
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
            # Use robust parser to handle mixed formats (ISO 8601 and 12hr AM/PM)
            if "lastLocationFix" in df_telemetry.columns:
                df_telemetry["lastLocationFix"] = utils.parse_timestamp_column(
                    df_telemetry["lastLocationFix"], errors="coerce", utc=True
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
    """Provides marine-specific forecast data (waves, currents). Forecasts are not provided for historical missions."""
    # Skip forecasting for historical missions
    if params.is_historical:
        logger.info(f"Skipping marine forecast for historical mission {mission_id}")
        raise HTTPException(
            status_code=400,
            detail="Marine forecasts are not available for historical missions.",
        )
    
    final_lat, final_lon = params.lat, params.lon

    if final_lat is None or final_lon is None:
        logger.info(
            f"Lat/Lon not provided for marine forecast. Inferring from "
            f"telemetry for mission {mission_id}."
        )
        df_telemetry, _, _ = await load_data_source(
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
                # Use robust parser to handle mixed formats (ISO 8601 and 12hr AM/PM)
                df_telemetry["lastLocationFix"] = utils.parse_timestamp_column(
                    df_telemetry["lastLocationFix"], errors="coerce", utc=True
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
        # data_cache stores (data, path, cache_timestamp, last_data_timestamp, file_modification_time). Here 'data' is the list of spectral_records.
        cached_spectral_records, cached_source_path_info, cache_timestamp, _, _ = data_cache[
            spectrum_cache_key
        ]

        is_realtime_source = (
            "Remote:" in cached_source_path_info
            and "output_realtime_missions" in cached_source_path_info
        )

        if is_realtime_source:
            now = datetime.now(timezone.utc)
            if cache_timestamp.tzinfo is None:
                cache_timestamp = cache_timestamp.replace(tzinfo=timezone.utc)
            if now - cache_timestamp < timedelta(minutes=CACHE_EXPIRY_MINUTES):
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
        df_freq, path_freq, _ = await load_data_source( # type: ignore
            "wave_frequency_spectrum",
            mission_id,
            params.source.value if params.source else None,
            params.local_path,
            params.refresh,
            current_user,
        )
        df_energy, path_energy, _ = await load_data_source( # type: ignore
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
                datetime.now(timezone.utc),
                None,  # last_data_timestamp not applicable for spectrum
                None,  # file_modification_time not available for combined data
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


# --- AIS CSV Download Endpoints ---
@app.get("/api/ais/csv/recent")
async def download_recent_ais_csv(
    mission: str = Query(..., description="Mission name"),
    hours: int = Query(24, description="Number of hours to look back"),
    current_user: models.User = Depends(get_current_active_user)
):
    """Download recent AIS contacts (last 24 hours) as CSV"""
    try:
        import io
        import csv
        from fastapi.responses import StreamingResponse
        from datetime import datetime
        
        # Load AIS data using the same method as the dashboard
        ais_df, _, _ = await load_data_source("ais", mission_id=mission, current_user=current_user)
        if ais_df is None or ais_df.empty:
            raise HTTPException(status_code=404, detail="No AIS data found for this mission")
        
        # Get recent AIS data using the same logic as the dashboard
        from .core.summaries import get_ais_summary
        recent_vessels = get_ais_summary(ais_df, max_age_hours=hours)
        
        # Create CSV
        output = io.StringIO()
        csv_writer = csv.writer(output)
        
        # Write header
        csv_writer.writerow([
            "Last Seen", "Vessel Name", "MMSI", "AIS Class", "Vessel Type", "Group", 
            "Speed (kn)", "Course (°)", "Heading (°)", "Navigation Status", 
            "Call Sign", "Destination", "ETA", "Length (m)", "Breadth (m)", 
            "Latitude", "Longitude", "IMO Number", "Hazardous Cargo"
        ])
        
        # Write data rows
        for vessel in recent_vessels:
            csv_writer.writerow([
                vessel.get('LastSeenTimestamp', '').strftime('%Y-%m-%d %H:%M:%S') if vessel.get('LastSeenTimestamp') else '',
                vessel.get('ShipName', ''),
                vessel.get('MMSI', ''),
                vessel.get('AISClassDisplay', ''),
                vessel.get('Category', ''),
                vessel.get('Group', ''),
                f"{vessel.get('SpeedOverGround', 0):.1f}" if vessel.get('SpeedOverGround') is not None else '',
                f"{vessel.get('CourseOverGround', 0):.0f}" if vessel.get('CourseOverGround') is not None else '',
                f"{vessel.get('Heading', 0):.0f}" if vessel.get('Heading') is not None else '',
                vessel.get('NavigationStatus', ''),
                vessel.get('CallSign', ''),
                vessel.get('Destination', ''),
                vessel.get('ETA', ''),
                f"{vessel.get('Length', 0):.0f}" if vessel.get('Length') is not None else '',
                f"{vessel.get('Breadth', 0):.0f}" if vessel.get('Breadth') is not None else '',
                f"{vessel.get('Latitude', 0):.6f}" if vessel.get('Latitude') is not None else '',
                f"{vessel.get('Longitude', 0):.6f}" if vessel.get('Longitude') is not None else '',
                vessel.get('IMONumber', ''),
                'Yes' if vessel.get('IsHazardous') else 'No'
            ])
        
        output.seek(0)
        content = output.getvalue()
        filename = f"recent_ais_contacts_{mission}_{hours}h_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
        
        return StreamingResponse(
            io.BytesIO(content.encode("utf-8")), 
            media_type="text/csv", 
            headers={"Content-Disposition": f"attachment; filename=\"{filename}\""}
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating AIS CSV: {str(e)}")


@app.get("/api/ais/csv/all")
async def download_all_ais_csv(
    mission: str = Query(..., description="Mission name"),
    current_user: models.User = Depends(get_current_active_user)
):
    """Download all mission AIS contacts as CSV"""
    try:
        import io
        import csv
        from fastapi.responses import StreamingResponse
        from datetime import datetime
        
        # Load AIS data using the same method as the dashboard
        ais_df, _, _ = await load_data_source("ais", mission_id=mission, current_user=current_user)
        if ais_df is None or ais_df.empty:
            raise HTTPException(status_code=404, detail="No AIS data found for this mission")
        
        # Process all AIS data using the same logic as the dashboard
        from .core.summaries import get_ais_summary
        all_vessels = get_ais_summary(ais_df, max_age_hours=8760)  # 1 year to get all data
        
        # Create CSV
        output = io.StringIO()
        csv_writer = csv.writer(output)
        
        # Write header
        csv_writer.writerow([
            "Last Seen", "Vessel Name", "MMSI", "AIS Class", "Vessel Type", "Group", 
            "Speed (kn)", "Course (°)", "Heading (°)", "Navigation Status", 
            "Call Sign", "Destination", "ETA", "Length (m)", "Breadth (m)", 
            "Latitude", "Longitude", "IMO Number", "Hazardous Cargo"
        ])
        
        # Write data rows
        for vessel in all_vessels:
            csv_writer.writerow([
                vessel.get('LastSeenTimestamp', '').strftime('%Y-%m-%d %H:%M:%S') if vessel.get('LastSeenTimestamp') else '',
                vessel.get('ShipName', ''),
                vessel.get('MMSI', ''),
                vessel.get('AISClassDisplay', ''),
                vessel.get('Category', ''),
                vessel.get('Group', ''),
                f"{vessel.get('SpeedOverGround', 0):.1f}" if vessel.get('SpeedOverGround') is not None else '',
                f"{vessel.get('CourseOverGround', 0):.0f}" if vessel.get('CourseOverGround') is not None else '',
                f"{vessel.get('Heading', 0):.0f}" if vessel.get('Heading') is not None else '',
                vessel.get('NavigationStatus', ''),
                vessel.get('CallSign', ''),
                vessel.get('Destination', ''),
                vessel.get('ETA', ''),
                f"{vessel.get('Length', 0):.0f}" if vessel.get('Length') is not None else '',
                f"{vessel.get('Breadth', 0):.0f}" if vessel.get('Breadth') is not None else '',
                f"{vessel.get('Latitude', 0):.6f}" if vessel.get('Latitude') is not None else '',
                f"{vessel.get('Longitude', 0):.6f}" if vessel.get('Longitude') is not None else '',
                vessel.get('IMONumber', ''),
                'Yes' if vessel.get('IsHazardous') else 'No'
            ])
        
        output.seek(0)
        content = output.getvalue()
        filename = f"all_ais_contacts_{mission}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
        
        return StreamingResponse(
            io.BytesIO(content.encode("utf-8")), 
            media_type="text/csv", 
            headers={"Content-Disposition": f"attachment; filename=\"{filename}\""}
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating AIS CSV: {str(e)}")


@app.get("/api/cache/stats")
async def get_cache_statistics(
    current_user: models.User = Depends(get_current_active_user)
):
    """Get cache statistics and performance metrics (admin only)"""
    # Check if user is admin
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    try:
        stats = get_cache_stats()
        return {
            "status": "success",
            "data": stats,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        logger.error(f"Error getting cache statistics: {e}")
        raise HTTPException(status_code=500, detail=f"Error retrieving cache statistics: {str(e)}")


@app.post("/api/cache/reset")
async def reset_cache_statistics(
    current_user: models.User = Depends(get_current_active_user)
):
    """Reset cache statistics (admin only)"""
    # Check if user is admin
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    try:
        global cache_stats
        cache_stats = {
            "hits": 0,
            "misses": 0,
            "refreshes": 0,
            "total_requests": 0,
            "data_volume_mb": 0.0,
            "last_reset": datetime.now(timezone.utc),
            "by_report_type": defaultdict(lambda: {"hits": 0, "misses": 0, "refreshes": 0, "data_volume_mb": 0.0}),
            "by_mission": defaultdict(lambda: {"hits": 0, "misses": 0, "refreshes": 0, "data_volume_mb": 0.0}),
        }
        
        logger.info(f"Cache statistics reset by admin user: {current_user.username}")
        return {
            "status": "success",
            "message": "Cache statistics reset successfully",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        logger.error(f"Error resetting cache statistics: {e}")
        raise HTTPException(status_code=500, detail=f"Error resetting cache statistics: {str(e)}")


@app.get("/api/usage/summary")
async def get_usage_summary_report(
    current_user: models.User = Depends(get_current_active_user)
):
    """Get usage summary report from dedicated log files (admin only)"""
    # Check if user is admin
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    try:
        summary = generate_usage_summary_report()
        return {
            "status": "success",
            "data": summary,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        logger.error(f"Error generating usage summary report: {e}")
        raise HTTPException(status_code=500, detail=f"Error generating usage summary report: {str(e)}")


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
