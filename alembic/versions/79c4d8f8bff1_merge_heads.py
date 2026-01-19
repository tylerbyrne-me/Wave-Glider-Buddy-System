"""merge heads

Revision ID: 79c4d8f8bff1
Revises: 20260118_120001, f63b026b32cd
Create Date: 2026-01-18 10:37:26.567860

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '79c4d8f8bff1'
down_revision: Union[str, Sequence[str], None] = ('20260118_120001', 'f63b026b32cd')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
