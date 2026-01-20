import logging
from pathlib import Path
from typing import Optional

from sqlmodel import Session as SQLModelSession, select

from app.core import models
from app.core.db import sqlite_engine


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mission_file_integrity")


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
STATIC_ROOT = PROJECT_ROOT / "web" / "static"


def _resolve_static_path(path_value: str) -> Optional[Path]:
    normalized = path_value.replace("\\", "/").strip()
    if normalized.startswith("http://") or normalized.startswith("https://"):
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


def _check_path(label: str, value: Optional[str]) -> bool:
    if not value:
        return True
    resolved = _resolve_static_path(value)
    if resolved is None:
        logger.warning("Skipping remote %s: %s", label, value)
        return True
    if not resolved.exists():
        logger.error("Missing %s: %s -> %s", label, value, resolved)
        return False
    return True


def run_checks() -> None:
    missing = 0
    total = 0

    with SQLModelSession(sqlite_engine) as session:
        overviews = session.exec(select(models.MissionOverview)).all()
        for overview in overviews:
            total += 1
            if not _check_path("weekly_report_url", overview.weekly_report_url):
                missing += 1
            if not _check_path("end_of_mission_report_url", overview.end_of_mission_report_url):
                missing += 1
            if not _check_path("document_url", overview.document_url):
                missing += 1

        media_items = session.exec(select(models.MissionMedia)).all()
        for media in media_items:
            total += 1
            if not _check_path("mission_media.file_path", media.file_path):
                missing += 1
            if media.thumbnail_path and not _check_path("mission_media.thumbnail_path", media.thumbnail_path):
                missing += 1

    logger.info("Integrity check complete. Missing references: %s", missing)


if __name__ == "__main__":
    run_checks()
