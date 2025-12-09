"""add_sensor_tracker_models

Revision ID: 4175c125aae7
Revises: 6d40c7456313
Create Date: 2025-12-09 12:20:11.070113

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '4175c125aae7'
down_revision: Union[str, Sequence[str], None] = '6d40c7456313'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - add Sensor Tracker tables."""
    # Create sensor_tracker_deployments table
    op.create_table(
        'sensor_tracker_deployments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('mission_id', sa.String(), nullable=False),
        sa.Column('sensor_tracker_deployment_id', sa.Integer(), nullable=False),
        sa.Column('deployment_number', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(), nullable=True),
        sa.Column('start_time', sa.DateTime(), nullable=True),
        sa.Column('end_time', sa.DateTime(), nullable=True),
        sa.Column('deployment_location_lat', sa.Float(), nullable=True),
        sa.Column('deployment_location_lon', sa.Float(), nullable=True),
        sa.Column('recovery_location_lat', sa.Float(), nullable=True),
        sa.Column('recovery_location_lon', sa.Float(), nullable=True),
        sa.Column('depth', sa.Float(), nullable=True),
        sa.Column('platform_id', sa.Integer(), nullable=True),
        sa.Column('platform_name', sa.String(), nullable=True),
        sa.Column('platform_type', sa.Integer(), nullable=True),
        sa.Column('full_metadata', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('last_synced_at', sa.DateTime(), nullable=True),
        sa.Column('sync_status', sa.String(), nullable=False, server_default='pending'),
        sa.Column('sync_error', sa.String(), nullable=True),
        sa.Column('created_at_utc', sa.DateTime(), nullable=False),
        sa.Column('updated_at_utc', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('mission_id')
    )
    op.create_index(op.f('ix_sensor_tracker_deployments_mission_id'), 'sensor_tracker_deployments', ['mission_id'], unique=True)
    op.create_index(op.f('ix_sensor_tracker_deployments_sensor_tracker_deployment_id'), 'sensor_tracker_deployments', ['sensor_tracker_deployment_id'], unique=False)
    op.create_index(op.f('ix_sensor_tracker_deployments_deployment_number'), 'sensor_tracker_deployments', ['deployment_number'], unique=False)

    # Create mission_instruments table
    op.create_table(
        'mission_instruments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('mission_id', sa.String(), nullable=False),
        sa.Column('sensor_tracker_instrument_id', sa.Integer(), nullable=True),
        sa.Column('instrument_identifier', sa.String(), nullable=False),
        sa.Column('instrument_short_name', sa.String(), nullable=True),
        sa.Column('instrument_serial', sa.String(), nullable=True),
        sa.Column('instrument_name', sa.String(), nullable=True),
        sa.Column('data_logger_type', sa.String(), nullable=True),
        sa.Column('data_logger_id', sa.Integer(), nullable=True),
        sa.Column('data_logger_name', sa.String(), nullable=True),
        sa.Column('data_logger_identifier', sa.String(), nullable=True),
        sa.Column('is_platform_direct', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('start_time', sa.DateTime(), nullable=True),
        sa.Column('end_time', sa.DateTime(), nullable=True),
        sa.Column('validated', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('validation_notes', sa.String(), nullable=True),
        sa.Column('created_at_utc', sa.DateTime(), nullable=False),
        sa.Column('updated_at_utc', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_mission_instruments_mission_id'), 'mission_instruments', ['mission_id'], unique=False)
    op.create_index(op.f('ix_mission_instruments_sensor_tracker_instrument_id'), 'mission_instruments', ['sensor_tracker_instrument_id'], unique=False)
    op.create_index(op.f('ix_mission_instruments_instrument_identifier'), 'mission_instruments', ['instrument_identifier'], unique=False)

    # Create mission_sensors table
    op.create_table(
        'mission_sensors',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('mission_id', sa.String(), nullable=False),
        sa.Column('instrument_id', sa.Integer(), nullable=False),
        sa.Column('sensor_tracker_sensor_id', sa.Integer(), nullable=True),
        sa.Column('sensor_identifier', sa.String(), nullable=False),
        sa.Column('sensor_short_name', sa.String(), nullable=True),
        sa.Column('sensor_serial', sa.String(), nullable=True),
        sa.Column('start_time', sa.DateTime(), nullable=True),
        sa.Column('end_time', sa.DateTime(), nullable=True),
        sa.Column('validated', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('validation_notes', sa.String(), nullable=True),
        sa.Column('created_at_utc', sa.DateTime(), nullable=False),
        sa.Column('updated_at_utc', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['instrument_id'], ['mission_instruments.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_mission_sensors_mission_id'), 'mission_sensors', ['mission_id'], unique=False)
    op.create_index(op.f('ix_mission_sensors_instrument_id'), 'mission_sensors', ['instrument_id'], unique=False)
    op.create_index(op.f('ix_mission_sensors_sensor_tracker_sensor_id'), 'mission_sensors', ['sensor_tracker_sensor_id'], unique=False)
    op.create_index(op.f('ix_mission_sensors_sensor_identifier'), 'mission_sensors', ['sensor_identifier'], unique=False)


def downgrade() -> None:
    """Downgrade schema - remove Sensor Tracker tables."""
    op.drop_index(op.f('ix_mission_sensors_sensor_identifier'), table_name='mission_sensors')
    op.drop_index(op.f('ix_mission_sensors_sensor_tracker_sensor_id'), table_name='mission_sensors')
    op.drop_index(op.f('ix_mission_sensors_instrument_id'), table_name='mission_sensors')
    op.drop_index(op.f('ix_mission_sensors_mission_id'), table_name='mission_sensors')
    op.drop_table('mission_sensors')
    
    op.drop_index(op.f('ix_mission_instruments_instrument_identifier'), table_name='mission_instruments')
    op.drop_index(op.f('ix_mission_instruments_sensor_tracker_instrument_id'), table_name='mission_instruments')
    op.drop_index(op.f('ix_mission_instruments_mission_id'), table_name='mission_instruments')
    op.drop_table('mission_instruments')
    
    op.drop_index(op.f('ix_sensor_tracker_deployments_deployment_number'), table_name='sensor_tracker_deployments')
    op.drop_index(op.f('ix_sensor_tracker_deployments_sensor_tracker_deployment_id'), table_name='sensor_tracker_deployments')
    op.drop_index(op.f('ix_sensor_tracker_deployments_mission_id'), table_name='sensor_tracker_deployments')
    op.drop_table('sensor_tracker_deployments')
