"""add_sensor_long_name_manufacturer_to_mission_sensors

Revision ID: 20260528_sensor_cols
Revises: 20260528_instrument_cols
Create Date: 2026-05-28
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20260528_sensor_cols"
down_revision: Union[str, Sequence[str], None] = "20260528_instrument_cols"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("mission_sensors")}
    if "sensor_long_name" not in columns:
        op.add_column(
            "mission_sensors",
            sa.Column("sensor_long_name", sa.String(), nullable=True),
        )
    if "sensor_manufacturer" not in columns:
        op.add_column(
            "mission_sensors",
            sa.Column("sensor_manufacturer", sa.String(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("mission_sensors")}
    if "sensor_manufacturer" in columns:
        op.drop_column("mission_sensors", "sensor_manufacturer")
    if "sensor_long_name" in columns:
        op.drop_column("mission_sensors", "sensor_long_name")
