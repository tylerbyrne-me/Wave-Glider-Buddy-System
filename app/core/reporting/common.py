"""Shared PDF primitives for Wave Glider and Slocum mission reports."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List, Optional

from .constants import LOGO_PATH
from .sections import build_cover
from .styling import build_paragraph_styles


def get_report_logo_path():
    """Canonical logo path for mission PDF cover pages."""
    return LOGO_PATH


def build_platform_cover_flowables(
    *,
    title: str,
    platform_name: str,
    mission_id: str,
    mission_title: str,
    date_range_str: str,
    generated_utc: Optional[str] = None,
    logo_path: Any = None,
) -> List[Any]:
    """Build cover-page flowables shared by WG and Slocum weekly reports."""
    return build_cover(
        title_for_pdf=title,
        platform_name=platform_name,
        mission_id=mission_id,
        mission_title=mission_title,
        date_range_str=date_range_str,
        generated_utc=generated_utc or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        logo_path=logo_path or get_report_logo_path(),
    )


def get_report_paragraph_styles():
    """Shared paragraph styles for mission PDF documents."""
    return build_paragraph_styles()
