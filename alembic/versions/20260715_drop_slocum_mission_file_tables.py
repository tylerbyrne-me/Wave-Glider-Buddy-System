"""drop_slocum_mission_file_tables

Revision ID: 20260715_drop_slocum_mission_files
Revises: 20260714_slocum_sensor_cards
Create Date: 2026-07-15

Drop mission-file-only tables. Keeps slocum_deployments and briefing metadata.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect


revision: str = "20260715_drop_slocum_mission_files"
down_revision: Union[str, Sequence[str], None] = "20260714_slocum_sensor_cards"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    # Drop in FK-safe order (dependents first).
    for table in (
        "slocum_mission_change_logs",
        "slocum_deployment_snapshots",
        "slocum_mission_file_versions",
        "slocum_mission_files",
    ):
        if inspector.has_table(table):
            op.drop_table(table)


def downgrade() -> None:
    # Intentionally empty: mission-file feature was removed and will not be restored
    # by reversing this migration. Recreate from 20260224_add_slocum_mission_file_tables
    # if a future rewrite needs these tables again.
    pass
