"""add_platform_to_live_kml_tokens

Revision ID: 20260720_live_kml_platform
Revises: 20260715_slocum_mission_key
Create Date: 2026-07-20

Add platform column so Live KML tokens can serve Wave Glider or Slocum tracks.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20260720_live_kml_platform"
down_revision: Union[str, Sequence[str], None] = "20260715_slocum_mission_key"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table("live_kml_tokens"):
        return
    columns = {col["name"] for col in inspector.get_columns("live_kml_tokens")}
    if "platform" not in columns:
        op.add_column(
            "live_kml_tokens",
            sa.Column(
                "platform",
                sa.String(length=32),
                nullable=False,
                server_default="wave_glider",
            ),
        )
        op.create_index(
            "ix_live_kml_tokens_platform",
            "live_kml_tokens",
            ["platform"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table("live_kml_tokens"):
        return
    columns = {col["name"] for col in inspector.get_columns("live_kml_tokens")}
    if "platform" in columns:
        op.drop_index("ix_live_kml_tokens_platform", table_name="live_kml_tokens")
        op.drop_column("live_kml_tokens", "platform")
