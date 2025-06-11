from typing import Optional, Dict
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer

from app.core.models import User, UserInDB, UserRoleEnum, UserCreate # Added UserCreate
from app.core.security import pwd_context, decode_access_token, SECRET_KEY, ALGORITHM, TokenData # TokenData imported from here
import logging

logger = logging.getLogger(__name__)

# --- In-Memory User Store (Replace with DB in Production) ---
# Passwords should be hashed before storing.
# Example: print(get_password_hash("adminpass")) -> store the result
# Example: print(get_password_hash("pilotpass")) -> store the result

FAKE_USERS_DB: Dict[str, UserInDB] = {
    "adminuser": UserInDB(
        username="adminuser",
        full_name="Admin User",
        email="admin@example.com",
        hashed_password=pwd_context.hash("adminpass"), # Store hashed password
        disabled=False,
        role=UserRoleEnum.admin,
    ),
    "pilotuser": UserInDB(
        username="pilotuser",
        full_name="Pilot User",
        email="pilot@example.com",
        hashed_password=pwd_context.hash("pilotpass"), # Store hashed password
        disabled=False,
        role=UserRoleEnum.pilot,
    ),
    "pilot_rt_only": UserInDB(
        username="pilot_rt_only",
        full_name="Realtime Pilot",
        email="pilot_rt@example.com",
        hashed_password=pwd_context.hash("pilotrtpass"),
        disabled=False,
        role=UserRoleEnum.pilot,
    )
}

def get_user_from_db(username: str) -> Optional[UserInDB]:
    if username in FAKE_USERS_DB:
        return FAKE_USERS_DB[username]
    return None

def add_user_to_db(user_create: UserCreate) -> UserInDB:
    if user_create.username in FAKE_USERS_DB:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered"
        )
    hashed_password = pwd_context.hash(user_create.password)
    user_in_db = UserInDB(
        username=user_create.username,
        full_name=user_create.full_name,
        email=user_create.email,
        hashed_password=hashed_password,
        role=user_create.role, # Defaults to pilot in UserCreate model
        disabled=False
    )
    FAKE_USERS_DB[user_create.username] = user_in_db
    return user_in_db

# --- OAuth2 Scheme ---
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token") # Relative to your app's root

# --- Dependency Functions ---
async def get_current_user_token_data(token: str = Depends(oauth2_scheme)) -> TokenData:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    token_data = decode_access_token(token)
    if token_data is None or token_data.username is None:
        logger.warning(f"Token decoding failed or username missing in token.")
        raise credentials_exception
    return token_data


async def get_current_user(token_data: TokenData = Depends(get_current_user_token_data)) -> User:
    user_in_db = get_user_from_db(token_data.username)
    if user_in_db is None:
        logger.warning(f"User '{token_data.username}' not found in DB from token.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # Convert UserInDB to User (excluding hashed_password for API responses)
    user_data = user_in_db.model_dump(exclude={"hashed_password"})
    return User(**user_data)


async def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    if current_user.disabled:
        logger.warning(f"User '{current_user.username}' is inactive.")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Inactive user")
    return current_user


async def get_current_admin_user(current_user: User = Depends(get_current_active_user)) -> User:
    if current_user.role != UserRoleEnum.admin:
        logger.warning(f"User '{current_user.username}' is not an admin. Access denied.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The user doesn't have enough privileges (Admin role required)",
        )
    return current_user


async def get_current_pilot_user(current_user: User = Depends(get_current_active_user)) -> User:
    if current_user.role != UserRoleEnum.pilot:
        logger.warning(f"User '{current_user.username}' is not a pilot. Access denied.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The user doesn't have enough privileges (Pilot role required)",
        )
    # Further pilot-specific checks could go here if needed
    return current_user

# New dependency to optionally get the current user without raising 401
async def get_optional_current_user(request: Request) -> Optional[User]:
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        return None
    
    # scheme, param = get_authorization_scheme_param(auth_header) # fastapi.security.utils
    # For simplicity, assuming "Bearer <token>" format
    parts = auth_header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1]

    token_data = decode_access_token(token)
    if not token_data or not token_data.username:
        return None
    
    user_in_db = get_user_from_db(token_data.username)
    if not user_in_db or user_in_db.disabled: # Check if user is disabled
        return None
    
    user_data = user_in_db.model_dump(exclude={"hashed_password"})
    return User(**user_data)
