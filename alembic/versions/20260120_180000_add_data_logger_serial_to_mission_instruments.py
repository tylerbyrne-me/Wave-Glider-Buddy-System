"""add_data_logger_serial_to_mission_instruments

Revision ID: 20260120_180000
Revises: 20260127_remote_health
Create Date: 2026-01-20 18:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "20260120_180000"
down_revision: Union[str, Sequence[str], None] = "20260127_remote_health"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add data_logger_serial to mission_instruments."""
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("mission_instruments")}
    if "data_logger_serial" not in columns:
        op.add_column(
            "mission_instruments",
            sa.Column("data_logger_serial", sa.String(), nullable=True),
        )


def downgrade() -> None:
    """Remove data_logger_serial from mission_instruments."""
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("mission_instruments")}
    if "data_logger_serial" in columns:
        op.drop_column("mission_instruments", "data_logger_serial")
