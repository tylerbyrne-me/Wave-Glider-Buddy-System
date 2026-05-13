"""Shared Chromium launch options for Playwright PDF rendering (hybrid reports)."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

CHROMIUM_LAUNCH_ARGS: List[str] = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--no-zygote",
]


def chromium_launch_kwargs() -> Dict[str, Any]:
    """Keyword args for ``playwright.chromium.launch`` / async equivalent."""
    kwargs: Dict[str, Any] = {"headless": True, "args": list(CHROMIUM_LAUNCH_ARGS)}
    exe = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", "").strip()
    if exe:
        p = Path(exe)
        if p.is_file():
            kwargs["executable_path"] = str(p.resolve())
        else:
            logger.warning("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH is set but not a file: %s", exe)
    return kwargs
