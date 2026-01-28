"""
Models package for the Wave Glider Buddy System.

This package contains all data models organized by type:
- enums.py: Enum definitions
- database.py: SQLModel database tables
- schemas.py: Pydantic request/response models

For backward compatibility, all models are re-exported from this __init__.py.
You can import models as:
    from app.core.models import UserInDB, UserCreate, ReportTypeEnum
    
Or import directly from submodules:
    from app.core.models.enums import ReportTypeEnum
    from app.core.models.database import UserInDB
    from app.core.models.schemas import UserCreate
"""

# Import everything from submodules for backward compatibility
from .enums import (
    ReportTypeEnum,
    SourceEnum,
    UserRoleEnum,
    PayPeriodStatusEnum,
    TimesheetStatusEnum,
    FormItemTypeEnum,
    JobStatusEnum,
)

# Import database models
from .database import (
    UserInDB,
    StationMetadata,
    OffloadLog,
    OffloadLogBase,
    FieldSeason,
    ShiftAssignment,
    UserUnavailability,
    PayPeriod,
    Timesheet,
    MissionOverview,
    MissionMedia,
    MissionGoal,
    MissionNote,
    SensorTrackerOutbox,
    SensorTrackerDeployment,
    MissionInstrument,
    MissionSensor,
    LiveKMLToken,
    SubmittedForm,
    Announcement,
    AnnouncementAcknowledgement,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    UserNote,
    SharedTip,
    TipContribution,
    TipComment,
    FAQEntry,
    ChatbotInteraction,
)

# Import Pydantic schemas
from .schemas import (
    # Report/Data params
    ReportDataParams,
    ForecastParams,
    ReportGenerationOptions,
    MissionReportFile,
    MissionReportListResponse,
    
    # User models
    UserBase,
    UserCreate,
    User,
    UserUpdateForAdmin,
    PasswordUpdate,
    Token,
    
    # Station metadata models
    StationMetadataCore,
    StationMetadataBase,
    StationMetadataCreate,
    StationMetadataUpdate,
    StationMetadataRead,
    StationMetadataReadWithLogs,
    StationMetadataCreateResponse,
    
    # Offload log models
    OffloadLogCreate,
    OffloadLogRead,
    
    # Field season models
    FieldSeasonCreate,
    FieldSeasonRead,
    FieldSeasonUpdate,
    FieldSeasonSummary,
    SeasonCloseRequest,
    MasterListExport,
    
    # Form models
    FormItem,
    FormSection,
    MissionFormSchema,
    MissionFormDataCreate,
    MissionFormDataResponse,
    
    # Schedule models
    ScheduleEvent,
    ScheduleEventCreate,
    LRIBlockCreate,
    UserUnavailabilityBase,
    UserUnavailabilityCreate,
    UserUnavailabilityResponse,
    
    # Pay period and timesheet models
    PayPeriodCreate,
    PayPeriodUpdate,
    MonthlyChartData,
    TimesheetCreate,
    TimesheetUpdate,
    TimesheetStatusForUser,
    TimesheetRead,
    
    # Mission info models
    MissionOverviewUpdate,
    MissionMediaUpdate,
    MissionMediaRead,
    MissionGoalCreate,
    MissionGoalUpdate,
    MissionNoteCreate,
    MissionInfoResponse,
    SensorTrackerOutboxRead,
    SensorTrackerOutboxReject,
    
    # Announcement models
    AnnouncementCreate,
    AnnouncementRead,
    AnnouncementReadForUser,
    AcknowledgedByInfo,
    AnnouncementReadWithAcks,
    
    # Home page models
    UpcomingShift,
    MyTimesheetStatus,
    MissionGoalToggle,
    JobTriggerInfo,
    ScheduledJob,
    
    # Other models
    PicHandoffLinkInfo,
    
    # Knowledge base models
    KnowledgeDocumentCreate,
    KnowledgeDocumentUpdate,
    KnowledgeDocumentRead,
    KnowledgeDocumentUploadResponse,
    UserNoteCreate,
    UserNoteUpdate,
    UserNoteRead,
    SharedTipCreate,
    SharedTipUpdate,
    SharedTipRead,
    TipCommentCreate,
    TipCommentUpdate,
    TipCommentRead,
    CategoryInfo,
    CategoriesResponse,
    FAQEntryCreate,
    FAQEntryUpdate,
    FAQEntryRead,
    ChatbotQueryRequest,
    ChatbotResponse,
    ChatbotFeedbackRequest,
    RelatedResource,
)

# Import error analysis models
from .error_analysis import (
    ErrorSeverityEnum,
    ClassifiedError,
    ErrorCategoryStats,
    ErrorPattern,
    ErrorClassificationResponse,
    ErrorTrendData,
    ErrorDashboardSummary,
    ErrorCategoryEnum,
)

__all__ = [
    # Enums
    "ReportTypeEnum",
    "SourceEnum",
    "UserRoleEnum",
    "PayPeriodStatusEnum",
    "TimesheetStatusEnum",
    "FormItemTypeEnum",
    "JobStatusEnum",
    
    # Database models
    "UserInDB",
    "StationMetadata",
    "OffloadLog",
    "OffloadLogBase",
    "FieldSeason",
    "ShiftAssignment",
    "UserUnavailability",
    "PayPeriod",
    "Timesheet",
    "MissionOverview",
    "MissionMedia",
    "MissionGoal",
    "MissionNote",
    "SensorTrackerOutbox",
    "SensorTrackerDeployment",
    "MissionInstrument",
    "MissionSensor",
    "LiveKMLToken",
    "SubmittedForm",
    "Announcement",
    "AnnouncementAcknowledgement",
    "KnowledgeDocument",
    "KnowledgeDocumentVersion",
    "UserNote",
    "SharedTip",
    "TipContribution",
    "TipComment",
    "FAQEntry",
    "ChatbotInteraction",
    
    # Pydantic schemas (add all schema names here)
    "ReportDataParams",
    "ForecastParams",
    "ReportGenerationOptions",
    "MissionReportFile",
    "MissionReportListResponse",
    "UserBase",
    "UserCreate",
    "User",
    "UserUpdateForAdmin",
    "PasswordUpdate",
    "Token",
    "StationMetadataCore",
    "StationMetadataBase",
    "StationMetadataCreate",
    "StationMetadataUpdate",
    "StationMetadataRead",
    "StationMetadataReadWithLogs",
    "StationMetadataCreateResponse",
    "OffloadLogCreate",
    "OffloadLogRead",
    "FieldSeasonCreate",
    "FieldSeasonRead",
    "FieldSeasonUpdate",
    "FieldSeasonSummary",
    "SeasonCloseRequest",
    "MasterListExport",
    "FormItem",
    "FormSection",
    "MissionFormSchema",
    "MissionFormDataCreate",
    "MissionFormDataResponse",
    "ScheduleEvent",
    "ScheduleEventCreate",
    "LRIBlockCreate",
    "UserUnavailabilityBase",
    "UserUnavailabilityCreate",
    "UserUnavailabilityResponse",
    "PayPeriodCreate",
    "PayPeriodUpdate",
    "MonthlyChartData",
    "TimesheetCreate",
    "TimesheetUpdate",
    "TimesheetStatusForUser",
    "TimesheetRead",
    "MissionOverviewUpdate",
    "MissionMediaUpdate",
    "MissionMediaRead",
    "MissionGoalCreate",
    "MissionGoalUpdate",
    "MissionNoteCreate",
    "MissionInfoResponse",
    "SensorTrackerOutboxRead",
    "SensorTrackerOutboxReject",
    "AnnouncementCreate",
    "AnnouncementRead",
    "AnnouncementReadForUser",
    "AcknowledgedByInfo",
    "AnnouncementReadWithAcks",
    "UpcomingShift",
    "MyTimesheetStatus",
    "MissionGoalToggle",
    "JobTriggerInfo",
    "ScheduledJob",
    "PicHandoffLinkInfo",
    "KnowledgeDocumentCreate",
    "KnowledgeDocumentUpdate",
    "KnowledgeDocumentRead",
    "KnowledgeDocumentUploadResponse",
    "UserNoteCreate",
    "UserNoteUpdate",
    "UserNoteRead",
    "SharedTipCreate",
    "SharedTipUpdate",
    "SharedTipRead",
    "TipCommentCreate",
    "TipCommentUpdate",
    "TipCommentRead",
    "CategoryInfo",
    "CategoriesResponse",
    "FAQEntryCreate",
    "FAQEntryUpdate",
    "FAQEntryRead",
    "ChatbotQueryRequest",
    "ChatbotResponse",
    "ChatbotFeedbackRequest",
    "RelatedResource",
    
    # Error analysis models
    "ErrorSeverityEnum",
    "ClassifiedError",
    "ErrorCategoryStats",
    "ErrorPattern",
    "ErrorClassificationResponse",
    "ErrorTrendData",
    "ErrorDashboardSummary",
    "ErrorCategoryEnum",
]

