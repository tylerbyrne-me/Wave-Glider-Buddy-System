from typing import Annotated, List

from fastapi import APIRouter, Depends, HTTPException, Response, status, Request
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session as SQLModelSession

from .. import auth_utils  # Import auth_utils module
from ..auth_utils import get_current_admin_user, get_current_active_user, get_optional_current_user
from ..core import models
from ..core.security import create_access_token, verify_password
from ..db import get_db_session
from app.core.templates import templates

router = APIRouter(tags=["Authentication"])


# Authentication Endpoint
@router.post("/token")  # Removed response_model to allow setting cookies
async def login_for_access_token(
    response: Response,  # Inject the Response object
    session: Annotated[SQLModelSession, Depends(get_db_session)],
    form_data: OAuth2PasswordRequestForm = Depends(),
):
    """Authenticates user and returns a token in the body and sets a secure cookie."""
    user_in_db = auth_utils.get_user_from_db(session, form_data.username)
    if not user_in_db or not verify_password(
        form_data.password, user_in_db.hashed_password
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if user_in_db.disabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Inactive user"
        )

    auth_utils.logger.info(  # Use auth_utils.logger
        f"User '{user_in_db.username}' authenticated successfully. Issuing token."
    )
    access_token = create_access_token(
        data={"sub": user_in_db.username, "role": user_in_db.role.value}
    )

    # Set the access token in an HttpOnly cookie
    response.set_cookie(
        key="access_token_cookie",
        value=access_token,
        httponly=True,  # Prevents client-side JS from accessing the cookie
        samesite="lax",  # Recommended for security
        # secure=True, # In production with HTTPS, this should be True
        # max_age=... # Optionally set an expiry
    )

    # Also return the token in the response body for client-side JS that needs it
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/logout")
async def logout_user(response: Response):
    """Clears the authentication cookie."""
    response.delete_cookie(key="access_token_cookie")
    return {"message": "Logged out successfully"}


# Registration Endpoint
@router.post("/register", response_model=models.User)
async def register_new_user(
    user_in: models.UserCreate,
    current_admin: Annotated[models.User, Depends(get_current_admin_user)],
    session: Annotated[SQLModelSession, Depends(get_db_session)],
):
    auth_utils.logger.info(  # Use auth_utils.logger
        f"Attempting to register new user: {user_in.username}"
    )
    try:
        created_user_in_db = auth_utils.add_user_to_db(
            session, user_in
        )  # auth_utils module is already imported
        # Return User model, not UserInDB (which includes hashed_password)
        return models.User.model_validate(created_user_in_db.model_dump())
    except HTTPException as e:  # Catch username already exists error
        auth_utils.logger.warning(  # Use auth_utils.logger
            f"Registration failed for {user_in.username}: {e.detail}"
        )
        raise e  # Re-raise the HTTPException


# API Endpoint for Current User Details
@router.get("/api/users/me", response_model=models.User)
async def read_users_me(
    current_user: Annotated[models.User, Depends(get_current_active_user)]
):
    """Fetch details for the currently authenticated user."""
    return current_user


# Admin User Management API Endpoints
@router.get("/api/admin/users", response_model=List[models.User])
async def admin_list_users(
    current_admin: Annotated[models.User, Depends(get_current_admin_user)],
    session: Annotated[SQLModelSession, Depends(get_db_session)],
):
    """Lists all users. Admin only."""
    auth_utils.logger.info(  # Use auth_utils.logger
        f"Admin '{current_admin.username}' requesting list of all users."
    )
    return auth_utils.list_all_users_from_db(
        session
    )  # auth_utils module already imported


@router.put("/api/admin/users/{username}", response_model=models.User)
async def admin_update_user(
    username: str,
    user_update: models.UserUpdateForAdmin,
    current_admin: Annotated[models.User, Depends(get_current_admin_user)],
    session: Annotated[SQLModelSession, Depends(get_db_session)],
):
    """
    Updates a user's details (full name, email, role, disabled status).
    Admin only.
    """
    update_data_str = user_update.model_dump(exclude_unset=True)
    auth_utils.logger.info(  # Use auth_utils.logger
        f"Admin '{current_admin.username}' updating user '{username}' with: {update_data_str}"
    )

    # Basic safety: Prevent admin from disabling/demoting the last active admin (themselves)
    if username == current_admin.username:
        if user_update.disabled is True or (
            user_update.role and user_update.role != models.UserRoleEnum.admin
        ):
            # Query active admins from DB
            stmt = select(models.UserInDB).where(
                models.UserInDB.role == models.UserRoleEnum.admin,
                models.UserInDB.disabled == False,
            )
            active_admins = session.exec(stmt).all()
            if len(active_admins) == 1 and active_admins[0].username == username:
                auth_utils.logger.error(  # Use auth_utils.logger
                    f"Admin '{current_admin.username}' attempted to disable or "
                    f"demote themselves as the sole active admin."
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Cannot disable or demote the only active administrator.",
                )

    updated_user_in_db = auth_utils.update_user_details_in_db(
        session, username, user_update
    )  # auth_utils module already imported
    if not updated_user_in_db:
        auth_utils.logger.warning(  # Use auth_utils.logger
            f"Admin '{current_admin.username}' failed to update "
            f"non-existent user '{username}'."
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    # Convert UserInDB to User for the response
    return models.User.model_validate(updated_user_in_db.model_dump())


@router.put("/api/admin/users/{username}/password")
async def admin_change_user_password(
    username: str,
    password_update: models.PasswordUpdate,
    current_admin: Annotated[models.User, Depends(get_current_admin_user)],
    session: Annotated[SQLModelSession, Depends(get_db_session)],
):
    """Changes a user's password. Admin only."""
    auth_utils.logger.info(  # Use auth_utils.logger
        f"Admin '{current_admin.username}' attempting to change password for "
        f"user '{username}'."
    )
    success = auth_utils.update_user_password_in_db(
        session, username, password_update.new_password
    )  # auth_utils module already imported
    if not success:
        auth_utils.logger.warning(  # Use auth_utils.logger
            f"Admin '{current_admin.username}' failed to change password for "
            f"non-existent user '{username}'."
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    return {"message": "Password updated successfully"}


@router.get("/login.html", response_class=HTMLResponse)
async def login_page(request: Request, current_user: models.User = Depends(get_optional_current_user)):
    if current_user:
        return RedirectResponse(url="/home.html")
    return templates.TemplateResponse("login.html", {"request": request})

@router.get("/register.html", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})