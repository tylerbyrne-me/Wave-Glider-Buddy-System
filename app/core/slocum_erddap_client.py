"""
Slocum ERDDAP client - Ocean Track Slocum glider data.

Single source of truth for fetching Slocum tabledap data from ERDDAP.
Used by exploration API, map telemetry endpoint, and CLI/scripts.
Server URL is read from app config (slocum_erddap_server).
"""

import logging
import time
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

# Variables for Slocum mission dashboard charts (depth, altitude, pitch, roll, navigation, power)
SLOCUM_DASHBOARD_VARIABLES = [
    "time",
    "m_depth",
    "m_altitude",
    "m_raw_altitude",
    "m_water_depth",
    "c_pitch",
    "m_pitch",
    "m_roll",
    "c_heading",
    "m_heading",
    "c_fin",
    "m_fin",
    "m_battery",
    "m_coulomb_amphr_total",
]

# Variables for CTD sensor card (conductivity, temperature, pressure, salinity, density)
SLOCUM_CTD_VARIABLES = [
    "time",
    "conductivity",
    "temperature",
    "pressure",
    "salinity",
    "density",
]

# Timeout in seconds for ERDDAP HTTP requests (avoids hanging on slow/unresponsive server)
ERDDAP_TIMEOUT = 30
# Retry transient connection errors (e.g. remote host closed connection, timeouts)
ERDDAP_RETRY_ATTEMPTS = 3
ERDDAP_RETRY_DELAY_SECONDS = 2


# ============================================================================
# Main Functions
# ============================================================================

def fetch_slocum_data(
    dataset_id: str,
    time_start: Optional[str] = None,
    time_end: Optional[str] = None,
    variables: Optional[list[str]] = None,
    pandas_kwargs: Optional[dict] = None,
) -> pd.DataFrame:
    """
    Fetch Slocum tabledap data from Ocean Track ERDDAP as a pandas DataFrame.

    Sync function; call from async code via asyncio.to_thread().

    Args:
        dataset_id: ERDDAP dataset_id (e.g. peggy_20250522_206_delayed).
        time_start: Start time ISO 8601 (e.g. 2025-08-01T00:00:00Z). If None with time_end, no time filter.
        time_end: End time ISO 8601 (e.g. 2025-08-31T23:59:59Z). If None with time_start, no time filter.
        variables: Optional list of variable names; defaults to DEFAULT_VARIABLES.
        pandas_kwargs: Optional dict passed to pandas.read_csv (e.g. {"skiprows": [1]}
            to skip a separate units row if the server returns two header rows).

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
    to_pandas_kw = {"requests_kwargs": {"timeout": ERDDAP_TIMEOUT}}
    if pandas_kwargs:
        to_pandas_kw.update(pandas_kwargs)

    last_err: Exception | None = None
    df: pd.DataFrame | None = None
    for attempt in range(ERDDAP_RETRY_ATTEMPTS):
        try:
            df = e.to_pandas(**to_pandas_kw)
            break
        except OSError as err:
            last_err = err
            if attempt < ERDDAP_RETRY_ATTEMPTS - 1:
                logger.warning(
                    "ERDDAP connection error for %s (attempt %s/%s): %s; retrying in %ss",
                    dataset_id, attempt + 1, ERDDAP_RETRY_ATTEMPTS, err, ERDDAP_RETRY_DELAY_SECONDS,
                )
                time.sleep(ERDDAP_RETRY_DELAY_SECONDS)
            else:
                logger.warning(f"ERDDAP fetch failed for {dataset_id}: {err}")
                raise
        except Exception as err:
            last_err = err
            # Retry on connection/timeout-style errors from requests (erddapy uses requests)
            if attempt < ERDDAP_RETRY_ATTEMPTS - 1:
                err_msg = str(err).lower()
                if "connection" in err_msg or "forcibly closed" in err_msg or "timeout" in err_msg or "10054" in err_msg:
                    logger.warning(
                        "ERDDAP request error for %s (attempt %s/%s): %s; retrying in %ss",
                        dataset_id, attempt + 1, ERDDAP_RETRY_ATTEMPTS, err, ERDDAP_RETRY_DELAY_SECONDS,
                    )
                    time.sleep(ERDDAP_RETRY_DELAY_SECONDS)
                    continue
            logger.warning(f"ERDDAP fetch failed for {dataset_id}: {err}")
            raise
    # df is set by the successful to_pandas() call when we break
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


def fetch_slocum_ctd_data(
    dataset_id: str,
    time_start: Optional[str] = None,
    time_end: Optional[str] = None,
    pandas_kwargs: Optional[dict] = None,
) -> pd.DataFrame:
    """
    Fetch Slocum CTD data (time, conductivity, temperature, pressure, salinity, density) from ERDDAP.

    Used by the CTD sensor card. Sync; call via asyncio.to_thread() from async code.
    """
    return fetch_slocum_data(
        dataset_id=dataset_id,
        time_start=time_start,
        time_end=time_end,
        variables=SLOCUM_CTD_VARIABLES,
        pandas_kwargs=pandas_kwargs,
    )


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


def fetch_slocum_dashboard_data(
    dataset_id: str,
    time_start: Optional[str] = None,
    time_end: Optional[str] = None,
    pandas_kwargs: Optional[dict] = None,
) -> pd.DataFrame:
    """
    Fetch Slocum data for dashboard charts (time, m_depth, m_altitude, m_raw_altitude, m_water_depth, c_pitch, m_pitch, m_roll).

    Convenience wrapper around fetch_slocum_data with SLOCUM_DASHBOARD_VARIABLES.

    Args:
        dataset_id: ERDDAP dataset_id.
        time_start: Start time ISO 8601. Optional.
        time_end: End time ISO 8601. Optional.
        pandas_kwargs: Optional dict for pandas.read_csv (e.g. skiprows for a units row).

    Returns:
        Raw DataFrame with ERDDAP column names (e.g. time (UTC), m_depth (m)).
    """
    return fetch_slocum_data(
        dataset_id=dataset_id,
        time_start=time_start,
        time_end=time_end,
        variables=SLOCUM_DASHBOARD_VARIABLES,
        pandas_kwargs=pandas_kwargs,
    )
