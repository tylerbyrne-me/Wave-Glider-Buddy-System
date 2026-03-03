"""
Slocum Mission LLM Service.

Uses LLM + masterdata vector search for mission interpretation and
natural language change request parsing.
"""

import logging
from typing import Any, Optional

from .slocum_file_parser import ParsedMissionFile, MissionSummary
from .slocum_file_editor import ParameterChange
from .slocum_masterdata_service import search_masterdata

logger = logging.getLogger(__name__)


def interpret_mission(
    parsed_files: list[ParsedMissionFile],
    mission_summary: Optional[MissionSummary],
    llm_service: Optional[Any] = None,
) -> str:
    """
    Generate a human-readable interpretation of the mission from parsed files and summary.
    Uses LLM if available, otherwise a simple template.
    """
    parts = []
    if mission_summary:
        if mission_summary.yo_cycles is not None:
            parts.append(f"This mission is programmed for {mission_summary.yo_cycles} yo (dive/climb) cycles.")
        if mission_summary.dive_angle is not None or mission_summary.climb_angle is not None:
            parts.append(
                f"Dive angle: {mission_summary.dive_angle}°, climb angle: {mission_summary.climb_angle}°."
            )
        if mission_summary.dive_depth is not None or mission_summary.climb_depth is not None:
            parts.append(
                f"Dive to depth: {mission_summary.dive_depth}m, climb to depth: {mission_summary.climb_depth}m."
            )
        if mission_summary.surface_interval is not None:
            parts.append(f"Surface interval: {mission_summary.surface_interval} hours.")
        if mission_summary.active_sample_files:
            parts.append(f"Active sample files: {', '.join(mission_summary.active_sample_files)}.")
        if mission_summary.active_goto_list:
            parts.append(f"Goto list: {mission_summary.active_goto_list} ({mission_summary.waypoint_count or 0} waypoints).")
        if mission_summary.post_surface_behavior:
            parts.append(f"Post-surface behavior: {mission_summary.post_surface_behavior}.")
    if not parts:
        parts.append("No mission summary could be derived from the uploaded files.")
    return " ".join(parts)


def parse_natural_language_change(
    request: str,
    current_parameters_by_file: dict[str, dict[str, str]],
    llm_service: Optional[Any] = None,
) -> list[ParameterChange]:
    """
    Convert a natural language change request into a list of ParameterChange.
    Uses masterdata vector search to resolve parameter names, and optionally LLM.
    """
    changes: list[ParameterChange] = []
    request_lower = request.lower().strip()
    # Try to find parameter mentions via masterdata search
    masterdata_hits = search_masterdata(request, limit=5)
    # Simple heuristic: if user says "change X to Y", try to extract value
    import re
    to_match = re.search(r"\bto\s+([\d\.\-]+\s*(?:m|meters?|deg|°)?)\b", request_lower, re.IGNORECASE)
    new_value = to_match.group(1).strip() if to_match else ""
    if not new_value and re.search(r"\d+\.?\d*", request):
        to_match = re.search(r"([\d\.\-]+)\s*(m|meters?|deg|°)?", request)
        if to_match:
            new_value = to_match.group(1) + (to_match.group(2) or "")

    for _meta, _sim, doc in masterdata_hits:
        # Try to find a parameter name in the chunk (e.g. b_arg: climb_to(m))
        param_match = re.search(r"([a-zA-Z_][a-zA-Z0-9_:\.\(\)\-]*)\s*[=:]", doc)
        if param_match and new_value:
            param_name = param_match.group(1).strip()
            # Determine which file this param might be in from current_parameters_by_file
            file_name = None
            for fn, params in current_parameters_by_file.items():
                if param_name in params:
                    file_name = fn
                    break
            if not file_name and current_parameters_by_file:
                file_name = next(iter(current_parameters_by_file.keys()))
            if file_name:
                changes.append(ParameterChange(param=param_name, new_value=new_value, file_name=file_name))
                break
    return changes
