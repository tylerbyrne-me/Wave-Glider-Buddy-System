"""
Slocum deployment identity helpers.

SlocumDeployment is the briefing/metadata owner for an ERDDAP mission (shared by
realtime and delayed datasets via ``mission_key``), analogous to Wave Glider
MissionOverview for a mission folder id. Rows are get-or-created from the
dataset id — no separate manual "link" step.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import select

from . import models, utils
from .infra.db import SQLModelSession

logger = logging.getLogger(__name__)


def resolve_deployment_for_dataset(
    session: SQLModelSession,
    dataset_id: str,
) -> Optional[models.SlocumDeployment]:
    mission_key = utils.slocum_mission_key(dataset_id)
    if not mission_key:
        return None

    by_key = session.exec(
        select(models.SlocumDeployment).where(
            models.SlocumDeployment.mission_key == mission_key,
            models.SlocumDeployment.is_active == True,  # noqa: E712
        )
    ).first()
    if by_key:
        return by_key

    # Legacy fallback: rows created before mission_key existed / was backfilled.
    # Match exact dataset id or a realtime/delayed sibling for the same mission key.
    candidate_ids = {
        dataset_id,
        mission_key,
        f"{mission_key}_realtime",
        f"{mission_key}_delayed",
    }
    return session.exec(
        select(models.SlocumDeployment).where(
            models.SlocumDeployment.erddap_dataset_id.in_(candidate_ids),
            models.SlocumDeployment.is_active == True,  # noqa: E712
        )
    ).first()


def get_or_create_deployment_for_dataset(
    session: SQLModelSession,
    dataset_id: str,
    *,
    created_by_username: str,
) -> Optional[models.SlocumDeployment]:
    """
    Return the active SlocumDeployment for ``dataset_id``, creating one if needed.

    Resolution is by suffix-agnostic ``mission_key`` so realtime and delayed
    datasets share the same briefing metadata. When an existing deployment is
    resolved from a different dataset id (e.g. delayed after realtime),
    ``erddap_dataset_id`` is updated to the most recently seen id.

    Returns None when the dataset id cannot be parsed (same gate as Sensor Tracker
    mission-code derivation).
    """
    existing = resolve_deployment_for_dataset(session, dataset_id)
    if existing:
        changed = False
        mission_key = utils.slocum_mission_key(dataset_id)
        if mission_key and not existing.mission_key:
            existing.mission_key = mission_key
            changed = True
        if dataset_id and existing.erddap_dataset_id != dataset_id:
            existing.erddap_dataset_id = dataset_id
            changed = True
        if changed:
            existing.updated_at_utc = datetime.now(timezone.utc)
            session.add(existing)
            session.commit()
            session.refresh(existing)
            logger.info(
                "Updated SlocumDeployment id=%s mission_key=%s erddap_dataset_id=%s",
                existing.id,
                existing.mission_key,
                existing.erddap_dataset_id,
            )
        return existing

    parsed = utils.parse_slocum_dataset_id(dataset_id)
    if not parsed:
        logger.warning("Cannot create SlocumDeployment for unparseable dataset id: %s", dataset_id)
        return None

    start_date = parsed.get("start_date")
    deployment_date = None
    if start_date is not None:
        deployment_date = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=timezone.utc)

    glider_name = parsed["glider_name"]
    mission_key = utils.slocum_mission_key(dataset_id)
    name = f"{glider_name} {start_date}" if start_date is not None else f"{glider_name} {dataset_id}"
    deployment = models.SlocumDeployment(
        name=name,
        glider_name=glider_name,
        deployment_date=deployment_date,
        mission_key=mission_key,
        erddap_dataset_id=dataset_id,
        status="active",
        created_by_username=created_by_username or "system",
    )
    session.add(deployment)
    session.commit()
    session.refresh(deployment)
    logger.info(
        "Auto-created SlocumDeployment id=%s for dataset_id=%s mission_key=%s (by %s)",
        deployment.id,
        dataset_id,
        mission_key,
        created_by_username,
    )
    return deployment
