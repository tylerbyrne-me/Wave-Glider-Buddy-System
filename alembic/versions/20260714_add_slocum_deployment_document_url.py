"""add_slocum_deployment_document_url

Revision ID: 20260714_slocum_document_url
Revises: 20260702_user_platform_access
Create Date: 2026-07-14

Formal mission plan document URL on slocum_deployments.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20260714_slocum_document_url"
down_revision: Union[str, Sequence[str], None] = "20260702_user_platform_access"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table("slocum_deployments"):
        return
    columns = {col["name"] for col in inspector.get_columns("slocum_deployments")}
    if "document_url" not in columns:
        op.add_column(
            "slocum_deployments",
            sa.Column("document_url", sa.String(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table("slocum_deployments"):
        return
    columns = {col["name"] for col in inspector.get_columns("slocum_deployments")}
    if "document_url" in columns:
        op.drop_column("slocum_deployments", "document_url")
