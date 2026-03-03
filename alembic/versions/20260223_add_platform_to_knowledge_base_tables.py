"""add_platform_to_knowledge_base_tables

Revision ID: 20260223_platform
Revises: 20260120_180000
Create Date: 2026-02-23

Add platform column (wave_glider | slocum) to KB-related tables for separate
Wave Glider and Slocum Knowledge Bases.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260223_platform"
down_revision: Union[str, Sequence[str], None] = "20260120_180000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PLATFORM_COLUMN = sa.Column("platform", sa.String(), nullable=False, server_default="wave_glider")


def upgrade() -> None:
    """Add platform column to KB-related tables. Backfill existing rows as wave_glider."""
    # knowledge_documents
    op.add_column("knowledge_documents", PLATFORM_COLUMN)
    op.create_index("ix_knowledge_documents_platform", "knowledge_documents", ["platform"], unique=False)

    # knowledge_document_versions
    op.add_column("knowledge_document_versions", PLATFORM_COLUMN)
    op.create_index("ix_knowledge_document_versions_platform", "knowledge_document_versions", ["platform"], unique=False)

    # user_notes
    op.add_column("user_notes", PLATFORM_COLUMN)
    op.create_index("ix_user_notes_platform", "user_notes", ["platform"], unique=False)

    # shared_tips
    op.add_column("shared_tips", PLATFORM_COLUMN)
    op.create_index("ix_shared_tips_platform", "shared_tips", ["platform"], unique=False)

    # faq_entries
    op.add_column("faq_entries", PLATFORM_COLUMN)
    op.create_index("ix_faq_entries_platform", "faq_entries", ["platform"], unique=False)

    # chatbot_interactions
    op.add_column("chatbot_interactions", PLATFORM_COLUMN)
    op.create_index("ix_chatbot_interactions_platform", "chatbot_interactions", ["platform"], unique=False)


def downgrade() -> None:
    """Remove platform column from KB-related tables."""
    op.drop_index("ix_chatbot_interactions_platform", table_name="chatbot_interactions")
    op.drop_column("chatbot_interactions", "platform")

    op.drop_index("ix_faq_entries_platform", table_name="faq_entries")
    op.drop_column("faq_entries", "platform")

    op.drop_index("ix_shared_tips_platform", table_name="shared_tips")
    op.drop_column("shared_tips", "platform")

    op.drop_index("ix_user_notes_platform", table_name="user_notes")
    op.drop_column("user_notes", "platform")

    op.drop_index("ix_knowledge_document_versions_platform", table_name="knowledge_document_versions")
    op.drop_column("knowledge_document_versions", "platform")

    op.drop_index("ix_knowledge_documents_platform", table_name="knowledge_documents")
    op.drop_column("knowledge_documents", "platform")
