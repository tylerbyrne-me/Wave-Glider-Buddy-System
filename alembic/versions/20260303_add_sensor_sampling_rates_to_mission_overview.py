"""add_sensor_sampling_rates_to_mission_overview

Revision ID: 20260303_sensor_sampling
Revises: 20260303_vessel_standoff
Create Date: 2026-03-03

Add sensor_sampling_rates (JSON text) to mission_overview for PIC form persistence.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20260303_sensor_sampling"
down_revision: Union[str, Sequence[str], None] = "20260303_vessel_standoff"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("mission_overview")}
    if "sensor_sampling_rates" not in columns:
        op.add_column(
            "mission_overview",
            sa.Column("sensor_sampling_rates", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("mission_overview")}
    if "sensor_sampling_rates" in columns:
        op.drop_column("mission_overview", "sensor_sampling_rates")
