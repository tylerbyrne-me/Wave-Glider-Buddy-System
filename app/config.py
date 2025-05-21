# c:\Users\ty225269\Documents\Python Playground\Wave Glider Project\app\config.py
from pathlib import Path
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    local_data_base_path: Path = Path(r"C:\Users\ty225269\Documents\Python Playground\Data")
    remote_data_url: str = "http://129.173.20.180:8086/" # Base URL before specific output folders
    remote_mission_folder_map: dict[str, str] = {
        "m169": "m169-SV3-1071 (C34166NS)",
        "m170": "m170-SV3-1070 (C34164NS)",
        "m171": "m171-SV3-1121 (C34167NS)",
        "m176": "m176-SV3-1070 (C34164NS)",
        "m177": "m177-SV3-1071 (C34166NS)",
        "m181": "m181-SV3-1121 (C34167NS)",
        "m182": "m182-SV3-1071 (C34166NS)",
        "m183": "m183-SV3-1070 (C34164NS)",
        "m186": "m186-SV3-1071 (C34166NS)",
        "m189": "m189-SV3-1121 (C34167NS)",
        "m193": "m193-SV3-1121 (C34167NS)",
        "m199": "m199-SV3-1070 (C34164NS)",
        "m203": "m203-SV3-1070 (C34164NS)",
        "m204": "m204-SV3-1070 (C34164NS)",
        # Add other mappings here if needed, e.g., "m204": "m204-XYZ-1234"
    }

    class Config:
        env_file = ".env" 
        env_file_encoding = 'utf-8'
        # plans to include custom parsing for maps from othre env var

settings = Settings()
