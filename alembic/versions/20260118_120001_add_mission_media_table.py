"""add_mission_media_table

Revision ID: 20260118_120001
Revises: d1c61203e080
Create Date: 2026-01-18 12:00:01.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260118_120001"
down_revision: Union[str, Sequence[str], None] = "d1c61203e080"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "mission_media",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("mission_id", sa.String(), nullable=False),
        sa.Column("media_type", sa.String(), nullable=False),
        sa.Column("file_path", sa.String(), nullable=False),
        sa.Column("file_name", sa.String(), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("mime_type", sa.String(), nullable=False),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("operation_type", sa.String(), nullable=True),
        sa.Column("uploaded_by_username", sa.String(), nullable=False),
        sa.Column("uploaded_at_utc", sa.DateTime(), nullable=False),
        sa.Column("thumbnail_path", sa.String(), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("is_featured", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_mission_media_mission_id", "mission_media", ["mission_id"], unique=False)
    op.create_index("ix_mission_media_uploaded_by_username", "mission_media", ["uploaded_by_username"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_mission_media_uploaded_by_username", table_name="mission_media")
    op.drop_index("ix_mission_media_mission_id", table_name="mission_media")
    op.drop_table("mission_media")
