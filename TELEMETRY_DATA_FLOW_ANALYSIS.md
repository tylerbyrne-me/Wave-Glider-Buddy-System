# Telemetry Data Flow Analysis

## Overview
This document analyzes how telemetry data flows through the system to ensure the new map feature uses consistent patterns and avoids code duplication.

## Data Processing Pipeline

### 1. Raw Data Input
**File Location:** Remote server or local path  
**Columns (Raw CSV):**
- `lastLocationFix` (timestamp) or `gliderTimeStamp`
- `latitude`, `longitude`
- `gliderHeading`, `gliderSpeed`
- `targetWayPoint`, `gliderDistance`
- `speedOverGround`, `oceanCurrent`, `oceanCurrentDirection`
- `headingFloatDegrees`, `desiredBearingDegrees`, `headingSubDegrees`

### 2. Preprocessing (`app/core/processors.py`)
**Function:** `preprocess_telemetry_df(df: pd.DataFrame)`

**Column Mapping:**
- `latitude` → `Latitude`
- `longitude` → `Longitude`
- `gliderHeading` → `GliderHeading`
- `gliderSpeed` → `GliderSpeed`
- `targetWayPoint` → `TargetWaypoint`
- `gliderDistance` → `DistanceToWaypoint`
- `speedOverGround` → `SpeedOverGround`
- `oceanCurrent` → `OceanCurrentSpeed`
- `oceanCurrentDirection` → `OceanCurrentDirection`
- `headingFloatDegrees` → `HeadingFloatDegrees`
- Timestamp: `lastLocationFix` or `gliderTimeStamp` → `Timestamp` (UTC)

**Output After Preprocessing:**
```python
{
    "Timestamp": datetime (UTC),
    "Latitude": float,
    "Longitude": float,
    "GliderHeading": float,
    "GliderSpeed": float,
    "TargetWaypoint": str,
    "DistanceToWaypoint": float,
    "SpeedOverGround": float,
    "OceanCurrentSpeed": float,
    "OceanCurrentDirection": float,
    "HeadingFloatDegrees": float,
    "DesiredBearingDegrees": float,
    "HeadingSubDegrees": float
}
```

### 3. Data Access Patterns

#### A. Dashboard Loading (`app/app.py`)
**Line:** 1939-2098  
**Pattern:**
```python
# Load raw data with caching
df, source_path = await load_data_source(
    "telemetry",
    mission_id,
    source_preference="remote",  # or "local"
    hours_back=params.hours_back,
    current_user=current_user
)

# Preprocess
processed_df = processors.preprocess_telemetry_df(df)

# Filter by time
recent_data = processed_df[processed_df["Timestamp"] > cutoff_time]

# Resample
resampled_data = numeric_cols.resample(f"{granularity}min").mean()
```

#### B. Report Generation (`app/reporting.py`)
**Line:** 32-68, 294-324  
**Pattern:**
```python
# Calculate distance using Haversine formula (already implemented!)
def _calculate_telemetry_summary(df: pd.DataFrame):
    # Clean and sort
    df_clean = df.dropna(subset=['latitude', 'longitude', 'lastLocationFix'])
    df_clean = df_clean.sort_values(by='lastLocationFix')
    
    # Vectorized Haversine calculation
    lat1, lon1 = radians(df_clean['latitude'].shift())
    lat2, lon2 = radians(df_clean[['latitude', 'longitude']])
    # ... calculates distances
    
    return {
        "total_distance_km": sum(distances),
        "avg_speed_knots": df['speedOverGround'].mean()
    }
```

#### C. Map Plotting (`app/core/plotting.py`)
**Line:** 294-324  
**Pattern:**
```python
def plot_telemetry_for_report(ax, df: pd.DataFrame):
    # Sort by lastLocationFix (raw column, NOT the standardized Timestamp!)
    df = df.sort_values(by='lastLocationFix')
    
    # Use raw columns for mapping
    if df.empty or 'longitude' not in df.columns or 'latitude' not in df.columns:
        return
    
    # Create extent for map
    extent = [
        df['longitude'].min() - 0.1,
        df['longitude'].max() + 0.1,
        df['latitude'].min() - 0.1,
        df['latitude'].max() + 0.1
    ]
    
    # Plot with speed color-coding
    ax.scatter(
        df['longitude'], 
        df['latitude'], 
        c=df['speedOverGround'], 
        cmap='plasma', 
        norm=Normalize(vmin=0, vmax=4)
    )
```

**CRITICAL NOTE:** The plotting function uses RAW column names (`longitude`, `latitude`, `lastLocationFix`), NOT the standardized names (`Longitude`, `Latitude`, `Timestamp`). This is because `reporting.py` passes raw unfiltered data to the plotting functions.

### 4. Summary Generation (`app/core/summaries.py`)
**Line:** 769-856  
**Pattern:**
```python
def get_navigation_status(df_telemetry):
    # Uses preprocess_telemetry_df internally
    df_telemetry_processed, last_row = _get_common_status_data(
        df_telemetry, preprocess_telemetry_df, "Navigation"
    )
    
    # Extract values using standardized column names
    latitude = last_row.get("Latitude")
    longitude = last_row.get("Longitude")
    speed = last_row.get("SpeedOverGround")
    # etc.
```

## Key Findings for Map Feature

### ✅ REUSE Existing Functions

1. **Distance Calculation:** ✅ Already implemented in `reporting.py:32-68`
   - Can copy `_calculate_telemetry_summary()` logic for track distance
   - Uses vectorized Haversine formula
   - Returns distance in km

2. **Data Loading:** ✅ Use existing pattern from `app/app.py:1939`
   ```python
   df, source_path = await load_data_source(
       "telemetry", mission_id,
       hours_back=72,
       current_user=current_user
   )
   ```

3. **Preprocessing:** ✅ Use existing function
   ```python
   from app.core.processors import preprocess_telemetry_df
   processed_df = preprocess_telemetry_df(df)
   ```

### ⚠️ COLUMN NAME INCONSISTENCY

**IMPORTANT:** There's an inconsistency between plotting and preprocessing:
- **Plotting functions** expect RAW column names: `longitude`, `latitude`, `lastLocationFix`
- **Dashboard/API** uses STANDARDIZED names: `Longitude`, `Latitude`, `Timestamp`

**For the map feature, we should:**
- Use STANDARDIZED column names (the output of `preprocess_telemetry_df`)
- This matches the dashboard pattern and is more maintainable
- If we need to convert back for compatibility with existing plotting, do it explicitly

### 🔧 RECOMMENDED PATTERN FOR MAP FEATURE

```python
# app/routers/map_router.py

from app.app import load_data_source
from app.core.processors import preprocess_telemetry_df

@app.get("/api/map/telemetry/{mission_id}")
async def get_map_telemetry(mission_id: str, hours_back: int = 72):
    # 1. Load using existing pattern
    df, source_path = await load_data_source(
        "telemetry", mission_id,
        hours_back=hours_back,
        current_user=current_user
    )
    
    # 2. Preprocess using existing function
    processed_df = preprocess_telemetry_df(df)
    
    # 3. Use STANDARDIZED column names
    track_data = processed_df[[
        'Timestamp',
        'Latitude',  # Note: capitalized
        'Longitude',  # Note: capitalized
        'SpeedOverGround',
        'GliderHeading'
    ]].to_dict('records')
    
    return JSONResponse(content=track_data)
```

### 📋 COLUMN REFERENCE TABLE

| Purpose | Raw Column Name | Standardized Name | Used Where |
|---------|----------------|-------------------|------------|
| Timestamp | `lastLocationFix` or `gliderTimeStamp` | `Timestamp` | Dashboard, API |
| Latitude | `latitude` | `Latitude` | Dashboard, API, Reports (use raw!) |
| Longitude | `longitude` | `Longitude` | Dashboard, API, Reports (use raw!) |
| Speed | `speedOverGround` | `SpeedOverGround` | Dashboard, API |
| Heading | `gliderHeading` | `GliderHeading` | Dashboard, API |

### 🎯 IMPLEMENTATION GUIDELINES

1. **Always preprocess telemetry data** using `preprocess_telemetry_df()`
2. **Use standardized column names** (`Latitude`, `Longitude`, `Timestamp`)
3. **Reuse distance calculation logic** from `reporting.py`
4. **Follow the existing caching patterns** from `app/app.py`
5. **Handle missing data gracefully** - use `.dropna()` pattern from reporting

### 🔄 AVOID THESE MISTAKES

1. ❌ Don't create new preprocessing logic - use existing `preprocess_telemetry_df()`
2. ❌ Don't duplicate distance calculation - reuse from `reporting.py`
3. ❌ Don't mix raw and standardized column names
4. ❌ Don't bypass the cache - use `load_data_source()`
5. ❌ Don't hardcode column names - use standardized names

## Summary

The system has:
- ✅ Robust preprocessing: `preprocess_telemetry_df()`
- ✅ Distance calculations: `_calculate_telemetry_summary()`
- ✅ Caching system: `load_data_source()` with time-aware caching
- ✅ Existing plotting patterns: `plot_telemetry_for_report()`

**For the map feature:** Reuse existing utilities, follow the standardized column naming, and don't duplicate logic.

