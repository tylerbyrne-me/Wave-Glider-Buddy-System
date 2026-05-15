"""
C3 fluorometer channel metadata from Sensor Tracker.

Wave Glider CSV columns (C1_Avg, C2_Avg, C3_Avg) are fixed; this module maps them to
Sensor Tracker parameter long names and short display aliases (CDOM, Backscatter, Chl-a).

Sensor Tracker instrument identity (science computer):
  - identifier: Fluorometer Samples 2
  - short_name: fluorometers
  - long_name: Turner Designs C3 submersible fluorometer

Parameters are fetched by exact identifier (e.g. Fluorometer Samples 2_c1Avg) with depth>=3.
The ST parameter API does not support instrument= or sensor= list filters. Rows are matched
by instrument.id and instrument.serial when multiple configuration histories exist.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TypedDict

DEFAULT_FILE_STEM = "Fluorometer Samples 2"

FLUOROMETER_INSTRUMENT_IDENTIFIER = "Fluorometer Samples 2"
FLUOROMETER_INSTRUMENT_SHORT_NAME = "fluorometers"
FLUOROMETER_INSTRUMENT_LONG_NAME = "turner designs c3 submersible fluorometer"

_SUFFIX_TO_COLUMN: Dict[str, str] = {
    "c1Avg": "C1_Avg",
    "c2Avg": "C2_Avg",
    "c3Avg": "C3_Avg",
    "temp": "Temperature_Fluor",
}

DEFAULT_CHANNEL_LABELS: Dict[str, str] = {
    "C1_Avg": "C1 Avg",
    "C2_Avg": "C2 Avg",
    "C3_Avg": "C3 Avg",
    "Temperature_Fluor": "Temperature",
}


class ChannelLabel(TypedDict):
    text: str
    subscript: Optional[str]


def default_file_stem() -> str:
    return DEFAULT_FILE_STEM


def is_fluorometer_card_enabled(
    mission_overview: Any,
    *,
    enabled_cards: Optional[List[str]] = None,
) -> bool:
    """Return True when the mission overview enables the fluorometer sensor card."""
    if enabled_cards is not None:
        normalized = {str(c).strip().lower() for c in enabled_cards}
        return "fluorometer" in normalized

    if mission_overview is None:
        return False

    raw = getattr(mission_overview, "enabled_sensor_cards", None)
    if not raw:
        return False

    try:
        cards = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return False

    if not isinstance(cards, list):
        return False

    return "fluorometer" in {str(c).strip().lower() for c in cards}


def resolve_fluorometer_alias(long_name: Optional[str]) -> Optional[str]:
    """Map ST parameter long_name to a short plot label (subscript)."""
    if not long_name:
        return None

    normalized = long_name.lower()
    if "coloured dissolved" in normalized or "colored dissolved" in normalized:
        return "CDOM"
    if "side scattering" in normalized or "turbidity" in normalized:
        return "Backscatter"
    if "chlorophyll-a fluorometer" in normalized or "chlorophyll a fluorometer" in normalized:
        return "Chl-a"
    if "temperature" in normalized and "fluorometer" in normalized:
        return "Temp"
    return None


def build_fluorometer_channel_map(
    parameters: List[Dict[str, Any]],
    *,
    file_stem: Optional[str] = None,
    sensor_serial: Optional[str] = None,
    sensor_tracker_sensor_id: Optional[int] = None,
    instrument_identifier: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Build per-mission channel map from ST parameter rows.

    ``sensor_tracker_sensor_id`` stores the Sensor Tracker instrument id (historical field name).

    Returns None if no Fluorometer Samples 2_* parameters are present.
    """
    stem = file_stem or default_file_stem()
    prefix = f"{stem}_"
    channels: Dict[str, Dict[str, Any]] = {}

    for param in parameters:
        identifier = param.get("identifier") or ""
        if not identifier.startswith(prefix):
            continue

        suffix = identifier[len(prefix) :]
        column_key = _SUFFIX_TO_COLUMN.get(suffix)
        if not column_key:
            continue

        long_name = param.get("long_name")
        channels[column_key] = {
            "st_parameter_id": param.get("id"),
            "identifier": identifier,
            "long_name": long_name,
            "units": param.get("units"),
            "alias": resolve_fluorometer_alias(long_name),
        }

    if not channels:
        return None

    return {
        "source_file_stem": stem,
        "sensor_serial": sensor_serial,
        "sensor_tracker_sensor_id": sensor_tracker_sensor_id,
        "instrument_identifier": instrument_identifier,
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "channels": channels,
    }


def is_fluorometer_instrument(inst: Dict[str, Any]) -> bool:
    """True when parsed instrument metadata matches the Turner C3 fluorometer."""
    identifier = (inst.get("instrument_identifier") or "").strip().lower()
    short_name = (inst.get("instrument_short_name") or "").strip().lower()
    long_name = (inst.get("instrument_long_name") or "").strip().lower()

    if identifier == FLUOROMETER_INSTRUMENT_IDENTIFIER.lower():
        return True
    if short_name == FLUOROMETER_INSTRUMENT_SHORT_NAME:
        return True
    if FLUOROMETER_INSTRUMENT_LONG_NAME in long_name:
        return True
    if identifier in ("c3", "c3-fluorometer"):
        return True
    return False


def parameters_include_fluorometer_channels(parameters: List[Dict[str, Any]]) -> bool:
    prefix = f"{DEFAULT_FILE_STEM}_"
    return any((p.get("identifier") or "").startswith(prefix) for p in parameters)


def fluorometer_parameter_identifiers(file_stem: Optional[str] = None) -> List[str]:
    """ST parameter identifiers for each fluorometer CSV channel suffix."""
    stem = file_stem or default_file_stem()
    return [f"{stem}_{suffix}" for suffix in _SUFFIX_TO_COLUMN]


def _parameter_instrument_id(param: Dict[str, Any]) -> Optional[int]:
    instrument = param.get("instrument")
    if isinstance(instrument, dict):
        value = instrument.get("id")
        return int(value) if value is not None else None
    if isinstance(instrument, int):
        return instrument
    return None


def _parameter_instrument_serial(param: Dict[str, Any]) -> Optional[str]:
    instrument = param.get("instrument")
    if isinstance(instrument, dict):
        serial = instrument.get("serial")
        return str(serial).strip() if serial else None
    return None


def pick_latest_parameters_for_instrument(
    parameters: List[Dict[str, Any]],
    instrument_id: int,
    *,
    instrument_serial: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    When multiple ST rows share an identifier (reconfiguration history), keep the row
    for this instrument (and serial when provided) with the newest modified_date.
    """
    if not parameters or not instrument_id:
        return []

    matched = [p for p in parameters if _parameter_instrument_id(p) == instrument_id]
    if instrument_serial:
        serial_norm = instrument_serial.strip()
        serial_matches = [
            p for p in matched if _parameter_instrument_serial(p) == serial_norm
        ]
        if serial_matches:
            matched = serial_matches

    if not matched:
        return []

    return [max(matched, key=lambda p: str(p.get("modified_date") or ""))]


def find_fluorometer_instrument(parsed_deployment: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Locate the Turner C3 fluorometer on the science data logger.

    Channel parameters are tied to the instrument record (serial on instrument), not to
    ancillary sensors such as the SBE pump listed on the same instrument in ST.
    """
    for logger_data in parsed_deployment.get("data_loggers", []) or []:
        logger_type = (logger_data.get("logger_type") or "").lower()
        if logger_type and logger_type != "science":
            continue

        for inst in logger_data.get("instruments", []) or []:
            if not is_fluorometer_instrument(inst):
                continue

            return {
                "instrument_id": inst.get("instrument_id"),
                "instrument_identifier": inst.get("instrument_identifier"),
                "instrument_short_name": inst.get("instrument_short_name"),
                "instrument_long_name": inst.get("instrument_long_name"),
                "instrument_serial": inst.get("instrument_serial"),
                "data_logger_type": logger_type or "science",
            }

    return None


def format_channel_label(
    column_key: str,
    channel_map: Optional[Dict[str, Any]],
) -> ChannelLabel:
    """Display label for a CSV column; subscript is the alias when channel_map is set."""
    text = DEFAULT_CHANNEL_LABELS.get(column_key, column_key.replace("_", " "))
    if not channel_map:
        return {"text": text, "subscript": None}

    channels = channel_map.get("channels") or {}
    entry = channels.get(column_key) or {}
    alias = entry.get("alias")
    if not alias:
        return {"text": text, "subscript": None}

    return {"text": text, "subscript": alias}


def build_channel_labels_for_display(
    channel_map: Optional[Dict[str, Any]],
) -> Dict[str, ChannelLabel]:
    return {
        column_key: format_channel_label(column_key, channel_map)
        for column_key in DEFAULT_CHANNEL_LABELS
    }


def format_channel_label_matplotlib(
    column_key: str,
    channel_map: Optional[Dict[str, Any]],
) -> str:
    label = format_channel_label(column_key, channel_map)
    subscript = label.get("subscript")
    if not subscript:
        return label["text"]

    safe = subscript.replace("-", r"\text{-}")
    return rf"{label['text']}$_{{\mathrm{{{safe}}}}}$"


def channel_y_axis_label(column_key: str, channel_map: Optional[Dict[str, Any]]) -> str:
    if channel_map:
        channels = channel_map.get("channels") or {}
        units = (channels.get(column_key) or {}).get("units")
        if units and str(units).strip():
            return str(units).strip()
    return "RFU"
