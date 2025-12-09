"""
Test script for Sensor Tracker integration.

This script demonstrates how to:
1. Connect to Sensor Tracker
2. Fetch a deployment
3. Parse the deployment data

Usage:
    python scripts/test_sensor_tracker.py <identifier>
    
Examples:
    python scripts/test_sensor_tracker.py 4291          # By deployment ID
    python scripts/test_sensor_tracker.py 216           # By mission number
    python scripts/test_sensor_tracker.py m216          # By mission ID
"""

import asyncio
import sys
import json
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.sensor_tracker_service import SensorTrackerService, SENSOR_TRACKER_AVAILABLE


async def test_sensor_tracker(deployment_identifier: str):
    """
    Test fetching and parsing a deployment from Sensor Tracker.
    
    Args:
        deployment_identifier: Can be:
            - A deployment ID (e.g., "4291")
            - A mission number (e.g., "216")
            - A mission ID (e.g., "m216")
    """
    
    if not SENSOR_TRACKER_AVAILABLE:
        print("ERROR: sensor_tracker_client is not installed.")
        print("Install with: pip install git+https://gitlab.oceantrack.org/ceotr/metadata-tracker/sensor_tracker_client.git")
        return
    
    try:
        # Initialize service
        # Skip auth if there are library compatibility issues
        print("Initializing Sensor Tracker service...")
        try:
            service = SensorTrackerService(skip_auth=False)
        except Exception as auth_error:
            print(f"Warning: Authentication setup failed: {auth_error}")
            print("Retrying without authentication (GET operations should still work)...")
            service = SensorTrackerService(skip_auth=True)
        
        # Test connection
        print("\nTesting connection...")
        # Get host URL from the service's internal stc reference
        try:
            from sensor_tracker_client import sensor_tracker_client as stc
            print(f"  Host URL: {stc.HOST}")
        except:
            print(f"  Host URL: Unable to determine")
        connection_ok = service.test_connection()
        if connection_ok:
            print("✓ Connection successful!")
        else:
            print("⚠ Connection test had issues, but continuing anyway...")
            print("  (GET operations may still work without authentication)")
            print("  If you get 404 errors, the host URL might be incorrect.")
        
        # Determine if identifier is a mission number/ID or deployment ID
        # Try to detect mission ID format (m216) or assume it's a mission number if it's a small number
        deployment_data = None
        identifier_type = None
        
        # Check if it's a mission ID (starts with 'm' or 'M')
        deployment_identifier_str = str(deployment_identifier)
        if deployment_identifier_str.lower().startswith('m'):
            print(f"\nFetching deployment by mission ID: {deployment_identifier}...")
            identifier_type = "mission_id"
            try:
                deployment_data = await service.fetch_deployment_by_mission_id(deployment_identifier)
            except Exception as e:
                print(f"✗ Error fetching by mission ID: {e}")
        else:
            # Try as mission number first (if it's a reasonable number)
            try:
                mission_num = int(deployment_identifier)
                # If it's a small number (< 10000), assume it's a mission number
                # (deployment IDs are typically much larger)
                if mission_num < 10000:
                    print(f"\nFetching deployment by mission number: {mission_num}...")
                    identifier_type = "mission_number"
                    try:
                        deployment_data = await service.fetch_deployment_by_number(mission_num)
                    except Exception as e:
                        print(f"✗ Error fetching by mission number: {e}")
                        print(f"  Trying as deployment ID instead...")
                        identifier_type = "deployment_id"
                        deployment_data = await service.fetch_deployment(mission_num)
                else:
                    # Large number, assume it's a deployment ID
                    print(f"\nFetching deployment by ID: {mission_num}...")
                    identifier_type = "deployment_id"
                    deployment_data = await service.fetch_deployment(mission_num)
            except ValueError:
                # Not a number, try as deployment ID string
                print(f"\nFetching deployment by ID: {deployment_identifier}...")
                identifier_type = "deployment_id"
                try:
                    deployment_data = await service.fetch_deployment(int(deployment_identifier))
                except ValueError:
                    print(f"✗ Invalid identifier format: {deployment_identifier}")
                    print("  Expected: deployment ID (number), mission number (number), or mission ID (m216)")
                    return
        
        if not deployment_data:
            print(f"✗ Deployment not found using {identifier_type}: {deployment_identifier}")
            print("\nTrying to list available deployments...")
            try:
                # Try to list some deployments to see what's available
                deployments = await service.list_all_deployments(limit=10)
                if deployments:
                    print(f"\n✓ Found {len(deployments)} deployment(s). Here are some examples:")
                    for dep in deployments[:5]:  # Show first 5
                        dep_id = dep.get('id', 'N/A')
                        dep_num = dep.get('deployment_number', 'N/A')
                        title = dep.get('title', 'N/A')
                        print(f"  - Deployment ID: {dep_id}, Mission: {dep_num}, Title: {title}")
                else:
                    print("  No deployments found.")
            except Exception as list_error:
                print(f"  Could not list deployments: {list_error}")
            return
        
        # Show what we found
        deployment_id = deployment_data.get('id')
        deployment_number = deployment_data.get('deployment_number')
        print(f"✓ Found deployment:")
        print(f"  - Deployment ID: {deployment_id}")
        print(f"  - Mission Number: {deployment_number}")
        print(f"  - Mission ID: m{deployment_number}")
        print(f"✓ Deployment fetched successfully")
        
        # Save raw data for inspection
        output_file = Path(__file__).parent.parent / f"test_data/sensor_tracker_deployment_{deployment_id}_raw.json"
        output_file.parent.mkdir(exist_ok=True)
        with open(output_file, 'w') as f:
            json.dump(deployment_data, f, indent=2, default=str)
        print(f"✓ Raw deployment data saved to: {output_file}")
        
        # Parse deployment
        print("\nParsing deployment data...")
        parsed_deployment = await service.parse_deployment(deployment_data)
        
        # Fetch platform details first (to get platform name)
        if parsed_deployment.get("platform_id"):
            print(f"Fetching platform {parsed_deployment['platform_id']} details...")
            try:
                parsed_deployment = await service.enrich_deployment_with_platform(parsed_deployment)
                print("✓ Platform details fetched")
            except Exception as e:
                print(f"⚠ Could not fetch platform details: {e}")
        
        # Fetch data loggers using the correct API endpoints
        if parsed_deployment.get("platform_id"):
            print(f"\nFetching data loggers for platform...")
            try:
                parsed_deployment = await service.enrich_deployment_with_data_loggers(parsed_deployment)
                print("✓ Data loggers fetched")
            except Exception as e:
                print(f"⚠ Could not fetch data loggers: {e}")
        
        # Save parsed data
        parsed_file = Path(__file__).parent.parent / f"test_data/sensor_tracker_deployment_{deployment_id}_parsed.json"
        with open(parsed_file, 'w') as f:
            json.dump(parsed_deployment, f, indent=2, default=str)
        print(f"✓ Parsed deployment data saved to: {parsed_file}")
        
        # Print summary
        print("\n" + "="*60)
        print("DEPLOYMENT SUMMARY")
        print("="*60)
        print(f"Sensor Tracker Deployment ID: {parsed_deployment.get('sensor_tracker_deployment_id')}")
        print(f"Deployment Number: {parsed_deployment.get('deployment_number')}")
        print(f"Mission ID: {parsed_deployment.get('mission_id')}")
        print(f"Title: {parsed_deployment.get('title')}")
        print(f"\nTiming:")
        print(f"  Start: {parsed_deployment.get('start_time')}")
        print(f"  End: {parsed_deployment.get('end_time')}")
        
        deployment_loc = parsed_deployment.get('deployment_location', {})
        recovery_loc = parsed_deployment.get('recovery_location', {})
        print(f"\nLocation:")
        print(f"  Deployment: ({deployment_loc.get('latitude')}, {deployment_loc.get('longitude')})")
        print(f"  Recovery: ({recovery_loc.get('latitude')}, {recovery_loc.get('longitude')})")
        print(f"  Depth: {parsed_deployment.get('depth')} m")
        
        print(f"\nPlatform ID: {parsed_deployment.get('platform_id')}")
        if "platform" in parsed_deployment:
            platform = parsed_deployment["platform"]
            print(f"Platform Name: {platform.get('platform_name')}")
            print(f"Platform Type: {platform.get('platform_type')}")
        
        # Display data loggers
        data_loggers = parsed_deployment.get('data_loggers', [])
        print(f"\nData Loggers: {len(data_loggers)}")
        for i, logger in enumerate(data_loggers, 1):
            logger_type = logger.get('logger_type', 'unknown')
            instrument_count = logger.get('instrument_count', 0)
            print(f"  {i}. {logger_type.upper()} Logger")
            print(f"     Instruments: {instrument_count}")
            print(f"     Parameters: {len(logger.get('parameters', []))}")
            
            # Show instrument details
            instruments = logger.get('instruments', [])
            if instruments:
                print(f"     Instrument Details:")
                for inst in instruments[:10]:  # Show first 10
                    inst_id = inst.get('instrument_id') or 'N/A'
                    inst_identifier = inst.get('instrument_identifier') or inst.get('instrument_short_name') or 'N/A'
                    inst_serial = inst.get('instrument_serial') or 'N/A'
                    inst_name = inst.get('instrument_name') or inst.get('instrument_short_name') or 'N/A'
                    sensor_count = inst.get('sensor_count', 0)
                    print(f"       - ID: {inst_id}, Identifier: {inst_identifier}, Serial: {inst_serial}, Name: {inst_name}, Sensors: {sensor_count}")
                    
                    # Show sensor details for this instrument
                    sensors = inst.get('sensors', [])
                    if sensors:
                        for sensor in sensors:
                            sensor_id = sensor.get('sensor_id') or 'N/A'
                            sensor_identifier = sensor.get('sensor_identifier') or sensor.get('sensor_short_name') or 'N/A'
                            sensor_serial = sensor.get('sensor_serial') or 'N/A'
                            sensor_name = sensor.get('sensor_short_name') or sensor.get('sensor_long_name') or 'N/A'
                            print(f"         └─ Sensor: ID: {sensor_id}, Identifier: {sensor_identifier}, Serial: {sensor_serial}, Name: {sensor_name}")
        
        program_info = parsed_deployment.get('program_info', {})
        if program_info.get('program'):
            print(f"\nProgram: {program_info.get('program')}")
        
        # Display platform instruments (not attached to data loggers)
        platform_instruments = parsed_deployment.get('platform_instruments', [])
        if platform_instruments:
            print(f"\nPlatform Instruments (direct attachment): {len(platform_instruments)}")
            for inst in platform_instruments[:10]:  # Show first 10
                inst_id = inst.get('instrument_id') or 'N/A'
                inst_identifier = inst.get('instrument_identifier') or inst.get('instrument_short_name') or 'N/A'
                inst_serial = inst.get('instrument_serial') or 'N/A'
                inst_name = inst.get('instrument_name') or inst.get('instrument_short_name') or 'N/A'
                print(f"  - ID: {inst_id}, Identifier: {inst_identifier}, Serial: {inst_serial}, Name: {inst_name}")
        
        print(f"\nTotal Instruments: {len(parsed_deployment.get('instruments', []))}")
        print(f"  - On Data Loggers: {len(parsed_deployment.get('instruments', [])) - len(platform_instruments)}")
        print(f"  - Direct on Platform: {len(platform_instruments)}")
        print(f"Sensors: {len(parsed_deployment.get('sensors', []))}")
        print(f"Sensor-Instrument Links: {len(parsed_deployment.get('sensor_on_instrument', []))}")
        
        print("\n" + "="*60)
        print("✓ Test completed successfully!")
        print(f"\nInspect the JSON files in test_data/ for full details.")
        
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/test_sensor_tracker.py <deployment_id>")
        print("Example: python scripts/test_sensor_tracker.py 123")
        sys.exit(1)
    
    try:
        deployment_id = int(sys.argv[1])
    except ValueError:
        print(f"ERROR: '{sys.argv[1]}' is not a valid deployment ID (must be an integer)")
        sys.exit(1)
    
    asyncio.run(test_sensor_tracker(deployment_id))

