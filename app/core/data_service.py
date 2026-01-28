"""
Data Service Layer

Centralized data loading service that eliminates circular dependencies.
This service handles all data loading operations that were previously
in app.py.
"""

from typing import Optional, Tuple, Dict, Any, List
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from pathlib import Path
import logging

import pandas as pd
import httpx
from cachetools import LRUCache

from ..config import settings
from . import utils, loaders
from . import models
from .feature_toggles import is_feature_enabled

logger = logging.getLogger(__name__)

# ============================================================================
# Cache Configuration and State
# ============================================================================

# Enhanced cache structure: key -> (data, actual_source_path_str, cache_timestamp, last_data_timestamp, file_modification_time)
# 'data' is typically pd.DataFrame, but for 'processed_wave_spectrum' it's List[Dict]
# last_data_timestamp: The most recent timestamp in the cached data
# file_modification_time: When the source file was last modified (Last-Modified header for remote, mtime for local)
data_cache: LRUCache[Tuple, Tuple[pd.DataFrame, str, datetime, Optional[datetime], Optional[datetime]]] = LRUCache(maxsize=512)

# Data type specific cache strategies - NO EXPIRY for incremental data
CACHE_STRATEGIES = {
    "power": {"expiry_minutes": None, "incremental": True, "overlap_hours": 1},
    "solar": {"expiry_minutes": None, "incremental": True, "overlap_hours": 1},
    "ctd": {"expiry_minutes": None, "incremental": True, "overlap_hours": 2},
    "weather": {"expiry_minutes": None, "incremental": True, "overlap_hours": 1},
    "waves": {"expiry_minutes": None, "incremental": True, "overlap_hours": 1},
    "ais": {"expiry_minutes": None, "incremental": True, "overlap_hours": 1},
    "errors": {"expiry_minutes": None, "incremental": False, "overlap_hours": 0},  # Static data - no expiry needed
    "vr2c": {"expiry_minutes": None, "incremental": True, "overlap_hours": 2},
    "fluorometer": {"expiry_minutes": None, "incremental": True, "overlap_hours": 2},
    "wg_vm4": {"expiry_minutes": None, "incremental": True, "overlap_hours": 2},
    "wg_vm4_info": {"expiry_minutes": None, "incremental": True, "overlap_hours": 2},
    "wg_vm4_remote_health": {"expiry_minutes": None, "incremental": True, "overlap_hours": 2},
    "telemetry": {"expiry_minutes": None, "incremental": True, "overlap_hours": 1},
    "wave_frequency_spectrum": {"expiry_minutes": None, "incremental": True, "overlap_hours": 1},
    "wave_energy_spectrum": {"expiry_minutes": None, "incremental": True, "overlap_hours": 1},
}

# Legacy CACHE_EXPIRY_MINUTES for backward compatibility
CACHE_EXPIRY_MINUTES = settings.background_cache_refresh_interval_minutes

# User activity tracking
user_activity: Dict[str, datetime] = {}  # user_id -> last_activity_timestamp
user_sessions: Dict[str, Dict[str, Any]] = {}  # user_id -> session_info

# Cache statistics tracking
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

# ============================================================================
# Cache Utility Functions
# ============================================================================

def create_time_aware_cache_key(
    report_type: str, 
    mission_id: str, 
    start_date: Optional[datetime], 
    end_date: Optional[datetime],
    hours_back: Optional[int],
    source_preference: Optional[str] = None,
    custom_local_path: Optional[str] = None
) -> Tuple:
    """
    Create cache key that includes time range parameters for better cache hit rates.
    
    Args:
        report_type: Type of report (e.g., 'power', 'ctd')
        mission_id: Mission identifier
        start_date: Start date for time range
        end_date: End date for time range  
        hours_back: Hours back from now
        source_preference: 'local' or 'remote'
        custom_local_path: Custom local path if specified
        
    Returns:
        Tuple suitable for use as cache key
    """
    # Normalize time range to a consistent format
    if start_date and end_date:
        # Round to nearest hour for better cache hit rates
        start_hour = start_date.replace(minute=0, second=0, microsecond=0)
        end_hour = end_date.replace(minute=0, second=0, microsecond=0)
        time_key = (start_hour.isoformat(), end_hour.isoformat())
    elif hours_back:
        # Round to nearest hour
        time_key = f"hours_{hours_back}"
    else:
        time_key = "full_dataset"
    
    return (report_type, mission_id, time_key, source_preference, custom_local_path)


def is_static_data_source(source_path: str, report_type: str, mission_id: str) -> bool:
    """
    Determine if data source is static (won't change) and should never expire.
    
    Args:
        source_path: Path to the data source
        report_type: Type of report
        mission_id: Mission identifier
        
    Returns:
        True if data source is static and should never expire
    """
    # Local files are typically static
    if "Local:" in source_path:
        return True
    
    # Some report types are inherently static
    static_types = ["errors", "ais"]  # Historical data that doesn't change
    return report_type in static_types


def get_cache_strategy(report_type: str) -> Dict[str, Any]:
    """
    Get cache strategy for a specific report type.
    
    Args:
        report_type: Type of report
        
    Returns:
        Dictionary with cache strategy parameters
    """
    return CACHE_STRATEGIES.get(report_type, {
        "expiry_minutes": None,  # No expiry for incremental data
        "incremental": True, 
        "overlap_hours": 1
    })


def get_cache_timestamp(
    report_type: str,
    mission_id: str,
    source_preference: Optional[str] = None,
    custom_local_path: Optional[str] = None
) -> Optional[datetime]:
    """
    Get the file modification time (when the source file was last updated) for a report type.
    
    Args:
        report_type: Type of report
        mission_id: Mission identifier
        source_preference: 'local' or 'remote'
        custom_local_path: Custom local path if specified
        
    Returns:
        File modification time (Last-Modified for remote, mtime for local) or None if not in cache
    """
    # Try to find cache entry - check multiple possible keys
    cache_keys_to_check = [
        create_time_aware_cache_key(
            report_type, mission_id, None, None, None, source_preference, custom_local_path
        ),
        create_time_aware_cache_key(
            report_type, mission_id, None, None, 24, source_preference, custom_local_path
        ),
        create_time_aware_cache_key(
            report_type, mission_id, None, None, 72, source_preference, custom_local_path
        ),
    ]
    
    for cache_key in cache_keys_to_check:
        if cache_key in data_cache:
            _, _, _, _, file_modification_time = data_cache[cache_key]
            return file_modification_time
    
    return None


def update_cache_stats(
    report_type: str, 
    mission_id: str, 
    cache_hit: bool, 
    data_size_mb: float = 0.0,
    is_refresh: bool = False
) -> None:
    """
    Update cache statistics.
    
    Args:
        report_type: Type of report
        mission_id: Mission identifier
        cache_hit: Whether this was a cache hit
        data_size_mb: Size of data in MB
        is_refresh: Whether this was a refresh operation
    """
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
    
    # Log cache statistics (using dedicated logger if available)
    # Note: Logger may be in app.py, but we avoid circular import by using logging.getLogger
    try:
        cache_stats_logger = logging.getLogger('cache_stats')
        if cache_stats_logger.handlers:  # Only log if handler is configured
            hit_rate = (cache_stats["hits"] / cache_stats["total_requests"] * 100) if cache_stats["total_requests"] > 0 else 0
            cache_stats_logger.info(
                f"CACHE_STATS: total={cache_stats['total_requests']}, "
                f"hits={cache_stats['hits']}, misses={cache_stats['misses']}, "
                f"hit_rate={hit_rate:.2f}%, data_volume_mb={cache_stats['data_volume_mb']:.2f}"
            )
    except Exception:
        # Logger not configured yet, skip logging
        pass


def update_user_activity(user_id: str, activity_type: str = "data_request") -> None:
    """
    Update user activity timestamp and session info.
    
    Args:
        user_id: User identifier
        activity_type: Type of activity (default: "data_request")
    """
    now = datetime.now(timezone.utc)
    user_activity[user_id] = now
    
    if user_id not in user_sessions:
        user_sessions[user_id] = {
            "first_seen": now,
            "last_activity": now,
            "activity_count": 0,
            "data_requests": 0,
            "missions_accessed": set(),
            "report_types_accessed": set()
        }
        # Log new user session (using dedicated logger if available)
        # Note: Logger may be in app.py, but we avoid circular import by using logging.getLogger
        try:
            user_activity_logger = logging.getLogger('user_activity')
            if user_activity_logger.handlers:  # Only log if handler is configured
                user_activity_logger.info(f"NEW_SESSION: user_id={user_id}, first_seen={now.isoformat()}")
        except Exception:
            pass
    
    user_sessions[user_id]["last_activity"] = now
    user_sessions[user_id]["activity_count"] += 1
    
    if activity_type == "data_request":
        user_sessions[user_id]["data_requests"] += 1
    
    # Log user activity (using dedicated logger if available)
    # Note: Logger may be in app.py, but we avoid circular import by using logging.getLogger
    try:
        user_activity_logger = logging.getLogger('user_activity')
        if user_activity_logger.handlers:  # Only log if handler is configured
            user_activity_logger.info(
                f"ACTIVITY: user_id={user_id}, activity_type={activity_type}, "
                f"activity_count={user_sessions[user_id]['activity_count']}, "
                f"data_requests={user_sessions[user_id]['data_requests']}"
            )
    except Exception:
        pass


# ============================================================================
# Data Manipulation Helper Functions
# ============================================================================

def trim_data_to_range(
    df: pd.DataFrame, 
    start_date: Optional[datetime], 
    end_date: Optional[datetime], 
    hours_back: Optional[int]
) -> pd.DataFrame:
    """
    Trim the cached data to the exact requested range.
    
    Args:
        df: DataFrame to trim
        start_date: Start date for trimming
        end_date: End date for trimming
        hours_back: Hours back from the last recorded data point (not from now)
        
    Returns:
        Trimmed DataFrame
    """
    if df.empty or "Timestamp" not in df.columns:
        return df
    
    if start_date and end_date:
        return df[(df["Timestamp"] >= start_date) & (df["Timestamp"] <= end_date)]
    elif hours_back:
        # Use the last recorded data timestamp instead of current time
        # This allows historical missions to display their last 24 hours of data
        # even if that data is from days, weeks, or months ago
        last_data_timestamp = df["Timestamp"].max()
        
        # Ensure last_data_timestamp is a datetime object
        if hasattr(last_data_timestamp, 'to_pydatetime'):
            last_data_timestamp = last_data_timestamp.to_pydatetime()
        elif isinstance(last_data_timestamp, (int, float)):
            last_data_timestamp = datetime.fromtimestamp(last_data_timestamp, tz=timezone.utc)
        elif not isinstance(last_data_timestamp, datetime):
            last_data_timestamp = pd.to_datetime(last_data_timestamp, utc=True)
        
        # Ensure timezone awareness
        if last_data_timestamp.tzinfo is None:
            last_data_timestamp = last_data_timestamp.replace(tzinfo=timezone.utc)
        
        # Calculate cutoff from the last data point, not from now
        cutoff = last_data_timestamp - timedelta(hours=hours_back)
        return df[df["Timestamp"] >= cutoff]
    
    return df


def _apply_date_filtering(df: pd.DataFrame, report_type: str, start_date: datetime, end_date: datetime) -> pd.DataFrame:
    """
    Apply date filtering to a DataFrame based on the report type and timestamp column.
    Returns the filtered DataFrame.
    
    Args:
        df: DataFrame to filter
        report_type: Type of report (determines timestamp column)
        start_date: Start date for filtering
        end_date: End date for filtering
        
    Returns:
        Filtered DataFrame
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
        "wg_vm4_remote_health": "timeStamp",
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


# ============================================================================
# Data Loading Helper Functions
# ============================================================================

async def _load_from_local_sources(
    report_type: str, mission_id: str, custom_local_path: Optional[str],
    current_user: Optional[models.User] = None,
    allow_system_access: bool = False
) -> Tuple[Optional[pd.DataFrame], str, Optional[datetime]]:
    """
    Helper to attempt loading data from local sources (custom then default).
    
    Local data loading is restricted to admin users only and requires the
    'local_data_loading' feature toggle to be enabled.
    
    Args:
        report_type: Type of report to load
        mission_id: Mission identifier
        custom_local_path: Custom local path if specified
        current_user: Current user for permission checking (must be admin)
        allow_system_access: If True, bypass admin check for system operations (e.g., startup)
        
    Returns:
        Tuple of (DataFrame or None, source_path_string, file_modification_time)
    """
    # Check if local data loading is enabled
    if not is_feature_enabled("local_data_loading"):
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
    """
    Helper to attempt loading data from remote sources based on user role.
    
    NOTE: With local storage sync, this is now primarily a fallback.
    Local storage should be checked first via _load_from_local_sources.
    
    Args:
        report_type: Type of report to load
        mission_id: Mission identifier
        current_user: Current user for access control
        
    Returns:
        Tuple of (DataFrame or None, source_path_string, file_modification_time)
    """
    actual_source_path = "Data not loaded"
    # Look up remote folder name
    # Mission ID format is now "1071-m169" (project-mission)
    # Mapping keys are "1071 m169" (project mission with space)
    # Mapping values are "m169-C34166NS" (remote folder names)
    
    remote_mission_folder = None
    
    # Try exact match first (for backward compatibility)
    remote_mission_folder = settings.remote_mission_folder_map.get(mission_id)
    
    if remote_mission_folder is None:
        # Handle "1071-m169" format - convert to "1071 m169" for lookup
        if '-' in mission_id:
            # Convert "1071-m169" to "1071 m169" format
            parts = mission_id.split('-', 1)
            if len(parts) == 2:
                lookup_key = f"{parts[0]} {parts[1]}"  # "1071 m169"
                remote_mission_folder = settings.remote_mission_folder_map.get(lookup_key)
                if remote_mission_folder:
                    logger.info(f"Mapped mission {mission_id} to remote folder {remote_mission_folder} via key '{lookup_key}'")
        
        # Fallback: try fuzzy matching (for legacy "m169" format)
        if remote_mission_folder is None:
            # Extract mission base (e.g., "m169" from "1071-m169" or just "m169")
            mission_base = mission_id.split('-')[-1] if '-' in mission_id else mission_id
            
            for key, value in settings.remote_mission_folder_map.items():
                if (key.endswith(f" {mission_base}") or 
                    key.endswith(mission_base) or 
                    key == mission_base or
                    f" {mission_base}" in key or
                    key.endswith(f"-{mission_base}")):
                    remote_mission_folder = value
                    logger.info(f"Mapped mission {mission_id} to remote folder {remote_mission_folder} via key '{key}' (fuzzy match)")
                    break
        
        # Final fallback: use mission_id as-is
        if remote_mission_folder is None:
            remote_mission_folder = mission_id
            logger.warning(f"No remote folder mapping found for {mission_id}, using mission_id as folder name. Available keys: {list(settings.remote_mission_folder_map.keys())[:5]}")
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
        df, actual_source_path, file_modification_time = await _load_from_local_sources(report_type, mission_id, custom_local_path, current_user, allow_system_access)
    elif source_preference == "remote":
        # Remote-only preference - try remote first
        load_attempted = True
        df, actual_source_path, file_modification_time = await _load_from_remote_sources(report_type, mission_id, current_user)
        if df is None:  # If remote failed, try local as fallback (only if admin and feature enabled)
            logger.warning(f"Remote preference failed for {report_type} ({mission_id}). Attempting local fallback (if enabled).")
            df_fallback, path_fallback, file_mod_time_fallback = await _load_from_local_sources(report_type, mission_id, None, current_user, allow_system_access)
            if df_fallback is not None:
                df, actual_source_path, file_modification_time = df_fallback, path_fallback, file_mod_time_fallback
            elif "Data not loaded" in actual_source_path or "Access Restricted" in actual_source_path:
                if path_fallback and "Data not loaded" not in path_fallback:
                    actual_source_path = path_fallback
                    file_modification_time = file_mod_time_fallback
    elif source_preference is None:
        # No preference - always try remote first (default), local is never default
        load_attempted = True
        df, actual_source_path, file_modification_time = await _load_from_remote_sources(report_type, mission_id, current_user)
        # Local is never used as default - only when explicitly requested by admin
    
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
    
    return new_df, source_path, file_modification_time


# ============================================================================
# DataService Class
# ============================================================================

class DataService:
    """
    Service for loading and caching mission data.
    
    This service provides a clean interface for data loading operations
    and eliminates circular dependencies between routers and app.py.
    """
    
    def __init__(self):
        """Initialize the data service."""
        pass
    
    async def load(
        self,
        report_type: str,
        mission_id: str,
        source_preference: Optional[str] = None,
        custom_local_path: Optional[str] = None,
        force_refresh: bool = False,
        current_user: Optional[models.User] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        hours_back: Optional[int] = None,
    ) -> Tuple[pd.DataFrame, str, Optional[datetime]]:
        """
        Load data for a mission with time-aware caching and overlap-based gap prevention.
        
        Enhanced load_data_source with time-aware caching and overlap-based gap prevention.
        
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
            Tuple of (DataFrame, source_path)
        """
        
        # Create time-aware cache key
        cache_key = create_time_aware_cache_key(
            report_type, mission_id, start_date, end_date, hours_back, 
            source_preference, custom_local_path
        )
        
        # Get cache strategy for this report type
        cache_strategy = get_cache_strategy(report_type)
        
        # Update user activity tracking
        if current_user:
            update_user_activity(str(current_user.id), "data_request")
            if hasattr(current_user, 'username'):
                user_sessions[str(current_user.id)]["missions_accessed"].add(mission_id)
                user_sessions[str(current_user.id)]["report_types_accessed"].add(report_type)
                
                # Log mission usage (using dedicated logger if available)
                try:
                    mission_usage_logger = logging.getLogger('mission_usage')
                    if mission_usage_logger.handlers:  # Only log if handler is configured
                        mission_usage_logger.info(
                            f"MISSION_USAGE: user_id={current_user.id}, "
                            f"username={current_user.username}, mission_id={mission_id}, "
                            f"report_type={report_type}, timestamp={datetime.now(timezone.utc).isoformat()}"
                        )
                except Exception:
                    pass
        
        # Check cache first (unless force refresh)
        if not force_refresh and cache_key in data_cache:
            cached_df, cached_source_path, cache_timestamp, last_data_timestamp, cached_file_mod_time = data_cache[cache_key]
            
            # Determine if this is a static data source
            is_static = is_static_data_source(cached_source_path, report_type, mission_id)
            
            if is_static:
                # Static data never expires - always return from cache
                logger.debug(
                    f"CACHE HIT (static): Returning {report_type} for {mission_id} "
                    f"from cache. Source: {cached_source_path}"
                )
                # Update cache statistics
                data_size_mb = len(cached_df) * cached_df.memory_usage(deep=True).sum() / (1024 * 1024) if not cached_df.empty else 0
                update_cache_stats(report_type, mission_id, cache_hit=True, data_size_mb=data_size_mb)
                # Trim to requested range and return
                return trim_data_to_range(cached_df, start_date, end_date, hours_back), cached_source_path, cached_file_mod_time
            else:
                # Dynamic data - always try incremental loading first if we have existing data
                if cache_strategy["incremental"] and last_data_timestamp:
                    logger.debug(
                        f"CACHE HIT (incremental): {report_type} for {mission_id} "
                        f"has existing data. Checking for updates since {last_data_timestamp}."
                    )
                    # Try incremental loading with overlap
                    new_df, new_source_path, new_file_mod_time = await load_incremental_data_with_overlap(
                        report_type, mission_id, last_data_timestamp, 
                        cache_strategy["overlap_hours"], source_preference, 
                        custom_local_path, current_user
                    )
                    
                    # Always update cache_timestamp to indicate a refresh attempt was made
                    # This ensures frontend polling can detect refresh cycles even if no new data is found
                    refresh_timestamp = datetime.now(timezone.utc)
                    
                    # Update cache with new data and file modification time
                    if new_df is not None and not new_df.empty:
                        # Merge with existing cached data
                        if not cached_df.empty:
                            # Ensure both DataFrames have "Timestamp" column before merging
                            # If new_df doesn't have "Timestamp", it needs preprocessing
                            if "Timestamp" not in new_df.columns:
                                # Preprocess the new data to ensure it has "Timestamp"
                                from .processor_framework import get_processor
                                preprocess_func = get_processor(report_type)
                                if preprocess_func:
                                    new_df = preprocess_func(new_df)
                            
                            # Only merge if both have "Timestamp" column
                            if "Timestamp" in cached_df.columns and "Timestamp" in new_df.columns:
                                # Combine old and new data, removing duplicates
                                combined_df = pd.concat([cached_df, new_df]).drop_duplicates(subset=["Timestamp"], keep="last").sort_values("Timestamp")
                            else:
                                # If columns don't match, just use new data
                                logger.warning(f"Cannot merge {report_type} data: column mismatch. Using new data only.")
                                combined_df = new_df
                        else:
                            combined_df = new_df
                        
                        # Update last_data_timestamp
                        if "Timestamp" in combined_df.columns:
                            updated_last_data_timestamp = combined_df["Timestamp"].max()
                            if hasattr(updated_last_data_timestamp, 'to_pydatetime'):
                                updated_last_data_timestamp = updated_last_data_timestamp.to_pydatetime()
                            elif isinstance(updated_last_data_timestamp, (int, float)):
                                updated_last_data_timestamp = datetime.fromtimestamp(updated_last_data_timestamp, tz=timezone.utc)
                            elif not isinstance(updated_last_data_timestamp, datetime):
                                updated_last_data_timestamp = pd.to_datetime(updated_last_data_timestamp, utc=True)
                        else:
                            updated_last_data_timestamp = last_data_timestamp
                        
                        # Update cache with merged data and new file modification time
                        # Always update cache_timestamp to indicate a refresh attempt was made
                        data_cache[cache_key] = (
                            combined_df, new_source_path, refresh_timestamp, updated_last_data_timestamp, new_file_mod_time or cached_file_mod_time
                        )
                        logger.debug(f"Cache updated (incremental): {report_type} for {mission_id}, cache_timestamp={refresh_timestamp.isoformat()}, new_data=True")
                    else:
                        # No new data found, but still update cache_timestamp to indicate refresh attempt
                        # This ensures frontend polling can detect that a refresh cycle occurred
                        data_cache[cache_key] = (
                            cached_df, cached_source_path, refresh_timestamp, last_data_timestamp, cached_file_mod_time
                        )
                        logger.debug(f"Cache timestamp updated (no new data): {report_type} for {mission_id}, cache_timestamp={refresh_timestamp.isoformat()}, new_data=False")
                    
                    return trim_data_to_range(combined_df if new_df is not None and not new_df.empty else cached_df, start_date, end_date, hours_back), new_source_path if new_df is not None else cached_source_path, new_file_mod_time if new_df is not None else cached_file_mod_time
                else:
                    # No existing data or not incremental - return cached data
                    logger.debug(
                        f"CACHE HIT (no-incremental): Returning {report_type} for {mission_id} "
                        f"from cache. Source: {cached_source_path}"
                    )
                    # Update cache statistics
                    data_size_mb = len(cached_df) * cached_df.memory_usage(deep=True).sum() / (1024 * 1024) if not cached_df.empty else 0
                    update_cache_stats(report_type, mission_id, cache_hit=True, data_size_mb=data_size_mb)
                    # Trim to requested range and return
                    return trim_data_to_range(cached_df, start_date, end_date, hours_back), cached_source_path, cached_file_mod_time
        
        # Load data with overlap to prevent gaps
        # Priority: local first (fastest), then remote (fallback)
        # If source_preference is "local", only try local
        # If source_preference is "remote" or None, try local first, then remote
        df = None
        actual_source_path = "Data not loaded"
        file_modification_time = None
        
        # Try local first (preferred - faster and more reliable)
        if source_preference != "remote":
            df, actual_source_path, file_modification_time = await _load_from_local_sources(
                report_type, mission_id, custom_local_path
            )
        
        # Fall back to remote if local failed or source_preference is "remote"
        if df is None or df.empty:
            if source_preference != "local":
                df, actual_source_path, file_modification_time = await _load_from_remote_sources(
                    report_type, mission_id, current_user
                )
        
        # Store in cache with enhanced structure
        if df is not None and not df.empty:
            last_data_timestamp = None
            if "Timestamp" in df.columns and not df.empty:
                last_data_timestamp = df["Timestamp"].max()
            
            logger.debug(
                f"CACHE STORE: Storing {report_type} for {mission_id} "
                f"(from {actual_source_path}) into cache with overlap."
            )
            # Ensure last_data_timestamp is a proper datetime object
            if last_data_timestamp is not None:
                if hasattr(last_data_timestamp, 'to_pydatetime'):
                    last_data_timestamp = last_data_timestamp.to_pydatetime()
                elif isinstance(last_data_timestamp, (int, float)):
                    last_data_timestamp = datetime.fromtimestamp(last_data_timestamp, tz=timezone.utc)
                elif not isinstance(last_data_timestamp, datetime):
                    last_data_timestamp = pd.to_datetime(last_data_timestamp, utc=True)
            
            data_cache[cache_key] = (
                df, actual_source_path, datetime.now(timezone.utc), last_data_timestamp, file_modification_time
            )
            
            # Update cache statistics for miss and store
            data_size_mb = len(df) * df.memory_usage(deep=True).sum() / (1024 * 1024) if not df.empty else 0
            update_cache_stats(report_type, mission_id, cache_hit=False, data_size_mb=data_size_mb, is_refresh=True)
        else:
            # Update cache statistics for miss (no data)
            update_cache_stats(report_type, mission_id, cache_hit=False, is_refresh=True)
        
        # Return trimmed data for the exact requested range
        return trim_data_to_range(df if df is not None else pd.DataFrame(), start_date, end_date, hours_back), actual_source_path, file_modification_time

    async def load_and_validate(
        self,
        report_type: str,
        mission_id: str,
        error_message: Optional[str] = None,
        source_preference: Optional[str] = None,
        custom_local_path: Optional[str] = None,
        force_refresh: bool = False,
        current_user: Optional[models.User] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        hours_back: Optional[int] = None,
    ) -> Tuple[pd.DataFrame, str]:
        """
        Load data and validate that it exists, raising HTTPException if not found.
        
        This is a convenience method that combines load() with validation.
        Use this when you want to fail fast if data doesn't exist.
        
        Args:
            report_type: Type of report to load
            mission_id: Mission identifier
            error_message: Custom error message for 404 (defaults to generic message)
            source_preference: 'local' or 'remote'
            custom_local_path: Custom local path if specified
            force_refresh: Bypass cache and force refresh
            current_user: Current user for access control
            start_date: Start date for time range
            end_date: End date for time range
            hours_back: Hours back from now
            
        Returns:
            Tuple of (DataFrame, source_path)
            
        Raises:
            HTTPException: If data is None or empty
        """
        from fastapi import HTTPException
        
        df, source_path, _ = await self.load(
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
        
        if df is None or df.empty:
            if error_message is None:
                error_message = f"No {report_type} data found for mission {mission_id}"
            raise HTTPException(status_code=404, detail=error_message)
        
        return df, source_path

    async def load_and_preprocess(
        self,
        report_type: str,
        mission_id: str,
        preprocess_func,
        error_message: Optional[str] = None,
        preprocessed_error_message: Optional[str] = None,
        source_preference: Optional[str] = None,
        custom_local_path: Optional[str] = None,
        force_refresh: bool = False,
        current_user: Optional[models.User] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        hours_back: Optional[int] = None,
    ) -> Tuple[pd.DataFrame, str]:
        """
        Load data, preprocess it, and validate both raw and preprocessed data exist.
        
        This is a convenience method that combines load(), preprocessing, and validation.
        Use this when you need to load and preprocess data in one step.
        
        Args:
            report_type: Type of report to load
            mission_id: Mission identifier
            preprocess_func: Function to preprocess the DataFrame (e.g., preprocess_telemetry_df)
            error_message: Custom error message if raw data not found (defaults to generic)
            preprocessed_error_message: Custom error message if preprocessed data is empty
            source_preference: 'local' or 'remote'
            custom_local_path: Custom local path if specified
            force_refresh: Bypass cache and force refresh
            current_user: Current user for access control
            start_date: Start date for time range
            end_date: End date for time range
            hours_back: Hours back from now
            
        Returns:
            Tuple of (preprocessed_DataFrame, source_path)
            
        Raises:
            HTTPException: If raw data or preprocessed data is empty
        """
        from fastapi import HTTPException
        
        # Load and validate raw data exists
        df, source_path = await self.load_and_validate(
            report_type=report_type,
            mission_id=mission_id,
            error_message=error_message,
            source_preference=source_preference,
            custom_local_path=custom_local_path,
            force_refresh=force_refresh,
            current_user=current_user,
            start_date=start_date,
            end_date=end_date,
            hours_back=hours_back,
        )
        
        # Preprocess
        processed_df = preprocess_func(df)
        
        # Validate preprocessed data
        if processed_df.empty:
            if preprocessed_error_message is None:
                preprocessed_error_message = f"No processed {report_type} data available for mission {mission_id}"
            raise HTTPException(status_code=404, detail=preprocessed_error_message)
        
        return processed_df, source_path

    async def load_multiple(
        self,
        report_types: List[str],
        mission_id: str,
        source_preference: Optional[str] = None,
        custom_local_path: Optional[str] = None,
        force_refresh: bool = False,
        current_user: Optional[models.User] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        hours_back: Optional[int] = None,
    ) -> Dict[str, Tuple[pd.DataFrame, str, Optional[datetime]]]:
        """
        Load multiple report types concurrently for a mission.
        
        This is useful when you need multiple data types at once (e.g., for reports).
        All data types are loaded in parallel for better performance.
        
        Args:
            report_types: List of report types to load
            mission_id: Mission identifier
            source_preference: 'local' or 'remote'
            custom_local_path: Custom local path if specified
            force_refresh: Bypass cache and force refresh
            current_user: Current user for access control
            start_date: Start date for time range
            end_date: End date for time range
            hours_back: Hours back from now
            
        Returns:
            Dictionary mapping report_type to (DataFrame, source_path, file_modification_time) tuple
            Missing or empty data will have empty DataFrame
        """
        import asyncio
        
        # Create load tasks for all report types
        tasks = [
            self.load(
                report_type=rt,
                mission_id=mission_id,
                source_preference=source_preference,
                custom_local_path=custom_local_path,
                force_refresh=force_refresh,
                current_user=current_user,
                start_date=start_date,
                end_date=end_date,
                hours_back=hours_back,
            )
            for rt in report_types
        ]
        
        # Execute all loads concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Build result dictionary
        result_dict = {}
        for report_type, result in zip(report_types, results):
            if isinstance(result, Exception):
                logger.warning(f"Error loading {report_type} for {mission_id}: {result}")
                result_dict[report_type] = (pd.DataFrame(), "Error", None)
            else:
                result_dict[report_type] = result
        
        return result_dict


# Create a singleton instance for convenience
# Routers can use: from ..core.data_service import data_service
_data_service_instance: Optional[DataService] = None


def get_data_service() -> DataService:
    """
    Get the singleton data service instance.
    
    Returns:
        DataService instance
    """
    global _data_service_instance
    if _data_service_instance is None:
        _data_service_instance = DataService()
    return _data_service_instance


# Convenience alias for direct import
data_service = get_data_service()

