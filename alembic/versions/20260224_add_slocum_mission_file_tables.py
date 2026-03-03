"""add_slocum_mission_file_tables

Revision ID: 20260224_slocum
Revises: 20260223_platform
Create Date: 2026-02-24

Add Slocum Mission File Tool tables: deployments, mission files, versions,
snapshots, and change logs.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260224_slocum"
down_revision: Union[str, Sequence[str], None] = "20260223_platform"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "slocum_deployments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("glider_name", sa.String(), nullable=False),
        sa.Column("deployment_date", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("created_by_username", sa.String(), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(), nullable=False),
        sa.Column("updated_at_utc", sa.DateTime(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
    )
    op.create_index("ix_slocum_deployments_name", "slocum_deployments", ["name"], unique=False)
    op.create_index("ix_slocum_deployments_glider_name", "slocum_deployments", ["glider_name"], unique=False)
    op.create_index("ix_slocum_deployments_status", "slocum_deployments", ["status"], unique=False)
    op.create_index("ix_slocum_deployments_created_by_username", "slocum_deployments", ["created_by_username"], unique=False)
    op.create_index("ix_slocum_deployments_is_active", "slocum_deployments", ["is_active"], unique=False)

    op.create_table(
        "slocum_mission_files",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("deployment_id", sa.Integer(), sa.ForeignKey("slocum_deployments.id"), nullable=False),
        sa.Column("file_name", sa.String(), nullable=False),
        sa.Column("file_type", sa.String(), nullable=False),
        sa.Column("ma_subtype", sa.String(), nullable=True),
        sa.Column("original_content", sa.Text(), nullable=False),
        sa.Column("current_content", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("parsed_parameters", sa.JSON(), nullable=True),
        sa.Column("uploaded_by_username", sa.String(), nullable=False),
        sa.Column("uploaded_at_utc", sa.DateTime(), nullable=False),
        sa.Column("updated_at_utc", sa.DateTime(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
    )
    op.create_index("ix_slocum_mission_files_deployment_id", "slocum_mission_files", ["deployment_id"], unique=False)
    op.create_index("ix_slocum_mission_files_file_name", "slocum_mission_files", ["file_name"], unique=False)
    op.create_index("ix_slocum_mission_files_file_type", "slocum_mission_files", ["file_type"], unique=False)
    op.create_index("ix_slocum_mission_files_ma_subtype", "slocum_mission_files", ["ma_subtype"], unique=False)
    op.create_index("ix_slocum_mission_files_uploaded_by_username", "slocum_mission_files", ["uploaded_by_username"], unique=False)
    op.create_index("ix_slocum_mission_files_is_active", "slocum_mission_files", ["is_active"], unique=False)

    op.create_table(
        "slocum_mission_file_versions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("mission_file_id", sa.Integer(), sa.ForeignKey("slocum_mission_files.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("changed_by_username", sa.String(), nullable=False),
        sa.Column("change_summary", sa.Text(), nullable=True),
        sa.Column("changed_parameters", sa.JSON(), nullable=True),
        sa.Column("created_at_utc", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_slocum_mission_file_versions_mission_file_id", "slocum_mission_file_versions", ["mission_file_id"], unique=False)
    op.create_index("ix_slocum_mission_file_versions_changed_by_username", "slocum_mission_file_versions", ["changed_by_username"], unique=False)

    op.create_table(
        "slocum_deployment_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("deployment_id", sa.Integer(), sa.ForeignKey("slocum_deployments.id"), nullable=False),
        sa.Column("snapshot_number", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("file_states", sa.JSON(), nullable=True),
        sa.Column("parameter_summary", sa.JSON(), nullable=True),
        sa.Column("created_by_username", sa.String(), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
    )
    op.create_index("ix_slocum_deployment_snapshots_deployment_id", "slocum_deployment_snapshots", ["deployment_id"], unique=False)
    op.create_index("ix_slocum_deployment_snapshots_created_by_username", "slocum_deployment_snapshots", ["created_by_username"], unique=False)

    op.create_table(
        "slocum_mission_change_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("deployment_id", sa.Integer(), sa.ForeignKey("slocum_deployments.id"), nullable=False),
        sa.Column("mission_file_id", sa.Integer(), sa.ForeignKey("slocum_mission_files.id"), nullable=True),
        sa.Column("snapshot_id", sa.Integer(), sa.ForeignKey("slocum_deployment_snapshots.id"), nullable=True),
        sa.Column("change_type", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("changed_by_username", sa.String(), nullable=False),
        sa.Column("request_method", sa.String(), nullable=False),
        sa.Column("original_request", sa.Text(), nullable=True),
        sa.Column("created_at_utc", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_slocum_mission_change_logs_deployment_id", "slocum_mission_change_logs", ["deployment_id"], unique=False)
    op.create_index("ix_slocum_mission_change_logs_mission_file_id", "slocum_mission_change_logs", ["mission_file_id"], unique=False)
    op.create_index("ix_slocum_mission_change_logs_snapshot_id", "slocum_mission_change_logs", ["snapshot_id"], unique=False)
    op.create_index("ix_slocum_mission_change_logs_change_type", "slocum_mission_change_logs", ["change_type"], unique=False)
    op.create_index("ix_slocum_mission_change_logs_changed_by_username", "slocum_mission_change_logs", ["changed_by_username"], unique=False)
    op.create_index("ix_slocum_mission_change_logs_request_method", "slocum_mission_change_logs", ["request_method"], unique=False)
    op.create_index("ix_slocum_mission_change_logs_created_at_utc", "slocum_mission_change_logs", ["created_at_utc"], unique=False)


def downgrade() -> None:
    op.drop_table("slocum_mission_change_logs")
    op.drop_table("slocum_deployment_snapshots")
    op.drop_table("slocum_mission_file_versions")
    op.drop_table("slocum_mission_files")
    op.drop_table("slocum_deployments")
