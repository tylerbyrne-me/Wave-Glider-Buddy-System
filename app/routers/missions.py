from fastapi import APIRouter, Depends, HTTPException, status, Request, UploadFile, File
from fastapi.responses import HTMLResponse
from typing import List, Optional
from datetime import datetime, timezone
from pathlib import Path
from sqlmodel import select
from ..core import models
from ..db import get_db_session, SQLModelSession
from ..auth_utils import get_current_active_user, get_current_admin_user, get_optional_current_user
import shutil
import logging
from app.core.templates import templates
from app.config import settings
from ..core.template_context import get_template_context


router = APIRouter(tags=["Missions"])
logger = logging.getLogger(__name__)

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
async def _get_mission_info(mission_id: str, session: SQLModelSession) -> models.MissionInfoResponse:
    overview = session.get(models.MissionOverview, mission_id)
    goals_stmt = select(models.MissionGoal).where(models.MissionGoal.mission_id == mission_id).order_by(models.MissionGoal.id)
    goals = session.exec(goals_stmt).all()
    notes_stmt = select(models.MissionNote).where(models.MissionNote.mission_id == mission_id).order_by(models.MissionNote.created_at_utc.desc())
    notes = session.exec(notes_stmt).all()
    return models.MissionInfoResponse(
        overview=overview,
        goals=goals,
        notes=notes
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
    mission_plans_dir = Path(__file__).resolve().parent.parent / "web" / "static" / "mission_plans"
    
    # Create the directory if it doesn't exist
    mission_plans_dir.mkdir(parents=True, exist_ok=True)
    
    file_path = mission_plans_dir / safe_filename
    try:
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    finally:
        file.file.close()
    file_url = f"/static/mission_plans/{safe_filename}"
    logger.info(f"Mission plan for '{mission_id}' saved to '{file_path}'. URL: {file_url}")
    return {"file_url": file_url}

@router.get("/api/missions/{mission_id}/info", response_model=models.MissionInfoResponse)
async def get_mission_info_api(
    mission_id: str,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session)
):
    logger.info(f"User '{current_user.username}' requesting info for mission '{mission_id}'.")
    return await _get_mission_info(mission_id, session)

@router.put("/api/missions/{mission_id}/overview", response_model=models.MissionOverview)
async def create_or_update_mission_overview(
    mission_id: str,
    overview_in: models.MissionOverviewUpdate,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session)
):
    logger.info(f"User '{current_user.username}' updating overview for mission '{mission_id}'.")
    db_overview = session.get(models.MissionOverview, mission_id)
    if not db_overview:
        db_overview = models.MissionOverview(mission_id=mission_id, **overview_in.model_dump(exclude_unset=True))
    else:
        update_data = overview_in.model_dump(exclude_unset=True)
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
    return settings.active_realtime_missions 