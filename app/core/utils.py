import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Union

import pandas as pd

logger = logging.getLogger(__name__)

# Minimum valid date for timestamps (filters out epoch dates from parsing failures)
MIN_VALID_TIMESTAMP = datetime(2000, 1, 1, tzinfo=timezone.utc)


def _ensure_utc(ts: pd.Timestamp) -> pd.Timestamp:
    """
    Helper function to ensure a timestamp is UTC-aware.
    
    Args:
        ts: pandas Timestamp (may be naive or in another timezone)
        
    Returns:
        UTC-aware pandas Timestamp
    """
    if pd.isna(ts):
        return ts
    if ts.tz is None:
        return ts.tz_localize('UTC')
    elif str(ts.tz) != 'UTC':
        return ts.tz_convert('UTC')
    return ts


def parse_timestamp_robust(
    timestamp_value: Union[str, datetime, pd.Timestamp, None],
    errors: str = 'coerce'
) -> Optional[pd.Timestamp]:
    """
    Robustly parse a timestamp value that can be in multiple formats.
    
    Handles:
    - ISO 8601 formats: '2025-10-27T14:13:15Z', '2025-10-27T14:13:15+00:00', etc.
    - 12hr AM/PM format: '10/27/2025 2:13:14PM' (UTC)
    - Already parsed datetime/Timestamp objects
    
    Args:
        timestamp_value: The timestamp value to parse (can be string, datetime, Timestamp, or None)
        errors: How to handle errors ('coerce' returns NaT, 'raise' raises exception)
    
    Returns:
        pd.Timestamp with UTC timezone, or NaT if parsing fails and errors='coerce'
    """
    if timestamp_value is None or pd.isna(timestamp_value):
        return pd.NaT if errors == 'coerce' else None
    
    # If already a datetime/Timestamp, ensure UTC
    if isinstance(timestamp_value, (datetime, pd.Timestamp)):
        return _ensure_utc(pd.Timestamp(timestamp_value))
    
    if not isinstance(timestamp_value, str):
        # Try to convert to string first
        timestamp_value = str(timestamp_value)
    
    if not timestamp_value or timestamp_value.strip() == '':
        return pd.NaT if errors == 'coerce' else None
    
    timestamp_value = timestamp_value.strip()
    
    # Try pandas ISO8601 parser first (handles most ISO 8601 formats reliably)
    # This covers: 2025-10-27T14:13:15Z, 2025-10-27T14:13:15+00:00, etc.
    try:
        ts = pd.to_datetime(timestamp_value, format='ISO8601', errors='raise', utc=True)
        if isinstance(ts, pd.Timestamp):
            return _ensure_utc(ts)
        return ts
    except (ValueError, TypeError):
        pass
    
    # Try simple ISO-like formats with strptime (for naive timestamps)
    iso_formats = [
        '%Y-%m-%dT%H:%M:%S',            # 2025-10-27T14:13:15 (naive, will assume UTC)
        '%Y-%m-%d %H:%M:%S',            # 2025-10-27 14:13:15 (naive, will assume UTC)
        '%Y-%m-%d %H:%M:%S.%f',         # 2025-10-27 14:13:15.123456 (naive, will assume UTC)
    ]
    
    for fmt in iso_formats:
        try:
            ts = datetime.strptime(timestamp_value, fmt)
            # Naive timestamps are assumed UTC (all our data sources are UTC)
            ts = ts.replace(tzinfo=timezone.utc)
            return pd.Timestamp(ts)
        except (ValueError, TypeError):
            continue
    
    # Try 12hr AM/PM format: '10/27/2025 2:13:14PM' (new format from upstream)
    # Handle various AM/PM format variations
    am_pm_formats = [
        '%m/%d/%Y %I:%M:%S%p',          # 10/27/2025 2:13:14PM
        '%m/%d/%Y %I:%M:%S %p',         # 10/27/2025 2:13:14 PM (with space)
        '%m/%d/%Y %I:%M%p',             # 10/27/2025 2:13PM (without seconds)
        '%m/%d/%Y %I:%M %p',            # 10/27/2025 2:13 PM
        '%m-%d-%Y %I:%M:%S%p',          # 10-27-2025 2:13:14PM (with dashes)
        '%m-%d-%Y %I:%M:%S %p',         # 10-27-2025 2:13:14 PM
        # Note: %-I and %#I don't work in Python strptime, handled by regex below
    ]
    
    for fmt in am_pm_formats:
        try:
            # Try parsing with the format
            ts = datetime.strptime(timestamp_value, fmt)
            # AM/PM format is always UTC per user specification
            ts = ts.replace(tzinfo=timezone.utc)
            return pd.Timestamp(ts)
        except (ValueError, TypeError):
            continue
    
    # Special handling for single-digit hours (e.g., "10/27/2025 2:13:14PM" vs "10/27/2025 02:13:14PM")
    # Python's strptime requires leading zeros, so we use regex for single-digit hours
    am_pm_pattern = r'(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}):(\d{2}):(\d{2})\s*(AM|PM)'
    match = re.match(am_pm_pattern, timestamp_value, re.IGNORECASE)
    if match:
        try:
            month, day, year, hour, minute, second, am_pm = match.groups()
            month, day, year = int(month), int(day), int(year)
            hour, minute, second = int(hour), int(minute), int(second)
            
            # Convert to 24-hour format
            if am_pm.upper() == 'PM' and hour != 12:
                hour += 12
            elif am_pm.upper() == 'AM' and hour == 12:
                hour = 0
            
            ts = datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)
            return pd.Timestamp(ts)
        except (ValueError, TypeError):
            pass
    
    # Fallback to pandas' dateutil parser (last resort)
    try:
        ts = pd.to_datetime(timestamp_value, errors=errors, utc=True)
        if isinstance(ts, pd.Timestamp):
            return _ensure_utc(ts)
        return ts
    except Exception:
        if errors == 'coerce':
            return pd.NaT
        raise


def parse_timestamp_column(
    series: pd.Series,
    errors: str = 'coerce',
    utc: bool = True
) -> pd.Series:
    """
    Robustly parse a pandas Series of timestamp values that may contain mixed formats.
    
    This function handles datasets with mixed timestamp formats by parsing each value
    individually. Useful when upstream data sources have inconsistent timestamp formats.
    
    Args:
        series: pandas Series containing timestamp values (strings, datetimes, or mixed)
        errors: How to handle errors ('coerce' returns NaT, 'raise' raises exception)
        utc: Ensure all timestamps are UTC-aware (default True)
    
    Returns:
        pd.Series of pd.Timestamp objects, all UTC-aware if utc=True
    """
    if series.empty:
        return series
    
    # Check if already datetime
    if pd.api.types.is_datetime64_any_dtype(series):
        # Ensure UTC if requested - use vectorized operations
        if utc:
            # Vectorized UTC conversion for already-datetime series
            if series.dt.tz is None:
                return series.dt.tz_localize('UTC')
            else:
                return series.dt.tz_convert('UTC')
        return series
    
    # Try to parse all at once first (faster if format is consistent)
    # Strategy: Try bulk parsing with different methods before falling back to row-by-row
    
    # 1. Try pandas' flexible parser first (handles ISO8601 and many formats via dateutil)
    # This should handle both ISO8601 and AM/PM formats efficiently
    try:
        parsed = pd.to_datetime(series, errors='coerce', utc=True)
        success_rate = parsed.notna().sum() / len(series) if len(series) > 0 else 0
        
        # If most succeed, use bulk result and only fix failures individually
        if success_rate >= 0.95:  # 95% threshold - tolerate some failures
            # Only parse the failed ones individually (much faster than all row-by-row)
            failed_mask = parsed.isna() & series.notna()  # Only process actual failures, not NaNs
            if failed_mask.any():
                failed_indices = series[failed_mask].index
                for idx in failed_indices:
                    try:
                        parsed[idx] = parse_timestamp_robust(series[idx], errors=errors)
                    except Exception:
                        if errors == 'coerce':
                            parsed[idx] = pd.NaT
            return parsed
    except Exception:
        pass
    
    # 2. Try ISO8601 format specifically if flexible parser had low success rate
    # (This can be faster for purely ISO8601 data)
    try:
        parsed = pd.to_datetime(series, format='ISO8601', errors='coerce', utc=True)
        success_rate = parsed.notna().sum() / len(series) if len(series) > 0 else 0
        if success_rate >= 0.95:
            # Handle the few failures individually
            failed_mask = parsed.isna() & series.notna()
            if failed_mask.any():
                failed_indices = series[failed_mask].index
                for idx in failed_indices:
                    try:
                        parsed[idx] = parse_timestamp_robust(series[idx], errors=errors)
                    except Exception:
                        if errors == 'coerce':
                            parsed[idx] = pd.NaT
            return parsed
    except Exception:
        pass
    
    # 4. Last resort: parse row by row (slow, but handles truly mixed formats)
    # Only do this if bulk parsing failed significantly
    def parse_single(ts_value):
        try:
            return parse_timestamp_robust(ts_value, errors=errors)
        except Exception:
            if errors == 'coerce':
                return pd.NaT
            raise
    
    result = series.apply(parse_single)
    
    return result


def get_df_latest_update_info(
    df: Optional[pd.DataFrame], timestamp_col: str = "Timestamp"
) -> dict:
    """Helper to get latest timestamp and time_ago string from a DataFrame. Returns safe defaults and logs errors if data is missing or malformed."""
    try:
        if df is None or df.empty or timestamp_col not in df.columns:
            return {"latest_timestamp_str": "N/A", "time_ago_str": "N/A"}

        # Ensure timestamp_col is datetime and handle potential errors # noqa
        try:
            df_copy = df.copy()  # Work on a copy to avoid SettingWithCopyWarning
            df_copy[timestamp_col] = parse_timestamp_column(
                df_copy[timestamp_col], errors="coerce", utc=True
            )
            df_copy = df_copy.dropna(subset=[timestamp_col])
        except Exception as e:
            logger.error(
                f"Error processing timestamp column '{timestamp_col}': {e}"
            )
            return {"latest_timestamp_str": "N/A", "time_ago_str": "N/A"}

        if df_copy.empty:
            return {"latest_timestamp_str": "N/A", "time_ago_str": "N/A"}

        latest_timestamp = df_copy[timestamp_col].max()
        latest_timestamp_str = "N/A"
        time_ago_str = "N/A"
        if pd.notna(latest_timestamp):
            latest_timestamp_str = latest_timestamp.strftime(
                "%Y-%m-%d %H:%M:%S UTC"
            )
            # Import here to avoid circular import
            from . import summaries
            time_ago_str = summaries.time_ago(latest_timestamp)
        return {
            "latest_timestamp_str": latest_timestamp_str,
            "time_ago_str": time_ago_str,
        }
    except Exception as e:
        logger.error(f"Error in get_df_latest_update_info: {e}")
        return {"latest_timestamp_str": "N/A", "time_ago_str": "N/A"}

def select_target_spectrum(
    spectral_records: List[Dict], requested_timestamp: Optional[datetime] = None
) -> Optional[Dict]:
    """
    Selects a spectral record from a list.
    If requested_timestamp is provided, finds the closest one. Otherwise, returns the latest.
    """ # noqa

    if not spectral_records:
        return None

    if requested_timestamp:
        # Ensure requested_timestamp is UTC for comparison
        # Use pd.Timestamp.now(tz="UTC").tzinfo for a reliable UTC timezone object
        utc_tz = pd.Timestamp.now(tz="UTC").tzinfo
        target_timestamp_utc = (
            requested_timestamp.astimezone(utc_tz) # noqa
            if requested_timestamp.tzinfo is None # noqa
            or requested_timestamp.tzinfo.utcoffset(requested_timestamp) is None
            else requested_timestamp # noqa
        )

        closest_record = min(
            spectral_records,
            key=lambda rec: abs(
                rec.get("timestamp", pd.Timestamp.min.tz_localize("UTC"))
                - target_timestamp_utc
            ),
        )
        # Optional: Add a threshold to ensure the "closest" isn't too far off
        if abs(
            closest_record.get("timestamp", pd.Timestamp.min.tz_localize("UTC"))
            - target_timestamp_utc
        ) < timedelta(
            hours=1
        ):  # Example threshold
            return closest_record
        else: # noqa
            logger.warning(
                f"Closest spectrum for timestamp {requested_timestamp} is too "
                f"far ({closest_record.get('timestamp')}). Returning latest."
            )
            return max(
                spectral_records,
                key=lambda rec: rec.get( # noqa
                    "timestamp", pd.Timestamp.min.tz_localize("UTC") # noqa
                ), # noqa
            )
    else:
        # Default to the latest spectral record
        return max(
            spectral_records,
            key=lambda rec: rec.get("timestamp", pd.Timestamp.min.tz_localize("UTC")),
        )
