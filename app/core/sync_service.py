"""
Mission Data Sync Service

Syncs mission data from remote servers to local storage.
This service ensures local storage is kept up-to-date with remote data.
"""

import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple, List
import httpx
import pandas as pd

from ..config import settings
from . import loaders

logger = logging.getLogger(__name__)


async def sync_mission_file(
    report_type: str,
    mission_id: str,
    is_realtime: bool = True,
    client: Optional[httpx.AsyncClient] = None
) -> Tuple[bool, Optional[datetime]]:
    """
    Sync a single report file from remote to local storage.
    
    Args:
        report_type: Type of report (e.g., 'power', 'ctd')
        mission_id: Mission identifier
        is_realtime: True for realtime missions, False for past missions
        client: Optional httpx client (will create one if not provided)
        
    Returns:
        Tuple of (success: bool, file_modification_time: Optional[datetime])
    """
    # Determine remote URL
    base_remote_url = settings.remote_data_url.rstrip("/")
    remote_folder = "output_realtime_missions" if is_realtime else "output_past_missions"
    remote_base_url = f"{base_remote_url}/{remote_folder}"
    
    # Determine local path
    mission_folder = settings.local_data_base_path / mission_id
    mission_folder.mkdir(parents=True, exist_ok=True)
    
    # Get filename for this report type
    reports = {
        "power": "Amps Power Summary Report.csv",
        "solar": "Amps Solar Input Port Report.csv",
        "ctd": "Seabird CTD Records with D.O..csv",
        "weather": "Weather Records 2.csv",
        "waves": "GPS Waves Sensor Data.csv",
        "ais": "AIS Report.csv",
        "telemetry": "Telemetry 6 Report by WGMS Datetime.csv",
        "errors": "Vehicle Error Report.csv",
        "vr2c": "Vemco VR2c Status.csv",
        "fluorometer": "Fluorometer Samples 2.csv",
        "wave_frequency_spectrum": "GPS Waves Frequency Spectrum.csv",
        "wave_energy_spectrum": "GPS Waves Energy Spectrum.csv",
        "wg_vm4": "Vemco VM4 Daily Local Health.csv",
        "wg_vm4_info": "Vemco VM4 Information.csv",
    }
    
    if report_type not in reports:
        logger.warning(f"Unknown report type for sync: {report_type}")
        return False, None
    
    filename = reports[report_type]
    local_file_path = mission_folder / filename
    remote_url = f"{remote_base_url}/{mission_id}/{filename}"
    
    # Check if local file exists and get its modification time
    local_mtime = None
    if local_file_path.exists():
        try:
            local_mtime = datetime.fromtimestamp(
                local_file_path.stat().st_mtime, tz=timezone.utc
            )
        except OSError:
            pass
    
    # Use provided client or create one
    use_provided_client = client is not None
    if not use_provided_client:
        retry_transport = httpx.AsyncHTTPTransport(retries=loaders.RETRY_COUNT)
        client = httpx.AsyncClient(transport=retry_transport, timeout=loaders.DEFAULT_TIMEOUT)
    
    try:
        # Download file from remote
        logger.debug(f"Syncing {report_type} for {mission_id} from {remote_url} to {local_file_path}")
        response = await client.get(remote_url)
        response.raise_for_status()
        
        # Get remote file modification time from Last-Modified header
        remote_mtime = None
        last_modified_header = response.headers.get("Last-Modified")
        if last_modified_header:
            try:
                from email.utils import parsedate_to_datetime
                remote_mtime = parsedate_to_datetime(last_modified_header)
                if remote_mtime.tzinfo is None:
                    remote_mtime = remote_mtime.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError) as e:
                logger.debug(f"Could not parse Last-Modified header: {e}")
        
        # Check if remote file is newer than local (or local doesn't exist)
        should_sync = True
        if local_mtime and remote_mtime:
            if remote_mtime <= local_mtime:
                should_sync = False
                logger.debug(
                    f"Local file for {report_type} ({mission_id}) is up-to-date. "
                    f"Local: {local_mtime}, Remote: {remote_mtime}"
                )
        
        if should_sync:
            # Write to temporary file first (atomic operation)
            temp_file_path = local_file_path.with_suffix('.tmp')
            temp_file_path.write_text(response.text, encoding='utf-8')
            
            # Validate the file can be parsed as CSV
            try:
                pd.read_csv(temp_file_path, nrows=1)  # Quick validation
            except pd.errors.ParserError as e:
                logger.error(f"Downloaded file for {report_type} ({mission_id}) is not valid CSV: {e}")
                temp_file_path.unlink()
                return False, None
            
            # Atomic rename (replaces existing file)
            temp_file_path.replace(local_file_path)
            
            # Update file modification time to match remote
            if remote_mtime:
                try:
                    import os
                    os.utime(local_file_path, (remote_mtime.timestamp(), remote_mtime.timestamp()))
                except OSError:
                    pass  # Not critical if we can't set mtime
            
            logger.info(
                f"Synced {report_type} for {mission_id}: {len(response.text)} bytes "
                f"(remote mtime: {remote_mtime})"
            )
            return True, remote_mtime
        else:
            return True, local_mtime  # Already up-to-date
        
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            logger.debug(f"File not found on remote: {remote_url} (mission may not exist)")
        else:
            logger.warning(f"HTTP error syncing {report_type} for {mission_id}: {e}")
        return False, None
    except httpx.RequestError as e:
        logger.warning(f"Request error syncing {report_type} for {mission_id}: {e}")
        return False, None
    except Exception as e:
        logger.error(f"Unexpected error syncing {report_type} for {mission_id}: {e}", exc_info=True)
        return False, None
    finally:
        if not use_provided_client and client:
            await client.aclose()


async def sync_mission(
    mission_id: str,
    is_realtime: bool = True,
    report_types: Optional[List[str]] = None
) -> Tuple[int, int]:
    """
    Sync all report types for a mission from remote to local.
    
    Args:
        mission_id: Mission identifier
        is_realtime: True for realtime missions, False for past missions
        report_types: Optional list of report types to sync (defaults to all incremental types)
        
    Returns:
        Tuple of (successful_syncs: int, failed_syncs: int)
    """
    from .data_service import CACHE_STRATEGIES
    
    if report_types is None:
        # Default to all incremental report types
        report_types = [
            rt for rt, strategy in CACHE_STRATEGIES.items()
            if strategy.get("incremental", False)
        ]
    
    logger.info(f"SYNC: Starting sync for mission {mission_id} (realtime={is_realtime})")
    
    # Create shared HTTP client for efficiency
    retry_transport = httpx.AsyncHTTPTransport(retries=loaders.RETRY_COUNT)
    async with httpx.AsyncClient(transport=retry_transport, timeout=loaders.DEFAULT_TIMEOUT) as client:
        successful = 0
        failed = 0
        
        for report_type in report_types:
            success, _ = await sync_mission_file(
                report_type, mission_id, is_realtime, client
            )
            if success:
                successful += 1
            else:
                failed += 1
    
    logger.info(
        f"SYNC: Completed sync for {mission_id}: {successful} successful, {failed} failed"
    )
    return successful, failed


async def sync_all_realtime_missions() -> dict:
    """
    Sync all real-time missions from remote to local.
    
    Returns:
        Dictionary mapping mission_id to (successful, failed) sync counts
    """
    results = {}
    # Filter out empty strings and whitespace-only mission IDs
    active_missions = [m for m in settings.active_realtime_missions if m and m.strip()]
    
    if not active_missions:
        logger.warning("SYNC: No valid active real-time missions found. Skipping sync.")
        return results
    
    logger.info(f"SYNC: Syncing {len(active_missions)} real-time missions")
    
    for mission_id in active_missions:
        successful, failed = await sync_mission(mission_id, is_realtime=True)
        results[mission_id] = {"successful": successful, "failed": failed}
    
    return results


async def sync_past_mission(mission_id: str) -> Tuple[int, int]:
    """
    Sync a past mission from remote to local (on-demand).
    
    Args:
        mission_id: Mission identifier
        
    Returns:
        Tuple of (successful_syncs: int, failed_syncs: int)
    """
    return await sync_mission(mission_id, is_realtime=False)



