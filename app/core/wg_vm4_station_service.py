"""
WG-VM4 Station Service

This module handles automatic station matching and offload log creation
from WG-VM4 info data.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple
import math

from sqlmodel import select
from .db import SQLModelSession
from . import models
from .wg_vm4_payload_parser import WgVm4PayloadParser, OffloadEvent, OffloadEventType

logger = logging.getLogger(__name__)


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
        mission_id: str
    ) -> Dict[str, int]:
        """
        Process WG-VM4 events and create offload logs
        
        Args:
            events: List of parsed OffloadEvent objects
            mission_id: Mission identifier
            
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
                    if self._create_offload_log_from_session(session, station, mission_id):
                        stats['offload_logs_created'] += 1
                        stats['stations_updated'] += 1
                        
            except Exception as e:
                logger.error(f"Error processing events for serial {serial_number}: {e}")
                stats['errors'] += 1
                continue
        
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
        mission_id: str
    ) -> bool:
        """
        Create an offload log from a parsed session
        
        Args:
            session: Parsed offload session dictionary
            station: Station metadata object
            mission_id: Mission identifier
            
        Returns:
            True if log was created successfully
        """
        try:
            # Only create logs for completed sessions
            if session['status'] not in ['completed', 'offload_failed']:
                logger.debug(f"Skipping incomplete session for station {station.station_id} (status: {session['status']})")
                return False
            
            # Check if we already have a log for this time period
            existing_log = self._find_existing_log(station.station_id, session['start_time'])
            if existing_log:
                logger.debug(f"Offload log already exists for station {station.station_id} at {session['start_time']}")
                return False
            
            # Extract session data
            start_time = session['start_time']
            end_time = session.get('end_time', start_time)
            
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
                'logged_by_username': 'wg_vm4_auto'
            }
            
            # Create the offload log
            offload_log = models.OffloadLog.model_validate(offload_log_data)
            self.session.add(offload_log)
            
            # Update station metadata
            station.last_offload_timestamp_utc = end_time
            station.was_last_offload_successful = was_offloaded
            station.last_offload_by_glider = mission_id
            self.session.add(station)
            
            # Commit changes
            self.session.commit()
            self.session.refresh(offload_log)
            
            logger.info(f"Created offload log for station {station.station_id} from WG-VM4 data")
            return True
            
        except Exception as e:
            logger.error(f"Error creating offload log for station {station.station_id}: {e}")
            self.session.rollback()
            return False
    
    def _find_existing_log(
        self, 
        station_id: str, 
        start_time: datetime
    ) -> Optional[models.OffloadLog]:
        """
        Check if an offload log already exists for this station and time period
        
        Args:
            station_id: Station identifier
            start_time: Session start time
            
        Returns:
            Existing OffloadLog or None
        """
        # Look for logs within 1 hour of the start time
        time_window = 3600  # 1 hour in seconds
        start_window = start_time - timedelta(seconds=time_window)
        end_window = start_time + timedelta(seconds=time_window)
        
        statement = select(models.OffloadLog).where(
            models.OffloadLog.station_id == station_id,
            models.OffloadLog.offload_start_time_utc >= start_window,
            models.OffloadLog.offload_start_time_utc <= end_window
        )
        
        return self.session.exec(statement).first()
    
    def process_wg_vm4_dataframe(
        self, 
        df, 
        mission_id: str
    ) -> Dict[str, int]:
        """
        Process a WG-VM4 info DataFrame and create offload logs
        
        Args:
            df: WG-VM4 info DataFrame
            mission_id: Mission identifier
            
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
            stats = self.process_wg_vm4_events(events, mission_id)
            
            # Debug: Show session statistics
            all_sessions = []
            for serial_number, station_events in self._group_events_by_serial(events).items():
                sessions = self.parser.get_offload_sessions(station_events)
                all_sessions.extend(sessions)
            
            session_statuses = {}
            for session in all_sessions:
                status = session['status']
                session_statuses[status] = session_statuses.get(status, 0) + 1
            logger.info(f"Session status distribution: {session_statuses}")
            
            logger.info(f"WG-VM4 processing complete: {stats}")
            return stats
            
        except Exception as e:
            logger.error(f"Error processing WG-VM4 dataframe: {e}")
            return {'events_processed': 0, 'stations_matched': 0, 'offload_logs_created': 0, 'stations_updated': 0, 'errors': 1}


# Convenience function for easy integration
def process_wg_vm4_info_for_mission(
    session: SQLModelSession, 
    df, 
    mission_id: str
) -> Dict[str, int]:
    """
    Process WG-VM4 info data for a mission and create offload logs
    
    Args:
        session: Database session
        df: WG-VM4 info DataFrame
        mission_id: Mission identifier
        
    Returns:
        Processing statistics
    """
    service = WgVm4StationService(session)
    return service.process_wg_vm4_dataframe(df, mission_id)
