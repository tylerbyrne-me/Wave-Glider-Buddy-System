"""Re-activate Slocum deployments archived by historical backfill.

Revision ID: 20260722_reactivate_hist
Revises: 20260722_archive_hist_deps
Create Date: 2026-07-22

Undo of 20260722_archive_hist_deps: set is_active=True and status='active'
for deployments whose erddap_dataset_id or mission_key matches config
historical_slocum_datasets. Soft-deleted rows that were intentionally
archived outside that backfill are not distinguished; matching historical
rows are restored to active briefing state.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260722_reactivate_hist"
down_revision: Union[str, Sequence[str], None] = "20260722_archive_hist_deps"
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

    to_reactivate: list[int] = []
    for row in rows:
        dep_id, erddap_id, mission_key, is_active, status = row
        if is_active and (status or "").strip().lower() == "active":
            continue
        erddap = (erddap_id or "").strip()
        key = (mission_key or "").strip() or (slocum_mission_key(erddap) if erddap else "")
        if erddap in historical_ids or (key and key in historical_keys):
            to_reactivate.append(int(dep_id))

    for dep_id in to_reactivate:
        bind.execute(
            sa.text(
                "UPDATE slocum_deployments "
                "SET is_active = 1, status = 'active' "
                "WHERE id = :id"
            ),
            {"id": dep_id},
        )


def downgrade() -> None:
    # Re-apply historical archive (same as 20260722_archive_hist_deps upgrade).
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

    for row in rows:
        dep_id, erddap_id, mission_key, is_active, status = row
        if is_active is False and (status or "").strip().lower() == "archived":
            continue
        erddap = (erddap_id or "").strip()
        key = (mission_key or "").strip() or (slocum_mission_key(erddap) if erddap else "")
        if erddap in historical_ids or (key and key in historical_keys):
            bind.execute(
                sa.text(
                    "UPDATE slocum_deployments "
                    "SET is_active = 0, status = 'archived' "
                    "WHERE id = :id"
                ),
                {"id": int(dep_id)},
            )
