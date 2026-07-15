"""Slocum weekly PDF report API."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session as SQLModelSession

from ..core.auth import get_current_active_user, get_current_admin_user, require_platform_access
from ..core import models
from ..core.infra.db import get_db_session
from ..core.infra.feature_toggles import is_feature_enabled
from ..core.reporting.slocum_reports import create_and_save_slocum_weekly_report, default_slocum_weekly_date_window
from ..core.utils import slocum_mission_key

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/slocum/reporting",
    tags=["Slocum Reporting"],
    dependencies=[Depends(require_platform_access("slocum"))],
)


def _classify_report_type(filename: str) -> str:
    name = filename.lower()
    if "weekly" in name:
        return "weekly"
    return "other"


@router.get("/datasets/{dataset_id}/reports")
async def list_slocum_reports(
    dataset_id: str,
    session: SQLModelSession = Depends(get_db_session),
    current_user: models.User = Depends(get_current_active_user),
):
    """List generated Slocum reports for a dataset (readable by any authenticated Slocum user)."""
    if not is_feature_enabled("slocum_platform"):
        raise HTTPException(status_code=403, detail="Slocum platform is disabled.")
    mission_key = slocum_mission_key(dataset_id) or dataset_id
    safe_id = mission_key.replace("/", "_").replace("\\", "_")
    report_dir = Path(__file__).resolve().parent.parent.parent / "web" / "static" / "mission_reports" / "slocum" / safe_id
    reports = []
    if report_dir.is_dir():
        for file_path in sorted(report_dir.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True):
            reports.append({
                "filename": file_path.name,
                "url": f"/static/mission_reports/slocum/{safe_id}/{file_path.name}",
                "report_type": _classify_report_type(file_path.name),
                "timestamp": datetime.utcfromtimestamp(file_path.stat().st_mtime).isoformat(),
            })
    return {"dataset_id": dataset_id, "mission_key": mission_key, "reports": reports}


@router.post("/datasets/{dataset_id}/generate-weekly-report")
async def generate_slocum_weekly_report(
    dataset_id: str,
    session: SQLModelSession = Depends(get_db_session),
    current_user: models.User = Depends(get_current_admin_user),
):
    if not is_feature_enabled("slocum_platform"):
        raise HTTPException(status_code=403, detail="Slocum platform is disabled.")
    url = await create_and_save_slocum_weekly_report(dataset_id, session)
    if not url:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No Slocum report data available for dataset '{dataset_id}'.",
        )
    start_date, end_date = default_slocum_weekly_date_window()
    return {
        "dataset_id": dataset_id,
        "report_url": url,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "message": "Slocum weekly report generated",
    }
