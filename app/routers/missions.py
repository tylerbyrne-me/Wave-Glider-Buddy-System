from fastapi import APIRouter, Depends, HTTPException, status, Request, UploadFile, File, Query
from fastapi.responses import HTMLResponse
from typing import List, Optional, Dict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import re
from sqlmodel import select
from sqlalchemy import or_
from ..core import models
from ..core.db import get_db_session, SQLModelSession
from ..core.auth import get_current_active_user, get_current_admin_user, get_optional_current_user
import shutil
import logging
from app.core.templates import templates
from app.config import settings
from ..core.template_context import get_template_context


router = APIRouter(tags=["Missions"])
logger = logging.getLogger(__name__)

# Approval status constants
APPROVAL_PENDING = "pending"
APPROVAL_APPROVED = "approved"
APPROVAL_REJECTED = "rejected"

# --- Mission Media Helpers ---
ALLOWED_IMAGE_TYPES = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
}
ALLOWED_VIDEO_TYPES = {
    "video/mp4": "mp4",
    "video/quicktime": "mov",
    "video/x-msvideo": "avi",
}


def _sanitize_path_segment(value: str) -> str:
    """Make a safe path segment for filesystem storage."""
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", value.strip())
    return safe or "unknown"


def _get_project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _get_mission_media_root() -> Path:
    configured_root = Path(settings.mission_media_root_path)
    if configured_root.is_absolute():
        return configured_root
    return _get_project_root() / configured_root


def _normalize_file_url(file_path: str) -> str:
    """Normalize file path to URL for static file serving."""
    normalized_path = file_path.replace(chr(92), "/")
    if normalized_path.startswith("web/static/"):
        normalized_path = normalized_path.replace("web/static/", "static/", 1)
    elif normalized_path.startswith("web\\static\\"):
        normalized_path = normalized_path.replace("web\\static\\", "static/", 1)
    if not normalized_path.startswith("static/"):
        return f"/{normalized_path}"
    return f"/{normalized_path}"


def _build_media_read(media: models.MissionMedia) -> models.MissionMediaRead:
    file_url = _normalize_file_url(media.file_path)
    thumbnail_url = _normalize_file_url(media.thumbnail_path) if media.thumbnail_path else None
    return models.MissionMediaRead(
        id=media.id,
        mission_id=media.mission_id,
        media_type=media.media_type,
        file_name=media.file_name,
        file_size=media.file_size,
        mime_type=media.mime_type,
        caption=media.caption,
        operation_type=media.operation_type,
        uploaded_by_username=media.uploaded_by_username,
        uploaded_at_utc=media.uploaded_at_utc,
        approval_status=media.approval_status,
        approved_by_username=media.approved_by_username,
        approved_at_utc=media.approved_at_utc,
        thumbnail_url=thumbnail_url,
        file_url=file_url,
        display_order=media.display_order,
        is_featured=media.is_featured,
    )


def _get_user_role_value(user: models.User) -> str:
    return user.role.value if hasattr(user.role, "value") else str(user.role)


def _create_announcement(
    session: SQLModelSession,
    content: str,
    created_by_username: str,
    target_roles: Optional[List[str]] = None,
    target_usernames: Optional[List[str]] = None,
    announcement_type: str = "system",
) -> None:
    db_announcement = models.Announcement(
        content=content,
        created_by_username=created_by_username,
        announcement_type=announcement_type,
        target_roles=",".join(target_roles) if target_roles else None,
        target_usernames=",".join(target_usernames) if target_usernames else None,
    )
    session.add(db_announcement)
    session.commit()

# --- HTML/Admin Page ---
@router.get("/admin/mission_overviews.html", response_class=HTMLResponse)
async def get_admin_mission_overviews_page(
    request: Request,
    current_user: Optional[models.User] = Depends(get_optional_current_user)
):
    username_for_log = (
        current_user.username if current_user else "anonymous/unauthenticated"
    )
    logger.info(
        f"User '{username_for_log}' accessing /admin/mission_overviews.html. JS will verify admin role."
    )
    return templates.TemplateResponse(
        "admin_mission_overviews.html",
        get_template_context(request=request, current_user=current_user),
    )

# --- Helper ---
async def _get_mission_info(
    mission_id: str,
    session: SQLModelSession,
    current_user: models.User,
) -> models.MissionInfoResponse:
    overview = session.get(models.MissionOverview, mission_id)
    goals_stmt = select(models.MissionGoal).where(models.MissionGoal.mission_id == mission_id).order_by(models.MissionGoal.id)
    goals = session.exec(goals_stmt).all()
    notes_stmt = select(models.MissionNote).where(models.MissionNote.mission_id == mission_id).order_by(models.MissionNote.created_at_utc.desc())
    notes = session.exec(notes_stmt).all()

    media_stmt = select(models.MissionMedia).where(models.MissionMedia.mission_id == mission_id)
    if _get_user_role_value(current_user) != models.UserRoleEnum.admin.value:
        media_stmt = media_stmt.where(models.MissionMedia.approval_status == APPROVAL_APPROVED)
    else:
        media_stmt = media_stmt.where(models.MissionMedia.approval_status.in_([APPROVAL_APPROVED, APPROVAL_PENDING]))
    media_stmt = media_stmt.order_by(
        models.MissionMedia.display_order.asc(),
        models.MissionMedia.uploaded_at_utc.desc(),
    )
    media_items = session.exec(media_stmt).all()
    media = [_build_media_read(item) for item in media_items]
    
    # Get Sensor Tracker deployment data
    # Try both full mission_id and mission base (e.g., "1070-m216" and "m216")
    mission_base = mission_id.split('-')[-1] if '-' in mission_id else mission_id
    sensor_tracker_deployment = session.exec(
        select(models.SensorTrackerDeployment).where(
            or_(
                models.SensorTrackerDeployment.mission_id == mission_id,
                models.SensorTrackerDeployment.mission_id == mission_base
            )
        )
    ).first()
    
    # If we found a deployment, load its instruments
    instruments = []
    if sensor_tracker_deployment:
        instruments = session.exec(
            select(models.MissionInstrument).where(
                or_(
                    models.MissionInstrument.mission_id == mission_id,
                    models.MissionInstrument.mission_id == mission_base
                )
            )
        ).all()
    
    return models.MissionInfoResponse(
        overview=overview,
        goals=goals,
        notes=notes,
        sensor_tracker_deployment=sensor_tracker_deployment,
        sensor_tracker_instruments=instruments,
        media=media,
    )

# --- API Endpoints ---
@router.post("/api/missions/{mission_id}/overview/upload_plan", response_model=dict)
async def upload_mission_plan_file(
    mission_id: str,
    file: UploadFile = File(...),
    current_admin: models.User = Depends(get_current_admin_user),
):
    logger.info(f"Admin '{current_admin.username}' uploading plan for mission '{mission_id}'. Filename: {file.filename}")
    allowed_content_types = [
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ]
    if file.content_type not in allowed_content_types:
        raise HTTPException(status_code=400, detail="Invalid file type. Only PDF, DOC, and DOCX are allowed.")
    
    file_extension = Path(file.filename).suffix
    safe_filename = f"{mission_id}_plan{file_extension}"
    # Fix path calculation - go up two levels from app/routers/ to project root, then to web/static/mission_plans
    mission_plans_dir = Path(__file__).resolve().parent.parent.parent / "web" / "static" / "mission_plans"
    
    # Create the directory if it doesn't exist
    mission_plans_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Mission plans directory: {mission_plans_dir}")
    
    file_path = mission_plans_dir / safe_filename
    logger.info(f"Attempting to save file to: {file_path}")
    
    try:
        # Read the file content first
        content = await file.read()
        logger.info(f"Read {len(content)} bytes from uploaded file")
        
        # Write the content to file
        with file_path.open("wb") as buffer:
            buffer.write(content)
        
        # Verify the file was actually written
        if not file_path.exists():
            raise Exception("File was not created on disk")
        
        file_size = file_path.stat().st_size
        if file_size != len(content):
            raise Exception(f"File size mismatch: expected {len(content)} bytes, got {file_size} bytes")
        
        logger.info(f"Mission plan for '{mission_id}' successfully saved to '{file_path}' ({file_size} bytes)")
        
    except Exception as e:
        logger.error(f"Failed to save mission plan file: {e}")
        # Clean up partial file if it exists
        if file_path.exists():
            file_path.unlink()
            logger.info(f"Removed partial file: {file_path}")
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")
    finally:
        # Ensure file is closed
        await file.close()
    
    file_url = f"/static/mission_plans/{safe_filename}"
    logger.info(f"Mission plan for '{mission_id}' saved successfully. URL: {file_url}")
    return {"file_url": file_url}

@router.get("/api/missions/{mission_id}/overview/upload_status", response_model=dict)
async def check_mission_plan_upload_status(
    mission_id: str,
    current_admin: models.User = Depends(get_current_admin_user),
):
    """Check if a mission plan file exists and get its details."""
    # Fix path calculation - go up two levels from app/routers/ to project root, then to web/static/mission_plans
    mission_plans_dir = Path(__file__).resolve().parent.parent.parent / "web" / "static" / "mission_plans"
    
    # Check for common file extensions
    extensions = ['.pdf', '.doc', '.docx']
    found_files = []
    
    for ext in extensions:
        file_path = mission_plans_dir / f"{mission_id}_plan{ext}"
        if file_path.exists():
            stat = file_path.stat()
            found_files.append({
                "filename": file_path.name,
                "path": str(file_path),
                "size": stat.st_size,
                "modified": stat.st_mtime,
                "extension": ext
            })
    
    return {
        "mission_id": mission_id,
        "directory": str(mission_plans_dir),
        "directory_exists": mission_plans_dir.exists(),
        "files_found": found_files,
        "total_files": len(found_files)
    }

@router.get("/api/missions/{mission_id}/info", response_model=models.MissionInfoResponse)
async def get_mission_info_api(
    mission_id: str,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session)
):
    logger.info(f"User '{current_user.username}' requesting info for mission '{mission_id}'.")
    return await _get_mission_info(mission_id, session, current_user)


@router.post("/api/missions/{mission_id}/media/upload", response_model=models.MissionMediaRead)
async def upload_mission_media(
    mission_id: str,
    file: UploadFile = File(...),
    caption: Optional[str] = Query(None),
    operation_type: Optional[str] = Query(None, description="deployment or recovery"),
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """Upload mission media (photo/video). Pilots and admins allowed."""
    logger.info(f"User '{current_user.username}' uploading media for mission '{mission_id}': {file.filename}")

    if file.content_type in ALLOWED_IMAGE_TYPES:
        media_type = "photo"
        max_size = settings.mission_media_max_image_size_mb * 1024 * 1024
    elif file.content_type in ALLOWED_VIDEO_TYPES:
        media_type = "video"
        max_size = settings.mission_media_max_video_size_mb * 1024 * 1024
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed images: {', '.join(ALLOWED_IMAGE_TYPES.keys())}; videos: {', '.join(ALLOWED_VIDEO_TYPES.keys())}",
        )

    content = await file.read()
    file_size = len(content)
    if file_size > max_size:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size is {max_size / 1024 / 1024:.0f}MB.",
        )

    safe_mission_id = _sanitize_path_segment(mission_id)
    media_root = _get_mission_media_root()
    subdir = "photos" if media_type == "photo" else "videos"
    target_dir = media_root / safe_mission_id / subdir
    target_dir.mkdir(parents=True, exist_ok=True)

    extension = Path(file.filename).suffix.lower()
    if not extension:
        extension = f".{(ALLOWED_IMAGE_TYPES | ALLOWED_VIDEO_TYPES).get(file.content_type, 'bin')}"

    safe_filename = f"{uuid4().hex}_{int(datetime.now(timezone.utc).timestamp())}{extension}"
    file_path = target_dir / safe_filename

    try:
        with file_path.open("wb") as buffer:
            buffer.write(content)
    except Exception as exc:
        logger.error(f"Failed to save mission media file: {exc}", exc_info=True)
        if file_path.exists():
            file_path.unlink()
        raise HTTPException(status_code=500, detail="Failed to save file.")
    finally:
        await file.close()

    project_root = _get_project_root()
    try:
        relative_path = file_path.relative_to(project_root)
        stored_path = str(relative_path).replace("\\", "/")
    except ValueError:
        stored_path = str(file_path)

    approval_status = APPROVAL_APPROVED
    approved_by_username = None
    approved_at_utc = None
    if _get_user_role_value(current_user) != models.UserRoleEnum.admin.value:
        approval_status = APPROVAL_PENDING
    else:
        approved_by_username = current_user.username
        approved_at_utc = datetime.now(timezone.utc)

    media = models.MissionMedia(
        mission_id=mission_id,
        media_type=media_type,
        file_path=stored_path,
        file_name=file.filename,
        file_size=file_size,
        mime_type=file.content_type,
        caption=caption,
        operation_type=operation_type,
        uploaded_by_username=current_user.username,
        approval_status=approval_status,
        approved_by_username=approved_by_username,
        approved_at_utc=approved_at_utc,
    )

    session.add(media)
    session.commit()
    session.refresh(media)

    if approval_status == APPROVAL_PENDING:
        _create_announcement(
            session=session,
            content=(
                f"Media upload pending approval for mission '{mission_id}' "
                f"by {current_user.username}: {file.filename}"
            ),
            created_by_username=current_user.username,
            target_roles=[models.UserRoleEnum.admin.value],
            target_usernames=[current_user.username],
        )

    return _build_media_read(media)


@router.get("/api/missions/{mission_id}/media", response_model=List[models.MissionMediaRead])
async def list_mission_media(
    mission_id: str,
    media_type: Optional[str] = Query(None, description="photo or video"),
    operation_type: Optional[str] = Query(None, description="deployment or recovery"),
    include_pending: bool = Query(False),
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """List mission media items. Pilots and admins allowed."""
    statement = select(models.MissionMedia).where(models.MissionMedia.mission_id == mission_id)
    if media_type:
        statement = statement.where(models.MissionMedia.media_type == media_type)
    if operation_type:
        statement = statement.where(models.MissionMedia.operation_type == operation_type)
    if _get_user_role_value(current_user) == models.UserRoleEnum.admin.value and include_pending:
        statement = statement.where(models.MissionMedia.approval_status.in_([APPROVAL_APPROVED, APPROVAL_PENDING]))
    else:
        statement = statement.where(models.MissionMedia.approval_status == APPROVAL_APPROVED)
    statement = statement.order_by(
        models.MissionMedia.display_order.asc(),
        models.MissionMedia.uploaded_at_utc.desc(),
    )

    media_items = session.exec(statement).all()
    return [_build_media_read(item) for item in media_items]


@router.get("/api/missions/{mission_id}/media/{media_id}", response_model=models.MissionMediaRead)
async def get_mission_media(
    mission_id: str,
    media_id: int,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """Get a single media item. Pilots and admins allowed."""
    media = session.get(models.MissionMedia, media_id)
    if not media or media.mission_id != mission_id:
        raise HTTPException(status_code=404, detail="Mission media not found.")
    if (
        _get_user_role_value(current_user) != models.UserRoleEnum.admin.value
        and media.approval_status != APPROVAL_APPROVED
    ):
        raise HTTPException(status_code=403, detail="Media is pending approval.")
    return _build_media_read(media)


@router.put("/api/missions/{mission_id}/media/{media_id}", response_model=models.MissionMediaRead)
async def update_mission_media(
    mission_id: str,
    media_id: int,
    update: models.MissionMediaUpdate,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """Update mission media metadata. Pilots can edit own uploads; admins can edit any."""
    media = session.get(models.MissionMedia, media_id)
    if not media or media.mission_id != mission_id:
        raise HTTPException(status_code=404, detail="Mission media not found.")

    if current_user.role == models.UserRoleEnum.pilot and media.uploaded_by_username != current_user.username:
        raise HTTPException(status_code=403, detail="Pilots can only edit their own uploads.")

    update_data = update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(media, key, value)

    session.add(media)
    session.commit()
    session.refresh(media)
    return _build_media_read(media)


@router.put("/api/missions/{mission_id}/media/{media_id}/approve", response_model=models.MissionMediaRead)
async def approve_mission_media(
    mission_id: str,
    media_id: int,
    current_admin: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """Approve mission media (admin only)."""
    media = session.get(models.MissionMedia, media_id)
    if not media or media.mission_id != mission_id:
        raise HTTPException(status_code=404, detail="Mission media not found.")

    media.approval_status = APPROVAL_APPROVED
    media.approved_by_username = current_admin.username
    media.approved_at_utc = datetime.now(timezone.utc)
    session.add(media)
    session.commit()
    session.refresh(media)

    _create_announcement(
        session=session,
        content=(
            f"Your media upload for mission '{mission_id}' "
            f"was approved by {current_admin.username}: {media.file_name}"
        ),
        created_by_username=current_admin.username,
        target_usernames=[media.uploaded_by_username],
    )

    return _build_media_read(media)


@router.put("/api/missions/{mission_id}/media/{media_id}/reject", response_model=models.MissionMediaRead)
async def reject_mission_media(
    mission_id: str,
    media_id: int,
    current_admin: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """Reject mission media (admin only)."""
    media = session.get(models.MissionMedia, media_id)
    if not media or media.mission_id != mission_id:
        raise HTTPException(status_code=404, detail="Mission media not found.")

    media.approval_status = APPROVAL_REJECTED
    media.approved_by_username = current_admin.username
    media.approved_at_utc = datetime.now(timezone.utc)
    session.add(media)
    session.commit()
    session.refresh(media)

    _create_announcement(
        session=session,
        content=(
            f"Your media upload for mission '{mission_id}' "
            f"was rejected by {current_admin.username}: {media.file_name}"
        ),
        created_by_username=current_admin.username,
        target_usernames=[media.uploaded_by_username],
    )

    return _build_media_read(media)


@router.delete("/api/missions/{mission_id}/media/{media_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mission_media(
    mission_id: str,
    media_id: int,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """Delete mission media. Pilots can delete own uploads; admins can delete any."""
    media = session.get(models.MissionMedia, media_id)
    if not media or media.mission_id != mission_id:
        raise HTTPException(status_code=404, detail="Mission media not found.")

    if current_user.role == models.UserRoleEnum.pilot and media.uploaded_by_username != current_user.username:
        raise HTTPException(status_code=403, detail="Pilots can only delete their own uploads.")

    project_root = _get_project_root()
    media_root = _get_mission_media_root().resolve()
    file_path = Path(media.file_path)
    if not file_path.is_absolute():
        file_path = (project_root / file_path).resolve()
    else:
        file_path = file_path.resolve()
    thumbnail_path = None
    if media.thumbnail_path:
        thumbnail_path = Path(media.thumbnail_path)
        if not thumbnail_path.is_absolute():
            thumbnail_path = (project_root / thumbnail_path).resolve()
        else:
            thumbnail_path = thumbnail_path.resolve()

    def _safe_delete(path: Path) -> None:
        try:
            path.relative_to(media_root)
        except ValueError:
            logger.warning(f"Skipping delete for file outside media root: {path}")
            return
        if path.exists():
            path.unlink()

    _safe_delete(file_path)
    if thumbnail_path:
        _safe_delete(thumbnail_path)

    session.delete(media)
    session.commit()
    return

@router.put("/api/missions/{mission_id}/overview", response_model=models.MissionOverview)
async def create_or_update_mission_overview(
    mission_id: str,
    overview_in: models.MissionOverviewUpdate,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session)
):
    logger.info(f"User '{current_user.username}' updating overview for mission '{mission_id}'.")
    logger.info(f"API: Received sensor card config: {overview_in.enabled_sensor_cards}")
    db_overview = session.get(models.MissionOverview, mission_id)
    if not db_overview:
        db_overview = models.MissionOverview(mission_id=mission_id, **overview_in.model_dump(exclude_unset=True))
    else:
        update_data = overview_in.model_dump(exclude_unset=True)
        logger.info(f"API: Updating mission overview with data: {update_data}")
        for key, value in update_data.items():
            setattr(db_overview, key, value)
        db_overview.updated_at_utc = datetime.now(timezone.utc)
    session.add(db_overview)
    session.commit()
    session.refresh(db_overview)
    return db_overview

@router.post("/api/missions/{mission_id}/goals", response_model=models.MissionGoal, status_code=status.HTTP_201_CREATED)
async def create_mission_goal(
    mission_id: str,
    goal_in: models.MissionGoalCreate,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session)
):
    logger.info(f"User '{current_user.username}' creating goal for mission '{mission_id}': {goal_in.description}")
    db_goal = models.MissionGoal(mission_id=mission_id, description=goal_in.description)
    session.add(db_goal)
    session.commit()
    session.refresh(db_goal)
    return db_goal

@router.put("/api/missions/goals/{goal_id}", response_model=models.MissionGoal)
async def update_mission_goal(
    goal_id: int,
    goal_update: models.MissionGoalUpdate,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session)
):
    db_goal = session.get(models.MissionGoal, goal_id)
    if not db_goal:
        raise HTTPException(status_code=404, detail="Mission goal not found.")
    update_data = goal_update.model_dump(exclude_unset=True)
    if "is_completed" in update_data:
        db_goal.is_completed = update_data["is_completed"]
        if db_goal.is_completed:
            db_goal.completed_by_username = current_user.username
            db_goal.completed_at_utc = datetime.now(timezone.utc)
        else:
            db_goal.completed_by_username = None
            db_goal.completed_at_utc = None
    if "description" in update_data and update_data["description"] is not None:
        db_goal.description = update_data["description"]
    session.add(db_goal)
    session.commit()
    session.refresh(db_goal)
    logger.info(f"User '{current_user.username}' updated goal ID {goal_id}.")
    return db_goal

@router.delete("/api/missions/goals/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mission_goal(
    goal_id: int,
    current_admin: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session)
):
    db_goal = session.get(models.MissionGoal, goal_id)
    if not db_goal:
        raise HTTPException(status_code=404, detail="Mission goal not found.")
    session.delete(db_goal)
    session.commit()
    logger.info(f"Admin '{current_admin.username}' deleted goal ID {goal_id}.")
    return

@router.post("/api/missions/{mission_id}/goals/{goal_id}/toggle", response_model=models.MissionGoal)
async def toggle_mission_goal_completion(
    mission_id: str,
    goal_id: int,
    goal_toggle: models.MissionGoalToggle,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    db_goal = session.get(models.MissionGoal, goal_id)
    if not db_goal:
        raise HTTPException(status_code=404, detail="Mission goal not found.")
    if db_goal.mission_id != mission_id:
        raise HTTPException(
            status_code=400,
            detail=f"Goal ID {goal_id} does not belong to mission '{mission_id}'.",
        )
    logger.info(
        f"User '{current_user.username}' toggling goal ID {goal_id} to completed={goal_toggle.is_completed}."
    )
    db_goal.is_completed = goal_toggle.is_completed
    if goal_toggle.is_completed:
        db_goal.completed_by_username = current_user.username
        db_goal.completed_at_utc = datetime.now(timezone.utc)
    else:
        db_goal.completed_by_username = None
        db_goal.completed_at_utc = None
    session.add(db_goal)
    session.commit()
    session.refresh(db_goal)
    return db_goal

@router.post("/api/missions/{mission_id}/notes", response_model=models.MissionNote, status_code=status.HTTP_201_CREATED)
async def create_mission_note(
    mission_id: str,
    note_in: models.MissionNoteCreate,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session)
):
    logger.info(f"User '{current_user.username}' creating note for mission '{mission_id}'.")
    db_note = models.MissionNote(
        mission_id=mission_id,
        content=note_in.content,
        created_by_username=current_user.username
    )
    session.add(db_note)
    session.commit()
    session.refresh(db_note)
    return db_note

@router.delete("/api/missions/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mission_note(
    note_id: int,
    current_admin: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session)
):
    db_note = session.get(models.MissionNote, note_id)
    if not db_note:
        raise HTTPException(status_code=404, detail="Mission note not found.")
    session.delete(db_note)
    session.commit()
    logger.info(f"Admin '{current_admin.username}' deleted note ID {note_id}.")
    return 

@router.get("/api/available_missions", response_model=List[str])
async def get_available_missions(
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session)
):
    """Get list of active real-time missions."""
    # Filter out empty strings and None values
    missions = [m for m in settings.active_realtime_missions if m and m.strip()]
    return missions


@router.get("/api/available_all_missions", response_model=Dict[str, List[str]])
async def get_all_available_missions(
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session)
):
    """
    Get list of all missions (active + historical).
    Returns a dictionary with 'active' and 'historical' keys.
    """
    # Get active missions
    active_missions = [m for m in settings.active_realtime_missions if m and m.strip()]
    
    # Get historical missions
    historical_missions = []
    try:
        historical_missions = await get_available_historical_missions(current_user, session)
    except Exception as e:
        logger.error(f"Error fetching historical missions for all missions endpoint: {e}")
        historical_missions = []
    
    return {
        "active": active_missions,
        "historical": historical_missions
    }


@router.get("/api/available_historical_missions", response_model=List[str])
async def get_available_historical_missions(
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session)
):
    """
    Get list of historical/past missions by checking the remote server.
    """
    from ..core import models
    from ..config import settings
    import httpx
    
    # Check remote server for available past missions
    base_remote_url = settings.remote_data_url.rstrip("/")
    past_missions_url = f"{base_remote_url}/output_past_missions/"
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(past_missions_url)
            logger.info(f"Historical missions URL: {past_missions_url}")
            logger.info(f"Response status: {response.status_code}")
            
            if response.status_code == 200:
                # Parse HTML to extract mission folder names
                # The directory listing format is: <m169-C34166NS/> or <m170-C34164NS/>
                import re
                
                # Log first part of response for debugging
                response_preview = response.text[:1000]
                logger.info(f"Response preview (first 1000 chars): {response_preview}")
                
                # Pattern to match folder names in angle brackets like <m169-C34166NS/>
                # The actual format from the server is: <m169-C34166NS/>
                # Try multiple patterns to handle different HTML structures
                patterns = [
                    r'<([mM]\d+-[A-Z0-9]+)/?>',  # <m169-C34166NS/> - matches m###-C##### format
                    r'<([mM]\d+-[^>]+)/?>',      # <m169-C34166NS/> - more general
                    r'<([mM]\d+[^>]*)/?>',       # <m169...> - catch-all for mission folders
                    r'href=["\']([mM]\d+[^"\']*)["\']',  # href="m169-C34166NS"
                ]
                
                all_matches = set()
                for pattern in patterns:
                    matches = re.findall(pattern, response.text, re.IGNORECASE)
                    all_matches.update(matches)
                    logger.debug(f"Pattern {pattern} found {len(matches)} matches: {matches[:5]}")
                
                # Extract mission IDs from folder names and convert to "1071-m169" format
                # Folder names are like "m169-C34166NS" - we want to extract "m169" and find "1071 m169" in mapping
                mission_ids = set()
                excluded = {'parent', 'directory', 'index', '..', '.', '', 'private'}
                
                logger.info(f"Total matches found: {len(all_matches)}, matches: {list(all_matches)[:10]}")
                for match in all_matches:
                    # Remove trailing slash if present
                    folder_name = match.strip().rstrip('/')
                    logger.info(f"Processing folder name: {folder_name}")
                    
                    # Skip excluded entries
                    if folder_name.lower() in excluded:
                        logger.info(f"Skipping excluded entry: {folder_name}")
                        continue
                    
                    # Extract mission ID (m###) from folder name (m###-C#####)
                    # Pattern: starts with 'm' followed by digits
                    mission_match = re.match(r'^([mM]\d+)', folder_name, re.IGNORECASE)
                    if mission_match:
                        mission_base = mission_match.group(1).lower()  # e.g., "m169"
                        
                        # Find the mapping key that contains this mission (e.g., "1071 m169")
                        # and convert to "1071-m169" format
                        found_mapping = False
                        for map_key, map_value in settings.remote_mission_folder_map.items():
                            # Check if this mapping value matches the folder name
                            # and if the key contains the mission base
                            if (map_value == folder_name or 
                                map_value.lower() == folder_name.lower() or
                                f" {mission_base}" in map_key or
                                map_key.endswith(mission_base)):
                                # Extract project number from key (e.g., "1071" from "1071 m169")
                                # Key format could be: "1071 m169", "1071-m169", "1071m169", etc.
                                project_match = re.match(r'^(\d+)', map_key)
                                if project_match:
                                    project_num = project_match.group(1)
                                    mission_id = f"{project_num}-{mission_base}"  # "1071-m169"
                                    mission_ids.add(mission_id)
                                    logger.info(f"Extracted mission ID: {mission_id} from folder {folder_name} via mapping key '{map_key}'")
                                    found_mapping = True
                                    break
                        
                        # Fallback: if no mapping found, use just the mission base (e.g., "m169")
                        if not found_mapping:
                            logger.warning(f"No mapping found for folder {folder_name}, using base mission ID: {mission_base}")
                            mission_ids.add(mission_base)
                    else:
                        logger.info(f"No mission ID match for: {folder_name}")
                
                # Convert to sorted list (numerically by mission number)
                # Sort by project number first, then mission number
                def sort_key(x):
                    if '-' in x:
                        parts = x.split('-')
                        if len(parts) == 2 and parts[1].startswith('m') and parts[1][1:].isdigit():
                            return (int(parts[0]) if parts[0].isdigit() else 9999, int(parts[1][1:]))
                    elif x.startswith('m') and x[1:].isdigit():
                        return (9999, int(x[1:]))  # Unmapped missions go to end
                    return (9999, 9999)
                
                filtered_missions = sorted(mission_ids, key=sort_key)
                
                logger.info(f"Found {len(filtered_missions)} historical missions: {filtered_missions}")
                if len(filtered_missions) == 0:
                    logger.warning(f"No missions found. Response length: {len(response.text)}, Preview: {response.text[:500]}")
                return filtered_missions
            else:
                logger.warning(f"Failed to fetch historical missions: HTTP {response.status_code}, URL: {past_missions_url}")
                return []
    except httpx.RequestError as e:
        logger.error(f"Network error fetching historical missions: {e}")
        return []
    except Exception as e:
        logger.error(f"Error fetching historical missions: {e}", exc_info=True)
        return [] 