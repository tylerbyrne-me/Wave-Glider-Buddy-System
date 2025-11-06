"""
Error handling utilities for consistent error responses across routers.

This module provides standardized error handling functions and patterns
to ensure consistent error responses and logging across all endpoints.
"""

import logging
from typing import Optional
from fastapi import HTTPException, status

logger = logging.getLogger(__name__)


class ErrorContext:
    """Context information for error handling."""
    def __init__(self, operation: str, resource: Optional[str] = None, user_id: Optional[str] = None):
        self.operation = operation
        self.resource = resource
        self.user_id = user_id
    
    def __str__(self) -> str:
        parts = [self.operation]
        if self.resource:
            parts.append(f"resource={self.resource}")
        if self.user_id:
            parts.append(f"user_id={self.user_id}")
        return ", ".join(parts)


def handle_data_error(
    error: Exception,
    context: ErrorContext,
    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
    detail: Optional[str] = None,
    log_level: str = "error"
) -> HTTPException:
    """
    Handle data-related errors with consistent logging and response.
    
    Args:
        error: The exception that occurred
        context: Error context information
        status_code: HTTP status code (default: 500)
        detail: Custom error message (default: generic message based on context)
        log_level: Logging level ('error', 'warning', 'info')
        
    Returns:
        HTTPException with appropriate status code and detail
    """
    if detail is None:
        detail = f"Error {context.operation}"
        if context.resource:
            detail += f" for {context.resource}"
    
    # Log the error
    log_message = f"{context}: {str(error)}"
    if log_level == "error":
        logger.error(log_message, exc_info=True)
    elif log_level == "warning":
        logger.warning(log_message)
    else:
        logger.info(log_message)
    
    return HTTPException(status_code=status_code, detail=detail)


def handle_not_found(
    resource_type: str,
    resource_id: str,
    context: Optional[ErrorContext] = None
) -> HTTPException:
    """
    Handle 404 Not Found errors consistently.
    
    Args:
        resource_type: Type of resource (e.g., "mission", "station")
        resource_id: Identifier of the resource
        context: Optional error context
        
    Returns:
        HTTPException with 404 status
    """
    detail = f"{resource_type.capitalize()} '{resource_id}' not found"
    
    if context:
        logger.warning(f"{context}: {detail}")
    else:
        logger.warning(detail)
    
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def handle_validation_error(
    message: str,
    field: Optional[str] = None,
    context: Optional[ErrorContext] = None
) -> HTTPException:
    """
    Handle 400 Bad Request validation errors.
    
    Args:
        message: Validation error message
        field: Optional field name that failed validation
        context: Optional error context
        
    Returns:
        HTTPException with 400 status
    """
    detail = message
    if field:
        detail = f"Validation error for '{field}': {message}"
    
    if context:
        logger.warning(f"{context}: {detail}")
    else:
        logger.warning(f"Validation error: {detail}")
    
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def handle_authorization_error(
    message: str = "Not authorized to perform this action",
    context: Optional[ErrorContext] = None
) -> HTTPException:
    """
    Handle 403 Forbidden authorization errors.
    
    Args:
        message: Authorization error message
        context: Optional error context
        
    Returns:
        HTTPException with 403 status
    """
    if context:
        logger.warning(f"{context}: {message}")
    else:
        logger.warning(f"Authorization error: {message}")
    
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=message)


def handle_processing_error(
    operation: str,
    error: Exception,
    resource: Optional[str] = None,
    user_id: Optional[str] = None
) -> HTTPException:
    """
    Handle 500 Internal Server Error for processing failures.
    
    This is a convenience wrapper around handle_data_error for processing errors.
    
    Args:
        operation: Description of the operation that failed
        error: The exception that occurred
        resource: Optional resource identifier
        user_id: Optional user identifier
        
    Returns:
        HTTPException with 500 status
    """
    context = ErrorContext(operation=operation, resource=resource, user_id=user_id)
    return handle_data_error(
        error=error,
        context=context,
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"Error {operation}" + (f" for {resource}" if resource else "")
    )


def handle_data_not_found(
    data_type: str,
    mission_id: Optional[str] = None,
    context: Optional[ErrorContext] = None
) -> HTTPException:
    """
    Handle 404 errors for missing data.
    
    Args:
        data_type: Type of data (e.g., "telemetry", "power")
        mission_id: Optional mission identifier
        context: Optional error context
        
    Returns:
        HTTPException with 404 status
    """
    detail = f"No {data_type} data found"
    if mission_id:
        detail += f" for mission {mission_id}"
    
    if context:
        logger.warning(f"{context}: {detail}")
    else:
        logger.warning(detail)
    
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)

