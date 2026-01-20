"""
Pydantic request/response model schemas for the Wave Glider Buddy System.
"""

from datetime import datetime, date
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator
from sqlmodel import SQLModel

from .enums import (
    SourceEnum,
    UserRoleEnum,
    FormItemTypeEnum,
    PayPeriodStatusEnum,
    TimesheetStatusEnum,
    JobStatusEnum,
)
from .database import (
    OffloadLog,
    MissionOverview,
    MissionGoal,
    MissionNote,
    SensorTrackerDeployment,
    MissionInstrument,
    MissionMedia,
)


# ============================================================================
# Report/Data Parameter Models
# ============================================================================

class ReportDataParams(BaseModel):
    """Query parameters for report data requests."""
    # Path parameters are handled by FastAPI directly in the function signature
    # Query parameters:
    hours_back: int = Field(72, gt=0, le=8760, description="Number of hours of data to retrieve, relative to the latest data point for the mission.")
    granularity_minutes: Optional[int] = Field(15, ge=5, le=60, description="Data resampling interval in minutes for charts. Minimum 5, maximum 60.")
    source: Optional[SourceEnum] = Field(None, description="Preferred data source: 'local' or 'remote'. Defaults to remote then local.")
    local_path: Optional[str] = Field(None, description="Custom base path for local data, overrides default settings path.")
    refresh: bool = Field(False, description="Force refresh data from source, bypassing cache.")
    start_date: Optional[datetime] = Field(None, description="Start date and time for data filtering (ISO 8601 format). If provided, overrides hours_back.")
    end_date: Optional[datetime] = Field(None, description="End date and time for data filtering (ISO 8601 format). If provided, overrides hours_back.")

    @field_validator("local_path")
    def local_path_rules(cls, v, values):
        # If source is 'local' and local_path is provided, it should not be
        # empty. This is a soft validation as the main logic handles default
        # paths. More complex validation (e.g. path existence) is better
        # handled in the endpoint logic.
        if (
            values.data.get("source") == SourceEnum.local
            and v is not None
            and not v.strip()
        ):
            raise ValueError(
                "local_path cannot be empty if provided and source is 'local'"
            )
        return v

    @field_validator("end_date")
    def validate_date_range(cls, v, values):
        # If start_date is provided, end_date must also be provided
        start_date = values.data.get("start_date")
        if start_date is not None and v is None:
            raise ValueError("end_date must be provided when start_date is specified")
        if v is not None and start_date is None:
            raise ValueError("start_date must be provided when end_date is specified")
        
        # If both dates are provided, start_date must be before end_date
        if start_date is not None and v is not None:
            if start_date >= v:
                raise ValueError("start_date must be before end_date")
        
        return v


class ForecastParams(BaseModel):
    """Query parameters for forecast requests."""
    # Path parameters are handled by FastAPI directly
    # Query parameters:
    lat: Optional[float] = Field(None, ge=-90, le=90, description="Latitude for the forecast. If not provided, attempts to infer from telemetry.")
    lon: Optional[float] = Field(None, ge=-180, le=180, description="Longitude for the forecast. If not provided, attempts to infer from telemetry.")
    source: Optional[SourceEnum] = Field(None, description="Preferred source for telemetry lookup if lat/lon are inferred.")
    local_path: Optional[str] = Field(None, description="Custom local path for telemetry lookup if lat/lon are inferred.")
    refresh: bool = Field(False, description="Force refresh of telemetry data if used for lat/lon inference.")
    force_marine: Optional[bool] = Field(False, description="Legacy or specific flag, currently not used by primary forecast endpoints.")
    is_historical: bool = Field(False, description="Whether this is a historical mission. Forecasts are not provided for historical missions.")

    @field_validator("local_path")
    def forecast_local_path_rules(cls, v, values):
        if (
            values.data.get("source") == SourceEnum.local
            and v is not None
            and not v.strip()
        ):
            raise ValueError(
                "local_path cannot be empty if provided and source is 'local' "
                "for telemetry lookup"
            )
        return v

    @field_validator("lon")
    def check_lon_with_lat(cls, v, values):
        # If one of lat/lon is provided, the other should also be (or neither for telemetry lookup)
        lat_val = values.data.get("lat")

        if (lat_val is not None and v is None) or (lat_val is None and v is not None):
            raise ValueError(
                "If 'lat' is provided, 'lon' must also be provided, and vice-versa."
            )
        return v


class ReportGenerationOptions(BaseModel):
    """Options for report generation."""
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    plots_to_include: List[str] = Field(default_factory=lambda: ["telemetry", "power"])
    save_to_overview: bool = Field(default=True, description="If true, saves the generated report URL to the mission overview.")
    custom_filename: Optional[str] = Field(default=None, max_length=100, description="A custom name for the report file, used when not saving to overview.")


# ============================================================================
# User Models
# ============================================================================

class UserBase(BaseModel):
    """Base user model."""
    username: str = Field(description="Unique username for the user.")
    email: Optional[str] = Field(None, description="Email address of the user.")
    full_name: Optional[str] = Field(None, description="Full name of the user.")
    color: Optional[str] = Field(default=None, description="User's assigned color for UI elements like schedule shifts.")
    role: UserRoleEnum = Field(UserRoleEnum.pilot, description="Role of the user, determines access permissions.")


class UserCreate(UserBase):
    """Model for creating a new user."""
    password: str = Field(description="User's password (will be hashed).")


class User(UserBase):
    """User response model."""
    id: int
    disabled: Optional[bool] = Field(None, description="Whether the user account is disabled.")


class UserUpdateForAdmin(BaseModel):
    """Model for admin updates to user."""
    full_name: Optional[str] = None
    email: Optional[str] = Field(None, description="New email for the user. Must be unique if changed.")
    role: Optional[UserRoleEnum] = Field(None, description="New role for the user.")
    disabled: Optional[bool] = Field(None, description="New disabled status for the user account.")


class PasswordUpdate(BaseModel):
    """Model for password change."""
    new_password: str = Field(description="The new password for the user.")


class Token(BaseModel):
    """Authentication token model."""
    access_token: str
    token_type: str


# ============================================================================
# Station Metadata Models
# ============================================================================

class StationMetadataCore(BaseModel):
    """Core station metadata fields."""
    serial_number: Optional[str] = Field(None, description="Serial number of the station hardware.")
    modem_address: Optional[int] = Field(None, description="Modem address of the station.")
    bottom_depth_m: Optional[float] = Field(None, description="Bottom depth at the station location in meters.")
    waypoint_number: Optional[str] = Field(None, description="Associated waypoint number or identifier.")
    last_offload_by_glider: Optional[str] = Field(None, description="Identifier of the glider that last performed an offload (e.g., mission ID).")
    station_settings: Optional[str] = Field(None, description="Configuration settings for the station (e.g., '300bps, 0db').")
    deployment_latitude: Optional[float] = Field(None, ge=-90, le=90, description="Latitude of the station deployment location in decimal degrees.")
    deployment_longitude: Optional[float] = Field(None, ge=-180, le=180, description="Longitude of the station deployment location in decimal degrees.")
    notes: Optional[str] = Field(None, description="General notes or comments about the station.")
    display_status_override: Optional[str] = Field(
        None, description="Manual override for the station's display status (e.g., 'SKIPPED', 'MAINTENANCE')."
    )


class StationMetadataBase(StationMetadataCore):
    """Base station metadata model."""
    station_id: str = Field(..., description="Unique Station Identifier (e.g., CBS001). This is the primary key.")
    # Fields to be updated by the latest offload log or direct edit
    last_offload_timestamp_utc: Optional[datetime] = Field(
        default=None,
        description="Timestamp of the last successful offload completion or log entry in UTC",
    )
    was_last_offload_successful: Optional[bool] = Field(
        default=None,
        description="Outcome of the last offload attempt"
    )


class StationMetadataCreate(StationMetadataBase):
    """Model for creating station metadata."""
    pass


class StationMetadataUpdate(SQLModel):
    """Model for partial updates of station metadata."""
    serial_number: Optional[str] = None
    modem_address: Optional[int] = None
    bottom_depth_m: Optional[float] = None
    waypoint_number: Optional[str] = None
    last_offload_by_glider: Optional[str] = None
    station_settings: Optional[str] = None
    deployment_latitude: Optional[float] = None
    deployment_longitude: Optional[float] = None
    notes: Optional[str] = None
    display_status_override: Optional[str] = None
    # last_offload_timestamp_utc and was_last_offload_successful are
    # typically updated via OffloadLog


class StationMetadataRead(StationMetadataBase):
    """Model for reading station metadata."""
    pass  # All fields from StationMetadataBase are included


class StationMetadataReadWithLogs(StationMetadataRead):
    """Station metadata with offload logs."""
    offload_logs: List[OffloadLog] = []


class StationMetadataCreateResponse(StationMetadataRead):
    """Response model for create/update endpoint."""
    is_created: bool


# ============================================================================
# Offload Log Models
# ============================================================================

class OffloadLogCreate(SQLModel):
    """Model for creating an offload log."""
    arrival_date: Optional[datetime] = None
    distance_command_sent_m: Optional[float] = None
    time_first_command_sent_utc: Optional[datetime] = None
    offload_start_time_utc: Optional[datetime] = None
    offload_end_time_utc: Optional[datetime] = None
    departure_date: Optional[datetime] = None
    was_offloaded: Optional[bool] = None
    vrl_file_name: Optional[str] = None
    offload_notes_file_size: Optional[str] = None


class OffloadLogRead(SQLModel):
    """Model for reading an offload log."""
    id: int
    station_id: str
    logged_by_username: str
    log_timestamp_utc: datetime
    arrival_date: Optional[datetime] = None
    distance_command_sent_m: Optional[float] = None
    time_first_command_sent_utc: Optional[datetime] = None
    offload_start_time_utc: Optional[datetime] = None
    offload_end_time_utc: Optional[datetime] = None
    departure_date: Optional[datetime] = None
    was_offloaded: Optional[bool] = None
    vrl_file_name: Optional[str] = None
    offload_notes_file_size: Optional[str] = None


# ============================================================================
# Form Models
# ============================================================================

class FormItem(BaseModel):
    """Form item model."""
    id: str = Field(description="Unique identifier for the form item within its section.")
    label: str = Field(description="Display label for the form item.")
    item_type: FormItemTypeEnum = Field(description="The type of form input element.")
    value: Optional[str] = Field(None, description="The value of the form item (for text, autofill, selected dropdown value).")
    is_verified: Optional[bool] = Field(None, description="Verification status, typically for a secondary check.")
    is_checked: Optional[bool] = Field(None, description="Checked status for checkbox items.")
    comment: Optional[str] = Field(None, description="Optional user comment for this item.")
    required: bool = Field(False, description="Whether this form item is mandatory.")
    options: Optional[List[str]] = Field(None, description="List of options for dropdown type items.")
    placeholder: Optional[str] = Field(None, description="Placeholder text for input fields.")


class FormSection(BaseModel):
    """Form section model."""
    id: str = Field(description="Unique identifier for the form section.")
    title: str = Field(description="Display title for the section.")
    items: List[FormItem] = Field(description="List of form items within this section.")
    section_comment: Optional[str] = Field(None, description="Optional comment for the entire section.")


class MissionFormSchema(BaseModel):
    """Defines the structure/template of a form."""
    form_type: str = Field(description="Identifier for the type of form (e.g., 'pre_deployment_checklist').")
    title: str = Field(description="Display title of the form.")
    description: Optional[str] = Field(None, description="Optional description of the form's purpose.")
    sections: List[FormSection] = Field(description="List of sections that make up the form.")


class MissionFormDataCreate(BaseModel):
    """Payload for submitting form data."""
    mission_id: str = Field(description="Identifier of the mission this form pertains to.")
    form_type: str = Field(description="Type of the form being submitted.")
    form_title: str = Field(description="Title of this specific form instance (can be same as schema title or customized).")
    sections_data: List[FormSection] = Field(description="The actual filled-out data, structured by sections and items.")


class MissionFormDataResponse(MissionFormDataCreate):
    """Response model for submitted form data."""
    submitted_by_username: str
    submission_timestamp: datetime


# ============================================================================
# Schedule Event Models
# ============================================================================

class ScheduleEvent(SQLModel):
    """Schedule event model."""
    id: str
    text: str
    start: datetime
    end: datetime
    resource: str
    backColor: Optional[str] = None
    type: str = "shift"  # Add a type field, default to "shift"
    user_role: Optional[UserRoleEnum] = None  # Add user role for styling unavailability
    user_color: Optional[str] = None  # Add user color for styling unavailability
    editable: bool = True  # Add editable flag for frontend
    startEditable: bool = True
    durationEditable: bool = True
    resourceEditable: bool = True
    overlap: bool = False  # Shifts should not overlap with other shifts or unavailability
    display: str = "auto"  # 'auto' for shifts, 'background' for unavailability
    groupId: Optional[str] = None  # For grouping events visually (e.g., consecutive LRI blocks)
    allDay: bool = False  # Add allDay property
    
    # Enhanced consecutive shift support
    consecutive_shifts: Optional[int] = 0  # Number of consecutive shifts
    is_first_in_sequence: Optional[bool] = True  # Is this the first shift in a sequence
    is_last_in_sequence: Optional[bool] = True   # Is this the last shift in a sequence
    total_sequence_length: Optional[int] = 1     # Total length of the shift sequence


class ScheduleEventCreate(BaseModel):
    """Model for creating schedule events."""
    start: str  # Expect ISO string from client
    end: str    # Expect ISO string from client
    resource: str
    text: Optional[str] = None   # Text is now optional, will be filled by backend
    id: Optional[str] = None  # Client might send an ID, or backend generates


class LRIBlockCreate(BaseModel):
    """Model for creating LRI blocks."""
    start_date: date  # Expect YYYY-MM-DD from client
    end_date: date    # Expect YYYY-MM-DD from client
    reason: Optional[str] = None  # Optional reason for the block


class UserUnavailabilityBase(SQLModel):
    """Base model for user unavailability."""
    start_time_utc: datetime
    end_time_utc: datetime
    reason: Optional[str] = None


class UserUnavailabilityCreate(BaseModel):
    """Model for creating user unavailability."""
    start_time_utc: datetime
    end_time_utc: datetime
    reason: Optional[str] = None


class UserUnavailabilityResponse(BaseModel):
    """Response model for user unavailability."""
    id: int
    user_id: int
    start_time_utc: datetime
    end_time_utc: datetime
    reason: Optional[str] = None
    username: str  # For frontend display
    user_role: UserRoleEnum  # For frontend coloring
    user_color: str  # For frontend coloring
    created_at_utc: datetime


# ============================================================================
# PIC Handoff Model
# ============================================================================

class PicHandoffLinkInfo(BaseModel):
    """Model for PIC handoff link information."""
    form_db_id: int  # The database ID of the SubmittedForm
    mission_id: str
    form_title: str  # Should typically be "PIC Handoff Checklist" or similar
    submitted_by_username: str
    submission_timestamp: datetime


# ============================================================================
# Pay Period and Timesheet Models
# ============================================================================

class PayPeriodCreate(BaseModel):
    """Model for creating a pay period."""
    name: str
    start_date: date
    end_date: date


class PayPeriodUpdate(SQLModel):
    """Model for updating a pay period."""
    name: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    status: Optional[PayPeriodStatusEnum] = None


class MonthlyChartData(BaseModel):
    """Model for monthly chart data."""
    pilot_name: str
    total_hours: float


class TimesheetCreate(BaseModel):
    """Model for creating a timesheet."""
    pay_period_id: int
    calculated_hours: float
    notes: Optional[str] = None


class TimesheetUpdate(BaseModel):
    """Model for updating a timesheet."""
    status: Optional[TimesheetStatusEnum] = None
    adjusted_hours: Optional[float] = None
    reviewer_notes: Optional[str] = None


class TimesheetStatusForUser(BaseModel):
    """Model for timesheet status for a user."""
    pay_period_name: str
    status: TimesheetStatusEnum
    reviewer_notes: Optional[str] = None
    submission_timestamp: datetime


class TimesheetRead(BaseModel):
    """Model for reading a timesheet."""
    id: int
    user_id: int
    username: str  # For display
    pay_period_id: int
    pay_period_name: str  # For display
    calculated_hours: float
    adjusted_hours: Optional[float]
    notes: Optional[str]
    reviewer_notes: Optional[str]  # For display
    status: TimesheetStatusEnum
    submission_timestamp: datetime
    is_active: bool


# ============================================================================
# Mission Info Models
# ============================================================================

class MissionOverviewUpdate(BaseModel):
    """Model for updating mission overview."""
    document_url: Optional[str] = None
    comments: Optional[str] = None
    weekly_report_url: Optional[str] = None
    end_of_mission_report_url: Optional[str] = None
    enabled_sensor_cards: Optional[str] = None


class MissionGoalCreate(BaseModel):
    """Model for creating a mission goal."""
    description: str


class MissionGoalUpdate(BaseModel):
    """Model for updating a mission goal."""
    is_completed: bool
    description: Optional[str] = None


class MissionNoteCreate(BaseModel):
    """Model for creating a mission note."""
    content: str


class MissionMediaUpdate(BaseModel):
    """Model for updating mission media metadata."""
    caption: Optional[str] = None
    operation_type: Optional[str] = None
    display_order: Optional[int] = None
    is_featured: Optional[bool] = None


class MissionMediaRead(BaseModel):
    """Model for reading mission media."""
    id: int
    mission_id: str
    media_type: str
    file_name: str
    file_size: int
    mime_type: str
    caption: Optional[str] = None
    operation_type: Optional[str] = None
    uploaded_by_username: str
    uploaded_at_utc: datetime
    approval_status: str
    approved_by_username: Optional[str] = None
    approved_at_utc: Optional[datetime] = None
    thumbnail_url: Optional[str] = None
    file_url: str
    display_order: int
    is_featured: bool

    class Config:
        from_attributes = True


class MissionInfoResponse(BaseModel):
    """Response model for mission info."""
    overview: Optional[MissionOverview] = None
    goals: List[MissionGoal] = []
    notes: List[MissionNote] = []
    sensor_tracker_deployment: Optional["SensorTrackerDeployment"] = None  # Sensor Tracker metadata
    sensor_tracker_instruments: List["MissionInstrument"] = []  # Sensor Tracker instruments
    media: List["MissionMediaRead"] = []


# ============================================================================
# Announcement Models
# ============================================================================

class AnnouncementCreate(SQLModel):
    """Model for creating an announcement."""
    content: str
    announcement_type: Optional[str] = "general"


class AnnouncementRead(SQLModel):
    """Model for reading an announcement."""
    id: int
    content: str
    created_by_username: str
    created_at_utc: datetime
    is_active: bool
    announcement_type: Optional[str] = "general"


class AnnouncementReadForUser(AnnouncementRead):
    """Model for reading an announcement with user-specific info."""
    is_acknowledged_by_user: bool = False


class AcknowledgedByInfo(SQLModel):
    """Model for acknowledgement information."""
    username: str
    acknowledged_at_utc: datetime


class AnnouncementReadWithAcks(AnnouncementRead):
    """Model for reading an announcement with acknowledgements."""
    acknowledged_by: List[AcknowledgedByInfo] = []


# ============================================================================
# Home Page Panel Models
# ============================================================================

class UpcomingShift(SQLModel):
    """Model for upcoming shift information."""
    mission_id: str
    start_time_utc: datetime
    end_time_utc: datetime


class MyTimesheetStatus(SQLModel):
    """Model for user's timesheet status."""
    current_period_status: str
    hours_this_period: float


class MissionGoalToggle(BaseModel):
    """Model for toggling mission goal completion."""
    is_completed: bool


class JobTriggerInfo(BaseModel):
    """Model for job trigger information."""
    type: str
    details: str


class ScheduledJob(BaseModel):
    """Model for scheduled job information."""
    id: str
    name: str
    func_ref: str
    trigger: JobTriggerInfo
    next_run_time: Optional[datetime] = None
    status: JobStatusEnum = Field(description="The current health status of the job.")


# ============================================================================
# Knowledge Base Models
# ============================================================================

class KnowledgeDocumentCreate(BaseModel):
    """Model for creating a knowledge document."""
    title: str
    description: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[str] = None
    access_level: str = Field(default="pilot", description="Access level: public, pilot, admin")


class KnowledgeDocumentUpdate(BaseModel):
    """Model for updating a knowledge document."""
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[str] = None
    access_level: Optional[str] = None
    
    class Config:
        from_attributes = True


class KnowledgeDocumentRead(BaseModel):
    """Model for reading a knowledge document."""
    id: int
    title: str
    description: Optional[str] = None
    file_name: str
    file_type: str
    file_size: int
    category: Optional[str] = None
    tags: Optional[str] = None
    access_level: str
    file_url: str
    uploaded_by_username: str
    uploaded_at_utc: datetime
    updated_at_utc: datetime
    version: int
    
    class Config:
        from_attributes = True


class KnowledgeDocumentUploadResponse(BaseModel):
    """Response model for document upload."""
    id: int
    title: str
    file_url: str
    message: str


# ============================================================================
# User Notes Models
# ============================================================================

class UserNoteCreate(BaseModel):
    """Model for creating a user note."""
    title: str
    content: str
    category: Optional[str] = None
    tags: Optional[str] = None
    is_pinned: bool = False


class UserNoteUpdate(BaseModel):
    """Model for updating a user note."""
    title: Optional[str] = None
    content: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[str] = None
    is_pinned: Optional[bool] = None


class UserNoteRead(BaseModel):
    """Model for reading a user note."""
    id: int
    user_id: int
    title: str
    content: str
    category: Optional[str] = None
    tags: Optional[str] = None
    is_pinned: bool
    created_at_utc: datetime
    updated_at_utc: datetime
    
    class Config:
        from_attributes = True


# ============================================================================
# Shared Tips Models
# ============================================================================

class SharedTipCreate(BaseModel):
    """Model for creating a shared tip."""
    title: str
    content: str
    category: Optional[str] = None
    tags: Optional[str] = None
    is_pinned: bool = False


class SharedTipUpdate(BaseModel):
    """Model for updating a shared tip."""
    title: Optional[str] = None
    content: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[str] = None
    is_pinned: Optional[bool] = None


class SharedTipRead(BaseModel):
    """Model for reading a shared tip."""
    id: int
    title: str
    content: str
    category: Optional[str] = None
    tags: Optional[str] = None
    created_by_username: str
    created_at_utc: datetime
    updated_at_utc: datetime
    last_edited_by_username: Optional[str] = None
    helpful_count: int
    view_count: int
    is_pinned: bool
    is_archived: bool
    comment_count: int = 0
    question_count: int = 0
    unresolved_question_count: int = 0
    
    class Config:
        from_attributes = True


# ============================================================================
# Tip Comments Models
# ============================================================================

class TipCommentCreate(BaseModel):
    """Model for creating a tip comment."""
    content: str
    is_question: bool = False


class TipCommentUpdate(BaseModel):
    """Model for updating a tip comment."""
    content: Optional[str] = None
    is_resolved: Optional[bool] = None


class TipCommentRead(BaseModel):
    """Model for reading a tip comment."""
    id: int
    tip_id: int
    commented_by_username: str
    content: str
    is_question: bool
    is_resolved: bool
    created_at_utc: datetime
    updated_at_utc: datetime
    
    class Config:
        from_attributes = True


class CategoryInfo(BaseModel):
    """Model for category information."""
    name: str
    count: int


class CategoriesResponse(BaseModel):
    """Response model for categories endpoints."""
    categories: List[CategoryInfo]


# ============================================================================
# FAQ and Chatbot Models
# ============================================================================

class FAQEntryCreate(BaseModel):
    """Model for creating an FAQ entry."""
    question: str
    answer: str
    keywords: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[str] = None
    related_document_ids: Optional[str] = None
    related_tip_ids: Optional[str] = None


class FAQEntryUpdate(BaseModel):
    """Model for updating an FAQ entry."""
    question: Optional[str] = None
    answer: Optional[str] = None
    keywords: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[str] = None
    related_document_ids: Optional[str] = None
    related_tip_ids: Optional[str] = None
    is_active: Optional[bool] = None


class FAQEntryRead(BaseModel):
    """Model for reading an FAQ entry."""
    id: int
    question: str
    answer: str
    keywords: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[str] = None
    related_document_ids: Optional[str] = None
    related_tip_ids: Optional[str] = None
    created_by_username: str
    created_at_utc: datetime
    updated_at_utc: datetime
    view_count: int
    helpful_count: int
    is_active: bool
    
    class Config:
        from_attributes = True


class ChatbotQueryRequest(BaseModel):
    """Model for chatbot query request."""
    query: str


class RelatedResource(BaseModel):
    """Model for related resource in chatbot response."""
    type: str  # "document" or "tip"
    id: int
    title: str
    url: str
    snippet: Optional[str] = None
    similarity: Optional[float] = None
    chunk_index: Optional[int] = None


class ChatbotResponse(BaseModel):
    """Model for chatbot query response."""
    matched_faqs: List[FAQEntryRead]
    related_documents: List[RelatedResource] = []
    related_tips: List[RelatedResource] = []
    interaction_id: Optional[int] = None
    # LLM-synthesized response fields
    synthesized_response: Optional[str] = None  # LLM-generated answer
    sources_used: List[str] = []  # References to sources used in synthesis
    llm_used: bool = False  # Whether LLM was used for this response
    llm_model: Optional[str] = None  # Model name used for LLM generation (e.g., "mistral:7b")


class ChatbotFeedbackRequest(BaseModel):
    """Model for chatbot feedback."""
    interaction_id: int
    was_helpful: bool
    selected_faq_id: Optional[int] = None