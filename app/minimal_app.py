import asyncio
import json
import logging
import time
from datetime import datetime, timedelta, timezone  # Added timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple  # Added Any

import httpx
import numpy as np
import pandas as pd  # type: ignore
from apscheduler.schedulers.asyncio import \
    AsyncIOScheduler  # Add this import back
from fastapi import (Depends, FastAPI, HTTPException, Request,  # Added status
                     status)
# from fastapi.templating import Jinja2Templates # Keep complex imports commented for now
from fastapi.security import OAuth2PasswordRequestForm  # type: ignore
from fastapi.staticfiles import StaticFiles  # Add this import back
from fastapi.templating import Jinja2Templates  # Add this import back
from sqlmodel import SQLModel, inspect, select  # type: ignore

from . import auth_utils
from .auth_utils import (get_current_active_user, get_current_admin_user,
                         get_current_pilot_user, get_optional_current_user)
from .config import settings
from .core import models  # type: ignore
from .core import (forecast, loaders, processors, summaries,  # type: ignore
                   utils)
from .core.security import (create_access_token, get_password_hash,
                            verify_password)
from .db import SQLModelSession, get_db_session, sqlite_engine
# from .station_sub_app import station_api # Comment out sub-app import
from .routers import station_metadata_router  # Import the new APIRouter

print("MINIMAL_APP: Initializing FastAPI app instance.")
app = FastAPI()

# --- Path definitions (from app.py) ---
APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent
# Construct the path to the templates directory (from app.py)
TEMPLATES_DIR = PROJECT_ROOT / "web" / "templates"
print(f"MINIMAL_APP: TEMPLATES_DIR defined: {TEMPLATES_DIR}")

# --- Jinja2Templates instantiation (from app.py) ---
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
print("MINIMAL_APP: Jinja2Templates instantiated.")

DATA_STORE_DIR = PROJECT_ROOT / "data_store"
LOCAL_FORMS_DB_FILE = DATA_STORE_DIR / "submitted_forms.json"
print(f"MINIMAL_APP: Paths defined. PROJECT_ROOT: {PROJECT_ROOT}")
# --- StaticFiles mounting (from app.py) ---
STATIC_DIR = PROJECT_ROOT / "web" / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
print(f"MINIMAL_APP: StaticFiles mounted from {STATIC_DIR}.")

# --- Logger (from app.py) ---
logger = logging.getLogger(__name__ + "_minimal")  # Use a distinct logger name
print(f"MINIMAL_APP: Logger '{logger.name}' initialized.")

# --- Global variable initializations (from app.py) ---
data_cache: Dict[Tuple, Tuple[pd.DataFrame, str, datetime]] = {}
CACHE_EXPIRY_MINUTES = settings.background_cache_refresh_interval_minutes
mission_forms_db: Dict[Tuple[str, str, str], models.MissionFormDataResponse] = {}
print(
    f"MINIMAL_APP: Global variables (data_cache, CACHE_EXPIRY_MINUTES, mission_forms_db) initialized. CACHE_EXPIRY_MINUTES: {CACHE_EXPIRY_MINUTES}"
)

# --- APScheduler instantiation (from app.py) ---
scheduler = AsyncIOScheduler()
print("MINIMAL_APP: APScheduler instantiated.")

# --- Include the APIRouter ---
print(
    f"MINIMAL_APP: About to include station_metadata_router. Type: {type(station_metadata_router.router)}"
)
app.include_router(
    station_metadata_router.router, prefix="/api", tags=["Station Metadata"]
)  # Include with /api prefix
print("MINIMAL_APP: station_metadata_router included with prefix /api")

print("MINIMAL_APP: Defining /api/minimal_test_route")


@app.get("/api/minimal_test_route")
async def minimal_test_route_endpoint():
    return {"message": "Minimal test route is working!"}


print("MINIMAL_APP: /api/minimal_test_route defined.")
