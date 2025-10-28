# Map Feature Implementation Summary

## ✅ Code Review Complete

After reviewing the existing codebase, I found **no duplication** issues and identified **significant reuse opportunities** for the map feature.

## Key Findings

### 1. Telemetry Data Already Fully Processed
✅ **Location:** `app/core/processors.py:542-590`
- Function: `preprocess_telemetry_df(df)`
- Output columns: `Latitude`, `Longitude`, `Timestamp`, `SpeedOverGround`, `GliderHeading`
- Standardized UTC timestamps
- Already handles missing data gracefully

### 2. Distance Calculation Already Exists
✅ **Location:** `app/reporting.py:32-68`
- Function: `_calculate_telemetry_summary(df)`
- Uses vectorized Haversine formula for performance
- Returns: `total_distance_km`, `avg_speed_knots`
- **Can be directly reused** for track statistics

### 3. Map Plotting Already Implemented
✅ **Location:** `app/core/plotting.py:294-324`
- Function: `plot_telemetry_for_report(ax, df)`
- Uses Cartopy for map projections
- Color-codes by speed (speedOverGround)
- Annotates start/end points
- **Pattern can be adapted** for Leaflet.js

### 4. Data Loading Pattern Established
✅ **Location:** `app/app.py:880-1011`
- Function: `load_data_source()` with caching
- Handles: remote vs local, time filtering, user permissions
- Time-aware caching prevents unnecessary reloads
- **Will be reused directly**

## Column Naming Convention

### ✅ CORRECT APPROACH (Use This)
After preprocessing via `preprocess_telemetry_df()`:
- `Latitude` (capitalized)
- `Longitude` (capitalized)
- `Timestamp` (UTC)
- `SpeedOverGround`
- `GliderHeading`

### ⚠️ BE AWARE
The plotting code in `plotting.py` uses RAW column names (`longitude`, `latitude`, `lastLocationFix`) because it receives unfiltered data from the reporting module. **For the new map feature, we'll use standardized names** to stay consistent with the dashboard pattern.

## No Code Duplication Needed

### Functions We'll Reuse (Not Duplicate):

| What We Need | Where It Exists | How We'll Use It |
|-------------|----------------|------------------|
| Load telemetry data | `app/app.py:880` (`load_data_source`) | Call directly |
| Preprocess data | `app/core/processors.py:542` (`preprocess_telemetry_df`) | Call directly |
| Calculate distance | `app/reporting.py:32` (`_calculate_telemetry_summary`) | Import and reuse |
| Apply time filtering | `app/app.py:2024-2058` (time filtering logic) | Follow same pattern |
| Handle permissions | `app/app.py` (user access control) | Reuse `get_current_active_user` |

### New Functions We'll Create:

| Function | Purpose | Location |
|----------|---------|----------|
| `generate_kml_from_telemetry()` | Convert DataFrame to KML format | `app/core/map_utils.py` |
| `prepare_track_points()` | Extract track with consistent columns | `app/core/map_utils.py` |
| `/api/map/telemetry/{mission_id}` | API endpoint for map data | `app/routers/map_router.py` |
| `/api/map/kml/{mission_id}` | API endpoint for KML download | `app/routers/map_router.py` |

## Implementation Pattern

Following the established patterns in the codebase:

```python
# app/routers/map_router.py

from fastapi import APIRouter, Depends
from app.auth_utils import get_current_active_user
from app.app import load_data_source  # ✅ Reuse existing
from app.core.processors import preprocess_telemetry_df  # ✅ Reuse existing
from app.core.map_utils import prepare_track_points, generate_kml  # ✨ New

router = APIRouter(tags=["Map"])

@app.get("/api/map/telemetry/{mission_id}")
async def get_map_telemetry(
    mission_id: str,
    hours_back: int = 72,
    current_user: User = Depends(get_current_active_user)
):
    # Step 1: Load data using existing pattern ✅
    df, source_path = await load_data_source(
        "telemetry", 
        mission_id,
        hours_back=hours_back,
        current_user=current_user
    )
    
    # Step 2: Preprocess using existing function ✅
    processed_df = preprocess_telemetry_df(df)
    
    # Step 3: Use standardized column names (Latitude, Longitude, Timestamp)
    track_points = prepare_track_points(processed_df)
    
    return JSONResponse(content=track_points)
```

## Benefits of This Approach

1. ✅ **No code duplication** - Reuse existing 500+ lines of data handling
2. ✅ **Consistent behavior** - Same caching, filtering, permissions as dashboard
3. ✅ **Maintainable** - Single source of truth for telemetry logic
4. ✅ **Fast** - Leverages existing time-aware cache
5. ✅ **Secure** - Inherits existing user permissions

## Dependencies: NONE

Existing codebase already has:
- ✅ Pandas (DataFrame operations)
- ✅ DateTime (timestamps)
- ✅ JSON (serialization)
- ✅ FastAPI (API framework)

**No new Python packages needed!** Only frontend library (Leaflet.js via CDN).

## Simplified Approach - Phase 1 Only

**User Decision:** Focus on bare minimum - just lat/long track plotting

**Implementation will include:**
- ✅ Basic track visualization (lat/long points connected by lines)
- ✅ Multiple mission support
- ✅ KML export for Google Maps
- ✅ Time range filtering

**Skipped for Phase 1:**
- ❌ Speed over ground coloring
- ❌ Sensor data overlays
- ❌ Waypoint annotations
- ❌ Heat maps

**These can be added later as toggleable features**

## Next Steps

Ready to implement the simplified map feature:

1. Create minimal code (~150 lines total)
2. Just track points - no sensor overlays
3. Basic Leaflet.js map with polyline
4. Reuse all existing telemetry infrastructure
5. Follow existing authentication patterns

**Total new code needed:** ~150 lines (much simpler!)

Would you like me to start implementing now?

