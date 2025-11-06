from fastapi import APIRouter, Depends, HTTPException, status, Request, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from typing import List, Optional
from datetime import date, datetime, timedelta, timezone
from sqlmodel import select, delete
from ..core import models
from ..core.db import get_db_session, SQLModelSession
from ..core.auth import (
    get_current_active_user, get_current_admin_user, get_optional_current_user, get_user_from_db
)
from ..core import auth
import io
import ics
import csv
import logging
from app.core.templates import templates
from ..core.template_context import get_template_context

router = APIRouter(tags=["Schedule"])
logger = logging.getLogger(__name__)

# --- Helper: Canadian Holidays ---
def _get_canadian_holidays(start_date: date, end_date: date) -> List[tuple]:
    holidays = []
    if start_date.year <= 2025 <= end_date.year:
        holidays.extend([
            (date(2025, 1, 1), "New Year's Day"),
            (date(2025, 4, 18), "Good Friday"),
            (date(2025, 5, 19), "Victoria Day"),
            (date(2025, 7, 1), "Canada Day"),
            (date(2025, 9, 1), "Labour Day"),
            (date(2025, 10, 13), "Thanksgiving Day"),
            (date(2025, 11, 11), "Remembrance Day"),
            (date(2025, 12, 25), "Christmas Day"),
            (date(2025, 12, 26), "Boxing Day"),
        ])
    if start_date.year <= 2026 <= end_date.year:
        holidays.extend([
            (date(2026, 1, 1), "New Year's Day"),
            (date(2026, 4, 3), "Good Friday"),
            (date(2026, 5, 18), "Victoria Day"),
            (date(2026, 7, 1), "Canada Day"),
            (date(2026, 9, 7), "Labour Day"),
            (date(2026, 10, 12), "Thanksgiving Day"),
            (date(2026, 11, 11), "Remembrance Day"),
            (date(2026, 12, 25), "Christmas Day"),
            (date(2026, 12, 26), "Boxing Day"),
        ])
    return [ (h_date, h_name) for h_date, h_name in holidays if start_date <= h_date <= end_date ]

# --- Helper: Detect Consecutive Shifts ---
def _detect_consecutive_shifts(assignments: List[models.ShiftAssignment]) -> dict:
    """
    Detect consecutive shifts for the same user and create enhanced grouping information.
    Returns a dict mapping assignment_id to consecutive shift metadata.
    """
    consecutive_info = {}
    
    # Group assignments by user
    user_assignments = {}
    for assignment in assignments:
        if assignment.user_id not in user_assignments:
            user_assignments[assignment.user_id] = []
        user_assignments[assignment.user_id].append(assignment)
    
    # For each user, check for consecutive shifts
    for user_id, user_shifts in user_assignments.items():
        # Sort by start time
        user_shifts.sort(key=lambda x: x.start_time_utc)
        
        for i, shift in enumerate(user_shifts):
            consecutive_count = 0
            is_first_in_sequence = True
            is_last_in_sequence = True
            
            # Check if this shift is consecutive with the previous one
            if i > 0:
                prev_shift = user_shifts[i-1]
                if prev_shift.end_time_utc == shift.start_time_utc:
                    consecutive_count += 1
                    is_first_in_sequence = False
            
            # Check if this shift is consecutive with the next one
            if i < len(user_shifts) - 1:
                next_shift = user_shifts[i+1]
                if shift.end_time_utc == next_shift.start_time_utc:
                    consecutive_count += 1
                    is_last_in_sequence = False
            
            consecutive_info[shift.id] = {
                'consecutive_count': consecutive_count,
                'is_first_in_sequence': is_first_in_sequence,
                'is_last_in_sequence': is_last_in_sequence,
                'total_sequence_length': consecutive_count + 1
            }
    
    return consecutive_info

# --- Schedule Endpoints ---

@router.get("/schedule.html", response_class=HTMLResponse)
async def read_schedule_page(
    request: Request,
    current_user: Optional[models.User] = Depends(get_optional_current_user)
):
    """
    Serves the daily shift schedule page.
    """
    if current_user:
        logger.info(f"User '{current_user.username}' accessing schedule page.")
    else:
        logger.info("Anonymous user accessing schedule page (relying on client-side auth check).")
    # Use request.app.state.templates to access Jinja2Templates instance
    return templates.TemplateResponse(
        "schedule.html",
        get_template_context(request=request, current_user=current_user),
    )

@router.get("/api/schedule/events", response_model=List[models.ScheduleEvent])
async def get_schedule_events_api(
    start_date: Optional[datetime] = Query(None, alias="start"),
    end_date: Optional[datetime] = Query(None, alias="end"),
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session)
):
    logger.info(f"User '{current_user.username}' requesting schedule events.")
    if start_date and end_date:
        if start_date.tzinfo is None:
            start_date = start_date.replace(tzinfo=timezone.utc)
        if end_date.tzinfo is None:
            end_date = end_date.replace(tzinfo=timezone.utc)
        logger.info(f"Fetching events for range: {start_date.isoformat()} to {end_date.isoformat()}")
        statement = select(models.ShiftAssignment).where(
            models.ShiftAssignment.start_time_utc < end_date,
            models.ShiftAssignment.end_time_utc > start_date
        )
    else:
        now = datetime.now(timezone.utc)
        logger.info(f"No date range provided, fetching all events (or implement a default server-side range).")
        statement = select(models.ShiftAssignment)

    db_assignments = session.exec(statement).all()
    unavailability_statement = select(models.UserUnavailability)
    if start_date and end_date:
        unavailability_statement = unavailability_statement.where(
            models.UserUnavailability.start_time_utc < end_date,
            models.UserUnavailability.end_time_utc > start_date
        )
    db_unavailabilities = session.exec(unavailability_statement).all()
    
    # Detect consecutive shifts for enhanced grouping
    consecutive_shift_info = _detect_consecutive_shifts(db_assignments)
    
    response_events = []
    lri_pilot_user = auth.get_user_from_db(session, "LRI_PILOT")
    
    # Group assignments by user and create merged events
    user_assignments = {}
    for assignment in db_assignments:
        if assignment.user_id not in user_assignments:
            user_assignments[assignment.user_id] = []
        user_assignments[assignment.user_id].append(assignment)
    
    # Process each user's assignments to create merged events
    for user_id, user_shifts in user_assignments.items():
        # Sort by start time
        user_shifts.sort(key=lambda x: x.start_time_utc)
        
        # Group consecutive shifts by day (daily cutoff for collation)
        daily_merged_events = {}
        
        for shift in user_shifts:
            # Get the day this shift starts (for daily grouping)
            shift_start_day = shift.start_time_utc.date()
            
            if shift_start_day not in daily_merged_events:
                daily_merged_events[shift_start_day] = []
            daily_merged_events[shift_start_day].append(shift)
        
        # Process each day's shifts separately
        for day_date, day_shifts in daily_merged_events.items():
            # Sort day shifts by start time
            day_shifts.sort(key=lambda x: x.start_time_utc)
            
            # Group consecutive shifts within the day
            merged_events = []
            current_sequence = []
            
            for shift in day_shifts:
                if not current_sequence:
                    current_sequence = [shift]
                elif shift.start_time_utc == current_sequence[-1].end_time_utc:
                    # Consecutive shift - add to current sequence
                    current_sequence.append(shift)
                else:
                    # Non-consecutive - process current sequence and start new one
                    if current_sequence:
                        merged_events.append(current_sequence)
                    current_sequence = [shift]
            
            # Don't forget the last sequence
            if current_sequence:
                merged_events.append(current_sequence)
            
            # Create events for each merged sequence within the day
            for sequence in merged_events:
                if len(sequence) == 1:
                    # Single shift - create normal event
                    assignment = sequence[0]
                    user = session.get(models.UserInDB, assignment.user_id)
                    username_display = user.username if user else "Unknown User"
                    user_color = user.color if user and user.color else "#DDDDDD"
                    is_editable = (current_user.id == user.id) if user else False
                    event_type = "shift"
                    display_type = "auto"
                    all_day = False
                    event_text = username_display
                    event_back_color = user_color
                    event_group_id = str(user.id) if user else None
                    
                    if lri_pilot_user and assignment.user_id == lri_pilot_user.id:
                        event_type = "lri_block"
                        event_text = "LRI Block"
                        event_back_color = lri_pilot_user.color
                        display_type = "block"
                        event_group_id = str(lri_pilot_user.id)
                        is_editable = current_user.role == models.UserRoleEnum.admin
                    
                    response_events.append(
                        models.ScheduleEvent(
                            id=f"shift-{assignment.id}",
                            text=event_text,
                            start=assignment.start_time_utc,
                            end=assignment.end_time_utc,
                            resource=assignment.resource_id,
                            backColor=event_back_color,
                            type=event_type,
                            editable=is_editable,
                            startEditable=False,
                            durationEditable=False,
                            resourceEditable=False,
                            overlap=True,
                            groupId=event_group_id,
                            display=display_type,
                            allDay=all_day,
                            user_role=user.role if user else None,
                            user_color=user_color,
                            consecutive_shifts=0,
                            is_first_in_sequence=True,
                            is_last_in_sequence=True,
                            total_sequence_length=1
                        )
                    )
                else:
                    # Multiple consecutive shifts within the day - create merged event
                    first_shift = sequence[0]
                    last_shift = sequence[-1]
                    user = session.get(models.UserInDB, first_shift.user_id)
                    username_display = user.username if user else "Unknown User"
                    user_color = user.color if user and user.color else "#DDDDDD"
                    is_editable = (current_user.id == user.id) if user else False
                    display_type = "block"  # Use block display for merged events
                    all_day = False
                    
                    # Create descriptive text with start/end times (not total hours)
                    start_time_str = first_shift.start_time_utc.strftime("%H:%M")
                    end_time_str = last_shift.end_time_utc.strftime("%H:%M")
                    
                    if lri_pilot_user and first_shift.user_id == lri_pilot_user.id:
                        event_type = "lri_block"
                        event_text = f"LRI Block: {start_time_str} - {end_time_str}"
                        event_back_color = lri_pilot_user.color
                        event_group_id = str(lri_pilot_user.id)
                        is_editable = current_user.role == models.UserRoleEnum.admin
                    else:
                        # For regular pilots and admins, preserve their event type and color
                        event_type = "shift"  # Keep as shift type for proper styling
                        event_text = f"{username_display}: {start_time_str} - {end_time_str}"
                        event_back_color = user_color  # Use the user's assigned color
                        event_group_id = str(user.id) if user else None
                        
                        # Debug logging for color assignment
                        logger.info(f"Creating merged event for user {username_display}: type={event_type}, color={event_back_color}, user_color={user_color}")
                    
                    response_events.append(
                        models.ScheduleEvent(
                            id=f"merged-{day_date.strftime('%Y%m%d')}-{first_shift.id}-{last_shift.id}",
                            text=event_text,
                            start=first_shift.start_time_utc,
                            end=last_shift.end_time_utc,
                            resource=f"merged-{day_date.strftime('%Y%m%d')}-{first_shift.resource_id}",
                            backColor=event_back_color,
                            type=event_type,
                            editable=is_editable,
                            startEditable=False,
                            durationEditable=False,
                            resourceEditable=False,
                            overlap=True,
                            groupId=event_group_id,
                            display=display_type,
                            allDay=all_day,
                            user_role=user.role if user else None,
                            user_color=user_color,
                            consecutive_shifts=len(sequence) - 1,
                            is_first_in_sequence=True,
                            is_last_in_sequence=True,
                            total_sequence_length=len(sequence)
                        )
                    )
    holidays = _get_canadian_holidays(start_date.date(), end_date.date())
    for holiday_date, holiday_name in holidays:
        response_events.append(
            models.ScheduleEvent(
                id=f"holiday-{holiday_date.strftime('%Y%m%d')}",
                text=f"Holiday: {holiday_name}",
                start=datetime.combine(holiday_date, datetime.min.time(), tzinfo=timezone.utc),
                end=datetime.combine(holiday_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc),
                resource="",
                backColor="#D3D3D3",
                type="holiday",
                editable=False,
                startEditable=False,
                durationEditable=False,
                resourceEditable=False,
                overlap=False,
                groupId=None,
                display="background",
                allDay=False,
                user_role=None,
                user_color="#D3D3D3"
            )
        )
    for unavailability in db_unavailabilities:
        user = session.get(models.UserInDB, unavailability.user_id)
        username_display = user.username if user else "Unknown User"
        unavailability_color = "#FFD700" if user and user.role == models.UserRoleEnum.admin else "#808080"
        is_editable = (current_user.id == user.id) if user else False
        if current_user.role == models.UserRoleEnum.admin:
            is_editable = True
        response_events.append(
            models.ScheduleEvent(
                id=f"unavail-{unavailability.id}",
                text=f"UNAVAILABLE: {username_display} ({unavailability.reason or 'No Reason'})",
                start=unavailability.start_time_utc,
                end=unavailability.end_time_utc,
                resource="",
                backColor=unavailability_color,
                type="unavailability",
                editable=is_editable,
                startEditable=False,
                durationEditable=False,
                resourceEditable=False,
                overlap=False,
                groupId=str(user.id) if user else None,
                display="block",
                allDay=True,
                user_role=user.role if user else None,
                user_color=unavailability_color
            )
        )
    logger.info(f"Returning {len(response_events)} events from database.")
    return response_events

@router.post("/api/schedule/shifts", response_model=models.ScheduleEvent, status_code=status.HTTP_201_CREATED)
async def create_schedule_event_api(
    event_in: models.ScheduleEventCreate,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session)
):
    logger.info(f"User '{current_user.username}' creating event. Client data: {event_in}")
    final_start_dt: datetime
    final_end_dt: datetime
    final_resource_id: str = event_in.resource
    if event_in.resource.startswith("SLOT_"):
        try:
            day_date_str = event_in.start.split("T")[0]
            day_dt = datetime.fromisoformat(day_date_str).replace(tzinfo=timezone.utc)
            slot_parts = event_in.resource.split("_")
            start_hour = int(slot_parts[1])
            end_hour_calc = (start_hour + 3) % 24
            final_start_dt = day_dt.replace(hour=start_hour, minute=0, second=0, microsecond=0)
            final_end_dt = final_start_dt + timedelta(hours=3)
        except (IndexError, ValueError) as e:
            logger.error(f"Error parsing SLOT resource ID '{event_in.resource}' or date '{event_in.start}': {e}")
            raise HTTPException(status_code=400, detail="Invalid slot or date format from client.")
    else:
        final_start_dt = datetime.fromisoformat(event_in.start.replace("Z", "+00:00"))
        final_end_dt = datetime.fromisoformat(event_in.end.replace("Z", "+00:00"))
        logger.info(f"create_schedule_event_api - Received slot: start={final_start_dt.isoformat()}, end={final_end_dt.isoformat()}");
    duration_hours = (final_end_dt - final_start_dt).total_seconds() / 3600
    if not (abs(duration_hours - 3) < 0.01 and final_start_dt.minute == 0 and final_start_dt.second == 0):
        logger.warning(f"Invalid shift slot attempted: Start time must be on the hour and duration must be 3 hours. Received start: {final_start_dt}, end: {final_end_dt}")
        raise HTTPException(status_code=400, detail="Invalid shift slot. Must be a 3-hour block starting on a designated hour.")
    user_in_db = auth.get_user_from_db(session, current_user.username)
    if not user_in_db:
        logger.error(f"Consistency error: User '{current_user.username}' found by token but not in DB for event creation.")
        raise HTTPException(status_code=500, detail="User not found in database.")
    overlap_statement = select(models.ShiftAssignment).where(
        models.ShiftAssignment.resource_id == final_resource_id,
        models.ShiftAssignment.start_time_utc < final_end_dt,
        models.ShiftAssignment.end_time_utc > final_start_dt
    )
    existing_assignment = session.exec(overlap_statement).first()
    if existing_assignment:
        logger.warning(f"Overlap detected for resource {final_resource_id} at {final_start_dt}")
        raise HTTPException(status_code=409, detail="This shift slot is already taken.")
    db_assignment = models.ShiftAssignment(
        user_id=user_in_db.id,
        start_time_utc=final_start_dt,
        end_time_utc=final_end_dt,
        resource_id=final_resource_id,
    )
    session.add(db_assignment)
    session.commit()
    session.refresh(db_assignment)
    logger.info(f"ShiftAssignment created with ID {db_assignment.id} for user {current_user.username}")
    user_assigned_color = user_in_db.color if user_in_db and user_in_db.color else "#DDDDDD"
    return models.ScheduleEvent(
        id=str(db_assignment.id),
        text=current_user.username,
        start=db_assignment.start_time_utc,
        end=db_assignment.end_time_utc,
        resource=db_assignment.resource_id,
        groupId=str(user_in_db.id),
        backColor=user_assigned_color
    )

@router.post("/api/schedule/lri_blocks", response_model=List[models.ScheduleEvent], status_code=status.HTTP_201_CREATED)
async def create_lri_blocks_api(
    block_in: models.LRIBlockCreate,
    current_admin: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session)
):
    logger.info(f"Admin '{current_admin.username}' creating LRI blocks from {block_in.start_date} to {block_in.end_date}.")
    lri_pilot_user = auth.get_user_from_db(session, "LRI_PILOT")
    if not lri_pilot_user:
        raise HTTPException(status_code=500, detail="LRI_PILOT user not found in database. Please ensure it's initialized.")
    created_events = []
    current_date = block_in.start_date
    valid_start_hours_utc = [2, 5, 8, 11, 14, 17, 20, 23]
    while current_date <= block_in.end_date:
        is_weekday = current_date.weekday() < 5
        holidays_for_year = {h[0] for h in _get_canadian_holidays(current_date, current_date)}
        is_holiday = current_date in holidays_for_year
        hours_to_block = []
        if is_weekday and not is_holiday:
            hours_to_block = [23, 2, 5, 8]
        elif not is_weekday or is_holiday:
            hours_to_block = valid_start_hours_utc
        for hour_utc in hours_to_block:
            shift_start_utc = datetime.combine(current_date, datetime.min.time(), tzinfo=timezone.utc).replace(hour=hour_utc)
            shift_end_utc = shift_start_utc + timedelta(hours=3)
            overlap_statement = select(models.ShiftAssignment).where(
                models.ShiftAssignment.resource_id == shift_start_utc.isoformat(),
                models.ShiftAssignment.start_time_utc < shift_end_utc,
                models.ShiftAssignment.end_time_utc > shift_start_utc
            )
            existing_assignment = session.exec(overlap_statement).first()
            if existing_assignment:
                logger.warning(f"Skipping LRI block for {shift_start_utc.isoformat()} due to existing assignment.")
                continue
            db_assignment = models.ShiftAssignment(
                user_id=lri_pilot_user.id,
                start_time_utc=shift_start_utc,
                end_time_utc=shift_end_utc,
                resource_id=shift_start_utc.isoformat(),
            )
            session.add(db_assignment)
            session.commit()
            session.refresh(db_assignment)
            logger.info(f"LRI ShiftAssignment created with ID {db_assignment.id} for {shift_start_utc.isoformat()}")
            created_events.append(
                models.ScheduleEvent(
                    id=str(db_assignment.id),
                    text="LRI Block",
                    start=db_assignment.start_time_utc,
                    end=db_assignment.end_time_utc,
                    resource=db_assignment.resource_id,
                    backColor=lri_pilot_user.color,
                    type="lri_block",
                    editable=True,
                    startEditable=False,
                    durationEditable=False,
                    resourceEditable=False,
                    overlap=False,
                    groupId=str(lri_pilot_user.id),
                    display="block",
                    allDay=False,
                    user_role=lri_pilot_user.role,
                    user_color=lri_pilot_user.color
                )
            )
        current_date += timedelta(days=1)
    return created_events

@router.delete("/api/schedule/lri_blocks/{shift_assignment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lri_block_api(
    shift_assignment_id: int,
    current_admin: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session)
):
    logger.info(f"Admin '{current_admin.username}' attempting to delete LRI block ID: {shift_assignment_id}")
    lri_pilot_user = auth.get_user_from_db(session, "LRI_PILOT")
    if not lri_pilot_user:
        raise HTTPException(status_code=500, detail="LRI_PILOT user not found.")
    db_assignment = session.get(models.ShiftAssignment, shift_assignment_id)
    if not db_assignment:
        raise HTTPException(status_code=404, detail="LRI block not found.")
    if db_assignment.user_id != lri_pilot_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this shift (not an LRI block).")
    session.delete(db_assignment)
    session.commit()
    logger.info(f"LRI block ID {shift_assignment_id} deleted successfully.")
    return

@router.post("/api/schedule/unavailability", response_model=models.UserUnavailabilityResponse, status_code=status.HTTP_201_CREATED)
async def create_unavailability_api(
    unavailability_in: models.UserUnavailabilityCreate,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session)
):
    logger.info(f"User '{current_user.username}' creating unavailability: {unavailability_in}")
    user_in_db = auth.get_user_from_db(session, current_user.username)
    if not user_in_db:
        raise HTTPException(status_code=500, detail="User not found in database.")
    if unavailability_in.start_time_utc > unavailability_in.end_time_utc:
        raise HTTPException(status_code=400, detail="End date cannot be before start date.")
    exclusive_end_time = unavailability_in.end_time_utc + timedelta(days=1)
    overlap_statement = select(models.ShiftAssignment).where(
        models.ShiftAssignment.user_id == user_in_db.id,
        models.ShiftAssignment.start_time_utc < exclusive_end_time,
        models.ShiftAssignment.end_time_utc > unavailability_in.start_time_utc
    )
    existing_shift_overlap = session.exec(overlap_statement).first()
    if existing_shift_overlap:
        raise HTTPException(status_code=409, detail="Cannot block out time that overlaps with your existing shifts.")
    db_unavailability = models.UserUnavailability(
        user_id=user_in_db.id,
        start_time_utc=unavailability_in.start_time_utc,
        end_time_utc=exclusive_end_time,
        reason=unavailability_in.reason,
    )
    session.add(db_unavailability)
    session.commit()
    session.refresh(db_unavailability)
    logger.info(f"UserUnavailability created with ID {db_unavailability.id} for user {current_user.username}")
    return models.UserUnavailabilityResponse(
        id=db_unavailability.id,
        user_id=db_unavailability.user_id,
        username=current_user.username,
        user_role=current_user.role,
        user_color=user_in_db.color,
        start_time_utc=db_unavailability.start_time_utc,
        end_time_utc=db_unavailability.end_time_utc,
        reason=db_unavailability.reason,
        created_at_utc=db_unavailability.created_at_utc
    )

@router.delete("/api/schedule/unavailability/{unavailability_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_unavailability_api(
    unavailability_id: int,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session)
):
    logger.info(f"User '{current_user.username}' attempting to delete unavailability ID: {unavailability_id}")
    db_unavailability = session.get(models.UserUnavailability, unavailability_id)
    if not db_unavailability:
        raise HTTPException(status_code=404, detail="Unavailability entry not found.")
    if db_unavailability.user_id != current_user.id and current_user.role != models.UserRoleEnum.admin:
        raise HTTPException(status_code=403, detail="Not authorized to delete this unavailability entry.")
    session.delete(db_unavailability)
    session.commit()
    logger.info(f"Unavailability ID {unavailability_id} deleted successfully.")
    return

@router.delete("/api/schedule/clear_range", status_code=status.HTTP_204_NO_CONTENT)
async def clear_range_api(
    start_date: date = Query(...),
    end_date: date = Query(...),
    current_admin: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session)
):
    logger.info(f"Admin '{current_admin.username}' attempting to clear all shifts and blocks from {start_date} to {end_date}")
    start_of_range_utc = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
    end_of_range_utc = datetime.combine(end_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
    shift_delete_statement = delete(models.ShiftAssignment).where(
        models.ShiftAssignment.start_time_utc < end_of_range_utc,
        models.ShiftAssignment.end_time_utc > start_of_range_utc
    )
    shifts_deleted_result = session.exec(shift_delete_statement)
    shifts_deleted_count = shifts_deleted_result.rowcount
    logger.info(f"Deleted {shifts_deleted_count} shift assignments for range {start_date} to {end_date}.")
    unavailability_delete_statement = delete(models.UserUnavailability).where(
        models.UserUnavailability.start_time_utc < end_of_range_utc,
        models.UserUnavailability.end_time_utc > start_of_range_utc
    )
    unavailabilities_deleted_result = session.exec(unavailability_delete_statement)
    unavailabilities_deleted_count = unavailabilities_deleted_result.rowcount
    logger.info(f"Deleted {unavailabilities_deleted_count} unavailability entries for range {start_date} to {end_date}.")
    session.commit()
    return

@router.get("/api/schedule/events/{shift_assignment_id}/pic_handoffs", response_model=List[models.PicHandoffLinkInfo])
async def get_pic_handoffs_for_shift(
    shift_assignment_id: int,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session)
):
    logger.info(f"User '{current_user.username}' requesting PIC Handoffs for shift ID {shift_assignment_id}.")
    shift_assignment = session.get(models.ShiftAssignment, shift_assignment_id)
    if not shift_assignment:
        raise HTTPException(status_code=404, detail="Shift assignment not found.")
    logger.info(f"Shift ID {shift_assignment_id} details: StartUTC='{shift_assignment.start_time_utc.isoformat()}', EndUTC='{shift_assignment.end_time_utc.isoformat()}'")
    statement = select(models.SubmittedForm).where(
        models.SubmittedForm.form_type == "pic_handoff_checklist",
        models.SubmittedForm.submission_timestamp >= shift_assignment.start_time_utc,
        models.SubmittedForm.submission_timestamp <= shift_assignment.end_time_utc
    ).order_by(models.SubmittedForm.submission_timestamp.desc())
    all_pic_handoffs_debug_stmt = select(models.SubmittedForm).where(models.SubmittedForm.form_type == "pic_handoff_checklist").order_by(models.SubmittedForm.submission_timestamp.desc())
    all_pic_handoffs_in_db = session.exec(all_pic_handoffs_debug_stmt).all()
    logger.debug(f"Total 'pic_handoff_checklist' forms in DB: {len(all_pic_handoffs_in_db)}")
    for f_debug in all_pic_handoffs_in_db[:5]:
        logger.debug(f"  Debug - Form ID: {f_debug.id}, Mission: {f_debug.mission_id}, Timestamp: {f_debug.submission_timestamp.isoformat()}, Type: {f_debug.form_type}")
    submitted_forms = session.exec(statement).all()
    logger.info(f"Query for shift {shift_assignment_id} (time range: {shift_assignment.start_time_utc.isoformat()} to {shift_assignment.end_time_utc.isoformat()}) found {len(submitted_forms)} matching 'pic_handoff_checklist' forms within the timeframe.")
    if not submitted_forms and all_pic_handoffs_in_db:
        logger.warning("No forms found for the specific shift time range, but 'pic_handoff_checklist' forms exist in general. Please verify timestamps and ensure they are UTC and overlap with the shift period.")
    handoff_links = []
    for form in submitted_forms:
        handoff_links.append(
            models.PicHandoffLinkInfo(
                form_db_id=form.id,
                mission_id=form.mission_id,
                form_title=form.form_title,
                submitted_by_username=form.submitted_by_username,
                submission_timestamp=form.submission_timestamp
            )
        )
    logger.info(f"Found {len(handoff_links)} PIC Handoff forms for shift {shift_assignment_id} across all missions.")
    return handoff_links

@router.get("/api/schedule/my-upcoming-shifts", response_model=List[models.UpcomingShift])
async def get_my_upcoming_shifts(
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session)
):
    user_in_db = auth.get_user_from_db(session, current_user.username)
    if not user_in_db:
        raise HTTPException(status_code=404, detail="Current user not found in database.")
    now_utc = datetime.now(timezone.utc)
    statement = select(
        models.ShiftAssignment.resource_id.label("mission_id"),
        models.ShiftAssignment.start_time_utc,
        models.ShiftAssignment.end_time_utc
    ).where(
        models.ShiftAssignment.user_id == user_in_db.id,
        models.ShiftAssignment.start_time_utc > now_utc
    ).order_by(models.ShiftAssignment.start_time_utc).limit(5)
    results = session.exec(statement).all()
    return [models.UpcomingShift.model_validate(row) for row in results]

@router.delete("/api/schedule/shifts/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule_event_api(
    event_id: str,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session)
):
    logger.info(f"User '{current_user.username}' attempting to delete event ID: {event_id}")
    if event_id.startswith("unavail-"):
        try:
            unavailability_id = int(event_id.split("-")[1])
            return await delete_unavailability_api(unavailability_id, current_user, session)
        except (ValueError, IndexError):
            raise HTTPException(status_code=400, detail="Invalid unavailability event ID format.")
    try:
        assignment_id = int(event_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid shift event ID format.")
    db_assignment = session.get(models.ShiftAssignment, assignment_id)
    if not db_assignment:
        logger.warning(f"Shift assignment ID {assignment_id} not found for deletion.")
        raise HTTPException(status_code=404, detail="Shift assignment not found.")
    is_admin = current_user.role == models.UserRoleEnum.admin
    user_in_db_for_auth = auth.get_user_from_db(session, current_user.username)
    if not user_in_db_for_auth:
        logger.error(f"Consistency error: User '{current_user.username}' not found in DB for auth.")
        raise HTTPException(status_code=500, detail="User not found in database for authorization.")
    lri_pilot_user = auth.get_user_from_db(session, "LRI_PILOT")
    is_lri_block = lri_pilot_user and db_assignment.user_id == lri_pilot_user.id
    if is_lri_block:
        if not is_admin:
            logger.warning(f"Non-admin user '{current_user.username}' attempted to delete LRI block ID {assignment_id}.")
            raise HTTPException(status_code=403, detail="Only administrators can delete LRI blocks.")
    elif db_assignment.user_id != user_in_db_for_auth.id and not is_admin:
        owner = session.get(models.UserInDB, db_assignment.user_id)
        owner_username = owner.username if owner else "unknown"
        logger.warning(f"User '{current_user.username}' not authorized to delete event ID {event_id} owned by '{owner_username}'.")
        raise HTTPException(status_code=403, detail="Not authorized to delete this event.")
    session.delete(db_assignment)
    session.commit()
    logger.info(f"Shift assignment ID {assignment_id} deleted successfully by '{current_user.username}'.")
    return

@router.get("/api/schedule/download")
async def download_schedule_data(
    start_date: date,
    end_date: date,
    format: str = Query(..., pattern="^(ics|csv)$"),
    user_scope: str = Query("all_users", pattern="^(all_users|my_shifts)$"),
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session)
):
    logger.info(f"User '{current_user.username}' requested schedule download. Format: {format}, Range: {start_date} to {end_date}, Scope: {user_scope}")
    if start_date > end_date:
        raise HTTPException(status_code=400, detail="Start date cannot be after end date.")
    start_datetime_utc = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
    end_datetime_utc = datetime.combine(end_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
    statement = select(models.ShiftAssignment).where(
        models.ShiftAssignment.start_time_utc >= start_datetime_utc,
        models.ShiftAssignment.start_time_utc < end_datetime_utc
    )
    user_in_db_for_filter = None
    if user_scope == "my_shifts":
        user_in_db_for_filter = auth.get_user_from_db(session, current_user.username)
        if not user_in_db_for_filter:
            logger.error(f"Could not find UserInDB for current_user {current_user.username} when filtering for 'my_shifts'. This should not happen if user is authenticated.")
            raise HTTPException(status_code=404, detail="Current user details not found for filtering.")
        statement = statement.where(models.ShiftAssignment.user_id == user_in_db_for_filter.id)
    statement = statement.order_by(models.ShiftAssignment.start_time_utc)
    db_assignments = session.exec(statement).all()
    user_ids = {assign.user_id for assign in db_assignments}
    users_map = {}
    if user_ids:
        users_stmt = select(models.UserInDB).where(models.UserInDB.id.in_(user_ids))
        db_users = session.exec(users_stmt).all()
        users_map = {user.id: user for user in db_users}
    filename_suffix = ""
    if user_scope == "my_shifts" and user_in_db_for_filter:
        filename_suffix = f"_{user_in_db_for_filter.username.replace(' ', '_')}"
    filename_base = f"schedule_{start_date.strftime('%Y%m%d')}_to_{end_date.strftime('%Y%m%d')}{filename_suffix}"
    if format == "ics":
        cal = ics.Calendar()
        for assignment in db_assignments:
            user = users_map.get(assignment.user_id)
            username = user.username if user else "Unknown User"
            slot_name_display = assignment.resource_id
            if assignment.resource_id.startswith("SLOT_"):
                try:
                    parts = assignment.resource_id.split("_")
                    slot_start_hour = int(parts[1])
                    slot_end_hour = (slot_start_hour + 3) % 24
                    slot_name_display = f"{slot_start_hour:02d}:00-{slot_end_hour:02d}:00"
                except (IndexError, ValueError):
                    pass
            event_name = f"Shift: {username} ({slot_name_display})"
            ics_event = ics.Event()
            ics_event.name = event_name
            ics_event.begin = assignment.start_time_utc
            ics_event.end = assignment.end_time_utc
            ics_event.description = f"Shift assigned to {username} for time slot {slot_name_display} on {assignment.start_time_utc.strftime('%Y-%m-%d')}."
            cal.events.add(ics_event)
        content = str(cal)
        media_type = "text/calendar"
        filename = f"{filename_base}.ics"
    elif format == "csv":
        output = io.StringIO()
        csv_writer = csv.writer(output)
        headers = ["Subject", "Start Date", "Start Time", "End Date", "End Time", "Assigned To", "Time Slot ID", "Description"]
        csv_writer.writerow(headers)
        for assignment in db_assignments:
            user = users_map.get(assignment.user_id)
            username = user.username if user else "Unknown User"
            slot_name_display = assignment.resource_id
            if assignment.resource_id.startswith("SLOT_"):
                try:
                    parts = assignment.resource_id.split("_")
                    slot_start_hour = int(parts[1]); slot_end_hour = (slot_start_hour + 3) % 24
                    slot_name_display = f"{slot_start_hour:02d}:00-{slot_end_hour:02d}:00"
                except: pass
            subject = f"Shift: {username} ({slot_name_display})"
            description = f"Shift for {username} covering time slot {slot_name_display} on {assignment.start_time_utc.strftime('%Y-%m-%d')}."
            csv_writer.writerow([subject, assignment.start_time_utc.strftime("%Y-%m-%d"), assignment.start_time_utc.strftime("%H:%M:%S UTC"), assignment.end_time_utc.strftime("%Y-%m-%d"), assignment.end_time_utc.strftime("%H:%M:%S UTC"), username, assignment.resource_id, description])
        content = output.getvalue()
        media_type = "text/csv"
        filename = f"{filename_base}.csv"
        output.close()
    else:
        raise HTTPException(status_code=400, detail="Invalid format specified.")
    return StreamingResponse(io.BytesIO(content.encode("utf-8")), media_type=media_type, headers={"Content-Disposition": f"attachment; filename=\"{filename}\""}) 