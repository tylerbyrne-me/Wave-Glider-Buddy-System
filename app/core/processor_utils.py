"""
Shared utility functions for data processors.

This module contains common processing functions that are used by both
the processor framework and individual processor functions.
"""

import logging
from typing import Dict, List

import numpy as np
import pandas as pd

from . import utils

logger = logging.getLogger(__name__)


def standardize_timestamp_column(
    df: pd.DataFrame, preferred: str = "Timestamp"
) -> pd.DataFrame:
    """Renames the first found common timestamp column"""
    if df.empty:
        return df
    for col in df.columns:
        lower_col = col.lower()
        if "time" in lower_col or col in [
            "timeStamp",
            "gliderTimeStamp",
            "lastLocationFix",
        ]:
            df = df.rename(columns={col: preferred})
            return df
    return df


def initial_dataframe_setup(
    df: pd.DataFrame, target_timestamp_col: str
) -> pd.DataFrame:
    """
    Handles initial DataFrame checks, timestamp standardization, conversion to UTC, and NaT removal.
    Works on a copy of the input DataFrame.
    Returns an empty DataFrame if input is invalid or processing results in an empty DataFrame.
    """
    if df is None or df.empty:
        return pd.DataFrame()

    df_processed = df.copy()  # Work on a copy to avoid modifying the original DataFrame
    df_processed = standardize_timestamp_column(
        df_processed, preferred=target_timestamp_col
    )

    if target_timestamp_col not in df_processed.columns:
        logger.warning(
            f"Timestamp column '{target_timestamp_col}' not found after "
            f"standardization for '{target_timestamp_col}' type. Cannot proceed. Columns: {df_processed.columns.tolist()}"
        )
        return (
            pd.DataFrame()
        )  # Return empty if timestamp column is essential and not found

    # Parse timestamps - ALL timestamps are UTC, never convert to local time
    # Use robust parser to handle mixed formats (ISO 8601 and 12hr AM/PM)
    # parse_timestamp_column already ensures UTC timezone awareness
    df_processed[target_timestamp_col] = utils.parse_timestamp_column(
        df_processed[target_timestamp_col], errors="coerce", utc=True
    )
    
    # Remove NaT values (parsing failures)
    df_processed = df_processed.dropna(subset=[target_timestamp_col])
    
    # Filter out epoch dates (typically 1970-01-01 or 1969-12-31) which indicate parsing failures
    # Use the minimum valid timestamp constant from utils
    if not df_processed.empty:
        min_valid_date = pd.Timestamp(utils.MIN_VALID_TIMESTAMP)
        valid_mask = df_processed[target_timestamp_col] >= min_valid_date
        invalid_count = (~valid_mask).sum()
        if invalid_count > 0:
            logger.warning(
                f"Removing {invalid_count} rows with pre-2000 timestamps from preprocessing "
                f"(column: {target_timestamp_col})"
            )
        df_processed = df_processed[valid_mask].copy()

    return df_processed


def apply_common_processing(
    df: pd.DataFrame,
    timestamp_col: str,
    rename_map: Dict[str, str],
    numeric_cols: List[str],
) -> pd.DataFrame:
    """
    Applies a common sequence of preprocessing steps: timestamp setup, renaming, and numeric conversion.
    """
    df_processed = initial_dataframe_setup(df, timestamp_col)
    if df_processed.empty:
        # To ensure schema consistency even for empty dataframes, add expected columns
        expected_cols = [timestamp_col] + list(rename_map.values())
        for col in expected_cols:
            if col not in df_processed.columns:
                if col == timestamp_col:
                    df_processed[col] = pd.Series(dtype="datetime64[ns, UTC]")
                else:
                    df_processed[col] = np.nan
        return df_processed

    df_processed = df_processed.rename(columns=rename_map)

    all_expected_cols = [timestamp_col] + list(rename_map.values())

    for col in all_expected_cols:
        if col not in df_processed.columns:
            df_processed[col] = np.nan

        if col in numeric_cols:
            df_processed[col] = pd.to_numeric(
                df_processed[col], errors="coerce"
            )

    return df_processed

