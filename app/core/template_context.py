"""
Template context processor for adding global context variables to all templates.
"""
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from .feature_toggles import get_feature_context
from ..config import settings


def get_global_template_context() -> Dict[str, Any]:
    """
    Get global context variables that should be available in all templates.
    
    Returns:
        dict: Global template context variables
    """
    # Get feature context (cached for performance)
    context = get_feature_context()
    
    # Add application-wide context
    context.update({
        # Application metadata
        "app_name": "Wave Glider Buddy System",
        "app_version": "1.0.0",  # You can make this dynamic if needed
        "current_year": datetime.now().year,
        "current_utc": datetime.now(timezone.utc),
        
        # Configuration context
        "active_missions": settings.active_realtime_missions,
        "mission_count": len(settings.active_realtime_missions),
        "forms_storage_mode": settings.forms_storage_mode,
        
        # Environment context
        "is_production": not settings.jwt_secret_key.startswith("CHANGE_THIS"),
        "is_development": settings.jwt_secret_key.startswith("CHANGE_THIS"),
        
        # Feature summary for templates
        "feature_summary": {
            "enabled_count": context.get("feature_count", 0),
            "total_count": context.get("total_features", 0),
            "has_admin_features": context.get("has_admin_features", False),
            "has_user_features": context.get("has_user_features", False),
        }
    })
    
    return context


def get_template_context(**kwargs) -> Dict[str, Any]:
    """
    Helper function to create template context with feature toggles and global context.
    
    Args:
        **kwargs: Additional context variables
        
    Returns:
        dict: Template context with feature toggles and global context
    """
    context = get_global_template_context()
    context.update(kwargs)
    return context


def get_minimal_template_context(**kwargs) -> Dict[str, Any]:
    """
    Get minimal template context without feature toggles (for performance-critical templates).
    
    Args:
        **kwargs: Additional context variables
        
    Returns:
        dict: Minimal template context
    """
    return {
        "app_name": "Wave Glider Buddy System",
        "current_year": datetime.now().year,
        **kwargs
    }


def get_admin_template_context(**kwargs) -> Dict[str, Any]:
    """
    Get template context specifically for admin pages with additional admin context.
    
    Args:
        **kwargs: Additional context variables
        
    Returns:
        dict: Admin template context
    """
    context = get_global_template_context()
    
    # Add admin-specific context
    context.update({
        "is_admin_page": True,
        "admin_features": {
            "user_management": context.get("is_admin_management_enabled", False),
            "payroll_management": context.get("is_payroll_enabled", False),
            "announcements": context.get("is_admin_management_enabled", False),
            "mission_overviews": context.get("is_admin_management_enabled", False),
            "scheduler_status": context.get("is_admin_management_enabled", False),
        }
    })
    
    context.update(kwargs)
    return context


def get_user_template_context(**kwargs) -> Dict[str, Any]:
    """
    Get template context specifically for user pages with user-relevant features.
    
    Args:
        **kwargs: Additional context variables
        
    Returns:
        dict: User template context
    """
    context = get_global_template_context()
    
    # Add user-specific context
    context.update({
        "is_user_page": True,
        "user_features": {
            "schedule": context.get("is_schedule_enabled", False),
            "pic_management": context.get("is_pic_management_enabled", False),
            "payroll": context.get("is_payroll_enabled", False),
            "forms": context.get("is_forms_enabled", False),
            "station_offloads": context.get("is_station_offloads_enabled", False),
        }
    })
    
    context.update(kwargs)
    return context
