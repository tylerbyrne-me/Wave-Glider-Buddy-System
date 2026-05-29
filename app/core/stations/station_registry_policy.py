"""
Station registry / field season UI rules (single source of truth).

- **Registry grid**: One row per `station_id` in `station_metadata`. The default ops list
  includes stations that are not retired and not legacy-archived (`is_archived`,
  cleared on migration; kept only for backward compatibility).
- **Season is event tagging**: `OffloadLog.field_season_year` and `FieldSeason` describe
  when offloads occurred. Choosing a season in the UI filters which logs feed per-row
  summaries; it does not switch to a separate roster table (live registry fields are
  always current hardware/settings).
- **Audit roster at close**: `station_metadata_season_snapshots` holds an immutable copy
  of each registry row at season close. Season summary statistics for a *closed* year
  prefer this snapshot set when present; otherwise the roster is derived from station
  IDs seen in that season's logs.
"""

from __future__ import annotations

from typing import Optional

from ..models.database import StationMetadata


def station_in_ops_registry_list(station: StationMetadata) -> bool:
    """True if this station should appear on the default station status / registry lists."""
    return not station.is_retired and not station.is_archived


def station_blocks_edits(station: StationMetadata) -> bool:
    """True if offload logs and mutable registry fields must not change (retired or legacy archived)."""
    return station.is_retired or station.is_archived


def offload_log_matches_season_year(
    *,
    log_season: Optional[int],
    target_year: int,
    season_is_closed: bool,
) -> bool:
    """Whether an offload log belongs to season `target_year` for filtering/stats."""
    if season_is_closed:
        return log_season == target_year
    return log_season is None or log_season == target_year
