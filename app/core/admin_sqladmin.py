"""
SQLAdmin configuration and setup.

This module configures SQLAdmin for database administration.
SQLAdmin provides a powerful admin interface for SQLAlchemy/SQLModel models.

FOCUS: Core operational models - Users, Stations, Missions, Timesheets, Payroll
"""

import logging
from fastapi import FastAPI
from sqladmin import Admin, ModelView
from sqlmodel import Session as SQLModelSession

from app.core.admin_auth import create_sqladmin_auth_backend
from app.core.db import sqlite_engine
from app.config import settings
from app.core.models.database import (
    Announcement,
    AnnouncementAcknowledgement,
    ChatbotInteraction,
    FAQEntry,
    FieldSeason,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    LiveKMLToken,
    MissionGoal,
    MissionInstrument,
    MissionMedia,
    MissionNote,
    MissionOverview,
    MissionSensor,
    OffloadLog,
    PayPeriod,
    SensorTrackerDeployment,
    SensorTrackerOutbox,
    SharedTip,
    ShiftAssignment,
    StationMetadata,
    SubmittedForm,
    Timesheet,
    TipComment,
    TipContribution,
    UserInDB,
    UserNote,
    UserUnavailability,
)

logger = logging.getLogger(__name__)

# Admin instance is created only inside setup_sqladmin(app) at startup.
# Do NOT instantiate Admin here - it requires the FastAPI app as first argument.


# Define Model Views for SQLAdmin
class UserAdmin(ModelView, model=UserInDB):
    """Admin view for User management."""
    column_list = [
        UserInDB.id,
        UserInDB.username,
        UserInDB.email,
        UserInDB.full_name,
        UserInDB.role,
        UserInDB.disabled,
    ]
    column_searchable_list = [UserInDB.username, UserInDB.email]
    column_sortable_list = [UserInDB.id, UserInDB.username, UserInDB.role]
    form_excluded_columns = [UserInDB.hashed_password, UserInDB.sensor_tracker_token]
    name = "User"
    name_plural = "Users"
    icon = "fa fa-users"


class StationMetadataAdmin(ModelView, model=StationMetadata):
    """Admin view for Station Metadata."""
    column_list = [
        StationMetadata.station_id,
        StationMetadata.serial_number,
        StationMetadata.deployment_latitude,
        StationMetadata.deployment_longitude,
        StationMetadata.field_season_year,
        StationMetadata.is_archived,
    ]
    column_searchable_list = [StationMetadata.station_id, StationMetadata.serial_number]
    column_sortable_list = [StationMetadata.station_id, StationMetadata.field_season_year]
    name = "Station"
    name_plural = "Stations"
    icon = "fa fa-map-marker"


class OffloadLogAdmin(ModelView, model=OffloadLog):
    """Admin view for Offload Logs."""
    column_list = [
        OffloadLog.id,
        OffloadLog.station_id,
        OffloadLog.logged_by_username,
        OffloadLog.was_offloaded,
        OffloadLog.log_timestamp_utc,
    ]
    column_searchable_list = [OffloadLog.station_id, OffloadLog.logged_by_username]
    column_sortable_list = [OffloadLog.log_timestamp_utc, OffloadLog.station_id]
    name = "Offload Log"
    name_plural = "Offload Logs"
    icon = "fa fa-list"


class FieldSeasonAdmin(ModelView, model=FieldSeason):
    """Admin view for Field Seasons."""
    column_list = [
        FieldSeason.id,
        FieldSeason.year,
        FieldSeason.is_active,
        FieldSeason.closed_at_utc,
        FieldSeason.created_at_utc,
    ]
    column_sortable_list = [FieldSeason.year, FieldSeason.is_active]
    name = "Field Season"
    name_plural = "Field Seasons"
    icon = "fa fa-calendar"


class MissionOverviewAdmin(ModelView, model=MissionOverview):
    """Admin view for Mission Overviews."""
    column_list = [
        MissionOverview.mission_id,
        MissionOverview.weekly_report_url,
        MissionOverview.end_of_mission_report_url,
        MissionOverview.created_at_utc,
        MissionOverview.updated_at_utc,
    ]
    column_searchable_list = [MissionOverview.mission_id]
    column_sortable_list = [MissionOverview.mission_id, MissionOverview.created_at_utc]
    name = "Mission Overview"
    name_plural = "Mission Overviews"
    icon = "fa fa-ship"


class MissionMediaAdmin(ModelView, model=MissionMedia):
    """Admin view for Mission Media."""
    column_list = [
        MissionMedia.id,
        MissionMedia.mission_id,
        MissionMedia.media_type,
        MissionMedia.file_name,
        MissionMedia.uploaded_by_username,
        MissionMedia.uploaded_at_utc,
        MissionMedia.approval_status,
    ]
    column_searchable_list = [MissionMedia.mission_id, MissionMedia.file_name]
    column_sortable_list = [MissionMedia.uploaded_at_utc, MissionMedia.mission_id]
    name = "Mission Media"
    name_plural = "Mission Media"
    icon = "fa fa-image"


class MissionGoalAdmin(ModelView, model=MissionGoal):
    """Admin view for Mission Goals."""
    column_list = [
        MissionGoal.id,
        MissionGoal.mission_id,
        MissionGoal.description,
        MissionGoal.is_completed,
        MissionGoal.created_at_utc,
    ]
    column_searchable_list = [MissionGoal.mission_id, MissionGoal.description]
    column_sortable_list = [MissionGoal.mission_id, MissionGoal.is_completed]
    name = "Mission Goal"
    name_plural = "Mission Goals"
    icon = "fa fa-check-square"


class MissionNoteAdmin(ModelView, model=MissionNote):
    """Admin view for Mission Notes."""
    column_list = [
        MissionNote.id,
        MissionNote.mission_id,
        MissionNote.created_by_username,
        MissionNote.created_at_utc,
    ]
    column_searchable_list = [MissionNote.mission_id, MissionNote.created_by_username]
    column_sortable_list = [MissionNote.created_at_utc, MissionNote.mission_id]
    name = "Mission Note"
    name_plural = "Mission Notes"
    icon = "fa fa-sticky-note"


class ShiftAssignmentAdmin(ModelView, model=ShiftAssignment):
    """Admin view for Shift Assignments."""
    column_list = [
        ShiftAssignment.id,
        ShiftAssignment.user_id,
        ShiftAssignment.start_time_utc,
        ShiftAssignment.end_time_utc,
        ShiftAssignment.resource_id,
    ]
    column_sortable_list = [ShiftAssignment.start_time_utc, ShiftAssignment.user_id]
    name = "Shift Assignment"
    name_plural = "Shift Assignments"
    icon = "fa fa-clock"


class PayPeriodAdmin(ModelView, model=PayPeriod):
    """Admin view for Pay Periods."""
    column_list = [
        PayPeriod.id,
        PayPeriod.name,
        PayPeriod.start_date,
        PayPeriod.end_date,
        PayPeriod.status,
    ]
    column_sortable_list = [PayPeriod.start_date, PayPeriod.status]
    name = "Pay Period"
    name_plural = "Pay Periods"
    icon = "fa fa-calendar-check"


class TimesheetAdmin(ModelView, model=Timesheet):
    """Admin view for Timesheets."""
    column_list = [
        Timesheet.id,
        Timesheet.user_id,
        Timesheet.pay_period_id,
        Timesheet.calculated_hours,
        Timesheet.adjusted_hours,
        Timesheet.status,
        Timesheet.submission_timestamp,
    ]
    column_sortable_list = [Timesheet.submission_timestamp, Timesheet.status]
    name = "Timesheet"
    name_plural = "Timesheets"
    icon = "fa fa-file-text"


class AnnouncementAdmin(ModelView, model=Announcement):
    """Admin view for Announcements."""
    column_list = [
        Announcement.id,
        Announcement.content,
        Announcement.created_by_username,
        Announcement.announcement_type,
        Announcement.is_active,
        Announcement.created_at_utc,
    ]
    column_searchable_list = [Announcement.content, Announcement.created_by_username]
    column_sortable_list = [Announcement.created_at_utc, Announcement.is_active]
    name = "Announcement"
    name_plural = "Announcements"
    icon = "fa fa-bullhorn"


class KnowledgeDocumentAdmin(ModelView, model=KnowledgeDocument):
    """Admin view for Knowledge Documents."""
    column_list = [
        KnowledgeDocument.id,
        KnowledgeDocument.title,
        KnowledgeDocument.category,
        KnowledgeDocument.file_type,
        KnowledgeDocument.access_level,
        KnowledgeDocument.uploaded_by_username,
        KnowledgeDocument.uploaded_at_utc,
    ]
    column_searchable_list = [KnowledgeDocument.title, KnowledgeDocument.category]
    column_sortable_list = [KnowledgeDocument.uploaded_at_utc, KnowledgeDocument.category]
    name = "Knowledge Document"
    name_plural = "Knowledge Documents"
    icon = "fa fa-book"


class SharedTipAdmin(ModelView, model=SharedTip):
    """Admin view for Shared Tips."""
    column_list = [
        SharedTip.id,
        SharedTip.title,
        SharedTip.category,
        SharedTip.created_by_username,
        SharedTip.is_pinned,
        SharedTip.is_archived,
        SharedTip.created_at_utc,
    ]
    column_searchable_list = [SharedTip.title, SharedTip.category]
    column_sortable_list = [SharedTip.created_at_utc, SharedTip.is_pinned]
    name = "Shared Tip"
    name_plural = "Shared Tips"
    icon = "fa fa-lightbulb"


class FAQEntryAdmin(ModelView, model=FAQEntry):
    """Admin view for FAQ Entries."""
    column_list = [
        FAQEntry.id,
        FAQEntry.question,
        FAQEntry.category,
        FAQEntry.is_active,
        FAQEntry.view_count,
        FAQEntry.created_at_utc,
    ]
    column_searchable_list = [FAQEntry.question, FAQEntry.category]
    column_sortable_list = [FAQEntry.created_at_utc, FAQEntry.view_count]
    name = "FAQ Entry"
    name_plural = "FAQ Entries"
    icon = "fa fa-question-circle"


class SensorTrackerDeploymentAdmin(ModelView, model=SensorTrackerDeployment):
    """Admin view for Sensor Tracker Deployments."""
    column_list = [
        SensorTrackerDeployment.id,
        SensorTrackerDeployment.mission_id,
        SensorTrackerDeployment.deployment_number,
        SensorTrackerDeployment.title,
        SensorTrackerDeployment.sync_status,
        SensorTrackerDeployment.last_synced_at,
    ]
    column_searchable_list = [SensorTrackerDeployment.mission_id, SensorTrackerDeployment.title]
    column_sortable_list = [SensorTrackerDeployment.mission_id, SensorTrackerDeployment.last_synced_at]
    name = "Sensor Tracker Deployment"
    name_plural = "Sensor Tracker Deployments"
    icon = "fa fa-database"


class SensorTrackerOutboxAdmin(ModelView, model=SensorTrackerOutbox):
    """Admin view for Sensor Tracker Outbox."""
    column_list = [
        SensorTrackerOutbox.id,
        SensorTrackerOutbox.mission_id,
        SensorTrackerOutbox.entity_type,
        SensorTrackerOutbox.status,
        SensorTrackerOutbox.created_at_utc,
        SensorTrackerOutbox.updated_at_utc,
    ]
    column_searchable_list = [SensorTrackerOutbox.mission_id, SensorTrackerOutbox.entity_type]
    column_sortable_list = [SensorTrackerOutbox.created_at_utc, SensorTrackerOutbox.status]
    name = "Sensor Tracker Outbox"
    name_plural = "Sensor Tracker Outbox"
    icon = "fa fa-inbox"


class UserNoteAdmin(ModelView, model=UserNote):
    """Admin view for User Notes."""
    column_list = [
        UserNote.id,
        UserNote.user_id,
        UserNote.title,
        UserNote.category,
        UserNote.is_pinned,
        UserNote.created_at_utc,
    ]
    column_searchable_list = [UserNote.title, UserNote.category]
    column_sortable_list = [UserNote.created_at_utc, UserNote.is_pinned]
    name = "User Note"
    name_plural = "User Notes"
    icon = "fa fa-sticky-note"


class UserUnavailabilityAdmin(ModelView, model=UserUnavailability):
    """Admin view for User Unavailability."""
    column_list = [
        UserUnavailability.id,
        UserUnavailability.user_id,
        UserUnavailability.start_time_utc,
        UserUnavailability.end_time_utc,
        UserUnavailability.reason,
    ]
    column_sortable_list = [UserUnavailability.start_time_utc, UserUnavailability.user_id]
    name = "User Unavailability"
    name_plural = "User Unavailability"
    icon = "fa fa-calendar-times"


class SubmittedFormAdmin(ModelView, model=SubmittedForm):
    """Admin view for Submitted Forms."""
    column_list = [
        SubmittedForm.id,
        SubmittedForm.mission_id,
        SubmittedForm.form_type,
        SubmittedForm.form_title,
        SubmittedForm.submitted_by_username,
        SubmittedForm.submission_timestamp,
    ]
    column_searchable_list = [SubmittedForm.mission_id, SubmittedForm.form_type]
    column_sortable_list = [SubmittedForm.submission_timestamp, SubmittedForm.mission_id]
    name = "Submitted Form"
    name_plural = "Submitted Forms"
    icon = "fa fa-file"


class MissionInstrumentAdmin(ModelView, model=MissionInstrument):
    """Admin view for Mission Instruments."""
    column_list = [
        MissionInstrument.id,
        MissionInstrument.mission_id,
        MissionInstrument.instrument_identifier,
        MissionInstrument.instrument_serial,
        MissionInstrument.start_time,
        MissionInstrument.end_time,
    ]
    column_searchable_list = [MissionInstrument.mission_id, MissionInstrument.instrument_identifier]
    column_sortable_list = [MissionInstrument.mission_id, MissionInstrument.start_time]
    name = "Mission Instrument"
    name_plural = "Mission Instruments"
    icon = "fa fa-cog"


class MissionSensorAdmin(ModelView, model=MissionSensor):
    """Admin view for Mission Sensors."""
    column_list = [
        MissionSensor.id,
        MissionSensor.mission_id,
        MissionSensor.instrument_id,
        MissionSensor.sensor_identifier,
        MissionSensor.sensor_serial,
        MissionSensor.start_time,
        MissionSensor.end_time,
    ]
    column_searchable_list = [MissionSensor.mission_id, MissionSensor.sensor_identifier]
    column_sortable_list = [MissionSensor.mission_id, MissionSensor.start_time]
    name = "Mission Sensor"
    name_plural = "Mission Sensors"
    icon = "fa fa-microchip"


class LiveKMLTokenAdmin(ModelView, model=LiveKMLToken):
    """Admin view for Live KML Tokens."""
    column_list = [
        LiveKMLToken.token,
        LiveKMLToken.mission_ids,
        LiveKMLToken.user_id,
        LiveKMLToken.is_active,
        LiveKMLToken.expires_at,
        LiveKMLToken.access_count,
    ]
    column_searchable_list = [LiveKMLToken.token, LiveKMLToken.mission_ids]
    column_sortable_list = [LiveKMLToken.expires_at, LiveKMLToken.is_active]
    name = "Live KML Token"
    name_plural = "Live KML Tokens"
    icon = "fa fa-key"


# Register all admin views
def setup_sqladmin(app: FastAPI):
    """
    Initialize and register core operational admin views with SQLAdmin.
    
    SQLAdmin focuses on core operational models:
    - User management
    - Station operations
    - Mission operations
    - Timesheets and payroll
    - Sensor tracker integration
    
    Content/knowledge models are handled by FastAPI-Admin to avoid duplication.
    
    Args:
        app: FastAPI application instance (required for SQLAdmin initialization)
    
    This function should be called during app startup.
    """
    try:
        # Create authentication backend using app's JWT secret
        authentication_backend = create_sqladmin_auth_backend(secret_key=settings.jwt_secret_key)
        
        # Initialize SQLAdmin with the FastAPI app (app is required as first arg)
        admin = Admin(
            app=app,
            engine=sqlite_engine,
            title="Wave Glider Admin - Operations",
            authentication_backend=authentication_backend,
        )
        
        # Core operational models
        admin.add_view(UserAdmin)
        admin.add_view(StationMetadataAdmin)
        admin.add_view(OffloadLogAdmin)
        admin.add_view(FieldSeasonAdmin)
        admin.add_view(MissionOverviewAdmin)
        admin.add_view(MissionMediaAdmin)
        admin.add_view(MissionGoalAdmin)
        admin.add_view(MissionNoteAdmin)
        admin.add_view(ShiftAssignmentAdmin)
        admin.add_view(PayPeriodAdmin)
        admin.add_view(TimesheetAdmin)
        admin.add_view(UserUnavailabilityAdmin)
        admin.add_view(SubmittedFormAdmin)
        admin.add_view(MissionInstrumentAdmin)
        admin.add_view(MissionSensorAdmin)
        admin.add_view(SensorTrackerDeploymentAdmin)
        admin.add_view(SensorTrackerOutboxAdmin)
        admin.add_view(LiveKMLTokenAdmin)
        
        # Note: Announcements are operational, so keep in SQLAdmin
        admin.add_view(AnnouncementAdmin)
        
        logger.info("SQLAdmin configured successfully with core operational models")
        logger.info("SQLAdmin is admin-only and requires authentication")
        
    except Exception as e:
        logger.error(f"Error setting up SQLAdmin: {e}", exc_info=True)
        raise
