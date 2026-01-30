"""add deployment latitude and longitude to station metadata

Revision ID: 0f54d18ff6ca
Revises: f838d65d6a9e
Create Date: 2025-09-15 15:26:38.174737

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = '0f54d18ff6ca'
down_revision: Union[str, Sequence[str], None] = 'f838d65d6a9e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema (idempotent for re-runs)."""
    bind = op.get_bind()
    inspector = inspect(bind)

    if inspector.has_table('error_category_stats'):
        op.drop_index(op.f('ix_error_category_stats_category'), table_name='error_category_stats')
        op.drop_index(op.f('ix_error_category_stats_mission_id'), table_name='error_category_stats')
        op.drop_index(op.f('ix_error_category_stats_time_period_end'), table_name='error_category_stats')
        op.drop_index(op.f('ix_error_category_stats_time_period_start'), table_name='error_category_stats')
        op.drop_table('error_category_stats')
    if inspector.has_table('error_patterns'):
        op.drop_table('error_patterns')
    if inspector.has_table('classified_errors'):
        op.drop_index(op.f('ix_classified_errors_mission_id'), table_name='classified_errors')
        op.drop_index(op.f('ix_classified_errors_timestamp'), table_name='classified_errors')
        op.drop_table('classified_errors')

    columns = {col["name"] for col in inspector.get_columns("station_metadata")}
    if "deployment_latitude" not in columns:
        op.add_column('station_metadata', sa.Column('deployment_latitude', sa.Float(), nullable=True))
    if "deployment_longitude" not in columns:
        op.add_column('station_metadata', sa.Column('deployment_longitude', sa.Float(), nullable=True))


def downgrade() -> None:
    """Downgrade schema (idempotent for re-runs)."""
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("station_metadata")}
    if "deployment_longitude" in columns:
        op.drop_column('station_metadata', 'deployment_longitude')
    if "deployment_latitude" in columns:
        op.drop_column('station_metadata', 'deployment_latitude')
    if not inspector.has_table('classified_errors'):
        op.create_table('classified_errors',
            sa.Column('id', sa.INTEGER(), nullable=False),
            sa.Column('mission_id', sa.VARCHAR(), nullable=False),
            sa.Column('timestamp', sa.DATETIME(), nullable=False),
            sa.Column('vehicle_name', sa.VARCHAR(), nullable=False),
            sa.Column('original_message', sa.TEXT(), nullable=True),
            sa.Column('error_category', sa.VARCHAR(length=13), nullable=False),
            sa.Column('classification_confidence', sa.FLOAT(), nullable=False),
            sa.Column('severity_level', sa.VARCHAR(length=6), nullable=False),
            sa.Column('category_description', sa.VARCHAR(), nullable=False),
            sa.Column('self_corrected', sa.BOOLEAN(), nullable=True),
            sa.Column('created_at', sa.DATETIME(), nullable=False),
            sa.Column('classification_version', sa.VARCHAR(), nullable=False),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_classified_errors_timestamp'), 'classified_errors', ['timestamp'], unique=False)
        op.create_index(op.f('ix_classified_errors_mission_id'), 'classified_errors', ['mission_id'], unique=False)
    if not inspector.has_table('error_patterns'):
        op.create_table('error_patterns',
            sa.Column('id', sa.INTEGER(), nullable=False),
            sa.Column('pattern_name', sa.VARCHAR(), nullable=False),
            sa.Column('regex_pattern', sa.TEXT(), nullable=True),
            sa.Column('category', sa.VARCHAR(length=13), nullable=False),
            sa.Column('severity', sa.VARCHAR(length=6), nullable=False),
            sa.Column('description', sa.VARCHAR(), nullable=False),
            sa.Column('confidence_threshold', sa.FLOAT(), nullable=False),
            sa.Column('is_active', sa.BOOLEAN(), nullable=False),
            sa.Column('created_at', sa.DATETIME(), nullable=False),
            sa.Column('updated_at', sa.DATETIME(), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('pattern_name')
        )
    if not inspector.has_table('error_category_stats'):
        op.create_table('error_category_stats',
            sa.Column('id', sa.INTEGER(), nullable=False),
            sa.Column('mission_id', sa.VARCHAR(), nullable=False),
            sa.Column('category', sa.VARCHAR(length=13), nullable=False),
            sa.Column('time_period_start', sa.DATETIME(), nullable=False),
            sa.Column('time_period_end', sa.DATETIME(), nullable=False),
            sa.Column('period_type', sa.VARCHAR(), nullable=False),
            sa.Column('total_errors', sa.INTEGER(), nullable=False),
            sa.Column('self_corrected_count', sa.INTEGER(), nullable=False),
            sa.Column('self_correction_rate', sa.FLOAT(), nullable=False),
            sa.Column('avg_confidence', sa.FLOAT(), nullable=False),
            sa.Column('severity_distribution', sa.TEXT(), nullable=True),
            sa.Column('calculated_at', sa.DATETIME(), nullable=False),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_error_category_stats_time_period_start'), 'error_category_stats', ['time_period_start'], unique=False)
        op.create_index(op.f('ix_error_category_stats_time_period_end'), 'error_category_stats', ['time_period_end'], unique=False)
        op.create_index(op.f('ix_error_category_stats_mission_id'), 'error_category_stats', ['mission_id'], unique=False)
        op.create_index(op.f('ix_error_category_stats_category'), 'error_category_stats', ['category'], unique=False)
