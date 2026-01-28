"""
SQLModel database table definitions for the Wave Glider Buddy System.
"""

from datetime import datetime, timezone, date
from typing import List, Optional, TYPE_CHECKING, Dict

from sqlmodel import JSON, Column, Text
from sqlmodel import Field as SQLModelField
from sqlmodel import Relationship, SQLModel

from .enums import (
    UserRoleEnum,
    PayPeriodStatusEnum,
    TimesheetStatusEnum,
)

if TYPE_CHECKING:
    pass  # Forward references for relationships


# --- User Database Model ---
class UserInDB(SQLModel, table=True):
    """User database table."""
    __tablename__ = "users"

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
    sensor_tracker_token: Optional[str] = SQLModelField(
        default=None,
        sa_column=Column(Text),
        description="Personal Sensor Tracker API token for admin sync actions.",
    )

    # Relationships
    shift_assignments: List["ShiftAssignment"] = Relationship(back_populates="user")
    unavailabilities: List["UserUnavailability"] = Relationship(back_populates="user")
    timesheets: List["Timesheet"] = Relationship(back_populates="user")


# --- Station Metadata Database Model ---
class StationMetadata(SQLModel, table=True):
    """Station metadata database table."""
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
    deployment_latitude: Optional[float] = SQLModelField(default=None, description="Latitude of the station deployment location in decimal degrees.")
    deployment_longitude: Optional[float] = SQLModelField(default=None, description="Longitude of the station deployment location in decimal degrees.")
    notes: Optional[str] = SQLModelField(default=None, description="General notes or comments about the station.")

    last_offload_timestamp_utc: Optional[datetime] = SQLModelField(
        default=None,
        index=True,
        description="Timestamp of the last successful offload or log entry in UTC",
    )
    was_last_offload_successful: Optional[bool] = SQLModelField(
        default=None,
        description="Outcome of the last offload attempt"
    )
    display_status_override: Optional[str] = SQLModelField(
        default=None,
        index=True,
        description="User override for display status, e.g., SKIPPED",
    )
    field_season_year: Optional[int] = SQLModelField(
        default=None,
        index=True,
        description="Field season year this station record belongs to (NULL = current/active season)",
    )
    is_archived: bool = SQLModelField(
        default=False,
        index=True,
        description="Whether this station record is archived (read-only)",
    )
    archived_at_utc: Optional[datetime] = SQLModelField(
        default=None,
        description="UTC timestamp when this station was archived",
    )

    offload_logs: List["OffloadLog"] = Relationship(
        back_populates="station",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )


# --- Offload Log Database Model ---
class OffloadLogBase(SQLModel):
    """Base model for offload log data."""
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
    offload_notes_file_size: Optional[str] = SQLModelField(
        default=None,
        description="Notes about the offload and/or file size"
    )
    # VM4 Remote Health snapshot at time of connection (from Vemco VM4 Remote Health.csv)
    remote_health_model_id: Optional[str] = SQLModelField(default=None, description="Model ID from station remote health (e.g. 1538).")
    remote_health_serial_number: Optional[str] = SQLModelField(default=None, description="Serial number from station remote health.")
    remote_health_modem_address: Optional[int] = SQLModelField(default=None, description="Modem address from station remote health.")
    remote_health_temperature_c: Optional[float] = SQLModelField(default=None, description="Temperature (C) from station remote health.")
    remote_health_tilt_rad: Optional[float] = SQLModelField(default=None, description="Tilt (rad) from station remote health.")
    remote_health_humidity: Optional[int] = SQLModelField(default=None, description="Humidity from station remote health.")


class OffloadLog(OffloadLogBase, table=True):
    """Offload log database table."""
    __tablename__ = "offload_logs"
    
    id: Optional[int] = SQLModelField(default=None, primary_key=True)
    station_id: str = SQLModelField(foreign_key="station_metadata.station_id", index=True, description="Identifier of the station this log pertains to.")
    logged_by_username: str = SQLModelField(index=True, description="Username of the user who logged this offload attempt.")
    log_timestamp_utc: datetime = SQLModelField(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when this log entry was created."
    )
    field_season_year: Optional[int] = SQLModelField(
        default=None,
        index=True,
        description="Field season year this offload occurred in",
    )

    station: "StationMetadata" = Relationship(back_populates="offload_logs")


# --- Field Season Database Model ---
class FieldSeason(SQLModel, table=True):
    """Field season database table."""
    __tablename__ = "field_seasons"
    
    id: Optional[int] = SQLModelField(default=None, primary_key=True)
    year: int = SQLModelField(
        unique=True,
        index=True,
        description="Field season year (e.g., 2024, 2025)",
    )
    is_active: bool = SQLModelField(
        default=True,
        index=True,
        description="Whether this is the currently active season (only one active at a time)",
    )
    closed_at_utc: Optional[datetime] = SQLModelField(
        default=None,
        description="UTC timestamp when this season was closed",
    )
    closed_by_username: Optional[str] = SQLModelField(
        default=None,
        description="Username of the user who closed this season",
    )
    summary_statistics: Optional[Dict] = SQLModelField(
        default=None,
        sa_column=Column(JSON),
        description="JSON field storing season summary statistics",
    )
    created_at_utc: datetime = SQLModelField(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when this season record was created",
    )


# --- Submitted Form Database Model ---
class SubmittedForm(SQLModel, table=True):
    """Submitted form database table."""
    __tablename__ = "submitted_forms"

    id: Optional[int] = SQLModelField(default=None, primary_key=True, description="Unique database ID for the submitted form.")
    mission_id: str = SQLModelField(index=True, description="Identifier of the mission this form pertains to.")
    form_type: str = SQLModelField(index=True, description="Type of the form submitted.")
    form_title: str = SQLModelField(description="Title of this specific form instance.")

    # Store sections_data as a JSONB/JSON column in the database
    sections_data: List[dict] = SQLModelField(sa_column=Column(JSON), description="The actual form data, stored as JSON.")

    submitted_by_username: str = SQLModelField(index=True, description="Username of the user who submitted the form.")
    submission_timestamp: datetime = SQLModelField(description="UTC timestamp when the form was submitted.")


# --- User Unavailability Database Model ---
class UserUnavailability(SQLModel, table=True):
    """User unavailability database table."""
    id: Optional[int] = SQLModelField(default=None, primary_key=True)
    user_id: int = SQLModelField(foreign_key="users.id")
    start_time_utc: datetime
    end_time_utc: datetime
    reason: Optional[str] = None
    created_at_utc: datetime = SQLModelField(default_factory=lambda: datetime.now(timezone.utc))

    user: Optional["UserInDB"] = Relationship(back_populates="unavailabilities")


# --- Shift Assignment Database Model ---
class ShiftAssignment(SQLModel, table=True):
    """Shift assignment database table."""
    __tablename__ = "shift_assignments"

    id: Optional[int] = SQLModelField(default=None, primary_key=True, description="Unique database ID for the shift assignment.")
    user_id: int = SQLModelField(foreign_key="users.id", index=True, description="ID of the user assigned to this shift.")
    start_time_utc: datetime = SQLModelField(index=True, description="UTC start time of the shift.")
    end_time_utc: datetime = SQLModelField(index=True, description="UTC end time of the shift.")
    resource_id: str = SQLModelField(index=True, description="Resource identifier for the shift (e.g., day of week, specific date/time slot).")

    # Relationship to User
    user: Optional["UserInDB"] = Relationship(back_populates="shift_assignments")

    created_at: datetime = SQLModelField(default_factory=lambda: datetime.now(timezone.utc))


# --- Pay Period Database Model ---
class PayPeriod(SQLModel, table=True):
    """Pay period database table."""
    __tablename__ = "pay_periods"
    
    id: Optional[int] = SQLModelField(default=None, primary_key=True)
    name: str = SQLModelField(index=True, description="Name of the pay period (e.g., 'June 1-15, 2025').")
    start_date: date = SQLModelField(description="Start date of the pay period.")
    end_date: date = SQLModelField(description="End date of the pay period.")
    status: PayPeriodStatusEnum = SQLModelField(default=PayPeriodStatusEnum.OPEN, description="Status of the pay period.")
    created_at: datetime = SQLModelField(default_factory=lambda: datetime.now(timezone.utc))

    timesheets: List["Timesheet"] = Relationship(back_populates="pay_period")


# --- Timesheet Database Model ---
class Timesheet(SQLModel, table=True):
    """Timesheet database table."""
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


# --- Mission Overview Database Model ---
class MissionOverview(SQLModel, table=True):
    """Mission overview database table."""
    __tablename__ = "mission_overview"
    
    mission_id: str = SQLModelField(primary_key=True, description="The mission identifier, e.g., 'm203'.")
    weekly_report_url: Optional[str] = SQLModelField(default=None, description="URL to the latest generated weekly report PDF.")
    end_of_mission_report_url: Optional[str] = SQLModelField(default=None, description="URL to the end of mission report PDF.")
    document_url: Optional[str] = SQLModelField(default=None, description="URL to the formal mission plan document (.doc, .pdf).")
    comments: Optional[str] = SQLModelField(default=None, sa_column=Column(Text), description="High-level comments about the mission.")
    enabled_sensor_cards: Optional[str] = SQLModelField(default=None, sa_column=Column(Text), description="JSON string of enabled sensor cards for this mission.")
    created_at_utc: datetime = SQLModelField(default_factory=lambda: datetime.now(timezone.utc))
    updated_at_utc: datetime = SQLModelField(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column_kwargs={"onupdate": lambda: datetime.now(timezone.utc)}
    )


# --- Mission Media Database Model ---
class MissionMedia(SQLModel, table=True):
    """Mission media (photos/videos) database table."""
    __tablename__ = "mission_media"

    id: Optional[int] = SQLModelField(default=None, primary_key=True)
    mission_id: str = SQLModelField(index=True, description="Mission identifier")
    media_type: str = SQLModelField(description="photo or video")
    file_path: str = SQLModelField(description="Relative path to file in static directory")
    file_name: str = SQLModelField(description="Original filename")
    file_size: int = SQLModelField(description="File size in bytes")
    mime_type: str = SQLModelField(description="MIME type (e.g., image/jpeg, video/mp4)")

    # Metadata
    caption: Optional[str] = SQLModelField(default=None, sa_column=Column(Text))
    operation_type: Optional[str] = SQLModelField(default=None, description="deployment or recovery")
    uploaded_by_username: str = SQLModelField(index=True)
    uploaded_at_utc: datetime = SQLModelField(default_factory=lambda: datetime.now(timezone.utc))

    # Source tracking (e.g., Sensor Tracker sync)
    source_system: Optional[str] = SQLModelField(default=None, index=True, description="Origin system for synced media")
    source_url: Optional[str] = SQLModelField(default=None, index=True, description="Origin URL for synced media")
    source_external_id: Optional[str] = SQLModelField(
        default=None, index=True, description="Origin system record identifier"
    )

    # For videos: thumbnail path (optional)
    thumbnail_path: Optional[str] = SQLModelField(default=None)

    # Approval workflow
    approval_status: str = SQLModelField(default="approved", description="pending, approved, rejected")
    approved_by_username: Optional[str] = SQLModelField(default=None)
    approved_at_utc: Optional[datetime] = SQLModelField(default=None)

    # Ordering/display
    display_order: int = SQLModelField(default=0, description="Order for display in gallery")
    is_featured: bool = SQLModelField(default=False, description="Featured image for mission overview")


# --- Mission Goal Database Model ---
class MissionGoal(SQLModel, table=True):
    """Mission goal database table."""
    __tablename__ = "mission_goals"
    
    id: Optional[int] = SQLModelField(default=None, primary_key=True)
    mission_id: str = SQLModelField(index=True, description="The mission this goal belongs to.")
    description: str = SQLModelField(description="The text of the mission goal.")
    is_completed: bool = SQLModelField(default=False, index=True)
    completed_by_username: Optional[str] = SQLModelField(default=None)
    completed_at_utc: Optional[datetime] = SQLModelField(default=None)
    created_at_utc: datetime = SQLModelField(default_factory=lambda: datetime.now(timezone.utc))


# --- Mission Note Database Model ---
class MissionNote(SQLModel, table=True):
    """Mission note database table."""
    __tablename__ = "mission_notes"
    
    id: Optional[int] = SQLModelField(default=None, primary_key=True)
    mission_id: str = SQLModelField(index=True, description="The mission this note belongs to.")
    content: str = SQLModelField(sa_column=Column(Text), description="The content of the note.")
    created_by_username: str
    created_at_utc: datetime = SQLModelField(default_factory=lambda: datetime.now(timezone.utc))


# --- Sensor Tracker Outbox Database Model ---
class SensorTrackerOutbox(SQLModel, table=True):
    """Queue for outbound Sensor Tracker sync items."""
    __tablename__ = "sensor_tracker_outbox"

    id: Optional[int] = SQLModelField(default=None, primary_key=True)
    mission_id: str = SQLModelField(index=True, description="Mission identifier")
    entity_type: str = SQLModelField(index=True, description="deployment_comment, goal, media")
    local_id: int = SQLModelField(index=True, description="Local entity ID")

    payload: Optional[Dict] = SQLModelField(sa_column=Column(JSON), description="Payload for sync")
    payload_hash: Optional[str] = SQLModelField(default=None, index=True, description="Hash of payload")

    status: str = SQLModelField(default="pending_review", index=True, description="pending_review, approved, rejected, synced, failed, remote_deleted")
    approved_by_username: Optional[str] = SQLModelField(default=None, index=True)
    approved_at_utc: Optional[datetime] = SQLModelField(default=None)
    rejected_by_username: Optional[str] = SQLModelField(default=None, index=True)
    rejected_at_utc: Optional[datetime] = SQLModelField(default=None)
    rejection_reason: Optional[str] = SQLModelField(default=None, sa_column=Column(Text))

    sensor_tracker_id: Optional[str] = SQLModelField(default=None, index=True, description="Remote record ID")
    last_attempt_at_utc: Optional[datetime] = SQLModelField(default=None)
    error_message: Optional[str] = SQLModelField(default=None, sa_column=Column(Text))

    created_at_utc: datetime = SQLModelField(default_factory=lambda: datetime.now(timezone.utc))
    updated_at_utc: datetime = SQLModelField(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column_kwargs={"onupdate": lambda: datetime.now(timezone.utc)}
    )


# --- Sensor Tracker Deployment Database Model ---
class SensorTrackerDeployment(SQLModel, table=True):
    """Stores Sensor Tracker deployment metadata linked to missions."""
    __tablename__ = "sensor_tracker_deployments"
    
    id: Optional[int] = SQLModelField(default=None, primary_key=True)
    mission_id: str = SQLModelField(index=True, unique=True, description="Mission ID (e.g., 'm216')")
    sensor_tracker_deployment_id: int = SQLModelField(index=True, description="Sensor Tracker internal ID")
    deployment_number: int = SQLModelField(index=True, description="Mission/deployment number")
    
    # Deployment metadata
    title: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    deployment_location_lat: Optional[float] = None
    deployment_location_lon: Optional[float] = None
    recovery_location_lat: Optional[float] = None
    recovery_location_lon: Optional[float] = None
    depth: Optional[float] = None
    
    # Platform info
    platform_id: Optional[int] = None
    platform_name: Optional[str] = None
    platform_type: Optional[int] = None
    
    # Priority metadata fields (Phase 1A)
    agencies: Optional[str] = SQLModelField(default=None, description="Funding/supporting agencies (comma-separated, order preserved)")
    agencies_role: Optional[str] = SQLModelField(default=None, description="Role of agencies (e.g., 'Funding agency')")
    deployment_comment: Optional[str] = SQLModelField(default=None, sa_column=Column(Text), description="Long-form deployment description/comment")
    acknowledgement: Optional[str] = SQLModelField(default=None, sa_column=Column(Text), description="Acknowledgement text")
    
    # Additional metadata fields (Phase 1B)
    # Deployment details
    deployment_cruise: Optional[str] = SQLModelField(default=None, description="Vessel name for deployment")
    recovery_cruise: Optional[str] = SQLModelField(default=None, description="Vessel name for recovery")
    deployment_personnel: Optional[str] = SQLModelField(default=None, description="Personnel involved in deployment (comma-separated)")
    recovery_personnel: Optional[str] = SQLModelField(default=None, description="Personnel involved in recovery (comma-separated)")
    wmo_id: Optional[str] = SQLModelField(default=None, description="WMO identifier if applicable")
    
    # Publication and data access
    data_repository_link: Optional[str] = SQLModelField(default=None, description="Link to data repository (e.g., ERDDAP)")
    metadata_link: Optional[str] = SQLModelField(default=None, description="Link to metadata documentation")
    publisher_name: Optional[str] = SQLModelField(default=None, description="Organization publishing the data")
    publisher_email: Optional[str] = SQLModelField(default=None, description="Publisher contact email")
    publisher_url: Optional[str] = SQLModelField(default=None, description="Publisher website")
    publisher_country: Optional[str] = SQLModelField(default=None, description="Country of publisher")
    
    # Attribution
    creator_name: Optional[str] = SQLModelField(default=None, description="Data creator name")
    creator_email: Optional[str] = SQLModelField(default=None, description="Creator contact email")
    creator_url: Optional[str] = SQLModelField(default=None, description="Creator website")
    creator_sector: Optional[str] = SQLModelField(default=None, description="Creator sector (academic, government, etc.)")
    contributor_name: Optional[str] = SQLModelField(default=None, description="Contributor names")
    contributor_role: Optional[str] = SQLModelField(default=None, description="Role of contributors")
    contributors_email: Optional[str] = SQLModelField(default=None, description="Contributor contact email")
    
    # Program information
    program: Optional[str] = SQLModelField(default=None, description="Program name")
    site: Optional[str] = SQLModelField(default=None, description="Site name")
    sea_name: Optional[str] = SQLModelField(default=None, description="Geographic region/sea name")
    
    # Technical details
    transmission_system: Optional[str] = SQLModelField(default=None, description="Communication systems (e.g., 'Iridium, Cellular')")
    positioning_system: Optional[str] = SQLModelField(default=None, description="Navigation systems (e.g., 'GPS')")
    references: Optional[str] = SQLModelField(default=None, sa_column=Column(Text), description="Technical references")
    
    # Full parsed data (JSON for flexibility)
    full_metadata: Optional[Dict] = SQLModelField(sa_column=Column(JSON), description="Complete parsed deployment data")
    
    # Sync metadata
    last_synced_at: Optional[datetime] = None
    sync_status: str = SQLModelField(default="pending", description="pending, synced, error")
    sync_error: Optional[str] = None
    
    created_at_utc: datetime = SQLModelField(default_factory=lambda: datetime.now(timezone.utc))
    updated_at_utc: datetime = SQLModelField(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column_kwargs={"onupdate": lambda: datetime.now(timezone.utc)}
    )


# --- Mission Instrument Database Model ---
class MissionInstrument(SQLModel, table=True):
    """Stores instrument metadata for missions."""
    __tablename__ = "mission_instruments"
    
    id: Optional[int] = SQLModelField(default=None, primary_key=True)
    mission_id: str = SQLModelField(index=True, description="Mission ID")
    sensor_tracker_instrument_id: Optional[int] = SQLModelField(index=True, description="Sensor Tracker instrument ID")
    
    # Instrument details
    instrument_identifier: str = SQLModelField(index=True, description="e.g., 'CTD', 'ADCP', 'GPSWaves-Sensor'")
    instrument_short_name: Optional[str] = None
    instrument_serial: Optional[str] = None
    instrument_name: Optional[str] = None
    
    # Data logger association
    data_logger_type: Optional[str] = None  # 'flight' or 'science'
    data_logger_id: Optional[int] = None
    data_logger_name: Optional[str] = None
    data_logger_identifier: Optional[str] = None
    is_platform_direct: bool = SQLModelField(default=False, description="True if attached directly to platform")
    
    # Timing
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    
    # Validation
    validated: bool = SQLModelField(default=False, description="Whether instrument data has been validated")
    validation_notes: Optional[str] = None
    
    created_at_utc: datetime = SQLModelField(default_factory=lambda: datetime.now(timezone.utc))
    updated_at_utc: datetime = SQLModelField(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column_kwargs={"onupdate": lambda: datetime.now(timezone.utc)}
    )
    
    # Relationship
    sensors: List["MissionSensor"] = Relationship(back_populates="instrument")


# --- Mission Sensor Database Model ---
class MissionSensor(SQLModel, table=True):
    """Stores sensor metadata for missions."""
    __tablename__ = "mission_sensors"
    
    id: Optional[int] = SQLModelField(default=None, primary_key=True)
    mission_id: str = SQLModelField(index=True, description="Mission ID")
    instrument_id: int = SQLModelField(foreign_key="mission_instruments.id", description="Parent instrument")
    sensor_tracker_sensor_id: Optional[int] = SQLModelField(index=True, description="Sensor Tracker sensor ID")
    
    # Sensor details
    sensor_identifier: str = SQLModelField(index=True, description="e.g., 'dissolved_oxygen - 3151', 'ctd_pump'")
    sensor_short_name: Optional[str] = None
    sensor_serial: Optional[str] = None
    
    # Timing
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    
    # Validation
    validated: bool = SQLModelField(default=False)
    validation_notes: Optional[str] = None
    
    created_at_utc: datetime = SQLModelField(default_factory=lambda: datetime.now(timezone.utc))
    updated_at_utc: datetime = SQLModelField(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column_kwargs={"onupdate": lambda: datetime.now(timezone.utc)}
    )
    
    # Relationship
    instrument: "MissionInstrument" = Relationship(back_populates="sensors")


# --- Live KML Token Database Model ---
class LiveKMLToken(SQLModel, table=True):
    """Stores tokens for live KML network links that auto-update in Google Earth"""
    __tablename__ = "live_kml_tokens"
    
    token: str = SQLModelField(primary_key=True, max_length=64, description="Unique token for live KML access")
    mission_ids: str = SQLModelField(sa_column=Column(Text), description="Comma-separated list of mission IDs")
    user_id: int = SQLModelField(foreign_key="users.id", index=True)
    
    hours_back: int = SQLModelField(default=72, description="Hours of history to include")
    refresh_interval_minutes: int = SQLModelField(default=10, description="Auto-refresh interval for Google Earth")
    
    is_active: bool = SQLModelField(default=True, index=True, description="Whether token is active")
    expires_at: datetime = SQLModelField(description="Token expiration date/time")
    access_count: int = SQLModelField(default=0, description="Number of times token has been accessed")
    last_accessed_at: Optional[datetime] = None
    
    created_at: datetime = SQLModelField(default_factory=lambda: datetime.now(timezone.utc))
    created_by: int = SQLModelField(foreign_key="users.id")
    description: Optional[str] = None
    
    # Future enhancements
    color_scheme: Optional[str] = None
    include_markers: bool = True
    include_timestamps: bool = True


# --- Announcement Database Models ---
class Announcement(SQLModel, table=True):
    """Announcement database table."""
    id: Optional[int] = SQLModelField(default=None, primary_key=True)
    content: str
    created_by_username: str
    created_at_utc: datetime = SQLModelField(default_factory=lambda: datetime.now(timezone.utc))
    is_active: bool = SQLModelField(default=True)
    announcement_type: Optional[str] = SQLModelField(default="general", index=True, description="Type: general, question, system, etc.")
    target_roles: Optional[str] = SQLModelField(default=None, description="Comma-separated roles (optional)")
    target_usernames: Optional[str] = SQLModelField(default=None, description="Comma-separated usernames (optional)")
    acknowledgements: List["AnnouncementAcknowledgement"] = Relationship(back_populates="announcement")


class AnnouncementAcknowledgement(SQLModel, table=True):
    """Announcement acknowledgement database table."""
    id: Optional[int] = SQLModelField(default=None, primary_key=True)
    announcement_id: int = SQLModelField(foreign_key="announcement.id")
    user_id: int = SQLModelField(foreign_key="users.id")
    acknowledged_at_utc: datetime = SQLModelField(default_factory=lambda: datetime.now(timezone.utc))
    announcement: "Announcement" = Relationship(back_populates="acknowledgements")


# --- Knowledge Base Database Models ---
class KnowledgeDocument(SQLModel, table=True):
    """Knowledge base document database table."""
    __tablename__ = "knowledge_documents"
    
    id: Optional[int] = SQLModelField(default=None, primary_key=True, description="Unique database identifier")
    title: str = SQLModelField(index=True, description="Document title")
    description: Optional[str] = SQLModelField(default=None, description="Document description")
    file_path: str = SQLModelField(description="Path to stored file (relative to project root)")
    file_name: str = SQLModelField(description="Original filename")
    file_type: str = SQLModelField(index=True, description="File type: pdf, docx, pptx")
    file_size: int = SQLModelField(description="File size in bytes")
    category: Optional[str] = SQLModelField(default=None, index=True, description="Document category")
    tags: Optional[str] = SQLModelField(default=None, description="Comma-separated tags")
    access_level: str = SQLModelField(default="pilot", index=True, description="Access level: public, pilot, admin")
    
    # Full-text search content (extracted text)
    searchable_content: Optional[str] = SQLModelField(default=None, sa_column=Column(Text), description="Extracted text for searching")
    
    # Metadata
    uploaded_by_username: str = SQLModelField(index=True, description="Username who uploaded")
    uploaded_at_utc: datetime = SQLModelField(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Upload timestamp"
    )
    updated_at_utc: datetime = SQLModelField(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column_kwargs={"onupdate": lambda: datetime.now(timezone.utc)},
        description="Last update timestamp"
    )
    version: int = SQLModelField(default=1, description="Current version number")
    is_active: bool = SQLModelField(default=True, index=True, description="Whether document is active")
    
    # Relationships
    document_versions: List["KnowledgeDocumentVersion"] = Relationship(back_populates="document")


class KnowledgeDocumentVersion(SQLModel, table=True):
    """Document version history."""
    __tablename__ = "knowledge_document_versions"
    
    id: Optional[int] = SQLModelField(default=None, primary_key=True)
    document_id: int = SQLModelField(foreign_key="knowledge_documents.id", index=True)
    file_path: str = SQLModelField(description="Path to version file")
    version: int = SQLModelField(description="Version number")
    uploaded_by_username: str = SQLModelField(description="Username who uploaded this version")
    uploaded_at_utc: datetime = SQLModelField(default_factory=lambda: datetime.now(timezone.utc))
    change_notes: Optional[str] = SQLModelField(default=None, description="Notes about changes")
    
    document: "KnowledgeDocument" = Relationship(back_populates="document_versions")


# --- User Notes Database Models ---
class UserNote(SQLModel, table=True):
    """User personal notes database table."""
    __tablename__ = "user_notes"
    
    id: Optional[int] = SQLModelField(default=None, primary_key=True)
    user_id: int = SQLModelField(foreign_key="users.id", index=True, description="User who owns this note")
    title: str = SQLModelField(index=True, description="Note title")
    content: str = SQLModelField(sa_column=Column(Text), description="Note content (rich text)")
    category: Optional[str] = SQLModelField(default=None, index=True, description="User-defined category")
    tags: Optional[str] = SQLModelField(default=None, description="Comma-separated tags")
    is_pinned: bool = SQLModelField(default=False, index=True, description="Whether note is pinned")
    
    created_at_utc: datetime = SQLModelField(default_factory=lambda: datetime.now(timezone.utc))
    updated_at_utc: datetime = SQLModelField(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column_kwargs={"onupdate": lambda: datetime.now(timezone.utc)}
    )
    
    # Relationships
    user: "UserInDB" = Relationship()


# --- Shared Tips Database Models ---
class SharedTip(SQLModel, table=True):
    """Shared tips and tricks database table."""
    __tablename__ = "shared_tips"
    
    id: Optional[int] = SQLModelField(default=None, primary_key=True)
    title: str = SQLModelField(index=True, description="Tip title")
    content: str = SQLModelField(sa_column=Column(Text), description="Tip content")
    category: Optional[str] = SQLModelField(default=None, index=True, description="Tip category")
    tags: Optional[str] = SQLModelField(default=None, description="Comma-separated tags")
    
    # Collaboration
    created_by_username: str = SQLModelField(index=True, description="Username who created")
    created_at_utc: datetime = SQLModelField(default_factory=lambda: datetime.now(timezone.utc))
    updated_at_utc: datetime = SQLModelField(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column_kwargs={"onupdate": lambda: datetime.now(timezone.utc)}
    )
    last_edited_by_username: Optional[str] = SQLModelField(default=None, description="Username who last edited")
    
    # Engagement metrics
    helpful_count: int = SQLModelField(default=0, description="Number of helpful votes")
    view_count: int = SQLModelField(default=0, description="Number of views")
    is_pinned: bool = SQLModelField(default=False, index=True, description="Whether tip is pinned")
    is_archived: bool = SQLModelField(default=False, index=True, description="Whether tip is archived")
    
    # Relationships
    tip_contributions: List["TipContribution"] = Relationship(back_populates="tip")
    tip_comments: List["TipComment"] = Relationship(back_populates="tip")


class TipContribution(SQLModel, table=True):
    """Tip contribution/edit history."""
    __tablename__ = "tip_contributions"
    
    id: Optional[int] = SQLModelField(default=None, primary_key=True)
    tip_id: int = SQLModelField(foreign_key="shared_tips.id", index=True)
    contributed_by_username: str = SQLModelField(description="Username who contributed")
    contribution_type: str = SQLModelField(description="Type: edit, comment, rating")
    content: Optional[str] = SQLModelField(default=None, sa_column=Column(Text), description="Contribution content")
    contributed_at_utc: datetime = SQLModelField(default_factory=lambda: datetime.now(timezone.utc))
    
    tip: "SharedTip" = Relationship(back_populates="tip_contributions")


class TipComment(SQLModel, table=True):
    """Comments on shared tips."""
    __tablename__ = "tip_comments"
    
    id: Optional[int] = SQLModelField(default=None, primary_key=True)
    tip_id: int = SQLModelField(foreign_key="shared_tips.id", index=True, description="Tip this comment belongs to")
    commented_by_username: str = SQLModelField(index=True, description="Username who posted the comment")
    content: str = SQLModelField(sa_column=Column(Text), description="Comment content")
    is_question: bool = SQLModelField(default=False, index=True, description="Whether this is a question")
    is_resolved: bool = SQLModelField(default=False, description="Whether question is resolved")
    created_at_utc: datetime = SQLModelField(default_factory=lambda: datetime.now(timezone.utc))
    updated_at_utc: datetime = SQLModelField(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column_kwargs={"onupdate": lambda: datetime.now(timezone.utc)}
    )
    
    # Relationships
    tip: "SharedTip" = Relationship(back_populates="tip_comments")


# --- FAQ and Chatbot Database Models ---
class FAQEntry(SQLModel, table=True):
    """FAQ entry database table."""
    __tablename__ = "faq_entries"
    
    id: Optional[int] = SQLModelField(default=None, primary_key=True)
    question: str = SQLModelField(index=True, description="FAQ question")
    answer: str = SQLModelField(sa_column=Column(Text), description="FAQ answer")
    keywords: Optional[str] = SQLModelField(default=None, description="Comma-separated keywords for matching")
    category: Optional[str] = SQLModelField(default=None, index=True, description="FAQ category")
    tags: Optional[str] = SQLModelField(default=None, description="Comma-separated tags")
    
    # Related resources
    related_document_ids: Optional[str] = SQLModelField(default=None, description="Comma-separated knowledge document IDs")
    related_tip_ids: Optional[str] = SQLModelField(default=None, description="Comma-separated shared tip IDs")
    
    # Metadata
    created_by_username: str = SQLModelField(index=True, description="Username who created")
    created_at_utc: datetime = SQLModelField(default_factory=lambda: datetime.now(timezone.utc))
    updated_at_utc: datetime = SQLModelField(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column_kwargs={"onupdate": lambda: datetime.now(timezone.utc)}
    )
    view_count: int = SQLModelField(default=0, description="Number of times this FAQ was viewed")
    helpful_count: int = SQLModelField(default=0, description="Number of helpful votes")
    is_active: bool = SQLModelField(default=True, index=True, description="Whether FAQ is active")


class ChatbotInteraction(SQLModel, table=True):
    """Chatbot interaction tracking for analytics."""
    __tablename__ = "chatbot_interactions"
    
    id: Optional[int] = SQLModelField(default=None, primary_key=True)
    user_id: Optional[int] = SQLModelField(default=None, foreign_key="users.id", index=True, description="User who made the query")
    query: str = SQLModelField(description="User's query text")
    matched_faq_ids: Optional[str] = SQLModelField(default=None, description="Comma-separated FAQ IDs that matched")
    selected_faq_id: Optional[int] = SQLModelField(default=None, foreign_key="faq_entries.id", description="FAQ that user selected")
    was_helpful: Optional[bool] = SQLModelField(default=None, description="Whether the response was helpful")
    created_at_utc: datetime = SQLModelField(default_factory=lambda: datetime.now(timezone.utc), index=True)