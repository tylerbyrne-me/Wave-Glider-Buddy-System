"""
Service for interacting with Sensor Tracker API and parsing deployment data.

This service handles:
- Fetching deployment data from Sensor Tracker
- Parsing complex hierarchical deployment structures
- Converting Sensor Tracker data into local data models
"""

import logging
from datetime import datetime
from typing import Optional, Dict, List, Any, Literal
from enum import Enum

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

# Try to import sensor_tracker_client, handle gracefully if not installed
try:
    from sensor_tracker_client import sensor_tracker_client as stc
    SENSOR_TRACKER_AVAILABLE = True
except ImportError:
    logger.warning("sensor_tracker_client not available. Install with: pip install git+https://gitlab.oceantrack.org/ceotr/metadata-tracker/sensor_tracker_client.git")
    SENSOR_TRACKER_AVAILABLE = False
    stc = None


class HistoryOption(str, Enum):
    """Options for fetching history data."""
    ALL = "All"
    NOW = "Now"
    ON_DATE = "On Date"


class SensorTrackerService:
    """
    Service for interacting with Sensor Tracker API and parsing deployment data.
    """
    
    def __init__(self, skip_auth: bool = False):
        """
        Initialize the Sensor Tracker service and configure client.
        
        Args:
            skip_auth: If True, skip authentication setup (useful for GET-only operations
                       or when auth setup fails due to library compatibility issues)
        """
        if not SENSOR_TRACKER_AVAILABLE:
            raise ImportError("sensor_tracker_client is not installed")
        
        self.skip_auth = skip_auth
        self._configure_client()
    
    def _configure_client(self):
        """Configure the Sensor Tracker client with settings from config."""
        try:
            # Set host
            stc.HOST = settings.sensor_tracker_host
            
            # Configure debug mode
            stc.basic.DEBUG = settings.sensor_tracker_debug
            if settings.sensor_tracker_debug:
                stc.basic.DEBUG_HOST = settings.sensor_tracker_debug_host
            
            # Set authentication - try token first, then username/password
            # Note: Token validation may fail due to library compatibility issues,
            # so we catch errors and continue. GET operations don't require auth.
            auth_configured = False
            
            if not self.skip_auth:
                if settings.sensor_tracker_token:
                    try:
                        stc.authentication.token = settings.sensor_tracker_token
                        auth_configured = True
                        logger.info("Sensor Tracker token configured")
                    except Exception as e:
                        logger.warning(f"Failed to set token (may be library compatibility issue): {e}")
                        logger.info("Will try username/password authentication instead")
                        # Try username/password as fallback
                        if settings.sensor_tracker_username and settings.sensor_tracker_password:
                            try:
                                stc.authentication.username = settings.sensor_tracker_username
                                stc.authentication.password = settings.sensor_tracker_password
                                auth_configured = True
                                logger.info("Sensor Tracker username/password configured")
                            except Exception as e2:
                                logger.warning(f"Failed to set username/password: {e2}")
                
                elif settings.sensor_tracker_username and settings.sensor_tracker_password:
                    try:
                        stc.authentication.username = settings.sensor_tracker_username
                        stc.authentication.password = settings.sensor_tracker_password
                        auth_configured = True
                        logger.info("Sensor Tracker username/password configured")
                    except Exception as e:
                        logger.warning(f"Failed to set username/password: {e}")
            else:
                logger.info("Skipping authentication setup (skip_auth=True)")
            
            if not auth_configured and not self.skip_auth:
                logger.warning("No Sensor Tracker authentication configured. GET operations will work, but POST/PUT will fail.")
            
            logger.info(f"Sensor Tracker client configured. Host: {stc.HOST}, Debug: {stc.basic.DEBUG}, Auth: {auth_configured}")
            
        except Exception as e:
            logger.error(f"Error configuring Sensor Tracker client: {e}")
            # Don't raise - allow service to be created even if config fails
            # GET operations should still work without auth
            logger.warning("Continuing without authentication - GET operations should still work")
    
    async def fetch_deployment_by_number(
        self,
        deployment_number: int
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch a deployment by mission number (deployment_number).
        
        This is more user-friendly than using the Sensor Tracker internal ID,
        as mission numbers are what users typically track in reporting.
        
        Args:
            deployment_number: The mission/deployment number (e.g., 216)
            
        Returns:
            Dictionary containing deployment data, or None if not found
        """
        try:
            logger.info(
                f"Fetching deployment by number {deployment_number} "
                f"from Sensor Tracker (Host: {stc.HOST})"
            )
            
            # Use deployment_number as a filter
            filters = {
                "deployment_number": deployment_number,
                "depth": 1
            }
            
            try:
                response = stc.deployment.get(filters)
            except Exception as e:
                # Fallback to direct API call
                logger.debug(f"Client library failed, trying direct API: {e}")
                base_url = stc.HOST.rstrip('/')
                url = f"{base_url}/api/deployment/"
                params = {"deployment_number": deployment_number, "depth": 1}
                
                async with httpx.AsyncClient() as client:
                    http_response = await client.get(url, params=params)
                    http_response.raise_for_status()
                    data = http_response.json()
                    
                    if 'results' in data:
                        results = data['results']
                        if len(results) > 0:
                            logger.info(
                                f"Found deployment {deployment_number} "
                                f"(ID: {results[0].get('id')})"
                            )
                            return results[0]
                        else:
                            logger.warning(f"No deployment found with number {deployment_number}")
                            return None
                    else:
                        logger.warning(f"Unexpected response format for deployment_number {deployment_number}")
                        return None
            
            if response and hasattr(response, 'dict'):
                deployment_data = response.dict
                
                # Handle different response structures
                if isinstance(deployment_data, list):
                    if len(deployment_data) > 0:
                        logger.info(
                            f"Found deployment {deployment_number} "
                            f"(ID: {deployment_data[0].get('id')})"
                        )
                        return deployment_data[0]
                    else:
                        logger.warning(f"No deployment found with number {deployment_number}")
                        return None
                elif isinstance(deployment_data, dict):
                    if 'results' in deployment_data:
                        results = deployment_data['results']
                        if len(results) > 0:
                            logger.info(
                                f"Found deployment {deployment_number} "
                                f"(ID: {results[0].get('id')})"
                            )
                            return results[0]
                        else:
                            logger.warning(f"No deployment found with number {deployment_number}")
                            return None
                    else:
                        # Single deployment dict
                        logger.info(
                            f"Found deployment {deployment_number} "
                            f"(ID: {deployment_data.get('id')})"
                        )
                        return deployment_data
                else:
                    logger.warning(f"Unexpected response format for deployment_number {deployment_number}")
                    return None
            else:
                logger.warning(f"Deployment {deployment_number} not found or invalid response")
                return None
                
        except Exception as e:
            error_msg = str(e)
            # Check if it's a 404
            if "404" in error_msg or "not found" in error_msg.lower():
                logger.warning(
                    f"Deployment {deployment_number} not found (404). "
                    f"It may not exist or you may not have access."
                )
            else:
                logger.error(f"Error fetching deployment {deployment_number}: {e}")
            raise
    
    async def fetch_deployment(self, deployment_id: int) -> Optional[Dict[str, Any]]:
        """
        Fetch a single deployment from Sensor Tracker by ID.
        
        For fetching by mission number, use fetch_deployment_by_number() instead.
        
        Args:
            deployment_id: The Sensor Tracker deployment ID (can be int or string)
            
        Returns:
            Dictionary containing deployment data, or None if not found
        """
        try:
            logger.info(f"Fetching deployment {deployment_id} from Sensor Tracker (Host: {stc.HOST})")
            
            # Try as integer first
            try:
                response = stc.deployment.get(deployment_id)
            except Exception as e1:
                # If that fails, try as string
                logger.debug(f"Trying deployment ID as string: {str(deployment_id)}")
                try:
                    response = stc.deployment.get(str(deployment_id))
                except Exception as e2:
                    logger.error(f"Failed to fetch deployment {deployment_id} as int or string")
                    logger.error(f"Error as int: {e1}")
                    logger.error(f"Error as string: {e2}")
                    raise e2
            
            if response and hasattr(response, 'dict'):
                deployment_data = response.dict
                
                # Handle case where response is a list (shouldn't happen for single ID, but handle it)
                if isinstance(deployment_data, list):
                    if len(deployment_data) > 0:
                        logger.info(f"Response was a list, using first item. Found {len(deployment_data)} deployment(s)")
                        deployment_data = deployment_data[0]
                    else:
                        logger.warning(f"Deployment {deployment_id} returned empty list")
                        return None
                
                logger.info(f"Successfully fetched deployment {deployment_id}")
                return deployment_data
            else:
                logger.warning(f"Deployment {deployment_id} not found or invalid response")
                return None
                
        except Exception as e:
            error_msg = str(e)
            # Check if it's a 404
            if "404" in error_msg or "not found" in error_msg.lower():
                logger.warning(f"Deployment {deployment_id} not found (404). It may not exist or you may not have access.")
                logger.info(f"Try listing deployments by platform name to find valid deployment IDs.")
            else:
                logger.error(f"Error fetching deployment {deployment_id}: {e}")
            raise
    
    async def fetch_deployments_by_platform(self, platform_name: str) -> List[Dict[str, Any]]:
        """
        Fetch all deployments for a platform.
        
        Args:
            platform_name: The platform name/identifier
            
        Returns:
            List of deployment dictionaries
        """
        try:
            logger.info(f"Fetching deployments for platform {platform_name} (Host: {stc.HOST})")
            response = stc.deployment.get({"platform_name": platform_name})
            
            if response and hasattr(response, 'dict'):
                deployments = response.dict
                # Handle both single dict and list of dicts
                if isinstance(deployments, dict):
                    if 'results' in deployments:
                        return deployments['results']
                    return [deployments]
                elif isinstance(deployments, list):
                    return deployments
                else:
                    logger.warning(f"Unexpected response format for platform {platform_name}")
                    return []
            else:
                logger.warning(f"No deployments found for platform {platform_name}")
                return []
                
        except Exception as e:
            logger.error(f"Error fetching deployments for platform {platform_name}: {e}")
            raise
    
    async def fetch_deployment_by_mission_id(
        self,
        mission_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch a deployment by mission ID (e.g., "m216").
        
        This is a convenience wrapper that extracts the number from mission_id
        and calls fetch_deployment_by_number().
        
        Args:
            mission_id: The mission ID string (e.g., "m216", "m123")
            
        Returns:
            Dictionary containing deployment data, or None if not found
        """
        try:
            # Extract number from mission_id (e.g., "m216" -> 216)
            if mission_id.startswith("m") or mission_id.startswith("M"):
                deployment_number_str = mission_id[1:]
            else:
                deployment_number_str = mission_id
            
            try:
                deployment_number = int(deployment_number_str)
            except ValueError:
                logger.error(f"Invalid mission_id format: {mission_id}. Expected format: 'm216' or '216'")
                return None
            
            return await self.fetch_deployment_by_number(deployment_number)
            
        except Exception as e:
            logger.error(f"Error fetching deployment by mission_id {mission_id}: {e}")
            raise

    async def fetch_deployment_images(self, deployment_id: Optional[int]) -> List[Dict[str, Any]]:
        """
        Fetch images linked to a platform deployment.

        Args:
            deployment_id: Sensor Tracker deployment ID

        Returns:
            List of image dictionaries
        """
        if not deployment_id:
            return []

        filters = {"platform_deployment": deployment_id}

        # Try sensor_tracker_client first if image endpoint exists
        try:
            if hasattr(stc, "image"):
                response = stc.image.get(filters)
                if response and hasattr(response, "dict"):
                    data = response.dict
                    return self._normalize_api_results(data)
        except Exception as e:
            logger.debug(f"sensor_tracker_client image.get failed, using direct API: {e}")

        # Fallback to direct API call
        base_url = stc.HOST.rstrip("/")
        url = f"{base_url}/apiimage/"

        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=filters)
            if response.status_code == 404:
                # Some deployments may use different filter key
                response = await client.get(url, params={"deployment": deployment_id})
            response.raise_for_status()
            data = response.json()
            return self._normalize_api_results(data)

    def build_media_url(self, url_value: Optional[str]) -> Optional[str]:
        """Return an absolute URL for media if provided value is relative."""
        if not url_value:
            return None
        if url_value.startswith("http://") or url_value.startswith("https://"):
            return url_value
        base_url = stc.HOST.rstrip("/")
        if url_value.startswith("/"):
            return f"{base_url}{url_value}"
        return f"{base_url}/{url_value}"

    def _normalize_api_results(self, data: Any) -> List[Dict[str, Any]]:
        """Normalize API results into a list of dicts."""
        if not data:
            return []
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            if "results" in data and isinstance(data["results"], list):
                return data["results"]
            return [data]
        return []
    
    async def list_all_deployments(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        List all deployments (with optional limit).
        
        Args:
            limit: Maximum number of deployments to return
            
        Returns:
            List of deployment dictionaries
        """
        try:
            logger.info(f"Fetching all deployments (Host: {stc.HOST})")
            filters = {}
            if limit:
                filters["limit"] = limit
            
            if filters:
                response = stc.deployment.get(filters)
            else:
                response = stc.deployment.get()
            
            if response and hasattr(response, 'dict'):
                deployments = response.dict
                # Handle both single dict and list of dicts
                if isinstance(deployments, dict):
                    if 'results' in deployments:
                        return deployments['results']
                    return [deployments]
                elif isinstance(deployments, list):
                    return deployments
                else:
                    logger.warning("Unexpected response format for deployments list")
                    return []
            else:
                logger.warning("No deployments found")
                return []
                
        except Exception as e:
            logger.error(f"Error listing deployments: {e}")
            raise
    
    async def parse_deployment(self, deployment_data: Any) -> Dict[str, Any]:
        """
        Parse deployment data into a structured format.
        
        Args:
            deployment_data: Raw deployment data from Sensor Tracker (dict or list)
            
        Returns:
            Parsed deployment structure with all metadata organized
        """
        # Handle case where deployment_data is a list
        if isinstance(deployment_data, list):
            if len(deployment_data) == 0:
                raise ValueError("Cannot parse empty list as deployment")
            logger.info(f"Parsing first deployment from list of {len(deployment_data)}")
            deployment_data = deployment_data[0]
        
        # Ensure we have a dictionary
        if not isinstance(deployment_data, dict):
            raise ValueError(f"Expected dict or list of dicts, got {type(deployment_data)}")
        
        # Extract core identifiers
        deployment_id = (
            deployment_data.get("id") or 
            deployment_data.get("pk") or 
            deployment_data.get("deployment_id")
        )
        
        deployment_number = deployment_data.get("deployment_number")
        # Map deployment_number to mission_id (e.g., 216 -> m216)
        mission_id = f"m{deployment_number}" if deployment_number else None
        
        # Extract platform information
        platform_id = None
        if "platform" in deployment_data:
            platform_value = deployment_data["platform"]
            if isinstance(platform_value, (int, str)):
                platform_id = platform_value
            elif isinstance(platform_value, dict):
                platform_id = platform_value.get("id") or platform_value.get("pk")
        
        # Build structured parsed output
        parsed = {
            # Core identifiers
            "sensor_tracker_deployment_id": deployment_id,
            "deployment_number": deployment_number,
            "mission_id": mission_id,  # Mapped from deployment_number
            
            # Timestamps
            "start_time": deployment_data.get("start_time"),
            "end_time": deployment_data.get("end_time"),
            "created_date": deployment_data.get("created_date"),
            "modified_date": deployment_data.get("modified_date"),
            
            # Location data
            "deployment_location": {
                "latitude": deployment_data.get("deployment_latitude"),
                "longitude": deployment_data.get("deployment_longitude"),
            },
            "recovery_location": {
                "latitude": deployment_data.get("recovery_latitude"),
                "longitude": deployment_data.get("recovery_longitude"),
            },
            "depth": deployment_data.get("depth"),
            
            # Basic metadata
            "title": deployment_data.get("title"),
            "comment": deployment_data.get("comment"),
            "testing_mission": deployment_data.get("testing_mission", False),
            "private": deployment_data.get("private", False),
            
            # Platform information
            "platform_id": platform_id,
            
            # Related entity IDs (for fetching full data later)
            "related_ids": {
                "institution_id": deployment_data.get("institution"),
                "project_id": deployment_data.get("project"),
                "platform_power_type_id": deployment_data.get("platform_power_type"),
                "platform_power_id": deployment_data.get("platform_power_id"),
            },
            
            # Deployment details
            "deployment_details": {
                "deployment_cruise": deployment_data.get("deployment_cruise"),
                "recovery_cruise": deployment_data.get("recovery_cruise"),
                "deployment_personnel": deployment_data.get("deployment_personnel"),
                "recovery_personnel": deployment_data.get("recovery_personnel"),
                "wmo_id": deployment_data.get("wmo_id"),
                "until": deployment_data.get("until"),
            },
            
            # Publication and attribution
            "publication": {
                "publisher_name": deployment_data.get("publisher_name"),
                "publisher_email": deployment_data.get("publisher_email"),
                "publisher_url": deployment_data.get("publisher_url"),
                "publisher_country": deployment_data.get("publisher_country"),
                "data_repository_link": deployment_data.get("data_repository_link"),
                "metadata_link": deployment_data.get("metadata_link"),
            },
            
            "attribution": {
                "creator_name": deployment_data.get("creator_name"),
                "creator_email": deployment_data.get("creator_email"),
                "creator_url": deployment_data.get("creator_url"),
                "creator_sector": deployment_data.get("creator_sector"),
                "contributor_name": deployment_data.get("contributor_name"),
                "contributor_role": deployment_data.get("contributor_role"),
                "contributors_email": deployment_data.get("contributors_email"),
                "acknowledgement": deployment_data.get("acknowledgement"),
            },
            
            # Program and agency information
            "program_info": {
                "program": deployment_data.get("program"),
                "agencies": deployment_data.get("agencies"),
                "agencies_role": deployment_data.get("agencies_role"),
                "site": deployment_data.get("site"),
                "sea_name": deployment_data.get("sea_name"),
            },
            
            # Technical details
            "technical": {
                "transmission_system": deployment_data.get("transmission_system"),
                "positioning_system": deployment_data.get("positioning_system"),
                "references": deployment_data.get("references"),
            },
            
            # Sensor and instrument data (will be populated by separate fetches)
            "sensors": deployment_data.get("sensor_list", []),
            "instruments": [],  # Will be populated via API endpoints
            "sensor_on_instrument": [],  # Will be populated via API endpoints
            
            # Keep raw data for reference and debugging
            "raw_data": deployment_data,
        }
        
        # Extract platform data if present (try different possible structures)
        platform_data = None
        if "platform" in deployment_data:
            platform_value = deployment_data["platform"]
            if isinstance(platform_value, dict):
                platform_data = platform_value
        
        # Parse platform if we have the full data
        if platform_data:
            parsed["platform"] = await self.parse_platform(platform_data)
        
        # Note: Instruments and sensors are now fetched via API endpoints in
        # enrich_deployment_with_data_loggers() and enrich_deployment_with_platform()
        # The history parsing methods below are kept for backward compatibility
        # but are typically not used in the current workflow
        
        logger.info(
            f"Parsed deployment {deployment_id} "
            f"(deployment_number: {deployment_number}, mission_id: {mission_id}) "
            f"for platform {platform_id}"
        )
        
        return parsed
    
    async def parse_platform(self, platform_data: Any) -> Dict[str, Any]:
        """
        Parse platform data from deployment.
        
        Args:
            platform_data: Platform data from deployment (dict, int, or string)
            
        Returns:
            Parsed platform structure
        """
        # Handle case where platform_data is not a dict
        if not isinstance(platform_data, dict):
            if isinstance(platform_data, (int, str)):
                # It's just an ID reference, return minimal info
                return {
                    "platform_id": platform_data,
                    "platform_name": None,
                    "note": "Platform is an ID reference, full data not available"
                }
            else:
                logger.warning(f"Unexpected platform_data type: {type(platform_data)}")
                return {"raw": platform_data}
        
        parsed = {
            "platform_name": platform_data.get("name") or platform_data.get("platform_name"),
            "platform_type": platform_data.get("platform_type"),
            "platform_id": platform_data.get("id") or platform_data.get("pk"),
            "raw_data": platform_data,
        }
        
        # Note: Data loggers are now fetched via API endpoints in enrich_deployment_with_data_loggers()
        # This code path is kept for backward compatibility but is typically not used
        parsed["data_loggers"] = []
        parsed["data_logger_count"] = 0
        
        # Extract instrument on platform history
        if "instrument_on_platform_history" in platform_data:
            parsed["instrument_on_platform_history"] = platform_data["instrument_on_platform_history"]
        
        # Extract custom fields
        if "custom_fields" in platform_data:
            parsed["custom_fields"] = platform_data["custom_fields"]
        
        return parsed
    
    async def fetch_instrument(self, instrument_id: int) -> Optional[Dict[str, Any]]:
        """
        Fetch instrument details by ID.
        
        Args:
            instrument_id: The instrument ID
            
        Returns:
            Instrument data dictionary or None
        """
        try:
            logger.debug(f"Fetching instrument {instrument_id} from Sensor Tracker")
            response = stc.instrument.get(instrument_id)
            
            if response and hasattr(response, 'dict'):
                instrument_data = response.dict
                # Handle list response
                if isinstance(instrument_data, list) and len(instrument_data) > 0:
                    instrument_data = instrument_data[0]
                return instrument_data
            else:
                return None
                
        except Exception as e:
            logger.debug(f"Error fetching instrument {instrument_id}: {e}")
            return None
    
    async def fetch_data_loggers_on_platform(
        self,
        platform_name: str,
        attached_time: Optional[str] = None,
        depth: int = 1
    ) -> List[Dict[str, Any]]:
        """
        Fetch data loggers on a platform using the data_logger_on_platform endpoint.
        
        This is the correct way to get data logger information - it's a separate endpoint,
        not nested in the platform response.
        
        Args:
            platform_name: The platform name (string, e.g., "SV3-1070 (C34164NS)")
            attached_time: Optional deployment start time to filter (e.g., "2025-10-10")
            depth: Depth parameter for the API (default 1)
            
        Returns:
            List of data logger on platform relationships
        """
        try:
            logger.info(f"Fetching data loggers on platform '{platform_name}' (attached_time: {attached_time})")
            
            filters = {
                "platform_name": platform_name,
                "depth": depth
            }
            if attached_time:
                filters["attached_time"] = attached_time
            
            # Try using sensor_tracker_client first
            try:
                if hasattr(stc, 'data_logger_on_platform'):
                    response = stc.data_logger_on_platform.get(filters)
                    if response and hasattr(response, 'dict'):
                        data_loggers = response.dict
                        # Handle different response structures
                        if isinstance(data_loggers, list):
                            return data_loggers
                        elif isinstance(data_loggers, dict):
                            if 'results' in data_loggers:
                                return data_loggers['results']
                            return [data_loggers]
            except AttributeError:
                # Client library doesn't have this endpoint, use direct API call
                logger.debug("data_logger_on_platform not in client library, using direct API call")
                pass
            except Exception as e:
                logger.debug(f"Client library call failed, trying direct API: {e}")
            
            # Fallback to direct API call (like the example file)
            base_url = stc.HOST.rstrip('/')
            url = f"{base_url}/api/data_logger_on_platform/"
            params = {
                "platform_name": platform_name,
                "depth": depth
            }
            if attached_time:
                params["attached_time"] = attached_time
            
            async with httpx.AsyncClient() as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()
                
                if 'results' in data:
                    return data['results']
                elif isinstance(data, list):
                    return data
                else:
                    return [data] if data else []
                
        except Exception as e:
            logger.error(f"Error fetching data loggers on platform '{platform_name}': {e}")
            return []
    
    async def fetch_sensors_on_instrument(
        self,
        instrument_id: Optional[int] = None,
        instrument_identifier: Optional[str] = None,
        attached_time: Optional[str] = None,
        depth: int = 1
    ) -> List[Dict[str, Any]]:
        """
        Fetch sensors on an instrument using the sensor_on_instrument endpoint.
        
        Args:
            instrument_id: Instrument ID (preferred if available)
            instrument_identifier: Instrument identifier (e.g., "CTD", "ADCP", "vm4")
            attached_time: Optional deployment start time to filter (e.g., "2025-10-10")
            depth: Depth parameter for the API (default 1)
            
        Returns:
            List of sensor on instrument relationships
        """
        try:
            logger.debug(
                f"Fetching sensors on instrument "
                f"(ID: {instrument_id}, identifier: {instrument_identifier}, "
                f"attached_time: {attached_time})"
            )
            
            # Skip client library for this endpoint - it doesn't work well
            # Always use direct API call for sensor_on_instrument
            logger.debug("Using direct API call for sensor_on_instrument (client library not reliable for this endpoint)")
            
            # Fallback to direct API call
            # Note: The API doesn't accept instrument=<id> directly (returns 403)
            # We need to use instrument_identifier and then filter by instrument ID
            base_url = stc.HOST.rstrip('/')
            url = f"{base_url}/api/sensor_on_instrument/"
            params = {"depth": depth}
            
            # Use instrument_identifier if available (this works, but returns all instruments with that identifier)
            # If we don't have identifier but have ID, we'll need to fetch all and filter (less efficient)
            if instrument_identifier:
                params["instrument_identifier"] = instrument_identifier
            # Note: We can't use instrument=<id> directly (403 error), so we'll filter after fetching
            
            if attached_time:
                params["attached_time"] = attached_time
            
            logger.info(f"Fetching sensors from {url} with params: {params}")
            
            async with httpx.AsyncClient() as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()
                
                results = []
                if 'results' in data:
                    results = data['results']
                elif isinstance(data, list):
                    results = data
                else:
                    results = [data] if data else []
                
                logger.info(f"API returned {len(results)} sensor relationship(s)")
                
                # Debug: show instrument IDs in results
                if results:
                    inst_ids = [r.get('instrument', {}).get('id') for r in results]
                    logger.info(f"Instrument IDs in API results: {set(inst_ids)}")
                
                # Filter by instrument ID if we have one (since identifier returns all matching instruments)
                if instrument_id and results:
                    filtered_results = [
                        r for r in results
                        if r.get('instrument', {}).get('id') == instrument_id
                    ]
                    logger.info(
                        f"Filtered {len(results)} results to {len(filtered_results)} "
                        f"for instrument ID {instrument_id}"
                    )
                    if filtered_results:
                        sensor_ids = [r.get('sensor', {}).get('id') for r in filtered_results]
                        sensor_names = [r.get('sensor', {}).get('identifier') for r in filtered_results]
                        logger.info(
                            f"Filtered sensors: {sensor_names} (IDs: {sensor_ids})"
                        )
                    return filtered_results
                elif not instrument_id and instrument_identifier:
                    # If we only have identifier, return all results (they should all match)
                    logger.info(f"Returning {len(results)} results for identifier '{instrument_identifier}'")
                    return results
                
                return results
                
        except Exception as e:
            logger.error(
                f"Error fetching sensors on instrument "
                f"(ID: {instrument_id}, identifier: {instrument_identifier}): {e}"
            )
            return []
    
    async def fetch_instruments_on_data_logger(
        self,
        data_logger_identifier: str,
        attached_time: Optional[str] = None,
        depth: int = 1
    ) -> List[Dict[str, Any]]:
        """
        Fetch instruments on a data logger using the instrument_on_data_logger endpoint.
        
        Args:
            data_logger_identifier: Data logger identifier (e.g., "science computer", "flight computer")
            attached_time: Optional deployment start time to filter (e.g., "2025-10-10")
            depth: Depth parameter for the API (default 1)
            
        Returns:
            List of instrument on data logger relationships
        """
        try:
            logger.info(f"Fetching instruments on data logger '{data_logger_identifier}' (attached_time: {attached_time})")
            
            filters = {
                "data_logger_identifier": data_logger_identifier,
                "depth": depth
            }
            if attached_time:
                filters["attached_time"] = attached_time
            
            # Try using sensor_tracker_client first
            try:
                if hasattr(stc, 'instrument_on_data_logger'):
                    response = stc.instrument_on_data_logger.get(filters)
                    if response and hasattr(response, 'dict'):
                        instruments = response.dict
                        # Handle different response structures
                        if isinstance(instruments, list):
                            return instruments
                        elif isinstance(instruments, dict):
                            if 'results' in instruments:
                                return instruments['results']
                            return [instruments]
            except AttributeError:
                # Client library doesn't have this endpoint, use direct API call
                logger.debug("instrument_on_data_logger not in client library, using direct API call")
                pass
            except Exception as e:
                logger.debug(f"Client library call failed, trying direct API: {e}")
            
            # Fallback to direct API call (like the example file)
            base_url = stc.HOST.rstrip('/')
            url = f"{base_url}/api/instrument_on_data_logger/"
            params = {
                "data_logger_identifier": data_logger_identifier,
                "depth": depth
            }
            if attached_time:
                params["attached_time"] = attached_time
            
            async with httpx.AsyncClient() as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()
                
                if 'results' in data:
                    return data['results']
                elif isinstance(data, list):
                    return data
                else:
                    return [data] if data else []
                
        except Exception as e:
            logger.error(f"Error fetching instruments on data logger '{data_logger_identifier}': {e}")
            return []
    
    async def fetch_platform(self, platform_id: int, include_data_loggers: bool = True) -> Optional[Dict[str, Any]]:
        """
        Fetch platform details by ID, including data logger information.
        
        The platform API returns data logger information in the platform response.
        Data loggers are structured as 'flight' and 'science' within the platform data.
        
        Args:
            platform_id: The platform ID
            include_data_loggers: If True, ensure data logger information is included
            
        Returns:
            Platform data dictionary with data logger information, or None
        """
        try:
            logger.info(f"Fetching platform {platform_id} from Sensor Tracker (with data loggers)")
            
            # Fetch platform - the data logger info should be in the platform response
            response = stc.platform.get(platform_id)
            
            if response and hasattr(response, 'dict'):
                platform_data = response.dict
                # Handle list response
                if isinstance(platform_data, list) and len(platform_data) > 0:
                    platform_data = platform_data[0]
                
                # Check if we have data logger information
                has_data_logger = (
                    "data_logger" in platform_data or
                    "flight" in platform_data or
                    "science" in platform_data
                )
                
                if include_data_loggers and not has_data_logger:
                    logger.warning(
                        f"Platform {platform_id} response does not contain data logger information. "
                        f"Available keys: {list(platform_data.keys())[:10]}"
                    )
                elif has_data_logger:
                    logger.info(f"Platform {platform_id} contains data logger information")
                
                logger.info(f"Successfully fetched platform {platform_id}")
                return platform_data
            else:
                logger.warning(f"Platform {platform_id} not found")
                return None
                
        except Exception as e:
            logger.error(f"Error fetching platform {platform_id}: {e}")
            return None
    
    async def fetch_instruments_on_platform(
        self, 
        platform_name: str,
        attached_time: Optional[str] = None,
        depth: int = 1
    ) -> List[Dict[str, Any]]:
        """
        Fetch instruments directly on a platform (not attached to data loggers).
        
        These are instruments that are physically on the platform but don't
        save data to a data logger.
        
        Args:
            platform_name: The platform name (string, e.g., "SV3-1070 (C34164NS)")
            attached_time: Optional deployment start time to filter (e.g., "2025-10-10")
            depth: Depth parameter for the API (default 1)
            
        Returns:
            List of instrument on platform relationships
        """
        try:
            logger.info(f"Fetching instruments on platform '{platform_name}' (attached_time: {attached_time})")
            
            filters = {
                "platform_name": platform_name,
                "depth": depth
            }
            if attached_time:
                filters["attached_time"] = attached_time
            
            # Try using sensor_tracker_client first
            try:
                if hasattr(stc, 'instrument_on_platform'):
                    response = stc.instrument_on_platform.get(filters)
                    if response and hasattr(response, 'dict'):
                        instruments = response.dict
                        # Handle different response structures
                        if isinstance(instruments, list):
                            return instruments
                        elif isinstance(instruments, dict):
                            if 'results' in instruments:
                                return instruments['results']
                            return [instruments]
            except AttributeError:
                # Client library doesn't have this endpoint, use direct API call
                logger.debug("instrument_on_platform not in client library, using direct API call")
                pass
            except Exception as e:
                logger.debug(f"Client library call failed, trying direct API: {e}")
            
            # Fallback to direct API call
            base_url = stc.HOST.rstrip('/')
            url = f"{base_url}/api/instrument_on_platform/"
            params = {
                "platform_name": platform_name,
                "depth": depth
            }
            if attached_time:
                params["attached_time"] = attached_time
            
            async with httpx.AsyncClient() as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()
                
                if 'results' in data:
                    return data['results']
                elif isinstance(data, list):
                    return data
                else:
                    return [data] if data else []
                
        except Exception as e:
            logger.error(f"Error fetching instruments on platform '{platform_name}': {e}")
            return []
    
    # Note: History parsing methods removed - we now use API endpoints directly
    # (parse_instrument_on_platform_history, parse_sensor_on_instrument_history)
    # These were used for parsing nested history data from deployment responses,
    # but we now fetch instruments and sensors via dedicated API endpoints.
    
    async def enrich_deployment_with_data_loggers(
        self,
        parsed_deployment: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Enrich deployment with data loggers using the correct API endpoints.
        
        This method:
        1. Gets platform_name from the platform
        2. Uses data_logger_on_platform endpoint to get data loggers
        3. Uses instrument_on_data_logger endpoint to get instruments for each logger
        
        Args:
            parsed_deployment: Parsed deployment dictionary
            
        Returns:
            Enriched deployment with data loggers and instruments
        """
        platform_id = parsed_deployment.get("platform_id")
        if not platform_id:
            logger.debug("No platform_id to fetch data loggers")
            return parsed_deployment
        
        # Get platform name - we need the name, not just the ID
        platform_name = None
        if "platform" in parsed_deployment:
            platform_name = parsed_deployment["platform"].get("platform_name")
        else:
            # Fetch platform to get the name
            platform_data = await self.fetch_platform(platform_id, include_data_loggers=False)
            if platform_data:
                platform_name = platform_data.get("name") or platform_data.get("platform_name")
                # Store platform data if not already stored
                if "platform" not in parsed_deployment:
                    parsed_deployment["platform"] = await self.parse_platform(platform_data)
        
        if not platform_name:
            logger.warning(f"Could not determine platform name for platform_id {platform_id}")
            return parsed_deployment
        
        # Get deployment start time for filtering
        deployment_start_time = parsed_deployment.get("start_time")
        # Format time for API (just date part if it's a datetime string)
        attached_time = None
        if deployment_start_time:
            # Extract date part if it's a datetime string
            if isinstance(deployment_start_time, str):
                attached_time = deployment_start_time.split()[0] if ' ' in deployment_start_time else deployment_start_time
            else:
                attached_time = str(deployment_start_time)
        
        try:
            # Fetch data loggers on platform using the correct endpoint
            data_logger_relationships = await self.fetch_data_loggers_on_platform(
                platform_name=platform_name,
                attached_time=attached_time
            )
            
            if not data_logger_relationships:
                logger.info(f"No data loggers found for platform '{platform_name}' at time {attached_time}")
                parsed_deployment["data_loggers"] = []
                return parsed_deployment
            
            # Parse data loggers
            parsed_data_loggers = []
            all_instruments = []
            
            for dl_rel in data_logger_relationships:
                data_logger = dl_rel.get("data_logger", {})
                data_logger_id = data_logger.get("id")
                data_logger_name = data_logger.get("name", "")
                data_logger_serial = data_logger.get("serial")
                data_logger_identifier = data_logger.get("identifier", "")
                
                # Determine logger type (flight or science) based on identifier or name
                logger_type = "science"  # Default
                if "flight" in data_logger_identifier.lower() or "Flight" in data_logger_name:
                    logger_type = "flight"
                
                parsed_logger = {
                    "logger_type": logger_type,
                    "data_logger_id": data_logger_id,
                    "data_logger_name": data_logger_name,
                    "data_logger_identifier": data_logger_identifier,
                    "data_logger_serial": data_logger_serial,
                    "start_time": dl_rel.get("start_time"),
                    "end_time": dl_rel.get("end_time"),
                    "raw_relationship": dl_rel,
                }
                
                # Fetch instruments on this data logger
                # Use data_logger_identifier (e.g., "science computer", "flight computer") not the name
                if data_logger_identifier:
                    logger.info(
                        f"Fetching instruments for data logger '{data_logger_name}' "
                        f"(identifier: '{data_logger_identifier}', ID: {data_logger_id})"
                    )
                    instruments = await self.fetch_instruments_on_data_logger(
                        data_logger_identifier=data_logger_identifier,
                        attached_time=attached_time
                    )
                    
                    logger.debug(f"API returned {len(instruments)} instrument relationship(s)")
                    
                    # Parse instruments - filter by data_logger_id to ensure we get the right ones
                    parsed_instruments = []
                    for inst_rel in instruments:
                        # Check if this instrument belongs to our data logger
                        inst_dl = inst_rel.get("data_logger", {})
                        inst_dl_id = inst_dl.get("id")
                        
                        if inst_dl_id == data_logger_id:
                            instrument = inst_rel.get("instrument")
                            if instrument:  # Only add if instrument data exists
                                parsed_inst = {
                                    "instrument_id": instrument.get("id"),
                                    "instrument_identifier": instrument.get("identifier"),
                                    "instrument_short_name": instrument.get("short_name"),
                                    "instrument_serial": instrument.get("serial"),
                                    "instrument_name": instrument.get("name"),
                                    "start_time": inst_rel.get("start_time"),
                                    "end_time": inst_rel.get("end_time"),
                                    "data_logger_type": logger_type,
                                    "data_logger_id": data_logger_id,
                                    "data_logger_name": data_logger_name,
                                    "data_logger_identifier": data_logger_identifier,
                                    "raw_relationship": inst_rel,
                                }
                                parsed_instruments.append(parsed_inst)
                                all_instruments.append(parsed_inst)
                        else:
                            logger.debug(
                                f"Skipping instrument - data logger ID mismatch: "
                                f"expected {data_logger_id}, got {inst_dl_id}"
                            )
                    
                    # Fetch sensors for each instrument
                    for parsed_inst in parsed_instruments:
                        inst_id = parsed_inst.get("instrument_id")
                        inst_identifier = parsed_inst.get("instrument_identifier")
                        
                        if inst_id or inst_identifier:
                            logger.info(
                                f"Fetching sensors for instrument "
                                f"ID: {inst_id}, identifier: {inst_identifier}, "
                                f"attached_time: {attached_time}"
                            )
                            sensors = await self.fetch_sensors_on_instrument(
                                instrument_id=inst_id,
                                instrument_identifier=inst_identifier,
                                attached_time=attached_time
                            )
                            
                            logger.debug(f"Received {len(sensors)} sensor relationship(s) from API")
                            
                            # Parse sensors
                            # Note: fetch_sensors_on_instrument already filters by instrument_id,
                            # so all sensors returned should be for this instrument
                            parsed_sensors = []
                            for sensor_rel in sensors:
                                sensor_inst = sensor_rel.get("instrument", {})
                                sensor_inst_id = sensor_inst.get("id")
                                
                                # Double-check the instrument matches (should already be filtered)
                                if inst_id and sensor_inst_id != inst_id:
                                    logger.warning(
                                        f"Sensor relationship has instrument ID {sensor_inst_id}, "
                                        f"expected {inst_id}, skipping"
                                    )
                                    continue
                                
                                sensor = sensor_rel.get("sensor", {})
                                if sensor:
                                    parsed_sensor = {
                                        "sensor_id": sensor.get("id"),
                                        "sensor_identifier": sensor.get("identifier"),
                                        "sensor_short_name": sensor.get("short_name"),
                                        "sensor_long_name": sensor.get("long_name"),
                                        "sensor_serial": sensor.get("serial"),
                                        "start_time": sensor_rel.get("start_time"),
                                        "end_time": sensor_rel.get("end_time"),
                                        "instrument_id": inst_id,
                                        "instrument_identifier": inst_identifier,
                                        "data_logger_type": logger_type,
                                        "raw_relationship": sensor_rel,
                                    }
                                    parsed_sensors.append(parsed_sensor)
                                    logger.debug(
                                        f"Added sensor: {sensor.get('identifier')} "
                                        f"(ID: {sensor.get('id')}, Serial: {sensor.get('serial')})"
                                    )
                            
                            parsed_inst["sensors"] = parsed_sensors
                            parsed_inst["sensor_count"] = len(parsed_sensors)
                            if parsed_sensors:
                                logger.info(
                                    f"Found {len(parsed_sensors)} sensor(s) on instrument "
                                    f"'{inst_identifier}' (ID: {inst_id})"
                                )
                            else:
                                logger.warning(
                                    f"No sensors found for instrument "
                                    f"'{inst_identifier}' (ID: {inst_id}) "
                                    f"at attached_time {attached_time}"
                                )
                    
                    parsed_logger["instruments"] = parsed_instruments
                    parsed_logger["instrument_count"] = len(parsed_instruments)
                    logger.info(
                        f"Found {len(parsed_instruments)} instrument(s) on data logger "
                        f"'{data_logger_name}' (identifier: '{data_logger_identifier}')"
                    )
                else:
                    logger.warning(
                        f"Data logger '{data_logger_name}' (ID: {data_logger_id}) "
                        f"does not have an identifier field - cannot fetch instruments"
                    )
                    parsed_logger["instruments"] = []
                    parsed_logger["instrument_count"] = 0
                
                parsed_data_loggers.append(parsed_logger)
            
            # Fetch instruments directly on platform (not attached to data loggers)
            logger.info(f"Fetching instruments directly on platform '{platform_name}'")
            platform_instruments = await self.fetch_instruments_on_platform(
                platform_name=platform_name,
                attached_time=attached_time
            )
            
            # Parse platform instruments
            parsed_platform_instruments = []
            for inst_rel in platform_instruments:
                instrument = inst_rel.get("instrument")
                if instrument:
                    parsed_inst = {
                        "instrument_id": instrument.get("id"),
                        "instrument_identifier": instrument.get("identifier"),
                        "instrument_short_name": instrument.get("short_name"),
                        "instrument_serial": instrument.get("serial"),
                        "instrument_name": instrument.get("name"),
                        "start_time": inst_rel.get("start_time"),
                        "end_time": inst_rel.get("end_time"),
                        "data_logger_type": None,  # Not attached to a data logger
                        "data_logger_id": None,
                        "data_logger_name": None,
                        "data_logger_identifier": None,
                        "is_platform_direct": True,  # Flag to indicate direct platform attachment
                        "raw_relationship": inst_rel,
                    }
                    
                    # Fetch sensors for platform instruments too
                    inst_id = parsed_inst.get("instrument_id")
                    inst_identifier = parsed_inst.get("instrument_identifier")
                    
                    if inst_id or inst_identifier:
                        logger.debug(
                            f"Fetching sensors for platform instrument "
                            f"ID: {inst_id}, identifier: {inst_identifier}"
                        )
                        sensors = await self.fetch_sensors_on_instrument(
                            instrument_id=inst_id,
                            instrument_identifier=inst_identifier,
                            attached_time=attached_time
                        )
                        
                        # Parse sensors
                        parsed_sensors = []
                        for sensor_rel in sensors:
                            sensor_inst = sensor_rel.get("instrument", {})
                            # Match by ID if available, otherwise by identifier
                            inst_matches = False
                            if inst_id and sensor_inst.get("id") == inst_id:
                                inst_matches = True
                            elif inst_identifier and sensor_inst.get("identifier") == inst_identifier:
                                inst_matches = True
                            
                            if inst_matches:
                                sensor = sensor_rel.get("sensor", {})
                                if sensor:
                                    parsed_sensor = {
                                        "sensor_id": sensor.get("id"),
                                        "sensor_identifier": sensor.get("identifier"),
                                        "sensor_short_name": sensor.get("short_name"),
                                        "sensor_long_name": sensor.get("long_name"),
                                        "sensor_serial": sensor.get("serial"),
                                        "start_time": sensor_rel.get("start_time"),
                                        "end_time": sensor_rel.get("end_time"),
                                        "instrument_id": inst_id,
                                        "instrument_identifier": inst_identifier,
                                        "data_logger_type": None,
                                        "is_platform_direct": True,
                                        "raw_relationship": sensor_rel,
                                    }
                                    parsed_sensors.append(parsed_sensor)
                        
                        parsed_inst["sensors"] = parsed_sensors
                        parsed_inst["sensor_count"] = len(parsed_sensors)
                        if parsed_sensors:
                            logger.info(
                                f"Found {len(parsed_sensors)} sensor(s) on platform instrument "
                                f"'{inst_identifier}' (ID: {inst_id})"
                            )
                    
                    parsed_platform_instruments.append(parsed_inst)
                    all_instruments.append(parsed_inst)
            
            # Collect all sensors from all instruments
            all_sensors = []
            all_sensor_instrument_links = []
            
            for inst in all_instruments:
                sensors = inst.get("sensors", [])
                for sensor in sensors:
                    all_sensors.append(sensor)
                    # Create sensor-instrument link entry
                    link = {
                        "sensor_id": sensor.get("sensor_id"),
                        "sensor_identifier": sensor.get("sensor_identifier"),
                        "instrument_id": inst.get("instrument_id"),
                        "instrument_identifier": inst.get("instrument_identifier"),
                        "data_logger_type": inst.get("data_logger_type"),
                        "is_platform_direct": inst.get("is_platform_direct", False),
                    }
                    all_sensor_instrument_links.append(link)
            
            # Update deployment with data loggers, instruments, and sensors
            parsed_deployment["data_loggers"] = parsed_data_loggers
            parsed_deployment["instruments"] = all_instruments
            parsed_deployment["platform_instruments"] = parsed_platform_instruments  # Separate list for clarity
            parsed_deployment["sensors"] = all_sensors
            parsed_deployment["sensor_on_instrument"] = all_sensor_instrument_links
            
            total_instruments = len(all_instruments)
            data_logger_instruments = total_instruments - len(parsed_platform_instruments)
            total_sensors = len(all_sensors)
            
            logger.info(
                f"Found {len(parsed_data_loggers)} data logger(s) with "
                f"{data_logger_instruments} instrument(s), and "
                f"{len(parsed_platform_instruments)} instrument(s) directly on platform "
                f"({total_instruments} total instruments, {total_sensors} total sensors) "
                f"for platform '{platform_name}'"
            )
            
        except Exception as e:
            logger.error(f"Error enriching deployment with data loggers: {e}")
            import traceback
            logger.debug(traceback.format_exc())
        
        return parsed_deployment
    
    async def enrich_deployment_with_platform(
        self, 
        parsed_deployment: Dict[str, Any],
        fetch_instruments: bool = True
    ) -> Dict[str, Any]:
        """
        Enrich parsed deployment with full platform details.
        
        Note: For data loggers, use enrich_deployment_with_data_loggers() instead,
        which uses the correct API endpoints.
        
        Args:
            parsed_deployment: Parsed deployment dictionary
            fetch_instruments: If True, fetch instrument details for data loggers
            
        Returns:
            Enriched deployment with platform details
        """
        platform_id = parsed_deployment.get("platform_id")
        if not platform_id:
            logger.debug("No platform_id to fetch")
            return parsed_deployment
        
        try:
            platform_data = await self.fetch_platform(platform_id, include_data_loggers=False)
            if platform_data:
                parsed_platform = await self.parse_platform(platform_data)
                parsed_deployment["platform"] = parsed_platform
                logger.info(f"Enriched deployment with platform {platform_id} details")
            else:
                logger.warning(f"Could not fetch platform {platform_id} details")
        except Exception as e:
            logger.error(f"Error enriching deployment with platform data: {e}")
        
        return parsed_deployment
    
    def test_connection(self) -> bool:
        """
        Test the Sensor Tracker connection.
        
        Returns:
            True if connection is successful, False otherwise
        """
        try:
            # Try a simple GET operation that doesn't require auth
            # Limit to 1 result to avoid large responses
            response = stc.institution.get({"limit": 1})
            if response:
                logger.info("Sensor Tracker connection test successful")
                return True
            else:
                logger.warning("Sensor Tracker connection test returned no data")
                return False
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Sensor Tracker connection test failed: {e}")
            
            # Check if it's a 404 - might indicate wrong host URL
            if "404" in error_msg:
                logger.warning(f"404 error suggests the host URL might be incorrect: {stc.HOST}")
                logger.info("Try checking if the Sensor Tracker API is accessible at this URL")
            
            # Log but don't fail - might be auth issue which is OK for GET
            logger.info("Note: This might be an authentication issue. GET operations may still work.")
            return False
    
    # Note: get_deployment_info removed - use fetch_deployment() instead
    # fetch_deployment() already handles different ID formats

