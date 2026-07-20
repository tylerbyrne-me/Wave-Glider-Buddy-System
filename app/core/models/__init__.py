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
    FormItemTypeEnum,
    JobStatusEnum,
)

# Import database models
from .database import (
    UserInDB,
    StationMetadata,
    StationMetadataSeasonSnapshot,
    StationArrayGroup,
    StationHardwareHistory,
    OffloadLog,
    OffloadLogBase,
    StationFlagEvent,
    Vm4ProcessingCheckpoint,
    FieldSeason,
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
    SlocumDeployment,
    SlocumDeploymentGoal,
    SlocumDeploymentNote,
    SlocumDeploymentMedia,
    SlocumSfmcSnapshot,
)

# Import Pydantic schemas
from .schemas import (
    # Report/Data params
    ReportDataParams,
    ForecastParams,
    ESSWaypointsRequest,
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
    OffloadLogUpdate,
    ConflictResolutionRequest,
    StationFlagUpdateRequest,
    StationFlagEventRead,
    StationHardwareSwapRequest,
    OffloadLogRead,
    StationHardwareHistoryRead,
    
    # Field season models
    FieldSeasonCreate,
    FieldSeasonRead,
    FieldSeasonUpdate,
    FieldSeasonSummary,
    SeasonCloseRequest,
    MasterListExport,
    StationArrayGroupRead,
    StationArrayGroupUpdate,
    
    # Form models
    FormItem,
    FormSection,
    MissionFormSchema,
    MissionFormDataCreate,
    MissionFormDataResponse,
    
    # Mission info models
    MissionOverviewUpdate,
    MissionMediaUpdate,
    MissionMediaRead,
    MissionGoalCreate,
    MissionGoalUpdate,
    MissionNoteCreate,
    MissionNoteUpdate,
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
    MissionGoalToggle,
    JobTriggerInfo,
    ScheduledJob,
    
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
    "FormItemTypeEnum",
    "JobStatusEnum",
    
    # Database models
    "UserInDB",
    "StationMetadata",
    "StationMetadataSeasonSnapshot",
    "StationArrayGroup",
    "StationHardwareHistory",
    "OffloadLog",
    "OffloadLogBase",
    "StationFlagEvent",
    "Vm4ProcessingCheckpoint",
    "FieldSeason",
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
    "SlocumDeployment",
    "SlocumDeploymentGoal",
    "SlocumDeploymentNote",
    "SlocumDeploymentMedia",
    "SlocumSfmcSnapshot",
    
    # Pydantic schemas (add all schema names here)
    "ReportDataParams",
    "ForecastParams",
    "ESSWaypointsRequest",
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
    "OffloadLogUpdate",
    "ConflictResolutionRequest",
    "StationFlagUpdateRequest",
    "StationFlagEventRead",
    "StationHardwareSwapRequest",
    "OffloadLogRead",
    "StationHardwareHistoryRead",
    "FieldSeasonCreate",
    "FieldSeasonRead",
    "FieldSeasonUpdate",
    "FieldSeasonSummary",
    "SeasonCloseRequest",
    "MasterListExport",
    "StationArrayGroupRead",
    "StationArrayGroupUpdate",
    "FormItem",
    "FormSection",
    "MissionFormSchema",
    "MissionFormDataCreate",
    "MissionFormDataResponse",
    "MissionOverviewUpdate",
    "MissionMediaUpdate",
    "MissionMediaRead",
    "MissionGoalCreate",
    "MissionGoalUpdate",
    "MissionNoteCreate",
    "MissionNoteUpdate",
    "MissionInfoResponse",
    "SensorTrackerOutboxRead",
    "SensorTrackerOutboxReject",
    "AnnouncementCreate",
    "AnnouncementRead",
    "AnnouncementReadForUser",
    "AcknowledgedByInfo",
    "AnnouncementReadWithAcks",
    "MissionGoalToggle",
    "JobTriggerInfo",
    "ScheduledJob",
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

