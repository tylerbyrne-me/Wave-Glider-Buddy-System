"""add_user_platform_access_flags

Revision ID: 20260702_user_platform_access
Revises: 20260625_slocum_metadata
Create Date: 2026-07-02

Per-user Wave Glider / Slocum platform access flags on users table.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20260702_user_platform_access"
down_revision: Union[str, Sequence[str], None] = "20260625_slocum_metadata"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("users")}

    if "can_access_wave_glider" not in columns:
        op.add_column(
            "users",
            sa.Column("can_access_wave_glider", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        )
        op.create_index("ix_users_can_access_wave_glider", "users", ["can_access_wave_glider"])

    if "can_access_slocum" not in columns:
        op.add_column(
            "users",
            sa.Column("can_access_slocum", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        )
        op.create_index("ix_users_can_access_slocum", "users", ["can_access_slocum"])

    if inspector.has_table("announcement"):
        ann_columns = {col["name"] for col in inspector.get_columns("announcement")}
        if "platform" not in ann_columns:
            op.add_column(
                "announcement",
                sa.Column("platform", sa.String(), nullable=False, server_default="all"),
            )
            op.create_index("ix_announcement_platform", "announcement", ["platform"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if inspector.has_table("announcement"):
        ann_indexes = {ix["name"] for ix in inspector.get_indexes("announcement")}
        ann_columns = {col["name"] for col in inspector.get_columns("announcement")}
        if "ix_announcement_platform" in ann_indexes:
            op.drop_index("ix_announcement_platform", table_name="announcement")
        if "platform" in ann_columns:
            op.drop_column("announcement", "platform")

    columns = {col["name"] for col in inspector.get_columns("users")}
    indexes = {ix["name"] for ix in inspector.get_indexes("users")}

    if "ix_users_can_access_slocum" in indexes:
        op.drop_index("ix_users_can_access_slocum", table_name="users")
    if "can_access_slocum" in columns:
        op.drop_column("users", "can_access_slocum")

    if "ix_users_can_access_wave_glider" in indexes:
        op.drop_index("ix_users_can_access_wave_glider", table_name="users")
    if "can_access_wave_glider" in columns:
        op.drop_column("users", "can_access_wave_glider")
