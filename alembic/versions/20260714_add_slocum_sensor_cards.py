"""add_slocum_sensor_cards

Revision ID: 20260714_slocum_sensor_cards
Revises: 20260714_slocum_document_url
Create Date: 2026-07-14

Enabled sensor cards JSON column on slocum_deployments.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20260714_slocum_sensor_cards"
down_revision: Union[str, Sequence[str], None] = "20260714_slocum_document_url"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table("slocum_deployments"):
        return
    columns = {col["name"] for col in inspector.get_columns("slocum_deployments")}
    if "enabled_sensor_cards" not in columns:
        op.add_column(
            "slocum_deployments",
            sa.Column("enabled_sensor_cards", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table("slocum_deployments"):
        return
    columns = {col["name"] for col in inspector.get_columns("slocum_deployments")}
    if "enabled_sensor_cards" in columns:
        op.drop_column("slocum_deployments", "enabled_sensor_cards")
