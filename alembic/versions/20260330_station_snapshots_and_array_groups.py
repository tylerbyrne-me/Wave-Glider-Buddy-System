"""station_metadata season snapshots and station_array_groups

Revision ID: 20260330_station_snapshots
Revises: 20260330_mos_pic_flags
Create Date: 2026-03-30

"""

from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "20260330_station_snapshots"
down_revision: Union[str, Sequence[str], None] = "20260330_mos_pic_flags"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = inspector.get_table_names()

    if "station_metadata_season_snapshots" not in tables:
        op.create_table(
            "station_metadata_season_snapshots",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("field_season_year", sa.Integer(), nullable=False),
            sa.Column("station_id", sa.String(), nullable=False),
            sa.Column("serial_number", sa.String(), nullable=True),
            sa.Column("modem_address", sa.Integer(), nullable=True),
            sa.Column("bottom_depth_m", sa.Float(), nullable=True),
            sa.Column("waypoint_number", sa.String(), nullable=True),
            sa.Column("last_offload_by_glider", sa.String(), nullable=True),
            sa.Column("station_settings", sa.String(), nullable=True),
            sa.Column("deployment_latitude", sa.Float(), nullable=True),
            sa.Column("deployment_longitude", sa.Float(), nullable=True),
            sa.Column("notes", sa.String(), nullable=True),
            sa.Column("last_offload_timestamp_utc", sa.DateTime(), nullable=True),
            sa.Column("was_last_offload_successful", sa.Boolean(), nullable=True),
            sa.Column("display_status_override", sa.String(), nullable=True),
            sa.Column("is_archived", sa.Boolean(), nullable=False, server_default="1"),
            sa.Column("archived_at_utc", sa.DateTime(), nullable=True),
            sa.Column("snapshot_created_at_utc", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "field_season_year",
                "station_id",
                name="uq_station_metadata_snapshot_season_station",
            ),
        )
        op.create_index(
            "ix_station_metadata_season_snapshots_field_season_year",
            "station_metadata_season_snapshots",
            ["field_season_year"],
            unique=False,
        )
        op.create_index(
            "ix_station_metadata_season_snapshots_station_id",
            "station_metadata_season_snapshots",
            ["station_id"],
            unique=False,
        )

    if "station_array_groups" not in tables:
        op.create_table(
            "station_array_groups",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("code", sa.String(), nullable=False),
            sa.Column("display_name", sa.String(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("updated_at_utc", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_station_array_groups_code",
            "station_array_groups",
            ["code"],
            unique=True,
        )
        op.create_index(
            "ix_station_array_groups_sort_order",
            "station_array_groups",
            ["sort_order"],
            unique=False,
        )

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        seed = [
            ("CBS", "CBS arrays", 10),
            ("NCAT", "NCAT arrays", 20),
            ("GULMPA", "GULMPA arrays", 30),
            ("HALIBT", "HALIBT arrays", 40),
            ("HFX", "HFX arrays", 50),
        ]
        conn = op.get_bind()
        insert_sql = sa.text(
            "INSERT INTO station_array_groups (code, display_name, notes, sort_order, updated_at_utc) "
            "VALUES (:code, :display_name, NULL, :sort_order, :updated_at)"
        )
        for code, display_name, sort_order in seed:
            conn.execute(
                insert_sql,
                {
                    "code": code,
                    "display_name": display_name,
                    "sort_order": sort_order,
                    "updated_at": now,
                },
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = inspector.get_table_names()

    if "station_array_groups" in tables:
        op.drop_index("ix_station_array_groups_sort_order", table_name="station_array_groups")
        op.drop_index("ix_station_array_groups_code", table_name="station_array_groups")
        op.drop_table("station_array_groups")

    if "station_metadata_season_snapshots" in tables:
        op.drop_index(
            "ix_station_metadata_season_snapshots_station_id",
            table_name="station_metadata_season_snapshots",
        )
        op.drop_index(
            "ix_station_metadata_season_snapshots_field_season_year",
            table_name="station_metadata_season_snapshots",
        )
        op.drop_table("station_metadata_season_snapshots")
