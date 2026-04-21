"""
Station Season Service

Handles field season management, statistics calculation, and season closing workflows.
"""
import logging
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from typing import Dict, Any, List, Optional
from collections import defaultdict

from sqlmodel import select
from sqlmodel import Session as SQLModelSession

from ..core import models
from ..core.models import (
    FieldSeason,
    OffloadLog,
    StationMetadata,
    StationMetadataSeasonSnapshot,
)

logger = logging.getLogger(__name__)


def _season_row(
    session: SQLModelSession, year: int
) -> Optional[FieldSeason]:
    return StationSeasonService.get_season_by_year(session, year)


def _season_is_closed(session: SQLModelSession, year: int) -> bool:
    row = _season_row(session, year)
    return bool(row and row.closed_at_utc)


def _season_logs_query(year: int, season_is_closed: bool):
    if season_is_closed:
        return select(OffloadLog).where(OffloadLog.field_season_year == year)
    return select(OffloadLog).where(
        (OffloadLog.field_season_year == year) | (OffloadLog.field_season_year.is_(None))
    )


def _minimal_station_for_stats(station_id: str) -> Any:
    return SimpleNamespace(
        station_id=station_id,
        display_status_override=None,
        last_offload_by_glider=None,
    )


class StationSeasonService:
    """Service for managing field seasons and station data."""

    @staticmethod
    def get_active_season(session: SQLModelSession) -> Optional[FieldSeason]:
        """Get the currently active field season."""
        statement = select(FieldSeason).where(FieldSeason.is_active == True)
        return session.exec(statement).first()

    @staticmethod
    def get_season_by_year(session: SQLModelSession, year: int) -> Optional[FieldSeason]:
        """Get a field season by year."""
        statement = select(FieldSeason).where(FieldSeason.year == year)
        return session.exec(statement).first()

    @staticmethod
    def get_all_seasons(session: SQLModelSession) -> List[FieldSeason]:
        """Get all field seasons, ordered by year descending."""
        statement = select(FieldSeason).order_by(FieldSeason.year.desc())
        return list(session.exec(statement).all())

    @staticmethod
    def create_season(session: SQLModelSession, year: int, is_active: bool = False) -> FieldSeason:
        """Create a new field season."""
        # If setting as active, deactivate all other seasons
        if is_active:
            existing_active = StationSeasonService.get_active_season(session)
            if existing_active:
                existing_active.is_active = False
                session.add(existing_active)

        season = FieldSeason(
            year=year,
            is_active=is_active,
            created_at_utc=datetime.now(timezone.utc),
        )
        session.add(season)
        session.commit()
        session.refresh(season)
        return season

    @staticmethod
    def calculate_season_statistics(
        session: SQLModelSession, year: int
    ) -> Dict[str, Any]:
        """
        Calculate comprehensive statistics for a field season.

        Roster: For a closed year, prefers `station_metadata_season_snapshots` if present;
        otherwise unique `station_id` values from that season's logs (with live registry
        fill-in when available). For the active (not-yet-closed) year, uses the live
        registry (non-retired, non-archived).

        Assumption: If a command was sent and we never have a confirmed offload
        response (was_offloaded True), the station is counted as failed.
        """
        season_is_closed = _season_is_closed(session, year)
        offload_statement = _season_logs_query(year, season_is_closed)
        offload_logs = list(session.exec(offload_statement).all())

        if season_is_closed:
            snap_stmt = (
                select(StationMetadataSeasonSnapshot)
                .where(StationMetadataSeasonSnapshot.field_season_year == year)
                .order_by(StationMetadataSeasonSnapshot.station_id)
            )
            stations = list(session.exec(snap_stmt).all())
            if not stations:
                ids = sorted({log.station_id for log in offload_logs})
                if not ids:
                    stations = []
                else:
                    live_stmt = select(StationMetadata).where(
                        StationMetadata.station_id.in_(ids)
                    )
                    by_id = {r.station_id: r for r in session.exec(live_stmt).all()}
                    stations = [
                        by_id.get(sid) or _minimal_station_for_stats(sid) for sid in ids
                    ]
        else:
            station_statement = (
                select(StationMetadata)
                .where(
                    StationMetadata.is_retired == False,
                    StationMetadata.is_archived == False,
                )
                .order_by(StationMetadata.station_id)
            )
            stations = list(session.exec(station_statement).all())
        
        # Create a mapping of station_id to its logs for efficient lookup
        logs_by_station = defaultdict(list)
        for log in offload_logs:
            logs_by_station[log.station_id].append(log)
        
        # Calculate statistics
        stations_by_type = defaultdict(int)
        successful_offloads = 0
        failed_offloads = 0
        skipped_stations = 0
        failed_stations = 0  # Track failed stations (not just failed log attempts)
        failed_station_ids: List[str] = []  # IDs of stations that had attempts but no success
        total_time_at_station_seconds = []
        unique_stations = set()
        first_offload_date = None
        last_offload_date = None
        # Remote health coverage
        remote_health_logs_with_data = 0
        remote_health_stations_with_data = set()
        
        # Statistics by station type
        success_by_type = defaultdict(lambda: {"successful": 0, "failed": 0, "skipped": 0, "total": 0})
        
        # Statistics by mission ID
        success_by_mission = defaultdict(lambda: {"successful": 0, "failed": 0, "skipped": 0, "total": 0})
        
        # Track offload attempts per station (for log notes)
        station_attempt_details = {}  # station_id -> {"attempt_count": int, "attempt_timestamps": [datetime, ...]}
        
        # Process stations to determine their status
        for station in stations:
            # Count by type (extract prefix from station_id)
            station_type = StationSeasonService._extract_station_type(station.station_id)
            stations_by_type[station_type] += 1
            unique_stations.add(station.station_id)
            
            # Get logs for this station
            station_logs = logs_by_station.get(station.station_id, [])
            
            # Track offload attempts for this station
            # An attempt is indicated by either time_first_command_sent_utc or offload_start_time_utc
            attempt_timestamps = []
            for log in station_logs:
                # Use offload_start_time_utc if available, otherwise time_first_command_sent_utc
                attempt_time = log.offload_start_time_utc or log.time_first_command_sent_utc
                if attempt_time:
                    attempt_timestamps.append(attempt_time)
            
            # Sort timestamps chronologically
            attempt_timestamps.sort()
            
            # Store attempt details for this station
            station_attempt_details[station.station_id] = {
                "attempt_count": len(attempt_timestamps),
                "attempt_timestamps": [ts.isoformat() for ts in attempt_timestamps] if attempt_timestamps else []
            }
            
            # Determine station status
            is_explicitly_skipped = (
                station.display_status_override and 
                station.display_status_override.upper() == "SKIPPED"
            )
            
            if is_explicitly_skipped:
                skipped_stations += 1
                success_by_type[station_type]["skipped"] += 1
                success_by_type[station_type]["total"] += 1
                # Try to get mission ID from station metadata
                mission_id = station.last_offload_by_glider or "unknown"
                success_by_mission[mission_id]["skipped"] += 1
                success_by_mission[mission_id]["total"] += 1
            elif not station_logs:
                # No offload attempts = skipped
                skipped_stations += 1
                success_by_type[station_type]["skipped"] += 1
                success_by_type[station_type]["total"] += 1
                mission_id = station.last_offload_by_glider or "unknown"
                success_by_mission[mission_id]["skipped"] += 1
                success_by_mission[mission_id]["total"] += 1
            else:
                # Has logs - analyze each log to determine station status
                # Check for any successful offloads first
                has_successful = any(log.was_offloaded is True for log in station_logs)
                
                if has_successful:
                    # At least one successful offload = station is successful
                    success_by_type[station_type]["successful"] += 1
                    success_by_type[station_type]["total"] += 1
                    # Get mission from the successful log's station metadata
                    mission_id = station.last_offload_by_glider or "unknown"
                    success_by_mission[mission_id]["successful"] += 1
                    success_by_mission[mission_id]["total"] += 1
                else:
                    # No confirmed offload (was_offloaded True). If command was sent, count as failed.
                    # Attempt = any log with offload_start_time_utc or time_first_command_sent_utc
                    has_any_attempt = any(
                        (log.offload_start_time_utc or log.time_first_command_sent_utc)
                        for log in station_logs
                    )
                    
                    if has_any_attempt:
                        # Command sent, no confirmed offload response → failed
                        failed_stations += 1
                        failed_station_ids.append(station.station_id)
                        success_by_type[station_type]["failed"] += 1
                        success_by_type[station_type]["total"] += 1
                        mission_id = station.last_offload_by_glider or "unknown"
                        success_by_mission[mission_id]["failed"] += 1
                        success_by_mission[mission_id]["total"] += 1
                        
                        logger.debug(
                            f"Station {station.station_id} marked as failed: "
                            f"attempt(s) but no success. "
                            f"Logs: {[(getattr(l, 'offload_start_time_utc'), getattr(l, 'time_first_command_sent_utc'), l.was_offloaded) for l in station_logs]}"
                        )
                    else:
                        # Has logs but no timestamps indicating an attempt = skipped
                        skipped_stations += 1
                        success_by_type[station_type]["skipped"] += 1
                        success_by_type[station_type]["total"] += 1
                        mission_id = station.last_offload_by_glider or "unknown"
                        success_by_mission[mission_id]["skipped"] += 1
                        success_by_mission[mission_id]["total"] += 1
        
        # Process offload logs for detailed statistics
        for log in offload_logs:
            unique_stations.add(log.station_id)

            # Track remote health presence on logs
            if (
                getattr(log, "remote_health_model_id", None) is not None
                or getattr(log, "remote_health_temperature_c", None) is not None
                or getattr(log, "remote_health_humidity", None) is not None
            ):
                remote_health_logs_with_data += 1
                remote_health_stations_with_data.add(log.station_id)
            
            # Track first and last offload dates
            if log.offload_start_time_utc:
                if first_offload_date is None or log.offload_start_time_utc < first_offload_date:
                    first_offload_date = log.offload_start_time_utc
                if last_offload_date is None or log.offload_start_time_utc > last_offload_date:
                    last_offload_date = log.offload_start_time_utc
            
            if log.offload_end_time_utc:
                if first_offload_date is None or log.offload_end_time_utc < first_offload_date:
                    first_offload_date = log.offload_end_time_utc
                if last_offload_date is None or log.offload_end_time_utc > last_offload_date:
                    last_offload_date = log.offload_end_time_utc
            
            # Count success/failure at log level
            if log.was_offloaded is True:
                successful_offloads += 1
            elif log.was_offloaded is False:
                failed_offloads += 1
            elif log.offload_start_time_utc is not None:
                # Has start time but was_offloaded is None or not True → assume failed
                # This catches cases where an offload was attempted but no confirmation was received
                failed_offloads += 1
            
            # Calculate time at station
            if log.arrival_date and log.departure_date:
                time_diff = log.departure_date - log.arrival_date
                if isinstance(time_diff, timedelta):
                    total_time_at_station_seconds.append(time_diff.total_seconds())
        
        total_offload_attempts = len(offload_logs)
        success_rate = (
            (successful_offloads / total_offload_attempts * 100)
            if total_offload_attempts > 0
            else 0.0
        )
        
        average_time_at_station_hours = (
            sum(total_time_at_station_seconds) / len(total_time_at_station_seconds) / 3600
            if total_time_at_station_seconds
            else None
        )
        
        # Calculate success rates by type
        success_rate_by_type = {}
        for station_type, counts in success_by_type.items():
            total = counts["total"]
            if total > 0:
                success_rate_by_type[station_type] = {
                    "total": total,
                    "successful": counts["successful"],
                    "failed": counts["failed"],
                    "skipped": counts["skipped"],
                    "success_rate": round((counts["successful"] / total * 100), 2) if total > 0 else 0.0
                }
        
        # Calculate success rates by mission
        success_rate_by_mission = {}
        for mission_id, counts in success_by_mission.items():
            total = counts["total"]
            if total > 0:
                success_rate_by_mission[mission_id] = {
                    "total": total,
                    "successful": counts["successful"],
                    "failed": counts["failed"],
                    "skipped": counts["skipped"],
                    "success_rate": round((counts["successful"] / total * 100), 2) if total > 0 else 0.0
                }
        
        # Convert datetime objects to ISO format strings for JSON serialization
        first_offload_date_str = (
            first_offload_date.isoformat() if first_offload_date else None
        )
        last_offload_date_str = (
            last_offload_date.isoformat() if last_offload_date else None
        )
        
        # Log summary for debugging
        logger.info(
            f"Season {year} statistics: "
            f"{len(stations)} total stations, "
            f"{failed_stations} failed stations, "
            f"{skipped_stations} skipped stations, "
            f"{total_offload_attempts} total offload attempts, "
            f"{successful_offloads} successful, {failed_offloads} failed"
        )
        
        # Calculate summary statistics for attempts
        total_attempts_all_stations = sum(details["attempt_count"] for details in station_attempt_details.values())
        stations_with_attempts = sum(1 for details in station_attempt_details.values() if details["attempt_count"] > 0)
        stations_with_multiple_attempts = sum(1 for details in station_attempt_details.values() if details["attempt_count"] > 1)
        avg_attempts_per_station = (
            total_attempts_all_stations / len(stations) if stations else 0
        )
        
        return {
            "year": year,
            "total_stations": len(stations),
            "stations_by_type": dict(stations_by_type),
            "total_offload_attempts": total_offload_attempts,
            "successful_offloads": successful_offloads,
            "failed_offloads": failed_offloads,
            "failed_stations": failed_stations,
            "failed_station_ids": sorted(failed_station_ids),  # For feedback: which stations failed
            "skipped_stations": skipped_stations,
            "success_rate": round(success_rate, 2),
            "average_time_at_station_hours": (
                round(average_time_at_station_hours, 2)
                if average_time_at_station_hours is not None
                else None
            ),
            "unique_stations_deployed": len(unique_stations),
            "first_offload_date": first_offload_date_str,
            "last_offload_date": last_offload_date_str,
            "success_by_station_type": success_rate_by_type,
            "success_by_mission": success_rate_by_mission,
            "remote_health_logs_with_data": remote_health_logs_with_data,
            "remote_health_stations_with_data": len(remote_health_stations_with_data),
            # Offload attempt tracking
            "total_connection_attempts": total_attempts_all_stations,
            "stations_with_attempts": stations_with_attempts,
            "stations_with_multiple_attempts": stations_with_multiple_attempts,
            "average_attempts_per_station": round(avg_attempts_per_station, 2),
            "station_attempt_details": station_attempt_details,  # Detailed per-station attempt info
        }

    @staticmethod
    def _extract_station_type(station_id: str) -> str:
        """Extract station type prefix from station ID (e.g., 'CBS' from 'CBS001')."""
        if not station_id:
            return "UNKNOWN"
        
        # Find the first numeric character
        for i, char in enumerate(station_id):
            if char.isdigit():
                return station_id[:i].upper() if i > 0 else "UNKNOWN"
        
        # If no numbers found, return the whole ID
        return station_id.upper()

    @staticmethod
    def close_season(
        session: SQLModelSession, year: int, closed_by_username: str
    ) -> FieldSeason:
        """
        Close a field season: freeze registry rows into season snapshots, stamp offload
        logs with the season year, persist summary statistics. Live registry rows are not
        mass-archived.
        """
        season = StationSeasonService.get_season_by_year(session, year)
        if not season:
            season = StationSeasonService.create_season(session, year, is_active=False)

        if season.closed_at_utc:
            raise ValueError(f"Season {year} is already closed")

        statistics = StationSeasonService.calculate_season_statistics(session, year)

        archive_time = datetime.now(timezone.utc)
        station_statement = select(StationMetadata).order_by(StationMetadata.station_id)
        stations = list(session.exec(station_statement).all())

        for station in stations:
            snapshot_row = StationMetadataSeasonSnapshot(
                field_season_year=season.year,
                station_id=station.station_id,
                serial_number=station.serial_number,
                modem_address=station.modem_address,
                bottom_depth_m=station.bottom_depth_m,
                waypoint_number=station.waypoint_number,
                last_offload_by_glider=station.last_offload_by_glider,
                station_settings=station.station_settings,
                deployment_latitude=station.deployment_latitude,
                deployment_longitude=station.deployment_longitude,
                notes=station.notes,
                last_offload_timestamp_utc=station.last_offload_timestamp_utc,
                was_last_offload_successful=station.was_last_offload_successful,
                display_status_override=station.display_status_override,
                is_archived=True,
                archived_at_utc=archive_time,
                snapshot_created_at_utc=archive_time,
            )
            session.add(snapshot_row)

        offload_statement = select(OffloadLog).where(
            (OffloadLog.field_season_year.is_(None))
            | (OffloadLog.field_season_year == year)
        )
        offload_logs = list(session.exec(offload_statement).all())

        for log in offload_logs:
            if log.field_season_year is None:
                log.field_season_year = season.year
            session.add(log)

        season.is_active = False
        season.closed_at_utc = archive_time
        season.closed_by_username = closed_by_username
        season.summary_statistics = statistics
        session.add(season)

        session.commit()
        session.refresh(season)

        logger.info(
            f"Season {year} closed by {closed_by_username}. "
            f"Snapshotted {len(stations)} registry rows; stamped {len(offload_logs)} offload logs."
        )

        return season

    @staticmethod
    def reprocess_season_statistics(
        session: SQLModelSession, year: int
    ) -> FieldSeason:
        """
        Recalculate and save summary statistics for a closed season.
        Only applies to seasons that are already closed.

        Args:
            session: Database session
            year: Year of the closed season

        Returns:
            The updated FieldSeason record with new summary_statistics
        """
        season = StationSeasonService.get_season_by_year(session, year)
        if not season:
            raise ValueError(f"Season {year} not found")
        if not season.closed_at_utc:
            raise ValueError(f"Season {year} is not closed; reprocess is only for closed seasons")

        statistics = StationSeasonService.calculate_season_statistics(session, year)
        season.summary_statistics = statistics
        session.add(season)
        session.commit()
        session.refresh(season)

        logger.info(f"Reprocessed statistics for closed season {year}.")
        return season

    @staticmethod
    def prepare_master_list_for_next_season(
        session: SQLModelSession, _current_year: int
    ) -> List[Dict[str, Any]]:
        """
        Export current live registry (non-retired) for CSV editing.
        The ``_current_year`` parameter is kept for URL compatibility only.
        """
        station_statement = (
            select(StationMetadata)
            .where(
                StationMetadata.is_retired == False,
                StationMetadata.is_archived == False,
            )
            .order_by(StationMetadata.station_id)
        )
        stations = list(session.exec(station_statement).all())
        return [
            {
                "station_id": s.station_id,
                "serial_number": s.serial_number,
                "modem_address": s.modem_address,
                "bottom_depth_m": s.bottom_depth_m,
                "waypoint_number": s.waypoint_number,
                "station_settings": s.station_settings,
                "deployment_latitude": s.deployment_latitude,
                "deployment_longitude": s.deployment_longitude,
                "notes": s.notes,
            }
            for s in stations
        ]

    @staticmethod
    def get_stations_for_season(
        session: SQLModelSession, _year: Optional[int]
    ) -> List[models.StationMetadataRead]:
        """Live registry stations in ops (non-retired). Path ``year`` is informational only."""
        statement = (
            select(StationMetadata)
            .where(
                StationMetadata.is_retired == False,
                StationMetadata.is_archived == False,
            )
            .order_by(StationMetadata.station_id)
        )
        rows = list(session.exec(statement).all())
        return [models.StationMetadataRead.model_validate(s) for s in rows]

    @staticmethod
    def get_offload_logs_for_season(
        session: SQLModelSession,
        year: Optional[int],
        station_type: Optional[str] = None,
    ) -> List[OffloadLog]:
        """
        Get all offload logs for a given season, optionally filtered by station type.
        
        Args:
            session: Database session
            year: Season year (None for active season)
            station_type: Optional station type prefix to filter by (e.g., 'CBS', 'NCAT')
        """
        season_row = _season_row(session, year) if year is not None else None
        season_is_closed = bool(season_row and season_row.closed_at_utc)
        if year is None:
            active = StationSeasonService.get_active_season(session)
            if active and not active.closed_at_utc:
                statement = select(OffloadLog).where(
                    (OffloadLog.field_season_year == active.year)
                    | (OffloadLog.field_season_year.is_(None))
                )
            else:
                statement = select(OffloadLog).where(
                    OffloadLog.field_season_year.is_(None)
                )
        else:
            statement = _season_logs_query(year, season_is_closed)

        logs = list(session.exec(statement).all())
        
        # Filter by station type if provided
        if station_type:
            station_type_upper = station_type.upper()
            logs = [
                log
                for log in logs
                if log.station_id and log.station_id.upper().startswith(station_type_upper)
            ]
        
        return logs
