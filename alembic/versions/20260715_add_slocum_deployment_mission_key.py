"""add_slocum_deployment_mission_key

Revision ID: 20260715_slocum_mission_key
Revises: 20260715_slocum_checklist_refs
Create Date: 2026-07-15

Add suffix-agnostic mission_key so realtime and delayed datasets share briefing
metadata, checklists, and reports. Backfill, merge duplicates, re-key checklist
forms, and rename report directories.
"""
from __future__ import annotations

import re
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision: str = "20260715_slocum_mission_key"
down_revision: Union[str, Sequence[str], None] = "20260715_slocum_checklist_refs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SLOCUM_DATASET_ID_PATTERN = re.compile(
    r"^(?P<glider>[A-Za-z0-9]+)_(?P<start>\d{8})_(?P<num>\d+)(?:_(?P<mode>realtime|delayed))?$"
)
_CHECKLIST_FORM_TYPE = "slocum_daily_checklist"


def _mission_key_from_dataset_id(dataset_id: Optional[str]) -> Optional[str]:
    if not dataset_id or not str(dataset_id).strip():
        return None
    trimmed = str(dataset_id).strip()
    match = _SLOCUM_DATASET_ID_PATTERN.match(trimmed)
    if not match:
        return trimmed
    return f"{match.group('glider')}_{match.group('start')}_{match.group('num')}"


def _reports_root() -> Path:
    # alembic/versions -> repo root / web/static/mission_reports
    return Path(__file__).resolve().parents[2] / "web" / "static" / "mission_reports" / "slocum"


def _rename_report_directories() -> None:
    root = _reports_root()
    if not root.is_dir():
        return

    dirs = [p for p in root.iterdir() if p.is_dir()]
    # Prefer consolidating into the suffix-stripped key dir.
    by_key: dict[str, list[Path]] = defaultdict(list)
    for path in dirs:
        key = _mission_key_from_dataset_id(path.name) or path.name
        by_key[key].append(path)

    for mission_key, paths in by_key.items():
        target = root / mission_key
        # Sources are any dir whose name is not already the mission key
        sources = [p for p in paths if p.name != mission_key]
        if not sources:
            continue
        target.mkdir(parents=True, exist_ok=True)
        for source in sources:
            for file_path in source.iterdir():
                if not file_path.is_file():
                    continue
                dest = target / file_path.name
                if dest.exists():
                    # Keep the newer file when names collide.
                    if file_path.stat().st_mtime > dest.stat().st_mtime:
                        dest.unlink()
                        shutil.move(str(file_path), str(dest))
                    else:
                        file_path.unlink()
                else:
                    shutil.move(str(file_path), str(dest))
            # Remove empty source dir (or leftover subdirs)
            try:
                shutil.rmtree(source)
            except OSError:
                pass


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table("slocum_deployments"):
        return

    columns = {col["name"] for col in inspector.get_columns("slocum_deployments")}
    if "mission_key" not in columns:
        op.add_column(
            "slocum_deployments",
            sa.Column("mission_key", sa.String(), nullable=True),
        )
        op.create_index(
            "ix_slocum_deployments_mission_key",
            "slocum_deployments",
            ["mission_key"],
        )

    # Backfill mission_key from erddap_dataset_id
    rows = bind.execute(
        text(
            "SELECT id, erddap_dataset_id, mission_key, is_active, "
            "document_url, enabled_sensor_cards, checklist_reference_values, "
            "created_at_utc "
            "FROM slocum_deployments"
        )
    ).mappings().all()

    for row in rows:
        if row["mission_key"]:
            continue
        key = _mission_key_from_dataset_id(row["erddap_dataset_id"])
        if key:
            bind.execute(
                text("UPDATE slocum_deployments SET mission_key = :key WHERE id = :id"),
                {"key": key, "id": row["id"]},
            )

    # Refresh after backfill
    rows = bind.execute(
        text(
            "SELECT id, erddap_dataset_id, mission_key, is_active, "
            "document_url, enabled_sensor_cards, checklist_reference_values, "
            "created_at_utc "
            "FROM slocum_deployments"
        )
    ).mappings().all()

    # Merge active duplicates that share a mission_key (keep oldest)
    by_key: dict[str, list] = defaultdict(list)
    for row in rows:
        key = row["mission_key"]
        if not key or not row["is_active"]:
            continue
        by_key[key].append(row)

    child_tables = (
        "slocum_deployment_goals",
        "slocum_deployment_notes",
        "slocum_deployment_media",
    )
    coalesce_fields = (
        "document_url",
        "enabled_sensor_cards",
        "checklist_reference_values",
    )

    for mission_key, group in by_key.items():
        if len(group) < 2:
            continue
        group_sorted = sorted(
            group,
            key=lambda r: (r["created_at_utc"] is None, r["created_at_utc"] or "", r["id"]),
        )
        keeper = group_sorted[0]
        losers = group_sorted[1:]

        # Coalesce null metadata onto keeper from losers
        updates = {}
        for field in coalesce_fields:
            if keeper[field]:
                continue
            for loser in losers:
                if loser[field]:
                    updates[field] = loser[field]
                    break
        # Prefer delayed erddap_dataset_id if present among the group
        preferred_dataset_id = keeper["erddap_dataset_id"]
        for row in group_sorted:
            ds = row["erddap_dataset_id"] or ""
            if ds.endswith("_delayed"):
                preferred_dataset_id = ds
                break
        if preferred_dataset_id and preferred_dataset_id != keeper["erddap_dataset_id"]:
            updates["erddap_dataset_id"] = preferred_dataset_id

        if updates:
            set_clause = ", ".join(f"{k} = :{k}" for k in updates)
            bind.execute(
                text(f"UPDATE slocum_deployments SET {set_clause} WHERE id = :id"),
                {**updates, "id": keeper["id"]},
            )

        for loser in losers:
            for table in child_tables:
                if not inspector.has_table(table):
                    continue
                bind.execute(
                    text(
                        f"UPDATE {table} SET deployment_id = :keeper "
                        "WHERE deployment_id = :loser"
                    ),
                    {"keeper": keeper["id"], "loser": loser["id"]},
                )
            bind.execute(
                text(
                    "UPDATE slocum_deployments "
                    "SET is_active = 0, status = 'archived' WHERE id = :id"
                ),
                {"id": loser["id"]},
            )

    # Re-key Slocum checklist forms to mission_key
    if inspector.has_table("submitted_forms"):
        form_rows = bind.execute(
            text(
                "SELECT id, mission_id FROM submitted_forms "
                "WHERE form_type = :form_type"
            ),
            {"form_type": _CHECKLIST_FORM_TYPE},
        ).mappings().all()
        for form in form_rows:
            new_key = _mission_key_from_dataset_id(form["mission_id"])
            if new_key and new_key != form["mission_id"]:
                bind.execute(
                    text("UPDATE submitted_forms SET mission_id = :key WHERE id = :id"),
                    {"key": new_key, "id": form["id"]},
                )

    _rename_report_directories()


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table("slocum_deployments"):
        return
    columns = {col["name"] for col in inspector.get_columns("slocum_deployments")}
    if "mission_key" not in columns:
        return
    indexes = {idx["name"] for idx in inspector.get_indexes("slocum_deployments")}
    if "ix_slocum_deployments_mission_key" in indexes:
        op.drop_index("ix_slocum_deployments_mission_key", table_name="slocum_deployments")
    op.drop_column("slocum_deployments", "mission_key")
