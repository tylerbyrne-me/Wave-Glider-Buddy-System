import pandas as pd
from typing import Optional
import logging
from . import summaries # For the time_ago function

logger = logging.getLogger(__name__)

def get_df_latest_update_info(df: Optional[pd.DataFrame], timestamp_col: str = "Timestamp") -> dict:
    """Helper to get latest timestamp and time_ago string from a DataFrame."""
    if df is None or df.empty or timestamp_col not in df.columns:
        return {"latest_timestamp_str": "N/A", "time_ago_str": "N/A"}
    
    # Ensure timestamp_col is datetime and handle potential errors
    try:
        df_copy = df.copy() # Work on a copy to avoid SettingWithCopyWarning
        df_copy[timestamp_col] = pd.to_datetime(df_copy[timestamp_col], errors='coerce')
        df_copy = df_copy.dropna(subset=[timestamp_col])
    except Exception as e:
        logger.error(f"Error processing timestamp column '{timestamp_col}': {e}")
        return {"latest_timestamp_str": "N/A", "time_ago_str": "N/A"}

    if df_copy.empty:
        return {"latest_timestamp_str": "N/A", "time_ago_str": "N/A"}

    latest_timestamp = df_copy[timestamp_col].max()
    latest_timestamp_str = "N/A"
    time_ago_str = "N/A" 
    if pd.notna(latest_timestamp):
        latest_timestamp_str = latest_timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')
        time_ago_str = summaries.time_ago(latest_timestamp) 
    return {"latest_timestamp_str": latest_timestamp_str, "time_ago_str": time_ago_str}