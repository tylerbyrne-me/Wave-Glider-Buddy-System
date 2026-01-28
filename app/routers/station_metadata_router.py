# station_metadata_router.py
import logging
from datetime import datetime, timezone
from typing import Annotated, Any, Dict, List, Optional
import io

import pandas as pd
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, status, UploadFile, File
from fastapi.responses import JSONResponse, StreamingResponse
from sqlmodel import select  # Import select for queries
from sqlalchemy.orm import selectinload  # For eager loading relationships

from ..core.auth import get_current_active_user, get_current_admin_user
from ..core import models
from ..core.crud import station_metadata_crud
from ..core.models import User as UserModel # UserModel alias is used
from ..core.db import SQLModelSession, get_db_session
from ..services.station_season_service import StationSeasonService

logger = logging.getLogger(__name__)

# Create an APIRouter instance
router = APIRouter()
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
    # Admin required to create/update
    current_user: Annotated[UserModel, Depends(get_current_admin_user)],
):
    logger.info(
        f"ROUTER: User '{current_user.username}' attempting to "
        f"create/update station: {station_data.station_id}"
    )
    
    # Check if updating an existing archived station
    existing_station = session.get(models.StationMetadata, station_data.station_id)
    if existing_station and existing_station.is_archived:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Station {station_data.station_id} is archived and cannot be modified",
        )
    
    # Set field_season_year if not provided (use active season)
    if not hasattr(station_data, 'field_season_year') or station_data.field_season_year is None:
        active_season = StationSeasonService.get_active_season(session)
        if active_season:
            # Set field_season_year on the station_data object
            station_data_dict = station_data.model_dump()
            station_data_dict['field_season_year'] = active_season.year
            station_data = models.StationMetadataCreate(**station_data_dict)
    
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
    station = session.get(models.StationMetadata, station_id)
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
        existing_station_ids = {s.station_id for s in session.exec(existing_stations_stmt).all()}
        
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
            existing_serials = {s.serial_number for s in session.exec(existing_serials_stmt).all() if s.serial_number}
            
            if existing_serials:
                existing_serials_list = sorted([str(s) for s in existing_serials])
                warnings.append({
                    "type": "duplicate_serial_number_in_db",
                    "message": f"Serial numbers that already exist in database: {', '.join(existing_serials_list)}",
                    "duplicates": existing_serials_list
                })
                logger.info(f"CSV Upload: Serial numbers that already exist: {existing_serials_list}")

    # Determine which season year to assign
    target_season_year = season_year
    is_historical_season = False
    
    if target_season_year is None:
        # Use active season if no season specified
        active_season = StationSeasonService.get_active_season(session)
        target_season_year = active_season.year if active_season else None
        is_historical_season = False  # Active season is not historical
    else:
        # Verify the specified season exists
        specified_season = StationSeasonService.get_season_by_year(session, target_season_year)
        if not specified_season:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Season {target_season_year} does not exist. Please create it first or use an existing season.",
            )
        # Check if it's a closed/historical season
        is_historical_season = not specified_season.is_active or specified_season.closed_at_utc is not None

    processed_count = 0
    errors = []
    for index, row in df.iterrows():
        try:
            # Convert row to dict - keep None values for fields we need to explicitly set
            row_dict = row.to_dict()
            # Remove None values only for optional fields that shouldn't override existing data
            # But keep fields we need to explicitly set
            row_dict = {k: v for k, v in row_dict.items() if v is not None or k in ['field_season_year', 'is_archived', 'archived_at_utc']}
            
            # Always set field_season_year and archive status based on target season
            if target_season_year is not None:
                row_dict['field_season_year'] = target_season_year
                # For historical/closed seasons, mark as archived
                if is_historical_season:
                    row_dict['is_archived'] = True
                    row_dict['archived_at_utc'] = datetime.now(timezone.utc)
                else:
                    # For active season, ensure not archived
                    row_dict['is_archived'] = False
                    row_dict['archived_at_utc'] = None
            else:
                # For active season (when no season specified), ensure not archived
                row_dict['field_season_year'] = None
                row_dict['is_archived'] = False
                row_dict['archived_at_utc'] = None
            
            # Create station data - this will include field_season_year and archive status
            station_data = models.StationMetadataCreate(**row_dict)
            
            # Get existing station if it exists
            existing_station = session.get(models.StationMetadata, station_data.station_id)
            
            if existing_station:
                logger.info(
                    f"Updating existing station {station_data.station_id}: "
                    f"field_season_year={station_data.field_season_year}, "
                    f"is_archived={station_data.is_archived}"
                )
                # Update existing station - ensure season fields are always updated
                update_data = station_data.model_dump(exclude_unset=True)
                # Always explicitly set season-related fields (don't rely on defaults)
                update_data['field_season_year'] = station_data.field_season_year
                update_data['is_archived'] = station_data.is_archived
                update_data['archived_at_utc'] = station_data.archived_at_utc
                
                for key, value in update_data.items():
                    setattr(existing_station, key, value)
                
                session.add(existing_station)
                session.commit()
                session.refresh(existing_station)
                logger.info(
                    f"Station {existing_station.station_id} updated: "
                    f"field_season_year={existing_station.field_season_year}, "
                    f"is_archived={existing_station.is_archived}"
                )
            else:
                logger.info(
                    f"Creating new station {station_data.station_id}: "
                    f"field_season_year={station_data.field_season_year}, "
                    f"is_archived={station_data.is_archived}"
                )
                # New station - use CRUD function
                new_station, _ = station_metadata_crud.create_or_update_station(
                    session=session, station_data=station_data
                )
                logger.info(
                    f"Station {new_station.station_id} created: "
                    f"field_season_year={new_station.field_season_year}, "
                    f"is_archived={new_station.is_archived}"
                )
            
            processed_count += 1
        except Exception as e:
            error_detail = f"Row {index + 2}: {e}"
            logger.error(f"ROUTER: CSV Upload - {error_detail}")
            errors.append(error_detail)

    # Build response message
    season_info = f" for season {target_season_year}" if target_season_year else " (active season)"
    response_content = {
        "message": f"Successfully created or updated {processed_count} stations from {file.filename}{season_info}.",
    }
    
    # Add warnings if any
    if warnings:
        response_content["warnings"] = warnings
    
    # Add errors if any
    if errors:
        response_content["errors"] = errors
        # Return 207 Multi-Status if there are partial successes
        return JSONResponse(
            status_code=status.HTTP_207_MULTI_STATUS,
            content=response_content,
        )

    # If there are warnings but no errors, still return success but include warnings
    if warnings:
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
    
    # Check if station is archived
    if db_station_metadata.is_archived:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Station {station_id} is archived and cannot be modified",
        )

    update_data = station_update_data.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No update data provided"
        )

    for key, value in update_data.items():
        setattr(db_station_metadata, key, value)

    session.add(db_station_metadata)
    session.commit()
    session.refresh(db_station_metadata)
    logger.info(
        f"ROUTER: Station '{station_id}' fields updated by user "
        f"'{current_user.username}'."
    )
    return db_station_metadata


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
    
    # Check if station is archived
    if db_station_metadata.is_archived:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Station {station_id} is archived and cannot be modified",
        )

    # Get active season to set field_season_year
    active_season = StationSeasonService.get_active_season(session)
    field_season_year = active_season.year if active_season else None

    offload_log_data = offload_log_in.model_dump()
    offload_log_data["logged_by_username"] = current_user.username
    offload_log_data["station_id"] = station_id
    offload_log_data["field_season_year"] = field_season_year

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


@router.get(
    "/stations/status_overview",
    response_model=List[Dict[str, Any]],
    tags=["Station Status Overview"],
)  # Using Dict for augmented response
async def get_station_offload_status_overview(
    session: Annotated[SQLModelSession, Depends(get_db_session)],
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
    season_year: Optional[int] = Query(None, description="Filter by field season year (None = active season)"),
):
    logger.info(
        f"User '{current_user.username}' requesting station offload status overview"
        f"{f' for season {season_year}' if season_year else ' (active season)'}."
    )

    # Filter by season year if provided
    if season_year is not None:
        # For specific seasons, include all stations (archived and non-archived)
        # Eagerly load offload_logs relationship
        statement = (
            select(models.StationMetadata)
            .options(selectinload(models.StationMetadata.offload_logs))
            .where(models.StationMetadata.field_season_year == season_year)
            .order_by(models.StationMetadata.station_id)
        )
    else:
        # Active season - get stations with NULL field_season_year and not archived
        # Eagerly load offload_logs relationship
        statement = (
            select(models.StationMetadata)
            .options(selectinload(models.StationMetadata.offload_logs))
            .where(
                models.StationMetadata.field_season_year.is_(None),
                models.StationMetadata.is_archived == False,
            )
            .order_by(models.StationMetadata.station_id)
        )
    
    stations_metadata = list(session.exec(statement).all())
    logger.info(
        f"Found {len(stations_metadata)} stations for season "
        f"{season_year if season_year else 'active (NULL)'}"
    )
    
    overview_list = []
    # now_utc = datetime.now(timezone.utc)

    for station in stations_metadata:
        status_text = "Unknown"  # Default if no conditions met
        status_color_key = "grey"  # Default color key
        last_offload_timestamp_str = "N/A"
        latest_vrl_file_name = "---"
        latest_arrival_date_str = "---"
        latest_distance_command_sent_m_str = "---"
        latest_time_first_command_sent_utc_str = "---"
        latest_offload_start_time_utc_str = "---"
        latest_offload_end_time_utc_str = "---"
        latest_departure_date_str = "---"
        latest_was_offloaded_str = "---"
        latest_offload_notes_file_size_str = "---"
        latest_remote_health_model_id = None
        latest_remote_health_serial_number = None
        latest_remote_health_modem_address = None
        latest_remote_health_temperature_c = None
        latest_remote_health_tilt_rad = None
        latest_remote_health_humidity = None

        if station.last_offload_timestamp_utc:
            retrieved_ts = station.last_offload_timestamp_utc
            if (
                retrieved_ts.tzinfo is None
                or retrieved_ts.tzinfo.utcoffset(retrieved_ts) is None
            ):
                retrieved_ts_aware = retrieved_ts.replace(tzinfo=timezone.utc)
            else:
                retrieved_ts_aware = retrieved_ts

            last_offload_timestamp_str = retrieved_ts_aware.strftime(
                "%Y-%m-%d %H:%M:%S UTC"
            )

        # Get latest VRL file name from offload logs
        # Filter logs by season if viewing a specific season
        relevant_logs = station.offload_logs
        if season_year is not None:
            # When viewing a specific season, only show logs from that season
            relevant_logs = [log for log in station.offload_logs if log.field_season_year == season_year]
        elif season_year is None:
            # For active season, only show logs without a season year (active season logs)
            relevant_logs = [log for log in station.offload_logs if log.field_season_year is None]
        
        if relevant_logs:
            # Sort logs by log_timestamp_utc descending to get the most recent
            sorted_logs = sorted(
                relevant_logs,
                key=lambda log: log.log_timestamp_utc,
                reverse=True,
            )
            if sorted_logs:
                latest_log = sorted_logs[0]
                if latest_log.vrl_file_name:
                    latest_vrl_file_name = latest_log.vrl_file_name

                # Helper to format datetime or return "---"
                def format_dt(dt_val):
                    if dt_val:
                        if (
                            dt_val.tzinfo is None
                            or dt_val.tzinfo.utcoffset(dt_val) is None
                        ):
                            return dt_val.replace(tzinfo=timezone.utc).strftime(
                                "%Y-%m-%d %H:%M:%S UTC"
                            )
                        return dt_val.strftime("%Y-%m-%d %H:%M:%S UTC")
                    return "---"

                latest_arrival_date_str = format_dt(latest_log.arrival_date)
                latest_distance_command_sent_m_str = (
                    str(latest_log.distance_command_sent_m)
                    if latest_log.distance_command_sent_m is not None
                    else "---" # noqa
                )
                latest_time_first_command_sent_utc_str = format_dt(
                    latest_log.time_first_command_sent_utc
                )
                latest_offload_start_time_utc_str = format_dt(
                    latest_log.offload_start_time_utc
                )
                # This is also the basis for last_offload_timestamp_str if this
                # log is the one that set it
                latest_offload_end_time_utc_str = format_dt(latest_log.offload_end_time_utc)
                latest_departure_date_str = format_dt(latest_log.departure_date)
                latest_was_offloaded_str = (
                    "Yes"
                    if latest_log.was_offloaded is True
                    else ("No" if latest_log.was_offloaded is False else "---")
                )
                latest_offload_notes_file_size_str = (
                    latest_log.offload_notes_file_size or "---"
                )
                # VM4 Remote Health snapshot at connection (from Vemco VM4 Remote Health.csv)
                if getattr(latest_log, "remote_health_model_id", None) is not None:
                    latest_remote_health_model_id = latest_log.remote_health_model_id
                if getattr(latest_log, "remote_health_serial_number", None) is not None:
                    latest_remote_health_serial_number = latest_log.remote_health_serial_number
                if getattr(latest_log, "remote_health_modem_address", None) is not None:
                    latest_remote_health_modem_address = latest_log.remote_health_modem_address
                if getattr(latest_log, "remote_health_temperature_c", None) is not None:
                    latest_remote_health_temperature_c = latest_log.remote_health_temperature_c
                if getattr(latest_log, "remote_health_tilt_rad", None) is not None:
                    latest_remote_health_tilt_rad = latest_log.remote_health_tilt_rad
                if getattr(latest_log, "remote_health_humidity", None) is not None:
                    latest_remote_health_humidity = latest_log.remote_health_humidity
        # New status logic
        if station.display_status_override:
            if station.display_status_override.upper() == "SKIPPED":
                status_text = "Skipped"
                status_color_key = "yellow"  # For orange/yellowish color
            # Potentially handle other override values here
            # else:
            #     status_text = station.display_status_override # Display the override text directly
            #     status_color_key = "blue" # A generic color for other overrides

        elif station.was_last_offload_successful is True:
            status_text = "Offloaded"
            status_color_key = "green"  # For green/blue success color
        elif station.was_last_offload_successful is False:
            status_text = "Failed Offload"
            status_color_key = "red"
        elif station.last_offload_timestamp_utc is None:  # No logs yet, and no override
            status_text = "Awaiting Offload"
            status_color_key = "grey"
        else:  # Has logs, but was_last_offload_successful is None (should be rare), and no override
            status_text = "Awaiting Status"  # Or "Awaiting Offload" if preferred
            status_color_key = "grey"

        overview_list.append(
            {
                "station_id": station.station_id,
                "serial_number": station.serial_number,
                "modem_address": station.modem_address,
                "station_settings": station.station_settings
                or "---",  # Add station settings
                "deployment_latitude": station.deployment_latitude,
                "deployment_longitude": station.deployment_longitude,
                # "last_offload_by_glider": station.last_offload_by_glider,
                # No longer directly in table
                "last_offload_timestamp_str": last_offload_timestamp_str,
                "status_text": status_text,
                # Send the key for JS to map to CSS class
                "status_color": status_color_key,
                # For modal pre-fill
                "display_status_override": station.display_status_override,
                "vrl_file_name": latest_vrl_file_name,  # Add latest VRL file name
                # Add other latest log details
                "latest_arrival_date": latest_arrival_date_str,
                "latest_distance_command_sent_m": latest_distance_command_sent_m_str,
                "latest_time_first_command_sent_utc": latest_time_first_command_sent_utc_str,
                "latest_offload_start_time_utc": latest_offload_start_time_utc_str,
                "latest_offload_end_time_utc": latest_offload_end_time_utc_str,
                "latest_departure_date": latest_departure_date_str,
                "latest_was_offloaded": latest_was_offloaded_str,
                "latest_offload_notes_file_size": latest_offload_notes_file_size_str,
                "remote_health_model_id": latest_remote_health_model_id,
                "remote_health_serial_number": latest_remote_health_serial_number,
                "remote_health_modem_address": latest_remote_health_modem_address,
                "remote_health_temperature_c": latest_remote_health_temperature_c,
                "remote_health_tilt_rad": latest_remote_health_tilt_rad,
                "remote_health_humidity": latest_remote_health_humidity,
            }
        )

    return overview_list


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
    This does NOT delete associated stations or offload logs, only the season record.
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
    
    session.delete(season)
    session.commit()
    
    logger.warning(
        f"TESTING: Season {year} deleted by '{current_user.username}'. "
        f"Note: Associated stations and offload logs remain in database."
    )
    
    return {
        "message": f"Season {year} deleted. Associated stations and offload logs remain in database.",
        "warning": "This was a testing operation. Station data was not deleted."
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
    """Close a field season, archiving all stations and offload logs (admin only)."""
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
            "Station Settings": station.station_settings if station else "---",
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
    """Get master list of stations for a season (clean data for next season preparation)."""
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
            detail=f"No stations found for season {year}",
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
    """Import master list CSV to create stations for a new season (admin only)."""
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
    
    # Ensure season exists
    season = StationSeasonService.get_season_by_year(session, year)
    if not season:
        season = StationSeasonService.create_season(session, year, is_active=True)
    
    processed_count = 0
    errors = []
    for index, row in df.iterrows():
        try:
            row_dict = {k: v for k, v in row.to_dict().items() if v is not None}
            # Set field_season_year for new season
            row_dict["field_season_year"] = year
            row_dict["is_archived"] = False
            row_dict["archived_at_utc"] = None
            
            station_data = models.StationMetadataCreate(**row_dict)
            station_metadata_crud.create_or_update_station(
                session=session, station_data=station_data
            )
            processed_count += 1
        except Exception as e:
            error_detail = f"Row {index + 2}: {e}"
            logger.error(f"Master list import - {error_detail}")
            errors.append(error_detail)
    
    # Build response message
    response_content = {
        "message": f"Successfully imported {processed_count} stations from {file.filename} for season {year}.",
    }
    
    # Add warnings if any
    if warnings:
        response_content["warnings"] = warnings
    
    # Add errors if any
    if errors:
        response_content["errors"] = errors
        return JSONResponse(
            status_code=status.HTTP_207_MULTI_STATUS,
            content=response_content,
        )
    
    # If there are warnings but no errors, still return success but include warnings
    if warnings:
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
        # Delete all offload logs
        from sqlmodel import delete
        delete_logs_stmt = delete(models.OffloadLog)
        session.exec(delete_logs_stmt)
        
        # Delete all station metadata
        delete_stations_stmt = delete(models.StationMetadata)
        session.exec(delete_stations_stmt)
        
        session.commit()
        
        logger.warning(
            f"TESTING: All stations and offload logs cleared by '{current_user.username}'."
        )
        
        return {
            "message": "All stations and offload logs have been cleared. This was a testing operation.",
            "warning": "All data has been permanently deleted without archiving."
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
    session: Annotated[SQLModelSession, Depends(get_db_session)],
    current_user: Annotated[UserModel, Depends(get_current_admin_user)],
    force: bool = Query(False, description="Force processing even if mission is historical"),
    field_season_year: Optional[int] = Query(None, description="Field season year to assign to offload logs (overrides station's season)"),
):
    """
    TESTING: Manually trigger VM4 offload processing for a mission.
    This allows processing historical mission data for testing purposes.
    If field_season_year is specified, all offload logs will be assigned to that season.
    """
    logger.warning(
        f"TESTING: Admin '{current_user.username}' manually triggering VM4 processing for mission {mission_id}."
    )
    
    try:
        from ..core.wg_vm4_station_service import process_wg_vm4_info_for_mission
        from ..core.processors import preprocess_wg_vm4_info_df
        from ..core.data_service import get_data_service
        
        # Load WG-VM4 info data for the mission
        data_service = get_data_service()
        try:
            df, source_path, file_mod_time = await data_service.load(
                "wg_vm4_info",
                mission_id,
                hours_back=None,  # Load all available data
            )
        except Exception as load_error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Error loading WG-VM4 info data for mission {mission_id}: {str(load_error)}",
            )
        
        if df is None or df.empty:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"WG-VM4 info DataFrame is empty for mission {mission_id}",
            )
        
        # Preprocess the data
        processed_df = preprocess_wg_vm4_info_df(df)
        
        # Validate field_season_year if provided
        if field_season_year is not None:
            from ..services.station_season_service import StationSeasonService
            season = StationSeasonService.get_season_by_year(session, field_season_year)
            if not season:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Field season {field_season_year} not found",
                )
            logger.info(f"Assigning VM4 offload logs to field season {field_season_year}")
        
        # Process for automatic offload logging
        stats = process_wg_vm4_info_for_mission(session, processed_df, mission_id, field_season_year)
        
        # Load and attach Vemco VM4 Remote Health to offload logs when available
        health_stats = {}
        try:
            from ..core.wg_vm4_station_service import attach_remote_health_to_offload_logs
            from ..core.processors import preprocess_wg_vm4_remote_health_df
            rh_df, _, _ = await data_service.load(
                "wg_vm4_remote_health",
                mission_id,
                hours_back=None,
            )
            if rh_df is not None and not rh_df.empty:
                rh_processed = preprocess_wg_vm4_remote_health_df(rh_df)
                health_stats = attach_remote_health_to_offload_logs(session, rh_processed)
                logger.info(f"VM4 remote health attached for mission {mission_id}: {health_stats}")
        except Exception as rh_err:
            logger.debug(f"VM4 remote health not loaded or attach failed for mission {mission_id}: {rh_err}")
        
        logger.warning(
            f"TESTING: VM4 processing complete for mission {mission_id}: {stats}, field_season_year={field_season_year}"
        )
        
        return {
            "message": f"VM4 offload processing completed for mission {mission_id}",
            "statistics": stats,
            "mission_id": mission_id,
            "rows_processed": len(processed_df),
            "field_season_year": field_season_year,
            "remote_health": health_stats,
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing VM4 offloads for mission {mission_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing VM4 offloads: {str(e)}",
        )
