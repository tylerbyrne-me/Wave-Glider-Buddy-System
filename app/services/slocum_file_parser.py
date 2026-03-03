"""
Slocum Mission File Parser and Generator.

Rule-based parser and generator for Webb/Teledyne Slocum Glider .ma and .mi files.
Handles parsing uploaded files, extracting parameters, mission summary, validation,
and generating new files from parameters.
"""

import re
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Filename patterns for .ma subtype detection
MA_SUBTYPE_PATTERNS = [
    (re.compile(r"^sample\d*\.ma$", re.IGNORECASE), "sample"),
    (re.compile(r"^surfac\d*\.ma$", re.IGNORECASE), "surfacing"),
    (re.compile(r"^yo\d*\.ma$", re.IGNORECASE), "yo"),
    (re.compile(r"^goto_l?\d*\.ma$", re.IGNORECASE), "goto"),
]


@dataclass
class ParameterInfo:
    """Single parameter with metadata."""
    name: str
    value: str
    line_number: int
    section: Optional[str] = None
    comment: Optional[str] = None
    raw_line: str = ""


@dataclass
class ParsedMissionFile:
    """Structured result of parsing a single mission file."""
    file_name: str
    file_type: str  # "ma" | "mi"
    ma_subtype: Optional[str] = None  # "sample" | "surfacing" | "yo" | "goto" | None for .mi
    parameters: dict = field(default_factory=dict)  # param_name -> ParameterInfo
    sections: list = field(default_factory=list)  # list of {name, params, start_line}
    referenced_files: list = field(default_factory=list)  # for .mi: list of .ma file names
    waypoints: list = field(default_factory=list)  # for goto .ma
    calibration_coefficients: dict = field(default_factory=dict)  # for .mi
    comments: list = field(default_factory=list)
    raw_lines: list = field(default_factory=list)


@dataclass
class MissionSummary:
    """Cross-file mission summary."""
    yo_cycles: Optional[int] = None
    dive_angle: Optional[float] = None
    climb_angle: Optional[float] = None
    dive_depth: Optional[float] = None
    climb_depth: Optional[float] = None
    surface_interval: Optional[float] = None
    surfacing_trigger_conditions: list = field(default_factory=list)
    active_sample_files: list = field(default_factory=list)
    active_goto_list: Optional[str] = None
    waypoint_count: Optional[int] = None
    post_surface_behavior: Optional[str] = None
    calibration_info: dict = field(default_factory=dict)
    referenced_files: list = field(default_factory=list)  # .ma files referenced by .mi


@dataclass
class ValidationIssue:
    """Single validation issue."""
    param: str
    message: str
    severity: str  # "error" | "warning"
    file_name: Optional[str] = None
    line_number: Optional[int] = None


@dataclass
class ParameterSpec:
    """Parameter specification for file generation (from masterdata)."""
    name: str
    required: bool
    default_value: Optional[str] = None
    description: Optional[str] = None
    valid_range: Optional[tuple] = None
    param_type: Optional[str] = None


@dataclass
class GeneratedFile:
    """Result of generating a new file from parameters."""
    content: str
    file_name: str
    validation_warnings: list = field(default_factory=list)


def _detect_file_type_and_subtype(file_name: str) -> tuple[str, Optional[str]]:
    """Return (file_type, ma_subtype). ma_subtype is None for .mi."""
    name_lower = file_name.lower().strip()
    if name_lower.endswith(".mi"):
        return "mi", None
    if name_lower.endswith(".ma"):
        for pattern, subtype in MA_SUBTYPE_PATTERNS:
            if pattern.match(name_lower):
                return "ma", subtype
        return "ma", None  # unknown .ma subtype
    return "ma", None  # default for unknown extension


def _parse_parameter_line(line: str, line_num: int, section: Optional[str]) -> Optional[tuple[str, ParameterInfo]]:
    """
    Parse a line that may contain param = value.
    Supports: name = value, b_arg: name(units) = value, etc.
    Returns (param_key, ParameterInfo) or None if not a parameter line.
    """
    stripped = line.strip()
    if not stripped or stripped.startswith(";") or stripped.startswith("#"):
        return None
    # Match key = value (key may contain colons, parentheses, etc.)
    match = re.match(r"^([^=]+)=(.*)$", stripped)
    if not match:
        return None
    key = match.group(1).strip().rstrip()
    value = match.group(2).strip()
    # Use full key as stored name (e.g. b_arg: climb_to(m))
    return key, ParameterInfo(
        name=key,
        value=value,
        line_number=line_num,
        section=section,
        raw_line=line,
    )


def parse_file(content: str, file_name: str) -> ParsedMissionFile:
    """
    Parse raw mission file content. Auto-detect file type and .ma subtype from filename.
    Preserves original formatting and line numbers.
    """
    file_type, ma_subtype = _detect_file_type_and_subtype(file_name)
    raw_lines = content.splitlines() if isinstance(content, str) else []
    parameters: dict[str, ParameterInfo] = {}
    sections: list[dict[str, Any]] = []
    current_section: Optional[str] = None
    comments: list[tuple[int, str]] = []
    referenced_files: list[str] = []
    waypoints: list[dict] = []

    for i, line in enumerate(raw_lines, start=1):
        stripped = line.strip()
        # Section header (common in .ma/.mi: lines in brackets or "Section Name")
        section_match = re.match(r"^\[([^\]]+)\]", stripped) or re.match(r"^(\w+)\s*:\s*$", stripped)
        if section_match:
            current_section = section_match.group(1).strip()
            sections.append({"name": current_section, "start_line": i, "params": []})
            continue
        # Comment
        if stripped.startswith(";") or stripped.startswith("#"):
            comments.append((i, line))
            continue
        # Parameter line
        parsed = _parse_parameter_line(line, i, current_section)
        if parsed:
            key, pinfo = parsed
            parameters[key] = pinfo
            if sections and current_section:
                for s in sections:
                    if s["name"] == current_section:
                        s["params"].append(key)
                        break
            continue
        # Referenced file in .mi (e.g. run_file = yo10.ma or similar)
        if file_type == "mi" and ".ma" in stripped.lower():
            m = re.search(r"[\w_]+\s*\.\s*ma", stripped, re.IGNORECASE)
            if m:
                ref = m.group(0).strip()
                if ref not in referenced_files:
                    referenced_files.append(ref)
        # Waypoint-like lines in goto files (lat, lon or waypoint list)
        if ma_subtype == "goto" and stripped and not stripped.startswith(";"):
            wp_match = re.match(r"^(-?\d+\.?\d*)\s+(-?\d+\.?\d*)", stripped)
            if wp_match:
                waypoints.append({"lat": float(wp_match.group(1)), "lon": float(wp_match.group(2))})

    return ParsedMissionFile(
        file_name=file_name,
        file_type=file_type,
        ma_subtype=ma_subtype,
        parameters=parameters,
        sections=sections,
        referenced_files=referenced_files,
        waypoints=waypoints,
        raw_lines=raw_lines,
    )


def extract_mission_summary(parsed_files: list[ParsedMissionFile]) -> MissionSummary:
    """
    Cross-file analysis: use .mi as orchestrator and resolve .ma files to build
    yo cycles, surface interval, sampling, waypoints, surfacing conditions, post-surface behavior.
    """
    summary = MissionSummary()
    mi_files = [p for p in parsed_files if p.file_type == "mi"]
    ma_by_subtype: dict[str, list[ParsedMissionFile]] = {"sample": [], "surfacing": [], "yo": [], "goto": []}
    for p in parsed_files:
        if p.ma_subtype:
            ma_by_subtype.setdefault(p.ma_subtype, []).append(p)

    # Yo: dive/climb angles, depth, cycle count
    for p in ma_by_subtype.get("yo", []):
        for name, info in p.parameters.items():
            n = name.lower()
            v = info.value
            if "dive_angle" in n or "diveangle" in n:
                try:
                    summary.dive_angle = float(re.search(r"-?\d+\.?\d*", v).group(0))
                except (ValueError, AttributeError):
                    pass
            if "climb_angle" in n or "climbangle" in n:
                try:
                    summary.climb_angle = float(re.search(r"-?\d+\.?\d*", v).group(0))
                except (ValueError, AttributeError):
                    pass
            if "dive_to" in n or "divedepth" in n:
                try:
                    summary.dive_depth = float(re.search(r"-?\d+\.?\d*", v).group(0))
                except (ValueError, AttributeError):
                    pass
            if "climb_to" in n or "climb_to" in n or "climbdepth" in n:
                try:
                    summary.climb_depth = float(re.search(r"-?\d+\.?\d*", v).group(0))
                except (ValueError, AttributeError):
                    pass
            if "cycle" in n or "yo" in n:
                try:
                    summary.yo_cycles = int(re.search(r"\d+", v).group(0))
                except (ValueError, AttributeError):
                    pass
    # Surfacing: interval, triggers
    for p in ma_by_subtype.get("surfacing", []):
        for name, info in p.parameters.items():
            n = name.lower()
            v = info.value
            if "surface" in n and ("interval" in n or "time" in n or "hour" in n):
                try:
                    summary.surface_interval = float(re.search(r"\d+\.?\d*", v).group(0))
                except (ValueError, AttributeError):
                    pass
            if "trigger" in n or "condition" in n:
                summary.surfacing_trigger_conditions.append(f"{name}={v}")
    # Sample files: active list from .mi or from parsed .ma
    for p in ma_by_subtype.get("sample", []):
        summary.active_sample_files.append(p.file_name)
    # Goto: waypoint list
    for p in ma_by_subtype.get("goto", []):
        summary.active_goto_list = p.file_name
        summary.waypoint_count = len(p.waypoints) if p.waypoints else None
    # From .mi: referenced files, defaults, post-surface
    for p in mi_files:
        summary.referenced_files = p.referenced_files or summary.referenced_files
        for name, info in p.parameters.items():
            n = name.lower()
            if "post_surface" in n or "after_surface" in n or "mission_end" in n:
                summary.post_surface_behavior = info.value
    return summary


def validate_parameters(parsed: ParsedMissionFile, masterdata: dict) -> list[ValidationIssue]:
    """Single-file parameter validity (range, type) using masterdata when available."""
    issues: list[ValidationIssue] = []
    if not masterdata:
        return issues
    # masterdata can be dict of param_name -> {min, max, type, description}
    for name, info in parsed.parameters.items():
        spec = masterdata.get(name) or masterdata.get(name.split(":")[-1].strip())
        if not spec or not isinstance(spec, dict):
            continue
        try:
            num = float(info.value)
        except ValueError:
            if spec.get("type") == "float" or spec.get("type") == "int":
                issues.append(ValidationIssue(
                    param=name,
                    message=f"Expected numeric value, got: {info.value}",
                    severity="error",
                    file_name=parsed.file_name,
                    line_number=info.line_number,
                ))
            continue
        min_v = spec.get("min")
        max_v = spec.get("max")
        if min_v is not None and num < float(min_v):
            issues.append(ValidationIssue(
                param=name,
                message=f"Value {num} below minimum {min_v}",
                severity="warning",
                file_name=parsed.file_name,
                line_number=info.line_number,
            ))
        if max_v is not None and num > float(max_v):
            issues.append(ValidationIssue(
                param=name,
                message=f"Value {num} above maximum {max_v}",
                severity="warning",
                file_name=parsed.file_name,
                line_number=info.line_number,
            ))
    return issues


def validate_deployment(parsed_files: list[ParsedMissionFile], masterdata: dict) -> list[ValidationIssue]:
    """Cross-file validation: parameter interactions across files."""
    issues: list[ValidationIssue] = []
    for p in parsed_files:
        issues.extend(validate_parameters(p, masterdata))
    # Placeholder for cross-file rules (e.g. climb_depth vs surface depth consistency)
    return issues


def get_required_parameters(subtype: str, masterdata: dict) -> list[ParameterSpec]:
    """Return required and optional parameters for a file subtype (for creation form)."""
    specs: list[ParameterSpec] = []
    # masterdata may have a section per subtype or a list of params per subtype
    subtype_key = subtype.lower()
    section = masterdata.get("subtypes", {}).get(subtype_key) or masterdata.get(subtype_key)
    if isinstance(section, dict):
        for name, meta in section.items():
            if isinstance(meta, dict):
                specs.append(ParameterSpec(
                    name=name,
                    required=meta.get("required", False),
                    default_value=meta.get("default"),
                    description=meta.get("description"),
                    valid_range=tuple(meta["range"]) if "range" in meta else None,
                    param_type=meta.get("type"),
                ))
            else:
                specs.append(ParameterSpec(name=name, required=False))
    return specs


def generate_file(
    file_name: str,
    subtype: str,
    parameters: dict[str, str],
    masterdata: dict,
) -> GeneratedFile:
    """
    Create a new .ma or .mi file from provided parameters.
    Fills in defaults from masterdata where not provided.
    """
    warnings: list[ValidationIssue] = []
    lines: list[str] = []
    file_type = "mi" if file_name.lower().endswith(".mi") else "ma"
    if file_type == "ma":
        lines.append(f"; Generated {subtype} file: {file_name}")
        lines.append("")
        spec_list = get_required_parameters(subtype, masterdata)
        seen = set(parameters.keys())
        for spec in spec_list:
            value = parameters.get(spec.name, spec.default_value)
            if value is None and spec.required:
                value = ""
                warnings.append(ValidationIssue(spec.name, "Required parameter missing", "warning"))
            if value is not None:
                lines.append(f"{spec.name} = {value}")
        # Any extra params not in spec
        for k, v in parameters.items():
            if k not in seen:
                lines.append(f"{k} = {v}")
    else:
        lines.append(f"; Generated mission file: {file_name}")
        lines.append("")
        for k, v in parameters.items():
            lines.append(f"{k} = {v}")
    content = "\n".join(lines)
    if not content.endswith("\n"):
        content += "\n"
    return GeneratedFile(content=content, file_name=file_name, validation_warnings=warnings)
