"""add_knowledge_base_tables

Revision ID: eb1164ea8808
Revises: 272c548c8d82
Create Date: 2025-12-15 11:45:56.841515

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'eb1164ea8808'
down_revision: Union[str, Sequence[str], None] = '272c548c8d82'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create knowledge_documents table
    op.create_table('knowledge_documents',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('file_path', sa.String(), nullable=False),
        sa.Column('file_name', sa.String(), nullable=False),
        sa.Column('file_type', sa.String(), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=False),
        sa.Column('category', sa.String(), nullable=True),
        sa.Column('tags', sa.String(), nullable=True),
        sa.Column('access_level', sa.String(), nullable=False),
        sa.Column('searchable_content', sa.Text(), nullable=True),
        sa.Column('uploaded_by_username', sa.String(), nullable=False),
        sa.Column('uploaded_at_utc', sa.DateTime(), nullable=False),
        sa.Column('updated_at_utc', sa.DateTime(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_knowledge_documents_title', 'knowledge_documents', ['title'], unique=False)
    op.create_index('ix_knowledge_documents_file_type', 'knowledge_documents', ['file_type'], unique=False)
    op.create_index('ix_knowledge_documents_category', 'knowledge_documents', ['category'], unique=False)
    op.create_index('ix_knowledge_documents_access_level', 'knowledge_documents', ['access_level'], unique=False)
    op.create_index('ix_knowledge_documents_uploaded_by_username', 'knowledge_documents', ['uploaded_by_username'], unique=False)
    op.create_index('ix_knowledge_documents_is_active', 'knowledge_documents', ['is_active'], unique=False)
    
    # Create knowledge_document_versions table
    op.create_table('knowledge_document_versions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('document_id', sa.Integer(), nullable=False),
        sa.Column('file_path', sa.String(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('uploaded_by_username', sa.String(), nullable=False),
        sa.Column('uploaded_at_utc', sa.DateTime(), nullable=False),
        sa.Column('change_notes', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(['document_id'], ['knowledge_documents.id'], name='fk_knowledge_document_versions_document_id'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_knowledge_document_versions_document_id', 'knowledge_document_versions', ['document_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_knowledge_document_versions_document_id', table_name='knowledge_document_versions')
    op.drop_table('knowledge_document_versions')
    op.drop_index('ix_knowledge_documents_is_active', table_name='knowledge_documents')
    op.drop_index('ix_knowledge_documents_uploaded_by_username', table_name='knowledge_documents')
    op.drop_index('ix_knowledge_documents_access_level', table_name='knowledge_documents')
    op.drop_index('ix_knowledge_documents_category', table_name='knowledge_documents')
    op.drop_index('ix_knowledge_documents_file_type', table_name='knowledge_documents')
    op.drop_index('ix_knowledge_documents_title', table_name='knowledge_documents')
    op.drop_table('knowledge_documents')
