import requests

def get_open_meteo_forecast(lat, lon):
    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}&hourly=temperature_2m,weathercode,precipitation,windspeed_10m"
    )
    try:
        resp = requests.get(url, timeout=10) # Added timeout
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        # Consider logging this error instead of printing, or raising a custom exception
        print(f"Forecast API error: {e}") # Or logger.error(f"Forecast API error: {e}")
        return None