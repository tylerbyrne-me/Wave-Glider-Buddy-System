"""
Build station offload status overview rows from live registry objects + season-filtered logs.
"""

from datetime import timezone
from typing import Any, Dict, List


def _format_overview_dt(dt_val) -> str:
    if dt_val:
        if dt_val.tzinfo is None or dt_val.tzinfo.utcoffset(dt_val) is None:
            return dt_val.replace(tzinfo=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        return dt_val.strftime("%Y-%m-%d %H:%M:%S UTC")
    return "---"


def build_status_overview_row(
    station,
    relevant_logs: List[Any],
    *,
    is_flagged_for_scope: bool = False,
    flag_note: str | None = None,
) -> Dict[str, Any]:
    """
    station: ORM object with same attributes as StationMetadata / StationMetadataSeasonSnapshot
    for fields used in the overview.
    relevant_logs: pre-filtered OffloadLog rows for this station + season context
    """
    status_text = "Unknown"
    status_color_key = "grey"
    last_offload_timestamp_str = "N/A"
    latest_vrl_file_name = "---"
    latest_arrival_date_str = "---"
    latest_distance_command_sent_m_str = "---"
    latest_time_first_command_sent_utc_str = "---"
    latest_offload_start_time_utc_str = "---"
    latest_offload_end_time_utc_str = "---"
    latest_departure_date_str = "---"
    latest_was_offloaded_str = "---"
    latest_offload_notes_file_size_str = "---"
    latest_remote_health_model_id = None
    latest_remote_health_serial_number = None
    latest_remote_health_modem_address = None
    latest_remote_health_temperature_c = None
    latest_remote_health_tilt_rad = None
    latest_remote_health_humidity = None
    if relevant_logs:
        sorted_logs = sorted(
            relevant_logs,
            key=lambda log: log.log_timestamp_utc,
            reverse=True,
        )
        if sorted_logs:
            latest_log = sorted_logs[0]
            relevant_ts = (
                latest_log.offload_end_time_utc
                or latest_log.offload_start_time_utc
                or latest_log.log_timestamp_utc
            )
            if relevant_ts:
                if (
                    relevant_ts.tzinfo is None
                    or relevant_ts.tzinfo.utcoffset(relevant_ts) is None
                ):
                    relevant_ts = relevant_ts.replace(tzinfo=timezone.utc)
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
            latest_offload_notes_file_size_str = (
                latest_log.offload_notes_file_size or "---"
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
            if latest_log.was_offloaded is True:
                status_text = "Offloaded"
                status_color_key = "green"
            elif latest_log.was_offloaded is False:
                status_text = "Failed Offload"
                status_color_key = "red"
            else:
                status_text = "Awaiting Status"
                status_color_key = "grey"
        else:
            status_text = "Awaiting Offload"
            status_color_key = "grey"
    else:
        status_text = "Awaiting Offload"
        status_color_key = "grey"

    if is_flagged_for_scope:
        status_text = "Flagged - Needs Review"
        status_color_key = "orange"
    elif station.display_status_override:
        if station.display_status_override.upper() == "SKIPPED":
            status_text = "Skipped"
            status_color_key = "yellow"

    return {
        "station_id": station.station_id,
        "serial_number": station.serial_number,
        "modem_address": station.modem_address,
        "station_settings": station.station_settings or "---",
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
        "latest_offload_notes_file_size": latest_offload_notes_file_size_str,
        "remote_health_model_id": latest_remote_health_model_id,
        "remote_health_serial_number": latest_remote_health_serial_number,
        "remote_health_modem_address": latest_remote_health_modem_address,
        "remote_health_temperature_c": latest_remote_health_temperature_c,
        "remote_health_tilt_rad": latest_remote_health_tilt_rad,
        "remote_health_humidity": latest_remote_health_humidity,
    }
