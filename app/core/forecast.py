import requests
import logging

logger = logging.getLogger(__name__)

def get_open_meteo_forecast(lat, lon):
    marine_url = (
        f"https://api.open-meteo.com/v1/marine?"
        f"latitude={lat}&longitude={lon}"
        "&hourly=wave_height,wave_direction,wave_period,windspeed_10m,winddirection_10m,ocean_current_velocity,ocean_current_direction,weathercode,temperature_2m,precipitation"
        "&timezone=GMT" # keep gmt/utc
    )
    general_forecast_url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}&hourly=temperature_2m,weathercode,precipitation,windspeed_10m,winddirection_10m"
        "&timezone=GMT"
    )
    try:
        logger.info(f"Attempting to fetch marine forecast from: {marine_url}")
        resp = requests.get(marine_url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        data['forecast_type'] = 'marine' # Add type for frontend if needed
        return data
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            logger.warning(f"Marine forecast API returned 404 for lat={lat}, lon={lon}. Falling back to general forecast.")
            try:
                logger.info(f"Attempting to fetch general forecast from: {general_forecast_url}")
                resp_general = requests.get(general_forecast_url, timeout=10)
                resp_general.raise_for_status()
                data = resp_general.json()
                data['forecast_type'] = 'general' # Add type for frontend
                return data
            except Exception as e_general:
                logger.error(f"General forecast API also failed: {e_general}")
                return None
        else:
            logger.error(f"Marine forecast API HTTP error: {e}")
            return None
    except Exception as e:
        logger.error(f"Generic forecast API error: {e}")
        return None