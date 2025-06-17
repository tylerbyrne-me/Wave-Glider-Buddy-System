import logging
from datetime import datetime, timedelta  # Added timedelta
from typing import Dict, List, Optional  # Added List and Dict for type hinting

import pandas as pd

from . import summaries  # For the time_ago function

logger = logging.getLogger(__name__)


def get_df_latest_update_info(
    df: Optional[pd.DataFrame], timestamp_col: str = "Timestamp"
) -> dict:
    """Helper to get latest timestamp and time_ago string from a DataFrame."""
    if df is None or df.empty or timestamp_col not in df.columns:
        return {"latest_timestamp_str": "N/A", "time_ago_str": "N/A"}

    # Ensure timestamp_col is datetime and handle potential errors # noqa
    try:
        df_copy = df.copy()  # Work on a copy to avoid SettingWithCopyWarning
        df_copy[timestamp_col] = pd.to_datetime(
            df_copy[timestamp_col], errors="coerce"
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
        time_ago_str = summaries.time_ago(latest_timestamp)
    return {
        "latest_timestamp_str": latest_timestamp_str,
        "time_ago_str": time_ago_str,
    }

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
