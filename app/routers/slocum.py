"""
Slocum dataset listing and map integration API.

Provides endpoints to list active/config Slocum datasets and search ERDDAP
for available datasets. Used by the map dataset picker UI.
"""
import asyncio
import logging
import time
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..config import settings
from ..core.auth import get_current_active_user
from ..core import models
from ..core.feature_toggles import is_feature_enabled
from ..core.slocum_erddap_client import list_slocum_datasets

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/slocum", tags=["Slocum"])

# Cache for full dataset list (ERDDAP list does not change frequently)
_DATASETS_CACHE: dict[str, Any] | None = None
_DATASETS_CACHE_TIME: float = 0
_DATASETS_CACHE_TTL_SECONDS = 300  # 5 minutes

ERDDAP_REQUEST_TIMEOUT = 35  # Slightly above client timeout for asyncio.wait_for


def _dataset_row_to_dict(row: pd.Series) -> dict[str, Any]:
    """Convert a DataFrame row to a JSON-serializable dict."""
    out: dict[str, Any] = {}
    for k in row.index:
        v = row[k]
        if pd.isna(v):
            out[str(k)] = None
        elif hasattr(v, "isoformat"):
            out[str(k)] = v.isoformat()
        else:
            out[str(k)] = str(v)
    return out


def _build_datasets_response(df: pd.DataFrame | None, active_ids: list[str]) -> dict[str, Any]:
    """Build {active, available} response from DataFrame and active IDs."""
    if df is None or df.empty:
        active_list = [
            {"datasetID": did, "title": did, "institution": None, "minTime": None, "maxTime": None}
            for did in active_ids
        ]
        return {"active": active_list, "available": []}
    records = df.to_dict(orient="records")
    available = [_dataset_row_to_dict(pd.Series(r)) for r in records]
    dataset_id_col = "datasetID"
    if dataset_id_col not in df.columns and len(df.columns):
        dataset_id_col = df.columns[0]
    id_to_meta = {str(r.get(dataset_id_col, "")): r for r in records}
    active_list = []
    for did in active_ids:
        if did in id_to_meta:
            active_list.append(_dataset_row_to_dict(pd.Series(id_to_meta[did])))
        else:
            active_list.append({
                "datasetID": did,
                "title": did,
                "institution": None,
                "minTime": None,
                "maxTime": None,
            })
    available_only = [r for r in available if str(r.get("datasetID", "")) not in set(active_ids)]
    return {"active": active_list, "available": available_only}


@router.get("/datasets")
async def get_slocum_datasets(
    current_user: models.User = Depends(get_current_active_user),
):
    """
    Return combined list of Slocum datasets: active (from config) and available (from ERDDAP).
    Active datasets are those listed in settings.active_slocum_datasets; they appear first
    with metadata from ERDDAP when possible. Response is cached for 5 minutes.
    """
    if not is_feature_enabled("slocum_platform"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Slocum platform is disabled (feature_toggles.slocum_platform).",
        )
    active_ids = [
        s.strip() for s in (settings.active_slocum_datasets or "").split(",") if s.strip()
    ]
    global _DATASETS_CACHE, _DATASETS_CACHE_TIME
    now = time.monotonic()
    if _DATASETS_CACHE is not None and (now - _DATASETS_CACHE_TIME) < _DATASETS_CACHE_TTL_SECONDS:
        return _DATASETS_CACHE
    try:
        df = await asyncio.wait_for(
            asyncio.to_thread(list_slocum_datasets, None),
            timeout=ERDDAP_REQUEST_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.warning("ERDDAP dataset list timed out")
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="ERDDAP server did not respond in time. Try again later.",
        ) from None
    except Exception as e:
        logger.exception("Slocum list_slocum_datasets failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"ERDDAP dataset list failed: {str(e)}",
        ) from e
    response = _build_datasets_response(df, active_ids)
    _DATASETS_CACHE = response
    _DATASETS_CACHE_TIME = now
    return response


@router.get("/datasets/search")
async def search_slocum_datasets(
    q: str = Query(..., min_length=1, description="Search term for dataset title"),
    current_user: models.User = Depends(get_current_active_user),
):
    """Search ERDDAP for Slocum datasets by title (case-insensitive)."""
    if not is_feature_enabled("slocum_platform"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Slocum platform is disabled (feature_toggles.slocum_platform).",
        )
    try:
        df = await asyncio.wait_for(
            asyncio.to_thread(list_slocum_datasets, q),
            timeout=ERDDAP_REQUEST_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.warning("ERDDAP dataset search timed out")
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="ERDDAP server did not respond in time. Try again later.",
        ) from None
    except Exception as e:
        logger.exception("Slocum search failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"ERDDAP search failed: {str(e)}",
        ) from e
    if df is None or df.empty:
        return {"datasets": []}
    records = df.to_dict(orient="records")
    datasets = [_dataset_row_to_dict(pd.Series(r)) for r in records]
    return {"datasets": datasets}
