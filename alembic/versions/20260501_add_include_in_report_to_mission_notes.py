"""add include_in_report to mission_notes

Revision ID: 20260501_note_include_flag
Revises: 20260429_pic_optional_sensors
Create Date: 2026-05-01
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20260501_note_include_flag"
down_revision: Union[str, Sequence[str], None] = "20260429_pic_optional_sensors"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("mission_notes")}
    if "include_in_report" not in columns:
        op.add_column(
            "mission_notes",
            sa.Column(
                "include_in_report",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
        )
        op.create_index(
            "ix_mission_notes_include_in_report",
            "mission_notes",
            ["include_in_report"],
            unique=False,
        )
        op.execute("UPDATE mission_notes SET include_in_report = 1 WHERE include_in_report IS NULL")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("mission_notes")}
    indexes = {idx["name"] for idx in inspector.get_indexes("mission_notes")}
    if "ix_mission_notes_include_in_report" in indexes:
        op.drop_index("ix_mission_notes_include_in_report", table_name="mission_notes")
    if "include_in_report" in columns:
        op.drop_column("mission_notes", "include_in_report")
