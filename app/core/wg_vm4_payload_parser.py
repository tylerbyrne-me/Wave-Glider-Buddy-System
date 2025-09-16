"""
WG-VM4 Payload Parser

This module parses WG-VM4 info payload data to extract offload events and station information.
"""

import re
import logging
import pandas as pd
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class OffloadEventType(Enum):
    """Types of offload events that can be parsed from WG-VM4 payloads"""
    CONNECTION_ATTEMPT = "connection_attempt"
    CONNECTION_SUCCESS = "connection_success"
    CONNECTION_FAILED = "connection_failed"
    OFFLOAD_START = "offload_start"
    OFFLOAD_PROGRESS = "offload_progress"
    OFFLOAD_COMPLETE = "offload_complete"
    OFFLOAD_FAILED = "offload_failed"
    STATION_INFO = "station_info"
    UNKNOWN = "unknown"


@dataclass
class OffloadEvent:
    """Represents a parsed offload event from WG-VM4 payload data"""
    event_type: OffloadEventType
    timestamp: datetime
    latitude: float
    longitude: float
    raw_payload: str
    
    # Event-specific data
    serial_number: Optional[str] = None
    station_id: Optional[str] = None
    progress_percent: Optional[int] = None
    error_count: Optional[int] = None
    modem_range_m: Optional[float] = None
    vrl_file_path: Optional[str] = None
    vrl_file_name: Optional[str] = None
    range_km: Optional[float] = None
    bearing: Optional[float] = None
    connection_status: Optional[str] = None


class WgVm4PayloadParser:
    """Parser for WG-VM4 payload data to extract offload events and station information"""
    
    def __init__(self):
        # Compiled regex patterns for different event types
        self.patterns = {
            OffloadEventType.CONNECTION_ATTEMPT: re.compile(
                r'Connecting to remote VR4-(\d+)', re.IGNORECASE
            ),
            OffloadEventType.CONNECTION_SUCCESS: re.compile(
                r'Connected to remote VR4-(\d+)', re.IGNORECASE
            ),
            OffloadEventType.CONNECTION_FAILED: re.compile(
                r'Failed to connect to remote VR4-(\d+)', re.IGNORECASE
            ),
            OffloadEventType.OFFLOAD_START: re.compile(
                r'Starting remote offload for VR4-(\d+)', re.IGNORECASE
            ),
            OffloadEventType.OFFLOAD_PROGRESS: re.compile(
                r'remote offload in progress:\s*(\d+)%\s*complete,\s*(\d+)\s*errors,\s*modem range:\s*([\d.]+)m',
                re.IGNORECASE
            ),
            OffloadEventType.OFFLOAD_COMPLETE: re.compile(
                r'Completed remote offload:\s*(.+)', re.IGNORECASE
            ),
            OffloadEventType.OFFLOAD_FAILED: re.compile(
                r'Failed remote offload for VR4-(\d+):\s*(.+)', re.IGNORECASE
            ),
            OffloadEventType.STATION_INFO: re.compile(
                r'Station\s+([A-Z0-9]+):\s*range=([\d.]+)km,\s*bearing:\s*([\d.]+)',
                re.IGNORECASE
            )
        }
    
    def parse_payload(self, timestamp: datetime, latitude: float, longitude: float, payload: str) -> Optional[OffloadEvent]:
        """
        Parse a single payload string and return an OffloadEvent if a pattern matches
        
        Args:
            timestamp: Event timestamp
            latitude: GPS latitude
            longitude: GPS longitude
            payload: Raw payload string
            
        Returns:
            OffloadEvent object if parsing successful, None otherwise
        """
        if not payload or not payload.strip():
            return None
            
        payload = payload.strip()
        
        # Try to match each event type pattern
        for event_type, pattern in self.patterns.items():
            match = pattern.search(payload)
            if match:
                return self._create_event_from_match(
                    event_type, timestamp, latitude, longitude, payload, match
                )
        
        # If no pattern matches, create an unknown event
        # Debug: Log offload complete patterns that don't match
        if 'Completed remote offload' in payload:
            logger.debug(f"OFFLOAD_COMPLETE pattern didn't match: {payload[:200]}...")
        logger.debug(f"No pattern matched for payload: {payload[:100]}...")
        return OffloadEvent(
            event_type=OffloadEventType.UNKNOWN,
            timestamp=timestamp,
            latitude=latitude,
            longitude=longitude,
            raw_payload=payload
        )
    
    def _create_event_from_match(
        self, 
        event_type: OffloadEventType, 
        timestamp: datetime, 
        latitude: float, 
        longitude: float, 
        payload: str, 
        match: re.Match
    ) -> OffloadEvent:
        """Create an OffloadEvent from a successful regex match"""
        
        event = OffloadEvent(
            event_type=event_type,
            timestamp=timestamp,
            latitude=latitude,
            longitude=longitude,
            raw_payload=payload
        )
        
        # Extract data based on event type
        if event_type == OffloadEventType.CONNECTION_ATTEMPT:
            event.serial_number = match.group(1)
            event.connection_status = "attempting"
            
        elif event_type == OffloadEventType.CONNECTION_SUCCESS:
            event.serial_number = match.group(1)
            event.connection_status = "success"
            
        elif event_type == OffloadEventType.CONNECTION_FAILED:
            event.serial_number = match.group(1)
            event.connection_status = "failed"
            
        elif event_type == OffloadEventType.OFFLOAD_START:
            event.serial_number = match.group(1)
            
        elif event_type == OffloadEventType.OFFLOAD_PROGRESS:
            event.progress_percent = int(match.group(1))
            event.error_count = int(match.group(2))
            event.modem_range_m = float(match.group(3))
            
        elif event_type == OffloadEventType.OFFLOAD_COMPLETE:
            vrl_path = match.group(1)  # Full path
            event.vrl_file_path = vrl_path
            
            # Extract serial number from the path (look for VR4-XXXXXX pattern)
            serial_match = re.search(r'VR4-[A-Z_]*(\d+)', vrl_path)
            if serial_match:
                event.serial_number = serial_match.group(1)
            
            # Extract filename from path (remove extra text after .vrl)
            if '/' in vrl_path:
                filename = vrl_path.split('/')[-1]
                # Remove everything after .vrl if present
                if '.vrl' in filename:
                    filename = filename.split('.vrl')[0] + '.vrl'
                event.vrl_file_name = filename
            else:
                event.vrl_file_name = vrl_path
                
        elif event_type == OffloadEventType.OFFLOAD_FAILED:
            event.serial_number = match.group(1)
            # Could extract error message from group(2) if needed
            
        elif event_type == OffloadEventType.STATION_INFO:
            event.station_id = match.group(1)
            event.range_km = float(match.group(2))
            event.bearing = float(match.group(3))
        
        return event
    
    def parse_dataframe(self, df) -> List[OffloadEvent]:
        """
        Parse an entire DataFrame of WG-VM4 info data
        
        Args:
            df: DataFrame with columns 'timeStamp', 'latitude', 'longitude', 'payload Data' or 'payload_data'
            
        Returns:
            List of OffloadEvent objects
        """
        events = []
        
        for _, row in df.iterrows():
            try:
                # Extract basic data
                timestamp = pd.to_datetime(row['timeStamp'])
                latitude = float(row['latitude'])
                longitude = float(row['longitude'])
                
                # Handle both column name variations
                if 'payload_data' in df.columns:
                    payload_col = 'payload_data'
                elif 'payload Data' in df.columns:
                    payload_col = 'payload Data'
                else:
                    logger.warning(f"No payload column found in dataframe. Available columns: {list(df.columns)}")
                    continue
                    
                payload = str(row[payload_col])
                
                # Parse the payload
                event = self.parse_payload(timestamp, latitude, longitude, payload)
                if event:
                    events.append(event)
                    
            except Exception as e:
                logger.warning(f"Error parsing row {row.name}: {e}")
                continue
        
        return events
    
    def get_offload_sessions(self, events: List[OffloadEvent]) -> List[Dict[str, Any]]:
        """
        Group events into offload sessions for easier analysis
        
        Args:
            events: List of parsed OffloadEvent objects
            
        Returns:
            List of dictionaries representing offload sessions
        """
        sessions = []
        current_session = None
        
        for event in events:
            # Skip events without serial numbers
            if not event.serial_number:
                continue
                
            if event.event_type == OffloadEventType.CONNECTION_ATTEMPT:
                # Start new session
                if current_session:
                    sessions.append(current_session)
                
                current_session = {
                    'serial_number': event.serial_number,
                    'start_time': event.timestamp,
                    'start_latitude': event.latitude,
                    'start_longitude': event.longitude,
                    'events': [event],
                    'status': 'in_progress'
                }
                
            elif event.event_type == OffloadEventType.OFFLOAD_COMPLETE:
                # Handle standalone offload complete events (no connection attempt)
                if not current_session or current_session['serial_number'] != event.serial_number:
                    # Create a new session for this offload complete
                    if current_session:
                        sessions.append(current_session)
                    
                    current_session = {
                        'serial_number': event.serial_number,
                        'start_time': event.timestamp,  # Use complete time as start if no connection attempt
                        'start_latitude': event.latitude,
                        'start_longitude': event.longitude,
                        'events': [event],
                        'status': 'completed'
                    }
                else:
                    # Add to existing session
                    current_session['events'].append(event)
                
                # Update session status
                current_session['end_time'] = event.timestamp
                current_session['end_latitude'] = event.latitude
                current_session['end_longitude'] = event.longitude
                current_session['status'] = 'completed'
                current_session['vrl_file_name'] = event.vrl_file_name
                current_session['vrl_file_path'] = event.vrl_file_path
                
            elif current_session and event.serial_number == current_session['serial_number']:
                # Add event to current session
                current_session['events'].append(event)
                
                # Update session status based on event type
                if event.event_type == OffloadEventType.CONNECTION_SUCCESS:
                    current_session['connection_time'] = event.timestamp
                    current_session['connection_latitude'] = event.latitude
                    current_session['connection_longitude'] = event.longitude
                    
                elif event.event_type == OffloadEventType.CONNECTION_FAILED:
                    current_session['end_time'] = event.timestamp
                    current_session['status'] = 'connection_failed'
                    
                elif event.event_type == OffloadEventType.OFFLOAD_FAILED:
                    current_session['end_time'] = event.timestamp
                    current_session['status'] = 'offload_failed'
        
        # Add final session if exists
        if current_session:
            sessions.append(current_session)
        
        return sessions


# Convenience function for easy integration
def parse_wg_vm4_info_data(df) -> Tuple[List[OffloadEvent], List[Dict[str, Any]]]:
    """
    Parse WG-VM4 info DataFrame and return both events and sessions
    
    Args:
        df: DataFrame with WG-VM4 info data
        
    Returns:
        Tuple of (events, sessions)
    """
    parser = WgVm4PayloadParser()
    events = parser.parse_dataframe(df)
    sessions = parser.get_offload_sessions(events)
    
    return events, sessions
