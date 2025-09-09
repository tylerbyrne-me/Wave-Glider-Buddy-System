"""
Error types and data structures for classification
"""

from dataclasses import dataclass
from enum import Enum

class ErrorCategory(Enum):
    NAVIGATION = "navigation"
    COMMUNICATION = "communication" 
    SYSTEM_OPS = "system_operations"
    ENVIRONMENTAL = "environmental"
    UNKNOWN = "unknown"

@dataclass
class ErrorPattern:
    """Defines a pattern for matching error messages"""
    pattern: str
    category: ErrorCategory
    severity: int = 1  # 1=low, 2=medium, 3=high
    description: str = ""
    confidence_threshold: float = 0.1
