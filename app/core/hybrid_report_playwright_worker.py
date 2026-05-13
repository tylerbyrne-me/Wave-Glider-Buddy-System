"""
Subprocess entrypoint for hybrid HTML → PDF via Playwright.

Gunicorn (and other prefork servers) fork workers before handling requests; starting
Playwright's Node/V8 driver inside a forked worker can crash with native check failures
when mapping executable memory. Running this module in a **fresh** ``python`` process
isolates Chromium/Node from the worker's address space.

Usage:
    python hybrid_report_playwright_worker.py <absolute_html_path> <absolute_output_pdf_path>

RPM-based servers (RHEL, Rocky, AlmaLinux, …): ``playwright install-deps`` uses apt and will
fail. Install shared libraries with dnf, then either use Playwright's downloaded Chromium or set
``PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH`` to a distro Chromium binary. Example::

    sudo dnf install -y alsa-lib atk at-spi2-atk cups-libs gtk3 libdrm libXcomposite libXdamage libXext libXfixes libXi libXrandr libxcb libxkbcommon mesa-libgbm nss nspr pango

Optional env:

    PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
        If set to an existing executable, Playwright uses it instead of the bundled Chromium.
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    from playwright_chromium_utils import chromium_launch_kwargs
except ModuleNotFoundError:  # pragma: no cover - depends on sys.path[0]
    from app.core.playwright_chromium_utils import chromium_launch_kwargs


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
        browser = playwright.chromium.launch(**chromium_launch_kwargs())
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
