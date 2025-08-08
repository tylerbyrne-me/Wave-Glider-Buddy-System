from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import HTMLResponse
from typing import List, Optional
from sqlmodel import select
from ..core import models
from ..db import get_db_session, SQLModelSession
from ..auth_utils import get_current_active_user, get_current_admin_user, get_optional_current_user
import logging

# Import Announcement models from app.py or core.models
from ..core.models import (
    Announcement,
    AnnouncementAcknowledgement,
    AnnouncementCreate,
    AnnouncementRead,
    AnnouncementReadForUser,
    AnnouncementReadWithAcks,
    AcknowledgedByInfo,
)
from .. import auth_utils
from app.core.templates import templates

router = APIRouter(tags=["Announcements"])
logger = logging.getLogger(__name__)

# --- HTML/Admin Page ---
@router.get("/admin/announcements.html", response_class=HTMLResponse)
async def get_admin_announcements_page(
    request: Request,
    current_user: Optional[models.User] = Depends(get_optional_current_user)
):
    username_for_log = (
        current_user.username if current_user else "anonymous/unauthenticated"
    )
    logger.info(
        f"User '{username_for_log}' accessing /admin/announcements.html. JS will verify admin role."
    )
    return templates.TemplateResponse(
        "admin_announcements.html",
        {"request": request, "current_user": current_user},
    )

# --- API Endpoints ---
@router.post("/api/admin/announcements", response_model=AnnouncementRead, status_code=status.HTTP_201_CREATED)
async def create_announcement(
    announcement_in: AnnouncementCreate,
    current_admin: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session)
):
    logger.info(f"Admin '{current_admin.username}' creating new announcement.")
    if not announcement_in.content.strip():
        raise HTTPException(status_code=400, detail="Announcement content cannot be empty.")
    db_announcement = Announcement(
        content=announcement_in.content,
        created_by_username=current_admin.username
    )
    session.add(db_announcement)
    session.commit()
    session.refresh(db_announcement)
    return db_announcement

@router.get("/api/announcements/active", response_model=List[AnnouncementReadForUser])
async def get_active_announcements(
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session)
):
    active_announcements_stmt = select(Announcement).where(Announcement.is_active == True).order_by(Announcement.created_at_utc.desc())
    active_announcements = session.exec(active_announcements_stmt).all()
    user_in_db = auth_utils.get_user_from_db(session, current_user.username)
    if not user_in_db:
        raise HTTPException(status_code=404, detail="Current user not found in database.")
    user_acks_stmt = select(AnnouncementAcknowledgement.announcement_id).where(AnnouncementAcknowledgement.user_id == user_in_db.id)
    user_acked_ids = set(session.exec(user_acks_stmt).all())
    response_list = []
    for ann in active_announcements:
        ann_data = AnnouncementReadForUser.model_validate(ann)
        ann_data.is_acknowledged_by_user = ann.id in user_acked_ids
        response_list.append(ann_data)
    return response_list

@router.post("/api/announcements/{announcement_id}/ack", status_code=status.HTTP_204_NO_CONTENT)
async def acknowledge_announcement(
    announcement_id: int,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session)
):
    user_in_db = auth_utils.get_user_from_db(session, current_user.username)
    if not user_in_db:
        raise HTTPException(status_code=404, detail="Current user not found in database.")
    announcement = session.get(Announcement, announcement_id)
    if not announcement or not announcement.is_active:
        raise HTTPException(status_code=404, detail="Active announcement not found.")
    existing_ack_stmt = select(AnnouncementAcknowledgement).where(
        AnnouncementAcknowledgement.announcement_id == announcement_id,
        AnnouncementAcknowledgement.user_id == user_in_db.id
    )
    if session.exec(existing_ack_stmt).first():
        logger.warning(f"User '{current_user.username}' tried to re-acknowledge announcement ID {announcement_id}.")
        return
    new_ack = AnnouncementAcknowledgement(announcement_id=announcement_id, user_id=user_in_db.id)
    session.add(new_ack)
    session.commit()
    logger.info(f"User '{current_user.username}' acknowledged announcement ID {announcement_id}.")
    return

@router.get("/api/admin/announcements/all", response_model=List[AnnouncementReadWithAcks])
async def admin_get_all_announcements(
    current_admin: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session)
):
    all_announcements = session.exec(select(Announcement).order_by(Announcement.created_at_utc.desc())).all()
    response_list = []
    for ann in all_announcements:
        ann_data = AnnouncementReadWithAcks.model_validate(ann)
        ack_list = []
        for ack in ann.acknowledgements:
            user = session.get(models.UserInDB, ack.user_id)
            if user:
                ack_list.append(AcknowledgedByInfo(username=user.username, acknowledged_at_utc=ack.acknowledged_at_utc))
        ann_data.acknowledged_by = sorted(ack_list, key=lambda x: x.acknowledged_at_utc)
        response_list.append(ann_data)
    return response_list

@router.delete("/api/admin/announcements/{announcement_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_announcement(
    announcement_id: int,
    current_admin: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session)
):
    db_announcement = session.get(Announcement, announcement_id)
    if not db_announcement:
        raise HTTPException(status_code=404, detail="Announcement not found.")
    db_announcement.is_active = False
    session.add(db_announcement)
    session.commit()
    logger.info(f"Admin '{current_admin.username}' archived announcement ID {announcement_id}.")
    return

@router.put("/api/admin/announcements/{announcement_id}", response_model=AnnouncementRead)
async def edit_announcement(
    announcement_id: int,
    announcement_update: AnnouncementCreate,
    current_admin: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session)
):
    logger.info(f"Admin '{current_admin.username}' editing announcement ID {announcement_id}.")
    db_announcement = session.get(Announcement, announcement_id)
    if not db_announcement:
        raise HTTPException(status_code=404, detail="Announcement not found.")
    if not announcement_update.content.strip():
        raise HTTPException(status_code=400, detail="Announcement content cannot be empty.")
    db_announcement.content = announcement_update.content
    session.add(db_announcement)
    session.commit()
    session.refresh(db_announcement)
    return db_announcement 