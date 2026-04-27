# app/core/crud/station_metadata_crud.py
import logging

from ...core import models
from ...core.db import SQLModelSession

logger = logging.getLogger(__name__)


def create_or_update_station(
    session: SQLModelSession,
    station_data: models.StationMetadataCreate,
    *,
    commit: bool = True,
) -> tuple[models.StationMetadata, bool]:
    """
    Creates a new station or updates an existing one based on station_id.
    Set commit=False to batch many upserts in one transaction.
    """
    existing_station = session.get(models.StationMetadata, station_data.station_id)

    if existing_station:
        logger.debug(f"CRUD: Station '{station_data.station_id}' already exists. Updating.")
        update_data = station_data.model_dump(exclude_unset=True)
        if "otn_metadata" in update_data:
            update_data["notes"] = update_data.pop("otn_metadata")
        for key, value in update_data.items():
            setattr(existing_station, key, value)

        session.add(existing_station)
        if commit:
            session.commit()
            session.refresh(existing_station)
        return existing_station, False
    else:
        logger.debug(f"CRUD: Creating new station: {station_data.station_id}")
        db_station = models.StationMetadata.model_validate(station_data)
        session.add(db_station)
        if commit:
            session.commit()
            session.refresh(db_station)
        return db_station, True