# c:\Users\ty225269\Documents\Python Playground\Wave Glider Project\app\config.py
import json
from typing import Any # Import Any
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    local_data_base_path: Path = Path(
        "/home/cove/Wave-Glider-Buddy-System/data"
    )
    remote_data_url: str = (
        "http://129.173.20.180:8086/"  # Base URL before specific output folders
    )
    # Store as JSON string in .env, parse here
    remote_mission_folder_map_json: str = "{}"
    # Store as JSON string in .env, parse here
    active_realtime_missions: list[str] = [
        "m209",
        "m211"
    ]
    # Example: List of mission IDs considered active
    # In a real scenario, this list might be managed dynamically or via
    # another config source.
    # These are the missions whose data in 'output_realtime_missions' will be
    # proactively cached.
    background_cache_refresh_interval_minutes: int = 60
    # Default if not in .env
    log_file_path: Path = Path(
        "C:/Users/ty225269/Documents/Python Playground/Wave Glider Buddy System/logs/app.log"
    )

    week_starts_sunday: bool = True 

    # Default relative to project root if not overridden by .env

    # JWT Settings
    # IMPORTANT: The default JWT_SECRET_KEY is INSECURE and for DEVELOPMENT ONLY.
    # ALWAYS override this in your .env file with a strong, randomly generated key for production.
    jwt_secret_key: str = "CHANGE_THIS_IN_DOT_ENV_FOR_PRODUCTION_NEVER_USE_THIS_DEFAULT"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60 * 24
    # 24 hours, adjust as needed
    forms_storage_mode: str = "local_json"  # Options: "local_json", "sqlite"
    sqlite_database_url: str = (
        "sqlite:///./data_store/app_data.sqlite" # Reverted to original default
    )
    sqlite_echo_log: bool = False  # Add this line, set to True for SQL logging

    # --- Email Settings for Timesheet Notifications ---
    # Replace these with your actual SMTP server details, preferably in a .env file.
    MAIL_USERNAME: str = "your-email@example.com"
    MAIL_PASSWORD: str = "your-email-password"
    MAIL_FROM: str = "no-reply@wgbuddy.com"
    MAIL_PORT: int = 587
    MAIL_SERVER: str = "smtp.example.com"
    MAIL_STARTTLS: bool = True
    MAIL_SSL_TLS: bool = False

    # Feature Toggles - JSON string in .env, parsed here
    feature_toggles_json: str = '{"schedule": true, "pic_management": true, "payroll": true, "admin_management": true, "station_offloads": true}'
    
    # Parsed values (not loaded directly from env)
    remote_mission_folder_map: dict[str, str] = {}
    feature_toggles: dict[str, bool] = {}

    def model_post_init(self, __context: Any) -> None:
        """Post-initialization hook to parse JSON strings."""
        self.remote_mission_folder_map = json.loads(self.remote_mission_folder_map_json)
        self.feature_toggles = json.loads(self.feature_toggles_json)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        env_prefix = "" # Ensure no prefix is added to env var names


settings = Settings()
