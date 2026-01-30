"""add_enabled_sensor_cards_to_mission_overview

Revision ID: f838d65d6a9e
Revises: 54ec6be030f9
Create Date: 2025-09-06 10:34:10.923932

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = 'f838d65d6a9e'
down_revision: Union[str, Sequence[str], None] = '54ec6be030f9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema (idempotent for re-runs)."""
    bind = op.get_bind()
    inspector = inspect(bind)

    if not inspector.has_table("announcement"):
        op.create_table('announcement',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('content', sa.String(), nullable=False),
            sa.Column('created_by_username', sa.String(), nullable=False),
            sa.Column('created_at_utc', sa.DateTime(), nullable=False),
            sa.Column('is_active', sa.Boolean(), nullable=False),
            sa.PrimaryKeyConstraint('id')
        )
    if not inspector.has_table('announcementacknowledgement'):
        op.create_table('announcementacknowledgement',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('announcement_id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('acknowledged_at_utc', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['announcement_id'], ['announcement.id'], ),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
            sa.PrimaryKeyConstraint('id')
        )
    columns = {col["name"] for col in inspector.get_columns("mission_overview")}
    if "enabled_sensor_cards" not in columns:
        op.add_column('mission_overview', sa.Column('enabled_sensor_cards', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("mission_overview")}
    if "enabled_sensor_cards" in columns:
        op.drop_column('mission_overview', 'enabled_sensor_cards')
    if inspector.has_table('announcementacknowledgement'):
        op.drop_table('announcementacknowledgement')
    if inspector.has_table('announcement'):
        op.drop_table('announcement')
