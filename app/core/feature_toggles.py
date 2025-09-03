"""
Feature toggle utilities for enabling/disabling application features.
"""
from typing import Dict, Any, Set, List
from functools import lru_cache
from ..config import settings


# Cache the feature context to avoid repeated dictionary creation
@lru_cache(maxsize=1)
def _get_cached_feature_context() -> Dict[str, Any]:
    """
    Cached version of feature context to avoid repeated dictionary creation.
    Cache is invalidated when settings change (app restart).
    """
    features = settings.feature_toggles
    
    # Pre-compute all feature states for better performance
    context = {
        "features": features,
        # Individual feature flags for direct template access
        "is_schedule_enabled": features.get("schedule", False),
        "is_pic_management_enabled": features.get("pic_management", False),
        "is_payroll_enabled": features.get("payroll", False),
        "is_admin_management_enabled": features.get("admin_management", False),
        "is_station_offloads_enabled": features.get("station_offloads", False),
        "is_mission_dashboard_enabled": features.get("mission_dashboard", True),
        "is_forms_enabled": features.get("forms", True),
        "is_reporting_enabled": features.get("reporting", True),
        "is_authentication_enabled": features.get("authentication", True),
    }
    
    # Add computed properties for template convenience
    context.update({
        "enabled_features": [name for name, enabled in features.items() if enabled],
        "disabled_features": [name for name, enabled in features.items() if not enabled],
        "has_admin_features": any([
            features.get("admin_management", False),
            features.get("payroll", False),  # Admin can manage pay periods
        ]),
        "has_user_features": any([
            features.get("schedule", False),
            features.get("pic_management", False),
            features.get("payroll", False),
            features.get("forms", False),
        ]),
        "feature_count": len([enabled for enabled in features.values() if enabled]),
        "total_features": len(features),
    })
    
    return context


def is_feature_enabled(feature_name: str) -> bool:
    """
    Check if a feature is enabled.
    
    Args:
        feature_name: The name of the feature to check
        
    Returns:
        bool: True if feature is enabled, False otherwise
    """
    return settings.feature_toggles.get(feature_name, False)


def get_enabled_features() -> Dict[str, bool]:
    """
    Get all feature toggle states.
    
    Returns:
        Dict[str, bool]: Dictionary of feature names to their enabled states
    """
    return settings.feature_toggles.copy()


def get_enabled_feature_names() -> Set[str]:
    """
    Get a set of enabled feature names for quick lookup.
    
    Returns:
        Set[str]: Set of enabled feature names
    """
    return {name for name, enabled in settings.feature_toggles.items() if enabled}


def get_disabled_feature_names() -> Set[str]:
    """
    Get a set of disabled feature names for quick lookup.
    
    Returns:
        Set[str]: Set of disabled feature names
    """
    return {name for name, enabled in settings.feature_toggles.items() if not enabled}


def get_feature_context() -> Dict[str, Any]:
    """
    Get feature toggle context for templates with caching for performance.
    
    Returns:
        Dict[str, Any]: Dictionary with feature states for template rendering
    """
    return _get_cached_feature_context()


def clear_feature_cache():
    """
    Clear the feature context cache. Useful for testing or when settings change.
    """
    _get_cached_feature_context.cache_clear()


def get_feature_summary() -> Dict[str, Any]:
    """
    Get a summary of feature toggle states for debugging/admin purposes.
    
    Returns:
        Dict[str, Any]: Summary information about feature toggles
    """
    features = settings.feature_toggles
    enabled_count = sum(1 for enabled in features.values() if enabled)
    
    return {
        "total_features": len(features),
        "enabled_count": enabled_count,
        "disabled_count": len(features) - enabled_count,
        "enabled_features": get_enabled_feature_names(),
        "disabled_features": get_disabled_feature_names(),
        "feature_states": features,
    }
