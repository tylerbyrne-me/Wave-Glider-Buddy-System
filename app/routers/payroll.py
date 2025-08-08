from fastapi import APIRouter, Depends, HTTPException, status, Request, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from typing import List, Optional
from datetime import date, datetime, timedelta, timezone
from sqlmodel import select, delete, func, case
from ..core import models
from ..db import get_db_session, SQLModelSession
from ..auth_utils import get_current_active_user, get_current_admin_user, get_optional_current_user
import io
import csv
import logging
from fastapi import BackgroundTasks
from pydantic import BaseModel
from fastapi_mail import FastMail, MessageSchema, ConnectionConfig
# (PayPeriodUpdate and MonthlyChartData have been moved to app/core/models.py)
import calendar
from app.core.templates import templates
from .. import auth_utils

router = APIRouter(tags=["Payroll"])
logger = logging.getLogger(__name__)

# --- Payroll and Timesheet Endpoints ---

@router.get("/api/pay_periods/open", response_model=List[models.PayPeriod])
async def get_open_pay_periods(
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session)
):
    """
    Get a list of pay periods that are currently open for submission, filtering out
    any periods for which the user already has an active 'submitted' or 'approved' timesheet.
    """
    # Get the current user's DB entry
    user_in_db = auth_utils.get_user_from_db(session, current_user.username)
    if not user_in_db:
        raise HTTPException(status_code=404, detail="Current user not found in database.")

    # Find pay periods for which the user has an active, non-rejected timesheet
    submitted_periods_stmt = select(models.Timesheet.pay_period_id).where(
        models.Timesheet.user_id == user_in_db.id,
        models.Timesheet.is_active == True,
        models.Timesheet.status.in_([models.TimesheetStatusEnum.SUBMITTED, models.TimesheetStatusEnum.APPROVED])
    )
    submitted_period_ids = session.exec(submitted_periods_stmt).all()

    # Fetch all open pay periods and filter out the ones already submitted.
    open_periods_stmt = select(models.PayPeriod).where(
        models.PayPeriod.status == models.PayPeriodStatusEnum.OPEN
    ).order_by(models.PayPeriod.start_date.desc())
    if submitted_period_ids:
        open_periods_stmt = open_periods_stmt.where(models.PayPeriod.id.notin_(submitted_period_ids))
    
    return session.exec(open_periods_stmt).all()

@router.get("/api/timesheets/calculate", response_model=dict)
async def calculate_timesheet_hours(
    pay_period_id: int,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session)
):
    """
    Calculates the total shift hours for the current user within a given pay period.
    """
    pay_period = session.get(models.PayPeriod, pay_period_id)
    if not pay_period:
        raise HTTPException(status_code=404, detail="Pay period not found.")

    user_in_db = auth_utils.get_user_from_db(session, current_user.username)
    if not user_in_db:
        raise HTTPException(status_code=404, detail="Current user not found in database.")

    start_datetime = datetime.combine(pay_period.start_date, datetime.min.time(), tzinfo=timezone.utc)
    end_datetime = datetime.combine(pay_period.end_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)

    shift_statement = select(models.ShiftAssignment).where(
        models.ShiftAssignment.user_id == user_in_db.id,
        models.ShiftAssignment.start_time_utc >= start_datetime,
        models.ShiftAssignment.end_time_utc < end_datetime
    )
    shifts = session.exec(shift_statement).all()

    total_hours = sum(
        (shift.end_time_utc - shift.start_time_utc).total_seconds() / 3600
        for shift in shifts
    )

    return {"calculated_hours": round(total_hours, 2)}

@router.post("/api/timesheets", response_model=models.Timesheet, status_code=status.HTTP_201_CREATED)
async def submit_timesheet(
    timesheet_in: models.TimesheetCreate,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session)
):
    """
    Submits a new, active timesheet for the current user for a specific pay period.
    If an active timesheet already exists (e.g., a rejected one), it will be
    deactivated, and this new submission will become the active one.
    """
    user_in_db = auth_utils.get_user_from_db(session, current_user.username)
    if not user_in_db:
        raise HTTPException(status_code=404, detail="Current user not found in database.")

    # Deactivate any previously active timesheet for this user and pay period
    existing_active_timesheet_stmt = select(models.Timesheet).where(
        models.Timesheet.user_id == user_in_db.id,
        models.Timesheet.pay_period_id == timesheet_in.pay_period_id,
        models.Timesheet.is_active == True
    )
    existing_active_timesheet = session.exec(existing_active_timesheet_stmt).first()

    if existing_active_timesheet:
        # If the existing active timesheet is approved or submitted, block resubmission.
        if existing_active_timesheet.status in [models.TimesheetStatusEnum.APPROVED, models.TimesheetStatusEnum.SUBMITTED]:
             raise HTTPException(status_code=409, detail="An active timesheet for this pay period is already submitted or approved.")
        
        # If it's rejected, we can proceed. Deactivate the old one.
        logger.info(f"Deactivating previous timesheet (ID: {existing_active_timesheet.id}) for user '{current_user.username}' for pay period {timesheet_in.pay_period_id}.")
        existing_active_timesheet.is_active = False
        session.add(existing_active_timesheet)

    # Create a new, active timesheet record.
    logger.info(f"User '{current_user.username}' submitting a new active timesheet for pay period {timesheet_in.pay_period_id}.")

    db_timesheet = models.Timesheet.model_validate(timesheet_in.model_dump() | {"user_id": user_in_db.id})
    session.add(db_timesheet)
    session.commit()
    session.refresh(db_timesheet)
    return db_timesheet

@router.get("/api/timesheets/my_submissions", response_model=List[models.TimesheetRead])
async def get_my_timesheet_submissions(
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session)
):
    """
    Gets all of the current user's timesheet submissions (active and inactive),
    ordered by pay period and then by submission date.
    """
    user_in_db = auth_utils.get_user_from_db(session, current_user.username)
    if not user_in_db:
        raise HTTPException(status_code=404, detail="Current user not found in database.")

    # Join Timesheet with PayPeriod to order by pay period start date
    statement = select(models.Timesheet, models.PayPeriod).join(models.PayPeriod).where(
        models.Timesheet.user_id == user_in_db.id
    ).order_by(
        models.PayPeriod.start_date.desc(), 
        models.Timesheet.submission_timestamp.desc()
    )
    
    results = session.exec(statement).all()
    return [models.TimesheetRead.model_validate(ts.model_dump() | {"username": user_in_db.username, "pay_period_name": pp.name}) for ts, pp in results]

@router.get("/api/timesheets/my-timesheet-status", response_model=models.MyTimesheetStatus)
async def get_my_timesheet_status_for_home_panel(
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session)
):
    """
    Gets a summary of the user's timesheet status for the current/most recent pay period.
    """
    user_in_db = auth_utils.get_user_from_db(session, current_user.username)
    if not user_in_db:
        raise HTTPException(status_code=404, detail="Current user not found in database.")

    # Find the most recent pay period that is currently open
    now = date.today()
    current_pay_period = session.exec(
        select(models.PayPeriod)
        .where(models.PayPeriod.start_date <= now, models.PayPeriod.end_date >= now, models.PayPeriod.status == models.PayPeriodStatusEnum.OPEN)
        .order_by(models.PayPeriod.start_date.desc())
    ).first()

    if not current_pay_period:
        return models.MyTimesheetStatus(current_period_status="No Open Period", hours_this_period=0.0)

    # Check the user's timesheet status for this period
    timesheet_status = "Not Submitted"
    active_timesheet = session.exec(
        select(models.Timesheet).where(
            models.Timesheet.user_id == user_in_db.id,
            models.Timesheet.pay_period_id == current_pay_period.id,
            models.Timesheet.is_active == True
        )
    ).first()

    if active_timesheet:
        timesheet_status = active_timesheet.status.value.capitalize()

    # Calculate hours logged in this period
    start_datetime = datetime.combine(current_pay_period.start_date, datetime.min.time(), tzinfo=timezone.utc)
    end_datetime = datetime.combine(current_pay_period.end_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
    shifts = session.exec(select(models.ShiftAssignment).where(models.ShiftAssignment.user_id == user_in_db.id, models.ShiftAssignment.start_time_utc >= start_datetime, models.ShiftAssignment.end_time_utc < end_datetime)).all()
    total_hours = sum((shift.end_time_utc - shift.start_time_utc).total_seconds() / 3600 for shift in shifts)

    return models.MyTimesheetStatus(current_period_status=f"{current_pay_period.name}: {timesheet_status}", hours_this_period=total_hours)

@router.get("/api/timesheets/my_status", response_model=List[models.TimesheetStatusForUser])
async def get_my_timesheet_statuses(
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session)
):
    """
    Gets the status of the current user's most recent *active* timesheet submission
    for each pay period they have submitted for.
    """
    user_in_db = auth_utils.get_user_from_db(session, current_user.username)
    if not user_in_db:
        raise HTTPException(status_code=404, detail="Current user not found in database.")

    # Get all *active* timesheets for the user, ordered by most recent submission
    timesheet_stmt = (
        select(models.Timesheet)
        .where(models.Timesheet.user_id == user_in_db.id, models.Timesheet.is_active == True)
        .order_by(models.Timesheet.submission_timestamp.desc())
    )
    active_timesheets = session.exec(timesheet_stmt).all()

    # To avoid N+1 queries, fetch the relevant pay periods and map them
    pay_period_ids = {ts.pay_period_id for ts in active_timesheets}
    pay_periods_map = {p.id: p for p in session.exec(select(models.PayPeriod).where(models.PayPeriod.id.in_(pay_period_ids))).all()} if pay_period_ids else {}

    response_list = []
    for ts in active_timesheets:
        pay_period = pay_periods_map.get(ts.pay_period_id)
        if pay_period:
            response_list.append(
                models.TimesheetStatusForUser(
                    pay_period_name=pay_period.name,
                    status=ts.status,
                    reviewer_notes=ts.reviewer_notes,
                    submission_timestamp=ts.submission_timestamp
                )
            )
    
    return response_list[:5] # Return the status for the 5 most recent pay periods

# /api/admin/timesheets/{timesheet_id}/history
@router.get("/api/admin/timesheets/{timesheet_id}/history", response_model=List[models.TimesheetRead])
async def admin_get_timesheet_history(
    timesheet_id: int,
    current_admin: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session)
):
    """
    Admin-only endpoint to retrieve the full submission history for a specific
    timesheet entry (i.e., all versions for that user and pay period).
    """
    # First, get the reference timesheet to find the user_id and pay_period_id
    ref_timesheet = session.get(models.Timesheet, timesheet_id)
    if not ref_timesheet:
        raise HTTPException(status_code=404, detail="Timesheet not found.")

    logger.info(f"Admin '{current_admin.username}' requesting history for timesheet ID {timesheet_id} (user_id: {ref_timesheet.user_id}, pay_period_id: {ref_timesheet.pay_period_id}).")

    # Now, query for all timesheets with the same user_id and pay_period_id
    history_stmt = select(models.Timesheet).where(
        models.Timesheet.user_id == ref_timesheet.user_id,
        models.Timesheet.pay_period_id == ref_timesheet.pay_period_id
    ).order_by(models.Timesheet.submission_timestamp.desc())
    
    history_timesheets = session.exec(history_stmt).all()

    user = session.get(models.UserInDB, ref_timesheet.user_id)
    pay_period = session.get(models.PayPeriod, ref_timesheet.pay_period_id)
    
    if not user or not pay_period:
        raise HTTPException(status_code=500, detail="Could not retrieve associated user or pay period.")

    return [models.TimesheetRead.model_validate(ts.model_dump() | {"username": user.username, "pay_period_name": pay_period.name}) for ts in history_timesheets]

# /api/admin/timesheets/{timesheet_id} (PATCH)
@router.patch("/api/admin/timesheets/{timesheet_id}", response_model=models.Timesheet)
async def admin_update_timesheet_status(
    timesheet_id: int,
    timesheet_update: models.TimesheetUpdate,
    background_tasks: BackgroundTasks,
    current_admin: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session)
):
    """
    Admin-only endpoint to update the status and add reviewer notes to a timesheet.
    """
    logger.info(f"Admin '{current_admin.username}' attempting to update timesheet ID: {timesheet_id} with data: {timesheet_update.model_dump(exclude_unset=True)}")

    db_timesheet = session.get(models.Timesheet, timesheet_id)
    if not db_timesheet:
        raise HTTPException(status_code=404, detail="Timesheet not found.")

    update_data = timesheet_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_timesheet, key, value)
    
    # If status is being changed to APPROVED or REJECTED, ensure reviewer_notes are present
    if timesheet_update.status in [models.TimesheetStatusEnum.APPROVED, models.TimesheetStatusEnum.REJECTED] and not db_timesheet.reviewer_notes:
        raise HTTPException(status_code=400, detail="Reviewer notes are required when approving or rejecting a timesheet.")

    session.add(db_timesheet)
    session.commit()
    session.refresh(db_timesheet)

    # --- Send Email Notification on Status Change ---
    if timesheet_update.status in [models.TimesheetStatusEnum.APPROVED, models.TimesheetStatusEnum.REJECTED]:
        user_to_notify = session.get(models.UserInDB, db_timesheet.user_id)
        pay_period = session.get(models.PayPeriod, db_timesheet.pay_period_id)

        if user_to_notify and user_to_notify.email and pay_period:
            subject = f"Update on your timesheet for {pay_period.name}"
            
            email_context = {
                "user_name": user_to_notify.full_name or user_to_notify.username,
                "pay_period_name": pay_period.name,
                "status": db_timesheet.status.value,
                "reviewer_notes": db_timesheet.reviewer_notes,
                "is_approved": db_timesheet.status == models.TimesheetStatusEnum.APPROVED,
                "is_rejected": db_timesheet.status == models.TimesheetStatusEnum.REJECTED,
            }

            message = MessageSchema(
                subject=subject,
                recipients=[user_to_notify.email],
                template_body=email_context,
                subtype="html"
            )

            fm = FastMail(conf)
            background_tasks.add_task(fm.send_message, message, template_name="timesheet_status_update.html")
            logger.info(f"Queued email notification for user '{user_to_notify.username}' for timesheet ID {db_timesheet.id}.")
        elif not (user_to_notify and user_to_notify.email):
             logger.warning(f"Could not send email for timesheet {db_timesheet.id}: User '{user_to_notify.username if user_to_notify else 'N/A'}' does not have an email address configured.")

    return db_timesheet

# /api/admin/timesheets
@router.get("/api/admin/timesheets", response_model=List[models.TimesheetRead])
async def admin_get_timesheets(
    pay_period_id: int,
    current_admin: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session)
):
    """
    Retrieves all *active* submitted timesheets for a given pay period.
    """
    timesheet_stmt = select(models.Timesheet).where(
        models.Timesheet.pay_period_id == pay_period_id,
        models.Timesheet.is_active == True
    )
    timesheets = session.exec(timesheet_stmt).all()

    user_ids = {ts.user_id for ts in timesheets}
    users = {u.id: u for u in session.exec(select(models.UserInDB).where(models.UserInDB.id.in_(user_ids))).all()}
    
    pay_period = session.get(models.PayPeriod, pay_period_id)
    pay_period_name = pay_period.name if pay_period else "Unknown Period"

    response_data = []
    for ts in timesheets:
        user = users.get(ts.user_id)
        response_data.append(
            models.TimesheetRead(
                id=ts.id,
                user_id=ts.user_id,
                username=user.username if user else "Unknown",
                pay_period_id=ts.pay_period_id,
                pay_period_name=pay_period_name,
                calculated_hours=ts.calculated_hours,
                adjusted_hours=ts.adjusted_hours,
                notes=ts.notes,
                reviewer_notes=ts.reviewer_notes,
                status=ts.status,
                submission_timestamp=ts.submission_timestamp,
                is_active=ts.is_active
            )
        )
    return response_data

@router.get("/api/admin/pay_periods", response_model=List[models.PayPeriod])
async def admin_get_pay_periods(
    current_admin: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session)
):
    statement = select(models.PayPeriod).order_by(models.PayPeriod.start_date.desc())
    return session.exec(statement).all()

@router.post("/api/admin/pay_periods", response_model=models.PayPeriod, status_code=status.HTTP_201_CREATED)
async def admin_create_pay_period(
    pay_period_in: models.PayPeriodCreate,
    current_admin: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session)
):
    if pay_period_in.start_date > pay_period_in.end_date:
        raise HTTPException(status_code=400, detail="Start date cannot be after end date.")
    
    db_pay_period = models.PayPeriod.model_validate(pay_period_in)
    session.add(db_pay_period)
    session.commit()
    session.refresh(db_pay_period)
    return db_pay_period

@router.patch("/api/admin/pay_periods/{period_id}", response_model=models.PayPeriod)
async def admin_update_pay_period(
    period_id: int,
    pay_period_update: models.PayPeriodUpdate,
    current_admin: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session)
):
    db_pay_period = session.get(models.PayPeriod, period_id)
    if not db_pay_period:
        raise HTTPException(status_code=404, detail="Pay period not found.")

    update_data = pay_period_update.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No update data provided.")
    
    # Validate dates if they are being updated
    new_start = update_data.get("start_date", db_pay_period.start_date)
    new_end = update_data.get("end_date", db_pay_period.end_date)
    if new_start > new_end:
        raise HTTPException(status_code=400, detail="Start date cannot be after end date.")

    for key, value in update_data.items():
        setattr(db_pay_period, key, value)
    
    session.add(db_pay_period)
    session.commit()
    session.refresh(db_pay_period)
    return db_pay_period

@router.delete("/api/admin/pay_periods/{period_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_delete_pay_period(
    period_id: int,
    current_admin: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session)
):
    db_pay_period = session.get(models.PayPeriod, period_id)
    if not db_pay_period:
        raise HTTPException(status_code=404, detail="Pay period not found.")

    # Check for associated timesheets before deleting
    timesheet_check_stmt = select(models.Timesheet).where(models.Timesheet.pay_period_id == period_id).limit(1)
    if session.exec(timesheet_check_stmt).first():
        raise HTTPException(status_code=409, detail="Cannot delete pay period with submitted timesheets.")

    session.delete(db_pay_period)
    session.commit()
    return

# /api/admin/reports/payroll
@router.get("/api/admin/reports/payroll")
async def get_payroll_report(
    # ... params ...
):
    pass

# /api/admin/reports/payroll/download
@router.get("/api/admin/reports/payroll/download")
async def download_payroll_report(
    # ... params ...
):
    pass

# /api/admin/reports/payroll/summary
@router.get("/api/admin/reports/payroll/summary")
async def get_payroll_summary(
    # ... params ...
):
    pass

@router.get("/api/admin/reports/monthly_timesheet_summary", response_class=StreamingResponse)
async def get_monthly_timesheet_summary_report(
    year: int = Query(..., ge=2020, le=2100),
    month: int = Query(..., ge=1, le=12),
    current_admin: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session)
):
    """
    Admin-only endpoint to generate a CSV summary report of all active, approved
    timesheets for pay periods ending within a given month and year.
    """
    logger.info(f"Admin '{current_admin.username}' requesting monthly timesheet summary for {year}-{month:02d}.")

    try:
        start_of_month = date(year, month, 1)
        # calendar.monthrange(year, month) returns (weekday of first day, number of days in month)
        _, num_days = calendar.monthrange(year, month)
        end_of_month = date(year, month, num_days)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid year or month.")

    # Find pay periods that end within the selected month
    pay_periods_in_month_stmt = select(models.PayPeriod).where(
        models.PayPeriod.end_date >= start_of_month,
        models.PayPeriod.end_date <= end_of_month
    )
    pay_periods_in_month = session.exec(pay_periods_in_month_stmt).all()
    pay_period_ids = [pp.id for pp in pay_periods_in_month]

    # Find all active, approved timesheets for those pay periods
    approved_timesheets_stmt = select(models.Timesheet).where(
        models.Timesheet.pay_period_id.in_(pay_period_ids),
        models.Timesheet.status == models.TimesheetStatusEnum.APPROVED,
        models.Timesheet.is_active == True
    ).order_by(models.Timesheet.submission_timestamp)
    
    approved_timesheets = session.exec(approved_timesheets_stmt).all()

    # Eager load related data to prevent N+1 queries
    user_ids = {ts.user_id for ts in approved_timesheets}
    users_map = {u.id: u for u in session.exec(select(models.UserInDB).where(models.UserInDB.id.in_(user_ids))).all()} if user_ids else {}
    pay_periods_map = {pp.id: pp for pp in pay_periods_in_month}

    # Generate CSV
    output = io.StringIO()
    csv_writer = csv.writer(output)
    headers = [
        "Timesheet ID", "Pilot Username", "Full Name", "Pay Period Name", "Pay Period End Date",
        "Calculated Hours", "Adjusted Hours", "Final Approved Hours", "Status", "Submission Timestamp (UTC)", "Reviewer Notes"
    ]
    csv_writer.writerow(headers)

    total_hours = 0.0

    for ts in approved_timesheets:
        user = users_map.get(ts.user_id)
        pay_period = pay_periods_map.get(ts.pay_period_id)
        final_hours = ts.adjusted_hours if ts.adjusted_hours is not None else ts.calculated_hours
        total_hours += final_hours

        row = [ts.id, user.username if user else "Unknown", user.full_name if user else "Unknown", pay_period.name if pay_period else "Unknown", pay_period.end_date.isoformat() if pay_period else "Unknown", f"{ts.calculated_hours:.2f}", f"{ts.adjusted_hours:.2f}" if ts.adjusted_hours is not None else "", f"{final_hours:.2f}", ts.status.value, ts.submission_timestamp.isoformat(), ts.reviewer_notes or ""]
        csv_writer.writerow(row)
    
    # Add a summary row at the end
    csv_writer.writerow([]) # Blank row
    csv_writer.writerow(["", "", "", "", "", "", "Total Approved Hours:", f"{total_hours:.2f}"])

    output.seek(0)
    content = output.getvalue()
    filename = f"approved_timesheets_summary_{year}-{month:02d}.csv"
    return StreamingResponse(io.BytesIO(content.encode("utf-8")), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename=\"{filename}\""})

class MonthlyChartData(BaseModel):
    pilot_name: str
    total_hours: float

@router.get("/api/admin/reports/monthly_summary_chart", response_model=List[models.MonthlyChartData])
async def get_monthly_summary_chart_data(
    year: int = Query(..., ge=2020, le=2100),
    month: int = Query(..., ge=1, le=12),
    current_admin: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session)
):
    """
    Admin-only endpoint to generate data for a monthly summary chart of approved hours per pilot.
    """
    logger.info(f"Admin '{current_admin.username}' requesting monthly summary chart data for {year}-{month:02d}.")

    try:
        start_of_month = date(year, month, 1)
        _, num_days = calendar.monthrange(year, month)
        end_of_month = date(year, month, num_days)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid year or month.")

    pay_periods_in_month_stmt = select(models.PayPeriod.id).where(
        models.PayPeriod.end_date >= start_of_month,
        models.PayPeriod.end_date <= end_of_month
    )
    pay_period_ids = session.exec(pay_periods_in_month_stmt).all()

    if not pay_period_ids:
        return []

    final_hours_expression = case(
        (models.Timesheet.adjusted_hours.isnot(None), models.Timesheet.adjusted_hours),
        else_=models.Timesheet.calculated_hours
    )

    summary_stmt = (
        select(models.UserInDB.username, func.sum(final_hours_expression).label("total_hours"))
        .join(models.Timesheet, models.UserInDB.id == models.Timesheet.user_id)
        .where(
            models.Timesheet.pay_period_id.in_(pay_period_ids),
            models.Timesheet.status == models.TimesheetStatusEnum.APPROVED,
            models.Timesheet.is_active == True
        )
        .group_by(models.UserInDB.username)
        .order_by(func.sum(final_hours_expression).desc())
    )
    
    results = session.exec(summary_stmt).all()

    return [models.MonthlyChartData(pilot_name=username, total_hours=round(total_hours, 2)) for username, total_hours in results if total_hours is not None]

@router.get("/api/admin/timesheets/export_csv", response_class=StreamingResponse)
async def export_timesheets_csv(
    pay_period_id: int,
    current_admin: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session)
):
    """
    Admin-only endpoint to export all submitted timesheets for a given pay period to CSV.
    """
    logger.info(f"Admin '{current_admin.username}' requesting CSV export for pay period ID: {pay_period_id}")

    timesheet_stmt = select(models.Timesheet).where(models.Timesheet.pay_period_id == pay_period_id)
    timesheets = session.exec(timesheet_stmt).all()

    pay_period = session.get(models.PayPeriod, pay_period_id)
    if not pay_period:
        raise HTTPException(status_code=404, detail="Pay period not found.")
    
    # Fetch all users involved in these timesheets to avoid N+1 queries
    user_ids = {ts.user_id for ts in timesheets}
    users = {u.id: u for u in session.exec(select(models.UserInDB).where(models.UserInDB.id.in_(user_ids))).all()}

    output = io.StringIO()
    csv_writer = csv.writer(output)

    headers = [
        "Timesheet ID", "Pilot Username", "Pay Period Name", "Pay Period Start", "Pay Period End",
        "Calculated Hours", "Adjusted Hours", "Final Hours", "Pilot Notes", "Reviewer Notes", "Status", "Submission Timestamp (UTC)"
    ]
    csv_writer.writerow(headers)

    for ts in timesheets:
        user = users.get(ts.user_id)
        username = user.username if user else "Unknown"
        final_hours = ts.adjusted_hours if ts.adjusted_hours is not None else ts.calculated_hours

        row = [
            ts.id, username, pay_period.name, pay_period.start_date.isoformat(), pay_period.end_date.isoformat(),
            f"{ts.calculated_hours:.2f}", f"{ts.adjusted_hours:.2f}" if ts.adjusted_hours is not None else "", f"{final_hours:.2f}",
            ts.notes or "", ts.reviewer_notes or "", ts.status.value, ts.submission_timestamp.isoformat()
        ]
        csv_writer.writerow(row)

    output.seek(0)
    filename = f"timesheets_{pay_period.name.replace(' ', '_').replace('-', '_')}.csv"
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename=\"{filename}\""})

# Add any payroll/timesheet/pay period helpers here 

@router.get("/payroll/submit.html", response_class=HTMLResponse)
async def get_payroll_submit_page(
    request: Request,
    current_user: Optional[models.User] = Depends(get_optional_current_user)
):
    return templates.TemplateResponse(
        "payroll_submit.html",
        {"request": request, "current_user": current_user},
    )

@router.get("/payroll/my_timesheets.html", response_class=HTMLResponse)
async def get_my_timesheets_page(
    request: Request,
    current_user: Optional[models.User] = Depends(get_optional_current_user)
):
    return templates.TemplateResponse(
        "my_timesheets.html",
        {"request": request, "current_user": current_user},
    )

@router.get("/admin/pay_periods.html", response_class=HTMLResponse)
async def get_admin_pay_periods_page(
    request: Request,
    current_user: Optional[models.User] = Depends(get_optional_current_user)
):
    return templates.TemplateResponse(
        "admin_pay_periods.html",
        {"request": request, "current_user": current_user},
    )

@router.get("/admin/timesheets.html", response_class=HTMLResponse)
async def get_admin_view_timesheets_page(
    request: Request,
    current_user: Optional[models.User] = Depends(get_optional_current_user)
):
    return templates.TemplateResponse(
        "admin_view_timesheets.html",
        {"request": request, "current_user": current_user},
    )

@router.get("/admin/reports.html", response_class=HTMLResponse)
async def get_admin_reports_page(
    request: Request,
    current_user: Optional[models.User] = Depends(get_optional_current_user)
):
    return templates.TemplateResponse(
        "admin_reports.html",
        {"request": request, "current_user": current_user},
    ) 