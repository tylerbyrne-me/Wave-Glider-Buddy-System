"""
Slocum deployment metadata API (goals, notes, media, briefing bundle).

Metadata is owned by ``SlocumDeployment``, keyed to ERDDAP datasets via
``erddap_dataset_id``. Rows are get-or-created from the dataset id (same idea as
Wave Glider ``MissionOverview`` for a mission folder) — Sensor Tracker sync and
ERDDAP identity are enough; no manual link step is required.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlmodel import select

from ..config import settings
from ..core.auth import get_current_active_user, get_current_admin_user, require_platform_access
from ..core.infra.db import get_db_session, SQLModelSession
from ..core import models, utils
from ..core.infra.feature_toggles import is_feature_enabled
from ..core.slocum_checklist_autofill import list_checklist_presets
from ..core.slocum_deployment_service import (
    get_or_create_deployment_for_dataset,
    resolve_deployment_for_dataset,
)
from ..core.models.schemas import (
    SlocumChecklistReferencesUpdate,
    SlocumDeploymentCreate,
    SlocumDeploymentGoalCreate,
    SlocumDeploymentGoalRead,
    SlocumDeploymentGoalToggle,
    SlocumDeploymentGoalUpdate,
    SlocumDeploymentInfoResponse,
    SlocumDeploymentMediaRead,
    SlocumDeploymentNoteCreate,
    SlocumDeploymentNoteRead,
    SlocumDeploymentNoteUpdate,
    SlocumDeploymentRead,
    SlocumDeploymentUpdate,
    SlocumParsedDataset,
    SlocumSensorCardsUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/slocum",
    tags=["Slocum Deployments"],
    dependencies=[Depends(require_platform_access("slocum"))],
)

# Canonical metadata owner for Slocum briefing features.
SLOCUM_METADATA_OWNER = "SlocumDeployment"
SLOCUM_VALID_SENSOR_CARDS: Set[str] = {"ctd", "dissolved_oxygen"}
SLOCUM_DEFAULT_SENSOR_CARDS = ["ctd"]


def _require_slocum_platform():
    if not is_feature_enabled("slocum_platform"):
        raise HTTPException(status_code=403, detail="Slocum platform is disabled.")


def _get_deployment_or_404(deployment_id: int, session: SQLModelSession) -> models.SlocumDeployment:
    deployment = session.get(models.SlocumDeployment, deployment_id)
    if not deployment or not deployment.is_active:
        raise HTTPException(status_code=404, detail="Deployment not found")
    return deployment


def _resolve_deployment_by_dataset(dataset_id: str, session: SQLModelSession) -> Optional[models.SlocumDeployment]:
    return resolve_deployment_for_dataset(session, dataset_id)


def _get_user_sensor_tracker_token(session: SQLModelSession, username: str) -> Optional[str]:
    user_in_db = session.exec(
        select(models.UserInDB).where(models.UserInDB.username == username)
    ).first()
    return user_in_db.sensor_tracker_token if user_in_db else None


def _build_deployment_info(
    deployment: Optional[models.SlocumDeployment],
    session: SQLModelSession,
    dataset_id: Optional[str] = None,
) -> SlocumDeploymentInfoResponse:
    parsed_dataset: Optional[SlocumParsedDataset] = None
    sensor_tracker_deployment: Optional[models.SensorTrackerDeployment] = None
    sensor_tracker_instruments: List[models.MissionInstrument] = []
    resolved_dataset_id = dataset_id or (deployment.erddap_dataset_id if deployment else None)
    if resolved_dataset_id:
        raw_parsed = utils.parse_slocum_dataset_id(resolved_dataset_id)
        if raw_parsed:
            parsed_dataset = SlocumParsedDataset(**raw_parsed)
            mission_code = f"m{raw_parsed['deployment_number']}"
            sensor_tracker_deployment = session.exec(
                select(models.SensorTrackerDeployment).where(
                    models.SensorTrackerDeployment.mission_id == mission_code
                )
            ).first()
            if sensor_tracker_deployment:
                sensor_tracker_instruments = session.exec(
                    select(models.MissionInstrument).where(
                        models.MissionInstrument.mission_id == mission_code
                    )
                ).all()
    if not deployment:
        return SlocumDeploymentInfoResponse(
            deployment=None,
            goals=[],
            notes=[],
            media=[],
            parsed_dataset=parsed_dataset,
            sensor_tracker_deployment=sensor_tracker_deployment,
            sensor_tracker_instruments=sensor_tracker_instruments,
        )
    goals = session.exec(
        select(models.SlocumDeploymentGoal)
        .where(models.SlocumDeploymentGoal.deployment_id == deployment.id)
        .order_by(models.SlocumDeploymentGoal.id)
    ).all()
    notes = session.exec(
        select(models.SlocumDeploymentNote)
        .where(models.SlocumDeploymentNote.deployment_id == deployment.id)
        .order_by(models.SlocumDeploymentNote.created_at_utc.desc())
    ).all()
    media = session.exec(
        select(models.SlocumDeploymentMedia)
        .where(models.SlocumDeploymentMedia.deployment_id == deployment.id)
        .order_by(models.SlocumDeploymentMedia.display_order, models.SlocumDeploymentMedia.uploaded_at_utc.desc())
    ).all()
    return SlocumDeploymentInfoResponse(
        deployment=SlocumDeploymentRead.model_validate(deployment),
        goals=[SlocumDeploymentGoalRead.model_validate(g) for g in goals],
        notes=[SlocumDeploymentNoteRead.model_validate(n) for n in notes],
        media=[SlocumDeploymentMediaRead.model_validate(m) for m in media],
        parsed_dataset=parsed_dataset,
        sensor_tracker_deployment=sensor_tracker_deployment,
        sensor_tracker_instruments=sensor_tracker_instruments,
    )


# --- Deployment CRUD ---


@router.post("/deployments", response_model=SlocumDeploymentRead, status_code=201)
def create_deployment(
    body: SlocumDeploymentCreate,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    _require_slocum_platform()
    deployment = models.SlocumDeployment(
        name=body.name,
        glider_name=body.glider_name,
        deployment_date=body.deployment_date,
        notes=body.notes,
        erddap_dataset_id=body.erddap_dataset_id,
        status="active",
        created_by_username=current_user.username,
    )
    session.add(deployment)
    session.commit()
    session.refresh(deployment)
    return deployment


@router.get("/deployments", response_model=List[SlocumDeploymentRead])
def list_deployments(
    status_filter: Optional[str] = Query(None),
    include_all: bool = Query(
        False,
        description="If true, return all active deployments; otherwise only those linked to active realtime ERDDAP datasets",
    ),
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    _require_slocum_platform()
    q = select(models.SlocumDeployment).where(models.SlocumDeployment.is_active == True)  # noqa: E712
    if status_filter:
        q = q.where(models.SlocumDeployment.status == status_filter)
    q = q.order_by(models.SlocumDeployment.updated_at_utc.desc())
    deployments = session.exec(q).all()
    if not include_all:
        active_ids = set(settings.active_slocum_datasets or [])
        deployments = [
            d for d in deployments
            if d.erddap_dataset_id and d.erddap_dataset_id in active_ids
        ]
    return list(deployments)


@router.get("/deployments/{deployment_id}", response_model=SlocumDeploymentRead)
def get_deployment(
    deployment_id: int,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    _require_slocum_platform()
    return _get_deployment_or_404(deployment_id, session)


@router.put("/deployments/{deployment_id}", response_model=SlocumDeploymentRead)
def update_deployment(
    deployment_id: int,
    body: SlocumDeploymentUpdate,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    _require_slocum_platform()
    deployment = _get_deployment_or_404(deployment_id, session)
    if body.name is not None:
        deployment.name = body.name
    if body.glider_name is not None:
        deployment.glider_name = body.glider_name
    if body.deployment_date is not None:
        deployment.deployment_date = body.deployment_date
    if body.status is not None:
        deployment.status = body.status
    if body.notes is not None:
        deployment.notes = body.notes
    if body.erddap_dataset_id is not None:
        deployment.erddap_dataset_id = body.erddap_dataset_id
    session.add(deployment)
    session.commit()
    session.refresh(deployment)
    return deployment


@router.delete("/deployments/{deployment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_deployment(
    deployment_id: int,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    _require_slocum_platform()
    deployment = session.get(models.SlocumDeployment, deployment_id)
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")
    deployment.is_active = False
    deployment.status = "archived"
    session.add(deployment)
    session.commit()
    return None


@router.get("/datasets/{dataset_id}/info", response_model=SlocumDeploymentInfoResponse)
def get_dataset_info(
    dataset_id: str,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """Briefing bundle for a Slocum ERDDAP dataset (auto-creates deployment metadata if needed)."""
    _require_slocum_platform()
    deployment = get_or_create_deployment_for_dataset(
        session,
        dataset_id,
        created_by_username=current_user.username,
    )
    return _build_deployment_info(deployment, session, dataset_id=dataset_id)


@router.post("/datasets/{dataset_id}/link-deployment", response_model=SlocumDeploymentInfoResponse)
def link_dataset_deployment(
    dataset_id: str,
    current_admin: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """
    Compatibility alias for get-or-create deployment metadata for a dataset.

    Prefer relying on GET /datasets/{dataset_id}/info, which now auto-creates.
    """
    _require_slocum_platform()
    deployment = get_or_create_deployment_for_dataset(
        session,
        dataset_id,
        created_by_username=current_admin.username,
    )
    if not deployment:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot create deployment metadata: invalid Slocum dataset id '{dataset_id}'.",
        )
    return _build_deployment_info(deployment, session, dataset_id=dataset_id)


@router.post("/datasets/{dataset_id}/sensor-tracker/sync", response_model=SlocumDeploymentInfoResponse)
async def sync_dataset_sensor_tracker(
    dataset_id: str,
    force_refresh: bool = Query(False, description="Force refresh Sensor Tracker metadata"),
    current_admin: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """Sync Sensor Tracker metadata for a Slocum dataset (mission id m{deployment_number})."""
    _require_slocum_platform()
    parsed = utils.parse_slocum_dataset_id(dataset_id)
    if not parsed:
        raise HTTPException(status_code=400, detail="Invalid Slocum dataset id format.")
    mission_code = f"m{parsed['deployment_number']}"
    from ..services.sensor_tracker_sync_service import SensorTrackerSyncService

    admin_token = _get_user_sensor_tracker_token(session, current_admin.username)
    sync_service = SensorTrackerSyncService(token_override=admin_token)
    await sync_service.get_or_sync_mission(
        mission_id=mission_code,
        force_refresh=force_refresh,
        session=session,
    )
    deployment = get_or_create_deployment_for_dataset(
        session,
        dataset_id,
        created_by_username=current_admin.username,
    )
    return _build_deployment_info(deployment, session, dataset_id=dataset_id)


@router.get("/deployments/{deployment_id}/info", response_model=SlocumDeploymentInfoResponse)
def get_deployment_info(
    deployment_id: int,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    _require_slocum_platform()
    deployment = _get_deployment_or_404(deployment_id, session)
    return _build_deployment_info(
        deployment,
        session,
        dataset_id=deployment.erddap_dataset_id,
    )


@router.post("/deployments/{deployment_id}/goals", response_model=SlocumDeploymentGoalRead, status_code=201)
def create_goal(
    deployment_id: int,
    body: SlocumDeploymentGoalCreate,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    _require_slocum_platform()
    _get_deployment_or_404(deployment_id, session)
    goal = models.SlocumDeploymentGoal(deployment_id=deployment_id, description=body.description)
    session.add(goal)
    session.commit()
    session.refresh(goal)
    return goal


@router.put("/deployments/goals/{goal_id}", response_model=SlocumDeploymentGoalRead)
def update_goal(
    goal_id: int,
    body: SlocumDeploymentGoalUpdate,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    _require_slocum_platform()
    goal = session.get(models.SlocumDeploymentGoal, goal_id)
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")
    if body.description is not None:
        goal.description = body.description
    if body.is_completed is not None:
        goal.is_completed = body.is_completed
        goal.completed_by_username = current_user.username if body.is_completed else None
        goal.completed_at_utc = datetime.now(timezone.utc) if body.is_completed else None
    session.add(goal)
    session.commit()
    session.refresh(goal)
    return goal


@router.post("/deployments/{deployment_id}/goals/{goal_id}/toggle", response_model=SlocumDeploymentGoalRead)
def toggle_goal(
    deployment_id: int,
    goal_id: int,
    body: SlocumDeploymentGoalToggle,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    _require_slocum_platform()
    goal = session.get(models.SlocumDeploymentGoal, goal_id)
    if not goal or goal.deployment_id != deployment_id:
        raise HTTPException(status_code=404, detail="Goal not found")
    goal.is_completed = body.is_completed
    goal.completed_by_username = current_user.username if body.is_completed else None
    goal.completed_at_utc = datetime.now(timezone.utc) if body.is_completed else None
    session.add(goal)
    session.commit()
    session.refresh(goal)
    return goal


@router.delete("/deployments/goals/{goal_id}", status_code=204)
def delete_goal(
    goal_id: int,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    _require_slocum_platform()
    goal = session.get(models.SlocumDeploymentGoal, goal_id)
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")
    session.delete(goal)
    session.commit()
    return None


@router.post("/deployments/{deployment_id}/notes", response_model=SlocumDeploymentNoteRead, status_code=201)
def create_note(
    deployment_id: int,
    body: SlocumDeploymentNoteCreate,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    _require_slocum_platform()
    _get_deployment_or_404(deployment_id, session)
    note = models.SlocumDeploymentNote(
        deployment_id=deployment_id,
        content=body.content,
        include_in_report=body.include_in_report,
        created_by_username=current_user.username,
    )
    session.add(note)
    session.commit()
    session.refresh(note)
    return note


@router.put("/deployments/notes/{note_id}", response_model=SlocumDeploymentNoteRead)
def update_note(
    note_id: int,
    body: SlocumDeploymentNoteUpdate,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    _require_slocum_platform()
    note = session.get(models.SlocumDeploymentNote, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    if body.content is not None:
        note.content = body.content
    if body.include_in_report is not None:
        note.include_in_report = body.include_in_report
    note.updated_at_utc = datetime.now(timezone.utc)
    session.add(note)
    session.commit()
    session.refresh(note)
    return note


@router.delete("/deployments/notes/{note_id}", status_code=204)
def delete_note(
    note_id: int,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    _require_slocum_platform()
    note = session.get(models.SlocumDeploymentNote, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    session.delete(note)
    session.commit()
    return None


@router.get("/checklist-presets")
def get_checklist_presets(
    current_user: models.User = Depends(get_current_active_user),
):
    """Battery pack and glider depth preset catalog for admin Mission Overview UI."""
    _require_slocum_platform()
    return list_checklist_presets()


@router.put("/deployments/{deployment_id}/sensor-cards", response_model=SlocumDeploymentRead)
def update_deployment_sensor_cards(
    deployment_id: int,
    body: SlocumSensorCardsUpdate,
    current_admin: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """Update enabled sensor cards for a Slocum deployment (admin only)."""
    _require_slocum_platform()
    deployment = _get_deployment_or_404(deployment_id, session)
    requested = body.enabled_sensor_cards or []
    invalid = [key for key in requested if key not in SLOCUM_VALID_SENSOR_CARDS]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid sensor card(s): {', '.join(invalid)}. "
                   f"Allowed: {', '.join(sorted(SLOCUM_VALID_SENSOR_CARDS))}.",
        )
    # Preserve request order, drop duplicates
    seen: Set[str] = set()
    ordered: List[str] = []
    for key in requested:
        if key not in seen:
            seen.add(key)
            ordered.append(key)
    deployment.enabled_sensor_cards = json.dumps(ordered) if ordered else None
    deployment.updated_at_utc = datetime.now(timezone.utc)
    session.add(deployment)
    session.commit()
    session.refresh(deployment)
    logger.info(
        "Admin '%s' updated sensor cards for deployment %s: %s",
        current_admin.username,
        deployment_id,
        deployment.enabled_sensor_cards,
    )
    return deployment


@router.put("/deployments/{deployment_id}/checklist-references", response_model=SlocumDeploymentRead)
def update_deployment_checklist_references(
    deployment_id: int,
    body: SlocumChecklistReferencesUpdate,
    current_admin: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """Update daily checklist reference values for a Slocum deployment (admin only)."""
    _require_slocum_platform()
    deployment = _get_deployment_or_404(deployment_id, session)
    raw = body.checklist_reference_values or {}
    cleaned: Dict[str, Any] = {}
    for key, value in raw.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        cleaned[str(key)] = value
    deployment.checklist_reference_values = json.dumps(cleaned) if cleaned else None
    deployment.updated_at_utc = datetime.now(timezone.utc)
    session.add(deployment)
    session.commit()
    session.refresh(deployment)
    logger.info(
        "Admin '%s' updated checklist references for deployment %s",
        current_admin.username,
        deployment_id,
    )
    return deployment


@router.post("/deployments/{deployment_id}/plan/upload", response_model=dict)
async def upload_deployment_plan(
    deployment_id: int,
    file: UploadFile = File(...),
    current_admin: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """Upload a formal mission plan document (PDF/DOC/DOCX) for a Slocum deployment."""
    _require_slocum_platform()
    deployment = _get_deployment_or_404(deployment_id, session)
    allowed_content_types = {
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
    if (file.content_type or "") not in allowed_content_types:
        raise HTTPException(status_code=400, detail="Invalid file type. Only PDF, DOC, and DOCX are allowed.")

    file_extension = Path(file.filename or "plan.pdf").suffix.lower()
    if file_extension not in {".pdf", ".doc", ".docx"}:
        raise HTTPException(status_code=400, detail="Invalid file extension. Only PDF, DOC, and DOCX are allowed.")

    safe_glider = utils.sanitize_path_segment(deployment.glider_name or f"deployment_{deployment.id}")
    safe_filename = f"{safe_glider}_plan{file_extension}"
    plan_dir = (
        Path(__file__).resolve().parent.parent.parent
        / "web"
        / "static"
        / "slocum_mission_plans"
        / str(deployment.id)
    )
    plan_dir.mkdir(parents=True, exist_ok=True)
    file_path = plan_dir / safe_filename

    try:
        content = await file.read()
        file_path.write_bytes(content)
        if not file_path.exists() or file_path.stat().st_size != len(content):
            raise RuntimeError("File was not written correctly")
    except Exception as exc:
        if file_path.exists():
            file_path.unlink()
        logger.error("Failed to save Slocum mission plan for deployment %s: %s", deployment_id, exc)
        raise HTTPException(status_code=500, detail=f"Failed to save file: {exc}") from exc
    finally:
        await file.close()

    # Remove any previous plan files in this directory that are not the new one.
    for existing in plan_dir.iterdir():
        if existing.is_file() and existing.name != safe_filename:
            try:
                existing.unlink()
            except OSError:
                logger.warning("Could not remove old plan file: %s", existing)

    file_url = f"/static/slocum_mission_plans/{deployment.id}/{safe_filename}"
    deployment.document_url = file_url
    deployment.updated_at_utc = datetime.now(timezone.utc)
    session.add(deployment)
    session.commit()
    session.refresh(deployment)
    logger.info(
        "Admin '%s' uploaded Slocum plan for deployment %s: %s",
        current_admin.username,
        deployment_id,
        file_url,
    )
    return {"file_url": file_url, "document_url": file_url}


@router.delete("/deployments/{deployment_id}/plan", response_model=dict)
def delete_deployment_plan(
    deployment_id: int,
    current_admin: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """Remove the formal mission plan document for a Slocum deployment."""
    _require_slocum_platform()
    deployment = _get_deployment_or_404(deployment_id, session)
    plan_dir = (
        Path(__file__).resolve().parent.parent.parent
        / "web"
        / "static"
        / "slocum_mission_plans"
        / str(deployment.id)
    )
    if plan_dir.is_dir():
        for existing in plan_dir.iterdir():
            if existing.is_file():
                try:
                    existing.unlink()
                except OSError:
                    logger.warning("Could not remove plan file: %s", existing)

    deployment.document_url = None
    deployment.updated_at_utc = datetime.now(timezone.utc)
    session.add(deployment)
    session.commit()
    logger.info(
        "Admin '%s' removed Slocum plan for deployment %s",
        current_admin.username,
        deployment_id,
    )
    return {"document_url": None, "message": "Plan document removed"}


@router.get("/deployments/{deployment_id}/media", response_model=List[SlocumDeploymentMediaRead])
def list_media(
    deployment_id: int,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    _require_slocum_platform()
    _get_deployment_or_404(deployment_id, session)
    media = session.exec(
        select(models.SlocumDeploymentMedia)
        .where(models.SlocumDeploymentMedia.deployment_id == deployment_id)
        .order_by(models.SlocumDeploymentMedia.display_order, models.SlocumDeploymentMedia.uploaded_at_utc.desc())
    ).all()
    return media


@router.post("/deployments/{deployment_id}/media/upload", response_model=SlocumDeploymentMediaRead, status_code=201)
async def upload_media(
    deployment_id: int,
    file: UploadFile = File(...),
    caption: Optional[str] = None,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    _require_slocum_platform()
    deployment = _get_deployment_or_404(deployment_id, session)
    content_type = file.content_type or "application/octet-stream"
    is_image = content_type.startswith("image/")
    is_video = content_type.startswith("video/")
    if not is_image and not is_video:
        raise HTTPException(status_code=400, detail="Only image and video uploads are supported.")
    media_root = Path(__file__).resolve().parent.parent.parent / "web" / "static" / "slocum_media" / str(deployment.id)
    media_root.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename or "upload.bin").name
    dest = media_root / safe_name
    data = await file.read()
    dest.write_bytes(data)
    static_root = Path(__file__).resolve().parent.parent.parent / "web" / "static"
    rel_path = str(dest.relative_to(static_root)).replace("\\", "/")
    media = models.SlocumDeploymentMedia(
        deployment_id=deployment.id,
        media_type="photo" if is_image else "video",
        file_path=rel_path.replace("\\", "/"),
        file_name=safe_name,
        file_size=len(data),
        mime_type=content_type,
        caption=caption,
        uploaded_by_username=current_user.username,
        approval_status="approved",
        approved_by_username=current_user.username,
        approved_at_utc=datetime.now(timezone.utc),
    )
    session.add(media)
    session.commit()
    session.refresh(media)
    return media
