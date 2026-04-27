"""add station_flag_events table for season-scoped flag history

Revision ID: 20260427_station_flags
Revises: 20260402_registry
Create Date: 2026-04-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20260427_station_flags"
down_revision: Union[str, Sequence[str], None] = "20260402_registry"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "station_flag_events" in tables:
        return
    op.create_table(
        "station_flag_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("station_id", sa.String(), nullable=False),
        sa.Column("field_season_year", sa.Integer(), nullable=True),
        sa.Column("is_flagged", sa.Boolean(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("changed_by_username", sa.String(), nullable=False),
        sa.Column("changed_at_utc", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["station_id"], ["station_metadata.station_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_station_flag_events_station_id",
        "station_flag_events",
        ["station_id"],
        unique=False,
    )
    op.create_index(
        "ix_station_flag_events_field_season_year",
        "station_flag_events",
        ["field_season_year"],
        unique=False,
    )
    op.create_index(
        "ix_station_flag_events_is_flagged",
        "station_flag_events",
        ["is_flagged"],
        unique=False,
    )
    op.create_index(
        "ix_station_flag_events_changed_by_username",
        "station_flag_events",
        ["changed_by_username"],
        unique=False,
    )
    op.create_index(
        "ix_station_flag_events_changed_at_utc",
        "station_flag_events",
        ["changed_at_utc"],
        unique=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "station_flag_events" not in tables:
        return
    for idx_name in (
        "ix_station_flag_events_changed_at_utc",
        "ix_station_flag_events_changed_by_username",
        "ix_station_flag_events_is_flagged",
        "ix_station_flag_events_field_season_year",
        "ix_station_flag_events_station_id",
    ):
        try:
            op.drop_index(idx_name, table_name="station_flag_events")
        except Exception:
            pass
    op.drop_table("station_flag_events")
