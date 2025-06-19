# c:\Users\ty225269\Documents\Python Playground\Wave Glider Project\app\config.py
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    local_data_base_path: Path = Path(
        "/home/cove/Wave-Glider-Buddy-System/data"
    )
    remote_data_url: str = (
        "http://129.173.20.180:8086/"  # Base URL before specific output folders
    )
    remote_mission_folder_map: dict[str, str] = {
        # Example: "mission_code_alias": "Actual_Folder_Name_On_Server"
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
        "m209": "m209-SV3-1071 (C34166NS)",
        # Add other mappings here if needed, e.g., "m204": "m204-XYZ-1234"
    }
    active_realtime_missions: list[str] = [
        "m203",
        "m204",
    ]
    # Example: List of mission IDs considered active
    # In a real scenario, this list might be managed dynamically or via
    # another config source.
    # These are the missions whose data in 'output_realtime_missions' will be
    # proactively cached.
    background_cache_refresh_interval_minutes: int = 60
    # Default if not in .env
    log_file_path: Path = Path(
        "app.log"
    )

    week_starts_sunday: bool = True 

    # Default relative to project root if not overridden by .env

    # JWT Settings
    jwt_secret_key: str = "plankt0n"  # CHANGE THIS!
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60 * 24
    # 24 hours, adjust as needed
    forms_storage_mode: str = "local_json"  # Options: "local_json", "sqlite"
    sqlite_database_url: str = (
        "sqlite:///./data_store/app_data.sqlite"
    )
    # Default if not in .env
    sqlite_echo_log: bool = False  # Add this line, set to True for SQL logging

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        # plans to include custom parsing for maps from othre env var


settings = Settings()
