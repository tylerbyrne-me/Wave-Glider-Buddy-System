from fastapi import APIRouter, Depends, HTTPException, status, Request, Body
from fastapi.responses import HTMLResponse
from typing import List, Optional, Tuple
from datetime import datetime, timedelta, timezone
from sqlmodel import select
from ..core import models
from ..core.db import get_db_session, SQLModelSession
from ..core.auth import get_current_active_user, get_optional_current_user
from ..config import settings
import json
import logging
from pathlib import Path
from ..forms.form_definitions import get_static_form_schema
from app.core.templates import templates
from ..core.template_context import get_template_context

router = APIRouter(tags=["Forms"])
logger = logging.getLogger(__name__)

# --- In-memory/local storage helpers (if using local_json mode) ---
DATA_STORE_DIR = Path(__file__).resolve().parent.parent.parent / "data_store"
LOCAL_FORMS_DB_FILE = DATA_STORE_DIR / "submitted_forms.json"
mission_forms_db: dict = {}

def _save_forms_to_local_json():
    if settings.forms_storage_mode == "local_json":
        DATA_STORE_DIR.mkdir(parents=True, exist_ok=True)
        serializable_db = {
            json.dumps(list(k)): v.model_dump(mode="json")
            for k, v in mission_forms_db.items()
        }
        try:
            with open(LOCAL_FORMS_DB_FILE, "w") as f:
                json.dump(serializable_db, f, indent=4)
            logger.info(f"Forms database saved to {LOCAL_FORMS_DB_FILE}")
        except IOError as e:
            logger.error(f"Error saving forms database to {LOCAL_FORMS_DB_FILE}: {e}")
        except TypeError as e:
            logger.error(f"TypeError saving forms database (serialization issue): {e}")
    elif settings.forms_storage_mode == "sqlite":
        logger.debug("Forms storage mode is 'sqlite'. JSON save skipped.")
    else:
        logger.warning(f"Unknown forms_storage_mode: {settings.forms_storage_mode}. Forms not saved to JSON.")

# --- API Endpoints ---
@router.get("/api/forms/all", response_model=List[models.SubmittedForm])
async def get_all_submitted_forms(
    session: SQLModelSession = Depends(get_db_session),
    current_user: models.User = Depends(get_current_active_user),
):
    statement = select(models.SubmittedForm)
    if current_user.role == models.UserRoleEnum.pilot:
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=72)
        statement = statement.where(
            models.SubmittedForm.submission_timestamp > cutoff_time
        )
    statement = statement.order_by(models.SubmittedForm.submission_timestamp.desc())
    forms = session.exec(statement).all()
    return forms

@router.get("/api/forms/id/{form_db_id}", response_model=models.SubmittedForm)
async def get_submitted_form_by_id(
    form_db_id: int,
    session: SQLModelSession = Depends(get_db_session),
    current_user: models.User = Depends(get_current_active_user)
):
    db_form = session.get(models.SubmittedForm, form_db_id)
    if not db_form:
        raise HTTPException(status_code=404, detail="Form not found")
    return db_form

@router.get("/api/forms/pic_handoffs/my", response_model=List[models.SubmittedForm])
async def get_my_pic_handoff_submissions(
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session)
):
    statement = select(models.SubmittedForm).where(
        models.SubmittedForm.form_type == "pic_handoff_checklist",
        models.SubmittedForm.submitted_by_username == current_user.username
    ).order_by(models.SubmittedForm.submission_timestamp.desc())
    forms = session.exec(statement).all()
    return forms

@router.get("/api/forms/pic_handoffs/recent", response_model=List[models.SubmittedForm])
async def get_recent_pic_handoff_submissions(
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session)
):
    twenty_four_hours_ago = datetime.now(timezone.utc) - timedelta(hours=24)
    statement = select(models.SubmittedForm).where(
        models.SubmittedForm.form_type == "pic_handoff_checklist",
        models.SubmittedForm.submission_timestamp >= twenty_four_hours_ago
    ).order_by(models.SubmittedForm.submission_timestamp.desc())
    forms = session.exec(statement).all()
    return forms

@router.get("/api/forms/{mission_id}/template/{form_type}")
async def get_form_template(mission_id: str, form_type: str):
    try:
        schema_obj = get_static_form_schema(form_type)
        if not schema_obj:
            raise HTTPException(status_code=404, detail="Form template not found")

        # Convert Pydantic model to dict for mutation and .get() access
        schema = schema_obj.model_dump(mode="python")

        from app.core.data_service import get_data_service
        from app.core import summaries

        data_service = get_data_service()
        df_power, _, _ = await data_service.load("power", mission_id, current_user=None)
        power_info = summaries.get_power_status(df_power, None) if df_power is not None else {}
        battery_wh = power_info.get("values", {}).get("BatteryWattHours", "N/A")
        battery_pct = power_info.get("values", {}).get("BatteryPercentage", "N/A")

        # Use schema IDs for autofill
        autofill_map = {
            "glider_id_val": lambda: mission_id,
            "current_battery_wh_val": lambda: battery_wh,
            "percent_battery_val": lambda: battery_pct,
        }

        for section in schema.get("sections", []):
            for item in section.get("items", []):
                if item.get("item_type") == "autofilled_value":
                    autofill_func = autofill_map.get(item.get("id"))
                    if autofill_func:
                        item["value"] = autofill_func()

        return schema
    except Exception as e:
        import logging
        logging.exception("Error in get_form_template")
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")

@router.post("/api/forms/{mission_id}")
async def submit_form(
    mission_id: str,
    form_data: dict = Body(...),
    session=Depends(get_db_session),
    current_user: models.User = Depends(get_current_active_user)
):
    """
    Accepts a submitted form for a mission and saves it to the SQL database.
    Assumes form_data matches the structure of models.SubmittedForm (or can be adapted).
    """
    try:
        # Build the SubmittedForm object
        submitted_form = models.SubmittedForm(
            mission_id=mission_id,
            form_type=form_data.get("form_type"),
            form_title=form_data.get("form_title"),
            submitted_by_username=current_user.username,
            submission_timestamp=datetime.now(timezone.utc),
            sections_data=form_data.get("sections_data"),
        )
        session.add(submitted_form)
        session.commit()
        session.refresh(submitted_form)
        return {
            "message": "Form submitted successfully",
            "mission_id": mission_id,
            "submitted_by_username": current_user.username,
            "submission_timestamp": submitted_form.submission_timestamp.isoformat()
        }
    except Exception as e:
        import logging
        logging.exception("Error saving submitted form")
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=f"Failed to save form: {e}")

# --- HTML Endpoints ---
@router.get("/view_forms.html", response_class=HTMLResponse)
async def get_view_forms_page(
    request: Request,
    current_user: Optional[models.User] = Depends(get_optional_current_user),
):
    username_for_log = (
        current_user.username if current_user else "anonymous/unauthenticated"
    )
    user_role_for_log = current_user.role.value if current_user else "N/A"
    logger.info(
        f"User '{username_for_log}' (role: {user_role_for_log}) accessing /view_forms.html."
    )
    return templates.TemplateResponse(
        "view_forms.html",
        get_template_context(request=request, current_user=current_user),
    )

@router.get("/my_pic_handoffs.html", response_class=HTMLResponse)
async def get_my_pic_handoffs_page(
    request: Request,
    current_user: Optional[models.User] = Depends(get_optional_current_user)
):
    logger.info(f"User '{current_user.username if current_user else 'anonymous'}' accessing /my_pic_handoffs.html.")
    return templates.TemplateResponse(
        "my_pic_handoffs.html",
        get_template_context(request=request, current_user=current_user),
    )

@router.get("/view_pic_handoffs.html", response_class=HTMLResponse)
async def get_view_pic_handoffs_page(
    request: Request,
    current_user: Optional[models.User] = Depends(get_optional_current_user)
):
    logger.info(f"User '{current_user.username if current_user else 'anonymous'}' accessing /view_pic_handoffs.html.")
    return templates.TemplateResponse(
        "view_pic_handoffs.html",
        get_template_context(request=request, current_user=current_user),
    ) 