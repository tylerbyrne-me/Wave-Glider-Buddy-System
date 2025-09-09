"""
Error pattern definitions for classification
Separated from main classification logic for better maintainability
"""

from ..core.error_types import ErrorCategory, ErrorPattern

# Pattern definitions organized by category
NAVIGATION_PATTERNS = [
    ErrorPattern(
        pattern=r"(?i)(gps|ais|gpsais).*(fail|error|timeout|lost|disconnect|monitor|fix)",
        category=ErrorCategory.NAVIGATION,
        severity=2,
        description="GPS/AIS positioning system issues"
    ),
    ErrorPattern(
        pattern=r"(?i)(out of bounds|went too far|path warning)",
        category=ErrorCategory.NAVIGATION,
        severity=2,
        description="Navigation boundary or path issues"
    ),
    ErrorPattern(
        pattern=r"(?i)(gpsublox|gps.*ublox)",
        category=ErrorCategory.NAVIGATION,
        severity=2,
        description="GPS Ublox system issues"
    ),
    ErrorPattern(
        pattern=r"(?i)(proximity.*alarm|proximity.*warning)",
        category=ErrorCategory.NAVIGATION,
        severity=2,
        description="Navigation proximity alarm system"
    ),
    ErrorPattern(
        pattern=r"(?i)avoiding",
        category=ErrorCategory.NAVIGATION,
        severity=2,
        description="Navigation collision avoidance system"
    ),
    ErrorPattern(
        pattern=r"(?i)(path.*alarm|path.*warning)",
        category=ErrorCategory.NAVIGATION,
        severity=2,
        description="Navigation path alarm system"
    ),
]

COMMUNICATION_PATTERNS = [
    ErrorPattern(
        pattern=r"(?i)(iridium.*modem|iridium.*fail|iridium.*error)",
        category=ErrorCategory.COMMUNICATION,
        severity=2,
        description="Iridium satellite communication issues"
    ),
    ErrorPattern(
        pattern=r"(?i)(received.*nack|nack.*received)",
        category=ErrorCategory.COMMUNICATION,
        severity=2,
        description="Communication NACK errors"
    ),
    ErrorPattern(
        pattern=r"(?i)(repeating.*telemetry|telemetry.*repeat)",
        category=ErrorCategory.COMMUNICATION,
        severity=1,
        description="Telemetry communication issues"
    ),
]

SYSTEM_OPS_PATTERNS = [
    ErrorPattern(
        pattern=r"(?i)(command.*fail|command.*error)",
        category=ErrorCategory.SYSTEM_OPS,
        severity=2,
        description="Command execution failures"
    ),
    ErrorPattern(
        pattern=r"(?i)(vehicle.*report.*timeout|report.*timeout)",
        category=ErrorCategory.SYSTEM_OPS,
        severity=2,
        description="Vehicle reporting timeout"
    ),
    ErrorPattern(
        pattern=r"(?i)(file.*read.*timeout|read.*timeout)",
        category=ErrorCategory.SYSTEM_OPS,
        severity=2,
        description="File system timeout errors"
    ),
    ErrorPattern(
        pattern=r"(?i)(power.*cycling|power.*cycle)",
        category=ErrorCategory.SYSTEM_OPS,
        severity=2,
        description="Power management issues"
    ),
]

ENVIRONMENTAL_PATTERNS = [
    ErrorPattern(
        pattern=r"(?i)(ocean.*current.*speed|current.*speed)",
        category=ErrorCategory.ENVIRONMENTAL,
        severity=1,
        description="Ocean current speed monitoring"
    ),
]

# Combine all patterns
ALL_PATTERNS = (
    NAVIGATION_PATTERNS + 
    COMMUNICATION_PATTERNS + 
    SYSTEM_OPS_PATTERNS + 
    ENVIRONMENTAL_PATTERNS
)
