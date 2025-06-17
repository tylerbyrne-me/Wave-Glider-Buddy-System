import io
import logging
from pathlib import Path

# import requests # disabled in favor of httpx
import httpx  # async http requests
import pandas as pd

logger = logging.getLogger(
    __name__
)  # Keep this for actual operational logging
DEFAULT_TIMEOUT = 10.0  # seconds
RETRY_COUNT = 2  # Number of retries for loaders


async def load_report(
    report_type: str,
    mission_id: str,
    base_path: Path = None,
    base_url: str = None,
    client: httpx.AsyncClient = None,
):
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
        "wg_vm4": "Vemco VM4 Daily Local Health.csv",  # New WG-VM4 sensor
    }

    if report_type not in reports:
        raise ValueError(f"Unknown report type: {report_type}")

    filename = reports[report_type]

    if base_path:
        file_path = Path(base_path) / mission_id / filename
        # Reading file is synchronous, keep the function async for consistency if remote is an option
        try:
            return pd.read_csv(file_path)
        except FileNotFoundError as e:
            # If base_url is also provided, we might want to fall back. For
            # now, if base_path is given, we assume it's the primary target.
            # Log this as it's an important operational detail if a file is
            # expected but not found.
            logger.info(
                f"File not found at local path: {file_path}. Error: {e}"
            )
            raise  # Re-raise the exception so the caller (app.py) can handle it
    elif base_url:
        url = f"{str(base_url).rstrip('/')}/{mission_id}/{filename}"
        # If an external client is provided, use it directly without an
        # additional 'async with'. If no client is provided, create one for
        # this specific operation.
        if client:
            # Assuming the client passed in might have its own
            # transport/retry config
            response = await client.get(url, timeout=DEFAULT_TIMEOUT)
            response.raise_for_status()
            return pd.read_csv(io.StringIO(response.text))
        else:
            # This case should ideally not be hit if app.py always provides a
            # client for remote calls.
            # However, as a fallback or for direct CLI usage:
            transport = httpx.HTTPTransport(retries=RETRY_COUNT)
            async with httpx.AsyncClient(
                timeout=DEFAULT_TIMEOUT, transport=transport
            ) as current_client:  # Fallback to create a client
                response = await current_client.get(url)
                response.raise_for_status()
                return pd.read_csv(io.StringIO(response.text))
    else:
        raise ValueError(
            "Either base_path or base_url must be provided to load_report." # noqa
        )
