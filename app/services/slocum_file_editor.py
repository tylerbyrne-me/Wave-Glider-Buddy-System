"""
Slocum Mission File Editor.

Applies parameter changes to mission files while preserving formatting.
Operates at deployment level for cross-file validation and batch diffs.
"""

import re
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from .slocum_file_parser import (
    parse_file,
    validate_parameters,
    ValidationIssue,
)

logger = logging.getLogger(__name__)


@dataclass
class ParameterChange:
    """Single parameter change request."""
    param: str
    new_value: str
    file_name: str


@dataclass
class DiffLine:
    """One line in a diff."""
    line_num: int
    kind: str  # "context" | "add" | "remove"
    content: str


@dataclass
class DeploymentEditResult:
    """Result of applying a batch of changes across deployment files."""
    modified_files: dict = field(default_factory=dict)  # file_name -> modified_content
    changes_applied: list = field(default_factory=list)  # [{param, old_value, new_value, file_name, line_number}]
    file_diffs: dict = field(default_factory=dict)  # file_name -> list of DiffLine
    single_file_warnings: list = field(default_factory=list)  # ValidationIssue
    cross_file_warnings: list = field(default_factory=list)
    cross_file_suggestions: list = field(default_factory=list)


def _apply_change_to_content(content: str, param_name: str, new_value: str, file_name: str) -> tuple[str, Optional[int], Optional[str]]:
    """
    Replace the value of param_name in content. Preserve line structure.
    Returns (modified_content, line_number, old_value).
    """
    lines = content.splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith(";") or stripped.startswith("#"):
            continue
        match = re.match(r"^([^=]+)=(.*)$", stripped)
        if not match:
            continue
        key = match.group(1).strip().rstrip()
        if key != param_name:
            continue
        old_value = match.group(2).strip()
        # Rebuild line preserving leading/trailing whitespace
        prefix = line[: line.index("=") + 1]
        new_line = prefix + " " + str(new_value)
        lines[i] = new_line
        return "\n".join(lines), i + 1, old_value
    return content, None, None


def apply_deployment_changes(
    deployment_files: dict[str, str],
    changes: list[ParameterChange],
    masterdata: dict,
) -> DeploymentEditResult:
    """
    Apply a batch of changes across multiple files. All changes are considered as a whole.
    Runs cross-file validation. Returns result with modified content and diffs.
    """
    result = DeploymentEditResult()
    working: dict[str, str] = dict(deployment_files)
    changes_by_file: dict[str, list[tuple[ParameterChange, str, int]]] = {}  # file -> [(change, old_value, line_num)]

    for ch in changes:
        if ch.file_name not in working:
            result.single_file_warnings.append(ValidationIssue(
                ch.param, f"File not in deployment: {ch.file_name}", "error", ch.file_name
            ))
            continue
        content = working[ch.file_name]
        new_content, line_num, old_value = _apply_change_to_content(content, ch.param, ch.new_value, ch.file_name)
        if line_num is None:
            result.single_file_warnings.append(ValidationIssue(
                ch.param, f"Parameter not found in {ch.file_name}", "warning", ch.file_name
            ))
            continue
        working[ch.file_name] = new_content
        result.changes_applied.append({
            "param": ch.param,
            "old_value": old_value,
            "new_value": ch.new_value,
            "file_name": ch.file_name,
            "line_number": line_num,
        })
        changes_by_file.setdefault(ch.file_name, []).append((ch, old_value or "", line_num))

    result.modified_files = working

    # Single-file validation on modified files
    for fname, content in working.items():
        parsed = parse_file(content, fname)
        result.single_file_warnings.extend(
            validate_parameters(parsed, masterdata)
        )

    # Build per-file diffs
    for fname in result.modified_files:
        orig = deployment_files.get(fname, "")
        modified = result.modified_files.get(fname, orig)
        result.file_diffs[fname] = generate_diff(orig, modified)

    return result


def generate_diff(original: str, modified: str) -> list[DiffLine]:
    """Line-by-line diff for a single file (simple implementation)."""
    a_lines = original.splitlines()
    b_lines = modified.splitlines()
    diff: list[DiffLine] = []
    i, j = 0, 0
    while i < len(a_lines) or j < len(b_lines):
        if i < len(a_lines) and j < len(b_lines) and a_lines[i] == b_lines[j]:
            diff.append(DiffLine(line_num=i + 1, kind="context", content=a_lines[i]))
            i += 1
            j += 1
        elif j < len(b_lines) and (i >= len(a_lines) or (i < len(a_lines) and a_lines[i] != b_lines[j] and (i + 1 >= len(a_lines) or a_lines[i + 1] != b_lines[j]))):
            diff.append(DiffLine(line_num=j + 1, kind="add", content="+ " + b_lines[j]))
            j += 1
        elif i < len(a_lines):
            diff.append(DiffLine(line_num=i + 1, kind="remove", content="- " + a_lines[i]))
            i += 1
        else:
            j += 1
    return diff


def generate_deployment_diff(
    original_files: dict[str, str],
    modified_files: dict[str, str],
) -> dict[str, list[DiffLine]]:
    """Consolidated diff across all affected files."""
    out: dict[str, list[DiffLine]] = {}
    all_names = set(original_files) | set(modified_files)
    for name in all_names:
        orig = original_files.get(name, "")
        mod = modified_files.get(name, "")
        if orig != mod:
            out[name] = generate_diff(orig, mod)
    return out
