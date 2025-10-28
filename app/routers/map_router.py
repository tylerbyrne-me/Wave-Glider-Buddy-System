"""
API endpoints for mission map visualization.

Provides endpoints to retrieve telemetry data for map display
and generate KML files for Google Maps/Earth export.
"""

from typing import Optional, List
from datetime import datetime
from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import JSONResponse, Response
import logging
import pandas as pd

from ..auth_utils import get_current_active_user
from ..core import models
from ..core.map_utils import prepare_track_points, generate_kml_from_track_points
from ..core.processors import preprocess_telemetry_df

# Note: load_data_source is imported inside functions to avoid circular import

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Map"])


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
        
        # Import load_data_source to avoid circular import
        from ..app import load_data_source
        
        # Load data using existing infrastructure
        df, source_path = await load_data_source(
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
            return JSONResponse(content={
                "mission_id": mission_id,
                "track_points": [],
                "point_count": 0,
                "bounds": None,
                "source": str(source_path)
            })
        
        # Preprocess to get standardized column names
        processed_df = preprocess_telemetry_df(df)
        
        if processed_df.empty:
            logger.warning(f"No valid track points after preprocessing for mission {mission_id}")
            return JSONResponse(content={
                "mission_id": mission_id,
                "track_points": [],
                "point_count": 0,
                "bounds": None,
                "source": str(source_path)
            })
        
        # Prepare track points (lat/lon only, simplified)
        track_points = prepare_track_points(processed_df, max_points=1000)
        
        # Calculate bounds for initial map extent
        from ..core.map_utils import get_track_bounds
        bounds = get_track_bounds(track_points)
        
        response_data = {
            "mission_id": mission_id,
            "track_points": track_points,
            "point_count": len(track_points),
            "bounds": bounds,
            "hours_back": hours_back,
            "source": str(source_path)
        }
        
        logger.info(f"Returning {len(track_points)} track points for mission {mission_id}")
        return JSONResponse(content=response_data)
        
    except Exception as e:
        logger.error(f"Error fetching track data for mission {mission_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving track data: {str(e)}"
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
        
        # Import load_data_source to avoid circular import
        from ..app import load_data_source
        
        # Load and preprocess data
        df, source_path = await load_data_source(
            "telemetry",
            mission_id,
            source_preference=None,
            custom_local_path=None,
            force_refresh=False,
            current_user=current_user,
            hours_back=hours_back
        )
        
        if df is None or df.empty:
            raise HTTPException(
                status_code=404,
                detail=f"No telemetry data found for mission {mission_id}"
            )
        
        # Preprocess to get standardized column names
        processed_df = preprocess_telemetry_df(df)
        
        if processed_df.empty:
            raise HTTPException(
                status_code=404,
                detail=f"No valid track points for mission {mission_id}"
            )
        
        # Prepare track points
        track_points = prepare_track_points(processed_df, max_points=5000)  # More points for KML
        
        if not track_points:
            raise HTTPException(
                status_code=404,
                detail=f"Could not generate track points for mission {mission_id}"
            )
        
        # Generate KML
        kml_content = generate_kml_from_track_points(track_points, mission_id)
        
        # Generate filename with timestamp
        from datetime import datetime
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"mission_{mission_id}_track_{timestamp}.kml"
        
        logger.info(f"Generated KML file for mission {mission_id} with {len(track_points)} points")
        
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
        logger.error(f"Error generating KML for mission {mission_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error generating KML file: {str(e)}"
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
            raise HTTPException(
                status_code=400,
                detail="No valid mission IDs provided"
            )
        
        logger.info(f"Fetching tracks for {len(mission_list)} missions: {mission_list}")
        
        # Fetch data for each mission
        tracks = {}
        
        # Import load_data_source to avoid circular import
        from ..app import load_data_source
        
        for mission_id in mission_list:
            try:
                # Load data
                df, source_path = await load_data_source(
                    "telemetry",
                    mission_id,
                    source_preference=None,
                    custom_local_path=None,
                    force_refresh=False,
                    current_user=current_user,
                    hours_back=hours_back
                )
                
                if df is None or df.empty:
                    logger.warning(f"No data for mission {mission_id}, skipping")
                    tracks[mission_id] = {
                        "track_points": [],
                        "point_count": 0,
                        "bounds": None,
                        "source": str(source_path),
                        "error": "No data available"
                    }
                    continue
                
                # Preprocess
                processed_df = preprocess_telemetry_df(df)
                
                if processed_df.empty:
                    logger.warning(f"No valid points for mission {mission_id}, skipping")
                    tracks[mission_id] = {
                        "track_points": [],
                        "point_count": 0,
                        "bounds": None,
                        "source": str(source_path),
                        "error": "No valid track points"
                    }
                    continue
                
                # Prepare track points
                track_points = prepare_track_points(processed_df, max_points=1000)
                
                # Calculate bounds
                from ..core.map_utils import get_track_bounds
                bounds = get_track_bounds(track_points)
                
                tracks[mission_id] = {
                    "track_points": track_points,
                    "point_count": len(track_points),
                    "bounds": bounds,
                    "source": str(source_path)
                }
                
                logger.info(f"Mission {mission_id}: {len(track_points)} points")
                
            except Exception as e:
                logger.error(f"Error processing mission {mission_id}: {e}")
                tracks[mission_id] = {
                    "track_points": [],
                    "point_count": 0,
                    "bounds": None,
                    "error": str(e)
                }
        
        response_data = {
            "missions": tracks,
            "mission_count": len(mission_list),
            "hours_back": hours_back
        }
        
        return JSONResponse(content=response_data)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching multiple mission tracks: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving track data: {str(e)}"
        )

