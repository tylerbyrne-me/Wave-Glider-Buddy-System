"""
Explore Sensor Tracker API to understand available endpoints and data.

This script helps debug connection issues and discover available deployments.
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.sensor_tracker_service import SensorTrackerService, SENSOR_TRACKER_AVAILABLE


async def explore_sensor_tracker():
    """Explore the Sensor Tracker API."""
    
    if not SENSOR_TRACKER_AVAILABLE:
        print("ERROR: sensor_tracker_client is not installed.")
        return
    
    try:
        # Initialize service (skip auth if needed)
        print("Initializing Sensor Tracker service...")
        try:
            service = SensorTrackerService(skip_auth=False)
        except Exception as e:
            print(f"Warning: Auth setup failed, continuing without auth: {e}")
            service = SensorTrackerService(skip_auth=True)
        
        # Get host URL from stc
        try:
            from sensor_tracker_client import sensor_tracker_client as stc
            host_url = stc.HOST
            print(f"\nHost URL: {host_url}")
        except:
            print(f"\nHost URL: Unable to determine")
        
        # Test basic endpoints
        print("\n" + "="*60)
        print("TESTING BASIC ENDPOINTS")
        print("="*60)
        
        endpoints_to_test = [
            ("Institutions", lambda: stc.institution.get({"limit": 1})),
            ("Platform Types", lambda: stc.platform_type.get({"limit": 1})),
            ("Manufacturers", lambda: stc.manufacturer.get({"limit": 1})),
            ("Projects", lambda: stc.project.get({"limit": 1})),
        ]
        
        for name, test_func in endpoints_to_test:
            try:
                print(f"\nTesting {name}...")
                response = test_func()
                if response and hasattr(response, 'dict'):
                    data = response.dict
                    print(f"  ✓ {name} endpoint works")
                    if isinstance(data, dict):
                        print(f"    Keys: {list(data.keys())[:5]}")
                    elif isinstance(data, list) and len(data) > 0:
                        print(f"    Returned {len(data)} items")
                        if isinstance(data[0], dict):
                            print(f"    Sample keys: {list(data[0].keys())[:5]}")
                else:
                    print(f"  ⚠ {name} returned no data")
            except Exception as e:
                print(f"  ✗ {name} failed: {e}")
        
        # Try to list deployments
        print("\n" + "="*60)
        print("TESTING DEPLOYMENTS")
        print("="*60)
        
        try:
            print("\nTrying to list deployments (limit 5)...")
            deployments = await service.list_all_deployments(limit=5)
            if deployments:
                print(f"✓ Found {len(deployments)} deployment(s)")
                for i, dep in enumerate(deployments[:5], 1):
                    dep_id = dep.get("id") or dep.get("pk") or dep.get("deployment_id") or "N/A"
                    platform = dep.get("platform_name") or dep.get("platform") or "N/A"
                    start = dep.get("start_time") or dep.get("start") or "N/A"
                    print(f"\n  Deployment {i}:")
                    print(f"    ID: {dep_id}")
                    print(f"    Platform: {platform}")
                    print(f"    Start: {start}")
                    print(f"    All keys: {list(dep.keys())[:10]}")
            else:
                print("⚠ No deployments returned")
        except Exception as e:
            print(f"✗ Failed to list deployments: {e}")
        
        # Try fetching by platform name
        print("\n" + "="*60)
        print("TESTING PLATFORM-BASED FETCH")
        print("="*60)
        
        # Try some common platform name patterns
        test_platforms = ["m211", "m209", "otn200", "dal556"]
        
        for platform_name in test_platforms:
            try:
                print(f"\nTrying platform: {platform_name}...")
                deployments = await service.fetch_deployments_by_platform(platform_name)
                if deployments:
                    print(f"  ✓ Found {len(deployments)} deployment(s) for {platform_name}")
                    for dep in deployments[:2]:  # Show first 2
                        dep_id = dep.get("id") or dep.get("pk") or "N/A"
                        print(f"    - Deployment ID: {dep_id}")
                else:
                    print(f"  ⚠ No deployments found for {platform_name}")
            except Exception as e:
                print(f"  ✗ Failed for {platform_name}: {e}")
        
        print("\n" + "="*60)
        print("EXPLORATION COMPLETE")
        print("="*60)
        print("\nIf you found deployment IDs above, try using them with:")
        print("  python scripts/test_sensor_tracker.py <deployment_id>")
        
    except Exception as e:
        print(f"\n✗ Error during exploration: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # Import stc here to avoid issues if not available
    try:
        from sensor_tracker_client import sensor_tracker_client as stc
    except ImportError:
        print("ERROR: sensor_tracker_client not available")
        sys.exit(1)
    
    asyncio.run(explore_sensor_tracker())

