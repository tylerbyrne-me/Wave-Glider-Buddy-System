from pathlib import Path
import pandas as pd
import requests
import io
import logging

# logger = logging.getLogger(__name__) # Optional: configure if needed

def load_report(report_type: str, mission_id: str, base_path: Path = None, base_url: str = None):
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
        return pd.read_csv(file_path)
    elif base_url:
        url = f"{str(base_url).rstrip('/')}/{mission_id}/{filename}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return pd.read_csv(io.StringIO(response.text))
    else:
        raise ValueError("Either base_path or base_url must be provided to load_report.")