"""add_faq_and_chatbot_tables

Revision ID: f63b026b32cd
Revises: d1c61203e080
Create Date: 2025-12-16 11:51:48.132463

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f63b026b32cd'
down_revision: Union[str, Sequence[str], None] = 'd1c61203e080'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # Create faq_entries table if missing
    if "faq_entries" not in existing_tables:
        op.create_table(
            "faq_entries",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("question", sa.String(), nullable=False),
            sa.Column("answer", sa.Text(), nullable=False),
            sa.Column("keywords", sa.String(), nullable=True),
            sa.Column("category", sa.String(), nullable=True),
            sa.Column("tags", sa.String(), nullable=True),
            sa.Column("related_document_ids", sa.String(), nullable=True),
            sa.Column("related_tip_ids", sa.String(), nullable=True),
            sa.Column("created_by_username", sa.String(), nullable=False),
            sa.Column("created_at_utc", sa.DateTime(), nullable=False),
            sa.Column("updated_at_utc", sa.DateTime(), nullable=False),
            sa.Column("view_count", sa.Integer(), nullable=False),
            sa.Column("helpful_count", sa.Integer(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
    existing_faq_indexes = {
        idx["name"] for idx in inspector.get_indexes("faq_entries")
    } if "faq_entries" in inspector.get_table_names() else set()
    if "ix_faq_entries_question" not in existing_faq_indexes:
        op.create_index("ix_faq_entries_question", "faq_entries", ["question"], unique=False)
    if "ix_faq_entries_category" not in existing_faq_indexes:
        op.create_index("ix_faq_entries_category", "faq_entries", ["category"], unique=False)
    if "ix_faq_entries_created_by_username" not in existing_faq_indexes:
        op.create_index("ix_faq_entries_created_by_username", "faq_entries", ["created_by_username"], unique=False)
    if "ix_faq_entries_is_active" not in existing_faq_indexes:
        op.create_index("ix_faq_entries_is_active", "faq_entries", ["is_active"], unique=False)

    # Create chatbot_interactions table if missing
    if "chatbot_interactions" not in existing_tables:
        op.create_table(
            "chatbot_interactions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("query", sa.String(), nullable=False),
            sa.Column("matched_faq_ids", sa.String(), nullable=True),
            sa.Column("selected_faq_id", sa.Integer(), nullable=True),
            sa.Column("was_helpful", sa.Boolean(), nullable=True),
            sa.Column("created_at_utc", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["selected_faq_id"], ["faq_entries.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    existing_chatbot_indexes = {
        idx["name"] for idx in inspector.get_indexes("chatbot_interactions")
    } if "chatbot_interactions" in inspector.get_table_names() else set()
    if "ix_chatbot_interactions_user_id" not in existing_chatbot_indexes:
        op.create_index("ix_chatbot_interactions_user_id", "chatbot_interactions", ["user_id"], unique=False)
    if "ix_chatbot_interactions_created_at_utc" not in existing_chatbot_indexes:
        op.create_index("ix_chatbot_interactions_created_at_utc", "chatbot_interactions", ["created_at_utc"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_chatbot_interactions_created_at_utc', table_name='chatbot_interactions')
    op.drop_index('ix_chatbot_interactions_user_id', table_name='chatbot_interactions')
    op.drop_table('chatbot_interactions')
    op.drop_index('ix_faq_entries_is_active', table_name='faq_entries')
    op.drop_index('ix_faq_entries_created_by_username', table_name='faq_entries')
    op.drop_index('ix_faq_entries_category', table_name='faq_entries')
    op.drop_index('ix_faq_entries_question', table_name='faq_entries')
    op.drop_table('faq_entries')
