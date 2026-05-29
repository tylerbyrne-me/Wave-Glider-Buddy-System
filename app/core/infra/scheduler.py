"""
Scheduler Management Module

Provides access to the APScheduler instance without circular dependencies.
The scheduler is initialized in app.py and registered here for access.
"""

from typing import Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Global scheduler instance - will be set by app.py during startup
_scheduler: Optional[AsyncIOScheduler] = None


def set_scheduler(scheduler: AsyncIOScheduler) -> None:
    """
    Register the scheduler instance.
    Called by app.py during startup.
    
    Args:
        scheduler: The AsyncIOScheduler instance
    """
    global _scheduler
    _scheduler = scheduler


def get_scheduler() -> AsyncIOScheduler:
    """
    Get the scheduler instance.
    
    Returns:
        The AsyncIOScheduler instance
        
    Raises:
        RuntimeError: If scheduler has not been initialized
    """
    if _scheduler is None:
        raise RuntimeError("Scheduler has not been initialized. This should be set during app startup.")
    return _scheduler

