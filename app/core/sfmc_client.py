"""
Read-only SFMC HTTP client (Teledyne Slocum Fleet Mission Control).

Auth and paths mirror Teledyne's Node ``sfmc`` package:

- ``POST /sfmc/api/signin`` with ``{clientId, secret}`` → ``{token: ...}``
- ``GET /sfmc/api/v1/...`` with ``Authorization: Bearer <token>``

Failures are best-effort: checklist autofill continues without SFMC.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import quote

import httpx

from ..config import settings
from .sfmc_transforms import (
    extract_from_dockserver_commands,
    extract_from_surface_events_payload,
    merge_sfmc_checklist_values,
    parse_goto_ma,
    pick_latest_goto_archive_filename,
    script_basename,
)

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(45.0, connect=15.0)

# In-process token cache (per worker).
_token_cache: dict[str, Any] = {"token": None, "expires_at": 0.0}


def sfmc_is_configured() -> bool:
    return bool(
        (settings.sfmc_base_url or "").strip()
        and (settings.sfmc_client_id or "").strip()
        and (settings.sfmc_client_secret or "").strip()
    )


def _base_url() -> str:
    raw = (settings.sfmc_base_url or "").strip().rstrip("/")
    if not raw:
        return ""
    if "://" not in raw:
        return f"https://{raw}"
    return raw


def _verify_tls() -> bool:
    return bool(settings.sfmc_verify_tls)


def _extract_token(payload: Any) -> Optional[str]:
    if not isinstance(payload, dict):
        return None
    for key in ("token", "access_token", "accessToken"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


async def get_access_token(*, force_refresh: bool = False) -> Optional[str]:
    """POST /sfmc/api/signin with Teledyne ``clientId`` / ``secret`` body."""
    if not sfmc_is_configured():
        return None

    now = time.monotonic()
    cached = _token_cache.get("token")
    expires_at = float(_token_cache.get("expires_at") or 0.0)
    if not force_refresh and cached and now < expires_at:
        return str(cached)

    url = f"{_base_url()}/sfmc/api/signin"
    body = {
        "clientId": settings.sfmc_client_id,
        "secret": settings.sfmc_client_secret,
    }
    try:
        async with httpx.AsyncClient(
            verify=_verify_tls(), timeout=_TIMEOUT, follow_redirects=True
        ) as client:
            response = await client.post(url, json=body)
    except httpx.HTTPError as err:
        logger.warning("SFMC signin request failed: %s", err)
        return None

    if response.status_code != 200:
        logger.warning("SFMC signin → HTTP %s: %s", response.status_code, response.text[:200])
        return None

    try:
        payload = response.json()
    except ValueError:
        logger.warning("SFMC signin returned non-JSON body")
        return None

    token = _extract_token(payload)
    if not token:
        logger.warning("SFMC signin JSON missing token field (keys=%s)", list(payload)[:12])
        return None

    # Tokens typically last many minutes; refresh early if no expiry provided.
    ttl = 15 * 60
    expires_in = payload.get("expires_in") or payload.get("expiresIn")
    if isinstance(expires_in, (int, float)) and expires_in > 60:
        ttl = float(expires_in) - 60.0
    _token_cache["token"] = token
    _token_cache["expires_at"] = now + ttl
    return token


async def _request(
    method: str,
    path: str,
    *,
    params: Optional[dict[str, Any]] = None,
    expect_json: bool = True,
) -> Optional[Any]:
    token = await get_access_token()
    if not token:
        return None

    url = f"{_base_url()}{path}"

    async def _once(auth_token: str) -> httpx.Response:
        async with httpx.AsyncClient(
            verify=_verify_tls(), timeout=_TIMEOUT, follow_redirects=True
        ) as client:
            return await client.request(
                method,
                url,
                headers={"Authorization": f"Bearer {auth_token}"},
                params=params,
            )

    try:
        response = await _once(token)
    except httpx.HTTPError as err:
        logger.debug("SFMC %s %s failed: %s", method, path, err)
        return None

    if response.status_code == 401:
        token = await get_access_token(force_refresh=True)
        if not token:
            return None
        try:
            response = await _once(token)
        except httpx.HTTPError as err:
            logger.debug("SFMC retry %s %s failed: %s", method, path, err)
            return None

    if response.status_code == 429:
        logger.warning("SFMC rate-limited on %s %s", method, path)
        return None
    if response.status_code != 200:
        logger.debug("SFMC %s %s → %s", method, path, response.status_code)
        return None

    if expect_json:
        try:
            return response.json()
        except ValueError:
            logger.debug("SFMC %s %s non-JSON", method, path)
            return None
    return response.text


async def _get_json(path: str, *, params: Optional[dict[str, Any]] = None) -> Optional[Any]:
    payload = await _request("GET", path, params=params, expect_json=True)
    return _unwrap_data(payload)


def _unwrap_data(payload: Any) -> Any:
    """SFMC v1 responses are often ``{\"data\": ...}``; unwrap when present."""
    if isinstance(payload, dict) and "data" in payload and len(payload) <= 3:
        return payload["data"]
    return payload


async def _get_text(path: str, *, params: Optional[dict[str, Any]] = None) -> Optional[str]:
    result = await _request("GET", path, params=params, expect_json=False)
    return result if isinstance(result, str) else None


def _folder_names_from_listing(payload: Any) -> list[str]:
    if payload is None:
        return []
    if isinstance(payload, list):
        names: list[str] = []
        for item in payload:
            if isinstance(item, str):
                names.append(item)
            elif isinstance(item, dict):
                name = (
                    item.get("fileName")
                    or item.get("filename")
                    or item.get("name")
                    or item.get("path")
                )
                if name:
                    names.append(str(name))
        return names
    if isinstance(payload, dict):
        # Live SFMC: {links, limit, results:[{fileName, dateTimeModified, fileSize}]}
        for key in ("results", "files", "listing", "content", "entries", "fileListing"):
            if key in payload:
                return _folder_names_from_listing(payload[key])
    return []


def _extract_script_from_scripts_payload(payload: Any) -> Optional[str]:
    """Best-effort assigned/current script name from scripts-for-glider JSON."""
    if payload is None:
        return None
    payload = _unwrap_data(payload)
    if isinstance(payload, str) and payload.strip().endswith((".xml", ".mi")):
        return script_basename(payload)
    if isinstance(payload, list):
        for item in payload:
            found = _extract_script_from_scripts_payload(item)
            if found:
                return found
        return None
    if not isinstance(payload, dict):
        return None

    for key in (
        "assignedScript",
        "assignedScriptName",
        "assignedDockServerScript",
        "dockServerScriptName",
        "currentScript",
        "scriptName",
        "script",
    ):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return script_basename(value)
        if isinstance(value, dict):
            nested = value.get("name") or value.get("path") or value.get("fileName")
            if isinstance(nested, str) and nested.strip():
                return script_basename(nested)

    for key in ("scripts", "availableScripts", "userScripts", "content", "items"):
        if key in payload:
            found = _extract_script_from_scripts_payload(payload[key])
            if found:
                return found

    for item in payload.get("userScripts") or payload.get("scripts") or payload.get("content") or []:
        if isinstance(item, dict) and (
            item.get("assigned") or item.get("isAssigned") or item.get("active")
        ):
            name = item.get("name") or item.get("scriptName") or item.get("path") or item.get("fileName")
            if name:
                return script_basename(str(name))
    return None


def _mission_name_from_payload(payload: Any) -> Optional[str]:
    payload = _unwrap_data(payload)
    if not isinstance(payload, dict):
        return None
    name = payload.get("missionName") or payload.get("mission_file") or payload.get("missionFile")
    if isinstance(name, str) and name.strip():
        return name.strip()
    mission = payload.get("mission")
    if isinstance(mission, dict):
        nested = mission.get("name") or mission.get("missionName")
        if isinstance(nested, str) and nested.strip():
            return nested.strip()
    if isinstance(mission, str) and mission.strip():
        return mission.strip()
    return None


async def fetch_active_deployment(glider_name: str) -> Optional[dict[str, Any]]:
    payload = await _get_json(f"/sfmc/api/v1/active-deployment/{quote(glider_name, safe='')}")
    return payload if isinstance(payload, dict) else None


async def fetch_newest_mission_details(glider_name: str) -> Optional[dict[str, Any]]:
    payload = await _get_json(f"/sfmc/api/v1/newest-mission-details/{quote(glider_name, safe='')}")
    return payload if isinstance(payload, dict) else None


async def fetch_scripts_for_glider(glider_name: str) -> Optional[Any]:
    return await _get_json(f"/sfmc/api/v1/scripts-for-glider/{quote(glider_name, safe='')}")


async def fetch_folder_listing(
    glider_name: str,
    folder: str,
    *,
    page: int = 0,
    filter_glob: Optional[str] = "*",
    last_modified_after: Optional[str] = None,
) -> Optional[Any]:
    """
    ``GET /sfmc/api/v1/glider-folder-file-listing/{glider}/{folder}``

    ``last_modified_after`` format: ``yyyyMMddHHmm`` (Teledyne convention).
    """
    params: dict[str, Any] = {"page": page}
    # Teledyne also accepts filter / lastModifiedAfter as query params (with page).
    if filter_glob is not None:
        params["filter"] = filter_glob
    if last_modified_after is not None:
        params["lastModifiedAfter"] = last_modified_after
    path = (
        f"/sfmc/api/v1/glider-folder-file-listing/"
        f"{quote(glider_name, safe='')}/{quote(folder, safe='')}"
    )
    return await _get_json(path, params=params)


async def download_glider_file_text(glider_name: str, folder: str, file_name: str) -> Optional[str]:
    path = (
        f"/sfmc/api/v1/download-glider-file/"
        f"{quote(glider_name, safe='')}/"
        f"{quote(folder, safe='')}/"
        f"{quote(file_name, safe='')}"
    )
    return await _get_text(path)


def _last_modified_after_24h() -> str:
    dt = datetime.now(timezone.utc) - timedelta(hours=24)
    return dt.strftime("%Y%m%d%H%M")


async def fetch_surface_events_payload(glider_name: str) -> Optional[dict[str, Any]]:
    """Active deployment details (often includes mission / surface-event maps)."""
    payload = await fetch_active_deployment(glider_name)
    if isinstance(payload, dict) and (
        "missionExecutionsMap" in payload
        or "surfaceEventsPage" in payload
        or "missionName" in payload
        or "mission" in payload
    ):
        return payload
    return payload if isinstance(payload, dict) else None


async def fetch_dockserver_commands(glider_name: str) -> list[dict[str, Any]]:
    """
    Prefer scripts endpoint; command-log shape is not in the Teledyne REST lib.
    Returns [] when payload is not a command list (script name handled separately).
    """
    payload = await fetch_scripts_for_glider(glider_name)
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        if "dockServerScriptName" in payload[0] or "command" in payload[0]:
            return [c for c in payload if isinstance(c, dict)]
    if isinstance(payload, dict):
        for key in ("commands", "content", "items"):
            items = payload.get(key)
            if isinstance(items, list) and items and isinstance(items[0], dict):
                if "command" in items[0] or "dockServerScriptName" in items[0]:
                    return [c for c in items if isinstance(c, dict)]
    return []


async def fetch_latest_goto_from_archive(glider_name: str) -> Optional[dict[str, Any]]:
    """List ``archive`` for ``*_goto_*.ma``, download newest, parse ``initial_wpt``."""
    payload = await fetch_folder_listing(
        glider_name,
        "archive",
        page=0,
        filter_glob="*_goto_*.ma",
    )
    names = _folder_names_from_listing(payload)
    if not names:
        # Broader listing if filter unsupported
        payload = await fetch_folder_listing(glider_name, "archive", page=0, filter_glob="*")
        names = _folder_names_from_listing(payload)

    latest = pick_latest_goto_archive_filename(names)
    if not latest:
        return None

    text = await download_glider_file_text(glider_name, "archive", latest)
    if not text:
        return None
    parsed = parse_goto_ma(text)
    parsed["archive_filename"] = latest
    return parsed


async def fetch_offload_hint(glider_name: str) -> Optional[str]:
    """Yes if ``from-glider`` has files modified in the last 24h."""
    payload = await fetch_folder_listing(
        glider_name,
        "from-glider",
        page=0,
        filter_glob="*",
        last_modified_after=_last_modified_after_24h(),
    )
    names = _folder_names_from_listing(payload)
    if names:
        return "Yes"
    # Empty filtered listing → no recent files (or empty folder)
    if payload is not None:
        return "No — manual offload ASAP"
    return None


def _normalize_active_deployment_for_transforms(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Ensure transform helpers see missionExecutionsMap-style keys when the API
    returns a flatter active-deployment object.
    """
    if "missionExecutionsMap" in payload or "surfaceEventsPage" in payload:
        return payload

    out = dict(payload)
    mission_name = _mission_name_from_payload(payload)
    if mission_name:
        out.setdefault(
            "missionExecutionsMap",
            {
                "0": {
                    "missionName": mission_name,
                    "endDateTime": None,
                    "complete": False,
                }
            },
        )
    return out


async def load_sfmc_checklist_values(glider_name: str) -> dict[str, str]:
    """
    Pull SFMC-derived checklist autofill for ``glider_name`` (e.g. ``peggy``).

    Returns empty dict when SFMC is unconfigured or unreachable/unauthorized.
    """
    name = (glider_name or "").strip()
    if not name or not sfmc_is_configured():
        return {}

    parts: list[dict[str, str]] = []

    try:
        mission = await fetch_newest_mission_details(name)
        mission_name = _mission_name_from_payload(mission)
        if mission_name:
            parts.append({"mission_file_running_val": mission_name})
    except Exception as err:
        logger.warning("SFMC newest-mission-details failed for %s: %s", name, err)

    try:
        surface = await fetch_surface_events_payload(name)
        if surface:
            parts.append(
                extract_from_surface_events_payload(
                    _normalize_active_deployment_for_transforms(surface)
                )
            )
    except Exception as err:
        logger.warning("SFMC active-deployment fetch failed for %s: %s", name, err)

    try:
        scripts_payload = await fetch_scripts_for_glider(name)
        script_name = _extract_script_from_scripts_payload(scripts_payload)
        if script_name:
            parts.append({"script_running_val": script_name})
        commands = await fetch_dockserver_commands(name)
        if commands:
            parts.append(extract_from_dockserver_commands(commands))
    except Exception as err:
        logger.warning("SFMC scripts fetch failed for %s: %s", name, err)

    try:
        offload = await fetch_offload_hint(name)
        if offload:
            parts.append({"offloaded_24h_val": offload})
    except Exception as err:
        logger.warning("SFMC from-glider listing failed for %s: %s", name, err)

    try:
        goto = await fetch_latest_goto_from_archive(name)
        if goto and goto.get("display"):
            parts.append({"goto_state_val": str(goto["display"])})
    except Exception as err:
        logger.warning("SFMC goto archive fetch failed for %s: %s", name, err)

    merged = merge_sfmc_checklist_values(*parts)
    if merged:
        logger.info("SFMC checklist autofill for %s: %s", name, sorted(merged.keys()))
    return merged
