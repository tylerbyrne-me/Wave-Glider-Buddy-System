from pathlib import Path
import pandas as pd
# import requests # disabled in favor of httpx
import httpx #async http requests
import io
import logging

# logger = logging.getLogger(__name__) # Optional: configure if needed

async def load_report(report_type: str, mission_id: str, base_path: Path = None, base_url: str = None, client: httpx.AsyncClient = None):
    reports = {
        "power": "Amps Power Summary Report.csv",
        "solar": "Amps Solar Input Port Report.csv",
        "ctd"  : "Seabird CTD Records with D.O..csv",
        "weather" : "Weather Records 2.csv",
        "waves": "GPS Waves Sensor Data.csv",
        "ais"  : "AIS Report.csv",
        "telemetry" : "Telemetry 6 Report by WGMS Datetime.csv",
        "errors": "Vehicle Error Report.csv"
    }

    if report_type not in reports:
        raise ValueError(f"Unknown report type: {report_type}")
    
    filename = reports[report_type]

    if base_path:
        file_path = Path(base_path) / mission_id / filename
         # Reading file is synchronous, keep the function async for consistency if remote is an option
        try:
            return pd.read_csv(file_path)
        except FileNotFoundError:
            # If base_url is also provided, we might want to fall back.
            # For now, if base_path is given, we assume it's the primary target.
            raise
    elif base_url:
        url = f"{str(base_url).rstrip('/')}/{mission_id}/{filename}"
        # If an external client is provided, use it directly without an additional 'async with'.
        # If no client is provided, create one for this specific operation.
        if client:
            response = await client.get(url, timeout=10) # Use the provided client
            response.raise_for_status()
            return pd.read_csv(io.StringIO(response.text))
        else:
            # This case should ideally not be hit if app.py always provides a client for remote calls.
            # However, as a fallback or for direct CLI usage:
            async with httpx.AsyncClient() as current_client: # Fallback to create a client
                response = await current_client.get(url, timeout=10)
                response.raise_for_status()
                return pd.read_csv(io.StringIO(response.text))
    else:
        raise ValueError("Either base_path or base_url must be provided to load_report.")