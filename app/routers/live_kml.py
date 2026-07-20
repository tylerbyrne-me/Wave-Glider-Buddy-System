"""
API endpoints for live KML network links.

Provides endpoints to create and manage live KML tokens that Google Earth
can automatically update via NetworkLink mechanism. Supports Wave Glider
missions and Slocum datasets.
"""

from typing import Literal, Optional, List
from datetime import datetime, timezone
from types import SimpleNamespace
from fastapi import APIRouter, Depends, HTTPException, Response, Request
from pydantic import BaseModel, Field
import secrets
import logging
import hashlib
from email.utils import format_datetime as format_http_datetime

from ..core.auth import get_current_active_user, user_has_platform_access
from ..core import models
from ..core.infra.db import get_db_session, SQLModelSession
from ..core.infra.feature_toggles import is_feature_enabled
from ..core.geo.map_utils import prepare_track_points, generate_live_kml_with_track
from ..core.data.data_service import get_data_service
from ..config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Live KML"])

LiveKMLPlatform = Literal["wave_glider", "slocum"]


def generate_token() -> str:
    """Generate a secure random token for live KML access"""
    return secrets.token_urlsafe(32)


def calculate_expiration_date() -> datetime:
    """Calculate expiration date as Dec 31, 23:59:59 of current year in UTC"""
    current_year = datetime.now(timezone.utc).year
    return datetime(current_year, 12, 31, 23, 59, 59, tzinfo=timezone.utc)


def _token_platform(token_record: models.LiveKMLToken) -> str:
    return getattr(token_record, "platform", None) or "wave_glider"


def _resource_label(platform: str) -> str:
    return "Dataset" if platform == "slocum" else "Mission"


class CreateLiveKMLRequest(BaseModel):
    mission_ids: List[str] = Field(
        ...,
        description="Wave Glider mission IDs or Slocum dataset IDs (comma-stored as mission_ids)",
    )
    hours_back: int = 72
    description: Optional[str] = None
    platform: LiveKMLPlatform = "wave_glider"


@router.post("/api/kml/create_live")
async def create_live_kml_token(
    request: CreateLiveKMLRequest,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
    request_obj: Request = None
):
    """
    Create a live KML token for one or more Wave Glider missions or Slocum datasets.
    
    Returns a token that can be used to generate auto-updating KML files
    that Google Earth can subscribe to.
    """
    try:
        if not request.mission_ids or len(request.mission_ids) == 0:
            raise HTTPException(status_code=400, detail="At least one mission/dataset ID is required")

        if request.hours_back < 1 or request.hours_back > 8760:
            raise HTTPException(status_code=400, detail="hours_back must be between 1 and 8760")

        platform = request.platform or "wave_glider"
        if platform == "slocum":
            if not is_feature_enabled("slocum_platform"):
                raise HTTPException(
                    status_code=403,
                    detail="Slocum platform is disabled (feature_toggles.slocum_platform).",
                )
            if not user_has_platform_access(current_user, "slocum"):
                raise HTTPException(status_code=403, detail="Access to slocum is not permitted.")
        elif platform == "wave_glider":
            if not user_has_platform_access(current_user, "wave_glider"):
                raise HTTPException(status_code=403, detail="Access to wave glider is not permitted.")
        else:
            raise HTTPException(status_code=400, detail="platform must be wave_glider or slocum")

        resource_ids = [rid.strip() for rid in request.mission_ids if rid and str(rid).strip()]
        if not resource_ids:
            raise HTTPException(status_code=400, detail="At least one mission/dataset ID is required")

        token = generate_token()
        expires_at = calculate_expiration_date()

        token_record = models.LiveKMLToken(
            token=token,
            mission_ids=",".join(resource_ids),
            platform=platform,
            user_id=current_user.id,
            hours_back=request.hours_back,
            refresh_interval_minutes=settings.background_cache_refresh_interval_minutes,
            is_active=True,
            expires_at=expires_at,
            access_count=0,
            created_at=datetime.now(timezone.utc),
            created_by=current_user.id,
            description=request.description
        )

        session.add(token_record)
        session.commit()
        session.refresh(token_record)

        logger.info(
            "Created live KML token %s... platform=%s resources=%s",
            token[:8],
            platform,
            ", ".join(resource_ids),
        )

        if request_obj:
            base_url = str(request_obj.base_url).rstrip('/')
        else:
            base_url = settings.app_base_url.rstrip('/')

        network_link_kml = _generate_network_link_kml(token, resource_ids, base_url, platform=platform)

        return {
            "token": token,
            "network_link_kml": network_link_kml,
            "embed_url": f"/api/kml/live/{token}",
            "expires_at": expires_at.isoformat(),
            "mission_ids": resource_ids,
            "platform": platform,
            "hours_back": request.hours_back
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating live KML token: {e}")
        raise HTTPException(status_code=500, detail=f"Error creating token: {str(e)}")


async def _load_wave_glider_tracks(resource_ids: List[str], hours_back: int) -> List[tuple]:
    from ..core.data.processors import preprocess_telemetry_df

    all_track_points = []
    data_service = get_data_service()
    for mission_id in resource_ids:
        try:
            df, _source_path, _ = await data_service.load(
                "telemetry",
                mission_id,
                source_preference=None,
                custom_local_path=None,
                force_refresh=False,
                hours_back=hours_back,
            )
            df = preprocess_telemetry_df(df)
            track_points = prepare_track_points(df, max_points=2000)
            if track_points:
                all_track_points.append((mission_id, track_points))
        except Exception as e:
            logger.warning(f"Error loading data for mission {mission_id}: {e}")
            continue
    return all_track_points


async def _load_slocum_tracks(resource_ids: List[str], hours_back: int) -> List[tuple]:
    from ..routers.map import _prepare_slocum_track_data

    user_stub = SimpleNamespace(id=0, username="live_kml")
    all_track_points = []
    for dataset_id in resource_ids:
        try:
            track_data = await _prepare_slocum_track_data(
                dataset_id,
                None,
                None,
                user_stub,
                max_points=2000,
                hours_back=hours_back,
            )
            track_points = track_data.get("track_points") or []
            if track_points:
                all_track_points.append(
                    (dataset_id, track_points, track_data.get("current_waypoint"))
                )
            elif track_data.get("error"):
                logger.warning(
                    "Slocum live KML skip %s: %s",
                    dataset_id,
                    track_data["error"],
                )
        except Exception as e:
            logger.warning(f"Error loading Slocum data for dataset {dataset_id}: {e}")
            continue
    return all_track_points


@router.get("/api/kml/live/{token}")
async def get_live_kml(
    token: str,
    session: SQLModelSession = Depends(get_db_session),
    request_obj: Request = None
):
    """
    Serve live KML data for a given token.
    
    This endpoint is publicly accessible (no authentication required).
    Google Earth will call this endpoint periodically to fetch updated track data.
    """
    try:
        token_record = session.query(models.LiveKMLToken).filter(
            models.LiveKMLToken.token == token
        ).first()

        if not token_record:
            raise HTTPException(status_code=404, detail="Token not found")

        if not token_record.is_active:
            return _generate_error_kml("Token has been revoked")

        now = datetime.now(timezone.utc)
        expires_at = token_record.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if now > expires_at:
            return _generate_error_kml(f"Token expired on {expires_at.date()}")

        token_record.access_count += 1
        token_record.last_accessed_at = datetime.now(timezone.utc)
        session.commit()

        resource_ids = [rid.strip() for rid in token_record.mission_ids.split(',') if rid.strip()]
        platform = _token_platform(token_record)
        resource_label = _resource_label(platform)

        if platform == "slocum":
            all_track_points = await _load_slocum_tracks(resource_ids, token_record.hours_back)
        else:
            all_track_points = await _load_wave_glider_tracks(resource_ids, token_record.hours_back)

        if not all_track_points:
            return _generate_error_kml(f"No track data available for these {resource_label.lower()}s")

        kml_payload = generate_live_kml_with_track(
            all_track_points,
            token_record.description,
            resource_label=resource_label,
        )

        total_points = sum(len(entry[1]) for entry in all_track_points)
        refresh_secs = token_record.refresh_interval_minutes * 60

        now_utc = datetime.now(timezone.utc)
        bucket_secs = refresh_secs
        bucket_epoch = int(now_utc.timestamp()) // bucket_secs * bucket_secs
        bucket_start = datetime.fromtimestamp(bucket_epoch, tz=timezone.utc)

        debug_comment = (
            f"<!-- server_utc={now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')} "
            f"token={token[:8]}... platform={platform} hours_back={token_record.hours_back} "
            f"resources={len(all_track_points)} points={total_points} "
            f"cache_bucket_start={bucket_start.strftime('%Y-%m-%dT%H:%M:%SZ')} "
            f"refresh_seconds={refresh_secs} -->\n"
        )

        first_newline = kml_payload.index('\n')
        kml_content = kml_payload[:first_newline + 1] + debug_comment + kml_payload[first_newline + 1:]

        body_hash = hashlib.sha256(kml_content.encode("utf-8")).hexdigest()
        etag = f'W/"{token}-{bucket_epoch}-{body_hash[:16]}"'

        if request_obj is not None:
            inm = request_obj.headers.get("If-None-Match")
            if inm and inm == etag:
                logger.info(
                    "Live KML 304 Not Modified | token=%s bucket=%s",
                    token[:8], bucket_start.isoformat()
                )
                return Response(status_code=304)

        logger.info(
            "Live KML 200 | token=%s platform=%s resources=%d points=%d bucket=%s etag=%s",
            token[:8], platform, len(all_track_points), total_points, bucket_start.isoformat(), etag
        )

        return Response(
            content=kml_content,
            media_type="application/vnd.google-earth.kml+xml; charset=utf-8",
            headers={
                "Cache-Control": f"public, max-age={refresh_secs}",
                "ETag": etag,
                "Last-Modified": format_http_datetime(now_utc),
                "Content-Disposition": f'inline; filename="live_{platform}_{token[:8]}.kml"'
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
    session: SQLModelSession = Depends(get_db_session),
    request_obj: Request = None
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

        resource_ids = [rid.strip() for rid in token_record.mission_ids.split(',') if rid.strip()]
        platform = _token_platform(token_record)

        if request_obj:
            base_url = str(request_obj.base_url).rstrip('/')
        else:
            base_url = settings.app_base_url.rstrip('/')

        network_link_kml = _generate_network_link_kml(
            token, resource_ids, base_url, platform=platform
        )

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
            "platform": _token_platform(t),
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

        if token_record.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Not authorized to revoke this token")

        token_record.is_active = False
        session.commit()

        logger.info(f"Token {token[:8]}... revoked by user {current_user.id}")

        return {"message": "Token revoked successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error revoking token {token}: {e}")
        raise HTTPException(status_code=500, detail=f"Error revoking token: {str(e)}")


def _generate_network_link_kml(
    token: str,
    resource_ids: List[str],
    base_url: str | None = None,
    *,
    platform: str = "wave_glider",
) -> str:
    """Generate NetworkLink KML that Google Earth can use to subscribe to live updates"""
    if base_url is None:
        base_url = settings.app_base_url.rstrip('/')
    if platform == "slocum":
        short_names = ", ".join(resource_ids)
        link_name = f"Slocum Track - Live ({short_names})"
    else:
        short_names = ", ".join([f"m{mid}" for mid in resource_ids])
        link_name = f"Mission Track - Live ({short_names})"

    live_url = f"{base_url}/api/kml/live/{token}"

    return f'''<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <NetworkLink>
    <name>{link_name}</name>
    <description>Automatically updating track from {base_url}</description>
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
