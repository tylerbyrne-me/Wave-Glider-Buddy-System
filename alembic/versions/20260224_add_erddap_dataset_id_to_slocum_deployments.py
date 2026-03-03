"""add_erddap_dataset_id_to_slocum_deployments

Revision ID: 20260224_erddap
Revises: 20260224_slocum
Create Date: 2026-02-24

Add erddap_dataset_id to slocum_deployments to link to active realtime datasets.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260224_erddap"
down_revision: Union[str, Sequence[str], None] = "20260224_slocum"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "slocum_deployments",
        sa.Column("erddap_dataset_id", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_slocum_deployments_erddap_dataset_id",
        "slocum_deployments",
        ["erddap_dataset_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_slocum_deployments_erddap_dataset_id", table_name="slocum_deployments")
    op.drop_column("slocum_deployments", "erddap_dataset_id")
