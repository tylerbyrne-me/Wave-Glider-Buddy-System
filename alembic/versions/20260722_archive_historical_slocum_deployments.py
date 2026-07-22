"""Archive Slocum deployments linked to historical ERDDAP datasets.

Revision ID: 20260722_archive_hist_deps
Revises: 20260720_sfmc_snapshots
Create Date: 2026-07-22

One-shot data migration: set is_active=False and status='archived' for
deployments whose erddap_dataset_id or mission_key matches config
historical_slocum_datasets (including mission_key siblings).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260722_archive_hist_deps"
down_revision: Union[str, Sequence[str], None] = "20260720_sfmc_snapshots"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from app.config import settings
    from app.core.utils import slocum_mission_key

    historical_ids = {s.strip() for s in (settings.historical_slocum_datasets or []) if s and s.strip()}
    if not historical_ids:
        return

    historical_keys = {slocum_mission_key(hid) for hid in historical_ids if slocum_mission_key(hid)}
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, erddap_dataset_id, mission_key, is_active, status "
            "FROM slocum_deployments"
        )
    ).fetchall()

    to_archive: list[int] = []
    for row in rows:
        dep_id, erddap_id, mission_key, is_active, status = row
        if is_active is False and (status or "").strip().lower() == "archived":
            continue
        erddap = (erddap_id or "").strip()
        key = (mission_key or "").strip() or (slocum_mission_key(erddap) if erddap else "")
        if erddap in historical_ids or (key and key in historical_keys):
            to_archive.append(int(dep_id))

    if not to_archive:
        return

    # Update in batches for large DBs (still fine for small lists).
    for dep_id in to_archive:
        bind.execute(
            sa.text(
                "UPDATE slocum_deployments "
                "SET is_active = 0, status = 'archived' "
                "WHERE id = :id"
            ),
            {"id": dep_id},
        )


def downgrade() -> None:
    # Irreversible: we cannot know which rows were active before this migration.
    pass
