"""add vrl_verified_on_rudics to offload_logs

Revision ID: 20260429_vrl_verified
Revises: 20260428_remote_health_date
Create Date: 2026-04-29
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20260429_vrl_verified"
down_revision: Union[str, Sequence[str], None] = "20260428_remote_health_date"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    offload_columns = {col["name"] for col in inspector.get_columns("offload_logs")}
    if "vrl_verified_on_rudics" not in offload_columns:
        op.add_column(
            "offload_logs",
            sa.Column("vrl_verified_on_rudics", sa.Boolean(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    offload_columns = {col["name"] for col in inspector.get_columns("offload_logs")}
    if "vrl_verified_on_rudics" in offload_columns:
        op.drop_column("offload_logs", "vrl_verified_on_rudics")
