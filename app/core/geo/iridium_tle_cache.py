"""CelesTrak Iridium-E TLE disk cache for the home-page satellite overlay.

Respects CelesTrak usage policy: at most one upstream contact per TTL (default 2h).

Hardening:
- Freshness and rate-limit state live on disk (survive process/app reboots).
- In-process single-flight lock plus a persistent upstream gate file so workers
  do not stampede CelesTrak after a restart.
- Prefer a single FORMAT=JSON request; TLE is fallback only when JSON fails and
  the rate-limit slot for this cycle has already been claimed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx

from ...config import settings
from ..infra.feature_toggles import is_feature_enabled

logger = logging.getLogger(__name__)

CELESTRAK_IRIDIUM_E_TLE_URL = (
    "https://celestrak.org/NORAD/elements/supplemental/sup-gp.php"
    "?SOURCE=Iridium-E&FORMAT=TLE"
)
CELESTRAK_IRIDIUM_E_JSON_URL = (
    "https://celestrak.org/NORAD/elements/supplemental/sup-gp.php"
    "?SOURCE=Iridium-E&FORMAT=JSON"
)
SOURCE_LABEL = "Iridium-E"
_HTTP_HEADERS = {
    "User-Agent": "WaveGliderBuddySystem/1.0 (iridium-map-overlay; local cache)",
    "Accept": "application/json, text/plain, */*",
}

_stats: dict[str, Any] = {
    "cache_hits": 0,
    "cache_misses": 0,
    "upstream_fetches": 0,
    "upstream_blocked_by_rate_limit": 0,
    "last_fetch_at": None,
    "last_fetch_ok": None,
    "last_error": None,
    "last_prefetch_at": None,
    "last_prefetch_summary": None,
    "last_cleanup_at": None,
    "last_cleanup_summary": None,
    "satellite_count": 0,
}
_fetch_lock = asyncio.Lock()


def _cache_dir() -> Path:
    return Path(settings.iridium_tle_cache_dir)


def _tles_path() -> Path:
    return _cache_dir() / "tles.json"


def _rate_limit_path() -> Path:
    """Persistent gate: last CelesTrak contact time (survives reboots)."""
    return _cache_dir() / "upstream_rate_limit.json"


def _ensure_cache_dir() -> None:
    _cache_dir().mkdir(parents=True, exist_ok=True)


def _ttl_seconds() -> int:
    return max(60, int(getattr(settings, "iridium_tle_cache_ttl_seconds", 7200) or 7200))


def _cleanup_max_age_days() -> int:
    return max(1, int(getattr(settings, "iridium_tle_cleanup_max_age_days", 7) or 7))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat().replace("+00:00", "Z")


def _parse_iso_utc(value: str) -> Optional[datetime]:
    try:
        normalized = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _age_seconds_from_iso(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    parsed = _parse_iso_utc(value)
    if parsed is None:
        return None
    return (_utc_now() - parsed).total_seconds()


def _file_mtime_age_seconds(path: Path) -> Optional[float]:
    try:
        if not path.is_file():
            return None
        return time.time() - path.stat().st_mtime
    except OSError:
        return None


def parse_tle_text(tle_text: str) -> list[dict[str, Any]]:
    """Parse CelesTrak 3LE text into satellite dicts with line1/line2."""
    lines = [ln.rstrip() for ln in tle_text.splitlines() if ln.strip()]
    satellites: list[dict[str, Any]] = []
    i = 0
    while i + 2 < len(lines):
        name_line = lines[i].strip()
        line1 = lines[i + 1].strip()
        line2 = lines[i + 2].strip()
        if not (line1.startswith("1 ") and line2.startswith("2 ")):
            i += 1
            continue
        norad_id: Optional[int] = None
        try:
            norad_id = int(line1[2:7])
        except ValueError:
            try:
                norad_id = int(line2[2:7])
            except ValueError:
                norad_id = None
        satellites.append(
            {
                "norad_id": norad_id,
                "name": name_line,
                "line1": line1,
                "line2": line2,
            }
        )
        i += 3
    return satellites


def _tle_checksum(line_without_checksum: str) -> int:
    total = 0
    for char in line_without_checksum:
        if char.isdigit():
            total += int(char)
        elif char == "-":
            total += 1
    return total % 10


def _format_exponent_field(value: float) -> str:
    """Format TLE BSTAR / n-ddot field (8 chars, e.g. ' 39240-3')."""
    if value == 0.0:
        return " 00000-0"
    sign = "-" if value < 0 else " "
    abs_val = abs(value)
    exponent = int(math.floor(math.log10(abs_val))) + 1
    mantissa = abs_val / (10 ** exponent)
    mantissa_int = int(round(mantissa * 100_000))
    if mantissa_int >= 100_000:
        mantissa_int = 10000
        exponent += 1
    exp_sign = "+" if exponent >= 0 else "-"
    return f"{sign}{mantissa_int:05d}{exp_sign}{abs(exponent)}"


def _format_n_dot(value: float) -> str:
    """Classic TLE mean-motion-dot field (10 chars, leading decimal)."""
    if value >= 0:
        text = f"{value:10.8f}"
        if text.startswith("0."):
            return " " + text[1:]
        return text
    text = f"{value:10.8f}"
    if text.startswith("-0."):
        return "-" + text[2:]
    return text


def _epoch_to_tle_year_day(epoch_str: str) -> tuple[int, float]:
    parsed = _parse_iso_utc(epoch_str)
    if parsed is None:
        raise ValueError(f"invalid epoch: {epoch_str}")
    year = parsed.year % 100
    day_of_year = (
        parsed.timetuple().tm_yday
        + parsed.hour / 24.0
        + parsed.minute / 1440.0
        + parsed.second / 86400.0
        + parsed.microsecond / 86400.0 / 1_000_000.0
    )
    return year, day_of_year


def omm_record_to_tle(record: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Build a 2-line TLE pair from a CelesTrak OMM JSON object."""
    try:
        norad_id = int(record["NORAD_CAT_ID"])
        name = str(record.get("OBJECT_NAME") or f"NORAD {norad_id}").strip()
        epoch_year, epoch_day = _epoch_to_tle_year_day(record["EPOCH"])
        mean_motion_dot = float(record.get("MEAN_MOTION_DOT") or 0.0)
        mean_motion_ddot = float(record.get("MEAN_MOTION_DDOT") or 0.0)
        bstar = float(record.get("BSTAR") or 0.0)
        inclination = float(record["INCLINATION"])
        raan = float(record["RA_OF_ASC_NODE"])
        ecc = float(record["ECCENTRICITY"])
        argp = float(record.get("ARG_OF_PERICENTER") or 0.0)
        mean_anom = float(record["MEAN_ANOMALY"])
        mean_motion = float(record["MEAN_MOTION"])
        rev = int(record.get("REV_AT_EPOCH") or 0)
        elset = int(record.get("ELEMENT_SET_NO") or 0) % 1000
        classification = str(record.get("CLASSIFICATION_TYPE") or "U")[:1] or "U"
        object_id = str(record.get("OBJECT_ID") or "").replace("-", "")
        if len(object_id) >= 7 and object_id[:4].isdigit():
            intl_des = f"{object_id[2:4]}{object_id[4:]}"[:8]
        else:
            intl_des = object_id[:8]
    except (KeyError, TypeError, ValueError):
        return None

    n_dot_field = _format_n_dot(mean_motion_dot)
    n_ddot_field = _format_exponent_field(mean_motion_ddot)
    bstar_field = _format_exponent_field(bstar)
    ecc_field = f"{ecc:.7f}".split(".")[1][:7]

    line1_body = (
        f"1 {norad_id:05d}{classification} {intl_des:<8} "
        f"{epoch_year:02d}{epoch_day:012.8f} "
        f"{n_dot_field} {n_ddot_field} {bstar_field} 0 {elset:3d}"
    )
    line2_body = (
        f"2 {norad_id:05d} {inclination:8.4f} {raan:8.4f} {ecc_field} "
        f"{argp:8.4f} {mean_anom:8.4f} {mean_motion:11.8f}{rev:5d}"
    )
    line1_body = line1_body[:68].ljust(68)
    line2_body = line2_body[:68].ljust(68)
    return {
        "norad_id": norad_id,
        "name": name,
        "line1": line1_body + str(_tle_checksum(line1_body)),
        "line2": line2_body + str(_tle_checksum(line2_body)),
    }


def parse_omm_json(payload: Any) -> list[dict[str, Any]]:
    """Convert CelesTrak OMM JSON list into TLE satellite dicts."""
    if not isinstance(payload, list):
        return []
    satellites: list[dict[str, Any]] = []
    for record in payload:
        if not isinstance(record, dict):
            continue
        sat = omm_record_to_tle(record)
        if sat:
            satellites.append(sat)
    return satellites


def _read_json_file(path: Path) -> Optional[dict[str, Any]]:
    if not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read %s: %s", path, exc)
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    _ensure_cache_dir()
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    tmp_path.replace(path)


def _read_cached_payload() -> Optional[dict[str, Any]]:
    payload = _read_json_file(_tles_path())
    if payload is None or "satellites" not in payload:
        return None
    return payload


def _read_rate_limit() -> dict[str, Any]:
    return _read_json_file(_rate_limit_path()) or {}


def _cache_age_seconds(payload: Optional[dict[str, Any]] = None) -> Optional[float]:
    """Age of TLE cache using payload fetched_at, falling back to file mtime.

    Both survive application reboots; fetched_at is preferred when present.
    """
    payload = payload if payload is not None else _read_cached_payload()
    ages: list[float] = []
    if payload:
        fetched_age = _age_seconds_from_iso(payload.get("fetched_at"))
        if fetched_age is not None:
            ages.append(fetched_age)
    mtime_age = _file_mtime_age_seconds(_tles_path())
    if mtime_age is not None:
        ages.append(mtime_age)
    if not ages:
        return None
    # Prefer metadata age when available; otherwise mtime-only.
    if payload and _age_seconds_from_iso(payload.get("fetched_at")) is not None:
        return _age_seconds_from_iso(payload.get("fetched_at"))
    return min(ages)


def _is_fresh(payload: Optional[dict[str, Any]] = None) -> bool:
    age = _cache_age_seconds(payload)
    if age is None:
        return False
    return age < _ttl_seconds()


def _upstream_gate_age_seconds() -> Optional[float]:
    """Seconds since last claimed/attempted CelesTrak contact (disk-backed)."""
    gate = _read_rate_limit()
    age = _age_seconds_from_iso(gate.get("last_attempt_at"))
    if age is not None:
        return age
    return _file_mtime_age_seconds(_rate_limit_path())


def _upstream_allowed() -> bool:
    """True if enough time has passed since the last upstream attempt."""
    age = _upstream_gate_age_seconds()
    if age is None:
        return True
    return age >= _ttl_seconds()


def _claim_upstream_slot() -> bool:
    """Claim the CelesTrak request slot for this TTL window (disk-backed).

    Writes the rate-limit marker *before* HTTP so concurrent workers / restarts
    within the TTL see a recent last_attempt_at and skip. A short claim_id
    re-read reduces double-fetch races across processes.
    """
    if not _upstream_allowed():
        return False

    claim_id = str(uuid.uuid4())
    now_iso = _utc_now_iso()
    existing = _read_rate_limit()
    age = _age_seconds_from_iso(existing.get("last_attempt_at"))
    if age is not None and age < _ttl_seconds():
        return False
    _atomic_write_json(
        _rate_limit_path(),
        {
            **existing,
            "last_attempt_at": now_iso,
            "claim_id": claim_id,
            "ttl_seconds": _ttl_seconds(),
            "claimed": True,
        },
    )
    # If another worker overwrote our claim in the same instant, back off.
    gate = _read_rate_limit()
    if gate.get("claim_id") != claim_id:
        return False
    return True


def _record_upstream_result(*, ok: bool, error: Optional[str] = None, source_url: Optional[str] = None) -> None:
    existing = _read_rate_limit()
    now_iso = _utc_now_iso()
    payload = {
        **existing,
        "last_attempt_at": existing.get("last_attempt_at") or now_iso,
        "last_result_at": now_iso,
        "last_ok": ok,
        "last_error": error,
        "last_source_url": source_url,
        "ttl_seconds": _ttl_seconds(),
    }
    if ok:
        payload["last_success_at"] = now_iso
    _atomic_write_json(_rate_limit_path(), payload)


def _write_payload(payload: dict[str, Any]) -> None:
    _atomic_write_json(_tles_path(), payload)


async def _fetch_upstream_tles() -> dict[str, Any]:
    """Perform at most one primary JSON request (TLE only if JSON fails)."""
    _stats["upstream_fetches"] += 1
    satellites: list[dict[str, Any]] = []
    source_url = CELESTRAK_IRIDIUM_E_JSON_URL
    last_error: Optional[Exception] = None

    async with httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        headers=_HTTP_HEADERS,
    ) as client:
        try:
            response = await client.get(CELESTRAK_IRIDIUM_E_JSON_URL)
            response.raise_for_status()
            satellites = parse_omm_json(response.json())
            source_url = CELESTRAK_IRIDIUM_E_JSON_URL
        except Exception as exc:
            last_error = exc
            logger.warning("Iridium-E JSON fetch failed (%s); trying TLE once", exc)
            try:
                response = await client.get(CELESTRAK_IRIDIUM_E_TLE_URL)
                response.raise_for_status()
                satellites = parse_tle_text(response.text)
                source_url = CELESTRAK_IRIDIUM_E_TLE_URL
            except Exception as tle_exc:
                _record_upstream_result(ok=False, error=str(tle_exc), source_url=CELESTRAK_IRIDIUM_E_TLE_URL)
                raise

    if not satellites:
        err = ValueError(
            f"CelesTrak Iridium-E returned no satellites"
            + (f" (JSON failed: {last_error})" if last_error else "")
        )
        _record_upstream_result(ok=False, error=str(err), source_url=source_url)
        raise err

    payload = {
        "fetched_at": _utc_now_iso(),
        "source": SOURCE_LABEL,
        "source_url": source_url,
        "attribution": "CelesTrak / Iridium ephemeris (SupGP Iridium-E)",
        "satellites": satellites,
    }
    _write_payload(payload)
    _record_upstream_result(ok=True, source_url=source_url)
    _stats["last_fetch_at"] = payload["fetched_at"]
    _stats["last_fetch_ok"] = True
    _stats["last_error"] = None
    _stats["satellite_count"] = len(satellites)
    logger.info(
        "Fetched Iridium-E elements from CelesTrak (%s satellites via %s)",
        len(satellites),
        source_url,
    )
    return payload


def _stale_payload_response(
    cached: dict[str, Any],
    *,
    reason: str,
    upstream_error: Optional[str] = None,
) -> dict[str, Any]:
    result = {
        **cached,
        "cache_hit": True,
        "stale": True,
        "age_seconds": _cache_age_seconds(cached),
        "rate_limit_reason": reason,
    }
    if upstream_error:
        result["upstream_error"] = upstream_error
    return result


async def get_iridium_tles(*, force_refresh: bool = False) -> dict[str, Any]:
    """Return Iridium TLEs, refreshing only when disk cache is stale and rate-limit allows.

    Freshness and the upstream gate are disk-backed (survive app reboots).
    ``force_refresh`` is accepted for callers/prefetch clarity but never bypasses
    a fresh disk cache or the CelesTrak TTL gate.
    """
    del force_refresh  # never bypass disk freshness / rate limit
    cached = _read_cached_payload()
    if cached is not None and _is_fresh(cached):
        _stats["cache_hits"] += 1
        _stats["satellite_count"] = len(cached.get("satellites") or [])
        return {
            **cached,
            "cache_hit": True,
            "age_seconds": _cache_age_seconds(cached),
        }

    async with _fetch_lock:
        cached = _read_cached_payload()
        if cached is not None and _is_fresh(cached):
            _stats["cache_hits"] += 1
            _stats["satellite_count"] = len(cached.get("satellites") or [])
            return {
                **cached,
                "cache_hit": True,
                "age_seconds": _cache_age_seconds(cached),
            }

        if not _claim_upstream_slot():
            _stats["upstream_blocked_by_rate_limit"] += 1
            _stats["cache_hits"] += 1
            if cached is not None:
                logger.info(
                    "Iridium TLE refresh skipped (CelesTrak rate limit / TTL); serving disk cache age=%.0fs",
                    _cache_age_seconds(cached) or -1,
                )
                return _stale_payload_response(cached, reason="upstream_ttl_gate")
            raise RuntimeError(
                "Iridium TLE cache empty and CelesTrak upstream is rate-limited for this TTL window"
            )

        _stats["cache_misses"] += 1
        try:
            payload = await _fetch_upstream_tles()
        except Exception as exc:
            _stats["last_fetch_ok"] = False
            _stats["last_error"] = str(exc)
            logger.error("Iridium TLE upstream fetch failed: %s", exc, exc_info=True)
            if cached is not None:
                logger.warning("Serving stale Iridium TLE cache after upstream failure")
                return _stale_payload_response(
                    cached, reason="upstream_error", upstream_error=str(exc)
                )
            raise

        return {
            **payload,
            "cache_hit": False,
            "age_seconds": 0.0,
        }


async def prefetch_iridium_tles() -> dict[str, Any]:
    """Leader job: refresh TLEs when stale if the feature + prefetch flag allow."""
    if not is_feature_enabled("iridium_map_layer"):
        summary = {"skipped": True, "reason": "feature_disabled"}
        _stats["last_prefetch_at"] = _utc_now_iso()
        _stats["last_prefetch_summary"] = summary
        logger.info("Iridium TLE prefetch skipped: iridium_map_layer disabled")
        return summary

    if not bool(getattr(settings, "iridium_tle_prefetch_enabled", True)):
        summary = {"skipped": True, "reason": "prefetch_disabled"}
        _stats["last_prefetch_at"] = _utc_now_iso()
        _stats["last_prefetch_summary"] = summary
        logger.info("Iridium TLE prefetch skipped: iridium_tle_prefetch_enabled=false")
        return summary

    before = _read_cached_payload()
    was_fresh = bool(before and _is_fresh(before))
    payload = await get_iridium_tles()
    summary = {
        "skipped": False,
        "was_fresh_before": was_fresh,
        "cache_hit": payload.get("cache_hit"),
        "stale": payload.get("stale", False),
        "satellite_count": len(payload.get("satellites") or []),
        "age_seconds": payload.get("age_seconds"),
        "rate_limit_reason": payload.get("rate_limit_reason"),
        "fetched_at": payload.get("fetched_at"),
    }
    _stats["last_prefetch_at"] = _utc_now_iso()
    _stats["last_prefetch_summary"] = summary
    logger.info("Iridium TLE prefetch finished: %s", summary)
    return summary


def purge_iridium_cache(*, force_all: bool = False) -> dict[str, Any]:
    """Remove Iridium cache files. force_all deletes everything; else TTL/stranded only."""
    _ensure_cache_dir()
    removed_files = 0
    freed_bytes = 0
    paths = [_tles_path(), _rate_limit_path()]
    max_age_seconds = _cleanup_max_age_days() * 86400
    feature_on = is_feature_enabled("iridium_map_layer")

    for path in paths:
        if not path.is_file():
            continue
        try:
            size = path.stat().st_size
            age = _file_mtime_age_seconds(path)
            should_remove = force_all
            if not should_remove and not feature_on:
                # Feature off: reclaim stranded cache regardless of age.
                should_remove = True
            if not should_remove and age is not None and age > max_age_seconds:
                should_remove = True
            if should_remove:
                path.unlink(missing_ok=True)
                removed_files += 1
                freed_bytes += size
        except OSError as exc:
            logger.warning("Failed to purge %s: %s", path, exc)

    # Remove empty leftover tmp files
    for tmp in _cache_dir().glob("*.tmp"):
        try:
            size = tmp.stat().st_size
            tmp.unlink(missing_ok=True)
            removed_files += 1
            freed_bytes += size
        except OSError:
            pass

    summary = {
        "removed_files": removed_files,
        "freed_bytes": freed_bytes,
        "force_all": force_all,
        "feature_enabled": feature_on,
        "max_age_days": _cleanup_max_age_days(),
    }
    return summary


async def run_iridium_tle_cleanup() -> dict[str, Any]:
    """Always-on cleanup: purge stranded/old Iridium cache (even if feature off)."""
    summary = purge_iridium_cache(force_all=False)
    _stats["last_cleanup_at"] = _utc_now_iso()
    _stats["last_cleanup_summary"] = summary
    logger.info("Iridium TLE cache cleanup complete: %s", summary)
    return summary


def get_cache_status() -> dict[str, Any]:
    """Disk/cache + rate-limit stats for debugging."""
    cached = _read_cached_payload()
    path = _tles_path()
    size_bytes = path.stat().st_size if path.is_file() else 0
    age = _cache_age_seconds(cached)
    gate = _read_rate_limit()
    gate_age = _upstream_gate_age_seconds()
    return {
        "cache_path": str(path),
        "cache_exists": path.is_file(),
        "cache_size_bytes": size_bytes,
        "ttl_seconds": _ttl_seconds(),
        "age_seconds": age,
        "mtime_age_seconds": _file_mtime_age_seconds(path),
        "is_fresh": bool(cached and _is_fresh(cached)),
        "satellite_count": len((cached or {}).get("satellites") or []),
        "fetched_at": (cached or {}).get("fetched_at"),
        "source": (cached or {}).get("source"),
        "upstream_rate_limit_path": str(_rate_limit_path()),
        "upstream_last_attempt_at": gate.get("last_attempt_at"),
        "upstream_last_success_at": gate.get("last_success_at"),
        "upstream_gate_age_seconds": gate_age,
        "upstream_allowed": _upstream_allowed(),
        "prefetch_enabled": bool(getattr(settings, "iridium_tle_prefetch_enabled", True)),
        "cleanup_max_age_days": _cleanup_max_age_days(),
        **_stats,
    }
