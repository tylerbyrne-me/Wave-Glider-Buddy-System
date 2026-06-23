"""
Helpers for station / array history timelines, hardware segments, and aggregates.
"""

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.core.offload_comments import enrich_offload_log_read

from .station_overview import resolve_station_status_text_and_color


def _aware_ts(dt: Optional[datetime]) -> datetime:
    if dt is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def resolve_hardware_at_time(
    segments: List[Any],
    ts: Optional[datetime],
) -> Optional[Any]:
    """
    Return the hardware history segment effective at ts, or None if no match.
    A segment is effective when effective_start_utc <= ts < effective_end_utc
    (or effective_end_utc is None for the open segment).
    """
    if ts is None or not segments:
        return None
    aware_ts = _aware_ts(ts)
    for segment in segments:
        start = _aware_ts(segment.effective_start_utc)
        end = segment.effective_end_utc
        if end is not None:
            end = _aware_ts(end)
            if start <= aware_ts < end:
                return segment
            continue
        if start <= aware_ts:
            return segment
    return None


def _offload_effective_ts(log: Any) -> datetime:
    """Best-effort offload time for ordering and post-swap comparisons."""
    return _aware_ts(
        log.offload_end_time_utc
        or log.offload_start_time_utc
        or log.log_timestamp_utc
    )


def offload_log_attribution_ts(log: Any) -> Optional[datetime]:
    """
    Timestamp used to attribute serial/modem on a season export row.
    Prefers visit start over end when both are present.
    """
    raw = (
        log.offload_start_time_utc
        or log.offload_end_time_utc
        or getattr(log, "arrival_date", None)
        or log.log_timestamp_utc
    )
    if raw is None:
        return None
    return _aware_ts(raw)


def latest_hardware_swap_ts_by_station(
    hardware_rows: List[Any],
) -> Dict[str, datetime]:
    """Return the latest effective_start_utc per station_id."""
    out: Dict[str, datetime] = {}
    for row in hardware_rows:
        start_ts = row.effective_start_utc
        if start_ts is None:
            continue
        prev = out.get(row.station_id)
        if prev is None or start_ts > prev:
            out[row.station_id] = start_ts
    return out


def group_hardware_segments_by_station(
    hardware_rows: List[Any],
) -> Dict[str, List[Any]]:
    """Group hardware history rows by station_id."""
    segments: Dict[str, List[Any]] = defaultdict(list)
    for row in hardware_rows:
        segments[row.station_id].append(row)
    return dict(segments)


def has_offload_since_hardware_swap(
    all_logs: List[Any],
    latest_swap_ts: Optional[datetime],
) -> bool:
    """
    True when any offload log occurs strictly after the latest hardware swap.

    Scans all logs (not season-filtered) so a post-swap offload in one season
    clears the pending-swap state in later seasons.
    """
    if latest_swap_ts is None:
        return False
    swap_ts = _aware_ts(latest_swap_ts)
    for log in all_logs:
        if _offload_effective_ts(log) > swap_ts:
            return True
    return False


def is_awaiting_first_offload_after_swap(
    all_logs: List[Any],
    latest_swap_ts: Optional[datetime],
) -> bool:
    """True when a swap is on record and no offload has followed it yet."""
    return latest_swap_ts is not None and not has_offload_since_hardware_swap(
        all_logs, latest_swap_ts
    )


def aggregate_offload_stats(logs: List[Any]) -> Dict[str, Any]:
    """Success counts and average hours at station for a list of offload logs."""
    if not logs:
        return {
            "total_offload_logs": 0,
            "successful_offloads": 0,
            "failed_offloads": 0,
            "unknown_outcome": 0,
            "success_rate": 0.0,
            "average_time_at_station_hours": None,
        }
    successful = sum(1 for l in logs if l.was_offloaded is True)
    failed = sum(1 for l in logs if l.was_offloaded is False)
    unknown = len(logs) - successful - failed
    durations_sec: List[float] = []
    for log in logs:
        if log.arrival_date and log.departure_date:
            try:
                d = log.departure_date - log.arrival_date
                if hasattr(d, "total_seconds"):
                    durations_sec.append(float(d.total_seconds()))
            except (TypeError, ValueError):
                continue
    avg_h = (
        sum(durations_sec) / len(durations_sec) / 3600.0 if durations_sec else None
    )
    return {
        "total_offload_logs": len(logs),
        "successful_offloads": successful,
        "failed_offloads": failed,
        "unknown_outcome": unknown,
        "success_rate": (successful / len(logs) * 100.0) if logs else 0.0,
        "average_time_at_station_hours": avg_h,
    }


def build_station_timeline(
    logs: List[Any],
    hardware: List[Any],
    snapshots: List[Any],
    flag_events: Optional[List[Any]] = None,
) -> List[Dict[str, Any]]:
    """Merge offload logs, hardware changes, and season snapshots (newest first)."""
    items: List[Dict[str, Any]] = []
    for log in logs:
        ts = _offload_effective_ts(log)
        items.append(
            {
                "event_type": "offload_log",
                "sort_ts": ts.isoformat(),
                "payload": enrich_offload_log_read(log),
            }
        )
    for h in hardware:
        ts = _aware_ts(h.effective_start_utc)
        items.append(
            {
                "event_type": "hardware_change",
                "sort_ts": ts.isoformat(),
                "payload": h.model_dump(),
            }
        )
    for snap in snapshots:
        ts = _aware_ts(getattr(snap, "snapshot_created_at_utc", None))
        payload = snap.model_dump()
        items.append(
            {
                "event_type": "season_snapshot",
                "sort_ts": ts.isoformat(),
                "field_season_year": getattr(snap, "field_season_year", None),
                "payload": payload,
            }
        )
    for flag_event in (flag_events or []):
        ts = _aware_ts(getattr(flag_event, "changed_at_utc", None))
        items.append(
            {
                "event_type": "flag_event",
                "sort_ts": ts.isoformat(),
                "field_season_year": getattr(flag_event, "field_season_year", None),
                "payload": flag_event.model_dump(),
            }
        )
    items.sort(key=lambda x: x["sort_ts"], reverse=True)
    return items


def station_mini_summary(
    station: Any,
    logs: List[Any],
    *,
    awaiting_first_offload_after_swap: bool = False,
) -> Dict[str, Any]:
    """Per-station row for array overview and history analytics."""
    sorted_logs = sorted(logs, key=_offload_effective_ts, reverse=True)
    latest = sorted_logs[0] if sorted_logs else None
    last_ts = None
    last_success = None
    if latest:
        last_ts = (
            latest.offload_end_time_utc
            or latest.offload_start_time_utc
            or latest.log_timestamp_utc
        )
        last_success = latest.was_offloaded
    status_text, _ = resolve_station_status_text_and_color(
        station,
        logs,
        awaiting_first_offload_after_swap=awaiting_first_offload_after_swap,
    )
    return {
        "station_id": station.station_id,
        "serial_number": station.serial_number,
        "modem_address": station.modem_address,
        "status_text": status_text,
        "last_offload_timestamp_utc": last_ts,
        "last_log_was_offloaded": last_success,
        "log_count": len(logs),
        "field_season_year": getattr(station, "field_season_year", None),
    }


def logs_by_season_counts(logs: List[Any]) -> Dict[Optional[int], int]:
    out: Dict[Optional[int], int] = {}
    for log in logs:
        y = log.field_season_year
        out[y] = out.get(y, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: (kv[0] is None, kv[0] or 0)))


def group_stations_by_status(summaries: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    buckets: Dict[str, List[str]] = defaultdict(list)
    for s in summaries:
        buckets[s["status_text"]].append(s["station_id"])
    return dict(buckets)
