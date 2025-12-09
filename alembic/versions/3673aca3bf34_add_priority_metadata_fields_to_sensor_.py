"""add_priority_metadata_fields_to_sensor_tracker_deployment

Revision ID: 3673aca3bf34
Revises: 20251209_134909
Create Date: 2025-12-09 14:44:14.815542

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import String


# revision identifiers, used by Alembic.
revision: str = '3673aca3bf34'
down_revision: Union[str, Sequence[str], None] = '20251209_134909'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - add priority metadata fields to sensor_tracker_deployments."""
    # Add priority metadata fields
    op.add_column('sensor_tracker_deployments', sa.Column('agencies', String(), nullable=True))
    op.add_column('sensor_tracker_deployments', sa.Column('agencies_role', String(), nullable=True))
    op.add_column('sensor_tracker_deployments', sa.Column('deployment_comment', sa.Text(), nullable=True))
    op.add_column('sensor_tracker_deployments', sa.Column('acknowledgement', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema - remove priority metadata fields from sensor_tracker_deployments."""
    op.drop_column('sensor_tracker_deployments', 'acknowledgement')
    op.drop_column('sensor_tracker_deployments', 'deployment_comment')
    op.drop_column('sensor_tracker_deployments', 'agencies_role')
    op.drop_column('sensor_tracker_deployments', 'agencies')
