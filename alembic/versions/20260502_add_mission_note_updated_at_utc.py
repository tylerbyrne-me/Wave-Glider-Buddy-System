"""add updated_at_utc to mission_notes

Revision ID: 20260502_mission_note_updated_at
Revises: 20260501_note_include_flag
Create Date: 2026-05-02
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20260502_mission_note_updated_at"
down_revision: Union[str, Sequence[str], None] = "20260501_note_include_flag"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("mission_notes")}
    if "updated_at_utc" not in columns:
        op.add_column(
            "mission_notes",
            sa.Column("updated_at_utc", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("mission_notes")}
    if "updated_at_utc" in columns:
        op.drop_column("mission_notes", "updated_at_utc")
