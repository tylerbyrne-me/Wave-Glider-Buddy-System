from pydantic import BaseModel, field_validator, Field
from typing import Optional, List
from enum import Enum # type: ignore
import datetime # Import the datetime module
from sqlmodel import Field as SQLModelField, SQLModel, JSON, Column # type: ignore


VALID_REPORT_TYPES = [
    "power", "ctd", "weather", "waves", "telemetry",
    "ais", "errors", "vr2c", "fluorometer", "solar"
]

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

class SourceEnum(str, Enum):
    local = "local"
    remote = "remote"

class ReportDataParams(BaseModel):
    # Path parameters are handled by FastAPI directly in the function signature
    # Query parameters:
    hours_back: int = Field(72, gt=0, le=8760) # e.g. 1 year max
    source: Optional[SourceEnum] = None
    local_path: Optional[str] = None
    refresh: bool = False

    @field_validator("local_path")
    def local_path_rules(cls, v, values):
        # If source is 'local' and local_path is provided, it should not be empty.
        # This is a soft validation as the main logic handles default paths.
        # More complex validation (e.g. path existence) is better handled in the endpoint logic.
        if values.data.get('source') == SourceEnum.local and v is not None and not v.strip():
            raise ValueError("local_path cannot be empty if provided and source is 'local'")
        return v

class ForecastParams(BaseModel):
    # Path parameters are handled by FastAPI directly
    # Query parameters:
    lat: Optional[float] = Field(None, ge=-90, le=90)
    lon: Optional[float] = Field(None, ge=-180, le=180)
    source: Optional[SourceEnum] = None # For telemetry lookup
    local_path: Optional[str] = None # For telemetry lookup
    refresh: bool = False # For telemetry lookup
    force_marine: Optional[bool] = False

    @field_validator("local_path")
    def forecast_local_path_rules(cls, v, values):
        if values.data.get('source') == SourceEnum.local and v is not None and not v.strip():
            raise ValueError("local_path cannot be empty if provided and source is 'local' for telemetry lookup")
        return v

    @field_validator("lon")
    def check_lon_with_lat(cls, v, values):
        # If one of lat/lon is provided, the other should also be (or neither for telemetry lookup)
        lat_val = values.data.get('lat')
        if (lat_val is not None and v is None) or (lat_val is None and v is not None):
            raise ValueError("If 'lat' is provided, 'lon' must also be provided, and vice-versa.")
        return v

# --- User Authentication Models ---
class UserRoleEnum(str, Enum):
    admin = "admin"
    pilot = "pilot"

class UserBase(BaseModel):
    username: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    role: UserRoleEnum = UserRoleEnum.pilot # Default role

class UserCreate(UserBase):
    password: str

class User(UserBase):
    disabled: Optional[bool] = None

# UserInDB will now be our SQLModel table for users
class UserInDB(SQLModel, table=True): # Inherit from SQLModel
    __tablename__ = "users" # Explicit table name

    id: Optional[int] = SQLModelField(default=None, primary_key=True)
    username: str = SQLModelField(unique=True, index=True)
    email: Optional[str] = SQLModelField(default=None, unique=True, index=True) # Made email unique and indexable
    full_name: Optional[str] = SQLModelField(default=None)
    hashed_password: str = SQLModelField()
    role: UserRoleEnum = SQLModelField(default=UserRoleEnum.pilot) # Role is now an SQLModelField
    disabled: Optional[bool] = SQLModelField(default=False)

class UserUpdateForAdmin(BaseModel): # New model for admin updates
    full_name: Optional[str] = None
    email: Optional[str] = None
    role: Optional[UserRoleEnum] = None
    disabled: Optional[bool] = None

class PasswordUpdate(BaseModel): # New model for password change
    new_password: str

class Token(BaseModel):
    access_token: str
    token_type: str

# --- Form Models ---
class FormItemTypeEnum(str, Enum):
    CHECKBOX = "checkbox"
    TEXT_INPUT = "text_input"
    TEXT_AREA = "text_area"
    AUTOFILLED_VALUE = "autofilled_value" # For values auto-populated from mission data
    STATIC_TEXT = "static_text" # For instructions or non-interactive text
    DROPDOWN = "dropdown" # New type for dropdown lists

class FormItem(BaseModel):
    id: str # Unique ID for the form item within the form
    label: str
    item_type: FormItemTypeEnum
    value: Optional[str] = None # For text_input, text_area, autofilled_value
    is_verified: Optional[bool] = None # For the new "verified" column 3 checkbox
    is_checked: Optional[bool] = None # For checkbox
    comment: Optional[str] = None # Optional comment for any item
    required: bool = False
    options: Optional[List[str]] = None # For dropdown
    placeholder: Optional[str] = None # For text_input, text_area

class FormSection(BaseModel):
    id: str # Unique ID for the section
    title: str
    items: List[FormItem]
    section_comment: Optional[str] = None

class MissionFormSchema(BaseModel): # Defines the structure/template of a form
    form_type: str # e.g., "pre_deployment_checklist", "mission_log_entry"
    title: str
    description: Optional[str] = None
    sections: List[FormSection]

class MissionFormDataCreate(BaseModel): # Payload for submitting form data
    mission_id: str
    form_type: str
    form_title: str # Title of the form instance, could be same as schema title or customized
    sections_data: List[FormSection] # The actual filled-out data

class MissionFormDataResponse(MissionFormDataCreate): # What's stored and returned
    submitted_by_username: str
    submission_timestamp: datetime.datetime # Specify the class from the module

# --- Database Model for Submitted Forms ---
class SubmittedForm(SQLModel, table=True):
    __tablename__ = "submitted_forms" # Explicit table name

    id: Optional[int] = SQLModelField(default=None, primary_key=True)
    mission_id: str = SQLModelField(index=True)
    form_type: str = SQLModelField(index=True)
    form_title: str

    # Store sections_data as a JSONB/JSON column in the database
    # Pydantic List[FormSection] will be converted to JSON string for storage
    # and parsed back when reading. By typing it as List[dict] here, we ensure
    # that SQLAlchemy's JSON serializer receives a directly serializable type.
    sections_data: List[dict] = SQLModelField(sa_column=Column(JSON))

    submitted_by_username: str = SQLModelField(index=True)
    submission_timestamp: datetime.datetime