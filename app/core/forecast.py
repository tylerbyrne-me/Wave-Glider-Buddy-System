import logging  # type: ignore # Keep type: ignore if needed for your linter
from datetime import datetime, timezone  # Added for fetch timestamp
from typing import Any, Dict, Optional  # For type hinting

import httpx  # Changed from requests to httpx

logger = logging.getLogger(__name__)

MARINE_API_BASE_URL = (
    "https://marine-api.open-meteo.com/v1/marine"  # Specialized marine data
)
GENERAL_API_BASE_URL = "https://api.open-meteo.com/v1/forecast"

# Parameters for the Marine API - focused on marine data
MARINE_API_HOURLY_PARAMS = (
    "wave_height,wave_direction,wave_period,"
    "ocean_current_velocity,ocean_current_direction"
)

# Parameters for the General Forecast API
GENERAL_API_HOURLY_PARAMS = (
    "temperature_2m,weathercode,precipitation,windspeed_10m,winddirection_10m"
)

DEFAULT_TIMEOUT = 15.0  # seconds (Revert to original or keep reasonable)
RETRY_COUNT = 3  # Number of retries
BACKOFF_FACTOR = 0.5  # Backoff factor for retries (delay = backoff_factor * (2 ** (retry_attempt - 1)))
# BACKOFF_FACTOR = 0.5
# delay = backoff_factor * (2 ** (retry_attempt - 1))

async def _fetch_forecast_data(
    api_url: str, params: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Helper function to fetch forecast data with retries."""
    try:
        transport_config = (
            httpx.AsyncHTTPTransport(  # Use AsyncHTTPTransport for AsyncClient
                retries=RETRY_COUNT
            )
        )
        async with httpx.AsyncClient(
            transport=transport_config, timeout=DEFAULT_TIMEOUT
        ) as client:
            logger.debug(
                f"Fetching data from {api_url} with params {params} using "
                f"{RETRY_COUNT} retries and backoff {BACKOFF_FACTOR}"
            )
            response = await client.get(api_url, params=params)
            logger.debug(f"Response status from {api_url}: {response.status_code}")
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        # Specific handling for HTTP status errors (like 404) is done by the caller
        logger.warning(
            f"HTTPStatusError when fetching {api_url}: {e.response.status_code} - {e}"
        )
        raise  # Re-raise to be caught by the caller
    except httpx.RequestError as e:  # Catches network errors, SSL errors, timeouts etc.
        logger.error(
            f"HTTPStatusError when fetching {api_url}: "
            f"{e.response.status_code} - {e}"
        )  # Log specific exception type
        return None
    except Exception as e:  # Catch-all for other unexpected errors
        logger.error(f"Unexpected error when fetching {api_url}: {e}")
        return None


async def get_general_meteo_forecast(
    lat: float, lon: float
) -> Optional[Dict[str, Any]]:
    """
    Fetches general weather forecast data (temperature, weathercode,
    precipitation, wind).
    """
    final_data: Optional[Dict[str, Any]] = None
    base_api_params = {"latitude": lat, "longitude": lon, "timezone": "GMT"}

    logger.info(
        f"Attempting to fetch general forecast from: {GENERAL_API_BASE_URL} "
        f"for lat={lat}, lon={lon}."
    )
    try:
        general_api_params = {**base_api_params, "hourly": GENERAL_API_HOURLY_PARAMS}
        final_data = await _fetch_forecast_data(
            GENERAL_API_BASE_URL, general_api_params
        )
        if final_data:
            final_data["forecast_type"] = "general"  # Mark the type
            final_data["latitude_used"] = lat
            final_data["longitude_used"] = lon
            final_data["fetched_at_utc"] = datetime.now(timezone.utc).isoformat()
            logger.info("Successfully fetched general forecast data.")
        else:  # General forecast also returned None (non-HTTP error)
            logger.error("General forecast fetch also failed (non-HTTP error).")
            return None
    except httpx.HTTPStatusError as e_gen_http: # noqa
        logger.error(
            f"General forecast API failed with HTTP error: "
            f"{e_gen_http.response.status_code} - {e_gen_http}"
        )
        return None
    except Exception as e_gen_other: # noqa
        logger.error(f"General forecast API failed with other error: {e_gen_other}")
        return final_data

    return final_data


async def get_marine_meteo_forecast(lat: float, lon: float) -> Optional[Dict[str, Any]]:
    """
    Fetches marine-specific forecast data (waves, currents).
    """
    final_data: Optional[Dict[str, Any]] = None
    base_api_params = {"latitude": lat, "longitude": lon, "timezone": "GMT"}

    logger.info(
        f"Attempting to fetch marine forecast from: {MARINE_API_BASE_URL} "
        f"for lat={lat}, lon={lon}"
    )
    try:
        marine_api_params = {**base_api_params, "hourly": MARINE_API_HOURLY_PARAMS}
        final_data = await _fetch_forecast_data(MARINE_API_BASE_URL, marine_api_params)
        if final_data:
            final_data["forecast_type"] = "marine"  # Mark the type
            final_data["latitude_used"] = lat
            final_data["longitude_used"] = lon
            final_data["fetched_at_utc"] = datetime.now(timezone.utc).isoformat()
            logger.info("Successfully fetched marine forecast data.")
        else:
            logger.error("Marine forecast fetch failed (non-HTTP error).")
            return None
    except httpx.HTTPStatusError as e_marine_http: # noqa
        logger.error(
            f"Marine forecast API failed with HTTP error: "
            f"{e_marine_http.response.status_code} - {e_marine_http}"
        )
        return None
    except Exception as e_marine_other: # noqa
        logger.error(f"Marine forecast API failed with other error: {e_marine_other}")
        return None

    return final_data
