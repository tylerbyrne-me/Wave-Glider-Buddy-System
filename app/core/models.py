from pydantic import BaseModel, field_validator, Field
from typing import Optional, List
from enum import Enum

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

class UserInDB(User):
    hashed_password: str

class Token(BaseModel):
    access_token: str
    token_type: str