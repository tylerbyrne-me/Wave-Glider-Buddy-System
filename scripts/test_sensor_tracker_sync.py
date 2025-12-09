"""
Test script for Sensor Tracker sync service.

This script tests the sync service to verify that priority metadata fields
(agencies, agencies_role, deployment_comment, acknowledgement) are being
populated correctly in the database.

Usage:
    python scripts/test_sensor_tracker_sync.py <mission_id>
    
Examples:
    python scripts/test_sensor_tracker_sync.py 1070-m216
    python scripts/test_sensor_tracker_sync.py m216
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.sensor_tracker_sync_service import SensorTrackerSyncService, SENSOR_TRACKER_AVAILABLE
from app.core.db import get_db_session
from sqlmodel import select
from app.core import models


async def test_sync(mission_id: str, force_refresh: bool = True):
    """
    Test syncing Sensor Tracker data and verify priority fields are populated.
    
    Args:
        mission_id: Mission ID (e.g., "1070-m216" or "m216")
        force_refresh: Whether to force refresh the data
    """
    
    if not SENSOR_TRACKER_AVAILABLE:
        print("ERROR: sensor_tracker_client is not installed.")
        return
    
    print(f"\n{'='*60}")
    print(f"Testing Sensor Tracker Sync for Mission: {mission_id}")
    print(f"{'='*60}\n")
    
    # Get database session
    session_gen = get_db_session()
    session = next(session_gen)
    
    try:
        # Check if deployment already exists
        mission_base = mission_id.split('-')[-1] if '-' in mission_id else mission_id
        existing = session.exec(
            select(models.SensorTrackerDeployment).where(
                models.SensorTrackerDeployment.mission_id == mission_id
            )
        ).first()
        
        if existing:
            print(f"Found existing deployment record:")
            print(f"  Mission ID: {existing.mission_id}")
            print(f"  Deployment Number: {existing.deployment_number}")
            print(f"  Last Synced: {existing.last_synced_at}")
            print(f"  Sync Status: {existing.sync_status}")
            print()
        
        # Perform sync
        print(f"Syncing Sensor Tracker data (force_refresh={force_refresh})...")
        sync_service = SensorTrackerSyncService()
        deployment = await sync_service.get_or_sync_mission(
            mission_id=mission_id,
            force_refresh=force_refresh,
            session=session
        )
        
        if not deployment:
            print("❌ Sync failed - no deployment returned")
            return
        
        # Refresh from database to get latest data
        session.refresh(deployment)
        
        print("\n" + "="*60)
        print("SYNC RESULTS - Priority Metadata Fields (Phase 1A)")
        print("="*60)
        
        # Check priority fields
        priority_fields = [
            ("Agencies", deployment.agencies),
            ("Agencies Role", deployment.agencies_role),
            ("Deployment Comment", deployment.deployment_comment),
            ("Acknowledgement", deployment.acknowledgement),
        ]
        
        all_populated = True
        for field_name, field_value in priority_fields:
            if field_value:
                # Truncate long values for display
                display_value = str(field_value)
                if len(display_value) > 100:
                    display_value = display_value[:100] + "..."
                print(f"✓ {field_name}: {display_value}")
            else:
                print(f"⚠ {field_name}: (empty/null)")
                all_populated = False
        
        print("\n" + "="*60)
        print("SYNC RESULTS - Additional Metadata Fields (Phase 1B)")
        print("="*60)
        
        # Check Phase 1B fields
        phase1b_fields = [
            ("Deployment Cruise", deployment.deployment_cruise),
            ("Recovery Cruise", deployment.recovery_cruise),
            ("Deployment Personnel", deployment.deployment_personnel),
            ("Recovery Personnel", deployment.recovery_personnel),
            ("Data Repository Link", deployment.data_repository_link),
            ("Publisher Name", deployment.publisher_name),
            ("Publisher URL", deployment.publisher_url),
            ("Program", deployment.program),
            ("Sea Name", deployment.sea_name),
            ("Transmission System", deployment.transmission_system),
            ("Positioning System", deployment.positioning_system),
        ]
        
        phase1b_populated = 0
        for field_name, field_value in phase1b_fields:
            if field_value:
                display_value = str(field_value)
                if len(display_value) > 80:
                    display_value = display_value[:80] + "..."
                print(f"✓ {field_name}: {display_value}")
                phase1b_populated += 1
            else:
                print(f"⚠ {field_name}: (empty/null)")
        
        print(f"\nPhase 1B Fields Populated: {phase1b_populated}/{len(phase1b_fields)}")
        
        print("\n" + "="*60)
        print("Additional Information")
        print("="*60)
        print(f"Mission ID: {deployment.mission_id}")
        print(f"Deployment Number: {deployment.deployment_number}")
        print(f"Title: {deployment.title}")
        print(f"Platform: {deployment.platform_name}")
        print(f"Sync Status: {deployment.sync_status}")
        print(f"Last Synced: {deployment.last_synced_at}")
        
        # Check if full_metadata has the data
        if deployment.full_metadata:
            program_info = deployment.full_metadata.get("program_info", {})
            attribution = deployment.full_metadata.get("attribution", {})
            comment = deployment.full_metadata.get("comment")
            
            print("\n" + "="*60)
            print("Verification - Data in full_metadata")
            print("="*60)
            print(f"Agencies (from program_info): {program_info.get('agencies', 'N/A')}")
            print(f"Agencies Role (from program_info): {program_info.get('agencies_role', 'N/A')}")
            print(f"Comment (from top-level): {'Present' if comment else 'Missing'}")
            print(f"Acknowledgement (from attribution): {attribution.get('acknowledgement', 'N/A')}")
        
        print("\n" + "="*60)
        if all_populated:
            print("✓ SUCCESS: All priority fields are populated!")
        else:
            print("⚠ WARNING: Some priority fields are empty (this may be expected)")
        print("="*60)
        
    except Exception as e:
        print(f"\n❌ ERROR during sync test: {e}")
        import traceback
        traceback.print_exc()
    finally:
        session.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/test_sensor_tracker_sync.py <mission_id>")
        print("Example: python scripts/test_sensor_tracker_sync.py 1070-m216")
        sys.exit(1)
    
    mission_id = sys.argv[1]
    force_refresh = "--force" in sys.argv or "-f" in sys.argv
    
    asyncio.run(test_sync(mission_id, force_refresh=force_refresh))

