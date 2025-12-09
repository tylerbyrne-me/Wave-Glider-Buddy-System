"""add_end_of_mission_report_url

Revision ID: 20251209_134909
Revises: 4175c125aae7
Create Date: 2025-12-09 13:49:09.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20251209_134909'
down_revision: Union[str, Sequence[str], None] = '4175c125aae7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add end_of_mission_report_url column to mission_overview table."""
    op.add_column('mission_overview', sa.Column('end_of_mission_report_url', sa.String(), nullable=True))


def downgrade() -> None:
    """Remove end_of_mission_report_url column from mission_overview table."""
    op.drop_column('mission_overview', 'end_of_mission_report_url')

