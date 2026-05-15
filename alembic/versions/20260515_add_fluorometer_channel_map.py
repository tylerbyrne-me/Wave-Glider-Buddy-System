"""add fluorometer_channel_map to sensor_tracker_deployments

Revision ID: 20260515_fluorometer_map
Revises: 20260502_mission_note_updated_at
Create Date: 2026-05-15

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260515_fluorometer_map"
down_revision: Union[str, Sequence[str], None] = "20260502_mission_note_updated_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sensor_tracker_deployments",
        sa.Column("fluorometer_channel_map", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sensor_tracker_deployments", "fluorometer_channel_map")
