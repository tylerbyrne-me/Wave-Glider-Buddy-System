"""
Subprocess entrypoint for hybrid HTML → PDF via Playwright.

Gunicorn (and other prefork servers) fork workers before handling requests; starting
Playwright's Node/V8 driver inside a forked worker can crash with native check failures
when mapping executable memory. Running this module in a **fresh** ``python`` process
isolates Chromium/Node from the worker's address space.

Usage:
    python hybrid_report_playwright_worker.py <absolute_html_path> <absolute_output_pdf_path>
"""
from __future__ import annotations

import sys
from pathlib import Path

# Chromium flags commonly required on Linux servers, containers, and locked-down hosts.
_CHROMIUM_LAUNCH_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--no-zygote",
]


def main() -> None:
    if len(sys.argv) != 3:
        print("usage: hybrid_report_playwright_worker.py <html_path> <output_pdf_path>", file=sys.stderr)
        raise SystemExit(2)
    html_path = Path(sys.argv[1]).resolve()
    pdf_path = Path(sys.argv[2]).resolve()
    if not html_path.is_file():
        print(f"HTML file not found: {html_path}", file=sys.stderr)
        raise SystemExit(1)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=_CHROMIUM_LAUNCH_ARGS)
        try:
            page = browser.new_page()
            page.goto(html_path.as_uri(), wait_until="domcontentloaded", timeout=120_000)
            page.pdf(
                path=str(pdf_path),
                format="A4",
                print_background=True,
                margin={"top": "16mm", "bottom": "14mm", "left": "12mm", "right": "12mm"},
            )
        finally:
            browser.close()


if __name__ == "__main__":
    main()
