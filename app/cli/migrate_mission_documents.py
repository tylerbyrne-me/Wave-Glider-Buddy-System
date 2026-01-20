import logging
import shutil
from pathlib import Path
from typing import Optional, Tuple

from sqlmodel import Session as SQLModelSession, select

from app.core import models, utils
from app.core.db import sqlite_engine


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mission_docs_migration")


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
STATIC_ROOT = PROJECT_ROOT / "web" / "static"
REPORTS_ROOT = STATIC_ROOT / "mission_reports"
PLANS_ROOT = STATIC_ROOT / "mission_plans"


def _resolve_static_path(path_value: str) -> Optional[Path]:
    normalized = path_value.replace("\\", "/").strip()
    if normalized.startswith("http://") or normalized.startswith("https://"):
        logger.warning(f"Skipping remote URL: {path_value}")
        return None
    normalized = normalized.lstrip("/")
    if normalized.startswith("web/static/"):
        return PROJECT_ROOT / normalized
    if normalized.startswith("static/"):
        return STATIC_ROOT / normalized.replace("static/", "", 1)
    candidate = Path(normalized)
    if candidate.is_absolute():
        return candidate
    return PROJECT_ROOT / candidate


def _build_static_url(file_path: Path) -> Optional[str]:
    try:
        relative = file_path.relative_to(STATIC_ROOT).as_posix()
    except ValueError:
        return None
    return f"/static/{relative}"


def _move_to_target_dir(
    current_url: str,
    target_dir: Path,
) -> Tuple[str, bool]:
    if not current_url:
        return current_url, False
    source_path = _resolve_static_path(current_url)
    if source_path is None:
        return current_url, False
    if not source_path.exists():
        logger.warning(f"Source file not found: {source_path} (from {current_url})")
        return current_url, False

    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / source_path.name

    if source_path.resolve() == target_path.resolve():
        new_url = _build_static_url(target_path)
        return new_url or current_url, False

    if target_path.exists():
        stem = target_path.stem
        suffix = target_path.suffix
        counter = 1
        while True:
            candidate = target_dir / f"{stem}_{counter}{suffix}"
            if not candidate.exists():
                target_path = candidate
                break
            counter += 1

    shutil.move(str(source_path), str(target_path))
    new_url = _build_static_url(target_path)
    if not new_url:
        logger.warning(f"Could not build static URL for {target_path}")
        return current_url, True
    return new_url, True


def migrate_documents() -> None:
    REPORTS_ROOT.mkdir(parents=True, exist_ok=True)
    PLANS_ROOT.mkdir(parents=True, exist_ok=True)

    updated_rows = 0
    moved_files = 0

    with SQLModelSession(sqlite_engine) as session:
        overviews = session.exec(select(models.MissionOverview)).all()
        for overview in overviews:
            mission_id = overview.mission_id

            report_dir = REPORTS_ROOT / utils.mission_storage_dir_name(mission_id, "reporting")
            forms_dir = PLANS_ROOT / utils.mission_storage_dir_name(mission_id, "forms")

            changed = False

            if overview.weekly_report_url:
                new_url, moved = _move_to_target_dir(overview.weekly_report_url, report_dir)
                if new_url != overview.weekly_report_url:
                    overview.weekly_report_url = new_url
                    changed = True
                moved_files += int(moved)

            if overview.end_of_mission_report_url:
                new_url, moved = _move_to_target_dir(overview.end_of_mission_report_url, report_dir)
                if new_url != overview.end_of_mission_report_url:
                    overview.end_of_mission_report_url = new_url
                    changed = True
                moved_files += int(moved)

            if overview.document_url:
                new_url, moved = _move_to_target_dir(overview.document_url, forms_dir)
                if new_url != overview.document_url:
                    overview.document_url = new_url
                    changed = True
                moved_files += int(moved)

            if changed:
                session.add(overview)
                updated_rows += 1

        if updated_rows:
            session.commit()

    legacy_plan_moves = _migrate_legacy_plan_files()
    legacy_report_moves = _migrate_legacy_report_files()
    logger.info(
        "Migration complete. Updated records: %s, files moved: %s, legacy plans moved: %s, legacy reports moved: %s",
        updated_rows,
        moved_files,
        legacy_plan_moves,
        legacy_report_moves,
    )


def _migrate_legacy_plan_files() -> int:
    """Move legacy mission plan files in the root folder into mission subfolders."""
    moved = 0
    if not PLANS_ROOT.exists():
        return moved

    for plan_file in PLANS_ROOT.glob("*_plan.*"):
        if plan_file.is_dir():
            continue
        if plan_file.parent != PLANS_ROOT:
            continue
        mission_id = plan_file.stem.replace("_plan", "")
        if not mission_id:
            continue
        target_dir = PLANS_ROOT / utils.mission_storage_dir_name(mission_id, "forms")
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / plan_file.name
        if target_path.exists():
            stem = target_path.stem
            suffix = target_path.suffix
            counter = 1
            while True:
                candidate = target_dir / f"{stem}_{counter}{suffix}"
                if not candidate.exists():
                    target_path = candidate
                    break
                counter += 1
        shutil.move(str(plan_file), str(target_path))
        moved += 1

    return moved


def _migrate_legacy_report_files() -> int:
    """Move legacy report files in the root folder into mission subfolders."""
    moved = 0
    if not REPORTS_ROOT.exists():
        return moved

    for report_file in REPORTS_ROOT.glob("*.pdf"):
        if report_file.is_dir():
            continue
        if report_file.parent != REPORTS_ROOT:
            continue
        filename = report_file.name

        mission_id = ""
        if "weekly_report_" in filename:
            token = filename.split("weekly_report_", 1)[1]
            mission_id = token.split("_", 1)[0]
        elif "End_of_Mission_Report_" in filename:
            token = filename.split("End_of_Mission_Report_", 1)[1]
            mission_id = token.split("_", 1)[0]
        else:
            parts = filename.split("_")
            if len(parts) > 2 and parts[-1].endswith(".pdf"):
                mission_id = parts[-2]

        if not mission_id:
            continue

        target_dir = REPORTS_ROOT / utils.mission_storage_dir_name(mission_id, "reporting")
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / report_file.name
        if target_path.exists():
            stem = target_path.stem
            suffix = target_path.suffix
            counter = 1
            while True:
                candidate = target_dir / f"{stem}_{counter}{suffix}"
                if not candidate.exists():
                    target_path = candidate
                    break
                counter += 1
        shutil.move(str(report_file), str(target_path))
        moved += 1

    return moved


if __name__ == "__main__":
    migrate_documents()
