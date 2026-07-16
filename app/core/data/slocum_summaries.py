"""
Slocum sensor-card summaries and mini-trends.

Mirrors the Wave Glider card contract from summaries.py
({values, latest_timestamp_str, time_ago_str, mini_trend}) but uses
Slocum mirror bundles, column names, and near-surface profile reduction.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from .processors import preprocess_slocum_ctd_df
from .summaries import _generate_mini_trend, _get_common_status_data
from ..slocum_mirror_service import load_mirror_df

logger = logging.getLogger(__name__)

_EMPTY_SHELL: Dict[str, Any] = {
    "values": {},
    "latest_timestamp_str": "N/A",
    "time_ago_str": "N/A",
    "mini_trend": [],
}


def _to_python_scalar(value: Any) -> Any:
    """Convert numpy/pandas scalars to JSON-friendly Python types."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    return value


def _sanitize_values(values: Dict[str, Any]) -> Dict[str, Any]:
    return {key: _to_python_scalar(val) for key, val in (values or {}).items()}


def reduce_slocum_profile_to_near_surface(df: pd.DataFrame) -> pd.DataFrame:
    """
    Reduce depth–time profile rows to one near-surface sample per Timestamp.

    Keeps the row with minimum Depth for each timestamp. If Depth is missing
    or all-null for a timestamp, falls back to the last row for that timestamp.
    """
    if df is None or df.empty:
        return pd.DataFrame() if df is None else df.copy()
    if "Timestamp" not in df.columns:
        return df.copy()

    working = df.copy()
    working = working.dropna(subset=["Timestamp"]).sort_values("Timestamp")
    if working.empty:
        return working

    if "Depth" in working.columns and working["Depth"].notna().any():
        # idxmin() returns NaN for groups where Depth is all-null — drop those.
        idx = working.groupby("Timestamp", sort=True)["Depth"].idxmin().dropna()
        selected = working.loc[idx] if len(idx) else working.iloc[0:0].copy()

        selected_ts = set(selected["Timestamp"].tolist()) if not selected.empty else set()
        all_ts = set(working["Timestamp"].tolist())
        missing_ts = all_ts - selected_ts
        if missing_ts:
            fallback = (
                working[working["Timestamp"].isin(missing_ts)]
                .groupby("Timestamp", sort=True)
                .tail(1)
            )
            selected = pd.concat([selected, fallback], ignore_index=True)

        return selected.sort_values("Timestamp").reset_index(drop=True)

    return working.groupby("Timestamp", sort=True).tail(1).reset_index(drop=True)


def preprocess_slocum_ctd_for_summary(df: Optional[pd.DataFrame]) -> pd.DataFrame:
    """Preprocess Slocum CTD then reduce to near-surface time series for cards."""
    if df is None or df.empty:
        return pd.DataFrame()
    processed = preprocess_slocum_ctd_df(df)
    return reduce_slocum_profile_to_near_surface(processed)


def get_slocum_ctd_status(
    df_ctd: Optional[pd.DataFrame],
    last_update_timestamp: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Summary dict for Slocum CTD left-nav card (near-surface values)."""
    try:
        result_shell, df_processed, last_row = _get_common_status_data(
            df_ctd,
            preprocess_slocum_ctd_for_summary,
            "Slocum CTD",
            last_update_timestamp,
        )
        if last_row is None:
            if result_shell.get("values") is None:
                result_shell["values"] = {}
            return result_shell

        df_last_24h = df_processed[
            df_processed["Timestamp"] > (last_row["Timestamp"] - pd.Timedelta(hours=24))
        ]
        highest_temp_24h = (
            df_last_24h["Temperature"].max()
            if not df_last_24h.empty and "Temperature" in df_last_24h.columns
            else None
        )
        lowest_temp_24h = (
            df_last_24h["Temperature"].min()
            if not df_last_24h.empty and "Temperature" in df_last_24h.columns
            else None
        )

        result_shell["values"] = _sanitize_values(
            {
                "Temperature": last_row.get("Temperature"),
                "Salinity": last_row.get("Salinity"),
                "Conductivity": last_row.get("Conductivity"),
                "Density": last_row.get("Density"),
                "Pressure": last_row.get("Pressure"),
                "HighestTemperature24h": highest_temp_24h,
                "LowestTemperature24h": lowest_temp_24h,
                "Timestamp": (
                    last_row["Timestamp"].isoformat()
                    if pd.notna(last_row.get("Timestamp"))
                    else "N/A"
                ),
            }
        )
        return result_shell
    except Exception as e:
        logger.warning("Error in get_slocum_ctd_status: %s", e, exc_info=True)
        return dict(_EMPTY_SHELL)


def get_slocum_ctd_mini_trend(df_ctd: Optional[pd.DataFrame]) -> List[Dict[str, Any]]:
    """24h near-surface Temperature mini-trend for the Slocum CTD card."""
    return _generate_mini_trend(
        df=df_ctd,
        preprocessor=preprocess_slocum_ctd_for_summary,
        metric_col="Temperature",
        hours_back=24,
        trend_name="Slocum CTD",
    )


# Transfer point for future sensors (dissolved_oxygen, etc.)
SLOCUM_SENSOR_SUMMARY_SPECS: Dict[str, Dict[str, Any]] = {
    "ctd": {
        "bundle": "ctd",
        "status_fn": get_slocum_ctd_status,
        "mini_trend_fn": get_slocum_ctd_mini_trend,
        "info_key": "ctd_info",
        "values_key": "ctd_values",
    },
}


def _empty_sensor_payload() -> Dict[str, Any]:
    return {
        "values": {},
        "latest_timestamp_str": "N/A",
        "time_ago_str": "N/A",
        "mini_trend": [],
    }


def build_slocum_sensor_summaries(
    dataset_id: str,
    enabled_cards: Sequence[str],
) -> Dict[str, Any]:
    """
    Build template/API context for enabled Slocum sensor cards.

    Returns flat keys for SSR (ctd_info, ctd_values, ...) plus a nested
    ``sensors`` map keyed by card name for the JSON API.
    """
    context: Dict[str, Any] = {"sensors": {}}
    enabled = {str(card) for card in (enabled_cards or [])}

    for card_name, spec in SLOCUM_SENSOR_SUMMARY_SPECS.items():
        info_key = spec["info_key"]
        values_key = spec["values_key"]
        empty = _empty_sensor_payload()
        context[info_key] = empty
        context[values_key] = {}

        if card_name not in enabled:
            continue

        status_fn: Callable = spec["status_fn"]
        mini_trend_fn: Callable = spec["mini_trend_fn"]
        bundle = spec["bundle"]

        try:
            df = load_mirror_df(dataset_id, bundle)
        except Exception as e:
            logger.warning(
                "Failed to load Slocum mirror for %s/%s: %s",
                dataset_id,
                bundle,
                e,
                exc_info=True,
            )
            df = pd.DataFrame()

        try:
            info = status_fn(df)
            mini_trend = mini_trend_fn(df)
            sanitized_trend = [
                {
                    "Timestamp": point.get("Timestamp"),
                    "value": _to_python_scalar(point.get("value")),
                }
                for point in (mini_trend or [])
                if point.get("Timestamp") is not None
            ]
            info = dict(info or empty)
            info["mini_trend"] = sanitized_trend
            if info.get("values") is None:
                info["values"] = {}
            else:
                info["values"] = _sanitize_values(info["values"])
        except Exception as e:
            logger.warning(
                "Failed to build Slocum summary for %s/%s: %s",
                dataset_id,
                card_name,
                e,
                exc_info=True,
            )
            info = _empty_sensor_payload()

        context[info_key] = info
        context[values_key] = info.get("values") or {}
        context["sensors"][card_name] = {
            "values": info.get("values") or {},
            "latest_timestamp_str": info.get("latest_timestamp_str", "N/A"),
            "time_ago_str": info.get("time_ago_str", "N/A"),
            "mini_trend": info.get("mini_trend") or [],
        }

    return context
