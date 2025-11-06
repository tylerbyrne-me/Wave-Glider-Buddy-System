"""
API endpoints for mission map visualization.

Provides endpoints to retrieve telemetry data for map display
and generate KML files for Google Maps/Earth export.
"""

from typing import Optional, List
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import JSONResponse, Response
import logging
import math
import asyncio
import pandas as pd
import httpx

from ..core.auth import get_current_active_user
from ..core import models
from ..core.map_utils import prepare_track_points, generate_kml_from_track_points, get_track_bounds
from ..core.processors import preprocess_telemetry_df
from ..core.data_service import get_data_service
from ..core.error_handlers import handle_processing_error, handle_data_not_found, ErrorContext

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Map"])


async def _prepare_track_data(
    mission_id: str,
    hours_back: int,
    current_user: models.User,
    max_points: int = 1000
) -> dict:
    """
    Helper function to load, preprocess, and prepare track data for a mission.
    
    This function encapsulates the common pattern of:
    1. Loading telemetry data
    2. Preprocessing to standardize columns
    3. Preparing track points
    4. Calculating bounds
    
    Args:
        mission_id: Mission identifier
        hours_back: Number of hours of history to retrieve
        current_user: Authenticated user
        max_points: Maximum number of track points to return
        
    Returns:
        Dictionary with track_points, point_count, bounds, source, and optional error
    """
    try:
        # Load data using data service
        data_service = get_data_service()
        df, source_path, _ = await data_service.load(
            "telemetry",
            mission_id,
            source_preference=None,  # Use default (remote then local)
            custom_local_path=None,
            force_refresh=False,
            current_user=current_user,
            hours_back=hours_back
        )
        
        if df is None or df.empty:
            logger.warning(f"No telemetry data found for mission {mission_id}")
            return {
                "track_points": [],
                "point_count": 0,
                "bounds": None,
                "source": str(source_path),
                "error": "No data available"
            }
        
        # Preprocess to get standardized column names
        processed_df = preprocess_telemetry_df(df)
        
        if processed_df.empty:
            logger.warning(f"No valid track points after preprocessing for mission {mission_id}")
            return {
                "track_points": [],
                "point_count": 0,
                "bounds": None,
                "source": str(source_path),
                "error": "No valid track points"
            }
        
        # Prepare track points
        track_points = prepare_track_points(processed_df, max_points=max_points)
        
        # Calculate bounds for initial map extent
        bounds = get_track_bounds(track_points)
        
        return {
            "track_points": track_points,
            "point_count": len(track_points),
            "bounds": bounds,
            "source": str(source_path),
            "error": None
        }
        
    except Exception as e:
        logger.error(f"Error processing track data for mission {mission_id}: {e}", exc_info=True)
        return {
            "track_points": [],
            "point_count": 0,
            "bounds": None,
            "source": "Unknown",
            "error": str(e)
        }


@router.get("/api/map/telemetry/{mission_id}")
async def get_mission_track(
    mission_id: str,
    hours_back: int = Query(72, ge=1, le=8760, description="Hours of history to retrieve"),
    current_user: models.User = Depends(get_current_active_user)
):
    """
    Get telemetry track points for a mission.
    
    Returns latitude, longitude, and timestamp for map visualization.
    Uses existing data loading and caching infrastructure.
    
    Args:
        mission_id: Mission identifier
        hours_back: Number of hours of history to retrieve (default: 72)
        current_user: Authenticated user
    
    Returns:
        JSON response with track points and metadata
    """
    try:
        logger.info(f"Fetching track data for mission {mission_id} (last {hours_back} hours)")
        
        # Use shared helper function to prepare track data
        track_data = await _prepare_track_data(mission_id, hours_back, current_user, max_points=1000)
        
        response_data = {
            "mission_id": mission_id,
            "track_points": track_data["track_points"],
            "point_count": track_data["point_count"],
            "bounds": track_data["bounds"],
            "hours_back": hours_back,
            "source": track_data["source"]
        }
        
        logger.info(f"Returning {track_data['point_count']} track points for mission {mission_id}")
        return JSONResponse(content=response_data)
        
    except HTTPException:
        raise
    except Exception as e:
        raise handle_processing_error(
            operation="retrieving track data",
            error=e,
            resource=mission_id,
            user_id=str(current_user.id) if current_user else None
        )


@router.get("/api/map/kml/{mission_id}")
async def get_mission_kml(
    mission_id: str,
    hours_back: int = Query(72, ge=1, le=8760, description="Hours of history to retrieve"),
    current_user: models.User = Depends(get_current_active_user)
):
    """
    Generate a KML file for a mission track.
    
    KML files can be imported into Google Maps, Google Earth, and other GIS applications.
    
    Args:
        mission_id: Mission identifier
        hours_back: Number of hours of history to retrieve (default: 72)
        current_user: Authenticated user
    
    Returns:
        KML file response
    """
    try:
        logger.info(f"Generating KML for mission {mission_id} (last {hours_back} hours)")
        
        # Use shared helper function (with more points for KML export)
        track_data = await _prepare_track_data(mission_id, hours_back, current_user, max_points=5000)
        
        if track_data.get("error") or not track_data["track_points"]:
            error_msg = track_data.get("error", "No track points available")
            raise handle_data_not_found(
                data_type="telemetry",
                mission_id=mission_id,
                context=ErrorContext(operation="generating KML", resource=mission_id)
            )
        
        # Generate KML
        kml_content = generate_kml_from_track_points(track_data["track_points"], mission_id)
        
        # Generate filename with timestamp
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"mission_{mission_id}_track_{timestamp}.kml"
        
        logger.info(f"Generated KML file for mission {mission_id} with {track_data['point_count']} points")
        
        return Response(
            content=kml_content,
            media_type="application/vnd.google-earth.kml+xml",
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise handle_processing_error(
            operation="generating KML file",
            error=e,
            resource=mission_id,
            user_id=str(current_user.id) if current_user else None
        )


@router.get("/api/map/multiple")
async def get_multiple_mission_tracks(
    mission_ids: str = Query(..., description="Comma-separated mission IDs"),
    hours_back: int = Query(72, ge=1, le=8760, description="Hours of history to retrieve"),
    current_user: models.User = Depends(get_current_active_user)
):
    """
    Get track data for multiple missions simultaneously.
    
    Useful for comparing tracks from different missions or viewing
    all active missions on a single map.
    
    Args:
        mission_ids: Comma-separated list of mission identifiers
        hours_back: Number of hours of history to retrieve (default: 72)
        current_user: Authenticated user
    
    Returns:
        JSON response with tracks for each mission
    """
    try:
        # Parse mission IDs
        mission_list = [mid.strip() for mid in mission_ids.split(',') if mid.strip()]
        
        if not mission_list:
            from ..core.error_handlers import handle_validation_error
            raise handle_validation_error(
                message="No valid mission IDs provided",
                field="mission_ids"
            )
        
        logger.info(f"Fetching tracks for {len(mission_list)} missions: {mission_list}")
        
        # Fetch data for each mission using shared helper function
        tracks = {}
        
        # Process missions concurrently for better performance
        tasks = [
            _prepare_track_data(mission_id, hours_back, current_user, max_points=1000)
            for mission_id in mission_list
        ]
        
        track_data_list = await asyncio.gather(*tasks, return_exceptions=True)
        
        for mission_id, track_data in zip(mission_list, track_data_list):
            if isinstance(track_data, Exception):
                logger.error(f"Error processing mission {mission_id}: {track_data}")
                tracks[mission_id] = {
                    "track_points": [],
                    "point_count": 0,
                    "bounds": None,
                    "error": str(track_data)
                }
            else:
                # Remove error field if None for clean responses
                mission_track = {
                    "track_points": track_data["track_points"],
                    "point_count": track_data["point_count"],
                    "bounds": track_data["bounds"],
                    "source": track_data["source"]
                }
                if track_data.get("error"):
                    mission_track["error"] = track_data["error"]
                
                tracks[mission_id] = mission_track
                logger.info(f"Mission {mission_id}: {track_data['point_count']} points")
        
        response_data = {
            "missions": tracks,
            "mission_count": len(mission_list),
            "hours_back": hours_back
        }
        
        return JSONResponse(content=response_data)
        
    except HTTPException:
        raise
    except Exception as e:
        raise handle_processing_error(
            operation="retrieving multiple mission tracks",
            error=e,
            user_id=str(current_user.id) if current_user else None
        )



