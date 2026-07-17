import errno
import logging
import os
import re
import sys
import time
import warnings
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Union

import pandas as pd

logger = logging.getLogger(__name__)

# Minimum valid date for timestamps (filters out epoch dates from parsing failures)
MIN_VALID_TIMESTAMP = datetime(2000, 1, 1, tzinfo=timezone.utc)

try:
    import fcntl  # type: ignore
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore

try:
    import msvcrt  # type: ignore
except ImportError:  # pragma: no cover - Unix
    msvcrt = None  # type: ignore


def unique_sibling_tmp_path(dest: Path) -> Path:
    """Temp path in the same directory as ``dest`` (required for atomic ``os.replace``)."""
    dest = Path(dest)
    return dest.with_name(f"{dest.name}.{os.getpid()}.{time.time_ns()}.tmp")


def sibling_lock_path(dest: Path) -> Path:
    """Sidecar lock path for a cache object (``name.lock`` next to ``name``)."""
    dest = Path(dest)
    return dest.with_name(f"{dest.name}.lock")


def iter_orphan_tmp_candidates(dest: Path) -> list[Path]:
    """Legacy ``name.tmp`` and unique ``name.*.tmp`` siblings for ``dest``."""
    dest = Path(dest)
    parent = dest.parent
    if not parent.is_dir():
        return []
    found: list[Path] = []
    legacy = parent / f"{dest.name}.tmp"
    if legacy.is_file() and legacy.stat().st_size > 0:
        found.append(legacy)
    found.extend(
        p for p in parent.glob(f"{dest.name}.*.tmp") if p.is_file() and p.stat().st_size > 0
    )
    return found


def promote_orphan_tmp_file(dest: Path) -> bool:
    """
    If ``dest`` is missing but a non-empty sibling ``.tmp`` exists, promote the newest.

    Recovers mirrors left with only ``*.parquet.tmp`` after a failed rename (seen on
    glider-dev when shared temp names raced or rename failed).
    """
    dest = Path(dest)
    if dest.is_file():
        return False
    candidates = iter_orphan_tmp_candidates(dest)
    if not candidates:
        return False
    newest = max(candidates, key=lambda p: p.stat().st_mtime)
    lock_path = sibling_lock_path(dest)
    try:
        with cross_process_file_lock(lock_path):
            if dest.is_file():
                return False
            if not newest.is_file():
                return False
            os.replace(newest, dest)
        for path in candidates:
            if path != newest and path.is_file():
                try:
                    path.unlink()
                except OSError:
                    pass
        logger.info("Promoted orphan cache tmp %s -> %s", newest.name, dest.name)
        return True
    except OSError as err:
        logger.warning("Failed to promote orphan tmp %s -> %s: %s", newest, dest, err)
        return False


def write_parquet_file_atomic(df: pd.DataFrame, dest: Path) -> None:
    """
    Write a DataFrame to ``dest`` via a unique temp file + ``os.replace``.

    The temp file is fully closed (and fsync'd) before rename so network/local FS
    that dislike renaming open files (and Windows readers) behave reliably.
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    promote_orphan_tmp_file(dest)
    tmp_path = unique_sibling_tmp_path(dest)
    lock_path = sibling_lock_path(dest)
    try:
        with open(tmp_path, "wb") as fh:
            df.to_parquet(fh, index=False)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                pass
        with cross_process_file_lock(lock_path):
            replace_path_with_retries(tmp_path, dest)
    except Exception:
        try:
            if tmp_path.is_file():
                tmp_path.unlink()
        except OSError:
            pass
        raise


def _is_retryable_replace_error(err: BaseException, *, is_windows: bool) -> bool:
    """
    Whether a failed replace should be retried.

    - Windows: PermissionError / sharing violation while a reader holds the file.
    - Linux: open readers do NOT block rename; only rare EBUSY/ETXTBSY are retryable.
      Treating EACCES as a lock causes multi-second stalls on real permission problems.
    """
    if not isinstance(err, OSError):
        return False
    en = getattr(err, "errno", None)
    winerror = getattr(err, "winerror", None)
    if is_windows:
        if isinstance(err, PermissionError):
            return True
        # WinError 5 (access), 32 (sharing violation)
        return en in (errno.EACCES, 32) or winerror in (5, 32)
    # POSIX: EBUSY / ETXTBSY only (not EACCES — that is ownership/mode)
    retryable = {errno.EBUSY}
    if hasattr(errno, "ETXTBSY"):
        retryable.add(errno.ETXTBSY)
    return en in retryable


@contextmanager
def cross_process_file_lock(
    lock_path: Path,
    *,
    timeout_seconds: float = 180.0,
) -> Iterator[None]:
    """
    Exclusive cross-process lock for shared-disk cache writers.

    - Linux/macOS: ``fcntl.flock`` (works across gunicorn workers)
    - Windows: ``msvcrt.locking`` (best-effort; still pair with replace retries)
    """
    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(lock_path, "a+b")
    start = time.monotonic()
    locked = False
    try:
        while True:
            try:
                if fcntl is not None:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    locked = True
                    break
                if msvcrt is not None:
                    fh.seek(0)
                    if fh.read(1) == b"":
                        fh.write(b"0")
                        fh.flush()
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                    locked = True
                    break
                # No platform lock available — proceed without blocking.
                locked = True
                break
            except OSError:
                if (time.monotonic() - start) >= timeout_seconds:
                    raise TimeoutError(f"Timed out waiting for file lock {lock_path}")
                time.sleep(0.1)
        yield
    finally:
        try:
            if locked:
                if fcntl is not None:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
                elif msvcrt is not None:
                    fh.seek(0)
                    try:
                        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                    except OSError:
                        pass
        finally:
            fh.close()


def replace_path_with_retries(
    src: Path,
    dest: Path,
    *,
    attempts: Optional[int] = None,
    initial_delay_seconds: float = 0.05,
) -> None:
    """
    Replace ``dest`` with ``src`` via ``os.replace`` (atomic on the same filesystem).

    Cross-platform behavior:
    - **Linux**: one-shot rename; open readers keep the old inode. Does not retry
      EACCES (permission/ownership). Brief retry only for EBUSY/ETXTBSY.
    - **Windows**: retry PermissionError/sharing violations; unlink+rename fallback.
    """
    src = Path(src)
    dest = Path(dest)
    is_windows = sys.platform.startswith("win")
    if attempts is None:
        attempts = 12 if is_windows else 3
    delay = initial_delay_seconds
    last_err: Optional[BaseException] = None

    for attempt in range(1, attempts + 1):
        try:
            os.replace(src, dest)
            return
        except OSError as err:
            last_err = err
            if not _is_retryable_replace_error(err, is_windows=is_windows):
                hint = ""
                if getattr(err, "errno", None) == errno.EACCES:
                    hint = (
                        f" Permission denied writing {dest} — check owner/mode "
                        f"(e.g. chown -R <appuser> {dest.parent})."
                    )
                raise PermissionError(
                    f"Could not replace {dest} with {src}: {err}.{hint}"
                ) from err
            if attempt >= attempts:
                break
            logger.debug(
                "File replace retryable failure (%s -> %s), retry %s/%s: %s",
                src,
                dest,
                attempt,
                attempts,
                err,
            )
            time.sleep(delay)
            delay = min(delay * 1.7, 1.0)

    if is_windows:
        try:
            if dest.is_file():
                dest.unlink()
            os.replace(src, dest)
            return
        except OSError as err:
            last_err = err

    raise PermissionError(
        f"Could not replace {dest} with {src} after {attempts} attempts "
        f"(last error: {last_err})."
    ) from last_err


def get_effective_local_path(
    source_preference: Optional[str], custom_local_path: Optional[str]
) -> Optional[str]:
    """Return the local data path to use: custom if set, else config default when source is 'local'."""
    if custom_local_path:
        return custom_local_path
    if source_preference == "local":
        from ..config import settings  # lazy to avoid circular import if config ever imports core
        return str(settings.local_data_base_path)
    return None


def sanitize_path_segment(value: str) -> str:
    """Make a safe path segment for filesystem storage."""
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", value.strip())
    return safe or "unknown"


def mission_storage_dir_name(mission_id: str, suffix: str) -> str:
    """Build a mission-specific folder name with a suffix."""
    safe_mission_id = sanitize_path_segment(mission_id)
    safe_suffix = sanitize_path_segment(suffix)
    return f"{safe_mission_id}_{safe_suffix}" if safe_suffix else safe_mission_id


_DEPLOYMENT_MISSION_CODE_PATTERN = re.compile(r"\b[mM](\d+)\b")
_MISSION_NOTE_PREFIX_PATTERN = re.compile(
    r"^\s*(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})(?:\s*UTC)?\s*:\s*",
    re.IGNORECASE,
)


def find_mission_overview_for_mission(session: Any, mission_id: str) -> Optional[Any]:
    """
    Resolve MissionOverview for a dashboard or sync mission id.

    Tries exact id, deployment code (e.g. m219), and folder-style ids that embed the code
    (e.g. m219-SV3-1121 when syncing deployment m219).
    """
    from sqlmodel import select

    from .models import MissionOverview

    if not mission_id or not str(mission_id).strip():
        return None

    trimmed = mission_id.strip()
    mission_base = deployment_mission_code_from_mission_id(trimmed)

    for key in (trimmed, mission_base):
        if not key:
            continue
        overview = session.get(MissionOverview, key)
        if overview:
            return overview

    if not mission_base:
        return None

    pattern_candidates = session.exec(
        select(MissionOverview).where(
            (MissionOverview.mission_id == mission_base)
            | (MissionOverview.mission_id.like(f"{mission_base}-%"))  # type: ignore[attr-defined]
            | (MissionOverview.mission_id.like(f"%-{mission_base}"))  # type: ignore[attr-defined]
        )
    ).all()

    exact_base = [o for o in pattern_candidates if o.mission_id == mission_base]
    if len(exact_base) == 1:
        return exact_base[0]

    code_matches = [
        o
        for o in pattern_candidates
        if deployment_mission_code_from_mission_id(o.mission_id) == mission_base
    ]
    if len(code_matches) == 1:
        return code_matches[0]

    return None


def deployment_mission_code_from_mission_id(mission_id: str) -> str:
    """
    Extract the Sensor Tracker deployment mission code (e.g. ``m219``) from a folder-style mission id.

    Legacy ids use a trailing segment (``1121-m171`` → ``m171``). New platform deployment ids put the
    code first (``m219-SV3-1121`` → ``m219``). If no ``m`` + digits token exists, falls back to the
    substring after the last hyphen, or the whole string when there is no hyphen.
    """
    if not mission_id or not mission_id.strip():
        return mission_id
    trimmed = mission_id.strip()
    match = _DEPLOYMENT_MISSION_CODE_PATTERN.search(trimmed)
    if match:
        return f"m{match.group(1)}"
    if "-" in trimmed:
        return trimmed.split("-")[-1]
    return trimmed


_SLOCUM_DATASET_ID_PATTERN = re.compile(
    r"^(?P<glider>[A-Za-z0-9]+)_(?P<start>\d{8})_(?P<num>\d+)(?:_(?P<mode>realtime|delayed))?$"
)


def parse_slocum_dataset_id(dataset_id: str) -> Optional[Dict[str, Any]]:
    """
    Parse a Slocum ERDDAP dataset id (e.g. ``polly_20260519_222_delayed``).

    Returns glider_name, start_date (date), deployment_number (int), and optional mode
    (``realtime`` | ``delayed``), or None when the id does not match.
    """
    if not dataset_id or not str(dataset_id).strip():
        return None
    match = _SLOCUM_DATASET_ID_PATTERN.match(str(dataset_id).strip())
    if not match:
        return None
    try:
        start_date = datetime.strptime(match.group("start"), "%Y%m%d").date()
    except ValueError:
        return None
    return {
        "glider_name": match.group("glider"),
        "start_date": start_date,
        "deployment_number": int(match.group("num")),
        "mode": match.group("mode"),
    }


def slocum_mission_key(dataset_id: str) -> str:
    """
    Suffix-agnostic mission identity shared by realtime and delayed datasets.

    ``sable_20260621_224_realtime`` and ``sable_20260621_224_delayed`` both map to
    ``sable_20260621_224``. Unparseable ids return the trimmed input unchanged.
    """
    if not dataset_id or not str(dataset_id).strip():
        return ""
    trimmed = str(dataset_id).strip()
    parsed = parse_slocum_dataset_id(trimmed)
    if not parsed:
        return trimmed
    start_date = parsed["start_date"]
    return f"{parsed['glider_name']}_{start_date.strftime('%Y%m%d')}_{parsed['deployment_number']}"


def mission_ids_for_offload_parser_trace_matching(
    mission_id: str,
    *,
    sensor_tracker_folder_mission_id: Optional[str] = None,
) -> tuple[str, ...]:
    """Mission id strings used to match WG-VM4 ``parser_run_id`` / ``parser_session_ref`` (``id:…`` prefix).

    The VM4 parser stores ``{mission_id passed to the parser}:{timestamp}``. Reports may be
    requested with a folder-style id (``m219-SV3-1121``) or deployment code (``m219``); logs may
    use either form. When ``sensor_tracker_folder_mission_id`` is set (typically the deployment
    row's ``mission_id``), it is included so short-code report requests still match folder-prefixed
    parser rows.
    """
    mid = (mission_id or "").strip()
    if not mid:
        return ()
    base = deployment_mission_code_from_mission_id(mid)
    out: List[str] = []
    for candidate in (mid, base):
        if candidate and candidate not in out:
            out.append(candidate)
    folder = (sensor_tracker_folder_mission_id or "").strip()
    if folder and folder not in out:
        out.append(folder)
    return tuple(out)


def parse_mission_note_datetime_prefix(note_content: Optional[str]) -> Optional[datetime]:
    """
    Parse mission note prefix timestamp in format:
    YYYY-MM-DD HH:MM : comment text

    Returns timezone-aware UTC datetime when valid, otherwise None.
    """
    if not note_content:
        return None
    match = _MISSION_NOTE_PREFIX_PATTERN.match(note_content)
    if not match:
        return None
    date_part, time_part = match.groups()
    try:
        parsed = datetime.strptime(f"{date_part} {time_part}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc)


def strip_mission_note_datetime_prefix(note_content: Optional[str]) -> str:
    """Remove the datetime prefix from a mission note if present."""
    if not note_content:
        return ""
    return _MISSION_NOTE_PREFIX_PATTERN.sub("", note_content, count=1).strip()


def _ensure_utc(ts: pd.Timestamp) -> pd.Timestamp:
    """
    Helper function to ensure a timestamp is UTC-aware.
    
    Args:
        ts: pandas Timestamp (may be naive or in another timezone)
        
    Returns:
        UTC-aware pandas Timestamp
    """
    if pd.isna(ts):
        return ts
    if ts.tz is None:
        return ts.tz_localize('UTC')
    elif str(ts.tz) != 'UTC':
        return ts.tz_convert('UTC')
    return ts


def parse_timestamp_robust(
    timestamp_value: Union[str, datetime, pd.Timestamp, None],
    errors: str = 'coerce'
) -> Optional[pd.Timestamp]:
    """
    Robustly parse a timestamp value that can be in multiple formats.
    
    Handles:
    - ISO 8601 formats: '2025-10-27T14:13:15Z', '2025-10-27T14:13:15+00:00', etc.
    - 12hr AM/PM format: '10/27/2025 2:13:14PM' (UTC)
    - Already parsed datetime/Timestamp objects
    
    Args:
        timestamp_value: The timestamp value to parse (can be string, datetime, Timestamp, or None)
        errors: How to handle errors ('coerce' returns NaT, 'raise' raises exception)
    
    Returns:
        pd.Timestamp with UTC timezone, or NaT if parsing fails and errors='coerce'
    """
    if timestamp_value is None or pd.isna(timestamp_value):
        return pd.NaT if errors == 'coerce' else None
    
    # If already a datetime/Timestamp, ensure UTC
    if isinstance(timestamp_value, (datetime, pd.Timestamp)):
        return _ensure_utc(pd.Timestamp(timestamp_value))
    
    if not isinstance(timestamp_value, str):
        # Try to convert to string first
        timestamp_value = str(timestamp_value)
    
    if not timestamp_value or timestamp_value.strip() == '':
        return pd.NaT if errors == 'coerce' else None
    
    timestamp_value = timestamp_value.strip()
    
    # Try pandas ISO8601 parser first (handles most ISO 8601 formats reliably)
    # This covers: 2025-10-27T14:13:15Z, 2025-10-27T14:13:15+00:00, etc.
    try:
        ts = pd.to_datetime(timestamp_value, format='ISO8601', errors='raise', utc=True)
        if isinstance(ts, pd.Timestamp):
            return _ensure_utc(ts)
        return ts
    except (ValueError, TypeError):
        pass
    
    # Try simple ISO-like formats with strptime (for naive timestamps)
    iso_formats = [
        '%Y-%m-%dT%H:%M:%S',            # 2025-10-27T14:13:15 (naive, will assume UTC)
        '%Y-%m-%d %H:%M:%S',            # 2025-10-27 14:13:15 (naive, will assume UTC)
        '%Y-%m-%d %H:%M:%S.%f',         # 2025-10-27 14:13:15.123456 (naive, will assume UTC)
    ]
    
    for fmt in iso_formats:
        try:
            ts = datetime.strptime(timestamp_value, fmt)
            # Naive timestamps are assumed UTC (all our data sources are UTC)
            ts = ts.replace(tzinfo=timezone.utc)
            return pd.Timestamp(ts)
        except (ValueError, TypeError):
            continue
    
    # Try 12hr AM/PM format: '10/27/2025 2:13:14PM' (new format from upstream)
    # Handle various AM/PM format variations
    am_pm_formats = [
        '%m/%d/%Y %I:%M:%S%p',          # 10/27/2025 2:13:14PM
        '%m/%d/%Y %I:%M:%S %p',         # 10/27/2025 2:13:14 PM (with space)
        '%m/%d/%Y %I:%M%p',             # 10/27/2025 2:13PM (without seconds)
        '%m/%d/%Y %I:%M %p',            # 10/27/2025 2:13 PM
        '%m-%d-%Y %I:%M:%S%p',          # 10-27-2025 2:13:14PM (with dashes)
        '%m-%d-%Y %I:%M:%S %p',         # 10-27-2025 2:13:14 PM
        # Note: %-I and %#I don't work in Python strptime, handled by regex below
    ]
    
    for fmt in am_pm_formats:
        try:
            # Try parsing with the format
            ts = datetime.strptime(timestamp_value, fmt)
            # AM/PM format is always UTC per user specification
            ts = ts.replace(tzinfo=timezone.utc)
            return pd.Timestamp(ts)
        except (ValueError, TypeError):
            continue
    
    # Special handling for single-digit hours (e.g., "10/27/2025 2:13:14PM" vs "10/27/2025 02:13:14PM")
    # Python's strptime requires leading zeros, so we use regex for single-digit hours
    am_pm_pattern = r'(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}):(\d{2}):(\d{2})\s*(AM|PM)'
    match = re.match(am_pm_pattern, timestamp_value, re.IGNORECASE)
    if match:
        try:
            month, day, year, hour, minute, second, am_pm = match.groups()
            month, day, year = int(month), int(day), int(year)
            hour, minute, second = int(hour), int(minute), int(second)
            
            # Convert to 24-hour format
            if am_pm.upper() == 'PM' and hour != 12:
                hour += 12
            elif am_pm.upper() == 'AM' and hour == 12:
                hour = 0
            
            ts = datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)
            return pd.Timestamp(ts)
        except (ValueError, TypeError):
            pass
    
    # Fallback to pandas' dateutil parser (last resort)
    try:
        ts = pd.to_datetime(timestamp_value, errors=errors, utc=True)
        if isinstance(ts, pd.Timestamp):
            return _ensure_utc(ts)
        return ts
    except Exception:
        if errors == 'coerce':
            return pd.NaT
        raise


def parse_timestamp_column(
    series: pd.Series,
    errors: str = 'coerce',
    utc: bool = True
) -> pd.Series:
    """
    Robustly parse a pandas Series of timestamp values that may contain mixed formats.
    
    This function handles datasets with mixed timestamp formats by parsing each value
    individually. Useful when upstream data sources have inconsistent timestamp formats.
    
    Args:
        series: pandas Series containing timestamp values (strings, datetimes, or mixed)
        errors: How to handle errors ('coerce' returns NaT, 'raise' raises exception)
        utc: Ensure all timestamps are UTC-aware (default True)
    
    Returns:
        pd.Series of pd.Timestamp objects, all UTC-aware if utc=True
    """
    if series.empty:
        return series
    
    # Check if already datetime
    if pd.api.types.is_datetime64_any_dtype(series):
        # Ensure UTC if requested - use vectorized operations
        if utc:
            # Vectorized UTC conversion for already-datetime series
            if series.dt.tz is None:
                return series.dt.tz_localize('UTC')
            else:
                return series.dt.tz_convert('UTC')
        return series
    
    # Try to parse all at once first (faster if format is consistent)
    # Strategy: Try bulk parsing with different methods before falling back to row-by-row
    
    # 1. Try explicit mixed-format parsing first (pandas >= 2.0).
    # This avoids repeated "could not infer format" warnings on mixed feeds.
    try:
        parsed = pd.to_datetime(series, format='mixed', errors='coerce', utc=True)
        success_rate = parsed.notna().sum() / len(series) if len(series) > 0 else 0
        
        # If most succeed, use bulk result and only fix failures individually
        if success_rate >= 0.95:  # 95% threshold - tolerate some failures
            # Only parse the failed ones individually (much faster than all row-by-row)
            failed_mask = parsed.isna() & series.notna()  # Only process actual failures, not NaNs
            if failed_mask.any():
                failed_indices = series[failed_mask].index
                for idx in failed_indices:
                    try:
                        parsed[idx] = parse_timestamp_robust(series[idx], errors=errors)
                    except Exception:
                        if errors == 'coerce':
                            parsed[idx] = pd.NaT
            return parsed
    except (TypeError, ValueError):
        # Fallback for pandas versions that do not support format='mixed'
        pass
    except Exception:
        pass

    # 1b. Flexible parser fallback (dateutil-backed).
    # Suppress noisy warning because per-element fallback is acceptable here.
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="Could not infer format, so each element will be parsed individually.*",
                category=UserWarning,
            )
            parsed = pd.to_datetime(series, errors='coerce', utc=True)
        success_rate = parsed.notna().sum() / len(series) if len(series) > 0 else 0
        
        # If most succeed, use bulk result and only fix failures individually
        if success_rate >= 0.95:  # 95% threshold - tolerate some failures
            # Only parse the failed ones individually (much faster than all row-by-row)
            failed_mask = parsed.isna() & series.notna()  # Only process actual failures, not NaNs
            if failed_mask.any():
                failed_indices = series[failed_mask].index
                for idx in failed_indices:
                    try:
                        parsed[idx] = parse_timestamp_robust(series[idx], errors=errors)
                    except Exception:
                        if errors == 'coerce':
                            parsed[idx] = pd.NaT
            return parsed
    except Exception:
        pass
    
    # 2. Try ISO8601 format specifically if flexible parser had low success rate
    # (This can be faster for purely ISO8601 data)
    try:
        parsed = pd.to_datetime(series, format='ISO8601', errors='coerce', utc=True)
        success_rate = parsed.notna().sum() / len(series) if len(series) > 0 else 0
        if success_rate >= 0.95:
            # Handle the few failures individually
            failed_mask = parsed.isna() & series.notna()
            if failed_mask.any():
                failed_indices = series[failed_mask].index
                for idx in failed_indices:
                    try:
                        parsed[idx] = parse_timestamp_robust(series[idx], errors=errors)
                    except Exception:
                        if errors == 'coerce':
                            parsed[idx] = pd.NaT
            return parsed
    except Exception:
        pass
    
    # 4. Last resort: parse row by row (slow, but handles truly mixed formats)
    # Only do this if bulk parsing failed significantly
    def parse_single(ts_value):
        try:
            return parse_timestamp_robust(ts_value, errors=errors)
        except Exception:
            if errors == 'coerce':
                return pd.NaT
            raise
    
    result = series.apply(parse_single)
    total_values = len(series)
    failed_values = int(result.isna().sum()) if total_values > 0 else 0
    if total_values > 0 and failed_values > 0:
        logger.info(
            "Timestamp parse fallback had failures: failed=%s total=%s success_rate=%.4f",
            failed_values,
            total_values,
            (total_values - failed_values) / total_values,
        )
    
    return result


def get_df_latest_update_info(
    df: Optional[pd.DataFrame], timestamp_col: str = "Timestamp"
) -> dict:
    """Helper to get latest timestamp and time_ago string from a DataFrame. Returns safe defaults and logs errors if data is missing or malformed."""
    try:
        if df is None or df.empty or timestamp_col not in df.columns:
            return {"latest_timestamp_str": "N/A", "time_ago_str": "N/A"}

        # Ensure timestamp_col is datetime and handle potential errors # noqa
        try:
            df_copy = df.copy()  # Work on a copy to avoid SettingWithCopyWarning
            df_copy[timestamp_col] = parse_timestamp_column(
                df_copy[timestamp_col], errors="coerce", utc=True
            )
            df_copy = df_copy.dropna(subset=[timestamp_col])
        except Exception as e:
            logger.error(
                f"Error processing timestamp column '{timestamp_col}': {e}"
            )
            return {"latest_timestamp_str": "N/A", "time_ago_str": "N/A"}

        if df_copy.empty:
            return {"latest_timestamp_str": "N/A", "time_ago_str": "N/A"}

        latest_timestamp = df_copy[timestamp_col].max()
        latest_timestamp_str = "N/A"
        time_ago_str = "N/A"
        if pd.notna(latest_timestamp):
            latest_timestamp_str = latest_timestamp.strftime(
                "%Y-%m-%d %H:%M:%S UTC"
            )
            # Import here to avoid circular import (summaries lives under core.data)
            from .data.summaries import time_ago
            time_ago_str = time_ago(latest_timestamp)
        return {
            "latest_timestamp_str": latest_timestamp_str,
            "time_ago_str": time_ago_str,
        }
    except Exception as e:
        logger.error(f"Error in get_df_latest_update_info: {e}")
        return {"latest_timestamp_str": "N/A", "time_ago_str": "N/A"}

def select_target_spectrum(
    spectral_records: List[Dict], requested_timestamp: Optional[datetime] = None
) -> Optional[Dict]:
    """
    Selects a spectral record from a list.
    If requested_timestamp is provided, finds the closest one. Otherwise, returns the latest.
    """ # noqa

    if not spectral_records:
        return None

    if requested_timestamp:
        # Ensure requested_timestamp is UTC for comparison
        # Use pd.Timestamp.now(tz="UTC").tzinfo for a reliable UTC timezone object
        utc_tz = pd.Timestamp.now(tz="UTC").tzinfo
        target_timestamp_utc = (
            requested_timestamp.astimezone(utc_tz) # noqa
            if requested_timestamp.tzinfo is None # noqa
            or requested_timestamp.tzinfo.utcoffset(requested_timestamp) is None
            else requested_timestamp # noqa
        )

        closest_record = min(
            spectral_records,
            key=lambda rec: abs(
                rec.get("timestamp", pd.Timestamp.min.tz_localize("UTC"))
                - target_timestamp_utc
            ),
        )
        # Optional: Add a threshold to ensure the "closest" isn't too far off
        if abs(
            closest_record.get("timestamp", pd.Timestamp.min.tz_localize("UTC"))
            - target_timestamp_utc
        ) < timedelta(
            hours=1
        ):  # Example threshold
            return closest_record
        else: # noqa
            logger.warning(
                f"Closest spectrum for timestamp {requested_timestamp} is too "
                f"far ({closest_record.get('timestamp')}). Returning latest."
            )
            return max(
                spectral_records,
                key=lambda rec: rec.get( # noqa
                    "timestamp", pd.Timestamp.min.tz_localize("UTC") # noqa
                ), # noqa
            )
    else:
        # Default to the latest spectral record
        return max(
            spectral_records,
            key=lambda rec: rec.get("timestamp", pd.Timestamp.min.tz_localize("UTC")),
        )
