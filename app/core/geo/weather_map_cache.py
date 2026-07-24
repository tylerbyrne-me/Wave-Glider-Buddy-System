"""Open-Meteo weather map layer disk cache, prefetch, and fetch-through proxy."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from ...config import settings
from ..data.data_service import get_data_service
from ..data.processors import preprocess_telemetry_df
from ..geo.map_utils import get_track_bounds, prepare_track_points
from ..infra.feature_toggles import is_feature_enabled

logger = logging.getLogger(__name__)

OPEN_METEO_HOST = "map-tiles.open-meteo.com"
OPEN_METEO_BASE = f"https://{OPEN_METEO_HOST}"
LATEST_JSON_PATH = "data_spatial/dwd_icon/latest.json"
WIND_VARIABLE = "wind_u_component_10m"
FALLBACK_BOUNDS = [-78.0, 36.0, -70.0, 44.0]  # west, south, east, north

_IN_FLIGHT: dict[str, asyncio.Task] = {}
# Short-lived negative cache so Leaflet tile HEAD storms do not re-hit Open-Meteo on known 404s.
_NEGATIVE_UPSTREAM: dict[str, float] = {}
_NEGATIVE_UPSTREAM_TTL_SECONDS = 120.0
_stats = {
    "cache_hits": 0,
    "cache_misses": 0,
    "upstream_fetches": 0,
    "last_prefetch_at": None,
    "last_prefetch_summary": None,
    "last_cleanup_at": None,
    "last_cleanup_summary": None,
}


def _cache_dir() -> Path:
    return Path(settings.weather_map_cache_dir)


def _manifest_path() -> Path:
    return _cache_dir() / "manifest.json"


def _response_cache_dir() -> Path:
    return _cache_dir() / "responses"


def _ensure_cache_dirs() -> None:
    _cache_dir().mkdir(parents=True, exist_ok=True)
    _response_cache_dir().mkdir(parents=True, exist_ok=True)


def _pad_utc(value: int) -> str:
    return f"{value:02d}"


def _parse_iso_utc(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def snap_bbox(bounds: list[float], snap_deg: float) -> list[float]:
    """Snap [west, south, east, north] outward to a degree grid."""
    west, south, east, north = bounds
    snap = max(snap_deg, 1e-6)
    return [
        math.floor(west / snap) * snap,
        math.floor(south / snap) * snap,
        math.ceil(east / snap) * snap,
        math.ceil(north / snap) * snap,
    ]


def pad_bbox(bounds: list[float], pad_deg: float) -> list[float]:
    west, south, east, north = bounds
    return [west - pad_deg, south - pad_deg, east + pad_deg, north + pad_deg]


def bounds_dict_to_list(bounds: dict[str, float]) -> list[float]:
    return [bounds["west"], bounds["south"], bounds["east"], bounds["north"]]


def bbox_cache_label(bounds: list[float]) -> str:
    west, south, east, north = bounds
    return f"bbox_{west:.2f}_{south:.2f}_{east:.2f}_{north:.2f}"


def select_prefetch_timesteps(
    valid_times: list[str],
    *,
    horizon_days: int = 7,
    step_hours: int = 3,
) -> list[tuple[int, str]]:
    """Match client buildWindTimeSteps 3-hourly selection for prefetch."""
    horizon_ms = horizon_days * 24 * 60 * 60 * 1000
    now_ms = time.time() * 1000
    selected: list[tuple[int, str]] = []
    for index, valid_time in enumerate(valid_times):
        if index == 0:
            continue
        try:
            valid_ms = _parse_iso_utc(valid_time).timestamp() * 1000
        except ValueError:
            continue
        if valid_ms - now_ms > horizon_ms:
            continue
        if valid_ms < now_ms - 60 * 60 * 1000:
            continue
        if index % step_hours != 0:
            continue
        selected.append((index, valid_time))
    return selected


def resolve_om_relative_path(reference_time: str, valid_time: str) -> str:
    """Return data_spatial/dwd_icon/... path for a timestep (no host/query)."""
    model_run = _parse_iso_utc(reference_time)
    valid_date = _parse_iso_utc(valid_time)
    om_segment = "/".join(
        [
            f"{model_run.year:04d}",
            _pad_utc(model_run.month),
            _pad_utc(model_run.day),
            f"{_pad_utc(model_run.hour)}00Z",
            (
                f"{valid_date.year:04d}-{_pad_utc(valid_date.month)}-"
                f"{_pad_utc(valid_date.day)}T{_pad_utc(valid_date.hour)}00.om"
            ),
        ]
    )
    return f"data_spatial/dwd_icon/{om_segment}"


def build_upstream_url(relative_path: str, query: Optional[dict[str, str]] = None) -> str:
    if not relative_path.startswith("data_spatial/dwd_icon/"):
        raise ValueError(f"Disallowed weather map path: {relative_path}")
    if query:
        return f"{OPEN_METEO_BASE}/{relative_path}?{urlencode(query)}"
    return f"{OPEN_METEO_BASE}/{relative_path}"


def _cache_entry_paths(cache_key: str) -> tuple[Path, Path]:
    prefix = cache_key[:2]
    base = _response_cache_dir() / prefix / cache_key
    return base.with_suffix(".meta.json"), base.with_suffix(".body")


def _make_cache_key(upstream_url: str, range_header: Optional[str]) -> str:
    material = upstream_url if not range_header else f"{upstream_url}|{range_header.strip()}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _read_cache_entry(cache_key: str) -> Optional[tuple[dict[str, Any], bytes]]:
    meta_path, body_path = _cache_entry_paths(cache_key)
    if not meta_path.is_file() or not body_path.is_file():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        body = body_path.read_bytes()
        return meta, body
    except (OSError, json.JSONDecodeError):
        return None


def _write_cache_entry(cache_key: str, meta: dict[str, Any], body: bytes) -> None:
    _ensure_cache_dirs()
    meta_path, body_path = _cache_entry_paths(cache_key)
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    body_path.write_bytes(body)


def _parse_range_header(range_header: str, total_size: int) -> Optional[tuple[int, int]]:
    match = re.match(r"bytes=(\d+)-(\d*)", range_header.strip())
    if not match:
        return None
    start = int(match.group(1))
    end = int(match.group(2)) if match.group(2) else total_size - 1
    end = min(end, total_size - 1)
    if start > end or start >= total_size:
        return None
    return start, end


def _slice_cached_body(
    body: bytes,
    range_header: Optional[str],
    meta: dict[str, Any],
) -> tuple[int, bytes, dict[str, str]]:
    headers = {
        "Content-Type": meta.get("content_type", "application/octet-stream"),
        "Accept-Ranges": "bytes",
    }
    if meta.get("etag"):
        headers["ETag"] = meta["etag"]
    if not range_header:
        headers["Cache-Control"] = "public, max-age=3600"
        return 200, body, headers

    parsed = _parse_range_header(range_header, len(body))
    if parsed is None:
        headers["Cache-Control"] = "public, max-age=3600"
        return 200, body, headers

    start, end = parsed
    chunk = body[start : end + 1]
    headers["Content-Range"] = f"bytes {start}-{end}/{len(body)}"
    headers["Content-Length"] = str(len(chunk))
    headers["Cache-Control"] = "public, max-age=3600"
    return 206, chunk, headers


async def compute_union_mission_bbox() -> list[float]:
    """Union bbox for active realtime missions with pad + snap."""
    mission_ids = [
        mission_id.strip()
        for mission_id in settings.active_realtime_missions
        if mission_id and mission_id.strip()
    ]
    if not mission_ids:
        return snap_bbox(FALLBACK_BOUNDS, settings.weather_map_bbox_snap_deg)

    data_service = get_data_service()
    union: Optional[dict[str, float]] = None

    for mission_id in mission_ids:
        try:
            df, _, _ = await data_service.load(
                "telemetry",
                mission_id,
                source_preference=None,
                force_refresh=False,
                current_user=None,
                hours_back=72,
            )
        except Exception as exc:
            logger.warning("Weather cache: failed loading telemetry for %s: %s", mission_id, exc)
            continue
        if df is None or df.empty:
            continue
        processed = preprocess_telemetry_df(df)
        if processed.empty:
            continue
        track_points = prepare_track_points(processed, max_points=1000)
        bounds = get_track_bounds(track_points)
        if not bounds:
            continue
        if union is None:
            union = dict(bounds)
        else:
            union["north"] = max(union["north"], bounds["north"])
            union["south"] = min(union["south"], bounds["south"])
            union["east"] = max(union["east"], bounds["east"])
            union["west"] = min(union["west"], bounds["west"])

    if union is None:
        raw = FALLBACK_BOUNDS
    else:
        raw = bounds_dict_to_list(union)

    padded = pad_bbox(raw, settings.weather_map_bbox_pad_deg)
    return snap_bbox(padded, settings.weather_map_bbox_snap_deg)


async def fetch_model_manifest_upstream() -> dict[str, Any]:
    url = build_upstream_url(LATEST_JSON_PATH)
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()


def _manifest_ttl_seconds() -> int:
    return max(60, int(getattr(settings, "weather_map_manifest_ttl_seconds", 6 * 3600) or 6 * 3600))


def manifest_age_seconds(manifest: Optional[dict[str, Any]]) -> Optional[float]:
    """Return age of a buddy manifest from cached_at, or None if unknown."""
    if not manifest:
        return None
    cached_at = manifest.get("cached_at")
    if not cached_at:
        return None
    try:
        parsed = _parse_iso_utc(str(cached_at))
    except ValueError:
        return None
    return max(0.0, (datetime.now(timezone.utc) - parsed).total_seconds())


def is_manifest_fresh(manifest: Optional[dict[str, Any]]) -> bool:
    """True when disk buddy manifest exists and is within weather_map_manifest_ttl_seconds."""
    age = manifest_age_seconds(manifest)
    if age is None:
        return False
    return age < _manifest_ttl_seconds()


def get_cached_manifest(*, require_fresh: bool = False) -> Optional[dict[str, Any]]:
    path = _manifest_path()
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if require_fresh and not is_manifest_fresh(payload):
        return None
    return payload


def write_buddy_manifest(payload: dict[str, Any]) -> None:
    _ensure_cache_dirs()
    _manifest_path().write_text(json.dumps(payload, indent=2), encoding="utf-8")


def clear_stale_manifest() -> bool:
    """Remove on-disk buddy manifest when older than TTL. Returns True if removed."""
    path = _manifest_path()
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = None
    if is_manifest_fresh(payload):
        return False
    try:
        path.unlink()
        return True
    except OSError:
        return False


def build_buddy_manifest(
    upstream_manifest: dict[str, Any],
    union_bbox: list[float],
    om_urls: dict[str, str],
) -> dict[str, Any]:
    om_proxy_urls = {step: buddy_om_proxy_url(url) for step, url in om_urls.items()}
    return {
        **upstream_manifest,
        "union_bbox": {
            "west": union_bbox[0],
            "south": union_bbox[1],
            "east": union_bbox[2],
            "north": union_bbox[3],
        },
        "om_urls": om_urls,
        "om_proxy_urls": om_proxy_urls,
        "wind_variable": WIND_VARIABLE,
        "cached_at": datetime.now(timezone.utc).isoformat(),
    }


def _nearest_valid_time(valid_times: list[str]) -> str:
    now_ms = time.time() * 1000
    nearest_time = valid_times[0]
    nearest_diff = float("inf")
    for valid_time in valid_times:
        try:
            diff = abs(_parse_iso_utc(valid_time).timestamp() * 1000 - now_ms)
        except ValueError:
            continue
        if diff < nearest_diff:
            nearest_diff = diff
            nearest_time = valid_time
    return nearest_time


def resolve_om_urls_for_manifest(
    upstream_manifest: dict[str, Any],
) -> dict[str, str]:
    valid_times = upstream_manifest.get("valid_times") or []
    reference_time = upstream_manifest.get("reference_time")
    if not reference_time or not valid_times:
        return {}

    om_urls: dict[str, str] = {}
    nearest = _nearest_valid_time(valid_times)
    om_urls["current_time_1H"] = build_upstream_url(
        resolve_om_relative_path(reference_time, nearest),
        {"variable": WIND_VARIABLE},
    )

    for index, valid_time in select_prefetch_timesteps(
        valid_times,
        horizon_days=settings.weather_map_prefetch_horizon_days,
        step_hours=settings.weather_map_prefetch_step_hours,
    ):
        time_step = f"valid_times_{index}"
        om_urls[time_step] = build_upstream_url(
            resolve_om_relative_path(reference_time, valid_time),
            {"variable": WIND_VARIABLE},
        )
    return om_urls


def buddy_om_proxy_url(upstream_url: str) -> str:
    """Convert upstream Open-Meteo URL to same-origin proxy path for om:// protocol."""
    parsed = urlparse(upstream_url)
    if parsed.netloc and parsed.netloc != OPEN_METEO_HOST:
        raise ValueError(f"Disallowed upstream host: {parsed.netloc}")
    relative = parsed.path.lstrip("/")
    query = parsed.query
    suffix = f"/api/map/weather/om/{relative}"
    if query:
        suffix = f"{suffix}?{query}"
    return suffix


def _response_headers_from_upstream(response: httpx.Response) -> dict[str, str]:
    out_headers = {
        "Content-Type": response.headers.get("content-type", "application/octet-stream"),
        "Accept-Ranges": response.headers.get("accept-ranges", "bytes"),
    }
    if response.headers.get("content-length"):
        out_headers["Content-Length"] = response.headers["content-length"]
    if response.headers.get("etag"):
        out_headers["ETag"] = response.headers["etag"]
    if response.headers.get("content-range"):
        out_headers["Content-Range"] = response.headers["content-range"]
    return out_headers


def _negative_cache_get(upstream_url: str) -> bool:
    expires_at = _NEGATIVE_UPSTREAM.get(upstream_url)
    if expires_at is None:
        return False
    if time.monotonic() >= expires_at:
        _NEGATIVE_UPSTREAM.pop(upstream_url, None)
        return False
    return True


def _negative_cache_set(upstream_url: str) -> None:
    _NEGATIVE_UPSTREAM[upstream_url] = time.monotonic() + _NEGATIVE_UPSTREAM_TTL_SECONDS


async def _fetch_upstream(
    upstream_url: str,
    range_header: Optional[str],
    *,
    head_only: bool = False,
) -> tuple[int, bytes, dict[str, str]]:
    headers: dict[str, str] = {}
    if range_header:
        headers["Range"] = range_header

    if _negative_cache_get(upstream_url):
        request = httpx.Request("HEAD" if head_only else "GET", upstream_url)
        response = httpx.Response(404, request=request)
        raise httpx.HTTPStatusError("Cached upstream 404", request=request, response=response)

    async with httpx.AsyncClient(timeout=60.0) as client:
        if head_only:
            response = await client.head(upstream_url, headers=headers)
        else:
            response = await client.get(upstream_url, headers=headers)
        if response.status_code == 404:
            _negative_cache_set(upstream_url)
        response.raise_for_status()
        out_headers = _response_headers_from_upstream(response)
        body = b"" if head_only else response.content
        if not head_only and "Content-Length" not in out_headers and body:
            out_headers["Content-Length"] = str(len(body))
        return response.status_code, body, out_headers


async def _get_or_fetch_cached(
    upstream_url: str,
    range_header: Optional[str],
    *,
    head_only: bool = False,
) -> tuple[int, bytes, dict[str, str], bool]:
    """Return status, body, headers, from_cache.

    Only full-file responses are written to disk. Range requests are served by
    slicing a cached (or freshly fetched) full body so Range fragments never
    proliferate under weather_cache/responses/.
    """
    if not upstream_url.startswith(OPEN_METEO_BASE):
        raise ValueError("Upstream URL is not allowlisted")

    full_key = _make_cache_key(upstream_url, None)
    full_cached = _read_cache_entry(full_key)

    if full_cached:
        _stats["cache_hits"] += 1
        meta, body = full_cached
        if head_only:
            headers = {
                "Content-Type": meta.get("content_type", "application/octet-stream"),
                "Accept-Ranges": "bytes",
                "Cache-Control": "public, max-age=3600",
            }
            if meta.get("etag"):
                headers["ETag"] = meta["etag"]
            if range_header:
                parsed = _parse_range_header(range_header, len(body))
                if parsed is not None:
                    start, end = parsed
                    headers["Content-Range"] = f"bytes {start}-{end}/{len(body)}"
                    headers["Content-Length"] = str(end - start + 1)
                    return 206, b"", headers, True
            headers["Content-Length"] = str(len(body))
            return 200, b"", headers, True
        status, chunk, headers = _slice_cached_body(body, range_header, meta)
        return status, chunk, headers, True

    _stats["cache_misses"] += 1
    _stats["upstream_fetches"] += 1
    # Always fetch the full object (no Range) so we can cache once and slice.
    status, body, headers = await _fetch_upstream(
        upstream_url, None, head_only=head_only
    )

    if head_only:
        out_headers = dict(headers)
        out_headers["Cache-Control"] = "public, max-age=3600"
        return status, b"", out_headers, False

    if status == 200 and body:
        meta = {
            "upstream_url": upstream_url,
            "content_type": headers.get("Content-Type", "application/octet-stream"),
            "etag": headers.get("ETag"),
            "status_code": 200,
            "cached_at": datetime.now(timezone.utc).isoformat(),
        }
        _write_cache_entry(full_key, meta, body)
        status_out, chunk, slice_headers = _slice_cached_body(body, range_header, meta)
        return status_out, chunk, slice_headers, False

    out_headers = dict(headers)
    out_headers["Cache-Control"] = "public, max-age=3600"
    return status, body, out_headers, False


async def proxy_open_meteo_request(
    relative_path: str,
    query_string: str,
    range_header: Optional[str],
    *,
    head_only: bool = False,
) -> tuple[int, bytes, dict[str, str]]:
    query_params = {k: v[0] for k, v in parse_qs(query_string).items()}
    if relative_path == LATEST_JSON_PATH:
        upstream_url = build_upstream_url(relative_path)
    else:
        if "variable" not in query_params:
            query_params["variable"] = WIND_VARIABLE
        upstream_url = build_upstream_url(relative_path, query_params)

    in_flight_key = _make_cache_key(
        upstream_url,
        f"{range_header or ''}|{'HEAD' if head_only else 'GET'}",
    )
    if in_flight_key in _IN_FLIGHT:
        status, body, headers, _ = await _IN_FLIGHT[in_flight_key]
        return status, body, headers

    task = asyncio.create_task(
        _get_or_fetch_cached(upstream_url, range_header, head_only=head_only)
    )
    _IN_FLIGHT[in_flight_key] = task
    try:
        status, body, headers, _ = await task
        return status, body, headers
    finally:
        _IN_FLIGHT.pop(in_flight_key, None)


async def prefetch_om_url(upstream_url: str) -> int:
    """Warm full-file cache for one .om URL. Returns bytes stored."""
    status, body, _, from_cache = await _get_or_fetch_cached(upstream_url, None)
    if status != 200 or not body:
        return 0
    if from_cache:
        return len(body)
    return len(body)


def _unlink_cache_pair(meta_path: Path) -> tuple[int, int]:
    """Remove meta + paired .body. Returns (files_removed, bytes_freed)."""
    removed = 0
    freed = 0
    body_path = meta_path.with_name(meta_path.name.replace(".meta.json", ".body"))
    for path in (body_path, meta_path):
        if not path.is_file():
            continue
        try:
            size = path.stat().st_size if path.suffix == ".body" else 0
            path.unlink()
            removed += 1
            freed += size
        except OSError:
            continue
    return removed, freed


def _remove_empty_cache_dirs(responses_root: Path) -> int:
    removed_dirs = 0
    if not responses_root.is_dir():
        return 0
    for dirpath, dirnames, filenames in os.walk(responses_root, topdown=False):
        if dirnames or filenames:
            continue
        path = Path(dirpath)
        if path == responses_root:
            continue
        try:
            path.rmdir()
            removed_dirs += 1
        except OSError:
            continue
    return removed_dirs


def _iter_body_entries() -> list[tuple[Path, Path, float, int]]:
    """Return (meta_path, body_path, mtime, byte_size) for each .body with optional meta."""
    responses_root = _response_cache_dir()
    entries: list[tuple[Path, Path, float, int]] = []
    if not responses_root.is_dir():
        return entries
    for body_path in responses_root.rglob("*.body"):
        try:
            st = body_path.stat()
            meta_path = body_path.with_name(body_path.name.replace(".body", ".meta.json"))
            entries.append((meta_path, body_path, st.st_mtime, st.st_size))
        except OSError:
            continue
    return entries


def purge_stale_runs(max_age_days: int = 7) -> int:
    """Remove cached response entries older than max_age_days. Returns meta pairs removed."""
    summary = purge_weather_cache(force_all=False, max_age_days=max_age_days, enforce_quota=False)
    return int(summary.get("stale_pairs_removed") or 0)


def enforce_weather_cache_quota() -> dict[str, int]:
    """Evict oldest-by-mtime full entries until under weather_map_cache_max_bytes."""
    max_bytes = int(getattr(settings, "weather_map_cache_max_bytes", 0) or 0)
    if max_bytes <= 0:
        return {"evicted_files": 0, "freed_bytes": 0}

    entries = _iter_body_entries()
    total = sum(size for _, _, _, size in entries)
    if total <= max_bytes:
        return {"evicted_files": 0, "freed_bytes": 0}

    entries.sort(key=lambda item: item[2])  # oldest mtime first
    removed_files = 0
    freed = 0
    for meta_path, body_path, _mtime, size in entries:
        if total <= max_bytes:
            break
        pair_removed, pair_freed = _unlink_cache_pair(meta_path)
        if pair_removed == 0 and body_path.is_file():
            try:
                body_path.unlink()
                pair_removed = 1
                pair_freed = size
            except OSError:
                continue
        removed_files += pair_removed
        freed += pair_freed
        total -= size

    _remove_empty_cache_dirs(_response_cache_dir())
    return {"evicted_files": removed_files, "freed_bytes": freed}


def purge_weather_cache(
    *,
    force_all: bool = False,
    max_age_days: Optional[int] = None,
    enforce_quota: bool = True,
) -> dict[str, Any]:
    """
    Remove stale/orphan weather map cache files and optionally enforce size quota.

    Runs regardless of weather_map_layers so stranded cache from a disabled
    feature can still be reclaimed.
    """
    if max_age_days is None:
        max_age_days = int(getattr(settings, "weather_map_prefetch_horizon_days", 7))
    cutoff = time.time() - max(0, max_age_days) * 24 * 60 * 60
    responses_root = _response_cache_dir()
    removed_files = 0
    freed_bytes = 0
    stale_pairs_removed = 0
    orphan_bodies_removed = 0

    if responses_root.is_dir():
        for meta_path in list(responses_root.rglob("*.meta.json")):
            try:
                if not force_all and meta_path.stat().st_mtime >= cutoff:
                    continue
            except OSError:
                continue
            pair_removed, pair_freed = _unlink_cache_pair(meta_path)
            removed_files += pair_removed
            freed_bytes += pair_freed
            if pair_removed:
                stale_pairs_removed += 1

        # Orphan .body files with no meta (e.g. interrupted writes / legacy fragments)
        for body_path in list(responses_root.rglob("*.body")):
            meta_path = body_path.with_name(body_path.name.replace(".body", ".meta.json"))
            if meta_path.is_file():
                continue
            try:
                size = body_path.stat().st_size
                body_path.unlink()
                removed_files += 1
                freed_bytes += size
                orphan_bodies_removed += 1
            except OSError:
                continue

        empty_dirs = _remove_empty_cache_dirs(responses_root)
    else:
        empty_dirs = 0

    quota = {"evicted_files": 0, "freed_bytes": 0}
    if enforce_quota:
        quota = enforce_weather_cache_quota()
        removed_files += quota["evicted_files"]
        freed_bytes += quota["freed_bytes"]

    summary = {
        "removed_files": removed_files,
        "freed_bytes": freed_bytes,
        "stale_pairs_removed": stale_pairs_removed,
        "orphan_bodies_removed": orphan_bodies_removed,
        "empty_dirs_removed": empty_dirs,
        "quota_evicted_files": quota["evicted_files"],
        "quota_freed_bytes": quota["freed_bytes"],
        "force_all": force_all,
        "max_age_days": max_age_days,
        "status": get_cache_status(),
    }
    return summary


def get_cache_status() -> dict[str, Any]:
    responses_root = _response_cache_dir()
    file_count = 0
    total_bytes = 0
    if responses_root.is_dir():
        for body_path in responses_root.rglob("*.body"):
            file_count += 1
            try:
                total_bytes += body_path.stat().st_size
            except OSError:
                pass

    manifest = get_cached_manifest()
    max_bytes = int(getattr(settings, "weather_map_cache_max_bytes", 0) or 0)
    return {
        "cache_dir": str(_cache_dir()),
        "response_files": file_count,
        "total_bytes": total_bytes,
        "max_bytes": max_bytes,
        "cache_hits": _stats["cache_hits"],
        "cache_misses": _stats["cache_misses"],
        "upstream_fetches": _stats["upstream_fetches"],
        "last_prefetch_at": _stats["last_prefetch_at"],
        "last_prefetch_summary": _stats["last_prefetch_summary"],
        "last_cleanup_at": _stats.get("last_cleanup_at"),
        "last_cleanup_summary": _stats.get("last_cleanup_summary"),
        "manifest_reference_time": manifest.get("reference_time") if manifest else None,
        "manifest_cached_at": manifest.get("cached_at") if manifest else None,
        "manifest_age_seconds": manifest_age_seconds(manifest),
        "manifest_ttl_seconds": _manifest_ttl_seconds(),
        "manifest_is_fresh": is_manifest_fresh(manifest),
        "union_bbox": manifest.get("union_bbox") if manifest else None,
    }


async def run_weather_map_cleanup() -> dict[str, Any]:
    """Always-on disk cleanup: TTL purge + quota (independent of feature toggle)."""
    summary = purge_weather_cache(force_all=False, enforce_quota=True)
    removed_stale_manifest = clear_stale_manifest()
    summary["stale_manifest_removed"] = removed_stale_manifest
    _stats["last_cleanup_at"] = datetime.now(timezone.utc).isoformat()
    _stats["last_cleanup_summary"] = {
        k: summary[k]
        for k in (
            "removed_files",
            "freed_bytes",
            "stale_pairs_removed",
            "orphan_bodies_removed",
            "quota_evicted_files",
            "quota_freed_bytes",
            "stale_manifest_removed",
        )
        if k in summary
    }
    logger.debug("Weather map cache cleanup complete: %s", _stats["last_cleanup_summary"])
    return summary


async def prefetch_union_bbox_cache() -> dict[str, Any]:
    """Daily prefetch orchestrator."""
    if not is_feature_enabled("weather_map_layers"):
        logger.info("Weather map prefetch skipped: weather_map_layers disabled")
        return {"skipped": True, "reason": "feature_disabled"}

    if not settings.weather_map_prefetch_enabled:
        logger.info("Weather map prefetch skipped: weather_map_prefetch_enabled=false")
        return {"skipped": True, "reason": "prefetch_disabled"}

    _ensure_cache_dirs()
    union_bbox = await compute_union_mission_bbox()
    upstream_manifest = await fetch_model_manifest_upstream()
    om_urls = resolve_om_urls_for_manifest(upstream_manifest)
    buddy_manifest = build_buddy_manifest(upstream_manifest, union_bbox, om_urls)
    write_buddy_manifest(buddy_manifest)

    bytes_stored = 0
    fetched = 0
    for time_step, upstream_url in om_urls.items():
        try:
            stored = await prefetch_om_url(upstream_url)
            bytes_stored += stored
            fetched += 1
        except Exception as exc:
            logger.warning("Weather prefetch failed for %s: %s", time_step, exc)

    cleanup = purge_weather_cache(force_all=False, enforce_quota=True)
    summary = {
        "union_bbox": buddy_manifest["union_bbox"],
        "reference_time": upstream_manifest.get("reference_time"),
        "timesteps_prefetched": fetched,
        "bytes_stored": bytes_stored,
        "stale_entries_removed": cleanup.get("stale_pairs_removed", 0),
        "cleanup": {
            "removed_files": cleanup.get("removed_files"),
            "freed_bytes": cleanup.get("freed_bytes"),
        },
    }
    _stats["last_prefetch_at"] = datetime.now(timezone.utc).isoformat()
    _stats["last_prefetch_summary"] = summary
    logger.debug("Weather map prefetch complete: %s", summary)
    return summary
