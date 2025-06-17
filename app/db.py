import logging

from sqlmodel import Session as SQLModelSession  # type: ignore
from sqlmodel import create_engine

from app.config import settings  # Assuming settings are in app.config

logger = logging.getLogger(__name__)

# --- Database Setup (SQLite with SQLModel) ---
# Use echo=False for production, True can be noisy but useful for debugging SQL
sqlite_engine = create_engine(
    settings.sqlite_database_url,
    echo=settings.sqlite_echo_log,
    connect_args={
        "check_same_thread": False,
        "timeout": 15,
    },  # Add timeout (e.g., 15 seconds)
)


def get_db_session():
    # The session is managed by FastAPI's dependency injection system.
    # It will be automatically closed after the request.
    with SQLModelSession(sqlite_engine) as session:
        yield session
