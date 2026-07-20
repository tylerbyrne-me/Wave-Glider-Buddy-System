"""
Pure transforms from SFMC web/API payload shapes → Slocum checklist field values.

No HTTP here — feed payloads from ``sfmc_client`` or saved exploration samples.
``u_alt_min_depth_val`` is intentionally omitted (pilot-entered / prior checklist).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath
from typing import Any, Optional

_GOTO_NAME_RE = re.compile(
    r"^.+_goto_.+\.ma$",
    re.IGNORECASE,
)
_GOTO_STAMP_RE = re.compile(
    r"^(?P<stamp>\d{8}T\d{6})_",
    re.IGNORECASE,
)
_INITIAL_WPT_RE = re.compile(
    r"b_arg:\s*initial_wpt\s*\(\s*enum\s*\)\s*(-?\d+)",
    re.IGNORECASE,
)
_OFFLOAD_CMD_RE = re.compile(
    r"(?:!dockzr|\bs\s+\*\.(?:scd|tcd|asc)\b)",
    re.IGNORECASE,
)

_INITIAL_WPT_LABELS = {
    -2: "closest",
    -1: "after last achieved",
    0: "first waypoint (index 0)",
}


def _parse_sfmc_dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            dt = datetime.strptime(text.replace("Z", ""), fmt.replace("Z", ""))
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def script_basename(dock_server_script_name: str) -> str:
    """``.../scripts//TC_safe_g3s.xml`` → ``TC_safe_g3s.xml``."""
    name = PurePosixPath(str(dock_server_script_name).replace("\\", "/")).name
    return name or str(dock_server_script_name).strip()


def format_initial_wpt(value: int) -> str:
    label = _INITIAL_WPT_LABELS.get(value)
    if label:
        return f"{value} ({label})"
    if value > 0:
        return f"{value} (waypoint index {value})"
    return str(value)


def parse_goto_ma(text: str) -> dict[str, Any]:
    """
    Parse a Slocum goto list ``.ma`` file (any ``*_goto_*.ma`` variant).

    Returns ``initial_wpt`` (int|None), ``display`` for ``goto_state_val``, and
    ``num_waypoints`` when present.
    """
    match = _INITIAL_WPT_RE.search(text or "")
    initial_wpt: Optional[int] = int(match.group(1)) if match else None
    num_match = re.search(
        r"b_arg:\s*num_waypoints\s*\(\s*nodim\s*\)\s*(-?\d+)",
        text or "",
        re.IGNORECASE,
    )
    num_waypoints = int(num_match.group(1)) if num_match else None
    display = format_initial_wpt(initial_wpt) if initial_wpt is not None else None
    return {
        "initial_wpt": initial_wpt,
        "num_waypoints": num_waypoints,
        "display": display,
    }


# Back-compat alias
parse_goto_l10_ma = parse_goto_ma


def pick_latest_goto_archive_filename(names: list[str]) -> Optional[str]:
    """
    Choose the newest archive goto file matching ``*_goto_*.ma``.

    Prefers ``YYYYMMDDTHHMMSS_*_goto_*.ma`` by stamp (e.g.
    ``20260624T115617_goto_l10.ma``, ``20260701T120000_goto_l1.ma``).
    If no stamped names match, falls back to lexicographic max of ``*_goto_*.ma``.
    """
    stamped: list[tuple[str, str]] = []
    unstamped: list[str] = []
    for name in names:
        base = PurePosixPath(str(name).replace("\\", "/")).name
        if not _GOTO_NAME_RE.match(base):
            continue
        stamp_match = _GOTO_STAMP_RE.match(base)
        if stamp_match:
            stamped.append((stamp_match.group("stamp"), base))
        else:
            unstamped.append(base)
    if stamped:
        stamped.sort(key=lambda item: item[0], reverse=True)
        return stamped[0][1]
    if unstamped:
        return sorted(unstamped)[-1]
    return None


def extract_from_surface_events_payload(payload: dict[str, Any]) -> dict[str, str]:
    """Map SFMC surface-events / deployment page JSON → checklist fields."""
    out: dict[str, str] = {}
    if not isinstance(payload, dict):
        return out

    missions = payload.get("missionExecutionsMap") or {}
    if isinstance(missions, dict):
        active = None
        for entry in missions.values():
            if not isinstance(entry, dict):
                continue
            if entry.get("endDateTime") is None and not entry.get("complete"):
                active = entry
                break
        if active is None:
            for entry in missions.values():
                if isinstance(entry, dict):
                    active = entry
                    break
        if isinstance(active, dict) and active.get("missionName"):
            out["mission_file_running_val"] = str(active["missionName"]).strip()

    page = payload.get("surfaceEventsPage") or {}
    content = page.get("content") if isinstance(page, dict) else None
    latest = content[0] if isinstance(content, list) and content else None
    hours_map = payload.get("hoursSinceMap") or {}

    if isinstance(latest, dict):
        event_id = latest.get("id")
        hours_val = None
        if isinstance(hours_map, dict) and event_id is not None:
            hours_val = hours_map.get(event_id)
            if hours_val is None:
                hours_val = hours_map.get(str(event_id))
        if hours_val is not None:
            try:
                hours = float(hours_val)
                out["surfacing_hours_val"] = f"{hours:.1f}".rstrip("0").rstrip(".")
            except (TypeError, ValueError):
                pass
        elif isinstance(hours_map, dict) and hours_map:
            try:
                # Prefer typical leg interval (~> 0.1 h), skip near-zero double-surface
                candidates = [
                    float(v)
                    for v in hours_map.values()
                    if isinstance(v, (int, float)) and float(v) >= 0.1
                ]
                if candidates:
                    hours = candidates[0]
                    out["surfacing_hours_val"] = f"{hours:.1f}".rstrip("0").rstrip(".")
            except (TypeError, ValueError):
                pass

        abort = bool(latest.get("abort"))
        warnings = latest.get("totalWarnings")
        oddities = latest.get("totalOddities")
        reason = (latest.get("reason") or "").strip()
        details = (latest.get("moreDetails") or "").strip()
        abort_bit = (
            f"ABORT @ {latest.get('abortDateTime')}"
            if abort
            else "No abort"
        )
        bits = [abort_bit, f"{warnings} warnings", f"{oddities} oddities"]
        if reason:
            detail_bit = reason
            if details:
                detail_bit = f"{reason} ({details})"
            bits.append(f"last surface: {detail_bit}")
        out["aborts_oddities_val"] = "; ".join(str(b) for b in bits if b is not None)

        bearing = latest.get("nextWaypointBearingInDeg")
        range_m = latest.get("nextWaypointRangeInM")
        if bearing is not None and range_m is not None:
            # Supplemental only — full goto_state comes from archive .ma
            out.setdefault(
                "goto_state_val",
                f"next wpt {float(range_m):.0f} m @ {float(bearing):.0f}°",
            )

    connections = payload.get("connectionsMap") or {}
    if isinstance(connections, dict):
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        recent = False
        for conn in connections.values():
            if not isinstance(conn, dict):
                continue
            for key in ("endDateTime", "startDateTime"):
                dt = _parse_sfmc_dt(conn.get(key))
                if dt is not None and dt >= cutoff:
                    recent = True
                    break
            if recent:
                break
        if recent:
            out.setdefault("offloaded_24h_val", "Yes")

    return out


def extract_from_dockserver_commands(
    commands: list[dict[str, Any]],
    *,
    now: Optional[datetime] = None,
) -> dict[str, str]:
    """Map dockserver command log → script + offload checklist fields."""
    out: dict[str, str] = {}
    if not commands:
        return out

    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)

    # Newest command first when sortable
    ordered = sorted(
        (c for c in commands if isinstance(c, dict)),
        key=lambda c: _parse_sfmc_dt(c.get("submissionDateTime")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )

    for entry in ordered:
        script_path = entry.get("dockServerScriptName")
        if script_path:
            out["script_running_val"] = script_basename(str(script_path))
            break

    offload_hit = False
    for entry in ordered:
        cmd = str(entry.get("command") or "")
        if not _OFFLOAD_CMD_RE.search(cmd):
            continue
        dt = _parse_sfmc_dt(entry.get("submissionDateTime"))
        if dt is None or dt >= cutoff:
            offload_hit = True
            break

    if offload_hit:
        out["offloaded_24h_val"] = "Yes"
    elif ordered:
        # Had command history but no offload cmds in 24h
        out.setdefault("offloaded_24h_val", "No — manual offload ASAP")

    return out


def merge_sfmc_checklist_values(*parts: dict[str, str]) -> dict[str, str]:
    """Merge SFMC-derived maps; later non-empty values win."""
    merged: dict[str, str] = {}
    for part in parts:
        for key, value in (part or {}).items():
            if value is None:
                continue
            text = str(value).strip()
            if text:
                merged[key] = text
    # Never autofill pilot altitude min depth from SFMC
    merged.pop("u_alt_min_depth_val", None)
    return merged
