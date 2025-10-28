"""add_live_kml_tokens_table

Revision ID: 6d40c7456313
Revises: 0f54d18ff6ca
Create Date: 2025-10-28 13:10:36.535509

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6d40c7456313'
down_revision: Union[str, Sequence[str], None] = '0f54d18ff6ca'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create live_kml_tokens table
    op.create_table('live_kml_tokens',
        sa.Column('token', sa.String(length=64), nullable=False),
        sa.Column('mission_ids', sa.Text(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('hours_back', sa.Integer(), nullable=False),
        sa.Column('refresh_interval_minutes', sa.Integer(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('access_count', sa.Integer(), nullable=False),
        sa.Column('last_accessed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('color_scheme', sa.String(), nullable=True),
        sa.Column('include_markers', sa.Boolean(), nullable=False),
        sa.Column('include_timestamps', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_live_kml_tokens_user_id'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], name='fk_live_kml_tokens_created_by'),
        sa.PrimaryKeyConstraint('token')
    )
    op.create_index('ix_live_kml_tokens_user_id', 'live_kml_tokens', ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_live_kml_tokens_user_id', table_name='live_kml_tokens')
    op.drop_table('live_kml_tokens')
