# c:\Users\ty225269\Documents\Python Playground\Wave Glider Project\app\config.py
from pathlib import Path
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    local_data_base_path: Path = Path(r"C:\Users\ty225269\Documents\Python Playground\Data")
    remote_data_url: str = "http://129.173.20.180:8086/output_realtime_missions/"
    remote_mission_folder_map: dict[str, str] = {
        "m203": "m203-SV3-1070 (C34164NS)",
        "m204": "m204-SV3-1070 (C34164NS)",
        # Add other mappings here if needed, e.g., "m204": "m204-XYZ-1234"
    }

    class Config:
        env_file = ".env" 
        env_file_encoding = 'utf-8'
        # plans to include custom parsing for maps from othre env var

settings = Settings()
