"""
Slocum daily pilot checklist API and form page.

Stores submissions in ``submitted_forms`` with
``form_type=slocum_daily_checklist`` and ``mission_id`` = suffix-agnostic
Slocum mission key (shared by realtime and delayed datasets).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional

import pandas as pd
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import select

from ..core import models, utils
from ..core.auth import get_current_active_user, get_optional_current_user, require_platform_access
from ..core.infra.db import SQLModelSession, get_db_session
from ..core.infra.feature_toggles import is_feature_enabled
from ..core.slocum_checklist_autofill import (
    CHECKLIST_FORM_TITLE,
    CHECKLIST_FORM_TYPE,
    CHECKLIST_HOURS_BACK,
    CHECKLIST_SERIES_MAX_HOURS_BACK,
    build_checklist_series_payload,
    get_plottable_spec,
    parse_checklist_reference_values,
)
from ..core.slocum_checklist_submit_service import (
    build_checklist_autofilled_schema,
    persist_checklist_submission,
)
from ..core.slocum_deployment_service import resolve_deployment_for_dataset
from ..core.slocum_mirror_service import is_historical_dataset
from ..core.slocum_overage_cache import OverageResult
from ..core.template_context import get_template_context
from ..core.templates import templates

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Slocum Checklists"])

_slocum_access = Depends(require_platform_access("slocum"))


def _require_slocum_platform() -> None:
    if not is_feature_enabled("slocum_platform"):
        raise HTTPException(status_code=403, detail="Slocum platform is disabled.")


def _can_edit_submitted_form(db_form: models.SubmittedForm, current_user: models.User) -> bool:
    role = current_user.role
    role_value = getattr(role, "value", None) or str(role)
    if role_value == "admin":
        return True
    return db_form.submitted_by_username == current_user.username


async def _build_checklist_template_schema(
    *,
    dataset_id: str,
    current_user: models.User,
    session: SQLModelSession,
    force_sfmc_refresh: bool = False,
) -> models.MissionFormSchema:
    return await build_checklist_autofilled_schema(
        dataset_id=dataset_id,
        pilot_username=current_user.username,
        session=session,
        force_sfmc_refresh=force_sfmc_refresh,
        use_sfmc_cache_only=False,
    )


@router.get(
    "/api/slocum/checklists/id/{form_db_id}",
    response_model=models.SubmittedForm,
    dependencies=[_slocum_access],
)
def get_checklist_by_id(
    form_db_id: int,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    _require_slocum_platform()
    db_form = session.get(models.SubmittedForm, form_db_id)
    if not db_form or db_form.form_type != CHECKLIST_FORM_TYPE:
        raise HTTPException(status_code=404, detail="Checklist submission not found")
    return db_form


@router.put(
    "/api/slocum/checklists/id/{form_db_id}",
    response_model=models.SubmittedForm,
    dependencies=[_slocum_access],
)
async def update_checklist(
    form_db_id: int,
    form_data: dict = Body(...),
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    _require_slocum_platform()
    db_form = session.get(models.SubmittedForm, form_db_id)
    if not db_form or db_form.form_type != CHECKLIST_FORM_TYPE:
        raise HTTPException(status_code=404, detail="Checklist submission not found")
    if not _can_edit_submitted_form(db_form, current_user):
        raise HTTPException(status_code=403, detail="Not allowed to edit this checklist")
    if "sections_data" in form_data:
        db_form.sections_data = form_data["sections_data"]
    if form_data.get("form_title"):
        db_form.form_title = form_data["form_title"]
    db_form.edited_by_username = current_user.username
    db_form.last_edited_timestamp = datetime.now(timezone.utc)
    session.add(db_form)
    session.commit()
    session.refresh(db_form)
    return db_form


@router.get(
    "/api/slocum/checklists/{dataset_id}/template",
    response_model=models.MissionFormSchema,
    dependencies=[_slocum_access],
)
async def get_checklist_template(
    dataset_id: str,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """Return checklist schema with live autofill and admin reference displays."""
    _require_slocum_platform()
    return await _build_checklist_template_schema(
        dataset_id=dataset_id,
        current_user=current_user,
        session=session,
        force_sfmc_refresh=False,
    )


@router.post(
    "/api/slocum/checklists/{dataset_id}/sfmc-refresh",
    response_model=models.MissionFormSchema,
    dependencies=[_slocum_access],
)
async def refresh_checklist_sfmc(
    dataset_id: str,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """Force a live SFMC pull for this deployment, then return the refreshed template."""
    _require_slocum_platform()
    return await _build_checklist_template_schema(
        dataset_id=dataset_id,
        current_user=current_user,
        session=session,
        force_sfmc_refresh=True,
    )


@router.get(
    "/api/slocum/checklists/{dataset_id}/series",
    dependencies=[_slocum_access],
)
async def get_checklist_series(
    dataset_id: str,
    item_id: str = Query(..., description="Checklist form item id (e.g. depth_rate_val)"),
    hours_back: int = Query(
        CHECKLIST_HOURS_BACK,
        ge=1,
        le=CHECKLIST_SERIES_MAX_HOURS_BACK,
        description="Hours of checklist bundle data to plot",
    ),
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """
    Dual time-series for Plot-it: depth (m) + the selected checklist variable.

    Temporary client-side charts only — no disk artifacts.
    """
    _require_slocum_platform()
    if get_plottable_spec(item_id) is None:
        raise HTTPException(
            status_code=404,
            detail=f"Checklist item '{item_id}' is not plottable",
        )

    from ..core.slocum_cache_service import get_cached_or_fetch_bundle_df

    deployment = resolve_deployment_for_dataset(session, dataset_id)
    references = parse_checklist_reference_values(
        deployment.checklist_reference_values if deployment else None
    )
    depth_class = str(references.get("glider_depth_class") or "").strip() or None

    is_historical = is_historical_dataset(dataset_id)
    try:
        result = await get_cached_or_fetch_bundle_df(
            dataset_id,
            "checklist",
            None,
            None,
            hours_back=hours_back,
            is_historical=is_historical,
            context="interactive",
            return_metadata=True,
        )
    except Exception as err:
        logger.exception("Checklist series fetch failed for %s: %s", dataset_id, err)
        raise HTTPException(status_code=502, detail=f"Failed to load checklist data: {err}") from err

    cache_metadata: dict = {}
    if isinstance(result, OverageResult):
        df = result.df if result.df is not None else pd.DataFrame()
        cache_metadata = dict(result.metadata or {})
    elif result is None:
        df = pd.DataFrame()
    else:
        df = result

    try:
        return build_checklist_series_payload(
            df,
            item_id,
            cache_metadata=cache_metadata,
            depth_class=depth_class,
        )
    except KeyError as err:
        raise HTTPException(
            status_code=404,
            detail=f"Checklist item '{item_id}' is not plottable",
        ) from err


@router.get(
    "/api/slocum/checklists/{dataset_id}",
    response_model=List[models.SubmittedForm],
    dependencies=[_slocum_access],
)
def list_checklists_for_dataset(
    dataset_id: str,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    _require_slocum_platform()
    mission_key = utils.slocum_mission_key(dataset_id) or dataset_id
    statement = (
        select(models.SubmittedForm)
        .where(
            models.SubmittedForm.form_type == CHECKLIST_FORM_TYPE,
            models.SubmittedForm.mission_id == mission_key,
        )
        .order_by(models.SubmittedForm.submission_timestamp.desc())
    )
    return list(session.exec(statement).all())


@router.post(
    "/api/slocum/checklists/{dataset_id}",
    dependencies=[_slocum_access],
)
async def submit_checklist(
    dataset_id: str,
    form_data: dict = Body(...),
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    _require_slocum_platform()
    mission_key = utils.slocum_mission_key(dataset_id) or dataset_id
    try:
        sections_data = form_data.get("sections_data")
        submitted_form = persist_checklist_submission(
            session,
            dataset_id=dataset_id,
            sections_data=sections_data,
            submitted_by=current_user.username,
            form_type=form_data.get("form_type") or CHECKLIST_FORM_TYPE,
            form_title=form_data.get("form_title") or CHECKLIST_FORM_TITLE,
        )
        return {
            "message": "Checklist submitted successfully",
            "id": submitted_form.id,
            "dataset_id": dataset_id,
            "mission_key": mission_key,
            "submitted_by_username": current_user.username,
            "submission_timestamp": submitted_form.submission_timestamp.isoformat(),
        }
    except Exception as err:
        logger.exception("Error saving Slocum checklist")
        raise HTTPException(status_code=500, detail=f"Failed to save checklist: {err}") from err


@router.get("/slocum/dataset/{dataset_id}/checklist.html", response_class=HTMLResponse)
async def get_checklist_form_page(
    request: Request,
    dataset_id: str,
    edit: Optional[int] = Query(None, description="Submitted form id to edit"),
    current_user: Optional[models.User] = Depends(get_optional_current_user),
):
    """HTML page for filling / editing a Slocum daily checklist."""
    if not current_user:
        return RedirectResponse(url="/login.html")
    if not is_feature_enabled("slocum_platform"):
        return RedirectResponse(url="/platform")
    context = get_template_context(request=request, current_user=current_user)
    context["platform"] = "slocum"
    context["platform_home_url"] = "/slocum/home"
    context["show_banner_nav"] = True
    context["dataset_id"] = dataset_id
    context["edit_form_id"] = edit
    return templates.TemplateResponse("slocum_checklist_form.html", context)
