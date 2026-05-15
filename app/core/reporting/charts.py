"""Render matplotlib report figures to ReportLab Image flowables."""

from __future__ import annotations

import io
import logging
from typing import Any, Dict, List, Optional

import matplotlib.pyplot as plt
import pandas as pd
from PIL import Image as PILImage
from reportlab.platypus import Image

from ..plotting import (
    plot_c3_for_report,
    plot_ctd_for_report,
    plot_power_for_report,
    plot_telemetry_page_with_notes,
    plot_wave_for_report,
    plot_weather_for_report,
    report_pdf_rc_context,
)

logger = logging.getLogger(__name__)

DEFAULT_DPI = 200


def _fig_to_image(
    fig: Any,
    *,
    dpi: int = DEFAULT_DPI,
    max_width_pt: float,
    max_height_pt: float | None = None,
) -> Image:
    buf = io.BytesIO()
    try:
        fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight", pad_inches=0.08, facecolor="white")
    finally:
        plt.close(fig)
    buf.seek(0)
    pil = PILImage.open(buf)
    px_w, px_h = pil.size
    aspect = px_h / max(px_w, 1)
    width_pt = max_width_pt
    height_pt = width_pt * aspect
    if max_height_pt is not None and height_pt > max_height_pt:
        height_pt = max_height_pt
        width_pt = height_pt / aspect
    if width_pt > max_width_pt:
        width_pt = max_width_pt
        height_pt = width_pt * aspect
    buf.seek(0)
    return Image(buf, width=width_pt, height=height_pt)


def chart_telemetry_image(
    telemetry_df: pd.DataFrame,
    note_annotations: Optional[List[Dict[str, Any]]],
    *,
    max_width_pt: float,
    max_height_pt: float | None = None,
    dpi: int = DEFAULT_DPI,
) -> Image:
    with report_pdf_rc_context():
        fig = plt.figure(figsize=(8.27, 11.69))
        plot_telemetry_page_with_notes(fig, telemetry_df, note_annotations=note_annotations or [])
    return _fig_to_image(fig, dpi=dpi, max_width_pt=max_width_pt, max_height_pt=max_height_pt)


def chart_power_image(
    power_df: pd.DataFrame,
    *,
    max_width_pt: float,
    max_height_pt: float | None = None,
    dpi: int = DEFAULT_DPI,
) -> Image:
    with report_pdf_rc_context():
        fig, ax = plt.subplots(figsize=(11.69, 8.27))
        plot_power_for_report(ax, power_df)
        fig.tight_layout(pad=2.0)
    return _fig_to_image(fig, dpi=dpi, max_width_pt=max_width_pt, max_height_pt=max_height_pt)


def chart_ctd_image(
    ctd_df: pd.DataFrame,
    *,
    max_width_pt: float,
    max_height_pt: float | None = None,
    dpi: int = DEFAULT_DPI,
) -> Image:
    with report_pdf_rc_context():
        fig = plt.figure(figsize=(11.69, 8.27))
        plot_ctd_for_report(fig, ctd_df)
        fig.tight_layout(rect=[0, 0.03, 1, 0.95])
    return _fig_to_image(fig, dpi=dpi, max_width_pt=max_width_pt, max_height_pt=max_height_pt)


def chart_weather_image(
    weather_df: pd.DataFrame,
    *,
    max_width_pt: float,
    max_height_pt: float | None = None,
    dpi: int = DEFAULT_DPI,
) -> Image:
    with report_pdf_rc_context():
        fig = plt.figure(figsize=(11.69, 8.27))
        plot_weather_for_report(fig, weather_df)
        fig.tight_layout(rect=[0, 0.03, 1, 0.95])
    return _fig_to_image(fig, dpi=dpi, max_width_pt=max_width_pt, max_height_pt=max_height_pt)


def chart_wave_image(
    wave_df: pd.DataFrame,
    *,
    max_width_pt: float,
    max_height_pt: float | None = None,
    dpi: int = DEFAULT_DPI,
) -> Image:
    with report_pdf_rc_context():
        fig = plt.figure(figsize=(11.69, 8.27))
        plot_wave_for_report(fig, wave_df)
        fig.tight_layout(rect=[0, 0.03, 1, 0.95])
    return _fig_to_image(fig, dpi=dpi, max_width_pt=max_width_pt, max_height_pt=max_height_pt)


def chart_c3_image(
    fluorometer_df: pd.DataFrame,
    *,
    channel_map: dict | None = None,
    max_width_pt: float,
    max_height_pt: float | None = None,
    dpi: int = DEFAULT_DPI,
) -> Image:
    with report_pdf_rc_context():
        fig = plt.figure(figsize=(11.69, 8.27))
        plot_c3_for_report(fig, fluorometer_df, channel_map=channel_map)
        fig.tight_layout(rect=[0, 0.03, 1, 0.95])
    return _fig_to_image(fig, dpi=dpi, max_width_pt=max_width_pt, max_height_pt=max_height_pt)
