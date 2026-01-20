"""add_sensor_tracker_token_to_users

Revision ID: 20260120_170000
Revises: 20260120_160000
Create Date: 2026-01-20 17:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "20260120_170000"
down_revision: Union[str, Sequence[str], None] = "20260120_160000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("users")}
    if "sensor_tracker_token" not in columns:
        op.add_column(
            "users",
            sa.Column("sensor_tracker_token", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("users")}
    if "sensor_tracker_token" in columns:
        op.drop_column("users", "sensor_tracker_token")
