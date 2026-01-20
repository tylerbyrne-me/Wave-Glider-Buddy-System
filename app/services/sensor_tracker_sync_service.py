"""
Sensor Tracker Sync Service

Handles syncing Sensor Tracker metadata to the local database.
This service fetches deployment data, parses it, and stores it in the database
for use in mission reports.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List
from uuid import uuid4

import httpx
from sqlmodel import Session as SQLModelSession, select
import pandas as pd

from ..core import models
from ..core import utils
from ..core.db import get_db_session
from ..config import settings
from .sensor_tracker_service import SensorTrackerService, SENSOR_TRACKER_AVAILABLE

logger = logging.getLogger(__name__)


class SensorTrackerSyncService:
    """
    Service for syncing Sensor Tracker metadata to the database.
    """
    
    def __init__(
        self,
        token_override: Optional[str] = None,
        username_override: Optional[str] = None,
        password_override: Optional[str] = None,
    ):
        """Initialize the sync service."""
        if not SENSOR_TRACKER_AVAILABLE:
            logger.warning("Sensor Tracker service not available. Sync operations will fail.")
        self.sensor_tracker_service = (
            SensorTrackerService(
                token_override=token_override,
                username_override=username_override,
                password_override=password_override,
            )
            if SENSOR_TRACKER_AVAILABLE
            else None
        )
    
    async def get_or_sync_mission(
        self,
        mission_id: str,
        force_refresh: bool = False,
        session: Optional[SQLModelSession] = None
    ) -> Optional[models.SensorTrackerDeployment]:
        """
        Get Sensor Tracker deployment data for a mission, syncing if needed.
        
        Args:
            mission_id: Mission ID (e.g., "1070-m216" or "m216")
            force_refresh: If True, force a refresh even if data exists
            session: Database session (will create one if not provided)
            
        Returns:
            SensorTrackerDeployment object if found/synced, None otherwise
        """
        if not SENSOR_TRACKER_AVAILABLE or not self.sensor_tracker_service:
            logger.warning("Sensor Tracker service not available. Cannot sync.")
            return None
        
        # Extract mission base from "1070-m216" format to get "m216" or "216"
        mission_base = mission_id.split('-')[-1] if '-' in mission_id else mission_id
        
        # Use provided session or create a new one
        if session is None:
            from ..core.db import get_db_session
            session_gen = get_db_session()
            session = next(session_gen)
            should_close = True
        else:
            should_close = False
        
        try:
            # Check if deployment already exists in database
            existing_deployment = session.exec(
                select(models.SensorTrackerDeployment).where(
                    models.SensorTrackerDeployment.mission_id == mission_base
                )
            ).first()
            
            # If exists and not forcing refresh, return existing
            if existing_deployment and not force_refresh:
                logger.info(f"Using cached Sensor Tracker data for mission '{mission_id}' (base: '{mission_base}')")
                return existing_deployment
            
            # Fetch deployment data from Sensor Tracker
            logger.info(f"Fetching Sensor Tracker data for mission '{mission_id}' (base: '{mission_base}')")
            deployment_data = None
            
            if mission_base.lower().startswith('m'):
                deployment_data = await self.sensor_tracker_service.fetch_deployment_by_mission_id(mission_base)
            else:
                try:
                    mission_number = int(mission_base)
                    deployment_data = await self.sensor_tracker_service.fetch_deployment_by_number(mission_number)
                except ValueError:
                    logger.warning(f"Could not parse mission base '{mission_base}' as number")
            
            if not deployment_data:
                logger.warning(f"No Sensor Tracker deployment found for mission '{mission_id}' (base: '{mission_base}')")
                # Update existing record with error status if it exists
                if existing_deployment:
                    existing_deployment.sync_status = "error"
                    existing_deployment.sync_error = "Deployment not found in Sensor Tracker"
                    existing_deployment.last_synced_at = datetime.now(timezone.utc)
                    session.add(existing_deployment)
                    session.commit()
                return None
            
            # Parse the deployment data
            parsed_deployment = await self.sensor_tracker_service.parse_deployment(deployment_data)
            
            if not parsed_deployment:
                logger.error(f"Failed to parse deployment data for mission '{mission_id}'")
                if existing_deployment:
                    existing_deployment.sync_status = "error"
                    existing_deployment.sync_error = "Failed to parse deployment data"
                    existing_deployment.last_synced_at = datetime.now(timezone.utc)
                    session.add(existing_deployment)
                    session.commit()
                return None
            
            # Enrich deployment with data loggers and instruments
            # Note: enrich_deployment_with_data_loggers also fetches platform-direct instruments
            logger.info(f"Enriching deployment data with data loggers and instruments for mission '{mission_id}'")
            parsed_deployment = await self.sensor_tracker_service.enrich_deployment_with_data_loggers(parsed_deployment)
            
            logger.info(
                f"Enriched deployment: {len(parsed_deployment.get('data_loggers', []))} data loggers, "
                f"{len(parsed_deployment.get('platform_instruments', []))} platform instruments, "
                f"{len(parsed_deployment.get('instruments', []))} total instruments"
            )
            
            # Extract deployment number and mission ID from parsed data
            deployment_number = parsed_deployment.get("deployment_number")
            parsed_mission_id = parsed_deployment.get("mission_id")  # e.g., "m216"
            
            if not parsed_mission_id:
                logger.error(f"Parsed deployment missing mission_id for '{mission_id}'")
                return None
            
            # Create or update deployment record
            if existing_deployment:
                deployment = existing_deployment
                logger.info(f"Updating existing Sensor Tracker deployment record for mission '{mission_id}'")
            else:
                deployment = models.SensorTrackerDeployment(mission_id=parsed_mission_id)
                logger.info(f"Creating new Sensor Tracker deployment record for mission '{mission_id}'")
            
            # Update deployment fields
            deployment.sensor_tracker_deployment_id = parsed_deployment.get("sensor_tracker_deployment_id")
            deployment.deployment_number = deployment_number
            deployment.title = parsed_deployment.get("title")
            
            # Convert datetime strings to datetime objects
            start_time_raw = parsed_deployment.get("start_time")
            if start_time_raw:
                if isinstance(start_time_raw, str):
                    deployment.start_time = pd.to_datetime(start_time_raw, utc=True).to_pydatetime()
                elif isinstance(start_time_raw, datetime):
                    deployment.start_time = start_time_raw
                else:
                    deployment.start_time = None
            else:
                deployment.start_time = None
            
            end_time_raw = parsed_deployment.get("end_time")
            if end_time_raw:
                if isinstance(end_time_raw, str):
                    deployment.end_time = pd.to_datetime(end_time_raw, utc=True).to_pydatetime()
                elif isinstance(end_time_raw, datetime):
                    deployment.end_time = end_time_raw
                else:
                    deployment.end_time = None
            else:
                deployment.end_time = None
            
            deployment.deployment_location_lat = parsed_deployment.get("deployment_location", {}).get("lat")
            deployment.deployment_location_lon = parsed_deployment.get("deployment_location", {}).get("lon")
            deployment.recovery_location_lat = parsed_deployment.get("recovery_location", {}).get("lat")
            deployment.recovery_location_lon = parsed_deployment.get("recovery_location", {}).get("lon")
            deployment.depth = parsed_deployment.get("depth")
            
            # Platform info
            platform = parsed_deployment.get("platform", {})
            if isinstance(platform, dict):
                deployment.platform_id = platform.get("platform_id")
                deployment.platform_name = platform.get("platform_name")
                deployment.platform_type = platform.get("platform_type")
            
            # Priority metadata fields (Phase 1A)
            # Agencies and agencies_role from program_info
            program_info = parsed_deployment.get("program_info", {})
            if isinstance(program_info, dict):
                deployment.agencies = program_info.get("agencies")  # Comma-separated, order preserved
                deployment.agencies_role = program_info.get("agencies_role")
                deployment.program = program_info.get("program")
                deployment.site = program_info.get("site")
                deployment.sea_name = program_info.get("sea_name")
            
            # Deployment comment (from top-level comment field)
            deployment.deployment_comment = parsed_deployment.get("comment")
            
            # Acknowledgement from attribution
            attribution = parsed_deployment.get("attribution", {})
            if isinstance(attribution, dict):
                deployment.acknowledgement = attribution.get("acknowledgement")
                deployment.creator_name = attribution.get("creator_name")
                deployment.creator_email = attribution.get("creator_email")
                deployment.creator_url = attribution.get("creator_url")
                deployment.creator_sector = attribution.get("creator_sector")
                deployment.contributor_name = attribution.get("contributor_name")
                deployment.contributor_role = attribution.get("contributor_role")
                deployment.contributors_email = attribution.get("contributors_email")
            
            # Additional metadata fields (Phase 1B)
            # Deployment details
            deployment_details = parsed_deployment.get("deployment_details", {})
            if isinstance(deployment_details, dict):
                deployment.deployment_cruise = deployment_details.get("deployment_cruise")
                deployment.recovery_cruise = deployment_details.get("recovery_cruise")
                deployment.deployment_personnel = deployment_details.get("deployment_personnel")
                deployment.recovery_personnel = deployment_details.get("recovery_personnel")
                deployment.wmo_id = deployment_details.get("wmo_id")
            
            # Publication and data access
            publication = parsed_deployment.get("publication", {})
            if isinstance(publication, dict):
                deployment.data_repository_link = publication.get("data_repository_link")
                deployment.metadata_link = publication.get("metadata_link")
                deployment.publisher_name = publication.get("publisher_name")
                deployment.publisher_email = publication.get("publisher_email")
                deployment.publisher_url = publication.get("publisher_url")
                deployment.publisher_country = publication.get("publisher_country")
            
            # Technical details
            technical = parsed_deployment.get("technical", {})
            if isinstance(technical, dict):
                deployment.transmission_system = technical.get("transmission_system")
                deployment.positioning_system = technical.get("positioning_system")
                deployment.references = technical.get("references")
            
            # Store full metadata
            deployment.full_metadata = parsed_deployment
            
            # Update sync status
            deployment.last_synced_at = datetime.now(timezone.utc)
            deployment.sync_status = "synced"
            deployment.sync_error = None
            
            session.add(deployment)
            session.commit()
            session.refresh(deployment)
            
            # Sync instruments and sensors (using mission_id, not deployment_id)
            await self._sync_instruments_and_sensors(deployment.mission_id, parsed_deployment, session)

            # Sync deployment images from Sensor Tracker
            await self._sync_deployment_images(deployment, session)
            
            logger.info(f"Successfully synced Sensor Tracker data for mission '{mission_id}' (deployment ID: {deployment.sensor_tracker_deployment_id})")
            return deployment
            
        except Exception as e:
            logger.error(f"Error syncing Sensor Tracker data for mission '{mission_id}': {e}", exc_info=True)
            # Rollback the session to clear any pending transactions
            try:
                session.rollback()
            except Exception as rollback_error:
                logger.warning(f"Error during session rollback: {rollback_error}")
            
            # Update existing record with error if it exists
            if existing_deployment:
                try:
                    existing_deployment.sync_status = "error"
                    existing_deployment.sync_error = str(e)[:500]  # Limit error message length
                    existing_deployment.last_synced_at = datetime.now(timezone.utc)
                    session.add(existing_deployment)
                    session.commit()
                except Exception as update_error:
                    logger.error(f"Failed to update error status: {update_error}")
                    session.rollback()
            return None
        finally:
            if should_close:
                session.close()
    
    async def _sync_instruments_and_sensors(
        self,
        mission_id: str,
        parsed_deployment: Dict[str, Any],
        session: SQLModelSession
    ):
        """
        Sync instruments and sensors for a mission.
        
        Args:
            mission_id: Mission ID (e.g., "m216")
            parsed_deployment: The parsed deployment data dictionary
            session: Database session
        """
        try:
            # Delete existing instruments and sensors for this mission
            existing_instruments = session.exec(
                select(models.MissionInstrument).where(
                    models.MissionInstrument.mission_id == mission_id
                )
            ).all()
            
            instrument_count = len(existing_instruments)
            sensor_count = 0
            
            for instrument in existing_instruments:
                # Delete associated sensors
                existing_sensors = session.exec(
                    select(models.MissionSensor).where(
                        models.MissionSensor.instrument_id == instrument.id
                    )
                ).all()
                sensor_count += len(existing_sensors)
                for sensor in existing_sensors:
                    session.delete(sensor)
                session.delete(instrument)
            
            # Get data loggers from parsed deployment
            data_loggers = parsed_deployment.get("data_loggers", [])
            
            # Process instruments from data loggers
            for logger_data in data_loggers:
                # Note: parsed logger uses "logger_type", not "data_logger_type"
                logger_type = logger_data.get("logger_type") or logger_data.get("data_logger_type", "")
                if logger_type:
                    logger_type = logger_type.lower()  # "flight" or "science"
                logger_id = logger_data.get("data_logger_id")
                logger_name = logger_data.get("data_logger_name")
                logger_identifier = logger_data.get("data_logger_identifier")
                
                instruments = logger_data.get("instruments", [])
                for inst_data in instruments:
                    await self._create_instrument_record(
                        mission_id, inst_data, session,
                        data_logger_type=logger_type,
                        data_logger_id=logger_id,
                        data_logger_name=logger_name,
                        data_logger_identifier=logger_identifier,
                        is_platform_direct=False
                    )
            
            # Process instruments directly on platform (not via data logger)
            platform_instruments = parsed_deployment.get("platform_instruments", [])
            for inst_data in platform_instruments:
                await self._create_instrument_record(
                    mission_id, inst_data, session,
                    is_platform_direct=True
                )
            
            session.commit()
            
            # Count newly created instruments
            new_instruments = session.exec(
                select(models.MissionInstrument).where(
                    models.MissionInstrument.mission_id == mission_id
                )
            ).all()
            new_sensors_count = 0
            for inst in new_instruments:
                sensors = session.exec(
                    select(models.MissionSensor).where(
                        models.MissionSensor.instrument_id == inst.id
                    )
                ).all()
                new_sensors_count += len(sensors)
            
            logger.info(
                f"Synced instruments and sensors for mission '{mission_id}': "
                f"removed {instrument_count} old instruments ({sensor_count} sensors), "
                f"created {len(new_instruments)} new instruments ({new_sensors_count} sensors)"
            )
            
        except Exception as e:
            logger.error(f"Error syncing instruments and sensors for mission '{mission_id}': {e}", exc_info=True)
            session.rollback()
            # Don't raise - allow deployment to be saved even if instruments fail
            # This way we at least have deployment metadata
            logger.warning(f"Instrument sync failed for mission '{mission_id}', but deployment was saved")
    
    async def _create_instrument_record(
        self,
        mission_id: str,
        inst_data: Dict[str, Any],
        session: SQLModelSession,
        data_logger_type: Optional[str] = None,
        data_logger_id: Optional[int] = None,
        data_logger_name: Optional[str] = None,
        data_logger_identifier: Optional[str] = None,
        is_platform_direct: bool = False
    ):
        """
        Create an instrument record and its associated sensors.
        
        Args:
            mission_id: Mission ID (e.g., "m216")
            inst_data: Instrument data dictionary
            session: Database session
            data_logger_type: Type of data logger ("flight" or "science")
            data_logger_id: Data logger ID
            data_logger_name: Data logger name
            data_logger_identifier: Data logger identifier
            is_platform_direct: True if instrument is directly on platform
        """
        instrument = models.MissionInstrument(
            mission_id=mission_id,
            sensor_tracker_instrument_id=inst_data.get("instrument_id"),
            instrument_identifier=inst_data.get("instrument_identifier") or "unknown",
            instrument_short_name=inst_data.get("instrument_short_name"),
            instrument_serial=inst_data.get("instrument_serial"),
            instrument_name=inst_data.get("instrument_name"),
            start_time=self._parse_datetime(inst_data.get("start_time")),
            end_time=self._parse_datetime(inst_data.get("end_time")),
            data_logger_type=data_logger_type,
            data_logger_id=data_logger_id,
            data_logger_name=data_logger_name,
            data_logger_identifier=data_logger_identifier,
            is_platform_direct=is_platform_direct
        )
        
        session.add(instrument)
        session.flush()  # Flush to get instrument.id
        
        # Create sensor records
        sensors = inst_data.get("sensors", [])
        for sensor_data in sensors:
            sensor = models.MissionSensor(
                mission_id=mission_id,
                instrument_id=instrument.id,
                sensor_tracker_sensor_id=sensor_data.get("sensor_id"),
                sensor_identifier=sensor_data.get("sensor_identifier") or "unknown",
                sensor_short_name=sensor_data.get("sensor_short_name"),
                sensor_serial=sensor_data.get("sensor_serial"),
                start_time=self._parse_datetime(sensor_data.get("start_time")),
                end_time=self._parse_datetime(sensor_data.get("end_time"))
            )
            session.add(sensor)
        
        return instrument
    
    def _parse_datetime(self, value: Any) -> Optional[datetime]:
        """
        Parse a datetime value from various formats to a datetime object.
        
        Args:
            value: String, datetime, or None
            
        Returns:
            datetime object or None
        """
        if value is None:
            return None
        
        if isinstance(value, datetime):
            return value
        
        if isinstance(value, str):
            try:
                return pd.to_datetime(value, utc=True).to_pydatetime()
            except (ValueError, TypeError):
                logger.warning(f"Could not parse datetime string: {value}")
                return None
        
        return None

    def _get_project_root(self) -> Path:
        return Path(__file__).resolve().parent.parent.parent

    def _get_mission_media_root(self) -> Path:
        configured_root = Path(settings.mission_media_root_path)
        if configured_root.is_absolute():
            return configured_root
        return self._get_project_root() / configured_root

    def _build_media_storage_path(self, mission_id: str, filename: str) -> Path:
        media_root = self._get_mission_media_root()
        media_dir_name = utils.mission_storage_dir_name(mission_id, "media")
        target_dir = media_root / media_dir_name / "sensortracker"
        target_dir.mkdir(parents=True, exist_ok=True)
        return target_dir / filename

    def _derive_extension(self, url_value: str, content_type: Optional[str]) -> str:
        if content_type and content_type.startswith("image/"):
            clean_type = content_type.split(";", 1)[0]
            return f".{clean_type.split('/')[-1]}"
        url_path = url_value.split("?")[0]
        if "." in url_path:
            return f".{url_path.rsplit('.', 1)[-1]}"
        return ".jpg"

    async def _sync_deployment_images(
        self,
        deployment: models.SensorTrackerDeployment,
        session: SQLModelSession
    ) -> None:
        """
        Sync Sensor Tracker deployment images to local mission media storage.
        """
        if not self.sensor_tracker_service:
            return

        deployment_id = deployment.sensor_tracker_deployment_id
        if not deployment_id:
            logger.warning(f"No Sensor Tracker deployment ID for mission '{deployment.mission_id}', skipping image sync")
            return

        images = await self.sensor_tracker_service.fetch_deployment_images(deployment_id)
        if not images:
            logger.info(f"No Sensor Tracker images found for deployment {deployment_id}")
            return

        for image in images:
            image_id = image.get("id") or image.get("pk")
            source_url = (
                image.get("picture")
                or image.get("image")
                or image.get("file")
                or image.get("url")
            )
            source_url = self.sensor_tracker_service.build_media_url(source_url)
            if not source_url:
                logger.debug(f"Skipping image without URL (ID: {image_id})")
                continue

            existing = session.exec(
                select(models.MissionMedia).where(
                    models.MissionMedia.mission_id == deployment.mission_id,
                    models.MissionMedia.source_system == "sensortracker",
                    models.MissionMedia.source_url == source_url
                )
            ).first()
            if existing:
                continue

            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(source_url)
                    response.raise_for_status()
                    content = response.content
                    content_type = response.headers.get("Content-Type", "image/jpeg")

                max_size = settings.mission_media_max_image_size_mb * 1024 * 1024
                if len(content) > max_size:
                    logger.warning(
                        f"Skipping Sensor Tracker image (too large) for mission '{deployment.mission_id}': {source_url}"
                    )
                    continue

                extension = self._derive_extension(source_url, content_type)
                safe_filename = f"{uuid4().hex}_{int(datetime.now(timezone.utc).timestamp())}{extension}"
                file_path = self._build_media_storage_path(deployment.mission_id, safe_filename)

                with file_path.open("wb") as buffer:
                    buffer.write(content)

                project_root = self._get_project_root()
                try:
                    relative_path = file_path.relative_to(project_root)
                    stored_path = str(relative_path).replace("\\", "/")
                except ValueError:
                    stored_path = str(file_path)

                media = models.MissionMedia(
                    mission_id=deployment.mission_id,
                    media_type="photo",
                    file_path=stored_path,
                    file_name=safe_filename,
                    file_size=len(content),
                    mime_type=content_type,
                    caption=image.get("title"),
                    operation_type=None,
                    uploaded_by_username="sensortracker_sync",
                    approval_status="approved",
                    approved_by_username="sensortracker_sync",
                    approved_at_utc=datetime.now(timezone.utc),
                    source_system="sensortracker",
                    source_url=source_url,
                    source_external_id=str(image_id) if image_id is not None else None,
                )
                session.add(media)
                session.commit()
                session.refresh(media)
            except Exception as e:
                logger.error(f"Failed to sync Sensor Tracker image {source_url}: {e}", exc_info=True)
                session.rollback()

