"""
Template configuration for the Wave Glider Buddy System.
"""
from fastapi.templating import Jinja2Templates
from pathlib import Path

# Path configuration
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATES_DIR = PROJECT_ROOT / "web" / "templates"

# Initialize Jinja2 templates
templates = Jinja2Templates(
    directory=str(TEMPLATES_DIR),
    autoescape=True,  # Enable auto-escape for security
) 