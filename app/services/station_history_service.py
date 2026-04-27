"""
Helpers for station / array history timelines and aggregates.
"""

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _aware_ts(dt: Optional[datetime]) -> datetime:
    if dt is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _offload_effective_ts(log: Any) -> datetime:
    return _aware_ts(
        log.offload_end_time_utc
        or log.offload_start_time_utc
        or log.log_timestamp_utc
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
                "payload": log.model_dump(),
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


def station_mini_summary(station: Any, logs: List[Any]) -> Dict[str, Any]:
    """Per-station row for array overview."""
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
    status_text = "Unknown"
    if (
        station.display_status_override
        and str(station.display_status_override).upper() == "SKIPPED"
    ):
        status_text = "Skipped"
    elif station.was_last_offload_successful is True:
        status_text = "Offloaded"
    elif station.was_last_offload_successful is False:
        status_text = "Failed Offload"
    elif station.last_offload_timestamp_utc is None:
        status_text = "Awaiting Offload"
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
