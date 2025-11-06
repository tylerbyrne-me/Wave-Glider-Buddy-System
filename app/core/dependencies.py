"""
Standardized dependency injection patterns for routers.

This module provides common dependency functions and patterns to ensure
consistency across all routers and endpoints.

Usage:
    from app.core.dependencies import get_session, get_active_user
    
    @router.get("/endpoint")
    async def my_endpoint(
        session: SQLModelSession = get_session(),
        current_user: User = get_active_user(),
    ):
        ...
"""

from typing import Optional, TYPE_CHECKING
from fastapi import Depends

from sqlmodel import Session as SQLModelSession

# Lazy imports to avoid circular dependencies
# auth imports from core.models, and core.__init__ imports dependencies
# So we import auth functions inside the dependency functions instead

if TYPE_CHECKING:
    from .models import User


# ============================================================================
# Standard Dependency Functions
# ============================================================================

def get_session() -> SQLModelSession:
    """
    Dependency for database session.
    
    Use this when you need database access.
    
    Example:
        session: SQLModelSession = get_session()
    """
    from .db import get_db_session
    return Depends(get_db_session)


def get_user():
    """
    Dependency for authenticated user (any user, active or disabled).
    
    Use this when you need user info but don't care about disabled status.
    Generally prefer get_active_user() for most endpoints.
    
    Example:
        current_user: User = get_user()
    """
    from .auth import get_current_user
    return Depends(get_current_user)


def get_active_user():
    """
    Dependency for authenticated active user.
    
    Use this for most endpoints that require authentication.
    Automatically rejects disabled users.
    
    Example:
        current_user: User = get_active_user()
    """
    from .auth import get_current_active_user
    return Depends(get_current_active_user)


def get_admin_user():
    """
    Dependency for authenticated admin user.
    
    Use this for admin-only endpoints.
    Automatically rejects non-admin and disabled users.
    
    Example:
        current_user: User = get_admin_user()
    """
    from .auth import get_current_admin_user
    return Depends(get_current_admin_user)


def get_optional_user():
    """
    Dependency for optional user (may be None if not authenticated).
    
    Use this for endpoints that work for both authenticated and anonymous users.
    
    Example:
        current_user: Optional[User] = get_optional_user()
    """
    from .auth import get_optional_current_user
    return Depends(get_optional_current_user)


# ============================================================================
# Common Dependency Combinations (Helper Functions)
# ============================================================================

def get_session_and_active_user():
    """
    Helper function that returns both session and active user dependencies.
    
    Note: FastAPI doesn't support tuple dependencies directly.
    Instead, use separate dependencies in your endpoint signature.
    
    Example:
        session: SQLModelSession = get_session()
        current_user: User = get_active_user()
    """
    return (get_session(), get_active_user())


def get_session_and_admin_user():
    """
    Helper function that returns both session and admin user dependencies.
    
    Note: FastAPI doesn't support tuple dependencies directly.
    Instead, use separate dependencies in your endpoint signature.
    
    Example:
        session: SQLModelSession = get_session()
        current_user: User = get_admin_user()
    """
    return (get_session(), get_admin_user())


# ============================================================================
# Type Aliases for Documentation
# ============================================================================

# These are type hints for documentation purposes
# They help IDEs and type checkers understand what dependencies provide

if TYPE_CHECKING:
    SessionDep = SQLModelSession
    ActiveUserDep = "User"
    AdminUserDep = "User"
    OptionalUserDep = "Optional[User]"
else:
    SessionDep = SQLModelSession
    ActiveUserDep = None
    AdminUserDep = None
    OptionalUserDep = None

