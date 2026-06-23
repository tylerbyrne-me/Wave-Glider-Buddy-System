"""consolidate_offload_comments

Revision ID: 20260623_offload_comments
Revises: 20260623_override_set_at
Create Date: 2026-06-23

Copy legacy user-entered offload_notes_file_size into user_notes.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision: str = "20260623_offload_comments"
down_revision: Union[str, Sequence[str], None] = "20260623_override_set_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PARSER_PREFIX = "Auto-generated from WG-VM4 data"


def _merge_user_notes(user_notes: str | None, legacy: str | None) -> str | None:
    user = (user_notes or "").strip()
    legacy_text = (legacy or "").strip()
    parts: list[str] = []
    if user:
        parts.append(user)
    if legacy_text and not legacy_text.startswith(PARSER_PREFIX):
        if legacy_text != user and legacy_text not in user:
            parts.append(legacy_text)
    return "\n\n".join(parts) if parts else None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table("offload_logs"):
        return

    rows = bind.execute(
        text(
            "SELECT id, user_notes, offload_notes_file_size FROM offload_logs"
        )
    ).fetchall()

    for row_id, user_notes, offload_notes_file_size in rows:
        legacy = (offload_notes_file_size or "").strip()
        if not legacy or legacy.startswith(PARSER_PREFIX):
            continue
        merged = _merge_user_notes(user_notes, offload_notes_file_size)
        if merged and merged != (user_notes or "").strip():
            bind.execute(
                text("UPDATE offload_logs SET user_notes = :notes WHERE id = :id"),
                {"notes": merged, "id": row_id},
            )


def downgrade() -> None:
    # Data consolidation is not reversed; user_notes content may have been merged.
    pass
