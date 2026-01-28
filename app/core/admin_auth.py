"""
Shared authentication backend for admin interfaces.

This module provides authentication backends for both SQLAdmin and FastAPI-Admin
that integrate with the existing application authentication system.
"""

import logging
from typing import Optional

from fastapi import Request, HTTPException, status
from fastapi.responses import RedirectResponse
from sqladmin.authentication import AuthenticationBackend
from sqlmodel import Session as SQLModelSession, select

from app.core.auth import get_user_from_db
from app.core.db import get_db_session
from app.core.models.database import UserInDB
from app.core.models.enums import UserRoleEnum
from app.core.security import verify_password, decode_access_token

logger = logging.getLogger(__name__)


class SQLAdminAuthBackend(AuthenticationBackend):
    """
    Authentication backend for SQLAdmin that uses the existing app authentication.
    
    Supports both cookie-based and token-based authentication.
    """
    
    async def login(self, request: Request) -> bool:
        """
        Handle login form submission.
        Validates credentials and sets session.
        """
        form = await request.form()
        username = form.get("username")
        password = form.get("password")
        
        if not username or not password:
            return False
        
        # Get database session (get_db_session is a generator)
        session_gen = get_db_session()
        try:
            session: SQLModelSession = next(session_gen)
            
            # Get user from database
            user = get_user_from_db(session, username)
            
            if not user:
                logger.warning(f"SQLAdmin login attempt with invalid username: {username}")
                return False
            
            # Verify password
            if not verify_password(password, user.hashed_password):
                logger.warning(f"SQLAdmin login attempt with invalid password for user: {username}")
                return False
            
            # Check if user is disabled
            if user.disabled:
                logger.warning(f"SQLAdmin login attempt with disabled user: {username}")
                return False
            
            # Check if user is admin
            if user.role != UserRoleEnum.admin:
                logger.warning(f"SQLAdmin login attempt by non-admin user: {username} (role: {user.role})")
                return False
            
            # Store user info in session
            request.session.update({
                "admin_user_id": user.id,
                "admin_username": user.username,
                "admin_role": user.role.value,
            })
            
            logger.info(f"SQLAdmin: User '{username}' logged in successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error during SQLAdmin login: {e}", exc_info=True)
            return False
        finally:
            # Close the generator properly
            try:
                next(session_gen, None)
            except StopIteration:
                pass
    
    async def logout(self, request: Request) -> bool:
        """Handle logout and clear session."""
        username = request.session.get("admin_username", "unknown")
        request.session.clear()
        logger.info(f"SQLAdmin: User '{username}' logged out")
        return True
    
    async def authenticate(self, request: Request) -> bool:
        """
        Authenticate incoming requests.
        Checks both session and cookie-based tokens.
        """
        # First, check session (for form-based login)
        if request.session.get("admin_user_id"):
            username = request.session.get("admin_username")
            role = request.session.get("admin_role")
            
            # Verify user still exists and is admin
            if username and role == UserRoleEnum.admin.value:
                session_gen = get_db_session()
                try:
                    session: SQLModelSession = next(session_gen)
                    user = get_user_from_db(session, username)
                    if user and not user.disabled and user.role == UserRoleEnum.admin:
                        return True
                finally:
                    # Close the generator properly
                    try:
                        next(session_gen, None)
                    except StopIteration:
                        pass
        
        # Fallback: Check cookie-based token (for API-style access)
        token = request.cookies.get("access_token_cookie")
        if token:
            token_data = decode_access_token(token)
            if token_data and token_data.username:
                # Verify user is admin
                session_gen = get_db_session()
                try:
                    session: SQLModelSession = next(session_gen)
                    user = get_user_from_db(session, token_data.username)
                    if user and not user.disabled and user.role == UserRoleEnum.admin:
                        # Update session for consistency
                        request.session.update({
                            "admin_user_id": user.id,
                            "admin_username": user.username,
                            "admin_role": user.role.value,
                        })
                        return True
                finally:
                    # Close the generator properly
                    try:
                        next(session_gen, None)
                    except StopIteration:
                        pass
        
        return False


def create_sqladmin_auth_backend(secret_key: str) -> SQLAdminAuthBackend:
    """
    Create and return an SQLAdmin authentication backend.
    
    Args:
        secret_key: Secret key for session encryption (use JWT secret from settings)
    
    Returns:
        Configured SQLAdminAuthBackend instance
    """
    return SQLAdminAuthBackend(secret_key=secret_key)
