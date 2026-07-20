"""add_slocum_sfmc_snapshots

Revision ID: 20260720_sfmc_snapshots
Revises: 20260720_live_kml_platform
Create Date: 2026-07-20

Cached SFMC checklist autofill per Slocum deployment (replace-on-refresh).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20260720_sfmc_snapshots"
down_revision: Union[str, Sequence[str], None] = "20260720_live_kml_platform"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_index_if_missing(table: str, index_name: str, columns: list[str], *, unique: bool = False) -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table(table):
        return
    existing = {idx["name"] for idx in inspector.get_indexes(table)}
    if index_name not in existing:
        op.create_index(index_name, table, columns, unique=unique)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "slocum_sfmc_snapshots" not in tables:
        op.create_table(
            "slocum_sfmc_snapshots",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("deployment_id", sa.Integer(), nullable=False),
            sa.Column("glider_name", sa.String(), nullable=False),
            sa.Column("values_json", sa.Text(), nullable=True),
            sa.Column("fetched_at_utc", sa.DateTime(), nullable=True),
            sa.Column("fetch_error", sa.Text(), nullable=True),
            sa.Column("updated_at_utc", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["deployment_id"], ["slocum_deployments.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("deployment_id", name="uq_slocum_sfmc_snapshots_deployment_id"),
        )
    _create_index_if_missing(
        "slocum_sfmc_snapshots",
        "ix_slocum_sfmc_snapshots_deployment_id",
        ["deployment_id"],
        unique=True,
    )
    _create_index_if_missing(
        "slocum_sfmc_snapshots",
        "ix_slocum_sfmc_snapshots_glider_name",
        ["glider_name"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "slocum_sfmc_snapshots" not in tables:
        return
    existing = {idx["name"] for idx in inspector.get_indexes("slocum_sfmc_snapshots")}
    if "ix_slocum_sfmc_snapshots_glider_name" in existing:
        op.drop_index("ix_slocum_sfmc_snapshots_glider_name", table_name="slocum_sfmc_snapshots")
    if "ix_slocum_sfmc_snapshots_deployment_id" in existing:
        op.drop_index("ix_slocum_sfmc_snapshots_deployment_id", table_name="slocum_sfmc_snapshots")
    op.drop_table("slocum_sfmc_snapshots")
