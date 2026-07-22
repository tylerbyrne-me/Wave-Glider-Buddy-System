"""
Scheduler Management Module

Provides access to the APScheduler instance without circular dependencies.
The scheduler is initialized in app.py and registered here for access.
"""

from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.models.enums import JobPlatformEnum

# Global scheduler instance - will be set by app.py during startup
_scheduler: Optional[AsyncIOScheduler] = None

# Explicit platform catalog for admin scheduler UI (source of truth for known jobs).
JOB_PLATFORM_BY_ID: dict[str, JobPlatformEnum] = {
    "wave_glider_active_mission_refresh_job": JobPlatformEnum.WAVE_GLIDER,
    "wave_glider_weekly_report_job": JobPlatformEnum.WAVE_GLIDER,
    "slocum_warm_cache_job": JobPlatformEnum.SLOCUM,
    "slocum_weekly_report_job": JobPlatformEnum.SLOCUM,
    "slocum_overage_cleanup_job": JobPlatformEnum.SLOCUM,
    "slocum_sfmc_cache_refresh_job": JobPlatformEnum.SLOCUM,
    "system_weather_map_prefetch_job": JobPlatformEnum.SYSTEM,
    "system_weather_map_cleanup_job": JobPlatformEnum.SYSTEM,
    "system_bathy_cache_cleanup_job": JobPlatformEnum.SYSTEM,
}


def resolve_job_platform(job_id: str) -> JobPlatformEnum:
    """Resolve a job's platform from the catalog, then ID prefix fallback."""
    known = JOB_PLATFORM_BY_ID.get(job_id)
    if known is not None:
        return known

    job_id_str = str(job_id or "")
    if job_id_str.startswith("system_"):
        return JobPlatformEnum.SYSTEM
    if job_id_str.startswith("slocum_"):
        return JobPlatformEnum.SLOCUM
    if job_id_str.startswith("wave_glider_"):
        return JobPlatformEnum.WAVE_GLIDER
    return JobPlatformEnum.SYSTEM


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
