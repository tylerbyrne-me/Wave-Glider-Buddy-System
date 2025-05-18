# c:\Users\ty225269\Documents\Python Playground\Wave Glider Project\app\config.py
from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

class Settings(BaseSettings):
    remote_data_url: str = "http://129.173.20.180:8086/output_realtime_missions"
    local_data_base_path: Path = Path(r"C:\Users\ty225269\Documents\1 - WG\2025\Spring Bloom 2025\Data")
    # Add other configurations as needed, e.g., log level

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding='utf-8', extra="ignore")

settings = Settings()