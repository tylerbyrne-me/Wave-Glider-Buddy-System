"""
Gunicorn multi-worker leader lock.

Ensures only one worker runs heavy startup (remote sync, cache warm) and APScheduler.
The lock is held for the process lifetime and released on exit.
"""

import logging
from pathlib import Path
from typing import Optional, TextIO

logger = logging.getLogger(__name__)

IS_UNIX = True
try:
    import fcntl
except ImportError:
    IS_UNIX = False
    fcntl = None  # type: ignore

_lock_file_handle: Optional[TextIO] = None
_is_leader: bool = False


def try_acquire_startup_leader(lock_path: Path) -> bool:
    """
    Attempt to become the startup leader for this process.

    Returns True if this worker should run sync, cache initialization, and scheduler.
    On non-Unix systems (local dev), every worker is treated as leader.
    """
    global _lock_file_handle, _is_leader

    if not IS_UNIX or fcntl is None:
        logger.info(
            "Startup leader lock skipped (non-Unix). This worker acts as leader."
        )
        _is_leader = True
        return True

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fh = open(lock_path, "w")
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        _lock_file_handle = fh
        _is_leader = True
        logger.info("Acquired startup leader lock: %s", lock_path)
        return True
    except BlockingIOError:
        _is_leader = False
        logger.info(
            "Could not acquire startup leader lock (%s). "
            "Another worker runs sync, cache warm, and APScheduler.",
            lock_path,
        )
        return False
    except OSError as e:
        logger.error("Error acquiring startup leader lock: %s", e, exc_info=True)
        _is_leader = False
        return False


def is_startup_leader() -> bool:
    """Return whether this process holds the startup leader lock."""
    return _is_leader
