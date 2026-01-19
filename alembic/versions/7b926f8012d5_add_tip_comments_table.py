"""add_tip_comments_table

Revision ID: 7b926f8012d5
Revises: 10eb6ea6c8a9
Create Date: 2025-12-15 13:52:20.276699

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7b926f8012d5'
down_revision: Union[str, Sequence[str], None] = '10eb6ea6c8a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create tip_comments table
    op.create_table('tip_comments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tip_id', sa.Integer(), nullable=False),
        sa.Column('commented_by_username', sa.String(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('is_question', sa.Boolean(), nullable=False),
        sa.Column('is_resolved', sa.Boolean(), nullable=False),
        sa.Column('created_at_utc', sa.DateTime(), nullable=False),
        sa.Column('updated_at_utc', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['tip_id'], ['shared_tips.id'], name='fk_tip_comments_tip_id'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_tip_comments_tip_id', 'tip_comments', ['tip_id'], unique=False)
    op.create_index('ix_tip_comments_commented_by_username', 'tip_comments', ['commented_by_username'], unique=False)
    op.create_index('ix_tip_comments_is_question', 'tip_comments', ['is_question'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_tip_comments_is_question', table_name='tip_comments')
    op.drop_index('ix_tip_comments_commented_by_username', table_name='tip_comments')
    op.drop_index('ix_tip_comments_tip_id', table_name='tip_comments')
    op.drop_table('tip_comments')
