"""Slocum glider weekly PDF report generation."""

from __future__ import annotations

import asyncio
import io
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, List, Optional

import matplotlib.pyplot as plt
import pandas as pd
from PIL import Image as PILImage
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer
from sqlmodel import Session as SQLModelSession, select

from .. import models
from ..data import processors
from ..geo.map_utils import generate_kml_from_track_points, prepare_track_points
from ..plotting import report_pdf_rc_context
from ..slocum_cache_service import get_cached_or_fetch_bundle_df, slice_processed_df
from ..slocum_deployment_service import get_or_create_deployment_for_dataset
from ..slocum_mirror_service import dashboard_df_to_track_df
from ..slocum_overage_cache import OverageResult
from ..utils import slocum_mission_key
from .common import build_platform_cover_flowables, get_report_paragraph_styles
from .constants import REPORTS_ROOT

logger = logging.getLogger(__name__)

SLOCUM_WEEKLY_REPORT_VARIABLE_GROUPS = {
    "track": ["time", "latitude", "longitude", "depth"],
    "dashboard": None,
    "ctd": None,
}


def default_slocum_weekly_date_window() -> tuple[date, date]:
    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=7)
    return start_date, end_date


def _iso_window(start_date: date, end_date: date) -> tuple[str, str]:
    start_dt = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
    end_dt = datetime.combine(end_date, datetime.max.time().replace(microsecond=0), tzinfo=timezone.utc)
    return (
        start_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        end_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


async def load_slocum_report_dataframes(
    dataset_id: str,
    start_date: date,
    end_date: date,
) -> dict[str, pd.DataFrame]:
    time_start, time_end = _iso_window(start_date, end_date)
    hours_back = max(1, int((end_date - start_date).total_seconds() / 3600) + 24)

    async def _load(bundle: str) -> pd.DataFrame:
        result = await get_cached_or_fetch_bundle_df(
            dataset_id,
            bundle,
            time_start,
            time_end,
            hours_back=hours_back,
            context="report",
            return_metadata=True,
        )
        if isinstance(result, OverageResult):
            return result.df if result.df is not None else pd.DataFrame()
        return result if isinstance(result, pd.DataFrame) and result is not None else pd.DataFrame()

    dash_raw, ctd_raw = await asyncio.gather(_load("dashboard"), _load("ctd"))
    # Results are already window-sliced by the overage service; re-slice for safety.
    dashboard = slice_processed_df(
        dash_raw if dash_raw is not None else pd.DataFrame(),
        hours_back=hours_back,
        use_date_range=True,
        time_start_str=time_start,
        time_end_str=time_end,
    )
    ctd = slice_processed_df(
        ctd_raw if ctd_raw is not None else pd.DataFrame(),
        hours_back=hours_back,
        use_date_range=True,
        time_start_str=time_start,
        time_end_str=time_end,
    )
    return {
        "track": dashboard_df_to_track_df(dashboard),
        "dashboard": dashboard,
        "ctd": ctd,
    }


def load_slocum_goals_for_report(session: SQLModelSession, deployment_id: int) -> List[models.SlocumDeploymentGoal]:
    return list(
        session.exec(
            select(models.SlocumDeploymentGoal)
            .where(models.SlocumDeploymentGoal.deployment_id == deployment_id)
            .order_by(models.SlocumDeploymentGoal.created_at_utc)
        ).all()
    )


def load_slocum_notes_for_report(session: SQLModelSession, deployment_id: int) -> List[models.SlocumDeploymentNote]:
    return list(
        session.exec(
            select(models.SlocumDeploymentNote)
            .where(
                models.SlocumDeploymentNote.deployment_id == deployment_id,
                models.SlocumDeploymentNote.include_in_report == True,  # noqa: E712
            )
            .order_by(models.SlocumDeploymentNote.created_at_utc)
        ).all()
    )


def _fig_to_image(fig: Any, *, max_width_pt: float) -> Image:
    buf = io.BytesIO()
    try:
        fig.savefig(buf, format="png", dpi=180, bbox_inches="tight", pad_inches=0.05, facecolor="white")
    finally:
        plt.close(fig)
    buf.seek(0)
    pil = PILImage.open(buf)
    px_w, px_h = pil.size
    aspect = px_h / max(px_w, 1)
    width_pt = max_width_pt
    height_pt = width_pt * aspect
    buf.seek(0)
    return Image(buf, width=width_pt, height=height_pt)


def _line_chart_image(df: pd.DataFrame, y_col: str, title: str, *, max_width_pt: float) -> Optional[Image]:
    if df.empty or "Timestamp" not in df.columns or y_col not in df.columns:
        return None
    series = df.set_index("Timestamp")[y_col].astype(float).dropna()
    if series.empty:
        return None
    with report_pdf_rc_context():
        fig, ax = plt.subplots(figsize=(8.27, 3.5))
        ax.plot(series.index, series.values, linewidth=1.2)
        ax.set_title(title)
        ax.grid(True, alpha=0.3)
        fig.autofmt_xdate()
    return _fig_to_image(fig, max_width_pt=max_width_pt)


def write_slocum_weekly_pdf(
    *,
    dataset_id: str,
    data_frames: dict[str, pd.DataFrame],
    goals: List[models.SlocumDeploymentGoal],
    notes: List[models.SlocumDeploymentNote],
    start_date: date,
    end_date: date,
    output_path: Path,
) -> Path:
    styles = get_report_paragraph_styles()
    max_width = 180 * mm
    story: list[Any] = []
    date_range = f"{start_date.isoformat()} to {end_date.isoformat()}"
    story.extend(
        build_platform_cover_flowables(
            title="Slocum Weekly Mission Report",
            platform_name="Slocum Glider",
            mission_id=dataset_id,
            mission_title=dataset_id,
            date_range_str=date_range,
        )
    )
    story.append(Spacer(1, 12))
    story.append(Paragraph("Mission goals", styles["Heading2"]))
    if goals:
        for goal in goals:
            mark = "[x]" if goal.is_completed else "[ ]"
            story.append(Paragraph(f"{mark} {goal.description}", styles["Body"]))
    else:
        story.append(Paragraph("No goals recorded.", styles["Body"]))
    story.append(Spacer(1, 8))
    story.append(Paragraph("Mission notes", styles["Heading2"]))
    if notes:
        for note in notes:
            story.append(Paragraph(note.content, styles["Body"]))
    else:
        story.append(Paragraph("No notes flagged for report.", styles["Body"]))
    story.append(Spacer(1, 12))

    dash_df = data_frames.get("dashboard", pd.DataFrame())
    for y_col, title in (
        ("MDepth", "Measured depth (m)"),
        ("MAltitude", "Altitude (m)"),
        ("MBattery", "Battery (V)"),
        ("CPitch", "Commanded pitch (deg)"),
    ):
        img = _line_chart_image(dash_df, y_col, title, max_width_pt=max_width)
        if img:
            story.append(Paragraph(title, styles["Heading3"]))
            story.append(img)
            story.append(Spacer(1, 8))

    ctd_df = data_frames.get("ctd", pd.DataFrame())
    for y_col, title in (
        ("Temperature", "CTD temperature"),
        ("Salinity", "CTD salinity"),
        ("Density", "CTD density"),
    ):
        img = _line_chart_image(ctd_df, y_col, title, max_width_pt=max_width)
        if img:
            story.append(Paragraph(title, styles["Heading3"]))
            story.append(img)
            story.append(Spacer(1, 8))

    track_df = data_frames.get("track", pd.DataFrame())
    if not track_df.empty:
        points = prepare_track_points(track_df, max_points=500)
        if points:
            story.append(Paragraph("Track summary", styles["Heading2"]))
            story.append(Paragraph(f"{len(points)} track points in report window.", styles["Body"]))
            _ = generate_kml_from_track_points(points, dataset_id)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(output_path), pagesize=(210 * mm, 297 * mm))
    doc.build(story)
    return output_path


async def create_and_save_slocum_weekly_report(dataset_id: str, session: SQLModelSession) -> Optional[str]:
    start_date, end_date = default_slocum_weekly_date_window()
    data_frames = await load_slocum_report_dataframes(dataset_id, start_date, end_date)
    if all(df.empty for df in data_frames.values()):
        logger.warning("No Slocum report data for dataset %s", dataset_id)
        return None

    deployment = get_or_create_deployment_for_dataset(
        session,
        dataset_id,
        created_by_username="system",
    )
    deployment_id = deployment.id if deployment else 0
    goals = load_slocum_goals_for_report(session, deployment_id) if deployment_id else []
    notes = load_slocum_notes_for_report(session, deployment_id) if deployment_id else []

    mission_key = slocum_mission_key(dataset_id) or dataset_id
    safe_id = mission_key.replace("/", "_").replace("\\", "_")
    report_dir = REPORTS_ROOT / "slocum" / safe_id
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    filename = f"weekly_report_{safe_id}_{timestamp}.pdf"
    output_path = report_dir / filename
    write_slocum_weekly_pdf(
        dataset_id=dataset_id,
        data_frames=data_frames,
        goals=goals,
        notes=notes,
        start_date=start_date,
        end_date=end_date,
        output_path=output_path,
    )
    return f"/static/mission_reports/slocum/{safe_id}/{filename}"
