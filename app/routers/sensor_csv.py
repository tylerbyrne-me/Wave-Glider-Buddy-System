"""
Unified CSV download router for all sensor cards
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from datetime import datetime, timedelta
import io
import pandas as pd

from ..auth_utils import get_current_active_user
from ..core.models import User
from ..core import processors

router = APIRouter(prefix="/api/sensor_csv", tags=["sensor-csv"])

# Mapping of sensor types to their preprocessor functions
SENSOR_PROCESSORS = {
    "telemetry": processors.preprocess_telemetry_df,
    "power": processors.preprocess_power_df,
    "ctd": processors.preprocess_ctd_df,
    "weather": processors.preprocess_weather_df,
    "waves": processors.preprocess_wave_df,
    "vr2c": processors.preprocess_vr2c_df,
    "fluorometer": processors.preprocess_fluorometer_df,
    "wg_vm4": processors.preprocess_wg_vm4_df,
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
        raise HTTPException(status_code=400, detail=f"Invalid sensor type: {sensor_type}")
    
    try:
        # Import the load_data_source function from app.py
        from ..app import load_data_source
        
        # Load sensor data using the same method as the dashboard
        sensor_df, _ = await load_data_source(sensor_type, mission_id=mission, current_user=current_user)
        if sensor_df is None or sensor_df.empty:
            raise HTTPException(status_code=404, detail=f"No {SENSOR_NAMES[sensor_type]} data found for this mission")
        
        # Preprocess the data using the same logic as the dashboard
        preprocessor = SENSOR_PROCESSORS[sensor_type]
        processed_df = preprocessor(sensor_df)
        
        if processed_df.empty:
            raise HTTPException(status_code=404, detail=f"No processed {SENSOR_NAMES[sensor_type]} data available")
        
        # Apply time filtering if hours_back is specified
        if hours_back > 0 and 'Timestamp' in processed_df.columns:
            cutoff_time = datetime.now() - timedelta(hours=hours_back)
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
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating {SENSOR_NAMES[sensor_type]} CSV: {str(e)}")
