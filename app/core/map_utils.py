"""
Map utilities for mission track visualization and KML generation.

This module provides functions to prepare telemetry data for map display
and generate KML files for export to Google Maps/Earth.
"""

from typing import List, Dict, Any, Optional
import logging
from datetime import datetime, timezone

import pandas as pd

logger = logging.getLogger(__name__)


def prepare_track_points(df: pd.DataFrame, max_points: int = 1000) -> List[Dict[str, Any]]:
    """
    Prepare telemetry data for map visualization.
    
    Extracts latitude, longitude, and timestamp from a telemetry DataFrame
    and returns a list of points suitable for map plotting.
    
    Args:
        df: Preprocessed telemetry DataFrame with standardized columns
            (Latitude, Longitude, Timestamp from preprocess_telemetry_df)
        max_points: Maximum number of points to return (for performance)
    
    Returns:
        List of dictionaries with 'lat', 'lon', and 'timestamp' keys
        
    Example:
        [{'lat': 40.7128, 'lon': -74.0060, 'timestamp': '2024-01-01T12:00:00'}, ...]
    """
    if df.empty:
        logger.warning("Empty DataFrame provided to prepare_track_points")
        return []
    
    # Ensure we have the required columns
    required_cols = ['Latitude', 'Longitude', 'Timestamp']
    missing_cols = [col for col in required_cols if col not in df.columns]
    
    if missing_cols:
        logger.error(f"Missing required columns in DataFrame: {missing_cols}")
        logger.debug(f"Available columns: {df.columns.tolist()}")
        return []
    
    # Drop rows with missing coordinates
    df_clean = df.dropna(subset=['Latitude', 'Longitude', 'Timestamp'])
    
    if df_clean.empty:
        logger.warning("No valid coordinates found after dropping NaN values")
        return []
    
    # Sort by timestamp to ensure chronological order
    df_clean = df_clean.sort_values('Timestamp')
    
    # Downsample if we have too many points for performance
    if len(df_clean) > max_points:
        step = len(df_clean) // max_points
        df_clean = df_clean.iloc[::step].reset_index(drop=True)
        logger.info(f"Downsampled track from {len(df)} to {len(df_clean)} points")
    
    # Extract points
    track_points = []
    for _, row in df_clean.iterrows():
        # Handle timestamp - ALL timestamps are UTC (never convert to local time)
        # Source data timestamps are always in UTC according to specification
        timestamp = row['Timestamp']
        
        if isinstance(timestamp, pd.Timestamp):
            # Ensure UTC timezone
            if timestamp.tz is None:
                # Naive timestamp - localize to UTC (data source timestamps are always UTC)
                timestamp_utc = timestamp.tz_localize('UTC')
            elif str(timestamp.tz) != 'UTC':
                # Timezone-aware but not UTC - convert to UTC
                timestamp_utc = timestamp.tz_convert('UTC')
            else:
                # Already UTC
                timestamp_utc = timestamp
            
            # Format as ISO 8601 with Z suffix (always UTC)
            timestamp_str = timestamp_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
                
        elif isinstance(timestamp, datetime):
            # Python datetime object - ensure UTC
            if timestamp.tzinfo is None:
                # Naive - assume UTC (data source timestamps are always UTC)
                timestamp_utc = timestamp.replace(tzinfo=timezone.utc)
            else:
                # Timezone-aware - ensure UTC
                timestamp_utc = timestamp.astimezone(timezone.utc)
            timestamp_str = timestamp_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
        else:
            # Fallback to string conversion
            timestamp_str = str(timestamp)
        
        track_points.append({
            'lat': float(row['Latitude']),
            'lon': float(row['Longitude']),
            'timestamp': timestamp_str
        })
    
    logger.info(f"Prepared {len(track_points)} track points")
    return track_points


def generate_kml_from_track_points(
    track_points: List[Dict[str, Any]], 
    mission_id: str,
    color: str = "#3388ff"
) -> str:
    """
    Generate a KML file string from track points.
    
    KML format can be imported into Google Maps and Google Earth.
    
    Args:
        track_points: List of points with 'lat', 'lon', 'timestamp'
        mission_id: Mission identifier for the track name
        color: Line color in hex format (default: blue)
    
    Returns:
        KML formatted string
    """
    # Convert hex color to KML AABBGGRR format with 80% opacity
    kml_color = hex_to_kml_color(color, opacity=204)  # 80% opacity
    if not track_points:
        logger.warning("No track points provided for KML generation")
        return '<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document/></kml>'
    
    kml_parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<kml xmlns="http://www.opengis.net/kml/2.2">',
        '<Document>',
        f'<name>Mission {mission_id} Track</name>',
        '<description>Wave Glider telemetry track</description>',
        f'<Style id="trackStyle">',
        f'<LineStyle>',
        f'<color>{kml_color}</color>',
        f'<width>3</width>',
        f'</LineStyle>',
        f'</Style>',
        '<Placemark>',
        f'<name>Mission {mission_id} Path</name>',
        '<styleUrl>#trackStyle</styleUrl>',
        '<LineString>',
        '<tessellate>1</tessellate>',
        '<coordinates>'
    ]
    
    # Add coordinates in KML format: lon,lat,altitude
    for point in track_points:
        kml_parts.append(f"{point['lon']},{point['lat']},0")
    
    kml_parts.extend([
        '</coordinates>',
        '</LineString>',
        '</Placemark>',
        '</Document>',
        '</kml>'
    ])
    
    return '\n'.join(kml_parts)


def get_track_bounds(track_points: List[Dict[str, Any]]) -> Optional[Dict[str, float]]:
    """
    Calculate the bounding box for a set of track points.
    
    Useful for setting initial map extent.
    
    Args:
        track_points: List of points with 'lat', 'lon'
    
    Returns:
        Dictionary with 'north', 'south', 'east', 'west' keys
        or None if no points provided
    """
    if not track_points:
        return None
    
    lats = [point['lat'] for point in track_points]
    lons = [point['lon'] for point in track_points]
    
    return {
        'north': max(lats),
        'south': min(lats),
        'east': max(lons),
        'west': min(lons)
    }


def hex_to_kml_color(hex_color: str, opacity: int = 255) -> str:
    """Convert hex color to KML AABBGGRR format
    
    Args:
        hex_color: Hex color string like '#3388ff'
        opacity: Opacity value 0-255 (default 255 = 100% opaque)
    Returns:
        KML color string in AABBGGRR format
    """
    hex_color = hex_color.lstrip('#')
    r = hex_color[0:2]
    g = hex_color[2:4]
    b = hex_color[4:6]
    # KML uses AABBGGRR format
    alpha = format(opacity, '02x').upper()
    return f'{alpha}{b}{g}{r}'  # Alpha, then BGR (reversed order)


def generate_live_kml_with_track(
    mission_tracks: List[tuple],
    description: Optional[str] = None
) -> str:
    """
    Generate KML with timed track data for Google Earth animation.
    
    Args:
        mission_tracks: List of tuples (mission_id, track_points)
        description: Optional description for the KML
    
    Returns:
        KML XML string
    """
    color_palette = [
        '#3388ff',  # Blue
        '#dc143c',  # Crimson
        '#32cd32',  # Lime Green
        '#ff8c00',  # Dark Orange
        '#9370db',  # Medium Purple
        '#ff69b4',  # Hot Pink
        '#00ced1',  # Dark Turquoise
        '#ffa500'   # Orange
    ]
    
    kml_parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<kml xmlns="http://www.opengis.net/kml/2.2">',
        '<Document>',
        f'<name>Live Mission Tracks</name>',
        f'<description>{description or "Automatically updating mission tracks"}</description>'
    ]
    
    # Add styles for each mission
    for i, (mission_id, _) in enumerate(mission_tracks):
        color = color_palette[i % len(color_palette)]
        # Use 100% opacity for better visibility
        kml_color = hex_to_kml_color(color, opacity=255)
        
        kml_parts.extend([
            f'<Style id="mission{mission_id}Style">',
            f'  <LineStyle>',
            f'    <color>{kml_color}</color>',
            f'    <width>3</width>',
            f'  </LineStyle>',
            f'  <IconStyle>',
            f'    <Icon>',
            f'      <href>http://maps.google.com/mapfiles/kml/shapes/track.png</href>',
            f'    </Icon>',
            f'  </IconStyle>',
            f'</Style>',
            f'<Style id="startStyle{mission_id}">',
            f'  <IconStyle>',
            f'    <color>ff00ff00</color>',
            f'    <scale>1.2</scale>',
            f'    <Icon>',
            f'      <href>http://maps.google.com/mapfiles/kml/pushpin/grn-pushpin.png</href>',
            f'    </Icon>',
            f'  </IconStyle>',
            f'</Style>',
            f'<Style id="endStyle{mission_id}">',
            f'  <IconStyle>',
            f'    <color>ff0000ff</color>',
            f'    <scale>1.2</scale>',
            f'    <Icon>',
            f'      <href>http://maps.google.com/mapfiles/kml/pushpin/red-pushpin.png</href>',
            f'    </Icon>',
            f'  </IconStyle>',
            f'</Style>'
        ])
    
    # Add mission tracks with timestamps
    for mission_id, track_points in mission_tracks:
        if not track_points:
            continue
        
        # Start marker
        first_point = track_points[0]
        kml_parts.extend([
            f'<Placemark>',
            f'  <name>Mission {mission_id} - Start</name>',
            f'  <description>Start: {first_point.get("timestamp", "N/A")}</description>',
            f'  <styleUrl>#startStyle{mission_id}</styleUrl>',
            f'  <Point>',
            f'    <coordinates>{first_point["lon"]},{first_point["lat"]},0</coordinates>',
            f'  </Point>',
            f'</Placemark>'
        ])
        
        # End marker
        last_point = track_points[-1]
        kml_parts.extend([
            f'<Placemark>',
            f'  <name>Mission {mission_id} - End</name>',
            f'  <description>End: {last_point.get("timestamp", "N/A")}</description>',
            f'  <styleUrl>#endStyle{mission_id}</styleUrl>',
            f'  <Point>',
            f'    <coordinates>{last_point["lon"]},{last_point["lat"]},0</coordinates>',
            f'  </Point>',
            f'</Placemark>'
        ])
        
        # Track line (using LineString for better compatibility)
        coords_list = []
        for point in track_points:
            coords_list.append(f"{point['lon']},{point['lat']},0")
        
        kml_parts.extend([
            f'<Placemark>',
            f'  <name>Mission {mission_id} Track</name>',
            f'  <description>Mission {mission_id} track with {len(track_points)} points</description>',
            f'  <styleUrl>#mission{mission_id}Style</styleUrl>',
            f'  <LineString>',
            f'    <tessellate>1</tessellate>',
            f'    <altitudeMode>clampToGround</altitudeMode>',
            f'    <coordinates>',
            '      ' + '\n      '.join(coords_list),
            f'    </coordinates>',
            f'  </LineString>',
            f'</Placemark>'
        ])
    
    kml_parts.extend([
        '</Document>',
        '</kml>'
    ])
    
    return '\n'.join(kml_parts)

