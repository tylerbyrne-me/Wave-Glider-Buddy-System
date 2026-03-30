"""add_mos_pic_flags_to_users

Revision ID: 20260330_mos_pic_flags
Revises: 20260303_sensor_sampling
Create Date: 2026-03-30
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20260330_mos_pic_flags"
down_revision: Union[str, Sequence[str], None] = "20260303_sensor_sampling"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("users")}

    if "is_mos" not in columns:
        op.add_column(
            "users",
            sa.Column("is_mos", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        )
        op.create_index("ix_users_is_mos", "users", ["is_mos"])

    if "is_pic" not in columns:
        op.add_column(
            "users",
            sa.Column("is_pic", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        )
        op.create_index("ix_users_is_pic", "users", ["is_pic"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("users")}
    indexes = {ix["name"] for ix in inspector.get_indexes("users")}

    if "ix_users_is_pic" in indexes:
        op.drop_index("ix_users_is_pic", table_name="users")
    if "is_pic" in columns:
        op.drop_column("users", "is_pic")

    if "ix_users_is_mos" in indexes:
        op.drop_index("ix_users_is_mos", table_name="users")
    if "is_mos" in columns:
        op.drop_column("users", "is_mos")

