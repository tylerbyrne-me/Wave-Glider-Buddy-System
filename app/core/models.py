from datetime import (datetime,  # Import the datetime module and timezone
                      timezone, date) # Import date
from enum import Enum  # type: ignore
from typing import List, Optional, TYPE_CHECKING

from pydantic import BaseModel, Field, field_validator
from sqlmodel import JSON, Column
from sqlmodel import Field as SQLModelField  # type: ignore
from sqlmodel import Relationship, SQLModel
# The VALID_REPORT_TYPES list is redundant as ReportTypeEnum serves as the source of truth.
# If it was used for a specific purpose, that should be documented or refactored.

if TYPE_CHECKING:
    from .models import UserInDB, Timesheet, PayPeriod  # noqa: F401


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


class SourceEnum(str, Enum):
    local = "local"
    remote = "remote"


class ReportDataParams(BaseModel):
    # Path parameters are handled by FastAPI directly in the function signature
    # Query parameters:
    hours_back: int = Field(72, gt=0, le=8760, description="Number of hours of data to retrieve, relative to the latest data point for the mission.")
    granularity_minutes: Optional[int] = Field(15, ge=5, le=60, description="Data resampling interval in minutes for charts. Minimum 5, maximum 60.")
    source: Optional[SourceEnum] = Field(None, description="Preferred data source: 'local' or 'remote'. Defaults to remote then local.")
    local_path: Optional[str] = Field(None, description="Custom base path for local data, overrides default settings path.")
    refresh: bool = Field(False, description="Force refresh data from source, bypassing cache.")

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


class ForecastParams(BaseModel):
    # Path parameters are handled by FastAPI directly
    # Query parameters:
    lat: Optional[float] = Field(None, ge=-90, le=90, description="Latitude for the forecast. If not provided, attempts to infer from telemetry.")
    lon: Optional[float] = Field(None, ge=-180, le=180, description="Longitude for the forecast. If not provided, attempts to infer from telemetry.")
    source: Optional[SourceEnum] = Field(None, description="Preferred source for telemetry lookup if lat/lon are inferred.")
    local_path: Optional[str] = Field(None, description="Custom local path for telemetry lookup if lat/lon are inferred.")
    refresh: bool = Field(False, description="Force refresh of telemetry data if used for lat/lon inference.")
    force_marine: Optional[bool] = Field(False, description="Legacy or specific flag, currently not used by primary forecast endpoints.") # Clarified description

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
        lat_val = values.data.get("lat") # noqa

        if (lat_val is not None and v is None) or (lat_val is None and v is not None):
            raise ValueError(
                "If 'lat' is provided, 'lon' must also be provided, and vice-versa."
            )
        return v


# --- User Authentication Models ---
class UserRoleEnum(str, Enum):
    admin = "admin"
    pilot = "pilot"


class UserBase(BaseModel):
    username: str = Field(description="Unique username for the user.")
    email: Optional[str] = Field(None, description="Email address of the user.")
    full_name: Optional[str] = Field(None, description="Full name of the user.")
    color: Optional[str] = Field(default=None, description="User's assigned color for UI elements like schedule shifts.")
    role: UserRoleEnum = Field(UserRoleEnum.pilot, description="Role of the user, determines access permissions.")


class UserCreate(UserBase):
    password: str = Field(description="User's password (will be hashed).")


class User(UserBase):
    id: int
    disabled: Optional[bool] = Field(None, description="Whether the user account is disabled.")


# UserInDB will now be our SQLModel table for users
class UserInDB(SQLModel, table=True):  # Inherit from SQLModel
    __tablename__ = "users"  # Explicit table name

    id: Optional[int] = SQLModelField(default=None, primary_key=True, description="Unique database identifier for the user.")
    username: str = SQLModelField(unique=True, index=True, description="Unique username for the user.")
    email: Optional[str] = SQLModelField(
        default=None, unique=True, index=True, description="Email address of the user (must be unique if provided)."
    )
    full_name: Optional[str] = SQLModelField(default=None, description="Full name of the user.")
    hashed_password: str = SQLModelField(description="Hashed password for the user.")
    role: UserRoleEnum = SQLModelField(
        default=UserRoleEnum.pilot, description="Role of the user, determines access permissions."
    )
    color: Optional[str] = SQLModelField(
        default=None, description="User's assigned color for UI elements."
    )
    disabled: Optional[bool] = SQLModelField(default=False, description="Whether the user account is disabled.")

    # If you want a direct relationship from UserInDB to their shifts
    # Ensure ShiftAssignment model is defined or forward-declared if it's below UserInDB
    shift_assignments: List["ShiftAssignment"] = Relationship(back_populates="user")
    unavailabilities: List["UserUnavailability"] = Relationship(back_populates="user")
    timesheets: List["Timesheet"] = Relationship(back_populates="user")




class UserUpdateForAdmin(BaseModel):  # New model for admin updates
    full_name: Optional[str] = None
    email: Optional[str] = Field(None, description="New email for the user. Must be unique if changed.")
    role: Optional[UserRoleEnum] = Field(None, description="New role for the user.")
    disabled: Optional[bool] = Field(None, description="New disabled status for the user account.")


class PasswordUpdate(BaseModel):  # New model for password change
    new_password: str = Field(description="The new password for the user.")


class Token(BaseModel):
    access_token: str
    token_type: str


# Forward declaration for type hinting in relationships
"StationMetadata"
"ShiftAssignment" # Forward declare ShiftAssignment
"PayPeriod"
"Timesheet"
"OffloadLog"


# --- Station Metadata Model ---
class StationMetadataCore(
    BaseModel
):  # Renamed to avoid conflict with SQLModel table name if used directly
    serial_number: Optional[str] = Field(None, description="Serial number of the station hardware.")
    modem_address: Optional[int] = Field(None, description="Modem address of the station.")
    bottom_depth_m: Optional[float] = Field(None, description="Bottom depth at the station location in meters.")
    waypoint_number: Optional[str] = Field(None, description="Associated waypoint number or identifier.")
    last_offload_by_glider: Optional[str] = Field(None, description="Identifier of the glider that last performed an offload (e.g., mission ID).")
    station_settings: Optional[str] = Field(None, description="Configuration settings for the station (e.g., '300bps, 0db').")
    notes: Optional[str] = Field(None, description="General notes or comments about the station.")
    display_status_override: Optional[str] = (
        Field(None, description="Manual override for the station's display status (e.g., 'SKIPPED', 'MAINTENANCE').")
    )


class StationMetadataBase(StationMetadataCore):
    station_id: str = Field(..., description="Unique Station Identifier (e.g., CBS001). This is the primary key.")
    # Fields to be updated by the latest offload log or direct edit
    last_offload_timestamp_utc: Optional[datetime] = Field(
        default=None, # noqa
        description="Timestamp of the last successful offload completion or log "
        "entry in UTC",
    )
    was_last_offload_successful: Optional[bool] = Field(
        default=None, # noqa
        description="Outcome of the last offload attempt"
    )


class StationMetadataCreate(StationMetadataBase):
    pass


class StationMetadataUpdate(SQLModel):  # For partial updates of core station info
    serial_number: Optional[str] = None
    modem_address: Optional[int] = None
    bottom_depth_m: Optional[float] = None
    waypoint_number: Optional[str] = None
    last_offload_by_glider: Optional[str] = None
    station_settings: Optional[str] = None
    notes: Optional[str] = None
    display_status_override: Optional[str] = None
    # last_offload_timestamp_utc and was_last_offload_successful are
    # typically updated via OffloadLog


# --- Offload Log Models ---
class OffloadLogBase(SQLModel):  # Using SQLModel as base for direct table inheritance
    arrival_date: Optional[datetime] = SQLModelField(default=None, description="Date and time of glider arrival at the station.")
    distance_command_sent_m: Optional[float] = SQLModelField(default=None, description="Distance (meters) from station when offload command was sent.")
    time_first_command_sent_utc: Optional[datetime] = SQLModelField(default=None, description="UTC timestamp of the first offload command sent.")
    offload_start_time_utc: Optional[datetime] = SQLModelField(default=None, description="UTC timestamp when the data offload started.")
    offload_end_time_utc: Optional[datetime] = SQLModelField(default=None, description="UTC timestamp when the data offload ended.")
    departure_date: Optional[datetime] = SQLModelField(default=None, description="Date and time of glider departure from the station.")
    was_offloaded: Optional[bool] = SQLModelField(
        default=None, description="Indicates if the offload was successful (True) or not (False)."
    )
    vrl_file_name: Optional[str] = SQLModelField(default=None, description="Name of the VRL file offloaded, if applicable.")
    offload_notes_file_size: Optional[str] = SQLModelField( # noqa
        default=None, # noqa
        description="Notes about the offload and/or file size"
    )


class OffloadLog(OffloadLogBase, table=True):
    __tablename__ = "offload_logs"
    id: Optional[int] = SQLModelField(default=None, primary_key=True)
    station_id: str = SQLModelField(foreign_key="station_metadata.station_id", index=True, description="Identifier of the station this log pertains to.")
    logged_by_username: str = SQLModelField(index=True, description="Username of the user who logged this offload attempt.")
    log_timestamp_utc: datetime = SQLModelField(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when this log entry was created."
    )

    station: "StationMetadata" = Relationship(back_populates="offload_logs")


class OffloadLogCreate(OffloadLogBase):  # For API input
    # Inherits all fields from OffloadLogBase
    pass


# --- Form Models ---
class FormItemTypeEnum(str, Enum):
    CHECKBOX = "checkbox"
    TEXT_INPUT = "text_input"
    TEXT_AREA = "text_area"
    AUTOFILLED_VALUE = "autofilled_value"
    # For values auto-populated from mission data
    STATIC_TEXT = "static_text"  # For instructions or non-interactive text
    DROPDOWN = "dropdown"  # New type for dropdown lists
    DATETIME_LOCAL = "datetime-local"  # For datetime-local input


class FormItem(BaseModel):
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
    id: str = Field(description="Unique identifier for the form section.")
    title: str = Field(description="Display title for the section.")
    items: List[FormItem] = Field(description="List of form items within this section.")
    section_comment: Optional[str] = Field(None, description="Optional comment for the entire section.")


class MissionFormSchema(BaseModel):  # Defines the structure/template of a form
    form_type: str = Field(description="Identifier for the type of form (e.g., 'pre_deployment_checklist').")
    title: str = Field(description="Display title of the form.")
    description: Optional[str] = Field(None, description="Optional description of the form's purpose.")
    sections: List[FormSection] = Field(description="List of sections that make up the form.")


class MissionFormDataCreate(BaseModel):  # Payload for submitting form data
    mission_id: str = Field(description="Identifier of the mission this form pertains to.")
    form_type: str = Field(description="Type of the form being submitted.")
    form_title: str = Field(description="Title of this specific form instance (can be same as schema title or customized).")
    sections_data: List[FormSection] = Field(description="The actual filled-out data, structured by sections and items.")


class MissionFormDataResponse(MissionFormDataCreate):  # What's stored and returned
    submitted_by_username: str
    submission_timestamp: (
        datetime  # datetime class is directly available due to the import
    )


# --- Database Model for Submitted Forms ---
class SubmittedForm(SQLModel, table=True):
    __tablename__ = "submitted_forms"  # Explicit table name

    id: Optional[int] = SQLModelField(default=None, primary_key=True, description="Unique database ID for the submitted form.")
    mission_id: str = SQLModelField(index=True, description="Identifier of the mission this form pertains to.")
    form_type: str = SQLModelField(index=True, description="Type of the form submitted.")
    form_title: str = Field(description="Title of this specific form instance.")

    # Store sections_data as a JSONB/JSON column in the database
    # Pydantic List[FormSection] will be converted to JSON string for storage
    # and parsed back when reading. By typing it as List[dict] here, we ensure
    # that SQLAlchemy's JSON serializer receives a directly serializable type.
    sections_data: List[dict] = SQLModelField(sa_column=Column(JSON), description="The actual form data, stored as JSON.")

    submitted_by_username: str = SQLModelField(index=True, description="Username of the user who submitted the form.")
    submission_timestamp: datetime = Field(description="UTC timestamp when the form was submitted.")


# --- Schedule Event Models ---
class ScheduleEvent(SQLModel):
    id: str
    text: str
    start: datetime
    end: datetime
    resource: str
    backColor: Optional[str] = None
    type: str = "shift"  # Add a type field, default to "shift"
    user_role: Optional[UserRoleEnum] = None # Add user role for styling unavailability
    user_color: Optional[str] = None # Add user color for styling unavailability
    editable: bool = True  # Add editable flag for frontend
    startEditable: bool = True
    durationEditable: bool = True
    resourceEditable: bool = True
    overlap: bool = False  # Shifts should not overlap with other shifts or unavailability
    display: str = "auto"  # 'auto' for shifts, 'background' for unavailability
    groupId: Optional[str] = None # For grouping events visually (e.g., consecutive LRI blocks)
    allDay: bool = False # Add allDay property


# New Pydantic model for creating schedule events from the client
class ScheduleEventCreate(BaseModel):
    start: str  # Expect ISO string from client
    end: str    # Expect ISO string from client
    resource: str
    text: Optional[str] = None   # Text is now optional, will be filled by backend
    id: Optional[str] = None # Client might send an ID, or backend generates

# New Pydantic model for creating LRI blocks from the client
class LRIBlockCreate(BaseModel):
    start_date: date # Expect YYYY-MM-DD from client
    end_date: date   # Expect YYYY-MM-DD from client
    reason: Optional[str] = None # Optional reason for the block


class UserUnavailabilityBase(SQLModel):
    start_time_utc: datetime
    end_time_utc: datetime
    reason: Optional[str] = None


class UserUnavailability(UserUnavailabilityBase, table=True):
    id: Optional[int] = SQLModelField(default=None, primary_key=True)
    user_id: int = SQLModelField(foreign_key="users.id") # Corrected foreign key table name and used SQLModelField
    created_at_utc: datetime = SQLModelField(default_factory=lambda: datetime.now(timezone.utc)) # Used SQLModelField

    user: Optional["UserInDB"] = Relationship(back_populates="unavailabilities")


class UserUnavailabilityCreate(UserUnavailabilityBase):
    pass  # No additional fields needed for creation


class UserUnavailabilityResponse(UserUnavailabilityBase):
    id: int
    user_id: int
    username: str  # For frontend display
    user_role: UserRoleEnum  # For frontend coloring
    user_color: str  # For frontend coloring
    created_at_utc: datetime

class ShiftAssignment(SQLModel, table=True):
    __tablename__ = "shift_assignments"

    id: Optional[int] = SQLModelField(default=None, primary_key=True, description="Unique database ID for the shift assignment.")
    user_id: int = SQLModelField(foreign_key="users.id", index=True, description="ID of the user assigned to this shift.")
    start_time_utc: datetime = SQLModelField(index=True, description="UTC start time of the shift.")
    end_time_utc: datetime = SQLModelField(index=True, description="UTC end time of the shift.")
    resource_id: str = SQLModelField(index=True, description="Resource identifier for the shift (e.g., day of week, specific date/time slot).")
    # Optional: Store the original text (username) if needed for quick display, though can be joined
    # event_text: str

    # Relationship to User
    user: Optional["UserInDB"] = Relationship(back_populates="shift_assignments")

    created_at: datetime = SQLModelField(default_factory=lambda: datetime.now(timezone.utc))
    # last_modified_at: datetime = Field(default_factory=datetime.utcnow, sa_column_kwargs={"onupdate": datetime.utcnow}) # More advanced


# --- Model for PIC Handoff Link Information ---
class PicHandoffLinkInfo(BaseModel):
    form_db_id: int # The database ID of the SubmittedForm
    mission_id: str
    form_title: str # Should typically be "PIC Handoff Checklist" or similar
    submitted_by_username: str
    submission_timestamp: datetime

# --- Pay Period and Timesheet Models ---

class PayPeriodStatusEnum(str, Enum):
    OPEN = "open"
    CLOSED = "closed"

class PayPeriod(SQLModel, table=True):
    __tablename__ = "pay_periods"
    id: Optional[int] = SQLModelField(default=None, primary_key=True)
    name: str = SQLModelField(index=True, description="Name of the pay period (e.g., 'June 1-15, 2025').")
    start_date: date = SQLModelField(description="Start date of the pay period.")
    end_date: date = SQLModelField(description="End date of the pay period.")
    status: PayPeriodStatusEnum = SQLModelField(default=PayPeriodStatusEnum.OPEN, description="Status of the pay period.")
    created_at: datetime = SQLModelField(default_factory=lambda: datetime.now(timezone.utc))

    timesheets: List["Timesheet"] = Relationship(back_populates="pay_period")

class PayPeriodCreate(BaseModel):
    name: str
    start_date: date
    end_date: date

class PayPeriodUpdate(BaseModel):
    name: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    status: Optional[PayPeriodStatusEnum] = None


class TimesheetStatusEnum(str, Enum):
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"

class Timesheet(SQLModel, table=True):
    __tablename__ = "timesheets"
    id: Optional[int] = SQLModelField(default=None, primary_key=True)
    user_id: int = SQLModelField(foreign_key="users.id", index=True)
    pay_period_id: int = SQLModelField(foreign_key="pay_periods.id", index=True)
    
    calculated_hours: float = SQLModelField(description="Total hours calculated from shifts for the period.")
    adjusted_hours: Optional[float] = SQLModelField(default=None, description="Admin-adjusted hours, overrides calculated_hours if set.")
    notes: Optional[str] = SQLModelField(default=None, description="Optional notes from the pilot.")
    reviewer_notes: Optional[str] = SQLModelField(default=None, description="Notes added by the administrator during review.")
    status: TimesheetStatusEnum = SQLModelField(default=TimesheetStatusEnum.SUBMITTED)
    submission_timestamp: datetime = SQLModelField(default_factory=lambda: datetime.now(timezone.utc))
    is_active: bool = SQLModelField(default=True, index=True, description="Indicates if this is the most recent submission for this user/period.")
    
    # Relationships
    user: "UserInDB" = Relationship(back_populates="timesheets")
    pay_period: "PayPeriod" = Relationship(back_populates="timesheets")

class TimesheetCreate(BaseModel):
    pay_period_id: int
    calculated_hours: float
    notes: Optional[str] = None

class TimesheetUpdate(BaseModel):
    status: Optional[TimesheetStatusEnum] = None
    adjusted_hours: Optional[float] = None
    reviewer_notes: Optional[str] = None

class StationMetadata(SQLModel, table=True):  # type: ignore
    __tablename__ = "station_metadata"

    station_id: str = SQLModelField(default=..., primary_key=True, index=True, description="Unique Station Identifier (e.g., CBS001). Primary key.")
    serial_number: Optional[str] = SQLModelField(default=None, index=True, description="Serial number of the station hardware.")
    modem_address: Optional[int] = SQLModelField(
        default=None, description="Modem address of the station."
    )
    bottom_depth_m: Optional[float] = SQLModelField(default=None, description="Bottom depth at the station location in meters.")
    waypoint_number: Optional[str] = SQLModelField(default=None, description="Associated waypoint number or identifier.")
    last_offload_by_glider: Optional[str] = SQLModelField(default=None, description="Identifier of the glider that last performed an offload.")
    station_settings: Optional[str] = SQLModelField(default=None, description="Configuration settings for the station.")
    notes: Optional[str] = SQLModelField(default=None, description="General notes or comments about the station.")

    last_offload_timestamp_utc: Optional[datetime] = SQLModelField(
        default=None,
        index=True, # noqa
        description="Timestamp of the last successful offload or log entry "
        "in UTC",
    )
    was_last_offload_successful: Optional[bool] = SQLModelField(
        default=None, # noqa
        description="Outcome of the last offload attempt"
    )
    display_status_override: Optional[str] = SQLModelField(
        default=None, # noqa
        index=True, # noqa
        description="User override for display status, e.g., SKIPPED",
    )

    offload_logs: List["OffloadLog"] = Relationship(
        back_populates="station",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )


class StationMetadataRead(
    StationMetadataBase
):  # For API responses, inherits from the Pydantic base
    pass  # All fields from StationMetadataBase are included


class StationMetadataReadWithLogs(StationMetadataRead):
    offload_logs: List[OffloadLog] = (
        []
    )  # Or OffloadLogRead if you create a specific Pydantic model for reading logs


class OffloadLogRead(OffloadLogBase):  # For API responses
    id: int
    station_id: str
    logged_by_username: str
    log_timestamp_utc: datetime

class TimesheetRead(BaseModel):
    id: int
    user_id: int
    username: str # For display
    pay_period_id: int
    pay_period_name: str # For display
    calculated_hours: float
    adjusted_hours: Optional[float]
    notes: Optional[str]
    reviewer_notes: Optional[str] # For display
    status: TimesheetStatusEnum
    submission_timestamp: datetime
    is_active: bool


class StationMetadataCreateResponse(StationMetadataRead):
    """
    Response model for the create/update endpoint.
    Includes all fields from StationMetadataRead plus a flag to indicate
    if the resource was newly created or just updated.
    """
    is_created: bool