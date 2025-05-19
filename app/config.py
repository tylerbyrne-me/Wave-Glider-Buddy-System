# c:\Users\ty225269\Documents\Python Playground\Wave Glider Project\app\config.py
from pathlib import Path
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    local_data_base_path: Path = Path(r"C:\Users\ty225269\Documents\Python Playground\Data")
    remote_data_url: str = "http://129.173.20.180:8086/output_realtime_missions/"
    # Add any other settings your app might need

    class Config:
        env_file = "env_file.txt" # Point to your env_file.txt
        env_file_encoding = 'utf-8'

settings = Settings()
