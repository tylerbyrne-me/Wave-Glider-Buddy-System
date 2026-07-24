"""Central application logging setup (format, levels, optional file handler)."""
from __future__ import annotations

import logging
import re
import sys
import uuid
from contextvars import ContextVar, Token
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional, Union

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_CTX: ContextVar[str] = ContextVar("request_id", default="-")
# Incoming IDs: keep short, printable, and free of whitespace/control chars.
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

_LOG_FORMAT = "%(asctime)s %(levelname)-5.5s [%(name)s] [%(request_id)s] %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Third-party loggers that spam INFO during normal HTTP / scheduler work.
_QUIET_LOGGERS = (
    "httpx",
    "httpcore",
    "apscheduler",
    "apscheduler.scheduler",
    "apscheduler.executors",
    "apscheduler.executors.default",
)


def get_request_id() -> str:
    """Return the current request id, or ``-`` outside an HTTP request."""
    return _REQUEST_ID_CTX.get()


def bind_request_id(request_id: str) -> Token:
    """Bind ``request_id`` for the current context; return a reset token."""
    return _REQUEST_ID_CTX.set(request_id)


def reset_request_id(token: Token) -> None:
    """Restore the previous request id binding."""
    _REQUEST_ID_CTX.reset(token)


def normalize_request_id(raw: Optional[str]) -> str:
    """Accept a client-supplied id when safe; otherwise generate a new one."""
    if raw is not None:
        candidate = raw.strip()
        if _REQUEST_ID_RE.fullmatch(candidate):
            return candidate
    return uuid.uuid4().hex[:12]


class RequestIdFilter(logging.Filter):
    """Inject ``record.request_id`` from the request ContextVar."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _REQUEST_ID_CTX.get()
        return True


def _parse_level(level: Union[str, int]) -> int:
    if isinstance(level, int):
        return level
    resolved = logging.getLevelName(str(level).upper())
    if isinstance(resolved, int):
        return resolved
    return logging.INFO


def configure_logging(
    level: Union[str, int] = "INFO",
    log_file_path: Optional[Path] = None,
    *,
    force: bool = True,
) -> None:
    """Configure root logging once for the FastAPI process.

    - Timestamps on every line for wall-clock correlation
    - ``request_id`` field (``-`` outside HTTP; set by middleware)
    - App/root level from ``LOG_LEVEL`` / ``level``
    - Quiet httpx / APScheduler at WARNING (app ``AUTOMATED:`` / ``BACKGROUND TASK:`` stay)
    - Optional rotating file handler when ``log_file_path`` is set
    """
    resolved_level = _parse_level(level)
    root = logging.getLogger()

    if force:
        for handler in list(root.handlers):
            root.removeHandler(handler)
            handler.close()

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)
    request_id_filter = RequestIdFilter()

    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(request_id_filter)
    stream_handler.setLevel(resolved_level)
    root.addHandler(stream_handler)
    root.setLevel(resolved_level)

    if log_file_path is not None:
        log_path = Path(log_file_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(request_id_filter)
        file_handler.setLevel(resolved_level)
        root.addHandler(file_handler)

    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
