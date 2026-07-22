"""
Persist and refresh SFMC-derived checklist autofill per Slocum deployment.

One snapshot row per deployment is upserted by a leader-only background job
(and by the pilot-facing force-refresh endpoint). Checklist template reads
prefer the cache so page loads do not wait on live SFMC HTTP.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlmodel import Session, select

from . import models
from .sfmc_client import load_sfmc_checklist_values, sfmc_is_configured
from .slocum_mirror_service import is_historical_dataset

logger = logging.getLogger(__name__)


def _deployment_linked_to_historical(deployment: models.SlocumDeployment) -> bool:
    """True when this briefing points at a config-listed historical ERDDAP mission."""
    if deployment.erddap_dataset_id and is_historical_dataset(deployment.erddap_dataset_id):
        return True
    if deployment.mission_key and is_historical_dataset(deployment.mission_key):
        return True
    return False

def _parse_values_json(raw: Optional[str]) -> dict[str, str]:
    if not raw or not str(raw).strip():
        return {}
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in payload.items():
        if value is None:
            continue
        text = str(value).strip()
        if text:
            out[str(key)] = text
    return out


def _dump_values_json(values: dict[str, str]) -> str:
    cleaned = {
        str(key): str(value).strip()
        for key, value in (values or {}).items()
        if value is not None and str(value).strip()
    }
    return json.dumps(cleaned, ensure_ascii=True, sort_keys=True)


def get_cached_sfmc_values(
    session: Session,
    deployment_id: Optional[int],
) -> tuple[dict[str, str], Optional[datetime], Optional[str]]:
    """
    Return ``(values, fetched_at_utc, fetch_error)`` for a deployment.

    Missing row → ``({}, None, None)``.
    """
    if deployment_id is None:
        return {}, None, None
    row = session.exec(
        select(models.SlocumSfmcSnapshot).where(
            models.SlocumSfmcSnapshot.deployment_id == deployment_id
        )
    ).first()
    if row is None:
        return {}, None, None
    return _parse_values_json(row.values_json), row.fetched_at_utc, row.fetch_error


def _get_or_create_snapshot(
    session: Session,
    deployment: models.SlocumDeployment,
) -> models.SlocumSfmcSnapshot:
    row = session.exec(
        select(models.SlocumSfmcSnapshot).where(
            models.SlocumSfmcSnapshot.deployment_id == deployment.id
        )
    ).first()
    if row is not None:
        return row
    row = models.SlocumSfmcSnapshot(
        deployment_id=int(deployment.id),
        glider_name=(deployment.glider_name or "").strip(),
        values_json="{}",
        fetched_at_utc=None,
        fetch_error=None,
        updated_at_utc=datetime.now(timezone.utc),
    )
    session.add(row)
    session.flush()
    return row


async def refresh_sfmc_snapshot(
    session: Session,
    deployment: models.SlocumDeployment,
) -> models.SlocumSfmcSnapshot:
    """
    Fetch live SFMC checklist values and upsert the deployment snapshot.

    On failure, records ``fetch_error`` and keeps the previous ``values_json``
    (last-known-good). Caller is responsible for committing when desired.
    """
    glider = (deployment.glider_name or "").strip()
    row = _get_or_create_snapshot(session, deployment)
    row.glider_name = glider
    row.updated_at_utc = datetime.now(timezone.utc)

    if not glider:
        row.fetch_error = "Deployment has no glider_name"
        session.add(row)
        session.commit()
        session.refresh(row)
        return row

    # Placeholder / sandbox briefings are not SFMC vehicles (legacy local "Testing" row).
    if glider.lower() in {"testing", "test", "dummy"}:
        row.fetch_error = f"Skipping SFMC for placeholder glider_name={glider!r}"
        session.add(row)
        session.commit()
        session.refresh(row)
        return row

    if not (deployment.erddap_dataset_id or "").strip():
        row.fetch_error = "Skipping SFMC: deployment has no erddap_dataset_id"
        session.add(row)
        session.commit()
        session.refresh(row)
        return row

    if not sfmc_is_configured():
        row.fetch_error = "SFMC is not configured"
        session.add(row)
        session.commit()
        session.refresh(row)
        return row

    try:
        values = await load_sfmc_checklist_values(glider)
        row.values_json = _dump_values_json(values)
        row.fetched_at_utc = datetime.now(timezone.utc)
        row.fetch_error = None
    except Exception as err:
        logger.warning(
            "SFMC snapshot refresh failed for deployment %s (%s): %s",
            deployment.id,
            glider,
            err,
        )
        # Keep previous values_json; surface the error for UI freshness notes.
        row.fetch_error = str(err)[:2000]
        row.updated_at_utc = datetime.now(timezone.utc)

    session.add(row)
    session.commit()
    session.refresh(row)
    return row


async def refresh_all_active_sfmc_snapshots(session: Session) -> dict[str, Any]:
    """
    Refresh SFMC snapshots for every non-soft-deleted deployment with a glider name.

    Skips deployments linked to config historical datasets.
    Per-deployment failures are isolated. Returns summary counts.
    """
    if not sfmc_is_configured():
        return {
            "skipped": True,
            "reason": "sfmc_not_configured",
            "attempted": 0,
            "succeeded": 0,
            "failed": 0,
        }

    deployments = session.exec(
        select(models.SlocumDeployment).where(
            models.SlocumDeployment.is_active == True  # noqa: E712
        )
    ).all()

    attempted = 0
    succeeded = 0
    failed = 0
    for deployment in deployments:
        if _deployment_linked_to_historical(deployment):
            continue
        glider = (deployment.glider_name or "").strip()
        if not glider or glider.lower() in {"testing", "test", "dummy"}:
            continue
        if not (deployment.erddap_dataset_id or "").strip():
            continue
        attempted += 1
        try:
            row = await refresh_sfmc_snapshot(session, deployment)
            if row.fetch_error:
                failed += 1
            else:
                succeeded += 1
        except Exception as err:
            failed += 1
            logger.warning(
                "SFMC snapshot job failed for deployment %s (%s): %s",
                getattr(deployment, "id", None),
                glider,
                err,
            )

    return {
        "skipped": False,
        "attempted": attempted,
        "succeeded": succeeded,
        "failed": failed,
    }
