import logging
from datetime import datetime, timezone
from typing import List, Optional

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from ..auth_utils import get_current_admin_user, get_optional_current_user
from ..core import models
from ..core.templates import templates

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin",
    tags=["Admin"],
    dependencies=[Depends(get_current_admin_user)],
)


def _format_trigger(trigger) -> models.JobTriggerInfo:
    """Helper to format APScheduler trigger into a Pydantic model."""
    if isinstance(trigger, CronTrigger):
        # Correctly extract fields from the CronTrigger object by name
        field_values = {field.name: str(field) for field in trigger.fields}
        day_of_week = field_values.get('day_of_week', '*')
        hour = field_values.get('hour', '*')
        minute = field_values.get('minute', '*')
        return models.JobTriggerInfo(
            type="cron",
            details=f"Day: {day_of_week}, Time: {hour}:{minute if not minute.isdigit() else f'{int(minute):02d}'} ({trigger.timezone})",
        )
    if isinstance(trigger, IntervalTrigger):
        return models.JobTriggerInfo(
            type="interval",
            details=f"Every {trigger.interval}",
        )
    return models.JobTriggerInfo(type=str(type(trigger).__name__), details=str(trigger))


@router.get("/scheduler/jobs", response_model=List[models.ScheduledJob], summary="Get Status of Scheduled Jobs")
async def get_scheduler_jobs():
    """Retrieves a list of all jobs currently scheduled in APScheduler."""
    from ..app import scheduler  # Import here to avoid circular dependency
    
    jobs_list = []
    now_utc = datetime.now(timezone.utc)

    for job in scheduler.get_jobs():
        status = models.JobStatusEnum.OK
        if job.next_run_time and job.next_run_time < now_utc:
            status = models.JobStatusEnum.OVERDUE

        job_info = models.ScheduledJob(
            id=job.id,
            name=job.name,
            func_ref=str(job.func_ref),
            trigger=_format_trigger(job.trigger),
            next_run_time=job.next_run_time,
            status=status,
        )
        jobs_list.append(job_info)
    return jobs_list


@router.get("/scheduler_status.html", response_class=HTMLResponse, include_in_schema=False, dependencies=[Depends(get_optional_current_user)])
async def get_scheduler_status_page(request: Request, current_user: models.User = Depends(get_optional_current_user)):
    """Serves the HTML page for viewing scheduler status."""
    return templates.TemplateResponse("admin/scheduler_status.html", {"request": request, "current_user": current_user})