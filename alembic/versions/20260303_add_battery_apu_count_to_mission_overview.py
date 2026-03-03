"""add_battery_apu_count_to_mission_overview

Revision ID: 20260303_battery_apu
Revises: 20260224_erddap
Create Date: 2026-03-03

Add battery_apu_count to mission_overview for Wave Glider theoretical max (980 + APU*980 Wh).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20260303_battery_apu"
down_revision: Union[str, Sequence[str], None] = "20260224_erddap"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("mission_overview")}
    if "battery_apu_count" not in columns:
        op.add_column(
            "mission_overview",
            sa.Column("battery_apu_count", sa.Integer(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("mission_overview")}
    if "battery_apu_count" in columns:
        op.drop_column("mission_overview", "battery_apu_count")
