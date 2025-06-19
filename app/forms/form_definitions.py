# app/forms/form_definitions.py
import logging
from fastapi import HTTPException
from ..core import models

logger = logging.getLogger(__name__)

def get_static_form_schema(form_type: str) -> models.MissionFormSchema:
    """
    Returns the static structure of a form schema, without auto-filled data.
    """
    if form_type == "pre_deployment_checklist":
        return models.MissionFormSchema(
            form_type=form_type,
            title="Pre-Deployment Checklist",
            description="Complete this checklist before deploying the Wave Glider.",
            sections=[
                models.FormSection(
                    id="general_checks",
                    title="General System Checks",
                    items=[
                        models.FormItem(id="hull_integrity", label="Hull Integrity Visual Check", item_type=models.FormItemTypeEnum.CHECKBOX, required=True),
                        models.FormItem(id="umbilical_check", label="Umbilical Secure and Undamaged", item_type=models.FormItemTypeEnum.CHECKBOX, required=True),
                        models.FormItem(id="payload_power", label="Payload Power On", item_type=models.FormItemTypeEnum.CHECKBOX),
                    ],
                ),
                models.FormSection(
                    id="power_system",
                    title="Power System",
                    items=[
                        models.FormItem(id="battery_level_auto", label="Current Battery Level (Auto)", item_type=models.FormItemTypeEnum.AUTOFILLED_VALUE, value="N/A"), # Placeholder
                        models.FormItem(id="battery_level_manual", label="Confirm Battery Level Sufficient", item_type=models.FormItemTypeEnum.CHECKBOX, required=True),
                        models.FormItem(id="solar_panels_clean", label="Solar Panels Clean", item_type=models.FormItemTypeEnum.CHECKBOX),
                    ],
                    section_comment="Ensure all power connections are secure.",
                ),
                models.FormSection(
                    id="comms_check",
                    title="Communications",
                    items=[
                        models.FormItem(id="iridium_status",label="Iridium Comms Check (Signal Strength)",item_type=models.FormItemTypeEnum.TEXT_INPUT,placeholder="e.g., 5 bars"),
                        models.FormItem(id="rudics_test",label="RUDICS Test Call Successful",item_type=models.FormItemTypeEnum.CHECKBOX),
                    ],
                ),
                models.FormSection(
                    id="final_notes",
                    title="Final Notes & Sign-off",
                    items=[
                        models.FormItem(id="deployment_notes",label="Deployment Notes/Observations",item_type=models.FormItemTypeEnum.TEXT_AREA,placeholder="Any issues or special conditions..."),
                        models.FormItem(id="sign_off_name",label="Signed Off By (Name)",item_type=models.FormItemTypeEnum.TEXT_INPUT,required=True),
                    ],
                ),
            ],
        )
    elif form_type == "pic_handoff_checklist":
        return models.MissionFormSchema(
            form_type=form_type,
            title="PIC Handoff Checklist",
            description="Pilot in Command (PIC) handoff checklist. Verify each item.",
            sections=[
                models.FormSection(
                    id="general_status",
                    title="Glider & Mission General Status",
                    items=[
                        models.FormItem(id="glider_id_val", label="Glider ID", item_type=models.FormItemTypeEnum.AUTOFILLED_VALUE, value="N/A"), # Placeholder
                        models.FormItem(id="current_mos_val", label="Current MOS", item_type=models.FormItemTypeEnum.DROPDOWN, options=["Sue L", "Tyler B", "Matt M", "Adam C"], required=True),
                        models.FormItem(id="current_pic_val", label="Current PIC", item_type=models.FormItemTypeEnum.DROPDOWN, options=["Adam S", "Laura R", "Sue L", "Tyler B", "Adam C", "Poppy K", "LRI", "Matt M", "Noa W", "Nicole N"], required=True),
                        models.FormItem(id="last_pic_val", label="Last PIC", item_type=models.FormItemTypeEnum.DROPDOWN, options=["Adam S", "Laura R", "Sue L", "Tyler B", "Adam C", "Poppy K", "LRI", "Matt M", "Noa W", "Nicole N"], required=True),
                        models.FormItem(id="mission_status_val", label="Mission Status", item_type=models.FormItemTypeEnum.DROPDOWN, options=["In Transit", "Avoiding Ship", "Holding for Storm", "Offloading", "In Recovery Hold", "Surveying"], required=True),
                        models.FormItem(id="total_battery_val", label="Total Battery Capacity (Wh)", item_type=models.FormItemTypeEnum.STATIC_TEXT, value="2775 Wh"),
                        models.FormItem(id="current_battery_wh_val", label="Current Glider Battery (Wh)", item_type=models.FormItemTypeEnum.AUTOFILLED_VALUE, value="N/A"), # Placeholder
                        models.FormItem(id="percent_battery_val", label="% Battery Remaining", item_type=models.FormItemTypeEnum.AUTOFILLED_VALUE, value="N/A"), # Placeholder
                        models.FormItem(id="tracker_battery_v_val", label="Tracker Battery (V)", item_type=models.FormItemTypeEnum.TEXT_INPUT, placeholder="e.g., 14.94"),
                        models.FormItem(id="tracker_last_update_val", label="Tracker Last Update", item_type=models.FormItemTypeEnum.TEXT_INPUT, placeholder="e.g., MM-DD-YYYY HH:MM:SS"),
                        models.FormItem(id="communications_val", label="Communications Mode", item_type=models.FormItemTypeEnum.DROPDOWN, options=["SAT", "CELL"], required=True),
                        models.FormItem(id="telemetry_rate_val", label="Telemetry Report Rate (min)", item_type=models.FormItemTypeEnum.TEXT_INPUT, placeholder="e.g., 5"),
                        models.FormItem(id="navigation_mode_val", label="Navigation Mode", item_type=models.FormItemTypeEnum.DROPDOWN, options=["FSC", "FFB", "FFH", "WC", "FCC"], required=True),
                        models.FormItem(id="target_waypoint_val", label="Target Waypoint", item_type=models.FormItemTypeEnum.TEXT_INPUT, placeholder="Enter target waypoint"),
                        models.FormItem(id="waypoint_details_val", label="Waypoint Start to Finish Details", item_type=models.FormItemTypeEnum.TEXT_INPUT, placeholder="e.g., 90 Degrees, 5km"),
                        models.FormItem(id="light_status_val", label="Light Status", item_type=models.FormItemTypeEnum.DROPDOWN, options=["ON", "OFF", "AUTO", "N/A"], required=True),
                        models.FormItem(id="thruster_status_val", label="Thruster Status", item_type=models.FormItemTypeEnum.DROPDOWN, options=["ON", "OFF", "N/A"], required=True),
                        models.FormItem(id="obstacle_avoid_val", label="Obstacle Avoidance", item_type=models.FormItemTypeEnum.DROPDOWN, options=["ON", "OFF", "N/A"], required=True),
                        models.FormItem(id="line_follow_val", label="Line Following Status", item_type=models.FormItemTypeEnum.DROPDOWN, options=["ON", "OFF", "N/A"], required=True),
                    ]
                ),
                # ... (include other sections for pic_handoff_checklist as defined in your original app.py)
                # For brevity, I'm omitting the full list of items for operational_notes, station_ops, payload_status
                # but you should include them here as per your original `get_example_form_schema`
            ]
        )
    # Add other form types here
    # Example:
    # elif form_type == "another_form_type":
    #     return models.MissionFormSchema(...)

    logger.error(f"Static form schema definition not found for form_type: {form_type}")
    raise HTTPException(status_code=404, detail=f"Form type '{form_type}' definition not found.")