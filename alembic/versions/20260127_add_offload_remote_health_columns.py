"""add_offload_remote_health_columns

Revision ID: 20260127_remote_health
Revises: 20260123_125014
Create Date: 2026-01-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "20260127_remote_health"
down_revision: Union[str, Sequence[str], None] = "20260123_125014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add VM4 Remote Health columns to offload_logs."""
    bind = op.get_bind()
    inspector = inspect(bind)
    offload_columns = {col["name"] for col in inspector.get_columns("offload_logs")}
    
    new_columns = [
        ("remote_health_model_id", sa.String(), True),
        ("remote_health_serial_number", sa.String(), True),
        ("remote_health_modem_address", sa.Integer(), True),
        ("remote_health_temperature_c", sa.Float(), True),
        ("remote_health_tilt_rad", sa.Float(), True),
        ("remote_health_humidity", sa.Integer(), True),
    ]
    for col_name, col_type, nullable in new_columns:
        if col_name not in offload_columns:
            op.add_column(
                "offload_logs",
                sa.Column(col_name, col_type, nullable=nullable),
            )


def downgrade() -> None:
    """Remove VM4 Remote Health columns from offload_logs."""
    bind = op.get_bind()
    inspector = inspect(bind)
    offload_columns = {col["name"] for col in inspector.get_columns("offload_logs")}
    
    for col_name in (
        "remote_health_model_id",
        "remote_health_serial_number",
        "remote_health_modem_address",
        "remote_health_temperature_c",
        "remote_health_tilt_rad",
        "remote_health_humidity",
    ):
        if col_name in offload_columns:
            op.drop_column("offload_logs", col_name)
