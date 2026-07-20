"""
Read-only SFMC (Teledyne Slocum Fleet Mission Control) HTTP client.

Auth against `/sfmc/api/*` is still being reverse-engineered (Client ID/Secret
currently returns 401). Methods are best-effort: failures return None / empty
and checklist autofill continues without SFMC.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from ..config import settings
from .sfmc_transforms import (
    extract_from_dockserver_commands,
    extract_from_surface_events_payload,
    merge_sfmc_checklist_values,
    parse_goto_ma,
    pick_latest_goto_archive_filename,
)

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


def sfmc_is_configured() -> bool:
    return bool(
        (settings.sfmc_base_url or "").strip()
        and (settings.sfmc_client_id or "").strip()
        and (settings.sfmc_client_secret or "").strip()
    )


def _base_url() -> str:
    return (settings.sfmc_base_url or "").rstrip("/")


def _auth_header_variants() -> list[tuple[str, dict[str, str], Optional[httpx.Auth]]]:
    cid = settings.sfmc_client_id or ""
    secret = settings.sfmc_client_secret or ""
    return [
        ("basic", {}, httpx.BasicAuth(cid, secret)),
        (
            "x_client",
            {"X-Client-Id": cid, "X-Client-Secret": secret},
            None,
        ),
        (
            "sfmc_headers",
            {"SFMC-Client-Id": cid, "SFMC-Client-Secret": secret},
            None,
        ),
    ]


async def _get_json(path: str, *, params: Optional[dict[str, Any]] = None) -> Optional[Any]:
    if not sfmc_is_configured():
        return None
    url = f"{_base_url()}{path}"
    verify = bool(settings.sfmc_verify_tls)
    async with httpx.AsyncClient(verify=verify, timeout=_TIMEOUT, follow_redirects=True) as client:
        for label, headers, auth in _auth_header_variants():
            try:
                response = await client.get(url, headers=headers, auth=auth, params=params)
            except httpx.HTTPError as err:
                logger.debug("SFMC GET %s (%s) failed: %s", path, label, err)
                continue
            if response.status_code == 401:
                continue
            if response.status_code >= 400:
                logger.debug("SFMC GET %s → %s (%s)", path, response.status_code, label)
                continue
            try:
                return response.json()
            except ValueError:
                logger.debug("SFMC GET %s non-JSON body", path)
                return None
    return None


async def _get_text(path: str, *, params: Optional[dict[str, Any]] = None) -> Optional[str]:
    if not sfmc_is_configured():
        return None
    url = f"{_base_url()}{path}"
    verify = bool(settings.sfmc_verify_tls)
    async with httpx.AsyncClient(verify=verify, timeout=_TIMEOUT, follow_redirects=True) as client:
        for label, headers, auth in _auth_header_variants():
            try:
                response = await client.get(url, headers=headers, auth=auth, params=params)
            except httpx.HTTPError as err:
                logger.debug("SFMC GET text %s (%s) failed: %s", path, label, err)
                continue
            if response.status_code in (401, 404) or response.status_code >= 400:
                continue
            return response.text
    return None


def _folder_names_from_listing(payload: Any) -> list[str]:
    if payload is None:
        return []
    if isinstance(payload, list):
        names: list[str] = []
        for item in payload:
            if isinstance(item, str):
                names.append(item)
            elif isinstance(item, dict):
                name = item.get("name") or item.get("fileName") or item.get("path")
                if name:
                    names.append(str(name))
        return names
    if isinstance(payload, dict):
        for key in ("files", "listing", "content", "entries"):
            if key in payload:
                return _folder_names_from_listing(payload[key])
    return []


async def fetch_surface_events_payload(glider_name: str) -> Optional[dict[str, Any]]:
    """Best-effort fetch of surface-events style payload for a glider."""
    candidates = [
        ("/sfmc/api/get-active-deployment-details", {"glider": glider_name}),
        ("/sfmc/api/get-active-deployment-details", {"gliderName": glider_name}),
        (f"/sfmc/api/gliders/{glider_name}/surface-events", None),
        (f"/sfmc/api/deployments/active", {"glider": glider_name}),
    ]
    for path, params in candidates:
        payload = await _get_json(path, params=params)
        if isinstance(payload, dict) and (
            "missionExecutionsMap" in payload or "surfaceEventsPage" in payload
        ):
            return payload
    return None


async def fetch_dockserver_commands(glider_name: str) -> list[dict[str, Any]]:
    candidates = [
        ("/sfmc/api/get-available-glider-scripts", {"glider": glider_name}),
        (f"/sfmc/api/gliders/{glider_name}/commands", None),
        (f"/sfmc/api/gliders/{glider_name}/dockserver-commands", None),
    ]
    for path, params in candidates:
        payload = await _get_json(path, params=params)
        if isinstance(payload, list) and payload and isinstance(payload[0], dict):
            if "dockServerScriptName" in payload[0] or "command" in payload[0]:
                return [c for c in payload if isinstance(c, dict)]
        if isinstance(payload, dict):
            for key in ("commands", "content", "items"):
                items = payload.get(key)
                if isinstance(items, list) and items and isinstance(items[0], dict):
                    return [c for c in items if isinstance(c, dict)]
    return []


async def fetch_latest_goto_from_archive(glider_name: str) -> Optional[dict[str, Any]]:
    """
    List glider archive folder, pick newest ``*_goto_*.ma``, download and parse.
    """
    listing_paths = [
        ("/sfmc/api/get-glider-folder-listing", {"glider": glider_name, "folder": "archive"}),
        ("/sfmc/api/get-glider-folder-listing", {"gliderName": glider_name, "folder": "archive"}),
        (f"/sfmc/api/gliders/{glider_name}/folder-listing", {"folder": "archive"}),
    ]
    names: list[str] = []
    for path, params in listing_paths:
        payload = await _get_json(path, params=params)
        names = _folder_names_from_listing(payload)
        if names:
            break
    latest = pick_latest_goto_archive_filename(names)
    if not latest:
        return None

    download_paths = [
        (
            "/sfmc/api/download-glider-files",
            {"glider": glider_name, "folder": "archive", "file": latest},
        ),
        (
            f"/sfmc/api/gliders/{glider_name}/files/archive/{latest}",
            None,
        ),
    ]
    text: Optional[str] = None
    for path, params in download_paths:
        text = await _get_text(path, params=params)
        if text and "initial_wpt" in text.lower():
            break
        text = None
    if not text:
        return None
    parsed = parse_goto_ma(text)
    parsed["archive_filename"] = latest
    return parsed


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
        surface = await fetch_surface_events_payload(name)
        if surface:
            parts.append(extract_from_surface_events_payload(surface))
    except Exception as err:
        logger.warning("SFMC surface-events fetch failed for %s: %s", name, err)

    try:
        commands = await fetch_dockserver_commands(name)
        if commands:
            parts.append(extract_from_dockserver_commands(commands))
    except Exception as err:
        logger.warning("SFMC command-log fetch failed for %s: %s", name, err)

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
