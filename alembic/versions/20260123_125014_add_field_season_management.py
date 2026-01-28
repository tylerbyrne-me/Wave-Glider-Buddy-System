"""add_field_season_management

Revision ID: 20260123_125014
Revises: 20260120_170000
Create Date: 2026-01-23 12:50:14.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "20260123_125014"
down_revision: Union[str, Sequence[str], None] = "20260120_170000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create field_seasons table
    op.create_table(
        "field_seasons",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("closed_at_utc", sa.DateTime(), nullable=True),
        sa.Column("closed_by_username", sa.String(), nullable=True),
        sa.Column("summary_statistics", sa.JSON(), nullable=True),
        sa.Column("created_at_utc", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_field_seasons_year", "field_seasons", ["year"], unique=True)
    op.create_index("ix_field_seasons_is_active", "field_seasons", ["is_active"], unique=False)
    
    # Add fields to station_metadata
    bind = op.get_bind()
    inspector = inspect(bind)
    station_columns = {col["name"] for col in inspector.get_columns("station_metadata")}
    
    if "field_season_year" not in station_columns:
        op.add_column(
            "station_metadata",
            sa.Column("field_season_year", sa.Integer(), nullable=True),
        )
        op.create_index("ix_station_metadata_field_season_year", "station_metadata", ["field_season_year"], unique=False)
    
    if "is_archived" not in station_columns:
        op.add_column(
            "station_metadata",
            sa.Column("is_archived", sa.Boolean(), nullable=False, server_default="0"),
        )
        op.create_index("ix_station_metadata_is_archived", "station_metadata", ["is_archived"], unique=False)
    
    if "archived_at_utc" not in station_columns:
        op.add_column(
            "station_metadata",
            sa.Column("archived_at_utc", sa.DateTime(), nullable=True),
        )
    
    # Add field to offload_logs
    offload_columns = {col["name"] for col in inspector.get_columns("offload_logs")}
    if "field_season_year" not in offload_columns:
        op.add_column(
            "offload_logs",
            sa.Column("field_season_year", sa.Integer(), nullable=True),
        )
        op.create_index("ix_offload_logs_field_season_year", "offload_logs", ["field_season_year"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    inspector = inspect(bind)
    
    # Remove fields from offload_logs
    offload_columns = {col["name"] for col in inspector.get_columns("offload_logs")}
    if "field_season_year" in offload_columns:
        op.drop_index("ix_offload_logs_field_season_year", table_name="offload_logs")
        op.drop_column("offload_logs", "field_season_year")
    
    # Remove fields from station_metadata
    station_columns = {col["name"] for col in inspector.get_columns("station_metadata")}
    if "archived_at_utc" in station_columns:
        op.drop_column("station_metadata", "archived_at_utc")
    if "is_archived" in station_columns:
        op.drop_index("ix_station_metadata_is_archived", table_name="station_metadata")
        op.drop_column("station_metadata", "is_archived")
    if "field_season_year" in station_columns:
        op.drop_index("ix_station_metadata_field_season_year", table_name="station_metadata")
        op.drop_column("station_metadata", "field_season_year")
    
    # Drop field_seasons table
    op.drop_index("ix_field_seasons_is_active", table_name="field_seasons")
    op.drop_index("ix_field_seasons_year", table_name="field_seasons")
    op.drop_table("field_seasons")
