"""Open-Meteo weather map layer disk cache, prefetch, and fetch-through proxy."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
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
_stats = {
    "cache_hits": 0,
    "cache_misses": 0,
    "upstream_fetches": 0,
    "last_prefetch_at": None,
    "last_prefetch_summary": None,
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


def get_cached_manifest() -> Optional[dict[str, Any]]:
    path = _manifest_path()
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_buddy_manifest(payload: dict[str, Any]) -> None:
    _ensure_cache_dirs()
    _manifest_path().write_text(json.dumps(payload, indent=2), encoding="utf-8")


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


async def _fetch_upstream(
    upstream_url: str,
    range_header: Optional[str],
    *,
    head_only: bool = False,
) -> tuple[int, bytes, dict[str, str]]:
    headers: dict[str, str] = {}
    if range_header:
        headers["Range"] = range_header

    async with httpx.AsyncClient(timeout=60.0) as client:
        if head_only:
            response = await client.head(upstream_url, headers=headers)
        else:
            response = await client.get(upstream_url, headers=headers)
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
    """Return status, body, headers, from_cache."""
    if not upstream_url.startswith(OPEN_METEO_BASE):
        raise ValueError("Upstream URL is not allowlisted")

    full_key = _make_cache_key(upstream_url, None)
    range_key = _make_cache_key(upstream_url, range_header) if range_header else full_key

    full_cached = _read_cache_entry(full_key)
    if full_cached and not range_header:
        _stats["cache_hits"] += 1
        meta, body = full_cached
        if head_only:
            headers = {
                "Content-Type": meta.get("content_type", "application/octet-stream"),
                "Accept-Ranges": "bytes",
                "Content-Length": str(len(body)),
                "Cache-Control": "public, max-age=3600",
            }
            if meta.get("etag"):
                headers["ETag"] = meta["etag"]
            return 200, b"", headers, True
        status, chunk, headers = _slice_cached_body(body, None, meta)
        return status, chunk, headers, True

    if full_cached and range_header:
        meta, body = full_cached
        _stats["cache_hits"] += 1
        if head_only:
            parsed = _parse_range_header(range_header, len(body))
            headers = {
                "Content-Type": meta.get("content_type", "application/octet-stream"),
                "Accept-Ranges": "bytes",
                "Cache-Control": "public, max-age=3600",
            }
            if parsed is not None:
                start, end = parsed
                headers["Content-Range"] = f"bytes {start}-{end}/{len(body)}"
                headers["Content-Length"] = str(end - start + 1)
            else:
                headers["Content-Length"] = str(len(body))
            if meta.get("etag"):
                headers["ETag"] = meta["etag"]
            return 206 if parsed is not None else 200, b"", headers, True
        status, chunk, headers = _slice_cached_body(body, range_header, meta)
        return status, chunk, headers, True

    if range_header:
        ranged_cached = _read_cache_entry(range_key)
        if ranged_cached:
            _stats["cache_hits"] += 1
            meta, body = ranged_cached
            headers = {
                "Content-Type": meta.get("content_type", "application/octet-stream"),
                "Accept-Ranges": "bytes",
            }
            if meta.get("etag"):
                headers["ETag"] = meta["etag"]
            if meta.get("content_range"):
                headers["Content-Range"] = meta["content_range"]
            headers["Cache-Control"] = "public, max-age=3600"
            return meta.get("status_code", 206), body, headers, True

    _stats["cache_misses"] += 1
    _stats["upstream_fetches"] += 1
    status, body, headers = await _fetch_upstream(
        upstream_url, range_header, head_only=head_only
    )

    if not head_only:
        meta = {
            "upstream_url": upstream_url,
            "content_type": headers.get("Content-Type", "application/octet-stream"),
            "etag": headers.get("ETag"),
            "status_code": status,
            "content_range": headers.get("Content-Range"),
            "cached_at": datetime.now(timezone.utc).isoformat(),
        }

        if range_header:
            _write_cache_entry(range_key, meta, body)
        elif status == 200:
            _write_cache_entry(full_key, meta, body)

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


def purge_stale_runs(max_age_days: int = 7) -> int:
    """Remove cached response entries older than max_age_days. Returns files removed."""
    cutoff = time.time() - max_age_days * 24 * 60 * 60
    removed = 0
    responses_root = _response_cache_dir()
    if not responses_root.is_dir():
        return 0

    for meta_path in responses_root.rglob("*.meta.json"):
        try:
            if meta_path.stat().st_mtime >= cutoff:
                continue
            body_path = meta_path.with_name(meta_path.name.replace(".meta.json", ".body"))
            meta_path.unlink(missing_ok=True)
            if body_path.is_file():
                body_path.unlink()
            removed += 1
        except OSError:
            continue
    return removed


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
    return {
        "cache_dir": str(_cache_dir()),
        "response_files": file_count,
        "total_bytes": total_bytes,
        "cache_hits": _stats["cache_hits"],
        "cache_misses": _stats["cache_misses"],
        "upstream_fetches": _stats["upstream_fetches"],
        "last_prefetch_at": _stats["last_prefetch_at"],
        "last_prefetch_summary": _stats["last_prefetch_summary"],
        "manifest_reference_time": manifest.get("reference_time") if manifest else None,
        "union_bbox": manifest.get("union_bbox") if manifest else None,
    }


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

    removed = purge_stale_runs(settings.weather_map_prefetch_horizon_days)
    summary = {
        "union_bbox": buddy_manifest["union_bbox"],
        "reference_time": upstream_manifest.get("reference_time"),
        "timesteps_prefetched": fetched,
        "bytes_stored": bytes_stored,
        "stale_entries_removed": removed,
    }
    _stats["last_prefetch_at"] = datetime.now(timezone.utc).isoformat()
    _stats["last_prefetch_summary"] = summary
    logger.info("Weather map prefetch complete: %s", summary)
    return summary
