"""add_slocum_checklist_reference_values

Revision ID: 20260715_slocum_checklist_refs
Revises: 20260715_drop_slocum_mission_files
Create Date: 2026-07-15

JSON text column for admin-managed daily checklist reference values.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20260715_slocum_checklist_refs"
down_revision: Union[str, Sequence[str], None] = "20260715_drop_slocum_mission_files"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table("slocum_deployments"):
        return
    columns = {col["name"] for col in inspector.get_columns("slocum_deployments")}
    if "checklist_reference_values" not in columns:
        op.add_column(
            "slocum_deployments",
            sa.Column("checklist_reference_values", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table("slocum_deployments"):
        return
    columns = {col["name"] for col in inspector.get_columns("slocum_deployments")}
    if "checklist_reference_values" in columns:
        op.drop_column("slocum_deployments", "checklist_reference_values")
