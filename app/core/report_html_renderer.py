from __future__ import annotations

import asyncio
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .playwright_chromium_utils import chromium_launch_kwargs

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATES_ROOT = PROJECT_ROOT / "web" / "templates"
STATIC_ROOT = PROJECT_ROOT / "web" / "static"

_PLAYWRIGHT_WORKER = Path(__file__).resolve().parent / "hybrid_report_playwright_worker.py"


def _render_hybrid_phase1_html(view_model: Dict[str, Any]) -> str:
    css_path = STATIC_ROOT / "css" / "reports" / "hybrid_report.css"
    css_text = css_path.read_text(encoding="utf-8") if css_path.exists() else ""

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_ROOT)),
        autoescape=select_autoescape(default=True),
    )
    template = env.get_template("reports/hybrid_phase1_report.html")
    return template.render(view_model=view_model, css_text=css_text)


async def _render_hybrid_phase1_pdf_inprocess(*, html_file_path: Path, output_pdf_path: Path) -> None:
    """Playwright in the current process (local dev only; avoid under Gunicorn prefork)."""
    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(**chromium_launch_kwargs())
        try:
            page = await browser.new_page()
            await page.goto(html_file_path.as_uri(), wait_until="domcontentloaded", timeout=120_000)
            await page.pdf(
                path=str(output_pdf_path),
                format="A4",
                print_background=True,
                margin={"top": "16mm", "bottom": "14mm", "left": "12mm", "right": "12mm"},
            )
        finally:
            await browser.close()


async def _run_playwright_worker_subprocess(*, html_file_path: Path, output_pdf_path: Path) -> None:
    """Spawn a fresh Python process to run Playwright (avoids Node/V8 crashes in forked Gunicorn workers)."""
    if not _PLAYWRIGHT_WORKER.is_file():
        raise RuntimeError(f"Playwright worker script missing: {_PLAYWRIGHT_WORKER}")

    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        str(_PLAYWRIGHT_WORKER),
        str(html_file_path),
        str(output_pdf_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise TimeoutError("Playwright PDF subprocess exceeded 300s") from None

    if proc.returncode != 0:
        err = (stderr or b"").decode("utf-8", errors="replace")[:8000]
        out = (stdout or b"").decode("utf-8", errors="replace")[:4000]
        raise RuntimeError(
            f"Playwright worker exited with code {proc.returncode}. stderr:\n{err}\nstdout:\n{out}"
        )


async def render_hybrid_phase1_pdf(*, view_model: Dict[str, Any], output_pdf_path: Path) -> None:
    html = _render_hybrid_phase1_html(view_model)
    try:
        import importlib.util

        if importlib.util.find_spec("playwright") is None:
            raise RuntimeError("Playwright is not installed for hybrid HTML rendering.")
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError("Playwright is not installed for hybrid HTML rendering.") from exc

    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False, encoding="utf-8") as tmp:
        tmp.write(html)
        html_file_path = Path(tmp.name)

    logger.info("Rendering hybrid phase-1 PDF with Playwright: %s", output_pdf_path)
    use_inprocess = os.environ.get("WAVE_GLIDER_PLAYWRIGHT_INPROCESS", "").lower() in ("1", "true", "yes")
    if use_inprocess:
        logger.info("Using in-process Playwright (WAVE_GLIDER_PLAYWRIGHT_INPROCESS is set).")
    try:
        if use_inprocess:
            await _render_hybrid_phase1_pdf_inprocess(
                html_file_path=html_file_path,
                output_pdf_path=output_pdf_path,
            )
        else:
            await _run_playwright_worker_subprocess(
                html_file_path=html_file_path,
                output_pdf_path=output_pdf_path,
            )
    finally:
        try:
            html_file_path.unlink(missing_ok=True)
        except OSError:
            pass
