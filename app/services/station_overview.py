"""
Build station offload status overview rows from live registry + season-filtered logs.

Status priority (lowest to highest): log-derived status, hardware-swap pending,
active display status override (until superseded by a newer log or season close),
season flag (Flagged).
"""

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.core.offload_comments import get_offload_comments

HARDWARE_SWAPPED_AWAITING_OFFLOAD_STATUS = "Hardware Swapped - Awaiting Offload"
DISPLAY_STATUS_OVERRIDE_OPTIONS: Tuple[Tuple[str, str], ...] = (
    ("SKIPPED", "Skipped"),
    ("OFFLOADED", "Offloaded"),
    ("FAILED_OFFLOAD", "Failed Offload"),
    (
        "HARDWARE_SWAPPED_AWAITING_OFFLOAD",
        "Hardware Swapped - Awaiting Offload",
    ),
)

_DISPLAY_STATUS_OVERRIDE_BY_KEY: Dict[str, Tuple[str, str]] = {
    "SKIPPED": ("Skipped", "yellow"),
    "OFFLOADED": ("Offloaded", "green"),
    "FAILED_OFFLOAD": ("Failed Offload", "red"),
    "HARDWARE_SWAPPED_AWAITING_OFFLOAD": (
        HARDWARE_SWAPPED_AWAITING_OFFLOAD_STATUS,
        "purple",
    ),
}


def normalize_display_status_override(raw: Optional[str]) -> Optional[str]:
    """Map stored or human-readable override text to a canonical key."""
    if raw is None or not str(raw).strip():
        return None
    normalized = (
        str(raw).strip().upper().replace("-", "_").replace(" ", "_")
    )
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    if normalized in _DISPLAY_STATUS_OVERRIDE_BY_KEY:
        return normalized
    return None


def status_from_display_override(
    raw: Optional[str],
) -> Optional[Tuple[str, str]]:
    """Return (status_text, status_color) for a display_status_override value."""
    key = normalize_display_status_override(raw)
    if key is None:
        return None
    return _DISPLAY_STATUS_OVERRIDE_BY_KEY.get(key)


def _log_effective_ts(log: Any) -> datetime:
    raw = (
        log.offload_end_time_utc
        or log.offload_start_time_utc
        or log.log_timestamp_utc
    )
    aware = _aware_utc(raw)
    if aware is not None:
        return aware
    return datetime.min.replace(tzinfo=timezone.utc)


def is_display_status_override_active(
    station: Any,
    relevant_logs: List[Any],
) -> bool:
    """
    True when a manual override should still drive the display status.

    Superseded by any season-context offload log recorded after the override
    was set (display_status_override_set_at_utc).
    """
    if status_from_display_override(
        getattr(station, "display_status_override", None)
    ) is None:
        return False
    set_at = _aware_utc(getattr(station, "display_status_override_set_at_utc", None))
    if set_at is None:
        return True
    for log in relevant_logs:
        if _log_effective_ts(log) > set_at:
            return False
    return True


def sync_display_status_override_timestamp(
    station: Any,
    *,
    previous_override: Optional[str],
) -> None:
    """Update set_at when display_status_override changes on save."""
    previous_key = normalize_display_status_override(previous_override)
    current_key = normalize_display_status_override(
        getattr(station, "display_status_override", None)
    )
    if current_key is None:
        station.display_status_override_set_at_utc = None
        return
    if current_key != previous_key:
        station.display_status_override_set_at_utc = datetime.now(timezone.utc)


def clear_display_status_override(station: Any) -> None:
    station.display_status_override = None
    station.display_status_override_set_at_utc = None


def resolve_station_status_text_and_color(
    station: Any,
    relevant_logs: List[Any],
    *,
    is_flagged_for_scope: bool = False,
    awaiting_first_offload_after_swap: bool = False,
) -> Tuple[str, str]:
    """
    Resolve the display status label and color key for a station.

    relevant_logs should already be filtered to the active season context.
    awaiting_first_offload_after_swap is computed from all logs vs latest swap.
    """
    status_text = "Awaiting Offload"
    status_color_key = "grey"

    if relevant_logs:
        sorted_logs = sorted(
            relevant_logs,
            key=lambda log: log.log_timestamp_utc,
            reverse=True,
        )
        latest_log = sorted_logs[0]
        if latest_log.was_offloaded is True:
            status_text = "Offloaded"
            status_color_key = "green"
        elif latest_log.was_offloaded is False:
            status_text = "Failed Offload"
            status_color_key = "red"
        else:
            status_text = "Awaiting Status"
            status_color_key = "grey"

    if awaiting_first_offload_after_swap:
        status_text = HARDWARE_SWAPPED_AWAITING_OFFLOAD_STATUS
        status_color_key = "purple"

    if is_display_status_override_active(station, relevant_logs):
        override_status = status_from_display_override(
            getattr(station, "display_status_override", None)
        )
        if override_status is not None:
            status_text, status_color_key = override_status

    if is_flagged_for_scope:
        status_text = "Flagged - Needs Review"
        status_color_key = "orange"

    return status_text, status_color_key


def count_stations_by_status_text(
    stations: List[Any],
    *,
    season_logs_by_station: Dict[str, List[Any]],
    all_logs_by_station: Dict[str, List[Any]],
    latest_swap_by_station: Dict[str, datetime],
    is_awaiting_first_offload_after_swap_fn: Any,
    flag_state_by_station: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Counter:
    """Count live stations by resolved display status (for analytics panels)."""
    counts: Counter = Counter()
    for station in stations:
        swap_ts = latest_swap_by_station.get(station.station_id)
        flag_state = (flag_state_by_station or {}).get(station.station_id, {})
        status_text, _ = resolve_station_status_text_and_color(
            station,
            season_logs_by_station.get(station.station_id, []),
            is_flagged_for_scope=bool(flag_state.get("is_flagged")),
            awaiting_first_offload_after_swap=is_awaiting_first_offload_after_swap_fn(
                all_logs_by_station.get(station.station_id, []),
                swap_ts,
            ),
        )
        counts[status_text] += 1
    return counts


def _format_overview_dt(dt_val) -> str:
    if dt_val:
        if dt_val.tzinfo is None or dt_val.tzinfo.utcoffset(dt_val) is None:
            return dt_val.replace(tzinfo=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        return dt_val.strftime("%Y-%m-%d %H:%M:%S UTC")
    return "---"


def _aware_utc(dt_val: Optional[datetime]) -> Optional[datetime]:
    if dt_val is None:
        return None
    if dt_val.tzinfo is None or dt_val.tzinfo.utcoffset(dt_val) is None:
        return dt_val.replace(tzinfo=timezone.utc)
    return dt_val


def build_status_overview_row(
    station,
    relevant_logs: List[Any],
    *,
    is_flagged_for_scope: bool = False,
    flag_note: str | None = None,
    awaiting_first_offload_after_swap: bool = False,
) -> Dict[str, Any]:
    """
    Build one status-table row for a station.

    Args:
        station: Live registry row (or season snapshot with the same fields).
        relevant_logs: OffloadLog rows for the selected season context only.
        awaiting_first_offload_after_swap: When True, the station has a hardware
            swap on record and no offload has occurred after that swap (any
            season). Shows purple "Hardware Swapped - Awaiting Offload" until
            the first post-swap offload is logged; later seasons then use the
            normal log-derived status.
    """
    last_offload_timestamp_str = "N/A"
    latest_vrl_file_name = "---"
    latest_arrival_date_str = "---"
    latest_distance_command_sent_m_str = "---"
    latest_time_first_command_sent_utc_str = "---"
    latest_offload_start_time_utc_str = "---"
    latest_offload_end_time_utc_str = "---"
    latest_departure_date_str = "---"
    latest_was_offloaded_str = "---"
    latest_offload_comments_str = "---"
    latest_vrl_verified_on_rudics = None
    latest_offload_log_id = None
    latest_remote_health_model_id = None
    latest_remote_health_serial_number = None
    latest_remote_health_modem_address = None
    latest_remote_health_temperature_c = None
    latest_remote_health_tilt_rad = None
    latest_remote_health_humidity = None
    latest_remote_health_report_date = None
    if relevant_logs:
        sorted_logs = sorted(
            relevant_logs,
            key=lambda log: log.log_timestamp_utc,
            reverse=True,
        )
        if sorted_logs:
            latest_log = sorted_logs[0]
            latest_offload_log_id = getattr(latest_log, "id", None)
            relevant_ts = (
                latest_log.offload_end_time_utc
                or latest_log.offload_start_time_utc
                or latest_log.log_timestamp_utc
            )
            if relevant_ts:
                relevant_ts = _aware_utc(relevant_ts)
                last_offload_timestamp_str = relevant_ts.strftime(
                    "%Y-%m-%d %H:%M:%S UTC"
                )
            if latest_log.vrl_file_name:
                latest_vrl_file_name = latest_log.vrl_file_name
            latest_arrival_date_str = _format_overview_dt(latest_log.arrival_date)
            latest_distance_command_sent_m_str = (
                str(latest_log.distance_command_sent_m)
                if latest_log.distance_command_sent_m is not None
                else "---"
            )
            latest_time_first_command_sent_utc_str = _format_overview_dt(
                latest_log.time_first_command_sent_utc
            )
            latest_offload_start_time_utc_str = _format_overview_dt(
                latest_log.offload_start_time_utc
            )
            latest_offload_end_time_utc_str = _format_overview_dt(
                latest_log.offload_end_time_utc
            )
            latest_departure_date_str = _format_overview_dt(latest_log.departure_date)
            latest_was_offloaded_str = (
                "Yes"
                if latest_log.was_offloaded is True
                else ("No" if latest_log.was_offloaded is False else "---")
            )
            merged_comments = get_offload_comments(latest_log)
            latest_offload_comments_str = merged_comments or "---"
            latest_vrl_verified_on_rudics = getattr(
                latest_log, "vrl_verified_on_rudics", None
            )
            if getattr(latest_log, "remote_health_model_id", None) is not None:
                latest_remote_health_model_id = latest_log.remote_health_model_id
            if getattr(latest_log, "remote_health_serial_number", None) is not None:
                latest_remote_health_serial_number = latest_log.remote_health_serial_number
            if getattr(latest_log, "remote_health_modem_address", None) is not None:
                latest_remote_health_modem_address = latest_log.remote_health_modem_address
            if getattr(latest_log, "remote_health_temperature_c", None) is not None:
                latest_remote_health_temperature_c = latest_log.remote_health_temperature_c
            if getattr(latest_log, "remote_health_tilt_rad", None) is not None:
                latest_remote_health_tilt_rad = latest_log.remote_health_tilt_rad
            if getattr(latest_log, "remote_health_humidity", None) is not None:
                latest_remote_health_humidity = latest_log.remote_health_humidity
            if getattr(latest_log, "remote_health_report_date", None) is not None:
                latest_remote_health_report_date = str(latest_log.remote_health_report_date)

    status_text, status_color_key = resolve_station_status_text_and_color(
        station,
        relevant_logs,
        is_flagged_for_scope=is_flagged_for_scope,
        awaiting_first_offload_after_swap=awaiting_first_offload_after_swap,
    )

    # Pre-swap VRL must not appear once a new offload is required (swap or override).
    if status_text == HARDWARE_SWAPPED_AWAITING_OFFLOAD_STATUS:
        latest_vrl_file_name = "---"

    return {
        "station_id": station.station_id,
        "serial_number": station.serial_number,
        "modem_address": station.modem_address,
        "rv_wp_number": station.waypoint_number or "---",
        "deployment_latitude": station.deployment_latitude,
        "deployment_longitude": station.deployment_longitude,
        "last_offload_timestamp_str": last_offload_timestamp_str,
        "status_text": status_text,
        "status_color": status_color_key,
        "display_status_override": station.display_status_override,
        "is_flagged_for_scope": is_flagged_for_scope,
        "flag_note": flag_note,
        "vrl_file_name": latest_vrl_file_name,
        "latest_arrival_date": latest_arrival_date_str,
        "latest_distance_command_sent_m": latest_distance_command_sent_m_str,
        "latest_time_first_command_sent_utc": latest_time_first_command_sent_utc_str,
        "latest_offload_start_time_utc": latest_offload_start_time_utc_str,
        "latest_offload_end_time_utc": latest_offload_end_time_utc_str,
        "latest_departure_date": latest_departure_date_str,
        "latest_was_offloaded": latest_was_offloaded_str,
        "latest_offload_comments": latest_offload_comments_str,
        "latest_vrl_verified_on_rudics": latest_vrl_verified_on_rudics,
        "latest_offload_log_id": latest_offload_log_id,
        "remote_health_model_id": latest_remote_health_model_id,
        "remote_health_serial_number": latest_remote_health_serial_number,
        "remote_health_modem_address": latest_remote_health_modem_address,
        "remote_health_temperature_c": latest_remote_health_temperature_c,
        "remote_health_tilt_rad": latest_remote_health_tilt_rad,
        "remote_health_humidity": latest_remote_health_humidity,
        "remote_health_report_date": latest_remote_health_report_date,
    }
