"""
WG-VM4 Station Service

This module handles automatic station matching and offload log creation
from WG-VM4 info data.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple
import math

import pandas as pd
from sqlmodel import select
from .db import SQLModelSession
from . import models
from .feature_toggles import is_feature_enabled
from .wg_vm4_payload_parser import WgVm4PayloadParser, OffloadEvent, OffloadEventType

logger = logging.getLogger(__name__)

MAX_PARSER_NOTES_LENGTH = 32000
PRIMARY_MATCH_WINDOW_MINUTES = 5
FALLBACK_MATCH_WINDOW_MINUTES = 10
BLANK_PLACEHOLDERS = {"---", "n/a", "na", "none", "null", "unknown"}


def _truncate_parser_notes(notes: Optional[str], max_length: int = MAX_PARSER_NOTES_LENGTH) -> Optional[str]:
    """Keep parser notes bounded to prevent oversized DB writes."""
    if not notes:
        return notes
    if len(notes) <= max_length:
        return notes
    suffix = "\n[TRUNCATED] parser notes exceeded storage limit."
    keep = max_length - len(suffix)
    if keep <= 0:
        return suffix[:max_length]
    return f"{notes[-keep:]}{suffix}"


def _is_blank_value(value: Any) -> bool:
    """Treat empty values and UI placeholders as parser-fill eligible."""
    if value is None:
        return True
    if isinstance(value, str):
        normalized = value.strip().lower()
        return normalized == "" or normalized in BLANK_PLACEHOLDERS
    return False


class WgVm4StationService:
    """Service for matching WG-VM4 events to stations and creating offload logs"""
    
    def __init__(self, session: SQLModelSession):
        self.session = session
        self.parser = WgVm4PayloadParser()
        self._station_cache = {}  # Cache for station lookups
    
    def extract_serial_number(self, vr4_identifier: str) -> Optional[str]:
        """
        Extract serial number from VR4-XXXXXX format
        
        Args:
            vr4_identifier: String like "VR4-250545" or "250545"
            
        Returns:
            Serial number string or None if not found
        """
        if not vr4_identifier:
            return None
            
        # Handle both "VR4-250545" and "250545" formats
        if vr4_identifier.startswith("VR4-"):
            return vr4_identifier[4:]  # Remove "VR4-" prefix
        elif vr4_identifier.isdigit():
            return vr4_identifier
        else:
            logger.warning(f"Unexpected VR4 identifier format: {vr4_identifier}")
            return None
    
    def find_station_by_serial(self, serial_number: str) -> Optional[models.StationMetadata]:
        """
        Find station by serial number with caching
        
        Args:
            serial_number: Station serial number
            
        Returns:
            StationMetadata object or None if not found
        """
        if not serial_number:
            return None
            
        # Check cache first
        if serial_number in self._station_cache:
            return self._station_cache[serial_number]
        
        # Query database
        statement = select(models.StationMetadata).where(
            models.StationMetadata.serial_number == serial_number
        )
        station = self.session.exec(statement).first()
        
        # Cache result (even if None)
        self._station_cache[serial_number] = station
        
        if station:
            logger.debug(f"Found station {station.station_id} for serial {serial_number}")
        else:
            logger.warning(f"No station found for serial number: {serial_number}")
            
        return station
    
    def round_distance_to_50m(self, distance_m: float) -> int:
        """
        Round distance to nearest 50m increment (50, 100, 150, 200, etc.)
        
        Args:
            distance_m: Distance in meters
            
        Returns:
            Rounded distance in meters
        """
        return int(round(distance_m / 50) * 50)
    
    def calculate_distance_from_coordinates(
        self, 
        lat1: float, 
        lon1: float, 
        lat2: float, 
        lon2: float
    ) -> float:
        """
        Calculate distance between two GPS coordinates using Haversine formula
        
        Args:
            lat1, lon1: First coordinate
            lat2, lon2: Second coordinate
            
        Returns:
            Distance in meters
        """
        # Convert to radians
        lat1_rad = math.radians(lat1)
        lon1_rad = math.radians(lon1)
        lat2_rad = math.radians(lat2)
        lon2_rad = math.radians(lon2)
        
        # Haversine formula
        dlat = lat2_rad - lat1_rad
        dlon = lon2_rad - lon1_rad
        
        a = (math.sin(dlat/2)**2 + 
             math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon/2)**2)
        c = 2 * math.asin(math.sqrt(a))
        
        # Earth's radius in meters
        earth_radius = 6371000
        return earth_radius * c
    
    def process_wg_vm4_events(
        self, 
        events: List[OffloadEvent], 
        mission_id: str,
        field_season_year: Optional[int] = None
    ) -> Dict[str, int]:
        """
        Process WG-VM4 events and create offload logs
        
        Args:
            events: List of parsed OffloadEvent objects
            mission_id: Mission identifier
            field_season_year: Optional field season year to assign to offload logs (overrides active season)
            
        Returns:
            Dictionary with processing statistics
        """
        stats = {
            'events_processed': 0,
            'stations_matched': 0,
            'offload_logs_created': 0,
            'stations_updated': 0,
            'errors': 0
        }
        
        # Group events by serial number
        events_by_serial = {}
        for event in events:
            if event.serial_number:
                if event.serial_number not in events_by_serial:
                    events_by_serial[event.serial_number] = []
                events_by_serial[event.serial_number].append(event)
        
        has_pending_writes = False
        # Process each station's events
        for serial_number, station_events in events_by_serial.items():
            try:
                stats['events_processed'] += len(station_events)
                
                # Find station
                station = self.find_station_by_serial(serial_number)
                if not station:
                    logger.warning(f"No station found for serial {serial_number}, skipping events")
                    continue
                
                stats['stations_matched'] += 1
                
                # Process offload sessions
                sessions = self.parser.get_offload_sessions(station_events)
                logger.debug(f"Found {len(sessions)} sessions for station {station.station_id}")
                
                for i, session in enumerate(sessions):
                    logger.debug(f"Session {i+1} for station {station.station_id}: status={session['status']}, serial={session['serial_number']}")
                    if self._create_offload_log_from_session(session, station, mission_id, field_season_year):
                        stats['offload_logs_created'] += 1
                        stats['stations_updated'] += 1
                        has_pending_writes = True
                        
            except Exception as e:
                logger.error(f"Error processing events for serial {serial_number}: {e}")
                stats['errors'] += 1
                continue
        
        if has_pending_writes:
            self.session.commit()
        return stats
    
    def _group_events_by_serial(self, events: List[OffloadEvent]) -> Dict[str, List[OffloadEvent]]:
        """Group events by serial number for debugging"""
        events_by_serial = {}
        for event in events:
            if event.serial_number:
                if event.serial_number not in events_by_serial:
                    events_by_serial[event.serial_number] = []
                events_by_serial[event.serial_number].append(event)
        return events_by_serial
    
    def _create_offload_log_from_session(
        self, 
        session: Dict, 
        station: models.StationMetadata, 
        mission_id: str,
        override_field_season_year: Optional[int] = None
    ) -> bool:
        """
        Create an offload log from a parsed session
        
        Args:
            session: Parsed offload session dictionary
            station: Station metadata object
            mission_id: Mission identifier
            override_field_season_year: Optional field season year to override active season default
            
        Returns:
            True if log was created successfully
        """
        try:
            # Only create logs for completed sessions
            if session['status'] not in ['completed', 'offload_failed']:
                logger.debug(f"Skipping incomplete session for station {station.station_id} (status: {session['status']})")
                return False
            
            # Extract session data
            start_time = session['start_time']
            end_time = session.get('end_time', start_time)
            # Check if we already have a log for this time period
            existing_log = self._find_existing_log(station.station_id, start_time, end_time)
            
            # Calculate distance if we have GPS data
            distance_m = None
            if 'start_latitude' in session and 'start_longitude' in session:
                if station.deployment_latitude and station.deployment_longitude:
                    distance_m = self.calculate_distance_from_coordinates(
                        session['start_latitude'],
                        session['start_longitude'],
                        station.deployment_latitude,
                        station.deployment_longitude
                    )
                    distance_m = self.round_distance_to_50m(distance_m)
            
            # Determine if offload was successful
            was_offloaded = session['status'] == 'completed'
            
            # field_season_year: override, else active FieldSeason (registry no longer carries season)
            if override_field_season_year is not None:
                field_season_year = override_field_season_year
            else:
                from ..services.station_season_service import StationSeasonService
                active_season = StationSeasonService.get_active_season(self.session)
                field_season_year = active_season.year if active_season else None
            
            parser_notes = (
                f"Auto-generated from WG-VM4 data. VRL: "
                f"{session.get('vrl_file_name', 'N/A')}"
            )
            parser_notes = _truncate_parser_notes(parser_notes)

            # Create offload log
            offload_log_data = {
                'station_id': station.station_id,
                'arrival_date': start_time,
                'departure_date': end_time,
                'distance_command_sent_m': distance_m,
                'time_first_command_sent_utc': start_time,
                'offload_start_time_utc': start_time,
                'offload_end_time_utc': end_time,
                'was_offloaded': was_offloaded,
                'vrl_file_name': session.get('vrl_file_name'),
                'offload_notes_file_size': f"Auto-generated from WG-VM4 data. VRL: {session.get('vrl_file_name', 'N/A')}",
                'parser_notes': parser_notes,
                'created_by_source': 'parser',
                'updated_by_source': 'parser',
                'updated_at_utc': datetime.now(timezone.utc),
                'parser_run_id': f"{mission_id}:{start_time.isoformat()}",
                'parser_session_ref': f"{mission_id}:{session.get('serial_number')}:{start_time.isoformat()}",
                'logged_by_username': 'wg_vm4_auto',
                'field_season_year': field_season_year
            }

            if existing_log:
                # User-wins merge: parser fills only missing fields.
                parser_fields = [
                    "arrival_date",
                    "departure_date",
                    "distance_command_sent_m",
                    "time_first_command_sent_utc",
                    "offload_start_time_utc",
                    "offload_end_time_utc",
                    "was_offloaded",
                    "vrl_file_name",
                    "offload_notes_file_size",
                    "parser_notes",
                    "parser_run_id",
                    "parser_session_ref",
                ]
                conflict_messages: List[str] = []
                backfilled_fields: List[str] = []
                for field_name in parser_fields:
                    existing_value = getattr(existing_log, field_name)
                    parser_value = offload_log_data[field_name]
                    if _is_blank_value(existing_value):
                        setattr(existing_log, field_name, parser_value)
                        backfilled_fields.append(field_name)
                        continue
                    if _is_blank_value(parser_value):
                        continue
                    if str(existing_value) != str(parser_value):
                        conflict_messages.append(
                            f"{field_name}: existing='{existing_value}' parser='{parser_value}'"
                        )
                # Never overwrite user_notes.
                if conflict_messages:
                    conflict_text = " | ".join(conflict_messages)
                    conflict_signature = f"[CONFLICT] {conflict_text}"
                    note_prefix = f"[CONFLICT {datetime.now(timezone.utc).isoformat()}]"
                    merged_note = f"{note_prefix} {conflict_text}"
                    existing_notes = existing_log.parser_notes or ""
                    if conflict_signature not in existing_notes:
                        if existing_notes:
                            existing_log.parser_notes = (
                                f"{existing_notes}\n{merged_note}"
                            )
                        else:
                            existing_log.parser_notes = merged_note
                        existing_log.parser_notes = _truncate_parser_notes(existing_log.parser_notes)
                    self._notify_conflict_via_admin_announcement(
                        station_id=station.station_id,
                        mission_id=mission_id,
                        parser_session_ref=offload_log_data["parser_session_ref"],
                        conflict_text=conflict_text,
                    )
                if backfilled_fields:
                    existing_notes = existing_log.parser_notes or ""
                    note = (
                        f"[BACKFILLED {datetime.now(timezone.utc).isoformat()}] "
                        f"fields={', '.join(sorted(set(backfilled_fields)))}"
                    )
                    existing_log.parser_notes = _truncate_parser_notes(
                        f"{existing_notes}\n{note}".strip()
                    )
                existing_log.updated_by_source = "parser"
                existing_log.updated_at_utc = datetime.now(timezone.utc)
                offload_log = existing_log
            else:
                offload_log = models.OffloadLog.model_validate(offload_log_data)
                self.session.add(offload_log)
            
            # Update station metadata
            station.last_offload_timestamp_utc = end_time
            station.was_last_offload_successful = was_offloaded
            station.last_offload_by_glider = mission_id
            self.session.add(station)
            
            logger.info(
                f"Upserted offload log for station {station.station_id} from WG-VM4 data"
            )
            return True
            
        except Exception as e:
            logger.error(f"Error creating offload log for station {station.station_id}: {e}")
            self.session.rollback()
            return False

    def _notify_conflict_via_admin_announcement(
        self,
        station_id: str,
        mission_id: str,
        parser_session_ref: Optional[str],
        conflict_text: str,
    ) -> None:
        """Create an admin-targeted system announcement for parser/user conflicts."""
        try:
            ref = parser_session_ref or f"{mission_id}:{station_id}"
            existing_stmt = select(models.Announcement).where(
                models.Announcement.is_active == True,
                models.Announcement.target_roles == "admin",
                models.Announcement.announcement_type == "system",
                models.Announcement.content.ilike(f"%{ref}%"),
            )
            if self.session.exec(existing_stmt).first():
                return
            content = (
                f"Conflict Queue Alert [{ref}] station={station_id} mission={mission_id}. "
                f"Parser detected field mismatch and preserved user values. "
                f"Details: {conflict_text}"
            )
            ann = models.Announcement(
                content=content,
                created_by_username="wg_vm4_auto",
                announcement_type="system",
                target_roles="admin",
            )
            self.session.add(ann)
        except Exception as exc:
            logger.warning(f"Unable to create conflict announcement: {exc}")
    
    def _find_existing_log(
        self,
        station_id: str,
        start_time: datetime,
        end_time: Optional[datetime] = None,
    ) -> Optional[models.OffloadLog]:
        """
        Check if an offload log already exists for this station and time period
        
        Args:
            station_id: Station identifier
            start_time: Session start time
            
        Returns:
            Existing OffloadLog or None
        """
        start_window = start_time - timedelta(minutes=PRIMARY_MATCH_WINDOW_MINUTES)
        end_window = start_time + timedelta(minutes=PRIMARY_MATCH_WINDOW_MINUTES)
        statement = select(models.OffloadLog).where(
            models.OffloadLog.station_id == station_id,
            models.OffloadLog.created_by_source == "user",
            models.OffloadLog.offload_start_time_utc >= start_window,
            models.OffloadLog.offload_start_time_utc <= end_window,
        ).order_by(models.OffloadLog.updated_at_utc.desc(), models.OffloadLog.log_timestamp_utc.desc())
        log = self.session.exec(statement).first()
        if log:
            return log

        # Fallback: broaden timestamp matching for user-entered logs that omitted offload_start_time_utc.
        fallback_window_start = start_time - timedelta(minutes=FALLBACK_MATCH_WINDOW_MINUTES)
        fallback_window_end = start_time + timedelta(minutes=FALLBACK_MATCH_WINDOW_MINUTES)
        fallback_columns = [
            models.OffloadLog.arrival_date,
            models.OffloadLog.time_first_command_sent_utc,
            models.OffloadLog.offload_end_time_utc,
        ]
        for fallback_column in fallback_columns:
            fallback_stmt = select(models.OffloadLog).where(
                models.OffloadLog.station_id == station_id,
                models.OffloadLog.created_by_source == "user",
                fallback_column.isnot(None),
                fallback_column >= fallback_window_start,
                fallback_column <= fallback_window_end,
            ).order_by(models.OffloadLog.updated_at_utc.desc(), models.OffloadLog.log_timestamp_utc.desc())
            log = self.session.exec(fallback_stmt).first()
            if log:
                return log

        # Last resort: allow parser-generated records for idempotent re-runs.
        parser_stmt = select(models.OffloadLog).where(
            models.OffloadLog.station_id == station_id,
            models.OffloadLog.offload_start_time_utc >= start_window,
            models.OffloadLog.offload_start_time_utc <= end_window,
        ).order_by(models.OffloadLog.updated_at_utc.desc(), models.OffloadLog.log_timestamp_utc.desc())
        return self.session.exec(parser_stmt).first()
    
    def process_wg_vm4_dataframe(
        self, 
        df, 
        mission_id: str,
        field_season_year: Optional[int] = None
    ) -> Dict[str, int]:
        """
        Process a WG-VM4 info DataFrame and create offload logs
        
        Args:
            df: WG-VM4 info DataFrame
            mission_id: Mission identifier
            field_season_year: Optional field season year to assign to offload logs (overrides active season)
            
        Returns:
            Processing statistics
        """
        try:
            # Parse events from dataframe
            events = self.parser.parse_dataframe(df)
            logger.info(f"Parsed {len(events)} WG-VM4 events")
            
            # Debug: Show event type distribution
            event_types = {}
            for event in events:
                event_type = event.event_type.value
                event_types[event_type] = event_types.get(event_type, 0) + 1
            logger.info(f"Event type distribution: {event_types}")
            
            # Debug: Show serial numbers for offload complete events
            offload_complete_serials = [event.serial_number for event in events 
                                     if event.event_type.value == 'offload_complete' and event.serial_number]
            logger.info(f"Offload complete events with serial numbers: {len(offload_complete_serials)} - {offload_complete_serials[:10]}")
            
            # Process events and create logs
            stats = self.process_wg_vm4_events(events, mission_id, field_season_year)
            
            logger.info(f"WG-VM4 processing complete: {stats}")
            return stats
            
        except Exception as e:
            logger.error(f"Error processing WG-VM4 dataframe: {e}")
            return {'events_processed': 0, 'stations_matched': 0, 'offload_logs_created': 0, 'stations_updated': 0, 'errors': 1}


# Convenience function for easy integration
def process_wg_vm4_info_for_mission(
    session: SQLModelSession, 
    df, 
    mission_id: str,
    field_season_year: Optional[int] = None
) -> Dict[str, int]:
    """
    Process WG-VM4 info data for a mission and create offload logs
    
    Args:
        session: Database session
        df: WG-VM4 info DataFrame
        mission_id: Mission identifier
        field_season_year: Optional field season year to assign to offload logs (overrides active season)
        
    Returns:
        Processing statistics
    """
    service = WgVm4StationService(session)
    return service.process_wg_vm4_dataframe(df, mission_id, field_season_year)


async def run_vm4_background_pipeline(
    session: SQLModelSession,
    mission_id: str,
    field_season_year: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Process VM4 offloads in a background-safe pipeline with durable checkpoint updates.
    """
    if not is_feature_enabled("vm4_offload_parser"):
        logger.info("VM4 offload parser is disabled by feature toggle; mission=%s", mission_id)
        return {
            "mission_id": mission_id,
            "source_path": None,
            "rows_processed": 0,
            "stats": {"events_processed": 0, "stations_matched": 0, "offload_logs_created": 0, "stations_updated": 0, "errors": 0},
            "remote_health": {},
            "duration_seconds": 0.0,
            "updated_checkpoint": False,
            "parser_disabled": True,
        }

    from .data_service import get_data_service
    from .processors import preprocess_wg_vm4_info_df, preprocess_wg_vm4_remote_health_df

    run_started_at = datetime.now(timezone.utc)
    data_service = get_data_service()
    checkpoint_for_mission_stmt = select(models.Vm4ProcessingCheckpoint).where(
        models.Vm4ProcessingCheckpoint.mission_id == mission_id,
        models.Vm4ProcessingCheckpoint.report_type == "wg_vm4_info",
    ).order_by(models.Vm4ProcessingCheckpoint.updated_at_utc.desc())
    previous_checkpoint = session.exec(checkpoint_for_mission_stmt).first()
    start_date = None
    if previous_checkpoint and previous_checkpoint.last_processed_timestamp_utc:
        start_date = previous_checkpoint.last_processed_timestamp_utc - timedelta(hours=2)

    df, source_path, file_mod_time = await data_service.load(
        "wg_vm4_info",
        mission_id,
        start_date=start_date,
        end_date=datetime.now(timezone.utc) if start_date else None,
        hours_back=None if start_date is None else None,
    )
    if df is None or df.empty:
        return {
            "mission_id": mission_id,
            "source_path": source_path,
            "rows_processed": 0,
            "stats": {"events_processed": 0, "stations_matched": 0, "offload_logs_created": 0, "stations_updated": 0, "errors": 0},
            "remote_health": {},
            "duration_seconds": (datetime.now(timezone.utc) - run_started_at).total_seconds(),
            "updated_checkpoint": False,
        }

    processed_df = preprocess_wg_vm4_info_df(df)
    stats = process_wg_vm4_info_for_mission(session, processed_df, mission_id, field_season_year)

    health_stats: Dict[str, int] = {}
    rh_df, _, _ = await data_service.load("wg_vm4_remote_health", mission_id, hours_back=None)
    if rh_df is not None and not rh_df.empty:
        rh_processed = preprocess_wg_vm4_remote_health_df(rh_df)
        health_stats = attach_remote_health_to_offload_logs(session, rh_processed)

    checkpoint_stmt = select(models.Vm4ProcessingCheckpoint).where(
        models.Vm4ProcessingCheckpoint.mission_id == mission_id,
        models.Vm4ProcessingCheckpoint.report_type == "wg_vm4_info",
        models.Vm4ProcessingCheckpoint.source_path == (source_path or "unknown"),
    )
    checkpoint = session.exec(checkpoint_stmt).first()
    if not checkpoint:
        checkpoint = models.Vm4ProcessingCheckpoint(
            mission_id=mission_id,
            report_type="wg_vm4_info",
            source_path=source_path or "unknown",
        )
    checkpoint.last_processed_timestamp_utc = run_started_at
    checkpoint.last_file_modification_time_utc = file_mod_time
    checkpoint.last_parser_run_id = f"{mission_id}:{run_started_at.isoformat()}"
    checkpoint.last_rows_processed = len(processed_df)
    checkpoint.last_events_processed = int(stats.get("events_processed", 0))
    checkpoint.last_offload_logs_upserted = int(stats.get("offload_logs_created", 0))
    session.add(checkpoint)
    session.commit()

    duration_seconds = (datetime.now(timezone.utc) - run_started_at).total_seconds()
    result = {
        "mission_id": mission_id,
        "source_path": source_path,
        "start_date_used": start_date.isoformat() if start_date else None,
        "rows_processed": len(processed_df),
        "stats": stats,
        "remote_health": health_stats,
        "duration_seconds": duration_seconds,
        "updated_checkpoint": True,
    }
    logger.info(
        "VM4 background pipeline completed mission=%s rows=%s events=%s logs=%s duration_s=%.2f",
        mission_id,
        result["rows_processed"],
        stats.get("events_processed", 0),
        stats.get("offload_logs_created", 0),
        duration_seconds,
    )
    return result


def attach_remote_health_to_offload_logs(
    session: SQLModelSession,
    remote_health_df,
    time_window_minutes: int = 30,
) -> Dict[str, int]:
    """
    Match Vemco VM4 Remote Health rows to offload logs by serial number and timestamp,
    and update logs with model_id, serial_number, modem_address, temperature_c, tilt_rad, humidity.
    
    Args:
        session: Database session
        remote_health_df: Preprocessed DataFrame from Vemco VM4 Remote Health.csv
        time_window_minutes: Match health row to offload log if within ± this many minutes
        
    Returns:
        Dict with keys: rows_processed, logs_updated, stations_matched, no_station, no_matching_log
    """
    if remote_health_df is None or remote_health_df.empty:
        return {"rows_processed": 0, "logs_updated": 0, "stations_matched": 0, "no_station": 0, "no_matching_log": 0}
    
    stats = {"rows_processed": 0, "logs_updated": 0, "stations_matched": 0, "no_station": 0, "no_matching_log": 0}
    
    # Required columns (after preprocessing)
    required = ["serial_number", "timestamp"]
    optional = ["model_id", "modem_address", "temperature_c", "tilt_rad", "humidity"]
    for c in required:
        if c not in remote_health_df.columns:
            logger.warning(f"attach_remote_health_to_offload_logs: missing column '{c}' in remote health DataFrame")
            return stats
    
    service = WgVm4StationService(session)
    
    for _, row in remote_health_df.iterrows():
        stats["rows_processed"] += 1
        serial = str(row["serial_number"]).strip() if pd.notna(row["serial_number"]) else None
        ts = row["timestamp"]
        if not serial or pd.isna(ts):
            continue
        if hasattr(ts, "to_pydatetime"):
            ts = ts.to_pydatetime()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        
        station = service.find_station_by_serial(serial)
        if not station:
            stats["no_station"] += 1
            continue
        stats["stations_matched"] += 1
        
        start_window = ts - timedelta(minutes=time_window_minutes)
        end_window = ts + timedelta(minutes=time_window_minutes)
        
        stmt = select(models.OffloadLog).where(
            models.OffloadLog.station_id == station.station_id,
            models.OffloadLog.offload_start_time_utc.isnot(None),
            models.OffloadLog.offload_start_time_utc >= start_window,
            models.OffloadLog.offload_start_time_utc <= end_window,
        ).order_by(models.OffloadLog.offload_start_time_utc.desc())
        
        log = session.exec(stmt).first()
        if not log:
            stmt2 = select(models.OffloadLog).where(
                models.OffloadLog.station_id == station.station_id,
                models.OffloadLog.time_first_command_sent_utc.isnot(None),
                models.OffloadLog.time_first_command_sent_utc >= start_window,
                models.OffloadLog.time_first_command_sent_utc <= end_window,
            ).order_by(models.OffloadLog.time_first_command_sent_utc.desc())
            log = session.exec(stmt2).first()
        
        if not log:
            stats["no_matching_log"] += 1
            continue
        
        updated = False
        if "model_id" in row and pd.notna(row.get("model_id")):
            log.remote_health_model_id = str(int(row["model_id"])) if isinstance(row["model_id"], (int, float)) else str(row["model_id"])
            updated = True
        if "serial_number" in row and pd.notna(row.get("serial_number")):
            log.remote_health_serial_number = str(row["serial_number"]).strip()
            updated = True
        if "modem_address" in row and pd.notna(row.get("modem_address")):
            log.remote_health_modem_address = int(row["modem_address"])
            updated = True
        if "temperature_c" in row and pd.notna(row.get("temperature_c")):
            log.remote_health_temperature_c = float(row["temperature_c"])
            updated = True
        if "tilt_rad" in row and pd.notna(row.get("tilt_rad")):
            log.remote_health_tilt_rad = float(row["tilt_rad"])
            updated = True
        if "humidity" in row and pd.notna(row.get("humidity")):
            val = row["humidity"]
            log.remote_health_humidity = int(val) if isinstance(val, (int, float)) else None
            updated = True
        
        if updated:
            session.add(log)
            stats["logs_updated"] += 1
    
    if stats["logs_updated"] > 0:
        session.commit()
    return stats
