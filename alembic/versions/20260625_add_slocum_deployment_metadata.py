"""add_slocum_deployment_metadata

Revision ID: 20260625_slocum_metadata
Revises: 20260623_offload_comments
Create Date: 2026-06-25

Slocum deployment goals, notes, and media tables (briefing/metadata parity).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20260625_slocum_metadata"
down_revision: Union[str, Sequence[str], None] = "20260623_offload_comments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_index_if_missing(table: str, index_name: str, columns: list[str]) -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table(table):
        return
    existing = {idx["name"] for idx in inspector.get_indexes(table)}
    if index_name not in existing:
        op.create_index(index_name, table, columns)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "slocum_deployment_goals" not in tables:
        op.create_table(
            "slocum_deployment_goals",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("deployment_id", sa.Integer(), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("is_completed", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("completed_by_username", sa.String(), nullable=True),
            sa.Column("completed_at_utc", sa.DateTime(), nullable=True),
            sa.Column("created_at_utc", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["deployment_id"], ["slocum_deployments.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_if_missing(
        "slocum_deployment_goals", "ix_slocum_deployment_goals_deployment_id", ["deployment_id"]
    )
    _create_index_if_missing(
        "slocum_deployment_goals", "ix_slocum_deployment_goals_is_completed", ["is_completed"]
    )

    if "slocum_deployment_notes" not in tables:
        op.create_table(
            "slocum_deployment_notes",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("deployment_id", sa.Integer(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("include_in_report", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_by_username", sa.String(), nullable=False),
            sa.Column("created_at_utc", sa.DateTime(), nullable=False),
            sa.Column("updated_at_utc", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["deployment_id"], ["slocum_deployments.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_if_missing(
        "slocum_deployment_notes", "ix_slocum_deployment_notes_deployment_id", ["deployment_id"]
    )
    _create_index_if_missing(
        "slocum_deployment_notes", "ix_slocum_deployment_notes_include_in_report", ["include_in_report"]
    )

    if "slocum_deployment_media" not in tables:
        op.create_table(
            "slocum_deployment_media",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("deployment_id", sa.Integer(), nullable=False),
            sa.Column("media_type", sa.String(), nullable=False),
            sa.Column("file_path", sa.String(), nullable=False),
            sa.Column("file_name", sa.String(), nullable=False),
            sa.Column("file_size", sa.Integer(), nullable=False),
            sa.Column("mime_type", sa.String(), nullable=False),
            sa.Column("caption", sa.Text(), nullable=True),
            sa.Column("operation_type", sa.String(), nullable=True),
            sa.Column("uploaded_by_username", sa.String(), nullable=False),
            sa.Column("uploaded_at_utc", sa.DateTime(), nullable=False),
            sa.Column("thumbnail_path", sa.String(), nullable=True),
            sa.Column("approval_status", sa.String(), nullable=False, server_default="approved"),
            sa.Column("approved_by_username", sa.String(), nullable=True),
            sa.Column("approved_at_utc", sa.DateTime(), nullable=True),
            sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("is_featured", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.ForeignKeyConstraint(["deployment_id"], ["slocum_deployments.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_if_missing(
        "slocum_deployment_media", "ix_slocum_deployment_media_deployment_id", ["deployment_id"]
    )
    _create_index_if_missing(
        "slocum_deployment_media", "ix_slocum_deployment_media_uploaded_by_username", ["uploaded_by_username"]
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "slocum_deployment_media" in tables:
        existing = {idx["name"] for idx in inspector.get_indexes("slocum_deployment_media")}
        if "ix_slocum_deployment_media_uploaded_by_username" in existing:
            op.drop_index("ix_slocum_deployment_media_uploaded_by_username", table_name="slocum_deployment_media")
        if "ix_slocum_deployment_media_deployment_id" in existing:
            op.drop_index("ix_slocum_deployment_media_deployment_id", table_name="slocum_deployment_media")
        op.drop_table("slocum_deployment_media")

    if "slocum_deployment_notes" in tables:
        existing = {idx["name"] for idx in inspector.get_indexes("slocum_deployment_notes")}
        if "ix_slocum_deployment_notes_include_in_report" in existing:
            op.drop_index("ix_slocum_deployment_notes_include_in_report", table_name="slocum_deployment_notes")
        if "ix_slocum_deployment_notes_deployment_id" in existing:
            op.drop_index("ix_slocum_deployment_notes_deployment_id", table_name="slocum_deployment_notes")
        op.drop_table("slocum_deployment_notes")

    if "slocum_deployment_goals" in tables:
        existing = {idx["name"] for idx in inspector.get_indexes("slocum_deployment_goals")}
        if "ix_slocum_deployment_goals_is_completed" in existing:
            op.drop_index("ix_slocum_deployment_goals_is_completed", table_name="slocum_deployment_goals")
        if "ix_slocum_deployment_goals_deployment_id" in existing:
            op.drop_index("ix_slocum_deployment_goals_deployment_id", table_name="slocum_deployment_goals")
        op.drop_table("slocum_deployment_goals")
