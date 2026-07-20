"""Static schema for the Slocum daily pilot checklist form."""

from __future__ import annotations

from ..core import models
from ..core.slocum_checklist_autofill import CHECKLIST_FORM_TITLE, CHECKLIST_FORM_TYPE


def get_slocum_daily_checklist_schema() -> models.MissionFormSchema:
    """
    Return the static structure of the Slocum daily checklist (no live autofill).

    Autofill values and reference displays are injected by the checklist router.
    SFMC-dependent items remain manual until a later phase.
    """
    return models.MissionFormSchema(
        form_type=CHECKLIST_FORM_TYPE,
        title=CHECKLIST_FORM_TITLE,
        description=(
            "Daily pilot checklist for Slocum gliders. Review autofilled values, "
            "complete manual items (SFMC until integrated), verify, and submit."
        ),
        sections=[
            models.FormSection(
                id="mission_status",
                title="Mission Status",
                section_comment=(
                    "SFMC autofills mission file, aborts/oddities, surfacing hours, and "
                    "offload when the SFMC client is configured; otherwise enter manually."
                ),
                items=[
                    models.FormItem(
                        id="pilot_val",
                        label="Pilot (submitting)",
                        item_type=models.FormItemTypeEnum.AUTOFILLED_VALUE,
                        value="N/A",
                    ),
                    models.FormItem(
                        id="dataset_id_val",
                        label="Dataset ID",
                        item_type=models.FormItemTypeEnum.STATIC_TEXT,
                        value="N/A",
                    ),
                    models.FormItem(
                        id="last_data_time_val",
                        label="Last Telemetry Time (UTC)",
                        item_type=models.FormItemTypeEnum.AUTOFILLED_VALUE,
                        value="N/A",
                    ),
                    models.FormItem(
                        id="aborts_oddities_val",
                        label="Aborts / warnings / oddities (Use/^W)",
                        item_type=models.FormItemTypeEnum.TEXT_AREA,
                        placeholder="Note any aborts, warnings, or surprises…",
                    ),
                    models.FormItem(
                        id="expected_mission_file_ref_val",
                        label="Expected mission file (reference)",
                        item_type=models.FormItemTypeEnum.STATIC_TEXT,
                        value="—",
                    ),
                    models.FormItem(
                        id="mission_file_running_val",
                        label="Mission file currently running",
                        item_type=models.FormItemTypeEnum.TEXT_INPUT,
                        placeholder="e.g. mission.mi or lastgasp.mi",
                    ),
                    models.FormItem(
                        id="surfacing_hours_val",
                        label="Surfacing hours (appropriate for surface behavior)",
                        item_type=models.FormItemTypeEnum.TEXT_INPUT,
                        placeholder="e.g. 3.75",
                    ),
                    models.FormItem(
                        id="offloaded_24h_val",
                        label="Offloaded in the last 24 hours?",
                        item_type=models.FormItemTypeEnum.DROPDOWN,
                        options=["Yes", "No — manual offload ASAP", "N/A"],
                        required=True,
                    ),
                    models.FormItem(
                        id="course_vmg_val",
                        label="VMG / course progress",
                        item_type=models.FormItemTypeEnum.AUTOFILLED_VALUE,
                        value="N/A",
                    ),
                    models.FormItem(
                        id="storm_outlook_val",
                        label="Incoming storms / weather outlook",
                        item_type=models.FormItemTypeEnum.AUTOFILLED_VALUE,
                        value="N/A",
                    ),
                ],
            ),
            models.FormSection(
                id="power_endurance",
                title="Power & Endurance",
                items=[
                    models.FormItem(
                        id="endurance_ref_val",
                        label="Endurance / coulomb total (reference)",
                        item_type=models.FormItemTypeEnum.STATIC_TEXT,
                        value="—",
                    ),
                    models.FormItem(
                        id="voltage_val",
                        label="m_battery (voltage)",
                        item_type=models.FormItemTypeEnum.AUTOFILLED_VALUE,
                        value="N/A",
                    ),
                    models.FormItem(
                        id="coulomb_prior_val",
                        label="m_coulomb_amphr_total (~24h prior)",
                        item_type=models.FormItemTypeEnum.AUTOFILLED_VALUE,
                        value="N/A",
                    ),
                    models.FormItem(
                        id="coulomb_latest_val",
                        label="m_coulomb_amphr_total (latest)",
                        item_type=models.FormItemTypeEnum.AUTOFILLED_VALUE,
                        value="N/A",
                    ),
                    models.FormItem(
                        id="amphr_rate_val",
                        label="Amphr usage rate / day",
                        item_type=models.FormItemTypeEnum.AUTOFILLED_VALUE,
                        value="N/A",
                    ),
                    models.FormItem(
                        id="days_left_val",
                        label="Days left (at current rate)",
                        item_type=models.FormItemTypeEnum.AUTOFILLED_VALUE,
                        value="N/A",
                    ),
                    models.FormItem(
                        id="end_date_val",
                        label="Projected end date",
                        item_type=models.FormItemTypeEnum.AUTOFILLED_VALUE,
                        value="N/A",
                    ),
                ],
            ),
            models.FormSection(
                id="flight_variables",
                title="Flight Variables",
                items=[
                    models.FormItem(
                        id="vacuum_val",
                        label="m_vacuum",
                        item_type=models.FormItemTypeEnum.AUTOFILLED_VALUE,
                        value="N/A",
                    ),
                    models.FormItem(
                        id="roll_val",
                        label="m_roll (24h avg / min / max; − port / + starboard)",
                        item_type=models.FormItemTypeEnum.AUTOFILLED_VALUE,
                        value="N/A",
                    ),
                    models.FormItem(
                        id="pitch_val",
                        label="Pitch climb/dive averages (commanded vs measured)",
                        item_type=models.FormItemTypeEnum.AUTOFILLED_VALUE,
                        value="N/A",
                    ),
                    models.FormItem(
                        id="fin_val",
                        label="Fin (commanded vs measured)",
                        item_type=models.FormItemTypeEnum.AUTOFILLED_VALUE,
                        value="N/A",
                    ),
                    models.FormItem(
                        id="oil_vol_val",
                        label="Buoyancy (oil or ballast) climb/dive averages",
                        item_type=models.FormItemTypeEnum.AUTOFILLED_VALUE,
                        value="N/A",
                    ),
                    models.FormItem(
                        id="battpos_val",
                        label="m_battpos (commanded vs measured)",
                        item_type=models.FormItemTypeEnum.AUTOFILLED_VALUE,
                        value="N/A",
                    ),
                    models.FormItem(
                        id="depth_rate_val",
                        label="m_depth_rate_avg_final",
                        item_type=models.FormItemTypeEnum.AUTOFILLED_VALUE,
                        value="N/A",
                    ),
                    models.FormItem(
                        id="water_depth_val",
                        label="m_water_depth",
                        item_type=models.FormItemTypeEnum.AUTOFILLED_VALUE,
                        value="N/A",
                    ),
                    models.FormItem(
                        id="u_alt_min_depth_ref_val",
                        label="u_alt_min_depth (reference)",
                        item_type=models.FormItemTypeEnum.STATIC_TEXT,
                        value="—",
                    ),
                    models.FormItem(
                        id="u_alt_min_depth_val",
                        label="u_alt_min_depth (current / observed)",
                        item_type=models.FormItemTypeEnum.TEXT_INPUT,
                        placeholder="Current value from vehicle (pilot entry; persisted with checklist)",
                    ),
                    models.FormItem(
                        id="bms_currents_val",
                        label="m_bms_[pitch,aft,ebay]_current (G3+)",
                        item_type=models.FormItemTypeEnum.AUTOFILLED_VALUE,
                        value="N/A",
                    ),
                    models.FormItem(
                        id="leakdetect_val",
                        label="Leak detect channels (24h range / spikes)",
                        item_type=models.FormItemTypeEnum.AUTOFILLED_VALUE,
                        value="N/A",
                    ),
                    models.FormItem(
                        id="density_range_val",
                        label="Water density range (24–48h)",
                        item_type=models.FormItemTypeEnum.AUTOFILLED_VALUE,
                        value="N/A",
                    ),
                ],
            ),
            models.FormSection(
                id="mission_config",
                title="Mission Configuration",
                section_comment=(
                    "Script and goto (Initial_wpt from latest archive *_goto_*.ma) "
                    "autofill from SFMC when available; expected script ref from admin."
                ),
                items=[
                    models.FormItem(
                        id="expected_script_ref_val",
                        label="Expected script (reference)",
                        item_type=models.FormItemTypeEnum.STATIC_TEXT,
                        value="—",
                    ),
                    models.FormItem(
                        id="script_running_val",
                        label="Script currently running",
                        item_type=models.FormItemTypeEnum.TEXT_INPUT,
                        placeholder="e.g. TC_safe_g3s.xml",
                    ),
                    models.FormItem(
                        id="goto_state_val",
                        label="Goto list / Initial_wpt state",
                        item_type=models.FormItemTypeEnum.TEXT_INPUT,
                        placeholder="e.g. -1 (after last achieved)",
                    ),
                ],
            ),
            models.FormSection(
                id="science",
                title="Science Variables",
                items=[
                    models.FormItem(
                        id="ctd_freshness_val",
                        label="CTD / science last data time",
                        item_type=models.FormItemTypeEnum.AUTOFILLED_VALUE,
                        value="N/A",
                    ),
                    models.FormItem(
                        id="science_realistic_val",
                        label="Science variables reporting realistic data?",
                        item_type=models.FormItemTypeEnum.DROPDOWN,
                        options=["Yes", "No — see comments", "Partial"],
                        required=True,
                    ),
                    models.FormItem(
                        id="asc_gap_check_val",
                        label="Evening .asc / file gap check",
                        item_type=models.FormItemTypeEnum.DROPDOWN,
                        options=["OK", "Gaps noted — notified", "N/A"],
                        required=True,
                    ),
                    models.FormItem(
                        id="argos_id_ref_val",
                        label="Argos ID (reference)",
                        item_type=models.FormItemTypeEnum.STATIC_TEXT,
                        value="—",
                    ),
                    models.FormItem(
                        id="argos_monitor_val",
                        label="Argos monitored?",
                        item_type=models.FormItemTypeEnum.DROPDOWN,
                        options=["Yes", "No", "N/A"],
                        required=True,
                    ),
                ],
            ),
            models.FormSection(
                id="comments",
                title="Comments",
                items=[
                    models.FormItem(
                        id="user_comments_val",
                        label="Comments",
                        item_type=models.FormItemTypeEnum.TEXT_AREA,
                        placeholder="Optional comments…",
                    ),
                ],
            ),
        ],
    )
