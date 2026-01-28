"""
Enum definitions for the Wave Glider Buddy System.
"""

from enum import Enum


class ReportTypeEnum(str, Enum):
    power = "power"
    ctd = "ctd"
    weather = "weather"
    waves = "waves"
    telemetry = "telemetry"
    ais = "ais"
    errors = "errors"
    vr2c = "vr2c"
    fluorometer = "fluorometer"
    solar = "solar"
    wg_vm4 = "wg_vm4"  # New WG-VM4 sensor
    wg_vm4_info = "wg_vm4_info"  # WG-VM4 info data for automatic offload logging
    wg_vm4_remote_health = "wg_vm4_remote_health"  # VM4 remote health at connection


class SourceEnum(str, Enum):
    local = "local"
    remote = "remote"


class UserRoleEnum(str, Enum):
    admin = "admin"
    pilot = "pilot"


class FormItemTypeEnum(str, Enum):
    CHECKBOX = "checkbox"
    TEXT_INPUT = "text_input"
    TEXT_AREA = "text_area"
    AUTOFILLED_VALUE = "autofilled_value"
    # For values auto-populated from mission data
    STATIC_TEXT = "static_text"  # For instructions or non-interactive text
    DROPDOWN = "dropdown"  # New type for dropdown lists
    DATETIME_LOCAL = "datetime-local"  # For datetime-local input


class PayPeriodStatusEnum(str, Enum):
    OPEN = "open"
    CLOSED = "closed"


class TimesheetStatusEnum(str, Enum):
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"


class JobStatusEnum(str, Enum):
    OK = "ok"
    OVERDUE = "overdue"

