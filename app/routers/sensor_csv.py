"""
Unified CSV download router for all sensor cards
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from datetime import datetime, timedelta, timezone
import io
import pandas as pd

from ..core.auth import get_current_active_user
from ..core.models import User
from ..core import processors
from ..core.processor_framework import get_processor_registry
from ..core.error_handlers import handle_processing_error, handle_validation_error, ErrorContext

router = APIRouter(prefix="/api/sensor_csv", tags=["sensor-csv"])

# Get processor registry for dynamic processor lookup
_processor_registry = get_processor_registry()

# Mapping of sensor types to their preprocessor functions
# Use registry for consistency, with fallback to direct imports for backward compatibility
SENSOR_PROCESSORS = {
    "telemetry": _processor_registry.get("telemetry") or processors.preprocess_telemetry_df,
    "power": _processor_registry.get("power") or processors.preprocess_power_df,
    "ctd": _processor_registry.get("ctd") or processors.preprocess_ctd_df,
    "weather": _processor_registry.get("weather") or processors.preprocess_weather_df,
    "waves": _processor_registry.get("waves") or processors.preprocess_wave_df,
    "vr2c": _processor_registry.get("vr2c") or processors.preprocess_vr2c_df,
    "fluorometer": _processor_registry.get("fluorometer") or processors.preprocess_fluorometer_df,
    "wg_vm4": _processor_registry.get("wg_vm4") or processors.preprocess_wg_vm4_df,
}

# Mapping of sensor types to their display names
SENSOR_NAMES = {
    "telemetry": "Navigation",
    "power": "Power",
    "ctd": "CTD",
    "weather": "Weather",
    "waves": "Waves",
    "vr2c": "VR2C",
    "fluorometer": "Fluorometer",
    "wg_vm4": "WG-VM4",
}

@router.get("/{sensor_type}")
async def download_sensor_csv(
    sensor_type: str,
    mission: str = Query(..., description="Mission name"),
    hours_back: int = Query(24, description="Number of hours to look back"),
    granularity_minutes: int = Query(15, description="Data resampling interval in minutes"),
    current_user: User = Depends(get_current_active_user)
):
    """Download sensor data as CSV"""
    
    # Validate sensor type
    if sensor_type not in SENSOR_PROCESSORS:
        raise handle_validation_error(
            message=f"Invalid sensor type: {sensor_type}. Valid types: {', '.join(SENSOR_PROCESSORS.keys())}",
            field="sensor_type"
        )
    
    try:
        # Use data service with consolidated load_and_preprocess helper
        from ..core.data_service import get_data_service
        
        data_service = get_data_service()
        preprocessor = SENSOR_PROCESSORS[sensor_type]
        
        # Load, preprocess, and validate in one call
        processed_df, _ = await data_service.load_and_preprocess(
            report_type=sensor_type,
            mission_id=mission,
            preprocess_func=preprocessor,
            error_message=f"No {SENSOR_NAMES[sensor_type]} data found for this mission",
            preprocessed_error_message=f"No processed {SENSOR_NAMES[sensor_type]} data available",
            current_user=current_user
        )
        
        # Apply time filtering if hours_back is specified - always use UTC
        if hours_back > 0 and 'Timestamp' in processed_df.columns:
            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours_back)
            # Convert cutoff_time to pandas Timestamp for proper comparison
            cutoff_timestamp = pd.Timestamp(cutoff_time, tz='UTC')
            processed_df = processed_df[processed_df['Timestamp'] >= cutoff_timestamp]
        
        # Apply granularity filtering if specified
        if granularity_minutes > 0 and 'Timestamp' in processed_df.columns:
            # Resample data to the specified granularity
            processed_df = processed_df.set_index('Timestamp')
            # Only resample numeric columns, keep non-numeric columns as first occurrence
            numeric_cols = processed_df.select_dtypes(include=['number']).columns
            non_numeric_cols = processed_df.select_dtypes(exclude=['number']).columns
            
            if len(numeric_cols) > 0:
                # Resample numeric columns with mean
                numeric_resampled = processed_df[numeric_cols].resample(f'{granularity_minutes}min').mean()
                
                if len(non_numeric_cols) > 0:
                    # For non-numeric columns, take the first occurrence
                    non_numeric_resampled = processed_df[non_numeric_cols].resample(f'{granularity_minutes}min').first()
                    processed_df = pd.concat([numeric_resampled, non_numeric_resampled], axis=1)
                else:
                    processed_df = numeric_resampled
            else:
                # If no numeric columns, just take first occurrence
                processed_df = processed_df.resample(f'{granularity_minutes}min').first()
            
            processed_df = processed_df.reset_index()
        
        # Create CSV
        output = io.StringIO()
        
        # Convert DataFrame to CSV
        processed_df.to_csv(output, index=False)
        
        output.seek(0)
        content = output.getvalue()
        
        # Generate filename
        sensor_name = SENSOR_NAMES[sensor_type].lower().replace(' ', '_')
        filename = f"{sensor_name}_{mission}_{hours_back}h_{granularity_minutes}min_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        return StreamingResponse(
            io.BytesIO(content.encode("utf-8")), 
            media_type="text/csv", 
            headers={"Content-Disposition": f"attachment; filename=\"{filename}\""}
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise handle_processing_error(
            operation=f"generating {SENSOR_NAMES[sensor_type]} CSV",
            error=e,
            resource=mission,
            user_id=str(current_user.id) if current_user else None
        )
