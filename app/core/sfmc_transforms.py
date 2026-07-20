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
_NETWORK_LOG_RE = re.compile(
    r"^(?P<stamp>\d{8}T\d{6})_?.*_network_net_\d+\.log$",
    re.IGNORECASE,
)
# Also: peggy_20260720T162013_network_net_0.log
_NETWORK_LOG_NAMED_RE = re.compile(
    r"^(?P<glider>[A-Za-z0-9_-]+)_(?P<stamp>\d{8}T\d{6})_network_net_\d+\.log$",
    re.IGNORECASE,
)
_DEVICES_TMS_RE = re.compile(
    r"devices:\(t/m/s\)\s*"
    r"errs:\s*(?P<te>\d+)\s*/\s*(?P<me>\d+)\s*/\s*(?P<se>\d+)\s*"
    r"warn:\s*(?P<tw>\d+)\s*/\s*(?P<mw>\d+)\s*/\s*(?P<sw>\d+)\s*"
    r"odd:\s*(?P<to>\d+)\s*/\s*(?P<mo>\d+)\s*/\s*(?P<so>\d+)",
    re.IGNORECASE,
)
_ABORT_HISTORY_RE = re.compile(
    r"ABORT HISTORY:\s*total since reset:\s*(?P<count>\d+)",
    re.IGNORECASE,
)
_MISSION_NAME_RE = re.compile(
    r"MissionName:\s*(?P<name>\S+\.mi)",
    re.IGNORECASE,
)
_BECAUSE_RE = re.compile(
    r"Because:\s*(?P<reason>.+?)(?:\r?\n)",
    re.IGNORECASE,
)
_SENSOR_LINE_RE = re.compile(
    r"sensor:(?P<name>[A-Za-z0-9_]+)\([^)]*\)=(?P<value>\S+)",
    re.IGNORECASE,
)

_INITIAL_WPT_LABELS = {
    -2: "closest",
    -1: "after last achieved",
    0: "first waypoint (index 0)",
}


def pick_typical_hours_since(hours_map: Any) -> Optional[float]:
    """
    Choose the common / most frequent \"Time Since Prior\" from ``hoursSinceMap``.

    Skips near-zero double-surface values (< 0.1 h). Prefers the modal value
    rounded to 0.1 h; if every value is unique, uses the median.
    """
    if not isinstance(hours_map, dict) or not hours_map:
        return None
    vals: list[float] = []
    for value in hours_map.values():
        try:
            hours = float(value)
        except (TypeError, ValueError):
            continue
        if hours >= 0.1:
            vals.append(hours)
    if not vals:
        return None

    from collections import Counter

    rounded = [round(v, 1) for v in vals]
    counts = Counter(rounded)
    best = max(counts.values())
    if best == 1:
        ordered = sorted(vals)
        return ordered[len(ordered) // 2]
    modes = sorted(h for h, c in counts.items() if c == best)
    return modes[len(modes) // 2]


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


def pick_latest_network_log_filename(names: list[str]) -> Optional[str]:
    """Newest ``{glider}_YYYYMMDDTHHMMSS_network_net_N.log`` by stamp."""
    best_name: Optional[str] = None
    best_stamp: Optional[str] = None
    for name in names:
        base = PurePosixPath(str(name).replace("\\", "/")).name
        match = _NETWORK_LOG_NAMED_RE.match(base) or _NETWORK_LOG_RE.match(base)
        if not match:
            continue
        stamp = match.group("stamp")
        if best_stamp is None or stamp > best_stamp:
            best_stamp = stamp
            best_name = base
    return best_name


def parse_surface_dialog_log(text: str) -> dict[str, str]:
    """
    Parse glider surface dialog / network log tail → checklist fields.

    Expects the ``Glider … at surface.`` block including Device Status (t/m/s):

    ``devices:(t/m/s) errs: t/m/s warn: t/m/s odd: t/m/s``
    """
    out: dict[str, str] = {}
    if not text or not str(text).strip():
        return out

    # Prefer the last (most recent) surface status block in the tail.
    blocks = re.split(r"(?=Glider\s+\S+\s+at surface\.)", text, flags=re.IGNORECASE)
    block = ""
    for candidate in reversed(blocks):
        if re.search(r"Glider\s+\S+\s+at surface\.", candidate, re.IGNORECASE):
            block = candidate
            break
    if not block:
        block = text

    mission = _MISSION_NAME_RE.search(block) or _MISSION_NAME_RE.search(text)
    if mission:
        out["mission_file_running_val"] = mission.group("name").strip()

    devices = _DEVICES_TMS_RE.search(block) or _DEVICES_TMS_RE.search(text)
    abort_hist = _ABORT_HISTORY_RE.search(block) or _ABORT_HISTORY_RE.search(text)
    because = _BECAUSE_RE.search(block) or _BECAUSE_RE.search(text)

    if devices or abort_hist or because:
        bits: list[str] = []
        abort_count = int(abort_hist.group("count")) if abort_hist else None
        if abort_count is None:
            bits.append("Abort history N/A")
        elif abort_count == 0:
            bits.append("No abort (history 0)")
        else:
            bits.append(f"ABORT HISTORY since reset: {abort_count}")

        if devices:
            bits.append(
                "Device Status (t/m/s): "
                f"errs {devices.group('te')}/{devices.group('me')}/{devices.group('se')}; "
                f"warn {devices.group('tw')}/{devices.group('mw')}/{devices.group('sw')}; "
                f"odd {devices.group('to')}/{devices.group('mo')}/{devices.group('so')}"
            )
        if because:
            reason = because.group("reason").strip()
            if reason:
                bits.append(f"last surface: {reason}")
        out["aborts_oddities_val"] = "; ".join(bits)

    # Sensor dump from full tail (last block may omit older lines).
    sensors: dict[str, str] = {}
    for match in _SENSOR_LINE_RE.finditer(text):
        sensors[match.group("name")] = match.group("value")
    if sensors.get("m_battery"):
        out["_dialog_m_battery"] = sensors["m_battery"]
    if sensors.get("u_alt_min_depth"):
        out["_dialog_u_alt_min_depth"] = sensors["u_alt_min_depth"]

    return out


def dialog_values_for_checklist(parsed: dict[str, str]) -> dict[str, str]:
    """Public checklist keys only (drops ``_dialog_*`` internals)."""
    return {
        key: value
        for key, value in (parsed or {}).items()
        if not key.startswith("_") and value
    }


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

    # Prefer the typical / modal dive-cycle interval, not the latest (often a
    # near-zero double-surface) and not GPS age.
    typical_hours = pick_typical_hours_since(hours_map)
    if typical_hours is not None:
        out["surfacing_hours_val"] = f"{typical_hours:.1f}".rstrip("0").rstrip(".")

    if isinstance(latest, dict):
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

    # Live v1 active-deployment is flat: bearing/range live at top level.
    if "goto_state_val" not in out:
        bearing = payload.get("nextWaypointBearingInDeg")
        range_m = payload.get("nextWaypointRangeInM")
        if bearing is not None and range_m is not None:
            try:
                out["goto_state_val"] = (
                    f"next wpt {float(range_m):.0f} m @ {float(bearing):.0f}°"
                )
            except (TypeError, ValueError):
                pass

    # Do NOT use GPS age as surfacing hours — that is \"time since last fix\",
    # not SFMC \"Time Since Prior\" (dive-cycle interval).

    # Live script assignment on flat active-deployment.
    script_name = payload.get("currentScriptName")
    if isinstance(script_name, str) and script_name.strip():
        display = script_basename(script_name)
        if payload.get("isCurrentScriptRunning") is False:
            display = f"{display} (not running)"
        out.setdefault("script_running_val", display)

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
            if key.startswith("_"):
                continue
            if value is None:
                continue
            text = str(value).strip()
            if text:
                merged[key] = text
    # Never autofill pilot altitude min depth from SFMC
    merged.pop("u_alt_min_depth_val", None)
    return merged
