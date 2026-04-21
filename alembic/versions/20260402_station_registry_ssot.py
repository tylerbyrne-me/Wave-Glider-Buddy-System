"""station_registry_ssot: is_retired, registry audit, un-archive legacy rollover rows

Revision ID: 20260402_registry
Revises: 20260401_vm4_living
Create Date: 2026-04-02
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20260402_registry"
down_revision: Union[str, Sequence[str], None] = "20260401_vm4_living"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("station_metadata")}

    if "is_retired" not in cols:
        op.add_column(
            "station_metadata",
            sa.Column("is_retired", sa.Boolean(), nullable=False, server_default="0"),
        )
        op.create_index("ix_station_metadata_is_retired", "station_metadata", ["is_retired"], unique=False)
    if "registry_confirmed_at_utc" not in cols:
        op.add_column(
            "station_metadata",
            sa.Column("registry_confirmed_at_utc", sa.DateTime(), nullable=True),
        )
    if "registry_confirmed_by_username" not in cols:
        op.add_column(
            "station_metadata",
            sa.Column("registry_confirmed_by_username", sa.String(), nullable=True),
        )

    # Legacy rollover: archived fleet was an artifact of season close, not retirement.
    op.execute(
        sa.text(
            """
            UPDATE station_metadata
            SET is_archived = 0,
                archived_at_utc = NULL,
                field_season_year = NULL
            WHERE is_archived = 1 OR field_season_year IS NOT NULL
            """
        )
    )

    # Drop server_default after backfill so new rows use ORM defaults.
    try:
        with op.batch_alter_table("station_metadata") as batch:
            batch.alter_column("is_retired", server_default=None)
    except Exception:
        pass


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("station_metadata")}
    if "registry_confirmed_by_username" in cols:
        op.drop_column("station_metadata", "registry_confirmed_by_username")
    if "registry_confirmed_at_utc" in cols:
        op.drop_column("station_metadata", "registry_confirmed_at_utc")
    if "is_retired" in cols:
        try:
            op.drop_index("ix_station_metadata_is_retired", table_name="station_metadata")
        except Exception:
            pass
        op.drop_column("station_metadata", "is_retired")
