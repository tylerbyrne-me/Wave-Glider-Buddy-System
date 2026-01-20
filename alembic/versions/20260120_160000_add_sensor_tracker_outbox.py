"""add_sensor_tracker_outbox

Revision ID: 20260120_160000
Revises: 20260120_153000
Create Date: 2026-01-20 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "20260120_160000"
down_revision: Union[str, Sequence[str], None] = "20260120_153000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = inspect(bind)

    if "sensor_tracker_outbox" not in inspector.get_table_names():
        op.create_table(
            "sensor_tracker_outbox",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("mission_id", sa.String(), nullable=False),
            sa.Column("entity_type", sa.String(), nullable=False),
            sa.Column("local_id", sa.Integer(), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=True),
            sa.Column("payload_hash", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="pending_review"),
            sa.Column("approved_by_username", sa.String(), nullable=True),
            sa.Column("approved_at_utc", sa.DateTime(), nullable=True),
            sa.Column("rejected_by_username", sa.String(), nullable=True),
            sa.Column("rejected_at_utc", sa.DateTime(), nullable=True),
            sa.Column("rejection_reason", sa.Text(), nullable=True),
            sa.Column("sensor_tracker_id", sa.String(), nullable=True),
            sa.Column("last_attempt_at_utc", sa.DateTime(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_at_utc", sa.DateTime(), nullable=False),
            sa.Column("updated_at_utc", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )

    existing_indexes = {idx["name"] for idx in inspector.get_indexes("sensor_tracker_outbox")}
    if "ix_sensor_tracker_outbox_mission_id" not in existing_indexes:
        op.create_index("ix_sensor_tracker_outbox_mission_id", "sensor_tracker_outbox", ["mission_id"])
    if "ix_sensor_tracker_outbox_entity_type" not in existing_indexes:
        op.create_index("ix_sensor_tracker_outbox_entity_type", "sensor_tracker_outbox", ["entity_type"])
    if "ix_sensor_tracker_outbox_local_id" not in existing_indexes:
        op.create_index("ix_sensor_tracker_outbox_local_id", "sensor_tracker_outbox", ["local_id"])
    if "ix_sensor_tracker_outbox_payload_hash" not in existing_indexes:
        op.create_index("ix_sensor_tracker_outbox_payload_hash", "sensor_tracker_outbox", ["payload_hash"])
    if "ix_sensor_tracker_outbox_status" not in existing_indexes:
        op.create_index("ix_sensor_tracker_outbox_status", "sensor_tracker_outbox", ["status"])
    if "ix_sensor_tracker_outbox_approved_by_username" not in existing_indexes:
        op.create_index("ix_sensor_tracker_outbox_approved_by_username", "sensor_tracker_outbox", ["approved_by_username"])
    if "ix_sensor_tracker_outbox_rejected_by_username" not in existing_indexes:
        op.create_index("ix_sensor_tracker_outbox_rejected_by_username", "sensor_tracker_outbox", ["rejected_by_username"])
    if "ix_sensor_tracker_outbox_sensor_tracker_id" not in existing_indexes:
        op.create_index("ix_sensor_tracker_outbox_sensor_tracker_id", "sensor_tracker_outbox", ["sensor_tracker_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_sensor_tracker_outbox_sensor_tracker_id", table_name="sensor_tracker_outbox")
    op.drop_index("ix_sensor_tracker_outbox_rejected_by_username", table_name="sensor_tracker_outbox")
    op.drop_index("ix_sensor_tracker_outbox_approved_by_username", table_name="sensor_tracker_outbox")
    op.drop_index("ix_sensor_tracker_outbox_status", table_name="sensor_tracker_outbox")
    op.drop_index("ix_sensor_tracker_outbox_payload_hash", table_name="sensor_tracker_outbox")
    op.drop_index("ix_sensor_tracker_outbox_local_id", table_name="sensor_tracker_outbox")
    op.drop_index("ix_sensor_tracker_outbox_entity_type", table_name="sensor_tracker_outbox")
    op.drop_index("ix_sensor_tracker_outbox_mission_id", table_name="sensor_tracker_outbox")
    op.drop_table("sensor_tracker_outbox")
