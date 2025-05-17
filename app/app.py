from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from mission_core import (
    load_report, get_power_status, get_ctd_status, get_weather_status,
    get_wave_status, get_ais_summary, get_recent_errors
)
from datetime import datetime, timedelta
from pathlib import Path


app = FastAPI()
templates = Jinja2Templates(directory="web/templates")

def load(report, mission):
    try:
        # Try remote URL first
        return load_report(report, mission, base_url="http://129.173.20.180:8086/output_realtime_missions")
    except Exception as e:
        print(f"[Fallback] Remote load failed for {report} ({mission}): {e}")
        # Fallback to local if remote fails
        local_base = Path(r"C:\Users\ty225269\Documents\1 - WG\2025\Spring Bloom 2025\Data")
        return load_report(report, mission, base_path=local_base)

@app.get("/", response_class=HTMLResponse)
async def home(request: Request, mission: str = "m203", hours: int = 72):

    df_power = load("power", mission)
    df_ctd = load("ctd", mission)
    df_weather = load("weather", mission)
    df_waves = load("waves", mission)
    df_ais = load("ais", mission)
    df_errors = load("errors", mission)

    return templates.TemplateResponse("index.html", {
        "request": request,
        "mission": mission,
        "power": get_power_status(df_power),
        "ctd": get_ctd_status(df_ctd),
        "weather": get_weather_status(df_weather),
        "waves": get_wave_status(df_waves),
        "ais": get_ais_summary(df_ais, max_age_hours=hours),
        "errors": get_recent_errors(df_errors, max_age_hours=hours)[:20],
    })
