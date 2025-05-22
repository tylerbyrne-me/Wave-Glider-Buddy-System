import httpx # Changed from requests to httpx
import logging # type: ignore # Keep type: ignore if needed for your linter
from typing import Optional, Dict, Any # For type hinting
from datetime import datetime, timezone # Added for fetch timestamp

logger = logging.getLogger(__name__)

MARINE_API_BASE_URL = "https://api.open-meteo.com/v1/marine"
GENERAL_API_BASE_URL = "https://api.open-meteo.com/v1/forecast"

MARINE_API_HOURLY_PARAMS = "wave_height,wave_direction,wave_period,windspeed_10m,winddirection_10m,ocean_current_velocity,ocean_current_direction,weathercode,temperature_2m,precipitation"
GENERAL_API_HOURLY_PARAMS = "temperature_2m,weathercode,precipitation,windspeed_10m,winddirection_10m"

DEFAULT_TIMEOUT = 15.0  # seconds (Revert to original or keep reasonable)
RETRY_COUNT = 3         # Number of retries
BACKOFF_FACTOR = 0.5    # Backoff factor for retries (delay = backoff_factor * (2 ** (retry_attempt - 1)))

async def _fetch_forecast_data(api_url: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Helper function to fetch forecast data with retries."""
    try:
        # Simpler retry configuration: httpx.HTTPTransport handles retries based on the integer value.
        # Use AsyncClient for consistency with FastAPI/asyncio
        transport = httpx.HTTPTransport(
            retries=RETRY_COUNT 
        )
        # Use async with for AsyncClient
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT, transport=transport) as client:
            logger.debug(f"Fetching data from {api_url} with params {params} using {RETRY_COUNT} retries and backoff {BACKOFF_FACTOR}")
            response = await client.get(api_url, params=params) # Make the get call asynchronous
            logger.debug(f"Response status from {api_url}: {response.status_code}")
            response.raise_for_status()  # Raise an exception for 4XX or 5XX status codes
            return response.json()
    except httpx.HTTPStatusError as e:
        # Specific handling for HTTP status errors (like 404) is done by the caller
        logger.warning(f"HTTPStatusError when fetching {api_url}: {e.response.status_code} - {e}")
        raise # Re-raise to be caught by the caller
    except httpx.RequestError as e: # Catches network errors, SSL errors, timeouts etc.
        logger.error(f"RequestError of type '{type(e).__name__}' when fetching {api_url}: {e}") # Log specific exception type
        return None
    except Exception as e: # Catch-all for other unexpected errors
        logger.error(f"Unexpected error when fetching {api_url}: {e}")
        return None

async def get_open_meteo_forecast(lat: float, lon: float, force_marine: bool = False) -> Optional[Dict[str, Any]]:
    marine_url = (
        f"{MARINE_API_BASE_URL}" # Base URL, params will be passed separately
    )
    general_forecast_url = (
        f"{GENERAL_API_BASE_URL}" # Base URL, params will be passed separately
    )
    
    # --- For Debugging Marine API: Start with minimal parameters ---
    # Original:
    # marine_hourly_params_to_request = MARINE_API_HOURLY_PARAMS
    # Revert to full parameters since simplified didn't fix 404
    marine_hourly_params_to_request = MARINE_API_HOURLY_PARAMS
    # You can gradually add more parameters back from MARINE_API_HOURLY_PARAMS to see which one might cause an issue.
    # --- End Debugging Section ---

    marine_params = {"latitude": lat, "longitude": lon, "hourly": marine_hourly_params_to_request, "timezone": "GMT"}
    general_params = {"latitude": lat, "longitude": lon, "hourly": GENERAL_API_HOURLY_PARAMS, "timezone": "GMT"}

    try:
        logger.info(f"Attempting to fetch marine forecast from: {marine_url}")
        data = await _fetch_forecast_data(MARINE_API_BASE_URL, marine_params) # Await the async helper
        if data is None: # If _fetch_forecast_data returned None due to RequestError or other non-HTTPStatusError
            raise Exception("Marine forecast fetch failed with non-HTTP error, trying general.")
        # Add metadata
        data['latitude_used'] = lat
        data['longitude_used'] = lon
        data['fetched_at_utc'] = datetime.now(timezone.utc).isoformat()
        data['forecast_type'] = 'marine' # Add type for frontend if needed

        return data
    except httpx.HTTPStatusError as e: # Catch HTTPStatusError specifically from _fetch_forecast_data
        if e.response.status_code == 404 and not force_marine: # Check if it's a 404 AND we are not forcing marine
            logger.warning(f"Marine forecast API returned 404 for lat={lat}, lon={lon}. Falling back to general forecast.")
            try:
                logger.info(f"Attempting to fetch general forecast from: {general_forecast_url}")
                data = await _fetch_forecast_data(GENERAL_API_BASE_URL, general_params)
                if data is None: # If general forecast also fails with non-HTTP error
                    logger.error("General forecast API also failed after marine 404.")
                    return None
                # Add metadata
                data['latitude_used'] = lat
                data['longitude_used'] = lon
                data['fetched_at_utc'] = datetime.now(timezone.utc).isoformat()
                data['forecast_type'] = 'general' # Add type for frontend
                return data
            except httpx.HTTPStatusError as e_general_http: # General forecast also had an HTTP error
                logger.error(f"General forecast API also failed with HTTP error: {e_general_http.response.status_code} - {e_general_http}")
                return None
            except Exception as e_general_other: # General forecast had another error
                logger.error(f"General forecast API also failed with other error: {e_general_other}")
                return None
        elif force_marine:
            logger.error(f"Marine forecast API HTTP error (force_marine=True, no fallback): {e.response.status_code} - {e}")
            return None # Do not fallback if force_marine is true
        else: # Other HTTP errors for marine and not forcing marine (though _fetch_forecast_data might return None before this for non-404s)
            logger.error(f"Marine forecast API HTTP error (not 404): {e.response.status_code} - {e}")
            return None
    except Exception as e: # Catches other errors, like the re-raised one from _fetch_forecast_data if marine fetch failed early, or if force_marine is true and marine fetch failed with non-HTTP error
        logger.error(f"Generic forecast API error (possibly after marine fetch failed before HTTPStatusError): {e}")
        return None