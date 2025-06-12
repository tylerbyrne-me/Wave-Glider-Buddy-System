from typing import Optional, Dict, List
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from sqlmodel import Session as SQLModelSession, select # type: ignore # Import Session and alias it

from app.core.models import User, UserInDB, UserRoleEnum, UserCreate, UserUpdateForAdmin # Added UserUpdateForAdmin
from app.core.security import pwd_context, decode_access_token, SECRET_KEY, ALGORITHM, TokenData, get_password_hash # TokenData imported from here, added get_password_hash

from app.db import get_db_session # Import the new get_db_session
import logging

logger = logging.getLogger(__name__)

# --- In-Memory User Store (Replace with DB in Production) ---
# FAKE_USERS_DB is now removed. Operations will use the database.

def get_user_from_db(session: SQLModelSession, username: str) -> Optional[UserInDB]:
    """Fetches a user from the database by username."""
    statement = select(UserInDB).where(UserInDB.username == username)
    user = session.exec(statement).first()
    return user

def list_all_users_from_db(session: SQLModelSession) -> List[User]:
    """Returns a list of all users, excluding sensitive info like hashed_password."""
    statement = select(UserInDB)
    users_in_db = session.exec(statement).all()
    users = []
    for user_in_db in users_in_db:
        user_data = user_in_db.model_dump(exclude={"hashed_password"})
        users.append(User(**user_data))
    return users

def add_user_to_db(session: SQLModelSession, user_create: UserCreate) -> UserInDB:
    """Adds a new user to the database."""
    db_user_by_username = get_user_from_db(session, user_create.username)
    if db_user_by_username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered"
        )
    
    if user_create.email:
        statement_email = select(UserInDB).where(UserInDB.email == user_create.email)
        db_user_by_email = session.exec(statement_email).first()
        if db_user_by_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered"
            )

    hashed_password = get_password_hash(user_create.password)
    user_in_db = UserInDB(
        username=user_create.username,
        full_name=user_create.full_name,
        email=user_create.email,
        hashed_password=hashed_password,
        role=user_create.role, # Defaults to pilot in UserCreate model
        disabled=False
    )
    session.add(user_in_db)
    session.commit()
    session.refresh(user_in_db)
    return user_in_db

def update_user_details_in_db(session: SQLModelSession, username: str, user_update: UserUpdateForAdmin) -> Optional[UserInDB]:
    """Updates user details in the database."""
    user_in_db = get_user_from_db(session, username)
    if not user_in_db:
        return None

    update_data = user_update.model_dump(exclude_unset=True)

    # Check for email uniqueness if email is being changed and is not None
    if "email" in update_data and update_data["email"] is not None:
        if user_in_db.email != update_data["email"]: # Email is actually changing
            statement_email = select(UserInDB).where(UserInDB.email == update_data["email"])
            existing_email_user = session.exec(statement_email).first()
            if existing_email_user and existing_email_user.username != username:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Email already registered by another user."
                )

    for field, value in update_data.items():
        setattr(user_in_db, field, value)
    
    session.add(user_in_db)
    session.commit()
    session.refresh(user_in_db)
    logger.info(f"User '{username}' details updated in DB: {update_data}")
    return user_in_db

def update_user_password_in_db(session: SQLModelSession, username: str, new_password: str) -> bool:
    """Updates a user's password in the database."""
    user_in_db = get_user_from_db(session, username)
    if not user_in_db:
        return False
    
    if user_in_db.role == UserRoleEnum.admin:
        statement = select(UserInDB).where(UserInDB.role == UserRoleEnum.admin, UserInDB.disabled == False)
        admin_users = session.exec(statement).all()
        if len(admin_users) == 1 and admin_users[0].username == username:
            logger.warning(f"Attempt to change password for the sole active admin '{username}'. Proceeding.")

    user_in_db.hashed_password = pwd_context.hash(new_password)
    session.add(user_in_db)
    session.commit()
    logger.info(f"Password updated in DB for user '{username}'.")
    return True

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


async def get_current_user(
    token_data: TokenData = Depends(get_current_user_token_data),
    session: SQLModelSession = Depends(get_db_session) # Inject DB session
) -> User:
    user_in_db = get_user_from_db(session, token_data.username) # Pass session
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
async def get_optional_current_user(
    request: Request,
    session: SQLModelSession = Depends(get_db_session) # Inject DB session
) -> Optional[User]:
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
    
    user_in_db = get_user_from_db(session, token_data.username) # Pass session
    if not user_in_db or user_in_db.disabled: # Check if user is disabled
        return None
    
    user_data = user_in_db.model_dump(exclude={"hashed_password"})
    return User(**user_data)
