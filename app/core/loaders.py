import asyncio
import io
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

# import requests # disabled in favor of httpx
import httpx  # async http requests
import pandas as pd
from email.utils import parsedate_to_datetime

logger = logging.getLogger(
    __name__
)  # Keep this for actual operational logging
DEFAULT_TIMEOUT = 10.0  # seconds
RETRY_COUNT = 2  # Number of retries for loaders
from ..config import settings # Import settings to access the map


def _read_local_csv(file_path: Path) -> Tuple[pd.DataFrame, Optional[datetime]]:
    """Sync helper for thread pool: read local CSV and mtime."""
    df = pd.read_csv(file_path)
    file_mod_time = None
    try:
        mtime = os.path.getmtime(file_path)
        file_mod_time = datetime.fromtimestamp(mtime, tz=timezone.utc)
    except (OSError, ValueError) as e:
        logger.debug(f"Could not get file modification time for {file_path}: {e}")
    return df, file_mod_time


def _parse_csv_text(csv_text: str) -> pd.DataFrame:
    """Sync helper for thread pool: parse CSV from HTTP response body."""
    return pd.read_csv(io.StringIO(csv_text))


async def load_report(
    report_type: str,
    mission_id: str,
    base_path: Path = None,
    base_url: str = None,
    client: httpx.AsyncClient = None,
) -> Tuple[Optional[pd.DataFrame], Optional[datetime]]:
    """
    Loads a report as a DataFrame from local or remote.
    
    Returns:
        Tuple of (DataFrame or None, file_modification_time or None)
        file_modification_time: Last-Modified header for remote, file mtime for local
    """
    reports = {
        "power": "Amps Power Summary Report.csv",  # Existing
        "solar": "Amps Solar Input Port Report.csv",  # New solar panel report
        "ctd": "Seabird CTD Records with D.O..csv",
        "weather": "Weather Records 2.csv",
        "waves": "GPS Waves Sensor Data.csv",  # For Hs, Tp, Dp time-series
        "ais": "AIS Report.csv",
        "telemetry": "Telemetry 6 Report by WGMS Datetime.csv",
        "errors": "Vehicle Error Report.csv",
        "vr2c": "Vemco VR2c Status.csv",
        "fluorometer": "Fluorometer Samples 2.csv",  # New C3 Fluorometer
        "wave_frequency_spectrum": "GPS Waves Frequency Spectrum.csv",  # New
        "wave_energy_spectrum": "GPS Waves Energy Spectrum.csv",  # New
        "wg_vm4": "Vemco VM4 Daily Local Health.csv",  #  WG-VM4 sensor daily detection counts
        "wg_vm4_info": "Vemco VM4 Information.csv",  # WG-VM4 sensor info
        "wg_vm4_remote_health": "Vemco VM4 Remote Health.csv",  # VM4 remote health at connection
    }

    if report_type not in reports:
        raise ValueError(f"Unknown report type: {report_type}")

    filename = reports[report_type]

    if base_path:
        file_path = Path(base_path) / mission_id / filename
        try:
            df, file_mod_time = await asyncio.to_thread(_read_local_csv, file_path)
            return df, file_mod_time
        except FileNotFoundError as e:
            logger.info(
                f"File not found at local path: {file_path}. Error: {e}"
            )
            return None, None
    elif base_url:
        url = f"{str(base_url).rstrip('/')}/{mission_id}/{filename}"
        if client:
            try:
                response = await client.get(url, timeout=DEFAULT_TIMEOUT)
                response.raise_for_status()
                df = await asyncio.to_thread(_parse_csv_text, response.text)
                file_mod_time = None
                last_modified_header = response.headers.get("Last-Modified")
                if last_modified_header:
                    try:
                        file_mod_time = parsedate_to_datetime(last_modified_header)
                        if file_mod_time.tzinfo is None:
                            file_mod_time = file_mod_time.replace(tzinfo=timezone.utc)
                    except (ValueError, TypeError) as e:
                        logger.debug(
                            f"Could not parse Last-Modified header '{last_modified_header}' "
                            f"for {url}: {e}"
                        )
                return df, file_mod_time
            except httpx.RequestError as e:
                logger.error(f"HTTP request failed for {url}: {e}")
                return None, None
        else:
            try:
                transport = httpx.HTTPTransport(retries=RETRY_COUNT)
                async with httpx.AsyncClient(
                    timeout=DEFAULT_TIMEOUT, transport=transport
                ) as current_client:
                    response = await current_client.get(url)
                    response.raise_for_status()
                    df = await asyncio.to_thread(_parse_csv_text, response.text)
                    file_mod_time = None
                    last_modified_header = response.headers.get("Last-Modified")
                    if last_modified_header:
                        try:
                            file_mod_time = parsedate_to_datetime(last_modified_header)
                            if file_mod_time.tzinfo is None:
                                file_mod_time = file_mod_time.replace(tzinfo=timezone.utc)
                        except (ValueError, TypeError) as e:
                            logger.debug(
                                f"Could not parse Last-Modified header '{last_modified_header}' "
                                f"for {url}: {e}"
                            )
                    return df, file_mod_time
            except httpx.RequestError as e:
                logger.error(f"HTTP request failed for {url}: {e}")
                return None, None
    else:
        raise ValueError(
            "Either base_path or base_url must be provided to load_report."
        )
