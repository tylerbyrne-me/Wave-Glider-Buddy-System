"""
Database models for error tracking and analysis
API-specific models for error analysis endpoints
"""

from datetime import datetime, timezone
from typing import Optional, List
from enum import Enum
from sqlmodel import SQLModel, Field, Column, Text, Integer, Float, Boolean
from ..core.error_types import ErrorCategory

# Use the same ErrorCategory enum for consistency
ErrorCategoryEnum = ErrorCategory

class ErrorSeverityEnum(int, Enum):
    """Error severity levels"""
    LOW = 1
    MEDIUM = 2
    HIGH = 3

class ClassifiedError(SQLModel, table=True):
    """Enhanced error tracking with classification"""
    __tablename__ = "classified_errors"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    mission_id: str = Field(index=True, description="Mission identifier (e.g., m209, m211)")
    timestamp: datetime = Field(index=True, description="When the error occurred")
    vehicle_name: str = Field(description="Vehicle that generated the error")
    original_message: str = Field(sa_column=Column(Text), description="Original error message")
    
    # Classification data
    error_category: ErrorCategoryEnum = Field(description="Classified error category")
    classification_confidence: float = Field(description="Confidence score (0.0-1.0)")
    severity_level: ErrorSeverityEnum = Field(description="Error severity level")
    category_description: str = Field(description="Human-readable category description")
    
    # Original data
    self_corrected: Optional[bool] = Field(description="Whether error self-corrected")
    
    # Metadata
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    classification_version: str = Field(default="1.0", description="Version of classification system used")

class ErrorCategoryStats(SQLModel, table=True):
    """Aggregated error statistics by category and time period"""
    __tablename__ = "error_category_stats"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    mission_id: str = Field(index=True)
    category: ErrorCategoryEnum = Field(index=True)
    time_period_start: datetime = Field(index=True)
    time_period_end: datetime = Field(index=True)
    period_type: str = Field(description="hourly, daily, weekly")
    
    # Statistics
    total_errors: int = Field(description="Total errors in this period")
    self_corrected_count: int = Field(description="Number that self-corrected")
    self_correction_rate: float = Field(description="Percentage that self-corrected")
    avg_confidence: float = Field(description="Average classification confidence")
    severity_distribution: str = Field(sa_column=Column(Text), description="JSON string of severity counts")
    
    # Metadata
    calculated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class ErrorPattern(SQLModel, table=True):
    """Stored error patterns for classification"""
    __tablename__ = "error_patterns"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    pattern_name: str = Field(unique=True, description="Human-readable pattern name")
    regex_pattern: str = Field(sa_column=Column(Text), description="Regex pattern for matching")
    category: ErrorCategoryEnum = Field(description="Category this pattern matches")
    severity: ErrorSeverityEnum = Field(description="Default severity for this pattern")
    description: str = Field(description="Description of what this pattern matches")
    confidence_threshold: float = Field(default=0.8, description="Minimum confidence for match")
    is_active: bool = Field(default=True, description="Whether pattern is currently active")
    
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

# Pydantic models for API responses
class ErrorClassificationResponse(SQLModel):
    """Response model for error classification API"""
    original_message: str
    category: ErrorCategoryEnum
    confidence: float
    description: str
    severity: ErrorSeverityEnum

class ErrorTrendData(SQLModel):
    """Data model for error trend analysis"""
    time_period: str
    category: ErrorCategoryEnum
    error_count: int
    self_correction_rate: float
    avg_confidence: float

class ErrorDashboardSummary(SQLModel):
    """Summary data for error dashboard"""
    total_errors: int
    recent_errors: int  # Last 24 hours
    category_breakdown: dict
    top_error_types: List[dict]
    self_correction_rate: float
    trend_direction: str  # "increasing", "decreasing", "stable"
