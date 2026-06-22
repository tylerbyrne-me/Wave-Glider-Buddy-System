"""add_submitted_form_edit_audit_columns

Revision ID: 20260622_form_edit_audit
Revises: 20260528_sensor_cols
Create Date: 2026-06-22

Add edited_by_username and last_edited_timestamp to submitted_forms for PIC edit audit.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20260622_form_edit_audit"
down_revision: Union[str, Sequence[str], None] = "20260528_sensor_cols"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table("submitted_forms"):
        return
    columns = {col["name"] for col in inspector.get_columns("submitted_forms")}
    if "edited_by_username" not in columns:
        op.add_column(
            "submitted_forms",
            sa.Column("edited_by_username", sa.String(), nullable=True),
        )
        op.create_index(
            "ix_submitted_forms_edited_by_username",
            "submitted_forms",
            ["edited_by_username"],
            unique=False,
        )
    if "last_edited_timestamp" not in columns:
        op.add_column(
            "submitted_forms",
            sa.Column("last_edited_timestamp", sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table("submitted_forms"):
        return
    columns = {col["name"] for col in inspector.get_columns("submitted_forms")}
    if "last_edited_timestamp" in columns:
        op.drop_column("submitted_forms", "last_edited_timestamp")
    if "edited_by_username" in columns:
        op.drop_index("ix_submitted_forms_edited_by_username", table_name="submitted_forms")
        op.drop_column("submitted_forms", "edited_by_username")
