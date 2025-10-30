"""
Feature guard utilities for protecting endpoints based on feature toggles.
"""
from fastapi import HTTPException, status
from .feature_toggles import is_feature_enabled


def require_feature(feature_name: str):
    """
    Decorator to require a feature to be enabled for an endpoint.
    
    Args:
        feature_name: The name of the feature that must be enabled
        
    Raises:
        HTTPException: 404 if feature is disabled
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            if not is_feature_enabled(feature_name):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Feature '{feature_name}' is currently disabled"
                )
            return func(*args, **kwargs)
        return wrapper
    return decorator


def check_feature_or_404(feature_name: str):
    """
    Check if a feature is enabled, raise 404 if not.
    
    Args:
        feature_name: The name of the feature to check
        
    Raises:
        HTTPException: 404 if feature is disabled
    """
    if not is_feature_enabled(feature_name):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Feature '{feature_name}' is currently disabled"
        )


def require_feature_dep(feature_name: str):
    """
    FastAPI dependency-style guard to require a feature for routes/handlers.

    Usage:
        @router.get("/payroll", dependencies=[Depends(require_feature_dep("payroll"))])
    """
    def _dependency():
        if not is_feature_enabled(feature_name):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Feature '{feature_name}' is currently disabled"
            )
    return _dependency


def return_if_feature_enabled(feature_name: str, value):
    """
    Convenience helper for handlers/services to short-circuit responses
    when a feature is disabled. Returns None if disabled, else returns value.
    """
    if not is_feature_enabled(feature_name):
        return None
    return value