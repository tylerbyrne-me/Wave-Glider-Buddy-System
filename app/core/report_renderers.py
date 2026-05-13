from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Dict, Any, List
import logging

from .report_html_renderer import render_hybrid_phase1_pdf

logger = logging.getLogger(__name__)

LegacyRendererCallable = Callable[[], Awaitable[str]]


@dataclass
class RendererRequest:
    renderer: str
    report_dir: Path
    report_filename_base: str
    view_model: Dict[str, Any]


def _url_to_path(*, reports_root: Path, report_url: str) -> Path:
    marker = "/static/mission_reports/"
    if marker not in report_url:
        raise ValueError(f"Could not map report URL to path: {report_url}")
    relative = report_url.split(marker, 1)[1].replace("/", "\\")
    return reports_root / relative


def _merge_hybrid_pdf(*, phase1_pdf: Path, legacy_pdf: Path, output_pdf: Path) -> None:
    import PyPDF2

    phase1_reader = PyPDF2.PdfReader(str(phase1_pdf))
    legacy_reader = PyPDF2.PdfReader(str(legacy_pdf))
    writer = PyPDF2.PdfWriter()

    for page in legacy_reader.pages:
        writer.add_page(page)

    for page in phase1_reader.pages:
        writer.add_page(page)

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    with output_pdf.open("wb") as f_out:
        writer.write(f_out)


async def render_report_with_strategy(
    *,
    request: RendererRequest,
    reports_root: Path,
    run_legacy_renderer: LegacyRendererCallable,
) -> str:
    if request.renderer != "hybrid_html":
        return await run_legacy_renderer()

    legacy_url = await run_legacy_renderer()
    legacy_pdf_path = _url_to_path(reports_root=reports_root, report_url=legacy_url)

    phase1_pdf_path = request.report_dir / f"{request.report_filename_base}_phase1.pdf"
    output_pdf_path = request.report_dir / f"{request.report_filename_base}_hybrid.pdf"
    output_url = f"/static/mission_reports/{request.report_dir.name}/{output_pdf_path.name}"

    try:
        await render_hybrid_phase1_pdf(view_model=request.view_model, output_pdf_path=phase1_pdf_path)
        _merge_hybrid_pdf(phase1_pdf=phase1_pdf_path, legacy_pdf=legacy_pdf_path, output_pdf=output_pdf_path)
        return output_url
    except Exception as exc:
        logger.warning("Hybrid HTML rendering failed. Falling back to legacy PDF. Error: %s", exc, exc_info=True)
        return legacy_url
