"""
Slocum platform backlog decisions and feature applicability notes.

Evaluated against Wave Glider parity (roadmap Phase 4).
"""

from __future__ import annotations

# Metadata identity: briefing goals/notes/media attach to SlocumDeployment.id;
# realtime ERDDAP datasets link through SlocumDeployment.erddap_dataset_id.
SLOCUM_METADATA_OWNER_MODEL = "SlocumDeployment"
SLOCUM_REALTIME_LINK_FIELD = "erddap_dataset_id"

# Feature applicability (False = not planned / not applicable for Slocum)
FEATURE_APPLICABILITY = {
    "pic_handoff_forms": False,
    "station_offloads": False,
    "vm4_offload_parser": False,
    "sensor_tracker_sync": True,
    "wg_style_error_analysis": False,  # pending suitable ERDDAP error/event variables
    "unified_chart_api_shim": True,  # implemented at GET /api/slocum/data/{variable}/{dataset_id}
    "live_kml": True,  # Live NetworkLink tokens + static KML (parity with Wave Glider)
    "weekly_pdf_reports": True,
    "forecast_marine": True,
}

BACKLOG_NOTES = {
    "error_analysis": (
        "Defer Slocum error analysis until ERDDAP exposes stable vehicle error/event "
        "variables comparable to WG Vehicle Error Report.csv."
    ),
    "pic_forms": "PIC handoff forms are Wave Glider operational workflow; not applicable to Slocum.",
    "station_offloads": "Acoustic station offload registry is WG VM4-specific; not applicable to Slocum.",
}
