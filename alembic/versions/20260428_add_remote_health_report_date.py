"""add remote_health_report_date to offload_logs

Revision ID: 20260428_remote_health_date
Revises: 20260427_station_flags
Create Date: 2026-04-28
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20260428_remote_health_date"
down_revision: Union[str, Sequence[str], None] = "20260427_station_flags"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    offload_columns = {col["name"] for col in inspector.get_columns("offload_logs")}
    if "remote_health_report_date" not in offload_columns:
        op.add_column(
            "offload_logs",
            sa.Column("remote_health_report_date", sa.Date(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    offload_columns = {col["name"] for col in inspector.get_columns("offload_logs")}
    if "remote_health_report_date" in offload_columns:
        op.drop_column("offload_logs", "remote_health_report_date")
