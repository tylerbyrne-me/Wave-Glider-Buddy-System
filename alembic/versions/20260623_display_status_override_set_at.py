"""display_status_override_set_at_utc

Revision ID: 20260623_override_set_at
Revises: 20260622_form_edit_audit
Create Date: 2026-06-23

Track when display_status_override was set so newer offload logs supersede it.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20260623_override_set_at"
down_revision: Union[str, Sequence[str], None] = "20260622_form_edit_audit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table("station_metadata"):
        return
    columns = {col["name"] for col in inspector.get_columns("station_metadata")}
    if "display_status_override_set_at_utc" not in columns:
        op.add_column(
            "station_metadata",
            sa.Column("display_status_override_set_at_utc", sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table("station_metadata"):
        return
    columns = {col["name"] for col in inspector.get_columns("station_metadata")}
    if "display_status_override_set_at_utc" in columns:
        op.drop_column("station_metadata", "display_status_override_set_at_utc")
