# This __init__.py file makes the core submodules available when the
# 'app.core' package is imported.

"""
Core package for the Wave Glider Buddy System.

This package contains modules for data loading, processing, summarization,
forecasting, data models, security configurations, and utility functions.
"""

from . import \
    models  # Ensure models are importable if needed directly from core
from . import forecast
from . import loaders
from . import processors
from . import summaries
from . import utils
from . import security
from . import data_service  # Data service layer for loading mission data
from . import error_handlers  # Error handling utilities
from . import processor_framework  # Generic processor framework
from . import reporting  # Report generation
from . import auth  # Authentication and authorization
from . import db  # Database session management
# Note: dependencies is NOT imported here to avoid circular import issues
# Import it directly when needed: from app.core.dependencies import get_session

__all__ = [
    "models",
    "forecast",
    "loaders",
    "processors",
    "summaries",
    "utils",
    "security",
    "data_service",
    "error_handlers",
    "processor_framework",
    "reporting",
    "auth",
    "db",
]
