from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from .core import loaders, summaries # Import from new core modules
from datetime import datetime, timedelta
import logging
from pathlib import Path
import asyncio # For concurrent loading if operations become async

# Assuming you create app/config.py as suggested
from .config import settings # Use relative import if config.py is in the same 'app' package

app = FastAPI()

# --- Robust path to templates directory ---
# Get the directory of the current file (app.py)
APP_DIR = Path(__file__).resolve().parent
# Go up one level to the project root
PROJECT_ROOT = APP_DIR.parent
# Construct the path to the templates directory
TEMPLATES_DIR = PROJECT_ROOT / "web" / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Consider making load_report in mission_core async if it involves I/O
# For this example, we'll assume load_report remains synchronous for now,
# but show how to adapt if it were async.

def load_data_source(report_type: str, mission_id: str):
    """Attempts to load data, trying remote then local sources."""
    try:
        # Try remote URL first
        logger.info(f"Attempting local load for {report_type} ({mission_id}) from {settings.local_data_base_path}")
        # Pass base_path to core.loaders.load_report
        return loaders.load_report(report_type, mission_id, base_path=settings.local_data_base_path)
    except FileNotFoundError:
        logger.warning(f"Local file for {report_type} ({mission_id}) not found at {settings.local_data_base_path}. Falling back to remote.")
    except Exception as e:
        logger.warning(f"Local load failed for {report_type} ({mission_id}): {e}. Falling back to remote.")

    # Fallback to remote if local fails or not found
    try:
        logger.info(f"Attempting remote load for {report_type} ({mission_id}) from {settings.remote_data_url}")
        # Pass base_url to core.loaders.load_report
        return loaders.load_report(report_type, mission_id, base_url=settings.remote_data_url)
    except Exception as e_remote:
        logger.error(f"Remote load also failed for {report_type} ({mission_id}): {e_remote}")
        # Return None or an empty DataFrame, or raise a custom error
        return None # Or pd.DataFrame() if preferred to avoid None checks later

@app.get("/", response_class=HTMLResponse)
async def home(request: Request, mission: str = "m203", hours: int = 72):
    # If load_report (and thus load_data_source) were async:
    # results = await asyncio.gather(
    #     load_data_source("power", mission),
    #     load_data_source("ctd", mission),
    #     load_data_source("weather", mission),
    #     load_data_source("waves", mission),
    #     load_data_source("ais", mission),
    #     load_data_source("errors", mission),
    #     return_exceptions=True # To handle individual load failures
    # )
    # df_power, df_ctd, df_weather, df_waves, df_ais, df_errors = results
    # Then check if any result is an exception or None

    # Synchronous loading (current approach)
    df_power = load_data_source("power", mission)
    df_ctd = load_data_source("ctd", mission)
    df_weather = load_data_source("weather", mission)
    df_waves = load_data_source("waves", mission)
    df_ais = load_data_source("ais", mission)
    df_errors = load_data_source("errors", mission)

    # Get status using the new standardized functions
    # The keys in these dicts now match our defined standard
    power_status = summaries.get_power_status(df_power) if df_power is not None and not df_power.empty else None
    ctd_status = summaries.get_ctd_status(df_ctd) if df_ctd is not None and not df_ctd.empty else None
    weather_status = summaries.get_weather_status(df_weather) if df_weather is not None and not df_weather.empty else None
    wave_status = summaries.get_wave_status(df_waves) if df_waves is not None and not df_waves.empty else None
    ais_summary_data = summaries.get_ais_summary(df_ais, max_age_hours=hours) if df_ais is not None else [] 
    recent_errors_list = summaries.get_recent_errors(df_errors, max_age_hours=hours)[:20] if df_errors is not None else []

    return templates.TemplateResponse("index.html", {
        "request": request,
        "mission": mission,
        "power": power_status if power_status else "Data unavailable",
        "ctd": ctd_status if ctd_status else "Data unavailable",
        "weather": weather_status if weather_status else "Data unavailable",
        "waves": wave_status if wave_status else "Data unavailable",
        "ais": ais_summary_data if ais_summary_data is not None else "Data unavailable",
        "errors": recent_errors_list if recent_errors_list is not None else [], # recent_errors can be an empty list
    })
