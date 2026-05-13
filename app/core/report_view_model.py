from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd

from . import models, utils
from .processors import preprocess_ais_df, preprocess_error_df
from .summaries import get_ais_summary, get_ais_summary_stats


@dataclass
class ReportViewModelInput:
    mission_id: str
    mission_title: str
    platform_name: str
    source_path: str
    start_date: Optional[date]
    end_date: Optional[date]
    mission_goals: List[models.MissionGoal]
    sensor_tracker_deployment: Optional[models.SensorTrackerDeployment]
    ais_df: pd.DataFrame
    error_df: pd.DataFrame


def _format_date_range(start_date: Optional[date], end_date: Optional[date]) -> str:
    if start_date and end_date:
        return f"From {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"
    if start_date:
        return f"From {start_date.strftime('%Y-%m-%d')} to mission end"
    if end_date:
        return f"From mission start to {end_date.strftime('%Y-%m-%d')}"
    return "From mission start to mission end"


def _build_error_rows(error_df: pd.DataFrame) -> List[Dict[str, str]]:
    if error_df.empty:
        return []
    df_processed = preprocess_error_df(error_df.copy())
    if df_processed.empty:
        return []
    rows: List[Dict[str, str]] = []
    for _, row in df_processed.tail(50).iterrows():
        timestamp = row.get("Timestamp")
        if pd.notna(timestamp):
            timestamp_text = pd.to_datetime(timestamp, utc=True).strftime("%Y-%m-%d %H:%M:%S UTC")
        else:
            timestamp_text = "N/A"
        vehicle_value = row.get("VehicleName")
        message_value = row.get("ErrorMessage")
        rows.append(
            {
                "timestamp": timestamp_text,
                "vehicle": str(vehicle_value).strip() if pd.notna(vehicle_value) else "N/A",
                "message": str(message_value).strip() if pd.notna(message_value) and str(message_value).strip() else "No message.",
            }
        )
    return rows


def _build_ais_rows(ais_df: pd.DataFrame) -> List[Dict[str, str]]:
    if ais_df.empty:
        return []
    df_processed = preprocess_ais_df(ais_df.copy())
    if df_processed.empty:
        return []
    rows: List[Dict[str, str]] = []
    for vessel in get_ais_summary(df_processed, max_age_hours=24 * 365):
        seen_time = vessel.get("LastSeenTimestamp")
        if seen_time is not None and pd.notna(seen_time):
            seen_text = pd.to_datetime(seen_time, utc=True).strftime("%Y-%m-%d %H:%M:%S UTC")
        else:
            seen_text = "N/A"
        rows.append(
            {
                "time": seen_text,
                "ship_name": str(vessel.get("ShipName") or "Unknown"),
                "mmsi": str(vessel.get("MMSI") or "N/A"),
                "type": str(vessel.get("Category") or "N/A"),
                "ais_class": str(vessel.get("AISClassDisplay") or vessel.get("AISClass") or "N/A"),
                "speed": f"{float(vessel.get('SpeedOverGround')):.1f} kn" if vessel.get("SpeedOverGround") is not None else "N/A",
                "course": f"{float(vessel.get('CourseOverGround')):.0f}°" if vessel.get("CourseOverGround") is not None else "N/A",
                "destination": str(vessel.get("Destination") or "N/A"),
                "hazardous": "Yes" if vessel.get("IsHazardous") else "No",
            }
        )
    return rows


def build_report_view_model(payload: ReportViewModelInput) -> Dict[str, Any]:
    ais_stats = get_ais_summary_stats(payload.ais_df.copy(), max_age_hours=24 * 365)
    error_rows = _build_error_rows(payload.error_df)
    ais_rows = _build_ais_rows(payload.ais_df)
    deployment = payload.sensor_tracker_deployment

    mission_details_fields = [
        {"label": "Mission Title", "value": payload.mission_title},
        {"label": "Platform Name", "value": payload.platform_name},
        {"label": "Mission ID", "value": payload.mission_id},
        {"label": "Date Range", "value": _format_date_range(payload.start_date, payload.end_date)},
        {"label": "Start time", "value": deployment.start_time.strftime("%Y-%m-%d %H:%M:%S UTC") if deployment and deployment.start_time else "N/A"},
        {"label": "End time", "value": deployment.end_time.strftime("%Y-%m-%d %H:%M:%S UTC") if deployment and deployment.end_time else "N/A"},
        {"label": "Deployment Description", "value": deployment.deployment_comment if deployment and deployment.deployment_comment else "N/A"},
        {"label": "Sea/Region", "value": deployment.sea_name if deployment and deployment.sea_name else "N/A"},
        {"label": "Mission Goals", "value": "; ".join(goal.description for goal in payload.mission_goals) if payload.mission_goals else "N/A"},
        {"label": "Agencies", "value": deployment.agencies if deployment and deployment.agencies else "N/A"},
        {"label": "Roles", "value": deployment.agencies_role if deployment and deployment.agencies_role else "N/A"},
        {"label": "Acknowledgements", "value": deployment.acknowledgement if deployment and deployment.acknowledgement else "N/A"},
        {"label": "Deployment Cruise", "value": deployment.deployment_cruise if deployment and deployment.deployment_cruise else "N/A"},
        {"label": "Recovery Cruise", "value": deployment.recovery_cruise if deployment and deployment.recovery_cruise else "N/A"},
        {"label": "Deployment Personnel", "value": deployment.deployment_personnel if deployment and deployment.deployment_personnel else "N/A"},
        {"label": "Recovery Personnel", "value": deployment.recovery_personnel if deployment and deployment.recovery_personnel else "N/A"},
    ]

    publication_fields = [
        {"label": "Publisher", "value": deployment.publisher_name if deployment and deployment.publisher_name else "N/A"},
        {"label": "Publisher Email", "value": deployment.publisher_email if deployment and deployment.publisher_email else "N/A"},
        {"label": "Publisher URL", "value": deployment.publisher_url if deployment and deployment.publisher_url else "N/A"},
        {"label": "Publisher Country", "value": deployment.publisher_country if deployment and deployment.publisher_country else "N/A"},
        {"label": "Data Repository", "value": deployment.data_repository_link if deployment and deployment.data_repository_link else "N/A"},
        {"label": "Creator", "value": deployment.creator_name if deployment and deployment.creator_name else "N/A"},
        {"label": "Creator Email", "value": deployment.creator_email if deployment and deployment.creator_email else "N/A"},
        {"label": "Creator URL", "value": deployment.creator_url if deployment and deployment.creator_url else "N/A"},
        {"label": "Contributer", "value": deployment.contributor_name if deployment and deployment.contributor_name else "N/A"},
        {"label": "Contributer Role", "value": deployment.contributor_role if deployment and deployment.contributor_role else "N/A"},
        {"label": "Contributer Email", "value": deployment.contributors_email if deployment and deployment.contributors_email else "N/A"},
        {"label": "Remote Data Source", "value": payload.source_path},
    ]

    return {
        "generated_on_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "mission_id": payload.mission_id,
        "mission_title": payload.mission_title,
        "platform_name": payload.platform_name,
        "date_range_text": _format_date_range(payload.start_date, payload.end_date),
        "error_rows": error_rows,
        "ais_summary": {
            "total_vessels": ais_stats.get("total_vessels", 0),
            "class_a_count": ais_stats.get("class_a_count", 0),
            "class_b_count": ais_stats.get("class_b_count", 0),
            "hazardous_count": ais_stats.get("hazardous_count", 0),
        },
        "ais_rows": ais_rows,
        "mission_details_fields": mission_details_fields,
        "publication_fields": publication_fields,
    }
