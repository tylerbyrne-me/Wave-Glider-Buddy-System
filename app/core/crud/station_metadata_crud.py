# app/core/crud/station_metadata_crud.py
import logging

from ...core import models
from ...db import SQLModelSession

logger = logging.getLogger(__name__)


def create_or_update_station(
    session: SQLModelSession, station_data: models.StationMetadataCreate
) -> tuple[models.StationMetadata, bool]: # Return tuple (station, is_created)
    """
    Creates a new station or updates an existing one based on station_id.
    """
    existing_station = session.get(models.StationMetadata, station_data.station_id)

    if existing_station:
        logger.debug(f"CRUD: Station '{station_data.station_id}' already exists. Updating.")
        # Use model_dump to get a dict of the data, excluding unset fields
        update_data = station_data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(existing_station, key, value)

        session.add(existing_station)
        session.commit()
        session.refresh(existing_station)
        return existing_station, False # Not created, it was updated
    else:
        logger.debug(f"CRUD: Creating new station: {station_data.station_id}")
        db_station = models.StationMetadata.model_validate(station_data)
        session.add(db_station)
        session.commit()
        session.refresh(db_station)
        return db_station, True # Newly created