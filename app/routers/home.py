from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from typing import Optional, Dict, List
from ..core import models
from ..core.auth import get_current_active_user, get_optional_current_user
from ..core.db import get_db_session, SQLModelSession
from app.core.templates import templates
from app.config import settings
from ..core.template_context import get_template_context
from ..core.feature_toggles import is_feature_enabled
from sqlmodel import select
from sqlalchemy import or_
import logging
logger = logging.getLogger(__name__)

router = APIRouter(tags=["Home"])


@router.get("/platform", response_class=HTMLResponse)
async def get_platform_choice(
    request: Request,
    current_user: Optional[models.User] = Depends(get_optional_current_user),
):
    """Platform choice (splash) after login: Wave Glider or Slocum Glider."""
    if not current_user:
        return RedirectResponse(url="/login.html")
    template_context = get_template_context(request=request, current_user=current_user)
    template_context["show_banner_nav"] = False  # No nav tabs on splash to avoid cross-platform confusion
    return templates.TemplateResponse("platform_choice.html", template_context)


@router.get("/home.html", response_class=HTMLResponse)
async def get_home_page_redirect():
    """Legacy: redirect to canonical Wave Glider home."""
    return RedirectResponse(url="/wave-glider/home")


async def _get_wave_glider_home_response(
    request: Request,
    current_user: models.User,
    session: SQLModelSession,
):
    """Build Wave Glider home page context and return TemplateResponse. Used by GET /wave-glider/home."""
    active_missions = settings.active_realtime_missions
    logger.info(f"Loading home page with active missions: {active_missions}")
    
    # Load mission data for each active mission
    active_mission_data: Dict[str, models.MissionInfoResponse] = {}

    def _normalize_file_url(file_path: str) -> str:
        normalized_path = file_path.replace(chr(92), "/")
        if normalized_path.startswith("web/static/"):
            normalized_path = normalized_path.replace("web/static/", "static/", 1)
        elif normalized_path.startswith("web\\static\\"):
            normalized_path = normalized_path.replace("web\\static\\", "static/", 1)
        if not normalized_path.startswith("static/"):
            return f"/{normalized_path}"
        return f"/{normalized_path}"
    
    for mission_id in active_missions:
        # Get mission overview, goals, and notes
        overview = session.get(models.MissionOverview, mission_id)
        goals_stmt = select(models.MissionGoal).where(models.MissionGoal.mission_id == mission_id).order_by(models.MissionGoal.id)
        goals = session.exec(goals_stmt).all()
        notes_stmt = select(models.MissionNote).where(models.MissionNote.mission_id == mission_id).order_by(models.MissionNote.created_at_utc.desc())
        notes = session.exec(notes_stmt).all()

        role_value = (
            current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
        )
        if role_value != models.UserRoleEnum.admin.value:
            outbox_items = session.exec(
                select(models.SensorTrackerOutbox).where(
                    models.SensorTrackerOutbox.mission_id == mission_id,
                    models.SensorTrackerOutbox.entity_type.in_(["goal", "deployment_comment"]),
                )
            ).all()
            status_by_id = {item.local_id: item.status for item in outbox_items}
            allowed_statuses = {"approved", "synced"}
            goals = [
                goal for goal in goals
                if status_by_id.get(goal.id) in allowed_statuses or status_by_id.get(goal.id) is None
            ]
            notes = [
                note for note in notes
                if status_by_id.get(note.id) in allowed_statuses or status_by_id.get(note.id) is None
            ]
        
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
        
        # Load instruments if we have a deployment
        # Instruments are stored with the full mission_id (e.g., "1070-m216")
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
        
        media_stmt = (
            select(models.MissionMedia)
            .where(models.MissionMedia.mission_id == mission_id)
            .where(models.MissionMedia.approval_status == "approved")
            .order_by(models.MissionMedia.display_order.asc(), models.MissionMedia.uploaded_at_utc.desc())
        )
        media_items = session.exec(media_stmt).all()
        media = []
        for item in media_items:
            file_url = _normalize_file_url(item.file_path)
            thumbnail_url = _normalize_file_url(item.thumbnail_path) if item.thumbnail_path else None
            media.append(models.MissionMediaRead(
                id=item.id,
                mission_id=item.mission_id,
                media_type=item.media_type,
                file_name=item.file_name,
                file_size=item.file_size,
                mime_type=item.mime_type,
                caption=item.caption,
                operation_type=item.operation_type,
                uploaded_by_username=item.uploaded_by_username,
                uploaded_at_utc=item.uploaded_at_utc,
                approval_status=item.approval_status,
                approved_by_username=item.approved_by_username,
                approved_at_utc=item.approved_at_utc,
                thumbnail_url=thumbnail_url,
                file_url=file_url,
                display_order=item.display_order,
                is_featured=item.is_featured,
            ))

        logger.info(f"Mission {mission_id} (base: {mission_base}) - Overview: {overview}, Goals: {len(goals)}, Notes: {len(notes)}, Sensor Tracker: {sensor_tracker_deployment is not None}, Instruments: {len(instruments)}")
        if sensor_tracker_deployment:
            logger.info(f"  Sensor Tracker Deployment found: mission_id={sensor_tracker_deployment.mission_id}, title={sensor_tracker_deployment.title}")
        else:
            logger.warning(f"  No Sensor Tracker Deployment found for mission_id={mission_id} or mission_base={mission_base}")
        
        active_mission_data[mission_id] = models.MissionInfoResponse(
            overview=overview,
            goals=goals,
            notes=notes,
            sensor_tracker_deployment=sensor_tracker_deployment,
            sensor_tracker_instruments=instruments,
            media=media,
        )
    
    template_context = get_template_context(
        request=request,
        current_user=current_user,
        active_missions=active_missions,
        active_mission_data=active_mission_data,
    )
    template_context["show_banner_nav"] = True
    template_context["platform"] = "wave_glider"
    template_context["platform_home_url"] = "/wave-glider/home"
    logger.info(f"Template context - active_missions: {active_missions}, active_mission_data keys: {list(active_mission_data.keys())}")
    logger.info(f"Active missions type: {type(active_missions)}, length: {len(active_missions) if active_missions else 0}")
    
    return templates.TemplateResponse("home.html", template_context)


@router.get("/wave-glider/home", response_class=HTMLResponse)
async def get_wave_glider_home(
    request: Request,
    current_user: Optional[models.User] = Depends(get_optional_current_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """Wave Glider home: mission list and briefings."""
    if not current_user:
        return RedirectResponse(url="/login.html")
    return await _get_wave_glider_home_response(request, current_user, session)


@router.get("/slocum", response_class=HTMLResponse)
async def get_slocum_dashboard(
    request: Request,
    dataset: Optional[str] = None,
    current_user: Optional[models.User] = Depends(get_optional_current_user),
):
    """Slocum Glider mission dashboard (active dataset). Same layout as WG dashboard."""
    if not current_user:
        return RedirectResponse(url="/login.html")
    if not is_feature_enabled("slocum_platform"):
        return RedirectResponse(url="/platform")
    if not dataset:
        return RedirectResponse(url="/slocum/home")
    template_context = get_template_context(
        request=request,
        current_user=current_user,
        active_missions=[],
    )
    template_context["show_banner_nav"] = True
    template_context["platform"] = "slocum"
    template_context["platform_home_url"] = "/slocum/home"
    template_context["dataset"] = dataset
    template_context["is_historical_dataset"] = False
    template_context["is_current_mission_realtime"] = True  # Active dataset: show auto-refresh in banner
    return templates.TemplateResponse("slocum_dashboard.html", template_context)


@router.get("/slocum/historical", response_class=HTMLResponse)
async def get_slocum_historical_dashboard(
    request: Request,
    dataset: Optional[str] = None,
    current_user: Optional[models.User] = Depends(get_optional_current_user),
):
    """Slocum Glider mission dashboard (historical dataset). Same template as /slocum with is_historical_dataset=True."""
    if not current_user:
        return RedirectResponse(url="/login.html")
    if not is_feature_enabled("slocum_platform"):
        return RedirectResponse(url="/platform")
    if not dataset:
        return RedirectResponse(url="/slocum/home")
    template_context = get_template_context(
        request=request,
        current_user=current_user,
        active_missions=[],
    )
    template_context["show_banner_nav"] = True
    template_context["platform"] = "slocum"
    template_context["platform_home_url"] = "/slocum/home"
    template_context["dataset"] = dataset
    template_context["is_historical_dataset"] = True
    template_context["is_current_mission_realtime"] = False  # Historical: no auto-refresh in banner
    return templates.TemplateResponse("slocum_dashboard.html", template_context)


@router.get("/slocum/vehicle-params", response_class=HTMLResponse)
async def get_slocum_vehicle_params(
    request: Request,
    deployment_id: Optional[int] = None,
    current_user: Optional[models.User] = Depends(get_optional_current_user),
):
    """Slocum Vehicle Parameters tool: edit mission files, view snapshots, apply changes."""
    if not current_user:
        return RedirectResponse(url="/login.html")
    if not is_feature_enabled("slocum_platform"):
        return RedirectResponse(url="/platform")
    if not is_feature_enabled("slocum_mission_files"):
        return RedirectResponse(url="/slocum/home")
    template_context = get_template_context(
        request=request,
        current_user=current_user,
        active_missions=[],
    )
    template_context["show_banner_nav"] = True
    template_context["platform"] = "slocum"
    template_context["platform_home_url"] = "/slocum/home"
    template_context["deployment_id"] = deployment_id
    return templates.TemplateResponse("slocum_vehicle_params.html", template_context)


@router.get("/slocum/home", response_class=HTMLResponse)
async def get_slocum_home(
    request: Request,
    current_user: Optional[models.User] = Depends(get_optional_current_user),
):
    """Slocum Glider home: dataset list and map. No WG mission data."""
    if not current_user:
        return RedirectResponse(url="/login.html")
    if not is_feature_enabled("slocum_platform"):
        return RedirectResponse(url="/platform")
    template_context = get_template_context(
        request=request,
        current_user=current_user,
        active_missions=[],  # Do not show WG missions on Slocum home
    )
    template_context["show_banner_nav"] = True
    template_context["platform"] = "slocum"
    template_context["platform_home_url"] = "/slocum/home"
    return templates.TemplateResponse("slocum_home.html", template_context)