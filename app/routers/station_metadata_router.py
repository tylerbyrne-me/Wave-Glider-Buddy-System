# station_metadata_router.py
import logging
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from typing import Annotated, Any, Dict, List, Optional
import io

import pandas as pd
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, status, UploadFile, File, BackgroundTasks
from fastapi.responses import JSONResponse, StreamingResponse
from sqlmodel import select  # Import select for queries
from sqlalchemy.orm import selectinload  # For eager loading relationships

from ..core.auth import get_current_active_user, get_current_admin_user
from ..core import models
from ..core.crud import station_metadata_crud
from ..core.models import User as UserModel # UserModel alias is used
from ..core.db import SQLModelSession, get_db_session, sqlite_engine
from ..services.station_overview import build_status_overview_row
from ..services.station_season_service import StationSeasonService
from ..services.station_history_service import (
    aggregate_offload_stats,
    build_station_timeline,
    group_stations_by_status,
    logs_by_season_counts,
    station_mini_summary,
)
from ..core.station_registry_policy import (
    station_blocks_edits,
    offload_log_matches_season_year,
)
from ..core.feature_toggles import is_feature_enabled

logger = logging.getLogger(__name__)


def _is_admin_or_pic_designated_pilot(user: UserModel) -> bool:
    if user.role == models.UserRoleEnum.admin:
        return True
    if user.role == models.UserRoleEnum.pilot and bool(user.is_pic):
        return True
    return False


def _resolve_station_flag_state(
    events: List[models.StationFlagEvent],
    *,
    target_year: Optional[int],
    season_is_closed: bool,
) -> Dict[str, Dict[str, Any]]:
    state_by_station: Dict[str, Dict[str, Any]] = {}
    for event in sorted(events, key=lambda e: e.changed_at_utc):
        include_event = False
        if target_year is None:
            include_event = event.field_season_year is None
        elif offload_log_matches_season_year(
            log_season=event.field_season_year,
            target_year=target_year,
            season_is_closed=season_is_closed,
        ):
            include_event = True
        if not include_event:
            continue
        state_by_station[event.station_id] = {
            "is_flagged": bool(event.is_flagged),
            "flag_note": event.note,
            "changed_at_utc": event.changed_at_utc,
        }
    return state_by_station

# Create an APIRouter instance
router = APIRouter()


def _offload_log_sort_key(log: models.OffloadLog) -> datetime:
    ts = log.offload_end_time_utc or log.offload_start_time_utc or log.log_timestamp_utc
    if ts is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


def _refresh_station_last_offload_from_all_logs(
    session: SQLModelSession, station_id: str
) -> None:
    """Recompute StationMetadata last offload fields from all logs for this station."""
    stmt = select(models.OffloadLog).where(models.OffloadLog.station_id == station_id)
    logs = list(session.exec(stmt).all())
    station = session.get(models.StationMetadata, station_id)
    if not station:
        return
    if not logs:
        station.last_offload_timestamp_utc = None
        station.was_last_offload_successful = None
        session.add(station)
        return
    latest = max(logs, key=_offload_log_sort_key)
    ts = latest.offload_end_time_utc or latest.offload_start_time_utc or latest.log_timestamp_utc
    if ts:
        station.last_offload_timestamp_utc = ts
    if latest.was_offloaded is not None:
        station.was_last_offload_successful = latest.was_offloaded
    session.add(station)


def _last_conflict_detail_from_parser_notes(parser_notes: Optional[str]) -> Optional[str]:
    if not parser_notes:
        return None
    best: Optional[str] = None
    for line in parser_notes.split("\n"):
        if "[CONFLICT" in line:
            idx = line.find("] ")
            if idx != -1:
                best = line[idx + 2 :].strip()
    return best


def _coerce_offload_field_from_conflict_string(field_name: str, s: str) -> Any:
    if s in ("None", ""):
        return None
    if field_name == "was_offloaded":
        sl = s.lower()
        if sl in ("true", "1", "yes"):
            return True
        if sl in ("false", "0", "no"):
            return False
        return None
    if field_name == "distance_command_sent_m":
        try:
            return float(s)
        except ValueError:
            return None
    if field_name in (
        "arrival_date",
        "departure_date",
        "time_first_command_sent_utc",
        "offload_start_time_utc",
        "offload_end_time_utc",
    ):
        try:
            s_clean = s.strip()
            if " " in s_clean and "T" not in s_clean and "+" not in s_clean and "Z" not in s_clean:
                s_clean = s_clean.replace(" ", "T", 1)
            return datetime.fromisoformat(s_clean.replace("Z", "+00:00"))
        except ValueError:
            return None
    return s


def _apply_parser_values_from_conflict_detail(
    log: models.OffloadLog, conflict_detail: Optional[str]
) -> None:
    if not conflict_detail:
        return
    for part in conflict_detail.split(" | "):
        part = part.strip()
        m = re.match(r"^(\w+): existing='(.*)' parser='(.*)'$", part)
        if not m:
            continue
        field_name, parser_str = m.group(1), m.group(3)
        if field_name in ("parser_notes", "parser_run_id", "parser_session_ref"):
            continue
        val = _coerce_offload_field_from_conflict_string(field_name, parser_str)
        setattr(log, field_name, val)


def _mark_conflict_resolved_in_parser_notes(
    parser_notes: Optional[str],
    admin_username: str,
    resolution: str,
) -> str:
    """Turn the latest [CONFLICT ...] line into [RESOLVED ...] so the queue filter drops it."""
    stamp = datetime.now(timezone.utc).isoformat()
    if not parser_notes:
        return f"[RESOLVED {stamp}] by={admin_username} action={resolution}\n"
    lines = parser_notes.split("\n")
    last_i: Optional[int] = None
    for i, line in enumerate(lines):
        if "[CONFLICT" in line:
            last_i = i
    if last_i is None:
        return (
            parser_notes
            + f"\n[RESOLVED {stamp}] by={admin_username} action={resolution} (no CONFLICT line)"
        )
    line = lines[last_i]
    line = line.replace("[CONFLICT", "[RESOLVED", 1)
    line = f"{line} | resolved_by={admin_username} | resolution={resolution}"
    lines[last_i] = line
    return "\n".join(lines)
# logger.debug(f"station_metadata_router.py - APIRouter instance created: {type(router)}") # Changed to logger

# --- Station Metadata Endpoints ---


# logger.debug("station_metadata_router.py - Defining POST /station_metadata/ (on router)") # Changed to logger
@router.post(
    "/station_metadata/",
    response_model=models.StationMetadataCreateResponse, # Use the new response model
    status_code=status.HTTP_200_OK, # Change status code to 200 for upsert
    tags=["Station Metadata Admin"],
)
async def create_or_update_station_metadata_on_router(
    station_data: models.StationMetadataCreate,
    session: Annotated[SQLModelSession, Depends(get_db_session)],
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
):
    logger.info(
        f"ROUTER: User '{current_user.username}' attempting to "
        f"create/update station: {station_data.station_id}"
    )

    existing_station = session.get(models.StationMetadata, station_data.station_id)
    if existing_station:
        if not _is_admin_or_pic_designated_pilot(current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins or PIC-designated pilots can edit station information",
            )
    elif current_user.role != models.UserRoleEnum.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can create new station records",
        )

    if existing_station and station_blocks_edits(existing_station):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Station {station_data.station_id} is retired or archived and cannot be modified",
        )

    # The original logic is now in a reusable CRUD function
    db_station, is_created = station_metadata_crud.create_or_update_station(
        session=session, station_data=station_data
    )
    return models.StationMetadataCreateResponse(
        **db_station.model_dump(), # Unpack station data
        is_created=is_created # Add the new flag
    )


# logger.debug("station_metadata_router.py - POST /station_metadata/ definition processed.") # Changed to logger


# logger.debug("station_metadata_router.py - Defining GET /station_metadata/{station_id} (on router)") # Changed to logger
@router.get(
    "/station_metadata/{station_id}",
    response_model=models.StationMetadataReadWithLogs,
    tags=["Station Metadata"],
)
async def get_station_metadata_by_id_on_router(
    station_id: str,
    session: Annotated[SQLModelSession, Depends(get_db_session)],
    # Any active user can view
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
):
    logger.info(
        f"ROUTER: User '{current_user.username}' fetching station metadata "
        f"for ID: {station_id}"
    )
    statement = (
        select(models.StationMetadata)
        .where(models.StationMetadata.station_id == station_id)
        .options(selectinload(models.StationMetadata.offload_logs))
    )
    station = session.exec(statement).first()
    if not station:
        logger.warning(f"ROUTER: Station with ID '{station_id}' not found.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Station not found"
        )
    return station


# logger.debug("station_metadata_router.py - GET /station_metadata/{station_id} definition processed.") # Changed to logger


@router.post(
    "/station_metadata/upload_csv/",
    tags=["Station Metadata Admin"],
    status_code=status.HTTP_200_OK,
)
async def upload_station_metadata_csv(
    session: Annotated[SQLModelSession, Depends(get_db_session)],
    current_user: Annotated[UserModel, Depends(get_current_admin_user)],
    file: UploadFile = File(...),
    season_year: Optional[int] = Query(None, description="Season year to assign stations to (None = active season)"),
):
    """
    Uploads a CSV file to bulk create or update station metadata.
    Requires admin privileges.
    The CSV must contain a 'station_id' column. Other columns matching the
    StationMetadata model are optional (e.g., serial_number, modem_address, etc.).
    """
    logger.info(
        f"ROUTER: User '{current_user.username}' attempting to upload station metadata CSV."
    )
    if not file.filename.endswith(".csv"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file type. Please upload a CSV file.",
        )

    contents = await file.read()
    try:
        # Use pandas to read the CSV from the in-memory bytes
        df = pd.read_csv(io.BytesIO(contents))
        # Standardize column names (lowercase, replace spaces with underscores)
        df.columns = df.columns.str.lower().str.replace(" ", "_")
    except Exception as e:
        logger.error(f"ROUTER: Error parsing CSV file: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error parsing CSV file: {e}",
        )

    required_columns = {"station_id"}
    if not required_columns.issubset(df.columns):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"CSV must contain the following columns: {', '.join(required_columns)}",
        )

    # --- NEW VALIDATION BLOCK ---
    # Ensure the station_id column does not contain any null/empty values
    if df['station_id'].isnull().any():
        # Find the row numbers (1-based index for user feedback) of the null entries
        null_rows = df[df['station_id'].isnull()].index + 2 # +1 for header, +1 for 0-based index
        error_detail = f"CSV contains rows with a missing station_id. This column cannot be empty. See row(s): {', '.join(map(str, null_rows))}"
        logger.error(f"ROUTER: CSV Upload Failed - {error_detail}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_detail,
        )

    # Convert all station_ids to string to handle cases where they might be read as numbers, and strip whitespace
    df['station_id'] = df['station_id'].astype(str).str.strip()
    
    # Handle serial_number if present
    if 'serial_number' in df.columns:
        df['serial_number'] = df['serial_number'].astype(str).str.strip()
        # Replace empty strings with None
        df['serial_number'] = df['serial_number'].replace('', None)

    # Replace numpy NaNs and pandas <NA> with None for Pydantic compatibility
    df = df.replace({np.nan: None, pd.NA: None})

    # --- PASSIVE DUPLICATE CHECKS (warnings only, don't prevent upload) ---
    warnings = []
    
    # Check for duplicate station_ids within the CSV file itself
    if df['station_id'].duplicated().any():
        duplicated_ids = sorted(df[df['station_id'].duplicated()]['station_id'].unique().tolist())
        warnings.append({
            "type": "duplicate_station_id_in_csv",
            "message": f"Duplicate station_id values found within the uploaded CSV: {', '.join(duplicated_ids)}",
            "duplicates": duplicated_ids
        })
        logger.warning(f"CSV Upload: Duplicate station_ids within CSV: {duplicated_ids}")
    
    # Check for duplicate serial_numbers within the CSV file itself
    if 'serial_number' in df.columns and df['serial_number'].notna().any():
        serial_duplicates = df[df['serial_number'].duplicated() & df['serial_number'].notna()]['serial_number'].unique().tolist()
        if serial_duplicates:
            serial_duplicates = sorted([str(s) for s in serial_duplicates])
            warnings.append({
                "type": "duplicate_serial_number_in_csv",
                "message": f"Duplicate serial_number values found within the uploaded CSV: {', '.join(serial_duplicates)}",
                "duplicates": serial_duplicates
            })
            logger.warning(f"CSV Upload: Duplicate serial_numbers within CSV: {serial_duplicates}")
    
    # Check for station_ids that already exist in the database
    existing_station_ids = set()
    if not df.empty:
        existing_stations_stmt = select(models.StationMetadata.station_id).where(
            models.StationMetadata.station_id.in_(df['station_id'].unique().tolist())
        )
        existing_station_ids = {
            station_id for station_id in session.exec(existing_stations_stmt).all() if station_id
        }
        
        if existing_station_ids:
            existing_ids_list = sorted(list(existing_station_ids))
            warnings.append({
                "type": "duplicate_station_id_in_db",
                "message": f"Station IDs that already exist in database (will be updated): {', '.join(existing_ids_list)}",
                "duplicates": existing_ids_list
            })
            logger.info(f"CSV Upload: Station IDs that will be updated: {existing_ids_list}")
    
    # Check for serial_numbers that already exist in the database
    if 'serial_number' in df.columns and df['serial_number'].notna().any():
        serial_numbers_in_csv = df[df['serial_number'].notna()]['serial_number'].unique().tolist()
        if serial_numbers_in_csv:
            existing_serials_stmt = select(models.StationMetadata.serial_number).where(
                models.StationMetadata.serial_number.in_(serial_numbers_in_csv)
            )
            existing_serials = {
                serial_number
                for serial_number in session.exec(existing_serials_stmt).all()
                if serial_number
            }
            
            if existing_serials:
                existing_serials_list = sorted([str(s) for s in existing_serials])
                warnings.append({
                    "type": "duplicate_serial_number_in_db",
                    "message": f"Serial numbers that already exist in database: {', '.join(existing_serials_list)}",
                    "duplicates": existing_serials_list
                })
                logger.info(f"CSV Upload: Serial numbers that already exist: {existing_serials_list}")

    target_season_year = season_year
    if target_season_year is not None:
        specified_season = StationSeasonService.get_season_by_year(session, target_season_year)
        if not specified_season:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Season {target_season_year} does not exist. Please create it first or use an existing season.",
            )

    processed_count = 0
    errors = []
    for index, row in df.iterrows():
        try:
            row_dict = row.to_dict()
            row_dict = {k: v for k, v in row_dict.items() if v is not None}
            row_dict.pop("field_season_year", None)
            row_dict["is_archived"] = False
            row_dict["archived_at_utc"] = None

            station_data = models.StationMetadataCreate(**row_dict)
            existing_station = session.get(
                models.StationMetadata, station_data.station_id
            )

            if existing_station:
                if station_blocks_edits(existing_station):
                    raise ValueError(
                        f"Station {existing_station.station_id} is retired or archived; "
                        "re-activate or un-retire before CSV update."
                    )
                old_serial = existing_station.serial_number
                old_modem = existing_station.modem_address
                update_data = station_data.model_dump(exclude_unset=True)
                if "otn_metadata" in update_data:
                    update_data["notes"] = update_data.pop("otn_metadata")
                update_data.pop("field_season_year", None)
                update_data["is_archived"] = False
                update_data["archived_at_utc"] = None
                # Preserve user notes when CSV sends empty / whitespace only
                if "notes" in update_data:
                    new_notes = update_data["notes"]
                    if (
                        new_notes is None
                        or (isinstance(new_notes, str) and not str(new_notes).strip())
                    ) and existing_station.notes:
                        del update_data["notes"]
                for key, value in update_data.items():
                    setattr(existing_station, key, value)
                if old_serial != existing_station.serial_number or old_modem != existing_station.modem_address:
                    open_stmt = (
                        select(models.StationHardwareHistory)
                        .where(
                            models.StationHardwareHistory.station_id
                            == existing_station.station_id,
                            models.StationHardwareHistory.effective_end_utc.is_(None),
                        )
                        .order_by(models.StationHardwareHistory.effective_start_utc.desc())
                    )
                    open_segment = session.exec(open_stmt).first()
                    now_utc = datetime.now(timezone.utc)
                    if open_segment:
                        open_segment.effective_end_utc = now_utc
                        session.add(open_segment)
                    session.add(
                        models.StationHardwareHistory(
                            station_id=existing_station.station_id,
                            serial_number=existing_station.serial_number,
                            modem_address=existing_station.modem_address,
                            effective_start_utc=now_utc,
                            changed_by_username=current_user.username,
                            change_source="user",
                            change_note="Updated via station CSV upload",
                        )
                    )
                    warnings.append(
                        {
                            "type": "csv_hardware_change",
                            "message": (
                                f"Station {existing_station.station_id}: serial/modem changed via CSV upload "
                                f"(previous serial={old_serial!r}, modem={old_modem!r})"
                            ),
                        }
                    )
                session.add(existing_station)
            else:
                station_metadata_crud.create_or_update_station(
                    session=session,
                    station_data=station_data,
                    commit=False,
                )
            processed_count += 1
        except Exception as e:
            error_detail = f"Row {index + 2}: {e}"
            logger.error(f"ROUTER: CSV Upload - {error_detail}")
            errors.append(error_detail)

    season_info = (
        f" (season {target_season_year} validated)"
        if target_season_year
        else " (registry sync)"
    )
    if errors:
        session.rollback()
        response_content = {
            "message": f"No stations were saved ({len(errors)} row error(s); entire upload rolled back).",
            "errors": errors,
        }
        if warnings:
            response_content["warnings"] = warnings
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=response_content,
        )

    session.commit()

    response_content = {
        "message": f"Successfully created or updated {processed_count} stations from {file.filename}{season_info}.",
    }

    if warnings:
        response_content["warnings"] = warnings
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=response_content,
        )

    return response_content


@router.put(
    "/station_metadata/{station_id}",
    response_model=models.StationMetadataRead,
    tags=["Station Offload Management"],
)
async def update_station_metadata_fields(
    station_id: str,
    station_update_data: models.StationMetadataUpdate,
    session: Annotated[SQLModelSession, Depends(get_db_session)],
    # Any authenticated user can update
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
):
    logger.info(
        f"ROUTER: User '{current_user.username}' attempting to update station "
        f"fields for: {station_id}"
    )
    db_station_metadata = session.get(models.StationMetadata, station_id)
    if not db_station_metadata:
        logger.warning(f"ROUTER: Station with ID '{station_id}' not found for update.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Station metadata not found"
        )

    if station_blocks_edits(db_station_metadata):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Station {station_id} is retired or archived and cannot be modified",
        )

    update_data = station_update_data.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No update data provided"
        )
    if "otn_metadata" in update_data:
        update_data["notes"] = update_data.pop("otn_metadata")

    old_serial = db_station_metadata.serial_number
    old_modem = db_station_metadata.modem_address

    for key, value in update_data.items():
        setattr(db_station_metadata, key, value)

    session.add(db_station_metadata)
    if (
        old_serial != db_station_metadata.serial_number
        or old_modem != db_station_metadata.modem_address
    ):
        # Close previous open hardware segment for this station.
        open_stmt = (
            select(models.StationHardwareHistory)
            .where(
                models.StationHardwareHistory.station_id == station_id,
                models.StationHardwareHistory.effective_end_utc.is_(None),
            )
            .order_by(models.StationHardwareHistory.effective_start_utc.desc())
        )
        open_segment = session.exec(open_stmt).first()
        now_utc = datetime.now(timezone.utc)
        if open_segment:
            open_segment.effective_end_utc = now_utc
            session.add(open_segment)
        session.add(
            models.StationHardwareHistory(
                station_id=station_id,
                serial_number=db_station_metadata.serial_number,
                modem_address=db_station_metadata.modem_address,
                effective_start_utc=now_utc,
                changed_by_username=current_user.username,
                change_source="user",
                change_note="Updated via station metadata edit",
            )
        )
    session.commit()
    session.refresh(db_station_metadata)
    logger.info(
        f"ROUTER: Station '{station_id}' fields updated by user "
        f"'{current_user.username}'."
    )
    return db_station_metadata


@router.post(
    "/station_metadata/{station_id}/flag",
    response_model=Dict[str, Any],
    tags=["Station Offload Management"],
)
async def upsert_station_flag_for_season(
    station_id: str,
    body: models.StationFlagUpdateRequest,
    session: Annotated[SQLModelSession, Depends(get_db_session)],
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
):
    station = session.get(models.StationMetadata, station_id)
    if not station:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Station metadata not found",
        )
    if station_blocks_edits(station):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Station {station_id} is retired or archived and cannot be modified",
        )

    target_year = body.season_year
    if target_year is None:
        active = StationSeasonService.get_active_season(session)
        target_year = active.year if active else None
    elif not StationSeasonService.get_season_by_year(session, target_year):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Field season {target_year} not found",
        )

    all_events = list(
        session.exec(
            select(models.StationFlagEvent).where(
                models.StationFlagEvent.station_id == station_id
            )
        ).all()
    )
    season_row = (
        StationSeasonService.get_season_by_year(session, target_year)
        if target_year is not None
        else None
    )
    season_is_closed = bool(season_row and season_row.closed_at_utc) or (
        season_row is None and target_year is not None
    )
    scoped_state = _resolve_station_flag_state(
        all_events,
        target_year=target_year,
        season_is_closed=season_is_closed,
    )
    is_currently_flagged = bool(scoped_state.get(station_id, {}).get("is_flagged"))
    if body.is_flagged == is_currently_flagged:
        return {
            "created": False,
            "message": "No flag state change for this season context",
            "station_id": station_id,
            "field_season_year": target_year,
        }

    flag_event = models.StationFlagEvent(
        station_id=station_id,
        field_season_year=target_year,
        is_flagged=body.is_flagged,
        note=(body.note or "").strip() or None,
        changed_by_username=current_user.username,
        changed_at_utc=datetime.now(timezone.utc),
    )
    session.add(flag_event)
    session.commit()
    session.refresh(flag_event)
    return {
        "created": True,
        "message": "Season flag updated",
        "station_id": station_id,
        "field_season_year": target_year,
        "flag_event_id": flag_event.id,
    }


@router.get(
    "/station_metadata/{station_id}/flag_state",
    response_model=Dict[str, Any],
    tags=["Station Offload Management"],
)
async def get_station_flag_state_for_season(
    station_id: str,
    session: Annotated[SQLModelSession, Depends(get_db_session)],
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
    season_year: Optional[int] = Query(
        None, description="Season context for flag lookup (None = active season context)"
    ),
):
    station = session.get(models.StationMetadata, station_id)
    if not station:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Station metadata not found",
        )
    if season_year is None:
        active = StationSeasonService.get_active_season(session)
        target_year = active.year if active else None
        season_is_closed = False
    else:
        target_year = season_year
        season_row = StationSeasonService.get_season_by_year(session, season_year)
        season_is_closed = bool(season_row and season_row.closed_at_utc) or (season_row is None)
    all_events = list(
        session.exec(
            select(models.StationFlagEvent).where(
                models.StationFlagEvent.station_id == station_id
            )
        ).all()
    )
    state_by_station = _resolve_station_flag_state(
        all_events,
        target_year=target_year,
        season_is_closed=season_is_closed,
    )
    state = state_by_station.get(station_id, {})
    return {
        "station_id": station_id,
        "field_season_year": target_year,
        "is_flagged": bool(state.get("is_flagged")),
        "note": state.get("flag_note"),
        "changed_at_utc": state.get("changed_at_utc"),
    }


@router.post(
    "/stations/{station_id}/swap_hardware",
    response_model=models.StationMetadataRead,
    tags=["Station Offload Management"],
)
async def swap_station_hardware(
    station_id: str,
    body: models.StationHardwareSwapRequest,
    session: Annotated[SQLModelSession, Depends(get_db_session)],
    current_user: Annotated[UserModel, Depends(get_current_admin_user)],
):
    """Record a deliberate serial/modem change with hardware history (admin only)."""
    db_station = session.get(models.StationMetadata, station_id)
    if not db_station:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Station metadata not found",
        )
    if station_blocks_edits(db_station):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Station {station_id} is retired or archived",
        )
    payload = body.model_dump(exclude_unset=True)
    if "serial_number" not in payload and "modem_address" not in payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide at least one of serial_number or modem_address",
        )
    old_serial = db_station.serial_number
    old_modem = db_station.modem_address
    if "serial_number" in payload:
        db_station.serial_number = payload["serial_number"]
    if "modem_address" in payload:
        db_station.modem_address = payload["modem_address"]
    if old_serial == db_station.serial_number and old_modem == db_station.modem_address:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No hardware change compared to current values",
        )
    note = payload.get("change_note") or "Hardware swap (admin)"
    open_stmt = (
        select(models.StationHardwareHistory)
        .where(
            models.StationHardwareHistory.station_id == station_id,
            models.StationHardwareHistory.effective_end_utc.is_(None),
        )
        .order_by(models.StationHardwareHistory.effective_start_utc.desc())
    )
    open_segment = session.exec(open_stmt).first()
    now_utc = datetime.now(timezone.utc)
    if open_segment:
        open_segment.effective_end_utc = now_utc
        session.add(open_segment)
    session.add(
        models.StationHardwareHistory(
            station_id=station_id,
            serial_number=db_station.serial_number,
            modem_address=db_station.modem_address,
            effective_start_utc=now_utc,
            changed_by_username=current_user.username,
            change_source="user",
            change_note=note,
        )
    )
    session.add(db_station)
    session.commit()
    session.refresh(db_station)
    return db_station


# logger.debug("station_metadata_router.py - Defining GET /station_metadata/ (on router)") # Changed to logger
@router.get(
    "/station_metadata/",
    response_model=List[models.StationMetadataRead],
    tags=["Station Metadata"],
)
async def search_station_metadata_on_router(
    query: Optional[str] = Query(
        None, description="Search query for station_id (substring match)"
    ),
    limit: int = Query(
        10, gt=0, le=100, description="Maximum number of stations to return"
    ),
    session: SQLModelSession = Depends(get_db_session),
    current_user: UserModel = Depends(get_current_active_user),
):
    logger.info(
        f"ROUTER: User '{current_user.username}' searching station metadata "
        f"with query: '{query}', limit: {limit}"
    )

    statement = select(models.StationMetadata)
    if query:
        # Assuming station_id is the primary field to search.
        # For SQLModel, if models.StationMetadata.station_id is a Column, .contains() works.
        # Ensure the column type supports contains, or use .ilike for case-insensitive partial string match
        statement = statement.where(
            models.StationMetadata.station_id.ilike(f"%{query}%")
        )

    statement = statement.order_by(models.StationMetadata.station_id).limit(
        limit
    )  # Added order_by for consistent results
    stations = session.exec(statement).all()

    logger.info(f"ROUTER: Found {len(stations)} stations matching query.")
    return stations


# logger.debug("station_metadata_router.py - Defining DELETE /station_metadata/{station_id} (on router)") # Changed to logger
@router.delete(
    "/station_metadata/{station_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Station Metadata Admin"],
)
async def delete_station_metadata_on_router(
    station_id: str,
    session: Annotated[SQLModelSession, Depends(get_db_session)],
    current_user: Annotated[UserModel, Depends(get_current_admin_user)],
):
    logger.info(
        f"ROUTER: User '{current_user.username}' attempting to delete station: "
        f"{station_id}"
    )

    db_station = session.get(models.StationMetadata, station_id)
    if not db_station:
        logger.warning(f"ROUTER: Station with ID '{station_id}' not found for deletion.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Station not found"
        )

    session.delete(db_station)
    session.commit()
    logger.info(f"ROUTER: Station '{station_id}' deleted by user '{current_user.username}'.")
    return


# logger.debug("station_metadata_router.py - DELETE /station_metadata/{station_id} definition processed.") # Changed to logger
# logger.debug("station_metadata_router.py - GET /station_metadata/ definition processed.") # Changed to logger


@router.post(
    "/station_metadata/{station_id}/offload_logs/",
    response_model=models.OffloadLogRead,
    status_code=status.HTTP_201_CREATED,
    tags=["Station Offload Management"],
)
async def create_offload_log_for_station(
    station_id: str,
    offload_log_in: models.OffloadLogCreate,
    session: Annotated[SQLModelSession, Depends(get_db_session)],
    # Any authenticated user can log
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
):
    logger.info(
        f"ROUTER: User '{current_user.username}' logging offload for station: "
        f"{station_id}"
    )
    db_station_metadata = session.get(models.StationMetadata, station_id)
    if not db_station_metadata:
        logger.warning(
            f"ROUTER: Station metadata not found for ID '{station_id}' when logging offload."
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Station metadata not found for logging offload",
        )

    if station_blocks_edits(db_station_metadata):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Station {station_id} is retired or archived and cannot be modified",
        )

    # Get active season to set field_season_year
    active_season = StationSeasonService.get_active_season(session)
    field_season_year = active_season.year if active_season else None

    offload_log_data = offload_log_in.model_dump()
    offload_log_data["logged_by_username"] = current_user.username
    offload_log_data["station_id"] = station_id
    offload_log_data["field_season_year"] = field_season_year
    offload_log_data["created_by_source"] = "user"
    offload_log_data["updated_by_source"] = "user"
    offload_log_data["updated_at_utc"] = datetime.now(timezone.utc)

    db_offload_log = models.OffloadLog.model_validate(offload_log_data)
    session.add(db_offload_log)

    # Update parent StationMetadata with latest offload info
    if db_offload_log.offload_end_time_utc:
        db_station_metadata.last_offload_timestamp_utc = (
            db_offload_log.offload_end_time_utc
        )
    elif (
        db_offload_log.log_timestamp_utc
    ):  # Fallback if end time not provided but log is made
        db_station_metadata.last_offload_timestamp_utc = (
            db_offload_log.log_timestamp_utc
        )

    if db_offload_log.was_offloaded is not None:
        db_station_metadata.was_last_offload_successful = db_offload_log.was_offloaded

    session.add(db_station_metadata)  # Add again to save changes to station metadata

    session.commit()
    session.refresh(db_offload_log)
    # session.refresh(db_station_metadata) # Optional: refresh station if its updated state is immediately needed by caller
    logger.info(
        f"ROUTER: Offload logged for station '{station_id}' by user "
        f"'{current_user.username}'. Log ID: {db_offload_log.id}"
    )
    return db_offload_log


@router.put(
    "/station_metadata/{station_id}/offload_logs/{log_id}",
    response_model=models.OffloadLogRead,
    tags=["Station Offload Management"],
)
async def update_offload_log_for_station(
    station_id: str,
    log_id: int,
    offload_update: models.OffloadLogUpdate,
    session: Annotated[SQLModelSession, Depends(get_db_session)],
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
):
    logger.info(
        f"ROUTER: User '{current_user.username}' updating offload log {log_id} "
        f"for station '{station_id}'."
    )
    db_station = session.get(models.StationMetadata, station_id)
    if not db_station:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Station metadata not found",
        )
    if station_blocks_edits(db_station):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Station {station_id} is retired or archived and cannot be modified",
        )

    db_log = session.get(models.OffloadLog, log_id)
    if not db_log or db_log.station_id != station_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Offload log not found for this station",
        )

    update_data = offload_update.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No update data provided",
        )

    for key, value in update_data.items():
        setattr(db_log, key, value)

    db_log.updated_by_source = "user"
    db_log.updated_at_utc = datetime.now(timezone.utc)
    session.add(db_log)
    _refresh_station_last_offload_from_all_logs(session, station_id)
    session.commit()
    session.refresh(db_log)
    logger.info(
        f"ROUTER: Offload log {log_id} updated for station '{station_id}'."
    )
    return db_log


@router.delete(
    "/station_metadata/{station_id}/offload_logs/{log_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Station Offload Management"],
)
async def delete_offload_log_for_station(
    station_id: str,
    log_id: int,
    session: Annotated[SQLModelSession, Depends(get_db_session)],
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
):
    db_station = session.get(models.StationMetadata, station_id)
    if not db_station:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Station metadata not found",
        )
    if station_blocks_edits(db_station):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Station {station_id} is retired or archived and cannot be modified",
        )
    db_log = session.get(models.OffloadLog, log_id)
    if not db_log or db_log.station_id != station_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Offload log not found for this station",
        )
    is_admin = current_user.role == models.UserRoleEnum.admin
    is_owner = db_log.logged_by_username == current_user.username
    if not (is_admin or is_owner):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only delete your own log unless you are an admin.",
        )

    session.delete(db_log)
    _refresh_station_last_offload_from_all_logs(session, station_id)
    session.commit()
    return


@router.get(
    "/stations/status_overview",
    response_model=List[Dict[str, Any]],
    tags=["Station Status Overview"],
)  # Using Dict for augmented response
async def get_station_offload_status_overview(
    session: Annotated[SQLModelSession, Depends(get_db_session)],
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
    season_year: Optional[int] = Query(
        None,
        description="Season tag for offload logs (None = active season context). Registry rows are always live.",
    ),
):
    logger.info(
        f"User '{current_user.username}' requesting station offload status overview"
        f"{f' for season {season_year}' if season_year else ' (active season)'}."
    )

    statement = (
        select(models.StationMetadata)
        .options(selectinload(models.StationMetadata.offload_logs))
        .where(
            models.StationMetadata.is_retired == False,
            models.StationMetadata.is_archived == False,
        )
        .order_by(models.StationMetadata.station_id)
    )
    stations_metadata = list(session.exec(statement).all())

    if season_year is None:
        active = StationSeasonService.get_active_season(session)
        target_year: Optional[int] = active.year if active else None
        season_is_closed = False
    else:
        target_year = season_year
        season_row = StationSeasonService.get_season_by_year(session, season_year)
        season_is_closed = bool(season_row and season_row.closed_at_utc) or (
            season_row is None
        )

    all_flag_events = list(session.exec(select(models.StationFlagEvent)).all())
    flag_state_by_station = _resolve_station_flag_state(
        all_flag_events,
        target_year=target_year,
        season_is_closed=season_is_closed,
    )

    overview_list: List[Dict[str, Any]] = []
    for station in stations_metadata:
        if season_year is None:
            if target_year is None:
                relevant_logs = [
                    log
                    for log in station.offload_logs
                    if log.field_season_year is None
                ]
            else:
                relevant_logs = [
                    log
                    for log in station.offload_logs
                    if offload_log_matches_season_year(
                        log_season=log.field_season_year,
                        target_year=target_year,
                        season_is_closed=False,
                    )
                ]
        else:
            relevant_logs = [
                log
                for log in station.offload_logs
                if target_year is not None
                and offload_log_matches_season_year(
                    log_season=log.field_season_year,
                    target_year=target_year,
                    season_is_closed=season_is_closed,
                )
            ]
        flag_state = flag_state_by_station.get(station.station_id, {})
        overview_list.append(
            build_status_overview_row(
                station,
                relevant_logs,
                is_flagged_for_scope=bool(flag_state.get("is_flagged")),
                flag_note=flag_state.get("flag_note"),
            )
        )

    logger.info(
        f"Built status overview for {len(stations_metadata)} registry stations "
        f"(season context={season_year!r})."
    )
    return overview_list


# ============================================================================
# Station array groups (HFX, NCAT, shared notes)
# ============================================================================


@router.get(
    "/station_array_groups/",
    response_model=List[models.StationArrayGroupRead],
    tags=["Station Array Groups"],
)
async def list_station_array_groups(
    session: Annotated[SQLModelSession, Depends(get_db_session)],
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
):
    statement = select(models.StationArrayGroup).order_by(
        models.StationArrayGroup.sort_order,
        models.StationArrayGroup.code,
    )
    rows = list(session.exec(statement).all())
    return [
        models.StationArrayGroupRead(
            id=r.id,
            code=r.code,
            display_name=r.display_name,
            notes=r.notes,
            sort_order=r.sort_order,
            updated_at_utc=r.updated_at_utc,
        )
        for r in rows
    ]


@router.put(
    "/station_array_groups/{code}",
    response_model=models.StationArrayGroupRead,
    tags=["Station Array Groups"],
)
async def update_station_array_group(
    code: str,
    body: models.StationArrayGroupUpdate,
    session: Annotated[SQLModelSession, Depends(get_db_session)],
    current_user: Annotated[UserModel, Depends(get_current_admin_user)],
):
    code_key = code.strip().upper()
    statement = select(models.StationArrayGroup).where(
        models.StationArrayGroup.code == code_key
    )
    row = session.exec(statement).first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Array group '{code_key}' not found",
        )
    update_data = body.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No update fields provided",
        )
    for key, value in update_data.items():
        setattr(row, key, value)
    row.updated_at_utc = datetime.now(timezone.utc)
    session.add(row)
    session.commit()
    session.refresh(row)
    return models.StationArrayGroupRead(
        id=row.id,
        code=row.code,
        display_name=row.display_name,
        notes=row.notes,
        sort_order=row.sort_order,
        updated_at_utc=row.updated_at_utc,
    )


# ============================================================================
# Station/array history and analytics endpoints
# ============================================================================


@router.get(
    "/stations/{station_id}/history",
    tags=["Station History"],
)
async def get_station_history(
    station_id: str,
    session: Annotated[SQLModelSession, Depends(get_db_session)],
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
    season_year: Optional[int] = Query(
        None,
        description="If set, only offload logs for this season included in stats/timeline",
    ),
):
    station = session.get(models.StationMetadata, station_id)
    if not station:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Station {station_id} not found",
        )
    log_stmt = select(models.OffloadLog).where(
        models.OffloadLog.station_id == station_id
    )
    all_logs = list(session.exec(log_stmt).all())
    logs_for_scope = all_logs
    if season_year is not None:
        logs_for_scope = [l for l in all_logs if l.field_season_year == season_year]
    flag_stmt = select(models.StationFlagEvent).where(
        models.StationFlagEvent.station_id == station_id
    )
    all_flag_events = list(session.exec(flag_stmt).all())
    flag_events_for_scope = all_flag_events
    if season_year is not None:
        season_row = StationSeasonService.get_season_by_year(session, season_year)
        season_is_closed = bool(season_row and season_row.closed_at_utc) or (
            season_row is None
        )
        flag_events_for_scope = [
            e
            for e in all_flag_events
            if offload_log_matches_season_year(
                log_season=e.field_season_year,
                target_year=season_year,
                season_is_closed=season_is_closed,
            )
        ]
    hw_stmt = (
        select(models.StationHardwareHistory)
        .where(models.StationHardwareHistory.station_id == station_id)
        .order_by(models.StationHardwareHistory.effective_start_utc.desc())
    )
    hardware = list(session.exec(hw_stmt).all())
    snap_stmt = (
        select(models.StationMetadataSeasonSnapshot)
        .where(models.StationMetadataSeasonSnapshot.station_id == station_id)
        .order_by(models.StationMetadataSeasonSnapshot.field_season_year.desc())
    )
    snapshots = list(session.exec(snap_stmt).all())
    timeline = build_station_timeline(
        logs_for_scope, hardware, snapshots, flag_events_for_scope
    )
    stats = aggregate_offload_stats(logs_for_scope)
    return {
        "station_id": station_id,
        "season_filter": season_year,
        "station": station.model_dump(),
        "stats": stats,
        "timeline": timeline,
        "season_snapshots": [s.model_dump() for s in snapshots],
        "hardware_history": [h.model_dump() for h in hardware],
        "offload_logs": [l.model_dump() for l in all_logs],
        "flag_events": [e.model_dump() for e in all_flag_events],
    }


@router.get(
    "/arrays/{array_code}/history",
    tags=["Station History"],
)
async def get_array_history(
    array_code: str,
    session: Annotated[SQLModelSession, Depends(get_db_session)],
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
    season_year: Optional[int] = Query(None),
):
    code = array_code.upper()
    ag_stmt = select(models.StationArrayGroup).where(
        models.StationArrayGroup.code == code
    )
    array_group = session.exec(ag_stmt).first()
    stations_stmt = select(models.StationMetadata).where(
        models.StationMetadata.station_id.ilike(f"{code}%")
    )
    stations = list(session.exec(stations_stmt).all())
    station_ids = [s.station_id for s in stations]
    if not station_ids:
        return {
            "array_code": code,
            "array_group": (
                {
                    "code": array_group.code,
                    "display_name": array_group.display_name,
                    "notes": array_group.notes,
                }
                if array_group
                else None
            ),
            "stations": [],
            "station_summaries": [],
            "stations_by_status": {},
            "offload_logs": [],
            "hardware_history": [],
            "logs_by_season": {},
            "aggregate_stats": aggregate_offload_stats([]),
        }
    logs_stmt = select(models.OffloadLog).where(
        models.OffloadLog.station_id.in_(station_ids)
    )
    if season_year is not None:
        logs_stmt = logs_stmt.where(models.OffloadLog.field_season_year == season_year)
    logs_stmt = logs_stmt.order_by(models.OffloadLog.log_timestamp_utc.desc())
    hw_stmt = (
        select(models.StationHardwareHistory)
        .where(models.StationHardwareHistory.station_id.in_(station_ids))
        .order_by(models.StationHardwareHistory.effective_start_utc.desc())
    )
    logs = list(session.exec(logs_stmt).all())
    hardware = list(session.exec(hw_stmt).all())
    logs_by_station: Dict[str, List[Any]] = defaultdict(list)
    for log in logs:
        logs_by_station[log.station_id].append(log)
    summaries = [
        station_mini_summary(st, logs_by_station.get(st.station_id, []))
        for st in stations
    ]
    all_logs_unfiltered = list(
        session.exec(
            select(models.OffloadLog)
            .where(models.OffloadLog.station_id.in_(station_ids))
            .order_by(models.OffloadLog.log_timestamp_utc.desc())
        ).all()
    )
    return {
        "array_code": code,
        "array_group": (
            {
                "code": array_group.code,
                "display_name": array_group.display_name,
                "notes": array_group.notes,
            }
            if array_group
            else None
        ),
        "season_filter": season_year,
        "stations": [s.model_dump() for s in stations],
        "station_summaries": summaries,
        "stations_by_status": group_stations_by_status(summaries),
        "offload_logs": [l.model_dump() for l in logs],
        "hardware_history": [h.model_dump() for h in hardware],
        "logs_by_season": logs_by_season_counts(all_logs_unfiltered)
        if season_year is None
        else logs_by_season_counts(logs),
        "aggregate_stats": aggregate_offload_stats(logs),
    }


def _ensure_aware_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Normalize datetimes for comparison (DB may return naive UTC from SQLite)."""
    if dt is None:
        return None
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _log_activity_ts(log: models.OffloadLog, fallback: datetime) -> datetime:
    """Latest activity timestamp for analytics windows (log create or last update)."""
    for candidate in (log.log_timestamp_utc, log.updated_at_utc):
        t = _ensure_aware_utc(candidate)
        if t is not None:
            return t
    return fallback


def _station_id_array_prefix(station_id: str) -> str:
    i = 0
    while i < len(station_id) and station_id[i].isalpha():
        i += 1
    return station_id[:i].upper() if i else station_id.upper()


def _format_duration_hhmm(total_seconds: Optional[float]) -> Optional[str]:
    if total_seconds is None:
        return None
    if total_seconds < 0:
        return None
    total_minutes = int(round(total_seconds / 60.0))
    hours = total_minutes // 60
    minutes = total_minutes % 60
    return f"{hours}:{minutes:02d}"


def _format_duration_hhmmss(total_seconds: Optional[float]) -> Optional[str]:
    if total_seconds is None:
        return None
    if total_seconds < 0:
        return None
    total_seconds_int = int(round(total_seconds))
    hours = total_seconds_int // 3600
    minutes = (total_seconds_int % 3600) // 60
    seconds = total_seconds_int % 60
    return f"{hours}:{minutes:02d}:{seconds:02d}"


def _mission_key_from_log(log: models.OffloadLog) -> str:
    parser_run_id = (getattr(log, "parser_run_id", None) or "").strip()
    if parser_run_id:
        return parser_run_id.split(":", 1)[0] if ":" in parser_run_id else parser_run_id

    parser_session_ref = (getattr(log, "parser_session_ref", None) or "").strip()
    if parser_session_ref:
        return parser_session_ref.split(":", 1)[0] if ":" in parser_session_ref else parser_session_ref
    return "unknown"


def _is_log_touched_by_parser(log: models.OffloadLog) -> bool:
    if getattr(log, "created_by_source", "user") == "parser":
        return True
    if getattr(log, "updated_by_source", None) == "parser":
        return True
    if getattr(log, "parser_run_id", None):
        return True
    if getattr(log, "parser_session_ref", None):
        return True
    if getattr(log, "parser_notes", None):
        return True
    # Retroactive enrichment runs may not stamp parser source fields;
    # infer parser touch from enriched payload presence.
    if _has_remote_health_payload(log):
        return True
    if bool(getattr(log, "vrl_file_name", None)):
        return True
    return False


def _has_remote_health_payload(log: models.OffloadLog) -> bool:
    return any(
        getattr(log, field_name, None) is not None
        for field_name in (
            "remote_health_model_id",
            "remote_health_serial_number",
            "remote_health_modem_address",
            "remote_health_temperature_c",
            "remote_health_tilt_rad",
            "remote_health_humidity",
            "remote_health_report_date",
        )
    )


@router.get(
    "/stations/analytics/overview",
    tags=["Station History"],
)
async def get_station_analytics_overview(
    session: Annotated[SQLModelSession, Depends(get_db_session)],
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
    season_year: Optional[int] = Query(
        None,
        description="Season filter for analytics (None = active season context)",
    ),
):
    if season_year is None:
        active = StationSeasonService.get_active_season(session)
        target_year: Optional[int] = active.year if active else None
        season_is_closed = False
    else:
        target_year = season_year
        season_row = StationSeasonService.get_season_by_year(session, season_year)
        season_is_closed = bool(season_row and season_row.closed_at_utc) or (season_row is None)

    all_logs = list(session.exec(select(models.OffloadLog)).all())
    logs: List[models.OffloadLog] = []
    for log in all_logs:
        if target_year is None:
            if log.field_season_year is None:
                logs.append(log)
            continue
        if log.field_season_year == target_year:
            logs.append(log)

    now_utc = datetime.now(timezone.utc)
    daily_cutoff = now_utc - timedelta(hours=24)
    last_48h_cutoff = now_utc - timedelta(hours=48)
    last_30d_cutoff = now_utc - timedelta(days=30)
    total_logs = len(logs)
    user_logs = sum(
        1 for l in logs if getattr(l, "created_by_source", "user") == "user"
    )
    parser_logs = sum(
        1 for l in logs if getattr(l, "created_by_source", "user") == "parser"
    )
    successful = sum(1 for l in logs if l.was_offloaded is True)
    failed = sum(1 for l in logs if l.was_offloaded is False)
    unresolved = sum(
        1
        for l in logs
        if (getattr(l, "parser_notes", None) and not getattr(l, "user_notes", None))
    )
    conflict_logs_pending = sum(
        1
        for l in logs
        if getattr(l, "parser_notes", None)
        and "[CONFLICT" in l.parser_notes
    )
    daily_logs = [
        l for l in logs if _log_activity_ts(l, now_utc) >= daily_cutoff
    ]
    daily_successful = sum(1 for l in daily_logs if l.was_offloaded is True)
    daily_failed = sum(1 for l in daily_logs if l.was_offloaded is False)
    recent_offloaded_logs = []
    for log in logs:
        if log.was_offloaded is not True:
            continue
        ts = _ensure_aware_utc(
            log.offload_end_time_utc
            or log.offload_start_time_utc
            or log.log_timestamp_utc
        )
        if ts is not None and ts >= last_48h_cutoff:
            recent_offloaded_logs.append((ts, log))
    recent_offloaded_logs.sort(key=lambda x: x[0], reverse=True)
    seen_stations = set()
    recent_offloaded_stations = []
    for ts, log in recent_offloaded_logs:
        if log.station_id in seen_stations:
            continue
        seen_stations.add(log.station_id)
        recent_offloaded_stations.append(
            {
                "station_id": log.station_id,
                "timestamp_utc": ts,
                "vrl_file_name": log.vrl_file_name,
                "logged_by_username": log.logged_by_username,
                "source": getattr(log, "created_by_source", "user"),
            }
        )
    hw_changes = list(session.exec(select(models.StationHardwareHistory)).all())

    by_prefix: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {
            "logs": 0,
            "successful": 0,
            "failed": 0,
            "last_30d_logs": 0,
            "first_activity_utc": None,
            "last_activity_utc": None,
            "offload_duration_seconds_sum": 0.0,
            "offload_duration_count": 0,
        }
    )
    for log in logs:
        pref = _station_id_array_prefix(log.station_id)
        by_prefix[pref]["logs"] += 1
        if log.was_offloaded is True:
            by_prefix[pref]["successful"] += 1
        elif log.was_offloaded is False:
            by_prefix[pref]["failed"] += 1
        ts = _ensure_aware_utc(
            log.offload_end_time_utc
            or log.offload_start_time_utc
            or log.log_timestamp_utc
        )
        if ts is not None:
            first_ts = by_prefix[pref]["first_activity_utc"]
            last_ts = by_prefix[pref]["last_activity_utc"]
            if first_ts is None or ts < first_ts:
                by_prefix[pref]["first_activity_utc"] = ts
            if last_ts is None or ts > last_ts:
                by_prefix[pref]["last_activity_utc"] = ts
        if ts is not None and ts >= last_30d_cutoff:
            by_prefix[pref]["last_30d_logs"] += 1
        offload_start = _ensure_aware_utc(log.offload_start_time_utc)
        offload_end = _ensure_aware_utc(log.offload_end_time_utc)
        if offload_start is not None and offload_end is not None and offload_end >= offload_start:
            by_prefix[pref]["offload_duration_seconds_sum"] += (
                offload_end - offload_start
            ).total_seconds()
            by_prefix[pref]["offload_duration_count"] += 1

    live_stmt = select(models.StationMetadata).where(
        models.StationMetadata.is_retired == False,
        models.StationMetadata.is_archived == False,
    )
    live_stations = list(session.exec(live_stmt).all())

    latest_log_by_station: Dict[str, models.OffloadLog] = {}
    for log in logs:
        existing = latest_log_by_station.get(log.station_id)
        if existing is None:
            latest_log_by_station[log.station_id] = log
            continue
        existing_ts = _ensure_aware_utc(
            existing.offload_end_time_utc
            or existing.offload_start_time_utc
            or existing.log_timestamp_utc
        ) or datetime.min.replace(tzinfo=timezone.utc)
        candidate_ts = _ensure_aware_utc(
            log.offload_end_time_utc
            or log.offload_start_time_utc
            or log.log_timestamp_utc
        ) or datetime.min.replace(tzinfo=timezone.utc)
        if candidate_ts >= existing_ts:
            latest_log_by_station[log.station_id] = log

    live_by_prefix: Dict[str, Dict[str, int]] = defaultdict(
        lambda: {"total_stations": 0, "stations_offloaded": 0, "stations_failed": 0}
    )
    for station in live_stations:
        pref = _station_id_array_prefix(station.station_id)
        live_by_prefix[pref]["total_stations"] += 1
        latest_station_log = latest_log_by_station.get(station.station_id)
        if latest_station_log is None:
            continue
        if latest_station_log.was_offloaded is True:
            live_by_prefix[pref]["stations_offloaded"] += 1
        elif latest_station_log.was_offloaded is False:
            live_by_prefix[pref]["stations_failed"] += 1

    all_prefixes = set(by_prefix.keys()) | set(live_by_prefix.keys())
    by_prefix_out = {}
    for pref in sorted(all_prefixes):
        d = by_prefix.get(pref, {})
        live_counts = live_by_prefix.get(pref, {})
        total_logs_for_prefix = int(d.get("logs", 0))
        successful_logs_for_prefix = int(d.get("successful", 0))
        failed_logs_for_prefix = int(d.get("failed", 0))
        total_stations_for_prefix = int(live_counts.get("total_stations", 0))
        stations_offloaded = int(live_counts.get("stations_offloaded", 0))
        stations_failed = int(live_counts.get("stations_failed", 0))
        stations_attempted = stations_offloaded + stations_failed
        stations_remaining = max(0, total_stations_for_prefix - stations_attempted)
        first_activity_utc = d.get("first_activity_utc")
        last_activity_utc = d.get("last_activity_utc")
        elapsed_days = None
        if first_activity_utc is not None and last_activity_utc is not None:
            elapsed_days = max(
                (last_activity_utc - first_activity_utc).total_seconds() / 86400.0,
                1.0 / 24.0,
            )

        stations_passed_per_day = (
            stations_attempted / elapsed_days
            if elapsed_days and elapsed_days > 0
            else None
        )
        stations_offloaded_per_day = (
            stations_offloaded / elapsed_days
            if elapsed_days and elapsed_days > 0
            else None
        )
        days_required = (
            total_stations_for_prefix / stations_passed_per_day
            if stations_passed_per_day and stations_passed_per_day > 0
            else None
        )
        days_left = (
            stations_remaining / stations_passed_per_day
            if stations_passed_per_day and stations_passed_per_day > 0
            else None
        )
        avg_offload_seconds = None
        offload_duration_count = int(d.get("offload_duration_count", 0))
        if offload_duration_count > 0:
            avg_offload_seconds = float(d.get("offload_duration_seconds_sum", 0.0)) / float(
                offload_duration_count
            )

        by_prefix_out[pref] = {
            "logs": total_logs_for_prefix,
            "successful": successful_logs_for_prefix,
            "failed": failed_logs_for_prefix,
            "last_30d_logs": int(d.get("last_30d_logs", 0)),
            "success_rate_pct": (
                successful_logs_for_prefix / total_logs_for_prefix * 100.0
            )
            if total_logs_for_prefix
            else 0.0,
            "date_started_utc": first_activity_utc,
            "last_updated_utc": last_activity_utc,
            "total_time_days": elapsed_days,
            "total_stations": total_stations_for_prefix,
            "stations_attempted": stations_attempted,
            "stations_offloaded": stations_offloaded,
            "stations_not_offloaded": stations_failed,
            "stations_remaining": stations_remaining,
            "percent_complete": (
                stations_attempted / total_stations_for_prefix * 100.0
            )
            if total_stations_for_prefix
            else 0.0,
            "percent_success": (
                stations_offloaded / stations_attempted * 100.0
            )
            if stations_attempted
            else 0.0,
            "stations_passed_per_day": stations_passed_per_day,
            "stations_offloaded_per_day": stations_offloaded_per_day,
            "days_required": days_required,
            "days_left": days_left,
            "avg_offload_seconds": avg_offload_seconds,
            "avg_time_per_station_h_mm": _format_duration_hhmm(avg_offload_seconds),
            "avg_offload_time_hh_mm_ss": _format_duration_hhmmss(avg_offload_seconds),
        }

    log_counts_by_station = Counter(l.station_id for l in logs)
    most_active_stations = [
        {"station_id": sid, "log_count": c}
        for sid, c in log_counts_by_station.most_common(20)
        if c > 1
    ]
    parser_touched_logs = [log for log in logs if _is_log_touched_by_parser(log)]
    parser_vrl_appended_logs = sum(
        1 for log in parser_touched_logs if bool(getattr(log, "vrl_file_name", None))
    )
    parser_remote_health_appended_logs = sum(
        1 for log in parser_touched_logs if _has_remote_health_payload(log)
    )

    n_live = len(live_stations)
    n_offloaded_display = 0
    n_failed_display = 0
    for station in live_stations:
        latest_station_log = latest_log_by_station.get(station.station_id)
        if latest_station_log is None:
            continue
        if latest_station_log.was_offloaded is True:
            n_offloaded_display += 1
        elif latest_station_log.was_offloaded is False:
            n_failed_display += 1
    n_skipped = sum(
        1
        for s in live_stations
        if s.display_status_override
        and str(s.display_status_override).upper() == "SKIPPED"
    )
    n_awaiting = sum(
        1
        for s in live_stations
        if s.last_offload_timestamp_utc is None
        and not (
            s.display_status_override
            and str(s.display_status_override).upper() == "SKIPPED"
        )
    )

    return {
        "season_year": target_year,
        "total_logs": total_logs,
        "user_logs": user_logs,
        "parser_logs": parser_logs,
        "successful_logs": successful,
        "failed_logs": failed,
        "logs_with_parser_notes_without_user_notes": unresolved,
        "conflict_logs_pending": conflict_logs_pending,
        "hardware_change_events": len(hw_changes),
        "daily": {
            "total_logs": len(daily_logs),
            "successful_logs": daily_successful,
            "failed_logs": daily_failed,
        },
        "recent_offloaded_stations_48h": recent_offloaded_stations,
        "by_array_prefix": by_prefix_out,
        "most_active_stations": most_active_stations,
        "parser_append_summary": {
            "logs_touched_by_parser": len(parser_touched_logs),
            "vrl_appended_logs": parser_vrl_appended_logs,
            "remote_health_appended_logs": parser_remote_health_appended_logs,
            "both_vrl_and_remote_health_logs": sum(
                1
                for log in parser_touched_logs
                if bool(getattr(log, "vrl_file_name", None))
                and _has_remote_health_payload(log)
            ),
        },
        "live_season_station_counts": {
            "total_stations": n_live,
            "display_offloaded": n_offloaded_display,
            "display_failed_offload": n_failed_display,
            "display_skipped": n_skipped,
            "display_awaiting_or_other": max(
                0, n_live - n_offloaded_display - n_failed_display - n_skipped
            ),
            "awaiting_offload_estimate": n_awaiting,
        },
    }


@router.get(
    "/stations/conflict_queue",
    tags=["Station History"],
)
async def get_station_conflict_queue(
    session: Annotated[SQLModelSession, Depends(get_db_session)],
    current_user: Annotated[UserModel, Depends(get_current_admin_user)],
):
    """
    Admin-only conflict queue.
    Returns offload logs where parser captured mismatch/conflict notes.
    """
    logs_stmt = (
        select(models.OffloadLog)
        .where(
            models.OffloadLog.parser_notes.isnot(None),
            models.OffloadLog.parser_notes.ilike("%[CONFLICT%"),
        )
        .order_by(models.OffloadLog.updated_at_utc.desc(), models.OffloadLog.log_timestamp_utc.desc())
    )
    logs = list(session.exec(logs_stmt).all())
    items = []
    for log in logs:
        items.append(
            {
                "offload_log_id": log.id,
                "station_id": log.station_id,
                "log_timestamp_utc": log.log_timestamp_utc,
                "updated_at_utc": log.updated_at_utc,
                "parser_run_id": log.parser_run_id,
                "parser_session_ref": log.parser_session_ref,
                "parser_notes": log.parser_notes,
                "user_notes": log.user_notes,
                "was_offloaded": log.was_offloaded,
                "vrl_file_name": log.vrl_file_name,
            }
        )
    return {
        "count": len(items),
        "items": items,
    }


@router.post(
    "/stations/conflict_queue/{log_id}/resolve",
    response_model=models.OffloadLogRead,
    tags=["Station History"],
)
async def resolve_station_conflict(
    log_id: int,
    body: models.ConflictResolutionRequest,
    session: Annotated[SQLModelSession, Depends(get_db_session)],
    current_user: Annotated[UserModel, Depends(get_current_admin_user)],
):
    """
    Resolve a parser/user field conflict on an offload log (admin only).
    """
    log = session.get(models.OffloadLog, log_id)
    if not log:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Offload log not found",
        )
    st = session.get(models.StationMetadata, log.station_id)
    if st and station_blocks_edits(st):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Station {log.station_id} is retired or archived",
        )
    if not log.parser_notes or "[CONFLICT" not in log.parser_notes:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No pending conflict on this log",
        )

    action = body.resolution_action
    if action == "manual_merge":
        if not body.resolved_notes or not str(body.resolved_notes).strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="resolved_notes is required for manual_merge",
            )
        log.user_notes = body.resolved_notes.strip()

    if action == "accept_parser":
        detail = _last_conflict_detail_from_parser_notes(log.parser_notes)
        _apply_parser_values_from_conflict_detail(log, detail)

    log.parser_notes = _mark_conflict_resolved_in_parser_notes(
        log.parser_notes,
        current_user.username,
        action,
    )
    log.updated_by_source = "user"
    log.updated_at_utc = datetime.now(timezone.utc)
    session.add(log)
    _refresh_station_last_offload_from_all_logs(session, log.station_id)
    session.commit()
    session.refresh(log)
    logger.info(
        f"Conflict resolved on log {log_id} by {current_user.username} action={action}"
    )
    return log


# ============================================================================
# Field Season Management Endpoints
# ============================================================================

@router.get(
    "/field_seasons/",
    response_model=List[models.FieldSeasonRead],
    tags=["Field Season Management"],
)
async def list_field_seasons(
    session: Annotated[SQLModelSession, Depends(get_db_session)],
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
):
    """List all field seasons."""
    logger.info(f"User '{current_user.username}' listing field seasons.")
    seasons = StationSeasonService.get_all_seasons(session)
    return seasons


@router.get(
    "/field_seasons/active",
    response_model=models.FieldSeasonRead,
    tags=["Field Season Management"],
)
async def get_active_season(
    session: Annotated[SQLModelSession, Depends(get_db_session)],
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
):
    """Get the currently active field season."""
    logger.info(f"User '{current_user.username}' requesting active season.")
    season = StationSeasonService.get_active_season(session)
    if not season:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active season found",
        )
    return season


@router.post(
    "/field_seasons/",
    response_model=models.FieldSeasonRead,
    status_code=status.HTTP_201_CREATED,
    tags=["Field Season Management"],
)
async def create_field_season(
    season_data: models.FieldSeasonCreate,
    session: Annotated[SQLModelSession, Depends(get_db_session)],
    current_user: Annotated[UserModel, Depends(get_current_admin_user)],
):
    """Create a new field season (admin only)."""
    logger.info(
        f"Admin '{current_user.username}' creating field season for year {season_data.year}."
    )
    
    # Check if season already exists
    existing = StationSeasonService.get_season_by_year(session, season_data.year)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Season for year {season_data.year} already exists",
        )
    
    season = StationSeasonService.create_season(
        session, season_data.year, season_data.is_active
    )
    return season


@router.put(
    "/field_seasons/{year}",
    response_model=models.FieldSeasonRead,
    tags=["Field Season Management"],
)
async def update_field_season(
    year: int,
    season_update: models.FieldSeasonUpdate,
    session: Annotated[SQLModelSession, Depends(get_db_session)],
    current_user: Annotated[UserModel, Depends(get_current_admin_user)],
):
    """Update a field season (testing/admin only)."""
    logger.warning(
        f"TESTING: Admin '{current_user.username}' updating field season {year}."
    )
    
    season = StationSeasonService.get_season_by_year(session, year)
    if not season:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Season {year} not found",
        )
    
    update_data = season_update.model_dump(exclude_unset=True)
    
    # Handle is_active change - deactivate other seasons if setting this one as active
    if 'is_active' in update_data and update_data['is_active'] is True:
        existing_active = StationSeasonService.get_active_season(session)
        if existing_active and existing_active.year != year:
            existing_active.is_active = False
            session.add(existing_active)
            logger.warning(
                f"TESTING: Deactivating season {existing_active.year} to activate {year}"
            )
    
    for key, value in update_data.items():
        setattr(season, key, value)
    
    session.add(season)
    session.commit()
    session.refresh(season)
    
    logger.warning(
        f"TESTING: Season {year} updated by '{current_user.username}'."
    )
    return season


@router.post(
    "/field_seasons/{year}/set_active",
    response_model=models.FieldSeasonRead,
    tags=["Field Season Management"],
)
async def set_active_season(
    year: int,
    session: Annotated[SQLModelSession, Depends(get_db_session)],
    current_user: Annotated[UserModel, Depends(get_current_admin_user)],
):
    """Set a season as the active season (testing/admin only)."""
    logger.warning(
        f"TESTING: Admin '{current_user.username}' setting season {year} as active."
    )
    
    season = StationSeasonService.get_season_by_year(session, year)
    if not season:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Season {year} not found",
        )
    
    # Deactivate all other seasons
    all_seasons = StationSeasonService.get_all_seasons(session)
    for s in all_seasons:
        if s.year != year and s.is_active:
            s.is_active = False
            session.add(s)
    
    # Activate this season
    season.is_active = True
    if season.closed_at_utc:
        # Reopen if it was closed
        season.closed_at_utc = None
        season.closed_by_username = None
        logger.warning(f"TESTING: Reopening closed season {year}")
    
    session.add(season)
    session.commit()
    session.refresh(season)
    
    logger.warning(
        f"TESTING: Season {year} set as active by '{current_user.username}'."
    )
    return season


@router.delete(
    "/field_seasons/{year}",
    status_code=status.HTTP_200_OK,
    tags=["Field Season Management"],
)
async def delete_field_season(
    year: int,
    session: Annotated[SQLModelSession, Depends(get_db_session)],
    current_user: Annotated[UserModel, Depends(get_current_admin_user)],
    confirm: bool = Query(False, description="Must be True to confirm deletion"),
):
    """
    TESTING ONLY: Delete a field season.
    By default, this now purges associated season data for cleaner testing resets.
    """
    if not confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Must set confirm=true to delete a season. This is a destructive operation.",
        )
    
    logger.warning(
        f"TESTING: Admin '{current_user.username}' deleting field season {year}."
    )
    
    season = StationSeasonService.get_season_by_year(session, year)
    if not season:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Season {year} not found",
        )
    
    if season.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete the active season. Set another season as active first.",
        )
    
    from sqlmodel import delete

    # Purge season-tagged logs and audit snapshots only (registry rows are shared).
    delete_logs_stmt = delete(models.OffloadLog).where(
        models.OffloadLog.field_season_year == year
    )
    session.exec(delete_logs_stmt)

    delete_snapshots_stmt = delete(models.StationMetadataSeasonSnapshot).where(
        models.StationMetadataSeasonSnapshot.field_season_year == year
    )
    session.exec(delete_snapshots_stmt)

    session.delete(season)
    session.commit()
    
    logger.warning(
        f"TESTING: Season {year} and associated season data deleted by "
        f"'{current_user.username}'."
    )
    
    return {
        "message": (
            f"Season {year} deleted; offload logs and snapshots for that year "
            f"were purged. Station registry rows were not deleted."
        ),
        "warning": "This was a testing operation with destructive cleanup.",
    }


@router.post(
    "/field_seasons/{year}/close",
    response_model=models.FieldSeasonRead,
    tags=["Field Season Management"],
)
async def close_field_season(
    year: int,
    session: Annotated[SQLModelSession, Depends(get_db_session)],
    current_user: Annotated[UserModel, Depends(get_current_admin_user)],
):
    """Close a field season: snapshot registry, stamp logs, compute stats (admin only)."""
    logger.info(
        f"Admin '{current_user.username}' closing field season {year}."
    )
    
    try:
        season = StationSeasonService.close_season(
            session, year, current_user.username
        )
        return season
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post(
    "/field_seasons/{year}/reprocess_statistics",
    response_model=models.FieldSeasonRead,
    tags=["Field Season Management"],
)
async def reprocess_season_statistics(
    year: int,
    session: Annotated[SQLModelSession, Depends(get_db_session)],
    current_user: Annotated[UserModel, Depends(get_current_admin_user)],
):
    """Reprocess and save summary statistics for a closed season (admin only)."""
    logger.info(
        f"Admin '{current_user.username}' reprocessing statistics for closed season {year}."
    )
    try:
        season = StationSeasonService.reprocess_season_statistics(session, year)
        return season
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get(
    "/field_seasons/{year}/stations",
    response_model=List[models.StationMetadataRead],
    tags=["Field Season Management"],
)
async def get_stations_for_season(
    year: int,
    session: Annotated[SQLModelSession, Depends(get_db_session)],
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
):
    """Get all stations for a specific season."""
    logger.info(
        f"User '{current_user.username}' requesting stations for season {year}."
    )
    stations = StationSeasonService.get_stations_for_season(session, year)
    return stations


@router.get(
    "/field_seasons/{year}/offload_logs",
    response_model=List[models.OffloadLogRead],
    tags=["Field Season Management"],
)
async def get_offload_logs_for_season(
    year: int,
    session: Annotated[SQLModelSession, Depends(get_db_session)],
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
    station_type: Optional[str] = Query(None, description="Filter by station type prefix (e.g., CBS, NCAT)"),
):
    """Get all offload logs for a specific season, optionally filtered by station type."""
    logger.info(
        f"User '{current_user.username}' requesting offload logs for season {year}"
        f"{f' (filtered by {station_type})' if station_type else ''}."
    )
    logs = StationSeasonService.get_offload_logs_for_season(
        session, year, station_type
    )
    return logs


@router.get(
    "/field_seasons/{year}/summary",
    response_model=models.FieldSeasonSummary,
    tags=["Field Season Management"],
)
async def get_season_summary(
    year: int,
    session: Annotated[SQLModelSession, Depends(get_db_session)],
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
):
    """Get summary statistics for a specific season."""
    logger.info(
        f"User '{current_user.username}' requesting summary for season {year}."
    )
    statistics = StationSeasonService.calculate_season_statistics(session, year)
    return statistics


@router.get(
    "/field_seasons/{year}/download",
    tags=["Field Season Management"],
)
async def download_season_data(
    year: int,
    session: Annotated[SQLModelSession, Depends(get_db_session)],
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
    station_type: Optional[str] = Query(None, description="Filter by station type prefix (e.g., CBS, NCAT)"),
):
    """Download season offload data as CSV, optionally filtered by station type."""
    logger.info(
        f"User '{current_user.username}' downloading data for season {year}"
        f"{f' (filtered by {station_type})' if station_type else ''}."
    )
    
    # Get offload logs
    logs = StationSeasonService.get_offload_logs_for_season(
        session, year, station_type
    )
    
    # Get stations for context
    stations = StationSeasonService.get_stations_for_season(session, year)
    station_dict = {s.station_id: s for s in stations}
    
    # Build CSV data
    rows = []
    for log in logs:
        station = station_dict.get(log.station_id)
        row = {
            "Station ID": log.station_id,
            "Serial Number": station.serial_number if station else "---",
            "Modem Address": station.modem_address if station else "---",
            "RV WP #": station.waypoint_number if station else "---",
            "Logged By": log.logged_by_username,
            "Log Timestamp (UTC)": log.log_timestamp_utc.strftime("%Y-%m-%d %H:%M:%S UTC") if log.log_timestamp_utc else "---",
            "Arrival Date (UTC)": log.arrival_date.strftime("%Y-%m-%d %H:%M:%S UTC") if log.arrival_date else "---",
            "Distance Cmd Sent (m)": log.distance_command_sent_m if log.distance_command_sent_m is not None else "---",
            "Time First Cmd Sent (UTC)": log.time_first_command_sent_utc.strftime("%Y-%m-%d %H:%M:%S UTC") if log.time_first_command_sent_utc else "---",
            "Offload Start (UTC)": log.offload_start_time_utc.strftime("%Y-%m-%d %H:%M:%S UTC") if log.offload_start_time_utc else "---",
            "Offload End (UTC)": log.offload_end_time_utc.strftime("%Y-%m-%d %H:%M:%S UTC") if log.offload_end_time_utc else "---",
            "Departure Date (UTC)": log.departure_date.strftime("%Y-%m-%d %H:%M:%S UTC") if log.departure_date else "---",
            "Was Offloaded": "Yes" if log.was_offloaded is True else ("No" if log.was_offloaded is False else "---"),
            "VRL File Name": log.vrl_file_name if log.vrl_file_name else "---",
            "Offload Notes/File Size": log.offload_notes_file_size if log.offload_notes_file_size else "---",
            # VM4 Remote Health (captured at connection time)
            "Remote Health Model ID": log.remote_health_model_id if getattr(log, "remote_health_model_id", None) is not None else "---",
            "Remote Health Serial Number": log.remote_health_serial_number if getattr(log, "remote_health_serial_number", None) is not None else "---",
            "Remote Health Modem Address": log.remote_health_modem_address if getattr(log, "remote_health_modem_address", None) is not None else "---",
            "Remote Health Temperature (C)": log.remote_health_temperature_c if getattr(log, "remote_health_temperature_c", None) is not None else "---",
            "Remote Health Tilt (Rad)": log.remote_health_tilt_rad if getattr(log, "remote_health_tilt_rad", None) is not None else "---",
            "Remote Health Humidity": log.remote_health_humidity if getattr(log, "remote_health_humidity", None) is not None else "---",
            "Remote Health Report Date (UTC)": str(log.remote_health_report_date) if getattr(log, "remote_health_report_date", None) is not None else "---",
        }
        rows.append(row)
    
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No data found for season {year}{f' with station type {station_type}' if station_type else ''}",
        )
    
    # Create DataFrame and convert to CSV
    df = pd.DataFrame(rows)
    output = io.StringIO()
    df.to_csv(output, index=False)
    output.seek(0)
    
    filename = f"station_offloads_{year}"
    if station_type:
        filename += f"_{station_type.upper()}"
    filename += ".csv"
    
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get(
    "/field_seasons/{year}/master_list",
    response_model=List[models.MasterListExport],
    tags=["Field Season Management"],
)
async def get_master_list(
    year: int,
    session: Annotated[SQLModelSession, Depends(get_db_session)],
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
):
    """Export current live registry (non-retired) for CSV. Year in path is legacy only."""
    logger.info(
        f"User '{current_user.username}' requesting master list for season {year}."
    )
    master_list = StationSeasonService.prepare_master_list_for_next_season(
        session, year
    )
    return master_list


@router.get(
    "/field_seasons/{year}/master_list/export",
    tags=["Field Season Management"],
)
async def export_master_list(
    year: int,
    session: Annotated[SQLModelSession, Depends(get_db_session)],
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
):
    """Export master list as CSV for editing and re-upload."""
    logger.info(
        f"User '{current_user.username}' exporting master list for season {year}."
    )
    
    master_list = StationSeasonService.prepare_master_list_for_next_season(
        session, year
    )
    
    if not master_list:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No non-retired stations in the registry to export",
        )
    
    # Create DataFrame and convert to CSV
    df = pd.DataFrame(master_list)
    output = io.StringIO()
    df.to_csv(output, index=False)
    output.seek(0)
    
    filename = f"master_list_{year}.csv"
    
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post(
    "/field_seasons/{year}/master_list/import",
    tags=["Field Season Management"],
    status_code=status.HTTP_200_OK,
)
async def import_master_list(
    year: int,
    session: Annotated[SQLModelSession, Depends(get_db_session)],
    current_user: Annotated[UserModel, Depends(get_current_admin_user)],
    file: UploadFile = File(...),
):
    """Bulk upsert registry rows from CSV (admin only). Season record is created if missing."""
    logger.info(
        f"Admin '{current_user.username}' importing master list for season {year}."
    )
    
    if not file.filename.endswith(".csv"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file type. Please upload a CSV file.",
        )
    
    contents = await file.read()
    try:
        df = pd.read_csv(io.BytesIO(contents))
        df.columns = df.columns.str.lower().str.replace(" ", "_")
    except Exception as e:
        logger.error(f"Error parsing CSV file: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error parsing CSV file: {e}",
        )
    
    required_columns = {"station_id"}
    if not required_columns.issubset(df.columns):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"CSV must contain the following columns: {', '.join(required_columns)}",
        )
    
    # Ensure the station_id column does not contain any null/empty values
    if df['station_id'].isnull().any():
        null_rows = df[df['station_id'].isnull()].index + 2
        error_detail = f"CSV contains rows with a missing station_id. See row(s): {', '.join(map(str, null_rows))}"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_detail,
        )
    
    # Convert all station_ids to string and strip whitespace
    df['station_id'] = df['station_id'].astype(str).str.strip()
    
    # Handle serial_number if present
    if 'serial_number' in df.columns:
        df['serial_number'] = df['serial_number'].astype(str).str.strip()
        df['serial_number'] = df['serial_number'].replace('', None)
    
    # Replace numpy NaNs with None
    df = df.replace({np.nan: None, pd.NA: None})
    
    # --- PASSIVE DUPLICATE CHECKS (warnings only) ---
    warnings = []
    
    # Check for duplicate station_ids within the CSV
    if df['station_id'].duplicated().any():
        duplicated_ids = sorted(df[df['station_id'].duplicated()]['station_id'].unique().tolist())
        warnings.append({
            "type": "duplicate_station_id_in_csv",
            "message": f"Duplicate station_id values found within the uploaded CSV: {', '.join(duplicated_ids)}",
            "duplicates": duplicated_ids
        })
    
    # Check for duplicate serial_numbers within the CSV
    if 'serial_number' in df.columns and df['serial_number'].notna().any():
        serial_duplicates = df[df['serial_number'].duplicated() & df['serial_number'].notna()]['serial_number'].unique().tolist()
        if serial_duplicates:
            serial_duplicates = sorted([str(s) for s in serial_duplicates])
            warnings.append({
                "type": "duplicate_serial_number_in_csv",
                "message": f"Duplicate serial_number values found within the uploaded CSV: {', '.join(serial_duplicates)}",
                "duplicates": serial_duplicates
            })
    
    # Check for station_ids that already exist in the database
    existing_station_ids = set()
    if not df.empty:
        existing_stations_stmt = select(models.StationMetadata.station_id).where(
            models.StationMetadata.station_id.in_(df['station_id'].unique().tolist())
        )
        existing_station_ids = {s.station_id for s in session.exec(existing_stations_stmt).all()}
        
        if existing_station_ids:
            existing_ids_list = sorted(list(existing_station_ids))
            warnings.append({
                "type": "duplicate_station_id_in_db",
                "message": f"Station IDs that already exist in database (will be updated): {', '.join(existing_ids_list)}",
                "duplicates": existing_ids_list
            })
    
    # Check for serial_numbers that already exist in the database
    if 'serial_number' in df.columns and df['serial_number'].notna().any():
        serial_numbers_in_csv = df[df['serial_number'].notna()]['serial_number'].unique().tolist()
        if serial_numbers_in_csv:
            existing_serials_stmt = select(models.StationMetadata.serial_number).where(
                models.StationMetadata.serial_number.in_(serial_numbers_in_csv)
            )
            existing_serials = {s.serial_number for s in session.exec(existing_serials_stmt).all() if s.serial_number}
            
            if existing_serials:
                existing_serials_list = sorted([str(s) for s in existing_serials])
                warnings.append({
                    "type": "duplicate_serial_number_in_db",
                    "message": f"Serial numbers that already exist in database: {', '.join(existing_serials_list)}",
                    "duplicates": existing_serials_list
                })
    
    season = StationSeasonService.get_season_by_year(session, year)
    if not season:
        StationSeasonService.create_season(session, year, is_active=False)
    
    processed_count = 0
    errors = []
    for index, row in df.iterrows():
        try:
            row_dict = {k: v for k, v in row.to_dict().items() if v is not None}
            row_dict.pop("field_season_year", None)
            row_dict["is_archived"] = False
            row_dict["archived_at_utc"] = None
            row_dict.setdefault("is_retired", False)

            station_data = models.StationMetadataCreate(**row_dict)
            station_metadata_crud.create_or_update_station(
                session=session,
                station_data=station_data,
                commit=False,
            )
            processed_count += 1
        except Exception as e:
            error_detail = f"Row {index + 2}: {e}"
            logger.error(f"Master list import - {error_detail}")
            errors.append(error_detail)

    if errors:
        session.rollback()
        response_content = {
            "message": f"No stations were imported ({len(errors)} row error(s); entire import rolled back).",
            "errors": errors,
        }
        if warnings:
            response_content["warnings"] = warnings
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=response_content,
        )

    session.commit()

    response_content = {
        "message": f"Successfully imported {processed_count} stations from {file.filename} for season {year}.",
    }

    if warnings:
        response_content["warnings"] = warnings
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=response_content,
        )

    return response_content


@router.delete(
    "/stations/clear_all",
    tags=["Field Season Management"],
    status_code=status.HTTP_200_OK,
)
async def clear_all_stations_testing(
    session: Annotated[SQLModelSession, Depends(get_db_session)],
    current_user: Annotated[UserModel, Depends(get_current_admin_user)],
    confirm: bool = Query(False, description="Must be True to confirm deletion"),
):
    """
    TESTING ONLY: Clear all stations and offload logs without archiving.
    This is a destructive operation for testing purposes only.
    """
    if not confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Must set confirm=true to clear all data. This is a destructive operation.",
        )
    
    logger.warning(
        f"TESTING: Admin '{current_user.username}' clearing all stations and offload logs."
    )
    
    try:
        # Delete all station/offload/season-related data for clean testing reset.
        from sqlmodel import delete
        session.exec(delete(models.AnnouncementAcknowledgement))
        session.exec(
            delete(models.Announcement).where(
                models.Announcement.created_by_username == "wg_vm4_auto"
            )
        )
        session.exec(delete(models.OffloadLog))
        session.exec(delete(models.StationHardwareHistory))
        session.exec(delete(models.StationMetadataSeasonSnapshot))
        session.exec(delete(models.StationMetadata))
        session.exec(delete(models.FieldSeason))
        
        session.commit()
        
        logger.warning(
            f"TESTING: All stations and offload logs cleared by '{current_user.username}'."
        )
        
        return {
            "message": (
                "All season/station/offload testing data has been cleared "
                "(including snapshots and hardware history)."
            ),
            "warning": "All cleared data has been permanently deleted."
        }
    except Exception as e:
        session.rollback()
        logger.error(f"Error clearing stations: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error clearing data: {str(e)}",
        )


@router.post(
    "/missions/{mission_id}/process_vm4_offloads",
    tags=["Field Season Management"],
    status_code=status.HTTP_200_OK,
)
async def process_vm4_offloads_for_mission(
    mission_id: str,
    background_tasks: BackgroundTasks,
    session: Annotated[SQLModelSession, Depends(get_db_session)],
    current_user: Annotated[UserModel, Depends(get_current_admin_user)],
    force: bool = Query(False, description="Force processing even if mission is historical"),
    wait_for_completion: bool = Query(False, description="Run immediately and return stats instead of background queue"),
    field_season_year: Optional[int] = Query(
        None,
        description="Field season year assigned to new offload logs from VM4 (overrides active season default)",
    ),
):
    """
    TESTING: Manually trigger VM4 offload processing for a mission.
    This allows processing historical mission data for testing purposes.
    If field_season_year is specified, parsed offload logs use that season tag.
    """
    logger.warning(
        f"TESTING: Admin '{current_user.username}' triggering VM4 processing for mission {mission_id} "
        f"(force={force}, wait_for_completion={wait_for_completion})."
    )
    if not is_feature_enabled("vm4_offload_parser"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WG-VM4 offload parser is currently disabled by feature toggle",
        )
    
    from ..core.wg_vm4_station_service import run_vm4_background_pipeline

    async def _run_vm4_pipeline_job(job_mission_id: str, job_field_season_year: Optional[int], job_force_full_scan: bool) -> None:
        with SQLModelSession(sqlite_engine) as job_session:
            try:
                result = await run_vm4_background_pipeline(
                    session=job_session,
                    mission_id=job_mission_id,
                    field_season_year=job_field_season_year,
                    force_full_scan=job_force_full_scan,
                )
                logger.info("VM4 background job finished mission=%s result=%s", job_mission_id, result)
            except Exception as exc:
                job_session.rollback()
                logger.error("VM4 background job failed mission=%s error=%s", job_mission_id, exc)

    try:
        if field_season_year is not None:
            season = StationSeasonService.get_season_by_year(session, field_season_year)
            if not season:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Field season {field_season_year} not found",
                )
        if wait_for_completion:
            result = await run_vm4_background_pipeline(
                session=session,
                mission_id=mission_id,
                field_season_year=field_season_year,
                force_full_scan=force,
            )
            return {
                "message": f"VM4 offload processing completed for mission {mission_id}",
                "mission_id": mission_id,
                "field_season_year": field_season_year,
                **result,
            }

        background_tasks.add_task(_run_vm4_pipeline_job, mission_id, field_season_year, force)
        return {
            "message": f"VM4 offload processing queued for mission {mission_id}",
            "mission_id": mission_id,
            "field_season_year": field_season_year,
            "force_full_scan": force,
            "queued": True,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing VM4 offloads for mission {mission_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing VM4 offloads: {str(e)}",
        )
