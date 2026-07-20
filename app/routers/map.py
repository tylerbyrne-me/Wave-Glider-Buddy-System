"""
API endpoints for mission map visualization.

Provides endpoints to retrieve telemetry data for map display
and generate KML files for Google Maps/Earth export.
"""

from typing import Optional, List
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, Query, HTTPException, status, Request
from fastapi.responses import JSONResponse, Response
import logging
import math
import asyncio
import re
import pandas as pd
import httpx

from ..core.auth import get_current_active_user, get_current_admin_user, require_platform_access
from ..core import models
from ..core.geo.map_utils import prepare_track_points, generate_kml_from_track_points, get_track_bounds
from ..core.geo import weather_map_cache
from ..core.data.processors import preprocess_telemetry_df
from ..core.data.data_service import get_data_service
from ..core.slocum_cache_service import (
    get_cached_or_fetch_dashboard_df,
    get_cached_or_fetch_bundle_df,
    parse_slocum_time_window,
    slice_processed_df,
)
from ..core.slocum_mirror_service import dashboard_df_to_track_df
from ..core.slocum_checklist_autofill import latest_valid_waypoint
from ..core.slocum_overage_cache import OverageRangeError
from ..core.infra.feature_toggles import is_feature_enabled
from ..core.infra.error_handlers import handle_processing_error, handle_data_not_found, ErrorContext

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Map"])

# Slocum map reads from parquet mirror (no live ERDDAP on request path)
SLOCUM_MAP_REQUEST_TIMEOUT = 35
UTC_ISO_INPUT_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?Z$")


def _parse_iso_datetime(value: str, field_name: str) -> datetime:
    """Parse UTC ISO datetime string into timezone-aware UTC datetime."""
    normalized_value = value.strip()
    if not UTC_ISO_INPUT_PATTERN.fullmatch(normalized_value):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid {field_name}. Expected UTC ISO 8601 format: YYYY-MM-DDTHH:MM[:SS]Z."
        )
    try:
        parsed_dt = datetime.fromisoformat(normalized_value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid {field_name}. Expected UTC ISO 8601 format: YYYY-MM-DDTHH:MM[:SS]Z."
        ) from exc
    return parsed_dt.replace(tzinfo=timezone.utc)


async def _prepare_track_data(
    mission_id: str,
    hours_back: Optional[int],
    current_user: models.User,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
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
            hours_back=hours_back,
            start_date=start_date,
            end_date=end_date,
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


async def _prepare_slocum_track_data(
    dataset_id: str,
    time_start: Optional[str],
    time_end: Optional[str],
    current_user: models.User,
    max_points: int = 1000,
    *,
    hours_back: int = 72,
    is_historical: bool = False,
) -> dict:
    """
    Load Slocum track from the parquet mirror (dashboard bundle lat/lon), preprocess,
    and prepare track points for map display.

    Returns same shape as _prepare_track_data: track_points, point_count, bounds, source, error.
    """
    source_label = f"Mirror: {dataset_id}"
    try:
        use_date_range = bool(time_start and time_end)
        if use_date_range:
            time_start_str, time_end_str = time_start, time_end
        else:
            time_start_str, time_end_str, _ = parse_slocum_time_window(
                dataset_id, hours_back, is_historical, None, None
            )

        try:
            dashboard_df = await asyncio.wait_for(
                get_cached_or_fetch_dashboard_df(
                    dataset_id,
                    time_start_str,
                    time_end_str,
                    hours_back=hours_back,
                    is_historical=is_historical,
                    context="interactive",
                ),
                timeout=SLOCUM_MAP_REQUEST_TIMEOUT,
            )
        except OverageRangeError as err:
            return {
                "track_points": [],
                "point_count": 0,
                "bounds": None,
                "source": source_label,
                "current_waypoint": None,
                "error": str(err),
            }
        if dashboard_df is None or dashboard_df.empty:
            logger.warning(f"No Slocum mirror/overage data for dataset {dataset_id}")
            return {
                "track_points": [],
                "point_count": 0,
                "bounds": None,
                "source": source_label,
                "current_waypoint": None,
                "error": "No data available",
            }

        sliced = slice_processed_df(
            dashboard_df,
            hours_back=hours_back,
            use_date_range=use_date_range,
            time_start_str=time_start_str,
            time_end_str=time_end_str,
        )
        processed_df = dashboard_df_to_track_df(sliced if not sliced.empty else dashboard_df)
        if processed_df.empty:
            logger.warning(f"No valid Slocum track points after preprocessing for {dataset_id}")
            return {
                "track_points": [],
                "point_count": 0,
                "bounds": None,
                "source": source_label,
                "current_waypoint": None,
                "error": "No valid track points",
            }
        track_points = prepare_track_points(processed_df, max_points=max_points)
        bounds = get_track_bounds(track_points)
        current_waypoint = None
        try:
            checklist_df = await asyncio.wait_for(
                get_cached_or_fetch_bundle_df(
                    dataset_id,
                    "checklist",
                    time_start_str,
                    time_end_str,
                    hours_back=hours_back,
                    is_historical=is_historical,
                    context="interactive",
                ),
                timeout=SLOCUM_MAP_REQUEST_TIMEOUT,
            )
            if checklist_df is not None and not checklist_df.empty:
                sliced_checklist = slice_processed_df(
                    checklist_df,
                    hours_back=hours_back,
                    use_date_range=use_date_range,
                    time_start_str=time_start_str,
                    time_end_str=time_end_str,
                )
                wpt_src = sliced_checklist if not sliced_checklist.empty else checklist_df
                wpt_lat, wpt_lon = latest_valid_waypoint(wpt_src)
                if wpt_lat is not None and wpt_lon is not None:
                    current_waypoint = {"lat": wpt_lat, "lon": wpt_lon}
        except Exception as wpt_err:
            logger.debug(
                "Slocum waypoint lookup skipped for %s: %s",
                dataset_id,
                wpt_err,
            )
        return {
            "track_points": track_points,
            "point_count": len(track_points),
            "bounds": bounds,
            "source": source_label,
            "current_waypoint": current_waypoint,
            "error": None,
        }
    except asyncio.TimeoutError:
        logger.warning(f"Slocum mirror read timed out for dataset {dataset_id}")
        return {
            "track_points": [],
            "point_count": 0,
            "bounds": None,
            "source": source_label,
            "current_waypoint": None,
            "error": "Slocum data did not load in time. Try again later.",
        }
    except Exception as e:
        logger.error(f"Error preparing Slocum track for {dataset_id}: {e}", exc_info=True)
        return {
            "track_points": [],
            "point_count": 0,
            "bounds": None,
            "source": source_label,
            "current_waypoint": None,
            "error": str(e),
        }


@router.get("/api/map/telemetry/{mission_id}")
async def get_mission_track(
    mission_id: str,
    hours_back: Optional[int] = Query(72, ge=1, le=8760, description="Hours of history to retrieve"),
    start_date: Optional[str] = Query(None, description="Start time ISO 8601. Use with end_date for date range."),
    end_date: Optional[str] = Query(None, description="End time ISO 8601. Use with start_date for date range."),
    full_range: bool = Query(False, description="If true, return full mission range and ignore hours_back."),
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
        parsed_start_date: Optional[datetime] = None
        parsed_end_date: Optional[datetime] = None
        query_hours_back: Optional[int] = hours_back
        if full_range:
            query_hours_back = None
        elif start_date or end_date:
            if not start_date or not end_date:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Both start_date and end_date are required for date range mode."
                )
            parsed_start_date = _parse_iso_datetime(start_date, "start_date")
            parsed_end_date = _parse_iso_datetime(end_date, "end_date")
            if parsed_start_date > parsed_end_date:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="start_date must be before or equal to end_date."
                )
            query_hours_back = None
        logger.info(
            "Fetching track data for mission %s (hours_back=%s, start_date=%s, end_date=%s, full_range=%s)",
            mission_id,
            query_hours_back,
            parsed_start_date.isoformat() if parsed_start_date else None,
            parsed_end_date.isoformat() if parsed_end_date else None,
            full_range,
        )
        
        # Use shared helper function to prepare track data
        track_data = await _prepare_track_data(
            mission_id,
            query_hours_back,
            current_user,
            start_date=parsed_start_date,
            end_date=parsed_end_date,
            max_points=1000,
        )
        
        response_data = {
            "mission_id": mission_id,
            "track_points": track_data["track_points"],
            "point_count": track_data["point_count"],
            "bounds": track_data["bounds"],
            "hours_back": query_hours_back,
            "start_date": parsed_start_date.isoformat() if parsed_start_date else None,
            "end_date": parsed_end_date.isoformat() if parsed_end_date else None,
            "full_range": full_range,
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


@router.get("/api/map/slocum/telemetry/{dataset_id}")
async def get_slocum_mission_track(
    dataset_id: str,
    hours_back: Optional[int] = Query(24, ge=1, le=8760, description="Hours of history from now (used if time_start/time_end not set)"),
    time_start: Optional[str] = Query(None, description="Start time ISO 8601 (e.g. 2025-08-01T00:00:00Z)"),
    time_end: Optional[str] = Query(None, description="End time ISO 8601 (e.g. 2025-08-31T23:59:59Z)"),
    current_user: models.User = Depends(get_current_active_user),
    _slocum_access: models.User = Depends(require_platform_access("slocum")),
):
    """
    Get Slocum ERDDAP track points for map visualization.

    Provide either (time_start, time_end) or hours_back. If time_start/time_end
    are provided they take precedence; otherwise time range is derived from
    hours_back from now (UTC).

    Returns same response shape as Wave Glider /api/map/telemetry/{mission_id}.
    """
    if not is_feature_enabled("slocum_platform"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Slocum platform is disabled (feature_toggles.slocum_platform).",
        )
    now = datetime.now(timezone.utc)
    if time_start and time_end:
        t_start, t_end = time_start, time_end
    else:
        end_dt = now
        start_dt = now - timedelta(hours=hours_back or 72)
        t_end = end_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        t_start = start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        track_data = await _prepare_slocum_track_data(
            dataset_id, t_start if time_start and time_end else None,
            t_end if time_start and time_end else None,
            current_user, max_points=1000, hours_back=hours_back or 24,
        )
        response_data = {
            "mission_id": dataset_id,
            "dataset_id": dataset_id,
            "track_points": track_data["track_points"],
            "point_count": track_data["point_count"],
            "bounds": track_data["bounds"],
            "source": track_data["source"],
            "current_waypoint": track_data.get("current_waypoint"),
            "time_start": t_start,
            "time_end": t_end,
        }
        if track_data.get("error"):
            response_data["error"] = track_data["error"]
        return JSONResponse(content=response_data)
    except HTTPException:
        raise
    except Exception as e:
        raise handle_processing_error(
            operation="retrieving Slocum track data",
            error=e,
            resource=dataset_id,
            user_id=str(current_user.id) if current_user else None,
        )


@router.get("/api/map/slocum/kml/{dataset_id}")
async def get_slocum_mission_kml(
    dataset_id: str,
    hours_back: Optional[int] = Query(72, ge=1, le=8760, description="Hours of history from now"),
    time_start: Optional[str] = Query(None, description="Start time ISO 8601"),
    time_end: Optional[str] = Query(None, description="End time ISO 8601"),
    current_user: models.User = Depends(get_current_active_user),
    _slocum_access: models.User = Depends(require_platform_access("slocum")),
):
    """Generate a KML file for a Slocum ERDDAP dataset track."""
    if not is_feature_enabled("slocum_platform"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Slocum platform is disabled (feature_toggles.slocum_platform).",
        )
    now = datetime.now(timezone.utc)
    if time_start and time_end:
        t_start, t_end = time_start, time_end
    else:
        end_dt = now
        start_dt = now - timedelta(hours=hours_back or 72)
        t_end = end_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        t_start = start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        track_data = await _prepare_slocum_track_data(
            dataset_id, t_start if time_start and time_end else None,
            t_end if time_start and time_end else None,
            current_user, max_points=5000, hours_back=hours_back or 24,
        )
        if track_data.get("error") or not track_data["track_points"]:
            raise handle_data_not_found(
                data_type="Slocum telemetry",
                mission_id=dataset_id,
                context=ErrorContext(operation="generating Slocum KML", resource=dataset_id),
            )
        kml_content = generate_kml_from_track_points(
            track_data["track_points"],
            dataset_id,
            waypoint=track_data.get("current_waypoint"),
            resource_label="Dataset",
        )
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"slocum_{dataset_id}_track_{timestamp}.kml"
        return Response(
            content=kml_content,
            media_type="application/vnd.google-earth.kml+xml",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except HTTPException:
        raise
    except Exception as e:
        raise handle_processing_error(
            operation="generating Slocum KML file",
            error=e,
            resource=dataset_id,
            user_id=str(current_user.id) if current_user else None,
        )


@router.get("/api/map/kml/{mission_id}")
async def get_mission_kml(
    mission_id: str,
    hours_back: Optional[int] = Query(72, ge=1, le=8760, description="Hours of history to retrieve"),
    start_date: Optional[str] = Query(None, description="Start time ISO 8601. Use with end_date for date range."),
    end_date: Optional[str] = Query(None, description="End time ISO 8601. Use with start_date for date range."),
    full_range: bool = Query(False, description="If true, return full mission range and ignore hours_back."),
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
        parsed_start_date: Optional[datetime] = None
        parsed_end_date: Optional[datetime] = None
        query_hours_back: Optional[int] = hours_back
        if full_range:
            query_hours_back = None
        elif start_date or end_date:
            if not start_date or not end_date:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Both start_date and end_date are required for date range mode."
                )
            parsed_start_date = _parse_iso_datetime(start_date, "start_date")
            parsed_end_date = _parse_iso_datetime(end_date, "end_date")
            if parsed_start_date > parsed_end_date:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="start_date must be before or equal to end_date."
                )
            query_hours_back = None
        logger.info(
            "Generating KML for mission %s (hours_back=%s, start_date=%s, end_date=%s, full_range=%s)",
            mission_id,
            query_hours_back,
            parsed_start_date.isoformat() if parsed_start_date else None,
            parsed_end_date.isoformat() if parsed_end_date else None,
            full_range,
        )
        
        # Use shared helper function (with more points for KML export)
        track_data = await _prepare_track_data(
            mission_id,
            query_hours_back,
            current_user,
            start_date=parsed_start_date,
            end_date=parsed_end_date,
            max_points=5000,
        )
        
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
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
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
    hours_back: Optional[int] = Query(72, ge=1, le=8760, description="Hours of history to retrieve"),
    start_date: Optional[str] = Query(None, description="Start time ISO 8601. Use with end_date for date range."),
    end_date: Optional[str] = Query(None, description="End time ISO 8601. Use with start_date for date range."),
    full_range: bool = Query(False, description="If true, return full mission range and ignore hours_back."),
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
            from ..core.infra.error_handlers import handle_validation_error
            raise handle_validation_error(
                message="No valid mission IDs provided",
                field="mission_ids"
            )
        
        parsed_start_date: Optional[datetime] = None
        parsed_end_date: Optional[datetime] = None
        query_hours_back: Optional[int] = hours_back
        if full_range:
            query_hours_back = None
        elif start_date or end_date:
            if not start_date or not end_date:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Both start_date and end_date are required for date range mode."
                )
            parsed_start_date = _parse_iso_datetime(start_date, "start_date")
            parsed_end_date = _parse_iso_datetime(end_date, "end_date")
            if parsed_start_date > parsed_end_date:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="start_date must be before or equal to end_date."
                )
            query_hours_back = None
        logger.info(
            "Fetching tracks for %s missions: %s (hours_back=%s, start_date=%s, end_date=%s, full_range=%s)",
            len(mission_list),
            mission_list,
            query_hours_back,
            parsed_start_date.isoformat() if parsed_start_date else None,
            parsed_end_date.isoformat() if parsed_end_date else None,
            full_range,
        )
        
        # Fetch data for each mission using shared helper function
        tracks = {}
        
        # Process missions concurrently for better performance
        tasks = [
            _prepare_track_data(
                mission_id,
                query_hours_back,
                current_user,
                start_date=parsed_start_date,
                end_date=parsed_end_date,
                max_points=1000,
            )
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
            "hours_back": query_hours_back,
            "start_date": parsed_start_date.isoformat() if parsed_start_date else None,
            "end_date": parsed_end_date.isoformat() if parsed_end_date else None,
            "full_range": full_range,
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


def _require_weather_map_layers() -> None:
    if not is_feature_enabled("weather_map_layers"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Weather map layers are disabled (feature_toggles.weather_map_layers).",
        )


@router.get("/api/map/weather/manifest")
async def get_weather_map_manifest(
    current_user: models.User = Depends(get_current_active_user),
):
    """Return cached Open-Meteo manifest with union bbox and proxied om URLs."""
    _require_weather_map_layers()
    manifest = weather_map_cache.get_cached_manifest()
    if manifest is None:
        try:
            union_bbox = await weather_map_cache.compute_union_mission_bbox()
            upstream_manifest = await weather_map_cache.fetch_model_manifest_upstream()
            om_urls = weather_map_cache.resolve_om_urls_for_manifest(upstream_manifest)
            manifest = weather_map_cache.build_buddy_manifest(
                upstream_manifest, union_bbox, om_urls
            )
            weather_map_cache.write_buddy_manifest(manifest)
        except Exception as exc:
            logger.error("Failed to build weather map manifest: %s", exc, exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unable to load weather map manifest.",
            ) from exc
    return JSONResponse(content=manifest)


@router.api_route("/api/map/weather/om/{path:path}", methods=["GET", "HEAD"])
async def proxy_weather_map_om(
    path: str,
    request: Request,
    current_user: models.User = Depends(get_current_active_user),
):
    """Proxy Open-Meteo .om files through disk cache."""
    _require_weather_map_layers()
    range_header = request.headers.get("range")
    query_string = str(request.url.query)
    head_only = request.method == "HEAD"
    try:
        status_code, body, headers = await weather_map_cache.proxy_open_meteo_request(
            path, query_string, range_header, head_only=head_only
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail="Upstream weather map request failed.",
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Weather map upstream unavailable.",
        ) from exc

    if head_only:
        if "Content-Length" not in headers and body:
            headers["Content-Length"] = str(len(body))
        return Response(content=b"", status_code=status_code, headers=headers)

    return Response(content=body, status_code=status_code, headers=headers)


@router.get("/api/map/weather/cache/status")
async def get_weather_map_cache_status(
    current_user: models.User = Depends(get_current_active_user),
):
    """Return weather map disk cache statistics for debugging.

    Available to any active user when weather_map_layers is on; admins can
    inspect status even when the feature is disabled (stranded cache).
    """
    if not is_feature_enabled("weather_map_layers"):
        if current_user.role != models.UserRoleEnum.admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Weather map layers are disabled (feature_toggles.weather_map_layers).",
            )
    return JSONResponse(content=weather_map_cache.get_cache_status())


@router.post("/api/map/weather/cache/purge")
async def purge_weather_map_cache(
    force_all: bool = Query(False, description="Remove all cached responses, not only stale ones."),
    current_admin: models.User = Depends(get_current_admin_user),
):
    """Admin: purge stale/orphan weather map cache entries (or wipe the response cache)."""
    summary = weather_map_cache.purge_weather_cache(force_all=force_all, enforce_quota=True)
    logger.info(
        "Admin '%s' purged weather map cache (force_all=%s, removed=%s, freed_bytes=%s)",
        current_admin.username,
        force_all,
        summary.get("removed_files"),
        summary.get("freed_bytes"),
    )
    return summary


