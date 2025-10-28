"""
API endpoints for live KML network links.

Provides endpoints to create and manage live KML tokens that Google Earth
can automatically update via NetworkLink mechanism.
"""

from typing import Optional, List
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import secrets
import logging

from ..auth_utils import get_current_active_user
from ..core import models
from ..db import get_db_session, SQLModelSession
from ..core.map_utils import prepare_track_points, generate_live_kml_with_track
from ..config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Live KML"])


def generate_token() -> str:
    """Generate a secure random token for live KML access"""
    return secrets.token_urlsafe(32)


def calculate_expiration_date() -> datetime:
    """Calculate expiration date as Dec 31, 23:59:59 of current year"""
    current_year = datetime.now().year
    return datetime(current_year, 12, 31, 23, 59, 59, tzinfo=datetime.now().tzinfo)


class CreateLiveKMLRequest(BaseModel):
    mission_ids: List[str]
    hours_back: int = 72
    description: Optional[str] = None


@router.post("/api/kml/create_live")
async def create_live_kml_token(
    request: CreateLiveKMLRequest,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session)
):
    """
    Create a live KML token for one or more missions.
    
    Returns a token that can be used to generate auto-updating KML files
    that Google Earth can subscribe to.
    """
    try:
        # Validate mission IDs
        if not request.mission_ids or len(request.mission_ids) == 0:
            raise HTTPException(status_code=400, detail="At least one mission ID is required")
        
        # Validate hours_back
        if request.hours_back < 1 or request.hours_back > 8760:
            raise HTTPException(status_code=400, detail="hours_back must be between 1 and 8760")
        
        # Generate token
        token = generate_token()
        
        # Calculate expiration (Dec 31 of current year)
        expires_at = calculate_expiration_date()
        
        # Create database record
        token_record = models.LiveKMLToken(
            token=token,
            mission_ids=",".join(request.mission_ids),
            user_id=current_user.id,
            hours_back=request.hours_back,
            refresh_interval_minutes=settings.background_cache_refresh_interval_minutes,
            is_active=True,
            expires_at=expires_at,
            access_count=0,
            created_at=datetime.now(),
            created_by=current_user.id,
            description=request.description
        )
        
        session.add(token_record)
        session.commit()
        session.refresh(token_record)
        
        logger.info(f"Created live KML token {token[:8]}... for missions: {', '.join(request.mission_ids)}")
        
        # Generate network link KML file content
        network_link_kml = _generate_network_link_kml(token, request.mission_ids)
        
        return {
            "token": token,
            "network_link_kml": network_link_kml,
            "embed_url": f"/api/kml/live/{token}",
            "expires_at": expires_at.isoformat(),
            "mission_ids": request.mission_ids,
            "hours_back": request.hours_back
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating live KML token: {e}")
        raise HTTPException(status_code=500, detail=f"Error creating token: {str(e)}")


@router.get("/api/kml/live/{token}")
async def get_live_kml(
    token: str,
    session: SQLModelSession = Depends(get_db_session)
):
    """
    Serve live KML data for a given token.
    
    This endpoint is publicly accessible (no authentication required).
    Google Earth will call this endpoint periodically to fetch updated track data.
    """
    try:
        # Look up token
        token_record = session.query(models.LiveKMLToken).filter(
            models.LiveKMLToken.token == token
        ).first()
        
        if not token_record:
            raise HTTPException(status_code=404, detail="Token not found")
        
        # Check if token is active
        if not token_record.is_active:
            return _generate_error_kml("Token has been revoked")
        
        # Check if token has expired
        if datetime.now() > token_record.expires_at:
            return _generate_error_kml(f"Token expired on {token_record.expires_at.date()}")
        
        # Update access tracking
        token_record.access_count += 1
        token_record.last_accessed_at = datetime.now()
        session.commit()
        
        # Parse mission IDs
        mission_ids = token_record.mission_ids.split(',')
        
        # Import load_data_source inside function to avoid circular import
        from ..app import load_data_source
        from ..core.processors import preprocess_telemetry_df
        
        # Fetch data for all missions
        all_track_points = []
        for mission_id in mission_ids:
            try:
                # Load telemetry data
                df, source_path = await load_data_source(
                    "telemetry",
                    mission_id,
                    source_preference=None,
                    custom_local_path=None,
                    force_refresh=False,
                    hours_back=token_record.hours_back
                )
                
                # Preprocess data
                df = preprocess_telemetry_df(df)
                
                # Prepare track points
                track_points = prepare_track_points(df, max_points=2000)
                
                if track_points:
                    all_track_points.append((mission_id, track_points))
                    
            except Exception as e:
                logger.warning(f"Error loading data for mission {mission_id}: {e}")
                continue
        
        # Generate KML
        if not all_track_points:
            return _generate_error_kml("No track data available for these missions")
        
        kml_content = generate_live_kml_with_track(all_track_points, token_record.description)
        
        return Response(
            content=kml_content,
            media_type="application/vnd.google-earth.kml+xml",
            headers={
                "Cache-Control": f"public, max-age={token_record.refresh_interval_minutes * 60}",
                "Content-Disposition": f'inline; filename="mission_live_{token[:8]}.kml"'
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error serving live KML for token {token}: {e}")
        return _generate_error_kml(f"Error loading track data: {str(e)}")


@router.get("/api/kml/network_link/{token}")
async def get_network_link_file(
    token: str,
    session: SQLModelSession = Depends(get_db_session)
):
    """
    Download a NetworkLink KML file for the given token.
    
    This file can be opened in Google Earth to subscribe to the live feed.
    """
    try:
        token_record = session.query(models.LiveKMLToken).filter(
            models.LiveKMLToken.token == token
        ).first()
        
        if not token_record:
            raise HTTPException(status_code=404, detail="Token not found")
        
        mission_ids = token_record.mission_ids.split(',')
        network_link_kml = _generate_network_link_kml(token, mission_ids)
        
        return Response(
            content=network_link_kml,
            media_type="application/vnd.google-earth.kml+xml",
            headers={
                "Content-Disposition": f'attachment; filename="live_track_{token[:8]}.kml"'
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating network link file for token {token}: {e}")
        raise HTTPException(status_code=500, detail=f"Error generating network link: {str(e)}")


@router.get("/api/kml/tokens")
async def list_user_tokens(
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session)
):
    """List all live KML tokens for the current user"""
    try:
        tokens = session.query(models.LiveKMLToken).filter(
            models.LiveKMLToken.user_id == current_user.id
        ).order_by(models.LiveKMLToken.created_at.desc()).all()
        
        return [{
            "token": t.token,
            "mission_ids": t.mission_ids.split(','),
            "hours_back": t.hours_back,
            "expires_at": t.expires_at.isoformat(),
            "is_active": t.is_active,
            "access_count": t.access_count,
            "last_accessed_at": t.last_accessed_at.isoformat() if t.last_accessed_at else None,
            "created_at": t.created_at.isoformat(),
            "description": t.description
        } for t in tokens]
        
    except Exception as e:
        logger.error(f"Error listing tokens for user {current_user.id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error listing tokens: {str(e)}")


@router.delete("/api/kml/tokens/{token}")
async def revoke_token(
    token: str,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session)
):
    """Revoke a live KML token (mark as inactive)"""
    try:
        token_record = session.query(models.LiveKMLToken).filter(
            models.LiveKMLToken.token == token
        ).first()
        
        if not token_record:
            raise HTTPException(status_code=404, detail="Token not found")
        
        # Check ownership
        if token_record.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Not authorized to revoke this token")
        
        # Revoke token
        token_record.is_active = False
        session.commit()
        
        logger.info(f"Token {token[:8]}... revoked by user {current_user.id}")
        
        return {"message": "Token revoked successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error revoking token {token}: {e}")
        raise HTTPException(status_code=500, detail=f"Error revoking token: {str(e)}")


def _generate_network_link_kml(token: str, mission_ids: List[str]) -> str:
    """Generate NetworkLink KML that Google Earth can use to subscribe to live updates"""
    mission_names = ", ".join([f"m{mid}" for mid in mission_ids])
    
    # For localhost testing, use full URL
    # In production, this should use the actual server URL
    live_url = f"http://localhost:8000/api/kml/live/{token}"
    
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <NetworkLink>
    <name>Mission Track - Live ({mission_names})</name>
    <description>Automatically updating mission track. Server must be running on http://localhost:8000</description>
    <refreshVisibility>1</refreshVisibility>
    <flyToView>0</flyToView>
    <Link>
      <href>{live_url}</href>
      <refreshMode>onInterval</refreshMode>
      <refreshInterval>600</refreshInterval>
      <viewRefreshMode>never</viewRefreshMode>
    </Link>
  </NetworkLink>
</kml>'''


def _generate_error_kml(message: str) -> Response:
    """Generate KML with an error message"""
    error_kml = f'''<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Error</name>
    <description>{message}</description>
    <Placemark>
      <name>Error</name>
      <description>{message}</description>
      <Point>
        <coordinates>0,0,0</coordinates>
      </Point>
    </Placemark>
  </Document>
</kml>'''
    
    return Response(
        content=error_kml,
        media_type="application/vnd.google-earth.kml+xml"
    )

