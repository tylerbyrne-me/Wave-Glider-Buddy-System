# Template System Optimization

This document outlines the optimizations and enhancements made to the Wave Glider Buddy System's template system.

## Overview

The template system has been optimized for:
- **Performance**: Caching and efficient context generation
- **Maintainability**: Clear separation of concerns and helper functions
- **Flexibility**: Multiple context types for different use cases
- **Developer Experience**: Better debugging and validation tools

## Key Optimizations

### 1. Feature Toggles (`app/core/feature_toggles.py`)

#### Performance Improvements:
- **LRU Cache**: Feature context is cached using `@lru_cache(maxsize=1)` to avoid repeated dictionary creation
- **Pre-computed Values**: All feature states are computed once and reused
- **Efficient Lookups**: Added `get_enabled_feature_names()` and `get_disabled_feature_names()` for set-based operations

#### New Features:
- **Extended Feature Support**: Added support for all 9 features (mission_dashboard, forms, reporting, authentication)
- **Computed Properties**: Added `has_admin_features`, `has_user_features`, `feature_count`, etc.
- **Debugging Tools**: Added `get_feature_summary()` for admin/debugging purposes
- **Cache Management**: Added `clear_feature_cache()` for testing

#### Template Context Variables:
```python
{
    "features": {...},  # All feature states
    "is_schedule_enabled": bool,
    "is_pic_management_enabled": bool,
    "is_payroll_enabled": bool,
    "is_admin_management_enabled": bool,
    "is_station_offloads_enabled": bool,
    "is_mission_dashboard_enabled": bool,
    "is_forms_enabled": bool,
    "is_reporting_enabled": bool,
    "is_authentication_enabled": bool,
    "enabled_features": [...],  # List of enabled feature names
    "disabled_features": [...],  # List of disabled feature names
    "has_admin_features": bool,
    "has_user_features": bool,
    "feature_count": int,
    "total_features": int,
}
```

### 2. Template Context (`app/core/template_context.py`)

#### New Context Functions:
- **`get_global_template_context()`**: Full context with app metadata, configuration, and features
- **`get_minimal_template_context()`**: Lightweight context for performance-critical templates
- **`get_admin_template_context()`**: Admin-specific context with admin feature flags
- **`get_user_template_context()`**: User-specific context with user feature flags

#### Global Context Variables:
```python
{
    # Application metadata
    "app_name": "Wave Glider Buddy System",
    "app_version": "1.0.0",
    "current_year": int,
    "current_utc": datetime,
    
    # Configuration
    "active_missions": [...],
    "mission_count": int,
    "forms_storage_mode": str,
    
    # Environment
    "is_production": bool,
    "is_development": bool,
    
    # Feature summary
    "feature_summary": {
        "enabled_count": int,
        "total_count": int,
        "has_admin_features": bool,
        "has_user_features": bool,
    }
}
```

### 3. Templates Configuration (`app/core/templates.py`)

#### Enhanced Jinja2 Configuration:
- **Auto-escape**: Enabled for security
- **Custom Filters**: Added `datetime_format`, `truncate`, `feature_enabled`
- **Custom Globals**: Added app metadata and paths
- **Error Handling**: Better error handling and logging

#### New Utility Functions:
- **`get_template_path()`**: Get full path to template file with validation
- **`list_available_templates()`**: List all available template files
- **`validate_template_context()`**: Clean and validate template context

#### Custom Template Filters:
```jinja2
<!-- Format datetime -->
{{ some_datetime | datetime_format("%Y-%m-%d") }}

<!-- Truncate text -->
{{ long_text | truncate(50) }}

<!-- Check feature in template -->
{% if "schedule" | feature_enabled %}
    <!-- Schedule content -->
{% endif %}
```

## Usage Examples

### Basic Template Context:
```python
from app.core.template_context import get_template_context

# In your router
return templates.TemplateResponse(
    "template.html",
    get_template_context(request=request, current_user=current_user)
)
```

### Admin-Specific Context:
```python
from app.core.template_context import get_admin_template_context

# For admin pages
return templates.TemplateResponse(
    "admin_template.html",
    get_admin_template_context(request=request, current_user=current_user)
)
```

### Minimal Context (Performance):
```python
from app.core.template_context import get_minimal_template_context

# For high-traffic pages
return templates.TemplateResponse(
    "simple_template.html",
    get_minimal_template_context(request=request)
)
```

### Template Usage:
```jinja2
<!-- Check individual features -->
{% if features.schedule %}
    <a href="/schedule.html">Schedule</a>
{% endif %}

<!-- Use computed properties -->
{% if has_admin_features %}
    <div class="admin-panel">Admin features available</div>
{% endif %}

<!-- Use feature summary -->
<div class="feature-status">
    {{ feature_summary.enabled_count }}/{{ feature_summary.total_count }} features enabled
</div>

<!-- Use custom filters -->
<p>{{ some_datetime | datetime_format("%B %d, %Y") }}</p>
<p>{{ long_description | truncate(100) }}</p>
```

## Performance Benefits

1. **Caching**: Feature context is cached, reducing repeated computation
2. **Pre-computation**: All feature states computed once per app lifecycle
3. **Efficient Lookups**: Set-based operations for feature checks
4. **Minimal Context**: Option for lightweight context when full features aren't needed
5. **Template Optimization**: Custom filters reduce template complexity

## Migration Guide

### For Existing Templates:
No changes required - all existing template code continues to work.

### For New Templates:
- Use `get_template_context()` for standard pages
- Use `get_admin_template_context()` for admin pages
- Use `get_minimal_template_context()` for performance-critical pages
- Leverage new computed properties like `has_admin_features`

### For Router Updates:
Replace manual context creation:
```python
# Old way
context = {"request": request, "current_user": current_user}

# New way
context = get_template_context(request=request, current_user=current_user)
```

## Configuration

### Feature Toggles:
```bash
# In .env file (single line)
FEATURE_TOGGLES_JSON={"schedule": false, "pic_management": false, "payroll": true, "admin_management": true, "station_offloads": true, "mission_dashboard": true, "forms": false, "reporting": false, "authentication": true}
```

### Template Development:
```python
# In app/core/templates.py
templates = Jinja2Templates(
    directory=str(TEMPLATES_DIR),
    auto_reload=True,  # Enable for development
    autoescape=True,   # Security
)
```

## Debugging Tools

### Feature Summary:
```python
from app.core.feature_toggles import get_feature_summary

summary = get_feature_summary()
print(f"Enabled: {summary['enabled_count']}/{summary['total_count']}")
print(f"Disabled: {summary['disabled_features']}")
```

### Template Validation:
```python
from app.core.templates import validate_template_context

clean_context = validate_template_context("template.html", context)
```

### Available Templates:
```python
from app.core.templates import list_available_templates

templates = list_available_templates()
print(f"Available templates: {templates}")
```

This optimization provides a robust, performant, and maintainable template system that scales with your application needs.
