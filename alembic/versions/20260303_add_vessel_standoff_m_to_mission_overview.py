"""add_vessel_standoff_m_to_mission_overview

Revision ID: 20260303_vessel_standoff
Revises: 20260303_battery_apu
Create Date: 2026-03-03

Add vessel_standoff_m to mission_overview for PIC form (distance in m for auto-avoidance).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20260303_vessel_standoff"
down_revision: Union[str, Sequence[str], None] = "20260303_battery_apu"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("mission_overview")}
    if "vessel_standoff_m" not in columns:
        op.add_column(
            "mission_overview",
            sa.Column("vessel_standoff_m", sa.Integer(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("mission_overview")}
    if "vessel_standoff_m" in columns:
        op.drop_column("mission_overview", "vessel_standoff_m")
