# c:\Users\ty225269\Documents\Python Playground\Wave Glider Project\app\config.py
import json
from typing import Any, Optional  # Import Any and Optional
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
    active_realtime_missions: list[str] = []
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
    # SECURITY: All email settings MUST be configured in .env file
    # These defaults are placeholders and will cause email functionality to fail if not overridden
    MAIL_USERNAME: Optional[str] = None
    MAIL_PASSWORD: Optional[str] = None
    MAIL_FROM: Optional[str] = None
    MAIL_PORT: int = 587
    MAIL_SERVER: Optional[str] = None
    MAIL_STARTTLS: bool = True
    MAIL_SSL_TLS: bool = False

    # Feature Toggles - JSON string in .env, parsed here
    feature_toggles_json: str = '{"schedule": true, "pic_management": true, "payroll": true, "admin_management": true, "station_offloads": true, "local_data_loading": false}'
    
    # --- Sensor Tracker Settings ---
    # SECURITY: Credentials MUST be configured in .env file
    sensor_tracker_host: str = "https://prod.ceotr.ca/sensor_tracker"
    sensor_tracker_token: Optional[str] = None  # Must be set in .env
    sensor_tracker_username: Optional[str] = None  # Must be set in .env
    sensor_tracker_password: Optional[str] = None  # Must be set in .env
    sensor_tracker_debug: bool = False
    sensor_tracker_debug_host: str = "http://127.0.0.1:8000/"
    
    # --- Knowledge Base Settings ---
    knowledge_base_max_upload_size_mb: int = 50  # Maximum file upload size in MB
    
    # --- OpenWeatherMap API Settings ---
    # SECURITY: API key MUST be configured in .env file
    openweathermap_api_key: Optional[str] = None  # Must be set in .env
    
    # --- Default User Accounts (Seed Users) ---
    # SECURITY: Passwords MUST be set in .env file - no defaults for security
    # Usernames can have defaults for convenience, but passwords must be configured
    default_admin_username: str = "adminuser"
    default_admin_password: Optional[str] = None  # MUST be set in .env
    default_admin_email: str = "admin@example.com"
    default_pilot_username: str = "pilotuser"
    default_pilot_password: Optional[str] = None  # MUST be set in .env
    default_pilot_email: str = "pilot@example.com"
    default_pilot_rt_username: str = "pilot_rt_only"
    default_pilot_rt_password: Optional[str] = None  # MUST be set in .env
    default_pilot_rt_email: str = "pilot_rt@example.com"
    default_lri_pilot_username: str = "LRI_PILOT"
    default_lri_pilot_password: Optional[str] = None  # Password doesn't matter (user is disabled), but set in .env for consistency
    default_lri_pilot_email: str = "lri@example.com"

    # --- Mission Media Settings ---
    mission_media_root_path: str = "web/static/mission_media"
    mission_media_max_image_size_mb: int = 10
    mission_media_max_video_size_mb: int = 50
    mission_media_max_files_per_upload: int = 10
    
    # --- Chatbot Vector Search Settings ---
    vector_search_enabled: bool = True  # Enable vector search (requires chromadb and sentence-transformers)
    vector_similarity_threshold: float = 0.35  # Minimum similarity for matches (0.0-1.0, 0.35 works well)
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"  # Embedding model name
    vector_chunking_enabled: bool = True  # Enable chunking for document vectorization
    vector_chunking_min_chars: int = 2000  # Chunk documents longer than this
    
    # --- LLM Settings (Ollama) ---
    llm_enabled: bool = True  # Enable LLM for response synthesis
    llm_host: str = "http://localhost:11434"  # Ollama server URL
    llm_model: str = "mistral:7b"  # Model to use (mistral:7b recommended for quality + context)
    llm_temperature: float = 0.3  # Lower temperature for more factual/consistent answers
    llm_max_tokens: int = 512  # Max response length (increased for detailed answers)
    llm_timeout: int = 180  # Timeout in seconds (increased for larger context)
    llm_fallback_to_search: bool = True  # Fall back to search results if LLM unavailable
    llm_max_context_chars: int = 6000  # Max context to send to LLM (Mistral supports ~8k tokens)
    
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
        extra = "ignore"  # Ignore extra environment variables (like CLI_ADMIN_* for CLI tools)


settings = Settings()
