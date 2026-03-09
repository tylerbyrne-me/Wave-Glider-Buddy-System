from fastapi import APIRouter, Depends, HTTPException, Request, Body
from fastapi.responses import HTMLResponse
from typing import List, Optional
from datetime import datetime, timedelta, timezone
from sqlmodel import select, or_
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

# Item IDs excluded from "changes since last PIC" highlighting (expected to change over time)
PIC_HANDOFF_EXCLUDED_CHANGE_IDS = {
    "current_mos_val",
    "current_pic_val",
    "last_pic_val",
    "current_battery_wh_val",
    "percent_battery_val",
    "tracker_battery_v_val",
    "tracker_last_update_val",
}

# Only compare these items: they are the ones the form template fills with current live data.
# User-filled fields (e.g. Light Status, Mission Status) are not compared, so they are never highlighted.
PIC_HANDOFF_COMPARABLE_ITEM_IDS = {
    "glider_id_val",
    "mission_title_val",
    "total_battery_val",
    "boats_in_area_val",
    "vessel_standoff_m_val",
    "recent_errors_val",
}


def _normalize_submitted_value(item: dict) -> str:
    """Normalize a submitted form item to a comparable string."""
    sub_val = item.get("value")
    sub_checked = item.get("is_checked")
    if sub_val is not None and str(sub_val).strip() != "":
        return str(sub_val).strip()
    if sub_checked is not None:
        return "true" if sub_checked else "false"
    return ""


def _current_value_from_template_item(item: dict) -> str:
    """Extract a comparable string from a template form item."""
    item_type = item.get("item_type") or ""
    val = item.get("value")
    if item_type == "sensor_status" and isinstance(val, str) and val.strip():
        try:
            parsed = json.loads(val)
            return str(parsed.get("value", "")).strip()
        except (json.JSONDecodeError, TypeError):
            pass
    if item_type == "checkbox":
        checked = item.get("is_checked")
        return "true" if checked else "false"
    if val is None:
        return ""
    return str(val).strip()


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


@router.get("/api/forms/id/{form_db_id}/with-changes")
async def get_submitted_form_with_changes(
    form_db_id: int,
    session: SQLModelSession = Depends(get_db_session),
    current_user: models.User = Depends(get_current_active_user),
):
    """Return the form and which item IDs have changed since submission. changed_item_ids is non-empty only when this form is the most recent PIC handoff for its mission."""
    db_form = session.get(models.SubmittedForm, form_db_id)
    if not db_form:
        raise HTTPException(status_code=404, detail="Form not found")
    if db_form.form_type != "pic_handoff_checklist":
        return {"form": db_form, "changed_item_ids": []}

    latest = session.exec(
        select(models.SubmittedForm)
        .where(
            models.SubmittedForm.form_type == "pic_handoff_checklist",
            models.SubmittedForm.mission_id == db_form.mission_id,
        )
        .order_by(models.SubmittedForm.submission_timestamp.desc())
        .limit(1)
    ).first()
    if not latest or latest.id != db_form.id:
        return {"form": db_form, "changed_item_ids": []}

    template = await get_form_template(
        db_form.mission_id, "pic_handoff_checklist", session, current_user
    )
    current_values: dict = {}
    for section in template.get("sections") or []:
        for item in section.get("items") or []:
            iid = item.get("id")
            if not iid:
                continue
            current_values[iid] = _current_value_from_template_item(item)

    changed_item_ids: List[str] = []
    for section in db_form.sections_data or []:
        for item in section.get("items") or []:
            iid = item.get("id")
            if not iid or iid in PIC_HANDOFF_EXCLUDED_CHANGE_IDS:
                continue
            # Only compare items that the template populates with current data (live AIS, errors, mission title, sensors, etc.).
            # User-filled fields (Light Status, Mission Status, etc.) are not in this set, so they are never highlighted.
            if iid not in PIC_HANDOFF_COMPARABLE_ITEM_IDS and not (
                iid.startswith("sensor_") and iid.endswith("_status")
            ):
                continue
            submitted_str = _normalize_submitted_value(item)
            current_str = current_values.get(iid, "")
            if submitted_str != current_str:
                changed_item_ids.append(iid)

    return {"form": db_form, "changed_item_ids": changed_item_ids}


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


@router.get("/api/forms/pic_handoffs/mission/{mission_id}", response_model=List[models.SubmittedForm])
async def get_pic_handoff_submissions_for_mission(
    mission_id: str,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    statement = (
        select(models.SubmittedForm)
        .where(
            models.SubmittedForm.form_type == "pic_handoff_checklist",
            models.SubmittedForm.mission_id == mission_id,
        )
        .order_by(models.SubmittedForm.submission_timestamp.desc())
    )
    forms = session.exec(statement).all()
    return forms

@router.get("/api/forms/{mission_id}/template/{form_type}")
async def get_form_template(
    mission_id: str,
    form_type: str,
    session: SQLModelSession = Depends(get_db_session),
    current_user: Optional[models.User] = Depends(get_optional_current_user),
):
    try:
        schema_obj = get_static_form_schema(form_type)
        if not schema_obj:
            raise HTTPException(status_code=404, detail="Form template not found")

        # Convert Pydantic model to dict for mutation and .get() access
        schema = schema_obj.model_dump(mode="python")

        from app.core.data_service import get_data_service
        from app.core import summaries

        # Resolve mission overview (support compound ids like "1070-m216" -> try "m216" if not found)
        mission_overview = session.get(models.MissionOverview, mission_id)
        if mission_overview is None and "-" in mission_id:
            mission_base = mission_id.split("-")[-1]
            mission_overview = session.get(models.MissionOverview, mission_base)
        battery_apu = getattr(mission_overview, "battery_apu_count", None) if mission_overview else None
        theoretical_max_wh = summaries.theoretical_max_wh(battery_apu)

        # Load power so battery values match dashboard (try local then remote if no data)
        data_service = get_data_service()
        df_power, _, _ = await data_service.load(
            "power", mission_id, current_user=current_user, source_preference="local"
        )
        if df_power is None or df_power.empty:
            df_power, _, _ = await data_service.load(
                "power", mission_id, current_user=current_user, source_preference="remote"
            )
        power_info = (
            summaries.get_power_status(df_power, None, theoretical_max_wh=theoretical_max_wh)
            if df_power is not None and not df_power.empty
            else {}
        )
        values = power_info.get("values", {})
        battery_wh = values.get("BatteryWattHours", "N/A")
        battery_pct = values.get("BatteryPercentage", "N/A")
        theoretical_wh = values.get("TheoreticalMaxBatteryWh")
        realistic_wh = values.get("RealisticMaxBatteryWh")
        effective_wh = values.get("EffectiveMaxBatteryWh")

        # Total Battery Capacity: show both theoretical and observed (match dashboard)
        if theoretical_wh is not None:
            total_capacity_display = f"Max (theoretical): {int(theoretical_wh)} Wh"
            if realistic_wh is not None:
                total_capacity_display += f". Observed max: {int(realistic_wh)} Wh"
        else:
            total_capacity_display = "2775 Wh"
            if realistic_wh is not None:
                total_capacity_display += f". Observed max: {int(realistic_wh)} Wh"

        # Hint for % Battery Remaining: explain which max was used
        if effective_wh is not None:
            if realistic_wh is not None and effective_wh == realistic_wh:
                percent_battery_hint = (
                    f"% Battery Remaining is calculated using the observed max ({int(realistic_wh)} Wh) for this mission."
                )
            else:
                percent_battery_hint = (
                    f"% Battery Remaining is calculated using the theoretical max ({int(effective_wh)} Wh)."
                )
        else:
            percent_battery_hint = (
                "% Battery Remaining is calculated using the theoretical max when set, otherwise the legacy default."
            )

        # Mission title from Sensor Tracker deployment
        mission_base = mission_id.split("-")[-1] if "-" in mission_id else mission_id
        st_deployment = session.exec(
            select(models.SensorTrackerDeployment).where(
                or_(
                    models.SensorTrackerDeployment.mission_id == mission_id,
                    models.SensorTrackerDeployment.mission_id == mission_base,
                )
            )
        ).first()
        mission_title = (st_deployment.title or "Mission Not Assigned") if st_deployment else "Mission Not Assigned"

        # Boats in the Area: AIS summary (8h) - time seen, time since contact, MMSI
        df_ais, _, _ = await data_service.load("ais", mission_id, current_user=current_user, source_preference="local")
        if df_ais is None or df_ais.empty:
            df_ais, _, _ = await data_service.load("ais", mission_id, current_user=current_user, source_preference="remote")
        ais_vessels = summaries.get_ais_summary(df_ais, max_age_hours=8) if df_ais is not None and not df_ais.empty else []
        if ais_vessels:
            boats_lines = []
            for v in ais_vessels:
                ts = v.get("LastSeenTimestamp")
                if ts is not None and hasattr(ts, "strftime"):
                    time_str = ts.strftime("%Y-%m-%d %H:%M UTC")
                else:
                    time_str = str(ts) if ts else "—"
                since = summaries.time_ago(ts)
                mmsi = v.get("MMSI", "—")
                boats_lines.append(f"{time_str} | {since} | MMSI {mmsi}")
            boats_in_area_display = "\n".join(boats_lines)
        else:
            boats_in_area_display = "No recent AIS contacts."

        # Vessel standoff (m) from mission overview - persists until user changes
        vessel_standoff = getattr(mission_overview, "vessel_standoff_m", None) if mission_overview else None
        vessel_standoff_display = str(vessel_standoff) if vessel_standoff is not None else ""

        # Recent Errors (8h): time, time since, category, self-corrected
        df_errors, _, _ = await data_service.load("errors", mission_id, current_user=current_user, source_preference="local")
        if df_errors is None or df_errors.empty:
            df_errors, _, _ = await data_service.load("errors", mission_id, current_user=current_user, source_preference="remote")
        recent_errors_raw = (
            summaries.get_recent_errors(df_errors, max_age_hours=8)
            if df_errors is not None and not df_errors.empty
            else []
        )
        from app.services.error_classification_service import classify_error_message
        errors_lines = []
        for err in recent_errors_raw:
            ts = err.get("Timestamp")
            if ts is not None and hasattr(ts, "strftime"):
                time_str = ts.strftime("%Y-%m-%d %H:%M UTC")
            else:
                time_str = str(ts) if ts else "—"
            since = summaries.time_ago(ts) if ts else "—"
            category = "unknown"
            if err.get("ErrorMessage"):
                cat_val, _, _ = classify_error_message(err["ErrorMessage"])
                category = cat_val.value
            self_corr = err.get("SelfCorrected")
            sc_str = "Yes" if self_corr in (True, "true", "True", "yes", 1) else "No" if self_corr is not None else "—"
            errors_lines.append(f"{time_str} | {since} | {category} | Self-corrected: {sc_str}")
        recent_errors_display = "\n".join(errors_lines) if errors_lines else "No recent errors."

        # Science sensor status rows: only for sensors in Enabled Sensor Cards
        science_sensors = ["ctd", "weather", "waves", "vr2c", "fluorometer", "wg_vm4"]
        sensor_labels = {
            "ctd": "CTD",
            "weather": "Weather",
            "waves": "Waves",
            "vr2c": "VR2C",
            "fluorometer": "Fluorometer",
            "wg_vm4": "WG-VM4",
        }
        status_functions = {
            "ctd": summaries.get_ctd_status,
            "weather": summaries.get_weather_status,
            "waves": summaries.get_wave_status,
            "vr2c": summaries.get_vr2c_status,
            "fluorometer": summaries.get_fluorometer_status,
            "wg_vm4": summaries.get_wg_vm4_status,
        }
        enabled_cards = []
        if mission_overview and mission_overview.enabled_sensor_cards:
            try:
                enabled_cards = json.loads(mission_overview.enabled_sensor_cards)
            except (json.JSONDecodeError, TypeError):
                enabled_cards = []
        now_utc = datetime.now(timezone.utc)
        sensor_items_to_inject = []
        for card in science_sensors:
            if card not in enabled_cards:
                continue
            report_type = card
            df_sensor, _, _ = await data_service.load(
                report_type, mission_id, current_user=current_user, source_preference="local"
            )
            if df_sensor is None or df_sensor.empty:
                df_sensor, _, _ = await data_service.load(
                    report_type, mission_id, current_user=current_user, source_preference="remote"
                )
            status_fn = status_functions.get(card)
            status = (
                status_fn(df_sensor, None)
                if status_fn and df_sensor is not None and not df_sensor.empty
                else {}
            )
            latest_timestamp_str = status.get("latest_timestamp_str") or "N/A"
            last_ts = None
            if df_sensor is not None and not df_sensor.empty and "Timestamp" in df_sensor.columns:
                last_ts = df_sensor["Timestamp"].max()
                if hasattr(last_ts, "to_pydatetime"):
                    last_ts = last_ts.to_pydatetime()
                if last_ts is not None and (last_ts.tzinfo is None or last_ts.tzinfo.utcoffset(last_ts) is None):
                    last_ts = last_ts.replace(tzinfo=timezone.utc)
            default_on = (
                (now_utc - last_ts).total_seconds() < 3600
                if last_ts is not None
                else False
            )
            item_id = f"sensor_{card}_status"
            value_dict = {
                "last_time_str": latest_timestamp_str,
                "value": "On" if default_on else "Off",
            }
            sensor_items_to_inject.append({
                "id": item_id,
                "label": sensor_labels.get(card, card.upper()),
                "item_type": models.FormItemTypeEnum.SENSOR_STATUS.value,
                "value": json.dumps(value_dict),
            })

        # Use schema IDs for autofill (including static_text for Total Battery Capacity)
        autofill_map = {
            "glider_id_val": lambda: mission_id,
            "current_battery_wh_val": lambda: battery_wh,
            "percent_battery_val": lambda: battery_pct,
            "total_battery_val": lambda: total_capacity_display,
        }

        for section in schema.get("sections", []):
            for item in section.get("items", []):
                item_id = item.get("id")
                if item_id == "total_battery_val":
                    item["value"] = total_capacity_display
                if item_id == "mission_title_val":
                    item["value"] = mission_title
                if item_id == "boats_in_area_val":
                    item["value"] = boats_in_area_display
                if item_id == "vessel_standoff_m_val":
                    item["value"] = vessel_standoff_display
                if item_id == "recent_errors_val":
                    item["value"] = recent_errors_display
                if item.get("item_type") == "autofilled_value":
                    autofill_func = autofill_map.get(item_id)
                    if autofill_func:
                        item["value"] = autofill_func()
                    if item_id == "percent_battery_val":
                        item["hint"] = percent_battery_hint

        # Inject science sensor status rows after recent_errors_val in general_status
        # When WG-VM4 is enabled, also inject Current Station, Offload Status, Next Station
        wg_vm4_form_items = []
        if "wg_vm4" in enabled_cards:
            wg_vm4_form_items = [
                {
                    "id": "wg_vm4_current_station_val",
                    "label": "Current Station",
                    "item_type": models.FormItemTypeEnum.TEXT_INPUT.value,
                    "value": "N/A",
                    "placeholder": "e.g. HFX031",
                },
                {
                    "id": "wg_vm4_offload_status_val",
                    "label": "Offload Status",
                    "item_type": models.FormItemTypeEnum.DROPDOWN.value,
                    "options": [
                        "N/A",
                        "Connecting to Station",
                        "Connected to Station",
                        "Offloading Station",
                        "Aborting Offload",
                    ],
                    "value": "N/A",
                },
                {
                    "id": "wg_vm4_next_station_val",
                    "label": "Next Station",
                    "item_type": models.FormItemTypeEnum.TEXT_INPUT.value,
                    "value": "N/A",
                    "placeholder": "e.g. HFX032",
                },
            ]

        # Sensor sampling rates (editable, persist until changed). Only for sensors with configurable rates; exclude WG-VM4.
        sampling_sensor_keys = ["ctd", "fluorometer", "waves", "weather", "vr2c"]
        item_id_by_key = {
            "ctd": "sensor_ctd_sampling_val",
            "fluorometer": "sensor_fluorometer_sampling_val",
            "waves": "sensor_waves_sampling_val",
            "weather": "sensor_weather_sampling_val",
            "vr2c": "sensor_vr2c_sampling_val",
        }
        rates_json = None
        if mission_overview and mission_overview.sensor_sampling_rates:
            try:
                rates_json = json.loads(mission_overview.sensor_sampling_rates)
            except (json.JSONDecodeError, TypeError):
                rates_json = {}
        # Storage key for display (fluorometer form row uses "c3" in JSON)
        sampling_storage_key = {"fluorometer": "c3"}
        # Keyed by sensor card for insertion under respective sensor status row
        sampling_item_by_key = {}
        for sk in sampling_sensor_keys:
            if sk not in enabled_cards:
                continue
            cfg = SENSOR_SAMPLING_CONFIG.get(sk)
            if not cfg:
                continue
            iid = item_id_by_key.get(sk)
            if not iid:
                continue
            storage_key = sampling_storage_key.get(sk, sk)
            display_val = _format_sensor_sampling_display(rates_json, storage_key)
            sampling_item_by_key[sk] = {
                "id": iid,
                "label": cfg["label"],
                "item_type": models.FormItemTypeEnum.TEXT_INPUT.value,
                "value": display_val,
                "placeholder": cfg.get("placeholder", ""),
                "hint": cfg.get("hint"),
            }

        if sensor_items_to_inject or wg_vm4_form_items or sampling_item_by_key:
            for section in schema.get("sections", []):
                if section.get("id") != "general_status":
                    continue
                items = section.get("items") or []
                insert_idx = None
                for i, it in enumerate(items):
                    if it.get("id") == "recent_errors_val":
                        insert_idx = i + 1
                        break
                if insert_idx is not None:
                    # Insert sensor status rows (with sampling where applicable). WG-VM4 is placed
                    # just above Current Station / Offload Status / Next Station so all VM4 fields stay together.
                    sensor_without_vm4 = [s for s in sensor_items_to_inject if s["id"] != "sensor_wg_vm4_status"]
                    wg_vm4_status_item = next((s for s in sensor_items_to_inject if s["id"] == "sensor_wg_vm4_status"), None)
                    for sensor_item in reversed(sensor_without_vm4):
                        items.insert(insert_idx, sensor_item)
                        insert_idx += 1
                        card = sensor_item["id"].replace("sensor_", "").replace("_status", "")
                        sampling_item = sampling_item_by_key.get(card)
                        if sampling_item:
                            items.insert(insert_idx, sampling_item)
                            insert_idx += 1
                    if wg_vm4_status_item:
                        items.insert(insert_idx, wg_vm4_status_item)
                        insert_idx += 1
                    for wg_item in wg_vm4_form_items:
                        items.insert(insert_idx, wg_item)
                        insert_idx += 1
                break

        return schema
    except Exception as e:
        logger.exception("Error in get_form_template")
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")

def _parse_vessel_standoff_from_sections(sections_data: Optional[List[dict]]) -> Optional[int]:
    """Extract vessel_standoff_m_val from submitted form sections_data."""
    if not sections_data:
        return None
    for section in sections_data:
        for item in (section.get("items") or []):
            if item.get("id") == "vessel_standoff_m_val" and item.get("value") not in (None, ""):
                try:
                    return int(str(item["value"]).strip())
                except (ValueError, TypeError):
                    pass
    return None


# Sensor sampling rate form item IDs and storage keys (WG-VM4 has no user-configurable rates)
# "hint" is shown as a hover tooltip on the input.
SENSOR_SAMPLING_CONFIG = {
    "ctd": {
        "label": "CTD Sample Rate",
        "hint": "period (sec), samples/block, flush (sec), off (sec). Period cannot exceed 14 sec if O2 sensor installed.",
        "placeholder": "e.g. 10, 10, 100, 400",
        "default": "10, 10, 100, 400",
    },
    "c3": {
        "label": "Fluorometer Sample Rate",
        "hint": "UsePump (true/false), Flush (sec), AvgPeriod/Block (sec), OffTime (sec).",
        "placeholder": "e.g. True, 100, 100, 400",
        "default": "False, 45, 30, 0",
    },
    "fluorometer": {
        "label": "Fluorometer Sample Rate",
        "hint": "UsePump (true/false), Flush (sec), AvgPeriod/Block (sec), OffTime (sec).",
        "placeholder": "e.g. True, 100, 100, 400",
        "default": "False, 45, 30, 0",
    },
    "waves": {
        "label": "Waves Interval",
        "hint": "Collection interval in minutes (default 30).",
        "placeholder": "e.g. 30",
        "default": "30",
    },
    "weather": {
        "label": "Weather Interval",
        "hint": "Collection period in minutes (default 10).",
        "placeholder": "e.g. 10",
        "default": "10",
    },
    "vr2c": {
        "label": "VR2C Status Interval",
        "hint": "Status output interval in minutes (default 60).",
        "placeholder": "e.g. 60",
        "default": "60",
    },
}
# Form item id suffix -> storage key (c3 = fluorometer)
SENSOR_SAMPLING_ITEM_ID_TO_KEY = {
    "sensor_ctd_sampling_val": "ctd",
    "sensor_fluorometer_sampling_val": "c3",
    "sensor_waves_sampling_val": "waves",
    "sensor_weather_sampling_val": "weather",
    "sensor_vr2c_sampling_val": "vr2c",
}


def _format_sensor_sampling_display(rates: Optional[dict], sensor_key: str) -> str:
    """Format stored JSON for a sensor into the form display string."""
    if not rates or sensor_key not in rates:
        return SENSOR_SAMPLING_CONFIG.get(sensor_key, {}).get("default", "")
    d = rates[sensor_key]
    if not isinstance(d, dict):
        return str(d) if d is not None else ""
    if sensor_key == "ctd":
        return ", ".join(
            str(d.get(k, ""))
            for k in ("period_sec", "samples_per_block", "flush_time_sec", "off_time_sec")
        )
    if sensor_key == "c3":
        use_pump = d.get("use_pump", False)
        return ", ".join(
            [str(use_pump).lower()]
            + [str(d.get(k, "")) for k in ("flush_sec", "avg_period_block_sec", "off_time_sec")]
        )
    if sensor_key in ("waves", "weather", "vr2c"):
        return str(d.get("interval_min", ""))
    return ""


def _parse_sensor_sampling_value(sensor_key: str, value: str) -> Optional[dict]:
    """Parse one sensor's form value string into a dict for JSON storage."""
    value = (value or "").strip()
    if not value:
        return None
    parts = [p.strip() for p in value.split(",")]
    try:
        if sensor_key == "ctd":
            if len(parts) < 4:
                return None
            return {
                "period_sec": int(parts[0]),
                "samples_per_block": int(parts[1]),
                "flush_time_sec": int(parts[2]),
                "off_time_sec": int(parts[3]),
            }
        if sensor_key == "c3":
            if len(parts) < 4:
                return None
            use_pump = str(parts[0]).lower() in ("true", "1", "yes")
            return {
                "use_pump": use_pump,
                "flush_sec": int(parts[1]),
                "avg_period_block_sec": int(parts[2]),
                "off_time_sec": int(parts[3]),
            }
        if sensor_key in ("waves", "weather", "vr2c"):
            if not parts:
                return None
            return {"interval_min": int(parts[0])}
    except (ValueError, TypeError):
        return None
    return None


def _parse_sensor_sampling_from_sections(sections_data: Optional[List[dict]]) -> Optional[dict]:
    """Extract sensor sampling rates from form sections_data. Returns dict keyed by sensor for JSON storage."""
    if not sections_data:
        return None
    collected = {}
    for section in sections_data:
        for item in (section.get("items") or []):
            iid = item.get("id")
            key = SENSOR_SAMPLING_ITEM_ID_TO_KEY.get(iid)
            if not key:
                continue
            val = item.get("value")
            parsed = _parse_sensor_sampling_value(key, str(val) if val is not None else "")
            if parsed is not None:
                collected[key] = parsed
    return collected if collected else None


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
    Persists vessel_standoff_m to MissionOverview when present in PIC handoff form.
    """
    try:
        sections_data = form_data.get("sections_data")

        # Build the SubmittedForm object
        submitted_form = models.SubmittedForm(
            mission_id=mission_id,
            form_type=form_data.get("form_type"),
            form_title=form_data.get("form_title"),
            submitted_by_username=current_user.username,
            submission_timestamp=datetime.now(timezone.utc),
            sections_data=sections_data,
        )
        session.add(submitted_form)

        # Persist vessel standoff (m) and sensor sampling rates to mission overview when present in form
        mission_overview = session.get(models.MissionOverview, mission_id)
        if mission_overview is None and "-" in mission_id:
            mission_overview = session.get(models.MissionOverview, mission_id.split("-")[-1])
        if mission_overview is not None:
            updated = False
            standoff_m = _parse_vessel_standoff_from_sections(sections_data)
            if standoff_m is not None and standoff_m >= 0:
                mission_overview.vessel_standoff_m = standoff_m
                updated = True
            sampling_rates = _parse_sensor_sampling_from_sections(sections_data)
            if sampling_rates is not None:
                mission_overview.sensor_sampling_rates = json.dumps(sampling_rates)
                updated = True
            if updated:
                mission_overview.updated_at_utc = datetime.now(timezone.utc)
                session.add(mission_overview)

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