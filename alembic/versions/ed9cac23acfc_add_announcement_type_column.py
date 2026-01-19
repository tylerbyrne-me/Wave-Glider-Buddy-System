"""add_announcement_type_column

Revision ID: ed9cac23acfc
Revises: 7b926f8012d5
Create Date: 2025-12-15 23:40:16.490652

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ed9cac23acfc'
down_revision: Union[str, Sequence[str], None] = '7b926f8012d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add announcement_type column to announcement table if missing
    # Set default to "general" for existing rows
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {col["name"] for col in inspector.get_columns("announcement")}
    if "announcement_type" not in existing_columns:
        op.add_column(
            "announcement",
            sa.Column(
                "announcement_type",
                sa.String(),
                nullable=True,
                server_default="general",
            ),
        )
    # Create index on announcement_type if missing
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("announcement")}
    if "ix_announcement_announcement_type" not in existing_indexes:
        op.create_index(
            "ix_announcement_announcement_type",
            "announcement",
            ["announcement_type"],
            unique=False,
        )
    # Update any NULL values to "general" (shouldn't be any, but just in case)
    op.execute("UPDATE announcement SET announcement_type = 'general' WHERE announcement_type IS NULL")


def downgrade() -> None:
    """Downgrade schema."""
    # Drop index
    op.drop_index('ix_announcement_announcement_type', table_name='announcement')
    # Drop column
    op.drop_column('announcement', 'announcement_type')
