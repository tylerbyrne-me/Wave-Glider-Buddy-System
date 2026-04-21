"""vm4_living_db_refinement

Revision ID: 20260401_vm4_living
Revises: 20260330_station_snapshots
Create Date: 2026-04-01
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20260401_vm4_living"
down_revision: Union[str, Sequence[str], None] = "20260330_station_snapshots"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    offload_columns = {col["name"] for col in inspector.get_columns("offload_logs")}
    if "parser_notes" not in offload_columns:
        op.add_column("offload_logs", sa.Column("parser_notes", sa.Text(), nullable=True))
    if "user_notes" not in offload_columns:
        op.add_column("offload_logs", sa.Column("user_notes", sa.Text(), nullable=True))
    if "created_by_source" not in offload_columns:
        op.add_column(
            "offload_logs",
            sa.Column("created_by_source", sa.String(), nullable=False, server_default="user"),
        )
        op.create_index("ix_offload_logs_created_by_source", "offload_logs", ["created_by_source"], unique=False)
    if "updated_by_source" not in offload_columns:
        op.add_column("offload_logs", sa.Column("updated_by_source", sa.String(), nullable=True))
        op.create_index("ix_offload_logs_updated_by_source", "offload_logs", ["updated_by_source"], unique=False)
    if "updated_at_utc" not in offload_columns:
        op.add_column("offload_logs", sa.Column("updated_at_utc", sa.DateTime(), nullable=True))
        op.create_index("ix_offload_logs_updated_at_utc", "offload_logs", ["updated_at_utc"], unique=False)
    if "parser_run_id" not in offload_columns:
        op.add_column("offload_logs", sa.Column("parser_run_id", sa.String(), nullable=True))
        op.create_index("ix_offload_logs_parser_run_id", "offload_logs", ["parser_run_id"], unique=False)
    if "parser_session_ref" not in offload_columns:
        op.add_column("offload_logs", sa.Column("parser_session_ref", sa.String(), nullable=True))

    tables = inspector.get_table_names()
    if "station_hardware_history" not in tables:
        op.create_table(
            "station_hardware_history",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("station_id", sa.String(), nullable=False),
            sa.Column("serial_number", sa.String(), nullable=True),
            sa.Column("modem_address", sa.Integer(), nullable=True),
            sa.Column("effective_start_utc", sa.DateTime(), nullable=False),
            sa.Column("effective_end_utc", sa.DateTime(), nullable=True),
            sa.Column("changed_by_username", sa.String(), nullable=True),
            sa.Column("change_source", sa.String(), nullable=False, server_default="user"),
            sa.Column("change_note", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["station_id"], ["station_metadata.station_id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_station_hardware_history_station_id", "station_hardware_history", ["station_id"], unique=False)
        op.create_index("ix_station_hardware_history_serial_number", "station_hardware_history", ["serial_number"], unique=False)
        op.create_index("ix_station_hardware_history_modem_address", "station_hardware_history", ["modem_address"], unique=False)
        op.create_index("ix_station_hardware_history_effective_start_utc", "station_hardware_history", ["effective_start_utc"], unique=False)
        op.create_index("ix_station_hardware_history_effective_end_utc", "station_hardware_history", ["effective_end_utc"], unique=False)
        op.create_index("ix_station_hardware_history_changed_by_username", "station_hardware_history", ["changed_by_username"], unique=False)
        op.create_index("ix_station_hardware_history_change_source", "station_hardware_history", ["change_source"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = inspector.get_table_names()

    if "station_hardware_history" in tables:
        op.drop_index("ix_station_hardware_history_change_source", table_name="station_hardware_history")
        op.drop_index("ix_station_hardware_history_changed_by_username", table_name="station_hardware_history")
        op.drop_index("ix_station_hardware_history_effective_end_utc", table_name="station_hardware_history")
        op.drop_index("ix_station_hardware_history_effective_start_utc", table_name="station_hardware_history")
        op.drop_index("ix_station_hardware_history_modem_address", table_name="station_hardware_history")
        op.drop_index("ix_station_hardware_history_serial_number", table_name="station_hardware_history")
        op.drop_index("ix_station_hardware_history_station_id", table_name="station_hardware_history")
        op.drop_table("station_hardware_history")

    offload_columns = {col["name"] for col in inspector.get_columns("offload_logs")}
    if "parser_session_ref" in offload_columns:
        op.drop_column("offload_logs", "parser_session_ref")
    if "parser_run_id" in offload_columns:
        op.drop_index("ix_offload_logs_parser_run_id", table_name="offload_logs")
        op.drop_column("offload_logs", "parser_run_id")
    if "updated_at_utc" in offload_columns:
        op.drop_index("ix_offload_logs_updated_at_utc", table_name="offload_logs")
        op.drop_column("offload_logs", "updated_at_utc")
    if "updated_by_source" in offload_columns:
        op.drop_index("ix_offload_logs_updated_by_source", table_name="offload_logs")
        op.drop_column("offload_logs", "updated_by_source")
    if "created_by_source" in offload_columns:
        op.drop_index("ix_offload_logs_created_by_source", table_name="offload_logs")
        op.drop_column("offload_logs", "created_by_source")
    if "user_notes" in offload_columns:
        op.drop_column("offload_logs", "user_notes")
    if "parser_notes" in offload_columns:
        op.drop_column("offload_logs", "parser_notes")
