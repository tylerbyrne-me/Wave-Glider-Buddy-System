"""add_media_approval_and_announcement_targets

Revision ID: 20260118_133000
Revises: 79c4d8f8bff1
Create Date: 2026-01-18 13:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260118_133000"
down_revision: Union[str, Sequence[str], None] = "79c4d8f8bff1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "mission_media",
        sa.Column("approval_status", sa.String(), nullable=False, server_default="approved"),
    )
    op.add_column("mission_media", sa.Column("approved_by_username", sa.String(), nullable=True))
    op.add_column("mission_media", sa.Column("approved_at_utc", sa.DateTime(), nullable=True))
    op.execute("UPDATE mission_media SET approval_status = 'approved' WHERE approval_status IS NULL")

    op.add_column("announcement", sa.Column("target_roles", sa.String(), nullable=True))
    op.add_column("announcement", sa.Column("target_usernames", sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("announcement", "target_usernames")
    op.drop_column("announcement", "target_roles")

    op.drop_column("mission_media", "approved_at_utc")
    op.drop_column("mission_media", "approved_by_username")
    op.drop_column("mission_media", "approval_status")
