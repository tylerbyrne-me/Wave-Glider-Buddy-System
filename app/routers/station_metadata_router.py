# station_metadata_router.py
import logging
from datetime import datetime, timezone
from typing import Annotated, Any, Dict, List, Optional
import io

import pandas as pd
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, status, UploadFile, File
from fastapi.responses import JSONResponse
from sqlmodel import select  # Import select for queries

from ..core.auth import get_current_active_user, get_current_admin_user
from ..core import models
from ..core.crud import station_metadata_crud
from ..core.models import User as UserModel # UserModel alias is used
from ..core.db import SQLModelSession, get_db_session

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

    # Check for duplicate station_ids within the CSV file itself
    if df['station_id'].duplicated().any():
        # Get the list of duplicated station_ids to show in the error message
        duplicated_ids = sorted(df[df['station_id'].duplicated()]['station_id'].unique().tolist())
        error_detail = f"Upload failed. The CSV file contains duplicate entries for the following station_ids, which is not allowed: {', '.join(duplicated_ids)}"
        logger.error(f"ROUTER: CSV Upload Failed - {error_detail}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_detail,
        )

    # Replace numpy NaNs and pandas <NA> with None for Pydantic compatibility
    df = df.replace({np.nan: None, pd.NA: None})

    processed_count = 0
    errors = []
    for index, row in df.iterrows():
        try:
            # Convert row to dict and filter out None values so Pydantic uses defaults
            row_dict = {k: v for k, v in row.to_dict().items() if v is not None}
            station_data = models.StationMetadataCreate(**row_dict)
            station_metadata_crud.create_or_update_station(
                session=session, station_data=station_data
            )
            processed_count += 1
        except Exception as e:
            error_detail = f"Row {index + 2}: {e}"
            logger.error(f"ROUTER: CSV Upload - {error_detail}")
            errors.append(error_detail)

    if errors:
        # Return 207 Multi-Status if there are partial successes
        return JSONResponse(
            status_code=status.HTTP_207_MULTI_STATUS,
            content={
                "message": f"Processed {processed_count} of {len(df)} stations with {len(errors)} errors.",
                "errors": errors,
            },
        )

    return {
        "message": f"Successfully created or updated {processed_count} stations from {file.filename}."
    }


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

    offload_log_data = offload_log_in.model_dump()
    offload_log_data["logged_by_username"] = current_user.username
    offload_log_data["station_id"] = station_id

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
    # Any active user can view
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
):
    logger.info(
        f"User '{current_user.username}' requesting station offload status overview."
    )

    statement = select(models.StationMetadata).order_by(
        models.StationMetadata.station_id
    )
    stations_metadata = session.exec(statement).all()

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
        if station.offload_logs:
            # Sort logs by log_timestamp_utc descending to get the most recent
            sorted_logs = sorted(
                station.offload_logs,
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
            }
        )

    return overview_list
