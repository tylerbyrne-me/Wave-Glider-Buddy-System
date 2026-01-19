"""remove_is_featured_from_shared_tips

Revision ID: d1c61203e080
Revises: 9e3e36f68ebe
Create Date: 2025-12-16 11:24:34.080240

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd1c61203e080'
down_revision: Union[str, Sequence[str], None] = '9e3e36f68ebe'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("shared_tips")}
    if "ix_shared_tips_is_featured" in existing_indexes:
        op.drop_index("ix_shared_tips_is_featured", table_name="shared_tips")
    existing_columns = {col["name"] for col in inspector.get_columns("shared_tips")}
    if "is_featured" in existing_columns:
        op.drop_column("shared_tips", "is_featured")


def downgrade() -> None:
    """Downgrade schema."""
    # Add is_featured column back
    op.add_column('shared_tips', 
        sa.Column('is_featured', sa.Boolean(), nullable=False, server_default='0')
    )
    # Recreate index
    op.create_index('ix_shared_tips_is_featured', 'shared_tips', ['is_featured'], unique=False)
