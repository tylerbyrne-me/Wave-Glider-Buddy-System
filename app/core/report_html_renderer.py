from __future__ import annotations

from pathlib import Path
from typing import Any, Dict
import logging
import tempfile

from jinja2 import Environment, FileSystemLoader, select_autoescape

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATES_ROOT = PROJECT_ROOT / "web" / "templates"
STATIC_ROOT = PROJECT_ROOT / "web" / "static"


def _render_hybrid_phase1_html(view_model: Dict[str, Any]) -> str:
    css_path = STATIC_ROOT / "css" / "reports" / "hybrid_report.css"
    css_text = css_path.read_text(encoding="utf-8") if css_path.exists() else ""

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_ROOT)),
        autoescape=select_autoescape(default=True),
    )
    template = env.get_template("reports/hybrid_phase1_report.html")
    return template.render(view_model=view_model, css_text=css_text)


async def render_hybrid_phase1_pdf(*, view_model: Dict[str, Any], output_pdf_path: Path) -> None:
    html = _render_hybrid_phase1_html(view_model)
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:
        raise RuntimeError("Playwright is not available for hybrid HTML rendering.") from exc

    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False, encoding="utf-8") as tmp:
        tmp.write(html)
        html_file_path = Path(tmp.name)

    logger.info("Rendering hybrid phase-1 PDF with Playwright: %s", output_pdf_path)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page()
        await page.goto(html_file_path.as_uri(), wait_until="networkidle")
        await page.pdf(
            path=str(output_pdf_path),
            format="A4",
            print_background=True,
            margin={"top": "16mm", "bottom": "14mm", "left": "12mm", "right": "12mm"},
        )
        await browser.close()
