"""add pic_handoff_optional_sensors to mission_overview

Revision ID: 20260429_pic_optional_sensors
Revises: 20260429_vrl_verified
Create Date: 2026-04-29
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20260429_pic_optional_sensors"
down_revision: Union[str, Sequence[str], None] = "20260429_vrl_verified"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("mission_overview")}
    if "pic_handoff_optional_sensors" not in columns:
        op.add_column(
            "mission_overview",
            sa.Column("pic_handoff_optional_sensors", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("mission_overview")}
    if "pic_handoff_optional_sensors" in columns:
        op.drop_column("mission_overview", "pic_handoff_optional_sensors")
