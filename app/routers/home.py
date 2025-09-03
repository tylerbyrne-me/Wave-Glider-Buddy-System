from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from typing import Optional, Dict, List
from ..core import models
from ..auth_utils import get_current_active_user, get_optional_current_user
from ..db import get_db_session, SQLModelSession
from app.core.templates import templates
from app.config import settings
from ..core.template_context import get_template_context
from sqlmodel import select
import logging

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Home"])

@router.get("/home.html", response_class=HTMLResponse)
async def get_home_page(
    request: Request,
    current_user: Optional[models.User] = Depends(get_optional_current_user),
    session: SQLModelSession = Depends(get_db_session)
):
    if not current_user:
        return RedirectResponse(url="/login.html")
    
    # Get active missions from settings
    active_missions = settings.active_realtime_missions
    logger.info(f"Loading home page with active missions: {active_missions}")
    
    # Load mission data for each active mission
    active_mission_data: Dict[str, models.MissionInfoResponse] = {}
    
    for mission_id in active_missions:
        # Get mission overview, goals, and notes
        overview = session.get(models.MissionOverview, mission_id)
        goals_stmt = select(models.MissionGoal).where(models.MissionGoal.mission_id == mission_id).order_by(models.MissionGoal.id)
        goals = session.exec(goals_stmt).all()
        notes_stmt = select(models.MissionNote).where(models.MissionNote.mission_id == mission_id).order_by(models.MissionNote.created_at_utc.desc())
        notes = session.exec(notes_stmt).all()
        
        logger.info(f"Mission {mission_id} - Overview: {overview}, Goals: {len(goals)}, Notes: {len(notes)}")
        
        active_mission_data[mission_id] = models.MissionInfoResponse(
            overview=overview,
            goals=goals,
            notes=notes
        )
    
    template_context = get_template_context(
        request=request, 
        current_user=current_user,
        active_missions=active_missions,
        active_mission_data=active_mission_data
    )
    logger.info(f"Template context - active_missions: {active_missions}, active_mission_data keys: {list(active_mission_data.keys())}")
    logger.info(f"Active missions type: {type(active_missions)}, length: {len(active_missions) if active_missions else 0}")
    
    return templates.TemplateResponse("home.html", template_context) 