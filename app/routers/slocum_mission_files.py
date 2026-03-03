"""
Slocum Mission File Tool API.

Deployments, file upload/download/create, change preview/apply,
snapshots, changelog, and masterdata status.
"""
import io
import json
import logging
import zipfile
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse, PlainTextResponse
from sqlmodel import select

from ..config import settings
from ..core.auth import get_current_active_user, get_current_admin_user
from ..core.db import get_db_session, SQLModelSession
from ..core import models
from ..core.feature_toggles import is_feature_enabled
from ..core.models.schemas import (
    SlocumDeploymentCreate,
    SlocumDeploymentUpdate,
    SlocumDeploymentRead,
    SlocumMissionFileRead,
    SlocumMissionFileVersionRead,
    SlocumDeploymentSnapshotRead,
    SlocumMissionChangeLogRead,
    DeploymentChangesPreviewRequest,
    DeploymentChangesApplyRequest,
    NaturalLanguageChangeRequest,
    ParameterChangeRequest,
    SlocumMasterdataStatus,
)
from ..services.slocum_file_parser import (
    parse_file,
    extract_mission_summary,
    ParsedMissionFile,
    MissionSummary,
)
from ..services.slocum_file_editor import (
    ParameterChange,
    apply_deployment_changes,
    DeploymentEditResult,
    generate_diff,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/slocum/mission-files", tags=["Slocum Mission Files"])


def _require_slocum_mission_files():
    if not is_feature_enabled("slocum_mission_files"):
        raise HTTPException(status_code=404, detail="Slocum Mission Files feature is not enabled")


def _serialize_validation_issue(issue) -> dict:
    return {
        "param": issue.param,
        "message": issue.message,
        "severity": issue.severity,
        "file_name": getattr(issue, "file_name", None),
        "line_number": getattr(issue, "line_number", None),
    }


# --- Masterdata ---
@router.get("/masterdata/status", response_model=SlocumMasterdataStatus)
def get_masterdata_status(
    current_user: models.User = Depends(get_current_active_user),
):
    _require_slocum_mission_files()
    from ..services.slocum_masterdata_service import get_masterdata_status as get_md_status
    from datetime import datetime
    st = get_md_status()
    lv = st.get("last_vectorized_utc")
    return SlocumMasterdataStatus(
        has_masterdata=st.get("has_masterdata", False),
        document_id=st.get("document_id"),
        chunk_count=st.get("chunk_count"),
        parameter_count=st.get("parameter_count"),
        last_vectorized_utc=datetime.fromisoformat(lv) if lv else None,
    )


# --- Deployments ---
@router.post("/deployments", response_model=SlocumDeploymentRead)
def create_deployment(
    body: SlocumDeploymentCreate,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    _require_slocum_mission_files()
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


@router.get("/deployments/active-datasets")
def list_active_realtime_datasets(
    current_user: models.User = Depends(get_current_active_user),
):
    """Return ERDDAP dataset IDs for active realtime Slocum missions (for deployment creation)."""
    _require_slocum_mission_files()
    return {"dataset_ids": list(settings.active_slocum_datasets)}


@router.get("/deployments", response_model=list[SlocumDeploymentRead])
def list_deployments(
    status_filter: Optional[str] = Query(None),
    include_all: bool = Query(False, description="If true, return all active deployments; otherwise only active realtime + testing"),
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    _require_slocum_mission_files()
    q = select(models.SlocumDeployment).where(models.SlocumDeployment.is_active == True)
    if status_filter:
        q = q.where(models.SlocumDeployment.status == status_filter)
    q = q.order_by(models.SlocumDeployment.updated_at_utc.desc())
    deployments = session.exec(q).all()
    if not include_all:
        active_ids = set(settings.active_slocum_datasets or [])
        deployments = [
            d for d in deployments
            if (d.erddap_dataset_id and d.erddap_dataset_id in active_ids)
            or (d.name and d.name.strip().lower() == "testing")
        ]
    return list(deployments)


@router.get("/deployments/{deployment_id}", response_model=SlocumDeploymentRead)
def get_deployment(
    deployment_id: int,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    _require_slocum_mission_files()
    deployment = session.get(models.SlocumDeployment, deployment_id)
    if not deployment or not deployment.is_active:
        raise HTTPException(status_code=404, detail="Deployment not found")
    return deployment


@router.put("/deployments/{deployment_id}", response_model=SlocumDeploymentRead)
def update_deployment(
    deployment_id: int,
    body: SlocumDeploymentUpdate,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    _require_slocum_mission_files()
    deployment = session.get(models.SlocumDeployment, deployment_id)
    if not deployment or not deployment.is_active:
        raise HTTPException(status_code=404, detail="Deployment not found")
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
    _require_slocum_mission_files()
    deployment = session.get(models.SlocumDeployment, deployment_id)
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")
    deployment.is_active = False
    deployment.status = "archived"
    session.add(deployment)
    session.commit()
    return None


# --- Files ---
@router.post("/deployments/{deployment_id}/files/upload")
def upload_files(
    deployment_id: int,
    files: list[UploadFile] = File(...),
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    _require_slocum_mission_files()
    deployment = session.get(models.SlocumDeployment, deployment_id)
    if not deployment or not deployment.is_active:
        raise HTTPException(status_code=404, detail="Deployment not found")
    created = []
    for uf in files:
        fn = uf.filename or "unknown"
        if not (fn.lower().endswith(".ma") or fn.lower().endswith(".mi")):
            continue
        content = uf.file.read().decode("utf-8", errors="replace")
        parsed = parse_file(content, fn)
        file_type = parsed.file_type
        ma_subtype = parsed.ma_subtype
        parsed_dict = {
            "parameters": {k: {"value": v.value, "line_number": v.line_number} for k, v in parsed.parameters.items()},
            "referenced_files": parsed.referenced_files,
            "waypoints": parsed.waypoints,
        }
        mf = models.SlocumMissionFile(
            deployment_id=deployment_id,
            file_name=fn,
            file_type=file_type,
            ma_subtype=ma_subtype,
            original_content=content,
            current_content=content,
            version=1,
            parsed_parameters=parsed_dict,
            uploaded_by_username=current_user.username,
        )
        session.add(mf)
        session.commit()
        session.refresh(mf)
        # Version record
        session.add(models.SlocumMissionFileVersion(
            mission_file_id=mf.id,
            version=1,
            content=content,
            changed_by_username=current_user.username,
            change_summary="Initial upload",
        ))
        session.add(models.SlocumMissionChangeLog(
            deployment_id=deployment_id,
            mission_file_id=mf.id,
            change_type="upload",
            description=f"Uploaded {fn}",
            changed_by_username=current_user.username,
            request_method="upload",
        ))
        session.commit()
        created.append(SlocumMissionFileRead.model_validate(mf))
    return {"uploaded": len(created), "files": created}


@router.get("/deployments/{deployment_id}/files")
def list_deployment_files(
    deployment_id: int,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    _require_slocum_mission_files()
    deployment = session.get(models.SlocumDeployment, deployment_id)
    if not deployment or not deployment.is_active:
        raise HTTPException(status_code=404, detail="Deployment not found")
    q = select(models.SlocumMissionFile).where(
        models.SlocumMissionFile.deployment_id == deployment_id,
        models.SlocumMissionFile.is_active == True,
    )
    files = session.exec(q).all()
    grouped = {"sample": [], "surfacing": [], "yo": [], "goto": [], "mi": []}
    for f in files:
        if f.file_type == "mi":
            grouped["mi"].append(SlocumMissionFileRead.model_validate(f))
        elif f.ma_subtype and f.ma_subtype in grouped:
            grouped[f.ma_subtype].append(SlocumMissionFileRead.model_validate(f))
    return {"files": [SlocumMissionFileRead.model_validate(f) for f in files], "grouped": grouped}


@router.get("/files/{file_id}", response_model=SlocumMissionFileRead)
def get_file(
    file_id: int,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    _require_slocum_mission_files()
    mf = session.get(models.SlocumMissionFile, file_id)
    if not mf or not mf.is_active:
        raise HTTPException(status_code=404, detail="File not found")
    return mf


@router.get("/files/{file_id}/download")
def download_file(
    file_id: int,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    _require_slocum_mission_files()
    mf = session.get(models.SlocumMissionFile, file_id)
    if not mf or not mf.is_active:
        raise HTTPException(status_code=404, detail="File not found")
    return PlainTextResponse(
        mf.current_content,
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{mf.file_name}"'},
    )


@router.get("/deployments/{deployment_id}/download")
def download_deployment_zip(
    deployment_id: int,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    _require_slocum_mission_files()
    deployment = session.get(models.SlocumDeployment, deployment_id)
    if not deployment or not deployment.is_active:
        raise HTTPException(status_code=404, detail="Deployment not found")
    q = select(models.SlocumMissionFile).where(
        models.SlocumMissionFile.deployment_id == deployment_id,
        models.SlocumMissionFile.is_active == True,
    )
    files = session.exec(q).all()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.writestr(f.file_name, f.current_content)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="deployment_{deployment_id}_files.zip"'},
    )


@router.delete("/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_file(
    file_id: int,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    _require_slocum_mission_files()
    mf = session.get(models.SlocumMissionFile, file_id)
    if not mf:
        raise HTTPException(status_code=404, detail="File not found")
    mf.is_active = False
    session.add(mf)
    session.commit()
    return None


# --- Summary ---
@router.get("/deployments/{deployment_id}/files/create/template/{subtype}")
def get_file_create_template(
    deployment_id: int,
    subtype: str,
    current_user: models.User = Depends(get_current_active_user),
):
    _require_slocum_mission_files()
    from ..services.slocum_file_parser import get_required_parameters
    masterdata = {}
    specs = get_required_parameters(subtype, masterdata)
    return {
        "subtype": subtype,
        "parameters": [
            {
                "name": s.name,
                "required": s.required,
                "default_value": s.default_value,
                "description": s.description,
                "valid_range": s.valid_range,
                "param_type": s.param_type,
            }
            for s in specs
        ],
    }


@router.post("/deployments/{deployment_id}/files/create")
def create_file_preview(
    deployment_id: int,
    body: dict,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    _require_slocum_mission_files()
    deployment = session.get(models.SlocumDeployment, deployment_id)
    if not deployment or not deployment.is_active:
        raise HTTPException(status_code=404, detail="Deployment not found")
    from ..services.slocum_file_parser import generate_file
    file_name = body.get("file_name", "unknown.ma")
    subtype = body.get("subtype", "yo")
    parameters = body.get("parameters", {})
    masterdata = {}
    result = generate_file(file_name, subtype, parameters, masterdata)
    return {
        "content": result.content,
        "file_name": result.file_name,
        "validation_warnings": [_serialize_validation_issue(w) for w in result.validation_warnings],
    }


@router.post("/deployments/{deployment_id}/files/create/confirm")
def create_file_confirm(
    deployment_id: int,
    body: dict,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    _require_slocum_mission_files()
    deployment = session.get(models.SlocumDeployment, deployment_id)
    if not deployment or not deployment.is_active:
        raise HTTPException(status_code=404, detail="Deployment not found")
    content = body.get("content")
    file_name = body.get("file_name")
    if not content or not file_name:
        raise HTTPException(status_code=400, detail="content and file_name required")
    parsed = parse_file(content, file_name)
    parsed_dict = {
        "parameters": {k: {"value": v.value, "line_number": v.line_number} for k, v in parsed.parameters.items()},
        "referenced_files": parsed.referenced_files,
        "waypoints": parsed.waypoints,
    }
    mf = models.SlocumMissionFile(
        deployment_id=deployment_id,
        file_name=file_name,
        file_type=parsed.file_type,
        ma_subtype=parsed.ma_subtype,
        original_content=content,
        current_content=content,
        version=1,
        parsed_parameters=parsed_dict,
        uploaded_by_username=current_user.username,
    )
    session.add(mf)
    session.commit()
    session.refresh(mf)
    session.add(models.SlocumMissionFileVersion(
        mission_file_id=mf.id,
        version=1,
        content=content,
        changed_by_username=current_user.username,
        change_summary="Created from template",
    ))
    session.add(models.SlocumMissionChangeLog(
        deployment_id=deployment_id,
        mission_file_id=mf.id,
        change_type="create",
        description=f"Created {file_name}",
        changed_by_username=current_user.username,
        request_method="template",
    ))
    session.commit()
    return {"file": SlocumMissionFileRead.model_validate(mf), "message": "File created"}


@router.get("/deployments/{deployment_id}/summary")
def get_deployment_summary(
    deployment_id: int,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    _require_slocum_mission_files()
    deployment = session.get(models.SlocumDeployment, deployment_id)
    if not deployment or not deployment.is_active:
        raise HTTPException(status_code=404, detail="Deployment not found")
    q = select(models.SlocumMissionFile).where(
        models.SlocumMissionFile.deployment_id == deployment_id,
        models.SlocumMissionFile.is_active == True,
    )
    mission_files = session.exec(q).all()
    parsed_list = [parse_file(f.current_content, f.file_name) for f in mission_files]
    summary = extract_mission_summary(parsed_list)
    return {
        "yo_cycles": summary.yo_cycles,
        "dive_angle": summary.dive_angle,
        "climb_angle": summary.climb_angle,
        "dive_depth": summary.dive_depth,
        "climb_depth": summary.climb_depth,
        "surface_interval": summary.surface_interval,
        "surfacing_trigger_conditions": summary.surfacing_trigger_conditions,
        "active_sample_files": summary.active_sample_files,
        "active_goto_list": summary.active_goto_list,
        "waypoint_count": summary.waypoint_count,
        "post_surface_behavior": summary.post_surface_behavior,
        "referenced_files": summary.referenced_files,
    }


@router.post("/deployments/{deployment_id}/interpret")
def interpret_deployment(
    deployment_id: int,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    _require_slocum_mission_files()
    deployment = session.get(models.SlocumDeployment, deployment_id)
    if not deployment or not deployment.is_active:
        raise HTTPException(status_code=404, detail="Deployment not found")
    q = select(models.SlocumMissionFile).where(
        models.SlocumMissionFile.deployment_id == deployment_id,
        models.SlocumMissionFile.is_active == True,
    )
    mission_files = session.exec(q).all()
    parsed_list = [parse_file(f.current_content, f.file_name) for f in mission_files]
    summary = extract_mission_summary(parsed_list)
    from ..services.slocum_mission_llm_service import interpret_mission
    text = interpret_mission(parsed_list, summary, None)
    return {
        "interpretation": text,
        "summary": {
            "yo_cycles": summary.yo_cycles,
            "dive_angle": summary.dive_angle,
            "climb_angle": summary.climb_angle,
            "dive_depth": summary.dive_depth,
            "climb_depth": summary.climb_depth,
            "surface_interval": summary.surface_interval,
            "active_sample_files": summary.active_sample_files,
            "active_goto_list": summary.active_goto_list,
            "waypoint_count": summary.waypoint_count,
        },
    }


@router.post("/files/{file_id}/explain")
def explain_file(
    file_id: int,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    _require_slocum_mission_files()
    mf = session.get(models.SlocumMissionFile, file_id)
    if not mf or not mf.is_active:
        raise HTTPException(status_code=404, detail="File not found")
    parsed = parse_file(mf.current_content, mf.file_name)
    from ..services.slocum_mission_llm_service import interpret_mission
    text = interpret_mission([parsed], None, None)
    return {"explanation": text, "file_name": mf.file_name}


# --- Changes (preview / apply) ---
@router.post("/deployments/{deployment_id}/changes/preview")
def preview_changes(
    deployment_id: int,
    body: DeploymentChangesPreviewRequest,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    _require_slocum_mission_files()
    deployment = session.get(models.SlocumDeployment, deployment_id)
    if not deployment or not deployment.is_active:
        raise HTTPException(status_code=404, detail="Deployment not found")
    q = select(models.SlocumMissionFile).where(
        models.SlocumMissionFile.deployment_id == deployment_id,
        models.SlocumMissionFile.is_active == True,
    )
    mission_files = session.exec(q).all()
    deployment_files = {f.file_name: f.current_content for f in mission_files}
    changes = [ParameterChange(param=c.param, new_value=c.new_value, file_name=c.file_name) for c in body.changes]
    masterdata = {}  # TODO: from masterdata service
    result = apply_deployment_changes(deployment_files, changes, masterdata)
    return {
        "modified_files": result.modified_files,
        "changes_applied": result.changes_applied,
        "file_diffs": {
            fn: [{"line_num": d.line_num, "kind": d.kind, "content": d.content} for d in diffs]
            for fn, diffs in result.file_diffs.items()
        },
        "single_file_warnings": [_serialize_validation_issue(w) for w in result.single_file_warnings],
        "cross_file_warnings": result.cross_file_warnings,
        "cross_file_suggestions": result.cross_file_suggestions,
    }


@router.post("/deployments/{deployment_id}/changes/apply")
def apply_changes(
    deployment_id: int,
    body: DeploymentChangesApplyRequest,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    _require_slocum_mission_files()
    deployment = session.get(models.SlocumDeployment, deployment_id)
    if not deployment or not deployment.is_active:
        raise HTTPException(status_code=404, detail="Deployment not found")
    q = select(models.SlocumMissionFile).where(
        models.SlocumMissionFile.deployment_id == deployment_id,
        models.SlocumMissionFile.is_active == True,
    )
    mission_files = session.exec(q).all()
    deployment_files = {f.file_name: f.current_content for f in mission_files}
    changes = [ParameterChange(param=c.param, new_value=c.new_value, file_name=c.file_name) for c in body.changes]
    masterdata = {}
    result = apply_deployment_changes(deployment_files, changes, masterdata)
    # Persist: update file current_content, create versions, snapshot, changelog
    snapshot_number = 1
    snap_q = select(models.SlocumDeploymentSnapshot).where(
        models.SlocumDeploymentSnapshot.deployment_id == deployment_id
    ).order_by(models.SlocumDeploymentSnapshot.snapshot_number.desc()).limit(1)
    last = session.exec(snap_q).first()
    if last:
        snapshot_number = last.snapshot_number + 1
    file_states = {}
    parameter_summary = {}
    for f in mission_files:
        if f.file_name in result.modified_files:
            new_content = result.modified_files[f.file_name]
            f.current_content = new_content
            f.version += 1
            session.add(models.SlocumMissionFileVersion(
                mission_file_id=f.id,
                version=f.version,
                content=new_content,
                changed_by_username=current_user.username,
                change_summary=body.label or "Parameter changes",
                changed_parameters=[c for c in result.changes_applied if c["file_name"] == f.file_name],
            ))
            session.add(f)
            file_states[f.file_name] = {"version": f.version}
            parsed = parse_file(new_content, f.file_name)
            parameter_summary.update({k: v.value for k, v in parsed.parameters.items()})
        else:
            file_states[f.file_name] = {"version": f.version}
    snapshot = models.SlocumDeploymentSnapshot(
        deployment_id=deployment_id,
        snapshot_number=snapshot_number,
        label=body.label or f"Edit {datetime.now(timezone.utc).isoformat()}",
        file_states=file_states,
        parameter_summary=parameter_summary,
        created_by_username=current_user.username,
        notes=body.notes,
    )
    session.add(snapshot)
    session.commit()
    session.refresh(snapshot)
    file_name_to_id = {f.file_name: f.id for f in mission_files}
    for c in result.changes_applied:
        session.add(models.SlocumMissionChangeLog(
            deployment_id=deployment_id,
            mission_file_id=file_name_to_id.get(c["file_name"]),
            snapshot_id=snapshot.id,
            change_type="edit",
            description=f"{c['param']}: {c['old_value']} -> {c['new_value']}",
            changed_by_username=current_user.username,
            request_method="form",
        ))
    session.commit()
    return {
        "snapshot_id": snapshot.id,
        "changes_applied": result.changes_applied,
        "message": "Changes applied and snapshot created",
    }


@router.post("/deployments/{deployment_id}/changes/natural-language")
def parse_natural_language_changes(
    deployment_id: int,
    body: NaturalLanguageChangeRequest,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    _require_slocum_mission_files()
    deployment = session.get(models.SlocumDeployment, deployment_id)
    if not deployment or not deployment.is_active:
        raise HTTPException(status_code=404, detail="Deployment not found")
    q = select(models.SlocumMissionFile).where(
        models.SlocumMissionFile.deployment_id == deployment_id,
        models.SlocumMissionFile.is_active == True,
    )
    mission_files = session.exec(q).all()
    current_parameters_by_file = {}
    for f in mission_files:
        parsed = parse_file(f.current_content, f.file_name)
        current_parameters_by_file[f.file_name] = {k: v.value for k, v in parsed.parameters.items()}
    from ..services.slocum_mission_llm_service import parse_natural_language_change
    parsed_changes = parse_natural_language_change(body.request, current_parameters_by_file)
    return {
        "parsed_changes": [
            {"param": c.param, "new_value": c.new_value, "file_name": c.file_name}
            for c in parsed_changes
        ],
    }


# --- Version history ---
@router.get("/files/{file_id}/versions", response_model=list[SlocumMissionFileVersionRead])
def list_file_versions(
    file_id: int,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    _require_slocum_mission_files()
    mf = session.get(models.SlocumMissionFile, file_id)
    if not mf or not mf.is_active:
        raise HTTPException(status_code=404, detail="File not found")
    q = select(models.SlocumMissionFileVersion).where(
        models.SlocumMissionFileVersion.mission_file_id == file_id
    ).order_by(models.SlocumMissionFileVersion.version.desc())
    versions = session.exec(q).all()
    return [SlocumMissionFileVersionRead.model_validate(v) for v in versions]


@router.get("/files/{file_id}/versions/{version}")
def get_file_version_content(
    file_id: int,
    version: int,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    _require_slocum_mission_files()
    q = select(models.SlocumMissionFileVersion).where(
        models.SlocumMissionFileVersion.mission_file_id == file_id,
        models.SlocumMissionFileVersion.version == version,
    )
    v = session.exec(q).first()
    if not v:
        raise HTTPException(status_code=404, detail="Version not found")
    return {"version": v.version, "content": v.content, "changed_by_username": v.changed_by_username, "created_at_utc": v.created_at_utc}


@router.post("/files/{file_id}/revert/{version}")
def revert_file_to_version(
    file_id: int,
    version: int,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """Revert a mission file to a previous version. Creates a new version and changelog entry."""
    _require_slocum_mission_files()
    mf = session.get(models.SlocumMissionFile, file_id)
    if not mf or not mf.is_active:
        raise HTTPException(status_code=404, detail="File not found")
    q = select(models.SlocumMissionFileVersion).where(
        models.SlocumMissionFileVersion.mission_file_id == file_id,
        models.SlocumMissionFileVersion.version == version,
    )
    v = session.exec(q).first()
    if not v:
        raise HTTPException(status_code=404, detail="Version not found")
    mf.current_content = v.content
    mf.version += 1
    session.add(models.SlocumMissionFileVersion(
        mission_file_id=file_id,
        version=mf.version,
        content=v.content,
        changed_by_username=current_user.username,
        change_summary=f"Revert to version {version}",
        changed_parameters=[],
    ))
    session.add(models.SlocumMissionChangeLog(
        deployment_id=mf.deployment_id,
        mission_file_id=file_id,
        change_type="revert",
        description=f"Reverted {mf.file_name} to version {version}",
        changed_by_username=current_user.username,
        request_method="form",
        original_request=str(version),
    ))
    session.add(mf)
    session.commit()
    session.refresh(mf)
    return {"id": mf.id, "version": mf.version, "message": f"Reverted to version {version}"}


# --- Snapshots ---
@router.get("/deployments/{deployment_id}/snapshots", response_model=list[SlocumDeploymentSnapshotRead])
def list_snapshots(
    deployment_id: int,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    _require_slocum_mission_files()
    deployment = session.get(models.SlocumDeployment, deployment_id)
    if not deployment or not deployment.is_active:
        raise HTTPException(status_code=404, detail="Deployment not found")
    q = select(models.SlocumDeploymentSnapshot).where(
        models.SlocumDeploymentSnapshot.deployment_id == deployment_id
    ).order_by(models.SlocumDeploymentSnapshot.snapshot_number.asc())
    snapshots = session.exec(q).all()
    return [SlocumDeploymentSnapshotRead.model_validate(s) for s in snapshots]


@router.get("/deployments/{deployment_id}/snapshots/{snapshot_id}", response_model=SlocumDeploymentSnapshotRead)
def get_snapshot(
    deployment_id: int,
    snapshot_id: int,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    _require_slocum_mission_files()
    snap = session.get(models.SlocumDeploymentSnapshot, snapshot_id)
    if not snap or snap.deployment_id != deployment_id:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return snap


@router.get("/deployments/{deployment_id}/snapshots/{snapshot_id}/download")
def download_snapshot_zip(
    deployment_id: int,
    snapshot_id: int,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    _require_slocum_mission_files()
    snap = session.get(models.SlocumDeploymentSnapshot, snapshot_id)
    if not snap or snap.deployment_id != deployment_id:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    # Reconstruct file set from file versions at snapshot time
    file_states = snap.file_states or {}
    deployment = session.get(models.SlocumDeployment, deployment_id)
    if not deployment or not deployment.is_active:
        raise HTTPException(status_code=404, detail="Deployment not found")
    q = select(models.SlocumMissionFile).where(
        models.SlocumMissionFile.deployment_id == deployment_id,
        models.SlocumMissionFile.is_active == True,
    )
    mission_files = session.exec(q).all()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in mission_files:
            fn = f.file_name
            ver = (file_states.get(fn) or {}).get("version", f.version)
            vq = select(models.SlocumMissionFileVersion).where(
                models.SlocumMissionFileVersion.mission_file_id == f.id,
                models.SlocumMissionFileVersion.version == ver,
            )
            v = session.exec(vq).first()
            content = v.content if v else f.current_content
            zf.writestr(fn, content)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="snapshot_{snapshot_id}.zip"'},
    )


@router.get("/deployments/{deployment_id}/snapshots/compare")
def compare_snapshots(
    deployment_id: int,
    from_id: int = Query(..., alias="from"),
    to_id: int = Query(..., alias="to"),
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    _require_slocum_mission_files()
    s_from = session.get(models.SlocumDeploymentSnapshot, from_id)
    s_to = session.get(models.SlocumDeploymentSnapshot, to_id)
    if not s_from or s_from.deployment_id != deployment_id or not s_to or s_to.deployment_id != deployment_id:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    p_from = (s_from.parameter_summary or {}) or {}
    p_to = (s_to.parameter_summary or {}) or {}
    diff = {}
    all_keys = set(p_from) | set(p_to)
    for k in all_keys:
        v1, v2 = p_from.get(k), p_to.get(k)
        if v1 != v2:
            diff[k] = {"old": v1, "new": v2}
    return {"from_snapshot_id": from_id, "to_snapshot_id": to_id, "parameter_diff": diff}


# --- Changelog ---
@router.get("/deployments/{deployment_id}/changelog", response_model=list[SlocumMissionChangeLogRead])
def get_changelog(
    deployment_id: int,
    file_id: Optional[int] = Query(None),
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    _require_slocum_mission_files()
    deployment = session.get(models.SlocumDeployment, deployment_id)
    if not deployment or not deployment.is_active:
        raise HTTPException(status_code=404, detail="Deployment not found")
    q = select(models.SlocumMissionChangeLog).where(
        models.SlocumMissionChangeLog.deployment_id == deployment_id
    ).order_by(models.SlocumMissionChangeLog.created_at_utc.desc())
    if file_id is not None:
        q = q.where(models.SlocumMissionChangeLog.mission_file_id == file_id)
    logs = session.exec(q).all()
    return [SlocumMissionChangeLogRead.model_validate(l) for l in logs]
