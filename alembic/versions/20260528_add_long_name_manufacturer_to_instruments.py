"""add_long_name_manufacturer_to_mission_instruments

Revision ID: 20260528_instrument_cols
Revises: 20260515_fluorometer_map
Create Date: 2026-05-28
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20260528_instrument_cols"
down_revision: Union[str, Sequence[str], None] = "20260515_fluorometer_map"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("mission_instruments")}
    if "instrument_long_name" not in columns:
        op.add_column(
            "mission_instruments",
            sa.Column("instrument_long_name", sa.String(), nullable=True),
        )
    if "instrument_manufacturer" not in columns:
        op.add_column(
            "mission_instruments",
            sa.Column("instrument_manufacturer", sa.String(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("mission_instruments")}
    if "instrument_manufacturer" in columns:
        op.drop_column("mission_instruments", "instrument_manufacturer")
    if "instrument_long_name" in columns:
        op.drop_column("mission_instruments", "instrument_long_name")
