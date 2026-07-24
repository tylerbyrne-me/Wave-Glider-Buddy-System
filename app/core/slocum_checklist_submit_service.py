"""
Slocum daily checklist submission helpers (HTTP + automated System submit).

Automated path uses ERDDAP autofill and cached SFMC snapshots only — never
forces a live SFMC refresh.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlmodel import Session, select

from . import models, utils
from .slocum_checklist_autofill import (
    CHECKLIST_FORM_TITLE,
    CHECKLIST_FORM_TYPE,
    load_checklist_autofill_values,
    parse_checklist_reference_values,
)
from .slocum_deployment_service import resolve_deployment_for_dataset
from .slocum_mirror_service import is_historical_dataset
from .sfmc_cache_service import get_cached_sfmc_values, refresh_sfmc_snapshot
from .sfmc_client import sfmc_is_configured
from ..forms.slocum_checklist_definitions import get_slocum_daily_checklist_schema

logger = logging.getLogger(__name__)

SYSTEM_USERNAME = "System"
AUTO_ITEM_COMMENT = "Not pilot-assessed — automated submission."


def utc_day_bounds(now_utc: Optional[datetime] = None) -> tuple[datetime, datetime]:
    """Return ``[start, end)`` for the UTC calendar day containing ``now_utc``."""
    base = now_utc or datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    else:
        base = base.astimezone(timezone.utc)
    start = datetime(base.year, base.month, base.day, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return start, end


def has_checklist_for_utc_day(
    session: Session,
    mission_key: str,
    day_start: datetime,
    day_end: datetime,
) -> bool:
    """True if a daily checklist already exists for ``mission_key`` in ``[day_start, day_end)``."""
    statement = (
        select(models.SubmittedForm.id)
        .where(
            models.SubmittedForm.form_type == CHECKLIST_FORM_TYPE,
            models.SubmittedForm.mission_id == mission_key,
            models.SubmittedForm.submission_timestamp >= day_start,
            models.SubmittedForm.submission_timestamp < day_end,
        )
        .limit(1)
    )
    return session.exec(statement).first() is not None


def apply_autofill_to_schema(
    schema: models.MissionFormSchema,
    autofill: dict[str, str],
) -> models.MissionFormSchema:
    for section in schema.sections:
        for item in section.items:
            if item.id in autofill and autofill[item.id] is not None:
                item.value = autofill[item.id]
    return schema


def format_sfmc_freshness_note(
    *,
    fetched_at_utc: Optional[datetime],
    fetch_error: Optional[str],
    has_values: bool,
) -> str:
    if fetched_at_utc is not None:
        stamp = fetched_at_utc.astimezone(timezone.utc).strftime("%H:%M UTC")
        note = f"SFMC data as of {stamp}"
        if fetch_error:
            note = f"{note} (last refresh error: {fetch_error[:120]})"
        return note
    if fetch_error:
        return f"SFMC unavailable: {fetch_error[:160]}"
    if has_values:
        return "SFMC data cached (fetch time unknown)"
    return "SFMC not yet fetched"


def apply_sfmc_freshness_to_schema(
    schema: models.MissionFormSchema,
    *,
    fetched_at_utc: Optional[datetime],
    fetch_error: Optional[str],
    has_values: bool,
    configured: bool,
) -> models.MissionFormSchema:
    if not configured:
        return schema
    note = format_sfmc_freshness_note(
        fetched_at_utc=fetched_at_utc,
        fetch_error=fetch_error,
        has_values=has_values,
    )
    for section in schema.sections:
        if section.id != "mission_status":
            continue
        base = (section.section_comment or "").rstrip()
        section.section_comment = f"{base} {note}".strip() if base else note
        break
    return schema


async def resolve_sfmc_values_for_template(
    session: Session,
    deployment: Optional[models.SlocumDeployment],
    *,
    force_refresh: bool = False,
    cache_only: bool = False,
) -> tuple[dict[str, str], Optional[datetime], Optional[str]]:
    """
    Return SFMC values for checklist autofill.

    When ``cache_only`` is True, never bootstrap or force-refresh — read the
    snapshot table only (automated submissions).
    """
    if deployment is None or not deployment.id:
        return {}, None, None

    values, fetched_at, fetch_error = get_cached_sfmc_values(session, deployment.id)
    if cache_only:
        return values, fetched_at, fetch_error

    needs_bootstrap = force_refresh or (fetched_at is None and not values and not fetch_error)
    if needs_bootstrap and sfmc_is_configured() and (deployment.glider_name or "").strip():
        try:
            row = await refresh_sfmc_snapshot(session, deployment)
            values = get_cached_sfmc_values(session, deployment.id)[0]
            return values, row.fetched_at_utc, row.fetch_error
        except Exception as err:
            logger.warning(
                "SFMC bootstrap/refresh failed for deployment %s: %s",
                deployment.id,
                err,
            )
            return values, fetched_at, str(err)[:2000]
    return values, fetched_at, fetch_error


async def build_checklist_autofilled_schema(
    *,
    dataset_id: str,
    pilot_username: str,
    session: Session,
    force_sfmc_refresh: bool = False,
    use_sfmc_cache_only: bool = False,
) -> models.MissionFormSchema:
    """Build checklist schema with live ERDDAP autofill and optional SFMC values."""
    deployment = resolve_deployment_for_dataset(session, dataset_id)
    references = parse_checklist_reference_values(
        deployment.checklist_reference_values if deployment else None
    )
    is_hist = is_historical_dataset(dataset_id)
    sfmc_values: dict[str, str] = {}
    fetched_at: Optional[datetime] = None
    fetch_error: Optional[str] = None
    if not is_hist:
        sfmc_values, fetched_at, fetch_error = await resolve_sfmc_values_for_template(
            session,
            deployment,
            force_refresh=force_sfmc_refresh and not use_sfmc_cache_only,
            cache_only=use_sfmc_cache_only,
        )
        if use_sfmc_cache_only and not sfmc_values:
            logger.info(
                "Auto checklist: SFMC cache empty for dataset %s (deployment_id=%s)",
                dataset_id,
                getattr(deployment, "id", None),
            )

    schema = get_slocum_daily_checklist_schema()
    try:
        autofill = await load_checklist_autofill_values(
            dataset_id,
            references,
            pilot_username=pilot_username,
            include_forecast=not is_hist,
            is_historical=is_hist,
            sfmc_values=sfmc_values,
        )
    except Exception as err:
        logger.exception("Checklist autofill failed for %s: %s", dataset_id, err)
        autofill = {
            "pilot_val": pilot_username,
            "dataset_id_val": dataset_id,
            "expected_mission_file_ref_val": str(references.get("expected_mission_file") or "—"),
            "expected_script_ref_val": str(references.get("expected_script") or "—"),
            "argos_id_ref_val": str(references.get("argos_id") or "—"),
            "u_alt_min_depth_ref_val": str(references.get("u_alt_min_depth") or "—"),
            "endurance_ref_val": f"{references.get('endurance_amphr_total') or '—'} Ah",
        }
        for key, val in (sfmc_values or {}).items():
            if val and key != "u_alt_min_depth_val":
                autofill[key] = val

    schema = apply_autofill_to_schema(schema, autofill)
    return apply_sfmc_freshness_to_schema(
        schema,
        fetched_at_utc=fetched_at,
        fetch_error=fetch_error,
        has_values=bool(sfmc_values),
        configured=sfmc_is_configured() and not is_hist,
    )


def _item_type_value(item: models.FormItem) -> str:
    raw = item.item_type
    return getattr(raw, "value", None) or str(raw)


def _is_empty_for_pilot_fill(value: Optional[str]) -> bool:
    """True when the field has no useful pilot/autofill content yet."""
    if value is None:
        return True
    return str(value).strip() == ""


def build_auto_sections_data(
    schema: models.MissionFormSchema,
    *,
    submitted_at_utc: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    """
    Build ``sections_data`` for an automated System submission.

    Keeps autofilled values unverified; fills empty judgment dropdowns with N/A
    when available; leaves other empty pilot fields blank with an automation comment.
    """
    stamp = submitted_at_utc or datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    else:
        stamp = stamp.astimezone(timezone.utc)
    stamp_iso = stamp.strftime("%Y-%m-%dT%H:%M:%SZ")
    banner = (
        f"Automated submission by {SYSTEM_USERNAME} at {stamp_iso} using available "
        "ERDDAP, cached SFMC, and reference data. Pilot-judgment items left N/A/blank "
        "and unverified."
    )

    sections_out: list[dict[str, Any]] = []
    for section in schema.sections:
        items_out: list[dict[str, Any]] = []
        section_comment = section.section_comment
        if section.id == "mission_status":
            base = (section_comment or "").rstrip()
            auto_note = "Automated System submission — values not pilot-verified."
            section_comment = f"{base} {auto_note}".strip() if base else auto_note

        for item in section.items:
            item_type = _item_type_value(item)
            value = item.value
            comment = item.comment
            is_verified: Optional[bool] = None

            if item.id == "pilot_val":
                value = SYSTEM_USERNAME
                is_verified = False
            elif item.id == "user_comments_val":
                value = banner
            elif item_type in (
                models.FormItemTypeEnum.AUTOFILLED_VALUE.value,
                models.FormItemTypeEnum.STATIC_TEXT.value,
            ):
                is_verified = False
            elif item_type == models.FormItemTypeEnum.DROPDOWN.value:
                if _is_empty_for_pilot_fill(value):
                    options = list(item.options or [])
                    if "N/A" in options:
                        value = "N/A"
                    else:
                        value = None
                    comment = AUTO_ITEM_COMMENT
                is_verified = False
            elif item_type in (
                models.FormItemTypeEnum.TEXT_INPUT.value,
                models.FormItemTypeEnum.TEXT_AREA.value,
            ):
                if _is_empty_for_pilot_fill(value):
                    value = None
                    comment = AUTO_ITEM_COMMENT

            items_out.append(
                {
                    "id": item.id,
                    "label": item.label,
                    "item_type": item_type,
                    "value": value,
                    "is_verified": is_verified,
                    "is_checked": item.is_checked,
                    "comment": comment,
                    "required": bool(item.required),
                    "options": list(item.options) if item.options else None,
                    "placeholder": item.placeholder,
                }
            )

        sections_out.append(
            {
                "id": section.id,
                "title": section.title,
                "items": items_out,
                "section_comment": section_comment,
            }
        )
    return sections_out


def persist_checklist_submission(
    session: Session,
    *,
    dataset_id: str,
    sections_data: list[dict[str, Any]],
    submitted_by: str = SYSTEM_USERNAME,
    form_type: Optional[str] = None,
    form_title: Optional[str] = None,
    submission_timestamp: Optional[datetime] = None,
) -> models.SubmittedForm:
    """Insert a checklist ``SubmittedForm`` row and commit."""
    mission_key = utils.slocum_mission_key(dataset_id) or dataset_id
    stamp = submission_timestamp or datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    submitted_form = models.SubmittedForm(
        mission_id=mission_key,
        form_type=form_type or CHECKLIST_FORM_TYPE,
        form_title=form_title or CHECKLIST_FORM_TITLE,
        submitted_by_username=submitted_by,
        submission_timestamp=stamp,
        sections_data=sections_data,
    )
    session.add(submitted_form)
    session.commit()
    session.refresh(submitted_form)
    return submitted_form


async def auto_submit_checklist_for_dataset(
    session: Session,
    dataset_id: str,
    *,
    now_utc: Optional[datetime] = None,
) -> Optional[models.SubmittedForm]:
    """
    If no checklist exists for this mission today (UTC), build and persist one as System.

    Returns the new form, or None when skipped (already submitted / historical).
    """
    if is_historical_dataset(dataset_id):
        logger.info("Auto checklist: skipping historical dataset %s", dataset_id)
        return None

    mission_key = utils.slocum_mission_key(dataset_id) or dataset_id
    day_start, day_end = utc_day_bounds(now_utc)
    if has_checklist_for_utc_day(session, mission_key, day_start, day_end):
        logger.info(
            "Auto checklist: skip %s (mission_key=%s) — already submitted for UTC day",
            dataset_id,
            mission_key,
        )
        return None

    stamp = now_utc or datetime.now(timezone.utc)
    schema = await build_checklist_autofilled_schema(
        dataset_id=dataset_id,
        pilot_username=SYSTEM_USERNAME,
        session=session,
        use_sfmc_cache_only=True,
    )
    sections_data = build_auto_sections_data(schema, submitted_at_utc=stamp)
    form = persist_checklist_submission(
        session,
        dataset_id=dataset_id,
        sections_data=sections_data,
        submitted_by=SYSTEM_USERNAME,
        submission_timestamp=stamp,
    )
    logger.info(
        "Auto checklist: submitted id=%s for %s (mission_key=%s) as %s",
        form.id,
        dataset_id,
        mission_key,
        SYSTEM_USERNAME,
    )
    return form
