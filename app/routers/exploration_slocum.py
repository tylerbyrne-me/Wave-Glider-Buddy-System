"""
Exploration API for Slocum ERDDAP data (testing only).

Authenticated endpoints to fetch Slocum data from Ocean Track ERDDAP
without building the Slocum dashboard yet. Use for Postman/curl/front-end testing.
"""
import asyncio
import logging

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..core.auth import get_current_active_user
from ..core import models
from ..core.feature_toggles import is_feature_enabled
from ..core.slocum_erddap_client import fetch_slocum_data

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/exploration/slocum", tags=["Exploration – Slocum"])

MAX_ROWS = 10_000


@router.get("/data")
async def get_slocum_data(
    dataset_id: str = Query(..., description="ERDDAP dataset_id (e.g. peggy_20250522_206_delayed)"),
    time_start: str = Query(..., description="Start time ISO 8601 (e.g. 2025-08-01T00:00:00Z)"),
    time_end: str = Query(..., description="End time ISO 8601 (e.g. 2025-08-31T23:59:59Z)"),
    current_user: models.User = Depends(get_current_active_user),
):
    """
    Fetch Slocum ERDDAP data for the given dataset and time range.
    Returns JSON with row_count, columns, and data (capped at 10,000 rows).
    For testing auth + backend + ERDDAP; no Slocum UI required.
    """
    if not is_feature_enabled("slocum_platform"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Slocum platform is disabled (feature_toggles.slocum_platform).",
        )
    try:
        df = await asyncio.to_thread(
            fetch_slocum_data, dataset_id, time_start, time_end
        )
    except Exception as e:
        logger.exception("Exploration Slocum fetch failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"ERDDAP fetch failed: {str(e)}",
        ) from e

    if df is None or df.empty:
        return {
            "dataset_id": dataset_id,
            "time_start": time_start,
            "time_end": time_end,
            "row_count": 0,
            "columns": [],
            "data": [],
        }

    df = df.head(MAX_ROWS)
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].astype(str)
    data = df.to_dict(orient="records")
    columns = list(data[0].keys()) if data else []

    return {
        "dataset_id": dataset_id,
        "time_start": time_start,
        "time_end": time_end,
        "row_count": len(data),
        "columns": columns,
        "data": data,
    }
