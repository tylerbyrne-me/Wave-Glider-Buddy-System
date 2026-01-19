"""add_user_notes_and_shared_tips_tables

Revision ID: 10eb6ea6c8a9
Revises: eb1164ea8808
Create Date: 2025-12-15 13:05:14.719593

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '10eb6ea6c8a9'
down_revision: Union[str, Sequence[str], None] = 'eb1164ea8808'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create user_notes table
    op.create_table('user_notes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('category', sa.String(), nullable=True),
        sa.Column('tags', sa.String(), nullable=True),
        sa.Column('is_pinned', sa.Boolean(), nullable=False),
        sa.Column('created_at_utc', sa.DateTime(), nullable=False),
        sa.Column('updated_at_utc', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_user_notes_user_id'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_user_notes_user_id', 'user_notes', ['user_id'], unique=False)
    op.create_index('ix_user_notes_title', 'user_notes', ['title'], unique=False)
    op.create_index('ix_user_notes_category', 'user_notes', ['category'], unique=False)
    op.create_index('ix_user_notes_is_pinned', 'user_notes', ['is_pinned'], unique=False)
    
    # Create shared_tips table
    op.create_table('shared_tips',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('category', sa.String(), nullable=True),
        sa.Column('tags', sa.String(), nullable=True),
        sa.Column('created_by_username', sa.String(), nullable=False),
        sa.Column('created_at_utc', sa.DateTime(), nullable=False),
        sa.Column('updated_at_utc', sa.DateTime(), nullable=False),
        sa.Column('last_edited_by_username', sa.String(), nullable=True),
        sa.Column('helpful_count', sa.Integer(), nullable=False),
        sa.Column('view_count', sa.Integer(), nullable=False),
        sa.Column('is_featured', sa.Boolean(), nullable=False),
        sa.Column('is_archived', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_shared_tips_title', 'shared_tips', ['title'], unique=False)
    op.create_index('ix_shared_tips_category', 'shared_tips', ['category'], unique=False)
    op.create_index('ix_shared_tips_created_by_username', 'shared_tips', ['created_by_username'], unique=False)
    op.create_index('ix_shared_tips_is_featured', 'shared_tips', ['is_featured'], unique=False)
    op.create_index('ix_shared_tips_is_archived', 'shared_tips', ['is_archived'], unique=False)
    
    # Create tip_contributions table
    op.create_table('tip_contributions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tip_id', sa.Integer(), nullable=False),
        sa.Column('contributed_by_username', sa.String(), nullable=False),
        sa.Column('contribution_type', sa.String(), nullable=False),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('contributed_at_utc', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['tip_id'], ['shared_tips.id'], name='fk_tip_contributions_tip_id'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_tip_contributions_tip_id', 'tip_contributions', ['tip_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_tip_contributions_tip_id', table_name='tip_contributions')
    op.drop_table('tip_contributions')
    op.drop_index('ix_shared_tips_is_archived', table_name='shared_tips')
    op.drop_index('ix_shared_tips_is_featured', table_name='shared_tips')
    op.drop_index('ix_shared_tips_created_by_username', table_name='shared_tips')
    op.drop_index('ix_shared_tips_category', table_name='shared_tips')
    op.drop_index('ix_shared_tips_title', table_name='shared_tips')
    op.drop_table('shared_tips')
    op.drop_index('ix_user_notes_is_pinned', table_name='user_notes')
    op.drop_index('ix_user_notes_category', table_name='user_notes')
    op.drop_index('ix_user_notes_title', table_name='user_notes')
    op.drop_index('ix_user_notes_user_id', table_name='user_notes')
    op.drop_table('user_notes')
