"""
Slocum ERDDAP client - Ocean Track Slocum glider data.

Single source of truth for fetching Slocum tabledap data from ERDDAP.
Used by exploration API, map telemetry endpoint, and CLI/scripts.
Server URL is read from app config (slocum_erddap_server).
"""

import logging
from typing import Optional

import pandas as pd
from erddapy import ERDDAP

from ..config import settings

logger = logging.getLogger(__name__)


# ============================================================================
# Constants
# ============================================================================

def _get_erddap_server() -> str:
    """ERDDAP server URL from config (default Ocean Track)."""
    return getattr(settings, "slocum_erddap_server", "https://erddap.oceantrack.org/erddap")

DEFAULT_VARIABLES = [
    "time",
    "latitude",
    "longitude",
    "depth",
    "temperature",
    "salinity",
]

# Four variables for map track: time, lat, lon, depth
TRACK_VARIABLES = [
    "time",
    "latitude",
    "longitude",
    "depth",
]

# Timeout in seconds for ERDDAP HTTP requests (avoids hanging on slow/unresponsive server)
ERDDAP_TIMEOUT = 30


# ============================================================================
# Main Functions
# ============================================================================

def fetch_slocum_data(
    dataset_id: str,
    time_start: Optional[str] = None,
    time_end: Optional[str] = None,
    variables: Optional[list[str]] = None,
) -> pd.DataFrame:
    """
    Fetch Slocum tabledap data from Ocean Track ERDDAP as a pandas DataFrame.

    Sync function; call from async code via asyncio.to_thread().

    Args:
        dataset_id: ERDDAP dataset_id (e.g. peggy_20250522_206_delayed).
        time_start: Start time ISO 8601 (e.g. 2025-08-01T00:00:00Z). If None with time_end, no time filter.
        time_end: End time ISO 8601 (e.g. 2025-08-31T23:59:59Z). If None with time_start, no time filter.
        variables: Optional list of variable names; defaults to DEFAULT_VARIABLES.

    Returns:
        DataFrame with requested variables; column names may include units
        (e.g. "time (UTC)", "latitude (degrees_north)").

    Raises:
        Exception: On ERDDAP request or parse errors.
    """
    vars_ = variables or DEFAULT_VARIABLES
    server = _get_erddap_server()
    e = ERDDAP(server=server, protocol="tabledap")
    e.response = "csv"
    e.dataset_id = dataset_id
    if time_start is not None and time_end is not None:
        e.constraints = {"time>=": time_start, "time<=": time_end}
    else:
        e.constraints = {}
    e.variables = vars_
    logger.debug(f"Fetching Slocum dataset {dataset_id} from {server}")
    try:
        df = e.to_pandas(requests_kwargs={"timeout": ERDDAP_TIMEOUT})
    except Exception as err:
        logger.warning(f"ERDDAP fetch failed for {dataset_id}: {err}")
        raise
    if df is not None and not df.empty:
        logger.info(f"Fetched {len(df)} rows for dataset {dataset_id}")
    return df if df is not None else pd.DataFrame()


def list_slocum_datasets(search_term: Optional[str] = None) -> pd.DataFrame:
    """
    Query ERDDAP for available Slocum datasets (metadata only).

    Sync function; call from async code via asyncio.to_thread().

    Args:
        search_term: Optional string to filter datasets by title (case-insensitive).

    Returns:
        DataFrame with columns such as datasetID, title, institution, minTime, maxTime
        (exact columns depend on ERDDAP server). Empty DataFrame on error.
    """
    server = _get_erddap_server()
    e = ERDDAP(server=server, protocol="tabledap")
    e.response = "csv"
    e.dataset_id = "allDatasets"
    e.constraints = {}
    e.variables = ["datasetID", "title", "institution", "minTime", "maxTime"]
    logger.debug(f"Listing Slocum datasets from {server}")
    try:
        df = e.to_pandas(requests_kwargs={"timeout": ERDDAP_TIMEOUT})
    except Exception as err:
        logger.warning(f"ERDDAP allDatasets request failed: {err}")
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    if search_term and search_term.strip():
        term = search_term.strip().lower()
        if "title" in df.columns:
            mask = df["title"].astype(str).str.lower().str.contains(term, na=False)
            df = df.loc[mask]
    return df


def fetch_slocum_track(
    dataset_id: str,
    time_start: Optional[str] = None,
    time_end: Optional[str] = None,
) -> pd.DataFrame:
    """
    Fetch Slocum track data (time, latitude, longitude, depth) for map display.

    Convenience wrapper around fetch_slocum_data with TRACK_VARIABLES.

    Args:
        dataset_id: ERDDAP dataset_id.
        time_start: Start time ISO 8601. Optional; if both omitted, full dataset.
        time_end: End time ISO 8601. Optional; if both omitted, full dataset.

    Returns:
        Raw DataFrame with ERDDAP column names (e.g. time (UTC), latitude (degrees_north)).
    """
    return fetch_slocum_data(
        dataset_id=dataset_id,
        time_start=time_start,
        time_end=time_end,
        variables=TRACK_VARIABLES,
    )
