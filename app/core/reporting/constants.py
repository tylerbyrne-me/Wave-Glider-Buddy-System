"""Paths and shared constants for mission PDF reports."""

from pathlib import Path

# Base output directory for generated reports (served under /static/mission_reports/...)
REPORTS_ROOT = Path(__file__).resolve().parent.parent.parent.parent / "web" / "static" / "mission_reports"
REPORTS_ROOT.mkdir(parents=True, exist_ok=True)

LOGO_PATH = Path(__file__).resolve().parent.parent.parent.parent / "web" / "static" / "images" / "otn_logo.png"
