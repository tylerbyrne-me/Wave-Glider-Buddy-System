"""add_is_pinned_to_shared_tips

Revision ID: 9e3e36f68ebe
Revises: ed9cac23acfc
Create Date: 2025-12-16 10:54:37.217261

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9e3e36f68ebe'
down_revision: Union[str, Sequence[str], None] = 'ed9cac23acfc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add is_pinned column to shared_tips table if missing
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {col["name"] for col in inspector.get_columns("shared_tips")}
    if "is_pinned" not in existing_columns:
        op.add_column(
            "shared_tips",
            sa.Column("is_pinned", sa.Boolean(), nullable=False, server_default="0"),
        )
    # Create index on is_pinned if missing
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("shared_tips")}
    if "ix_shared_tips_is_pinned" not in existing_indexes:
        op.create_index(
            "ix_shared_tips_is_pinned",
            "shared_tips",
            ["is_pinned"],
            unique=False,
        )


def downgrade() -> None:
    """Downgrade schema."""
    # Drop index
    op.drop_index('ix_shared_tips_is_pinned', table_name='shared_tips')
    # Drop column
    op.drop_column('shared_tips', 'is_pinned')
