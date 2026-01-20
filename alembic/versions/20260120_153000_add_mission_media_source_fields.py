"""add_mission_media_source_fields

Revision ID: 20260120_153000
Revises: 20260118_133000
Create Date: 2026-01-20 15:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260120_153000"
down_revision: Union[str, Sequence[str], None] = "20260118_133000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("mission_media", sa.Column("source_system", sa.String(), nullable=True))
    op.add_column("mission_media", sa.Column("source_url", sa.String(), nullable=True))
    op.add_column("mission_media", sa.Column("source_external_id", sa.String(), nullable=True))

    op.create_index("ix_mission_media_source_system", "mission_media", ["source_system"])
    op.create_index("ix_mission_media_source_url", "mission_media", ["source_url"])
    op.create_index("ix_mission_media_source_external_id", "mission_media", ["source_external_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_mission_media_source_external_id", table_name="mission_media")
    op.drop_index("ix_mission_media_source_url", table_name="mission_media")
    op.drop_index("ix_mission_media_source_system", table_name="mission_media")

    op.drop_column("mission_media", "source_external_id")
    op.drop_column("mission_media", "source_url")
    op.drop_column("mission_media", "source_system")
