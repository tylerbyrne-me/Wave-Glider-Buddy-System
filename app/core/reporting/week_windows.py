"""ISO calendar week windows for end-of-mission PDF collation.

Each window is Monday 00:00 UTC (inclusive) through the following Monday 00:00 UTC (exclusive),
clipped to the mission span from Sensor Tracker start/end or telemetry min/max.
First and last windows may be partial; empty telemetry weeks are skipped in ``builder``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional


@dataclass(frozen=True)
class WeekWindow:
    iso_year: int
    iso_week: int
    start_utc: datetime
    end_utc_exclusive: datetime
    is_partial: bool
    label: str


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _monday_00_utc(dt: datetime) -> datetime:
    dt = _ensure_utc(dt)
    monday_date = dt.date() - timedelta(days=dt.weekday())
    return datetime.combine(monday_date, datetime.min.time(), tzinfo=timezone.utc)


def _format_week_label(
    week_monday: datetime,
    effective_start: datetime,
    effective_end_exclusive: datetime,
    *,
    is_partial: bool,
) -> str:
    week_monday = _ensure_utc(week_monday)
    sunday = week_monday + timedelta(days=6)
    start = _ensure_utc(effective_start)
    end_inclusive = _ensure_utc(effective_end_exclusive) - timedelta(seconds=1)
    partial_tag = " (partial)" if is_partial else ""
    return (
        f"Week of {week_monday.strftime('%Y-%m-%d')} (Mon) – "
        f"{sunday.strftime('%Y-%m-%d')} (Sun){partial_tag} · "
        f"data {start.strftime('%Y-%m-%d %H:%M')} – {end_inclusive.strftime('%Y-%m-%d %H:%M')} UTC"
    )


def compute_iso_week_windows(
    mission_start: datetime,
    mission_end: datetime,
) -> List[WeekWindow]:
    """Return ISO calendar weeks (Mon 00:00 UTC → next Mon 00:00 UTC) covering the mission."""
    start = _ensure_utc(mission_start)
    end = _ensure_utc(mission_end)
    if end < start:
        return []

    windows: List[WeekWindow] = []
    week_monday = _monday_00_utc(start)
    if week_monday > start:
        week_monday = week_monday - timedelta(days=7)

    while week_monday <= end:
        next_monday = week_monday + timedelta(days=7)
        effective_start = max(week_monday, start)
        effective_end_exclusive = min(next_monday, end + timedelta(seconds=1))
        if effective_start >= effective_end_exclusive:
            week_monday = next_monday
            continue

        is_partial = effective_start > week_monday or effective_end_exclusive < next_monday
        iso = effective_start.isocalendar()
        label = _format_week_label(
            week_monday,
            effective_start,
            effective_end_exclusive,
            is_partial=is_partial,
        )
        windows.append(
            WeekWindow(
                iso_year=iso[0],
                iso_week=iso[1],
                start_utc=effective_start,
                end_utc_exclusive=effective_end_exclusive,
                is_partial=is_partial,
                label=label,
            )
        )
        week_monday = next_monday

    return windows


def resolve_mission_time_bounds(
    *,
    sensor_tracker_start: Optional[datetime],
    sensor_tracker_end: Optional[datetime],
    telemetry_df,
) -> tuple[datetime, datetime]:
    """Mission span for EOM week iteration (Sensor Tracker preferred, telemetry fallback)."""
    import pandas as pd

    start: Optional[datetime] = None
    end: Optional[datetime] = None

    if sensor_tracker_start is not None:
        start = _ensure_utc(sensor_tracker_start)
    if sensor_tracker_end is not None:
        end = _ensure_utc(sensor_tracker_end)

    if not telemetry_df.empty and "lastLocationFix" in telemetry_df.columns:
        ts = telemetry_df["lastLocationFix"]
        if hasattr(ts, "dtype") and str(ts.dtype) != "object":
            pass
        parsed = pd.to_datetime(ts, errors="coerce", utc=True)
        valid = parsed.dropna()
        if not valid.empty:
            t_min = valid.min().to_pydatetime()
            t_max = valid.max().to_pydatetime()
            if start is None:
                start = _ensure_utc(t_min)
            if end is None:
                end = _ensure_utc(t_max)

    if start is None:
        start = datetime.now(timezone.utc)
    if end is None:
        end = datetime.now(timezone.utc)
    if end < start:
        end = start
    return start, end
