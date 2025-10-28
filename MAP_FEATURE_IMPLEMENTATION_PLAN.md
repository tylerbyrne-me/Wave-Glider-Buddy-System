# Map Generation Feature Implementation Plan

## Feature Overview
Add interactive map generation to the Wave Glider Buddy System home page, allowing users of all levels to:
- Generate mission track maps for individual or multiple active missions
- Export track data to shareable Google Maps formats (KML)
- **Phase 1 (Initial):** Simple lat/long track visualization
- **Phase 2 (Future):** Add speed coloring, waypoints, sensor overlays (toggleable)

## Current System Analysis

### Existing Telemetry Infrastructure
- ✅ Telemetry data already processed in `app/core/processors.py` (`preprocess_telemetry_df`)
- ✅ Data includes: `Latitude`, `Longitude`, `Timestamp`, `SpeedOverGround`, `GliderHeading`
- ✅ Existing API endpoint: `/api/data/telemetry/{mission_id}`
- ✅ Cartopy-based plotting exists in `app/core/plotting.py` for PDF reports
- ✅ Cache system already handles telemetry data

### Home Page Structure
- ✅ Mission tabs for multiple active missions
- ✅ Mission cards with overviews, goals, and notes
- ✅ User context and permissions already established

## Feature Design

### 1. Backend Components

#### A. API Endpoints

**Endpoint 1: `/api/map/telemetry/{mission_id}`**
- Purpose: Get telemetry data for map visualization
- Returns: JSON with track points (lat, lon, timestamp only for now)
- Parameters: hours_back (default 72), date range filtering
- **Simplified:** Just coordinates and time - no extra sensor data initially

**Endpoint 2: `/api/map/kml/{mission_id}`**
- Purpose: Generate KML file for Google Maps
- Returns: KML formatted file for download
- Parameters: hours_back, include waypoints, speed threshold

**Endpoint 3: `/api/map/multiple`**
- Purpose: Get telemetry for multiple missions simultaneously
- Returns: JSON with multiple mission tracks (color-coded)
- Parameters: mission_ids (comma-separated), hours_back

### B. New Router
- File: `app/routers/map_router.py`
- Responsibilities:
  - Map data endpoints
  - KML generation
  - Multi-mission track aggregation

### C. Map Utilities Module
- File: `app/core/map_utils.py`
- Functions:
  - `generate_kml_from_telemetry(df, mission_id, color="blue")` - Converts DataFrame to KML format
  - `prepare_track_points(df)` - Extracts track points with consistent column names
  - `calculate_track_stats(df)` - Reuses logic from `reporting.py:_calculate_telemetry_summary()`
  
**IMPORTANT:** Use standardized column names from `preprocess_telemetry_df()`:
- `Latitude`, `Longitude` (capitalized)
- `Timestamp` (UTC)
- `SpeedOverGround`, `GliderHeading`

**Reuse existing logic:**
- Distance calculation from `reporting.py:32-68`
- Haversine formula (already implemented)
- Data loading via `load_data_source()`

### 2. Frontend Components

#### A. Map Section on Home Page
Location: Add to home.html after mission briefing cards

**UI Components:**
1. **Map Generation Panel**
   - Dropdown to select missions (single or multiple)
   - Time range selector (hours back or date range)
   - "Generate Map" button
   - "Download KML" button

2. **Interactive Map Display**
   - Leaflet.js or Google Maps embed
   - Color-coded tracks per mission
   - Click points for telemetry details
   - Time slider for temporal navigation

3. **Map Options**
   - Show/Hide waypoints
   - Speed filtering
   - Track simplification (reduce points)
   - Map style selection

#### B. JavaScript Module
File: `web/static/js/map_generator.js`

**Key Functions:**
- `initializeMap()` - Set up map container
- `loadMissionTrack(missionId, hoursBack)` - Fetch and display track
- `loadMultipleMissionTracks(missionIds, hoursBack)` - Display multiple tracks
- `generateKML(missionId)` - Download KML file
- `addTrackToMap(trackData, color, label)` - Plot track on map
- `showTrackPopup(point)` - Display telemetry details

### 3. Database Schema
**No database changes required** - Uses existing telemetry data sources

### 4. Technology Stack

**Libraries to Add:**
- **Leaflet.js** - Open-source mapping library (via CDN)
- Standard library: `json`, `xml`, `datetime` (already used)

**Python Libraries - NO NEW DEPENDENCIES NEEDED:**
- ✅ Haversine distance already implemented in `reporting.py`
- ✅ Coordinate conversion already in `processors.py`
- ✅ All utilities exist in codebase

**Frontend Libraries (via CDN):**
- Leaflet CSS & JS
- Leaflet.heat (optional, for speed visualization)

## Implementation Steps

### Phase 1: Backend Foundation (Simplified - Lat/Long Only)
1. Create `app/routers/map_router.py`
2. Create `app/core/map_utils.py` with:
   - `prepare_track_points()` - Extract only: `Latitude`, `Longitude`, `Timestamp`
   - `generate_kml_from_telemetry()` - Simple KML with coordinates only
   - **Skip speed/heading for now** - keep it minimal
3. Add map router to main app (import at line 104 in `app.py`)
4. Implement `/api/map/telemetry/{mission_id}` endpoint:
   - Use existing `load_data_source()` pattern
   - Use existing `preprocess_telemetry_df()` 
   - Return only: `[{lat, lon, timestamp}]`
5. Test with existing mission data

### Phase 2: KML Export
1. Implement KML generation in `map_utils.py`
2. Add `/api/map/kml/{mission_id}` endpoint
3. Test KML output in Google Maps/Google Earth

### Phase 3: Multi-Mission Support
1. Implement `/api/map/multiple` endpoint
2. Add mission track aggregation logic
3. Test with 2+ missions

### Phase 4: Frontend Integration
1. Add map section to `home.html`
2. Create `map_generator.js`
3. Add Leaflet.js to base template
4. Implement map initialization
5. Connect to backend endpoints

### Phase 5: UI/UX Polish
1. Add map options panel
2. Implement track filtering
3. Add download buttons
4. Mobile-responsive design
5. Error handling and loading states

## File Structure

```
app/
├── routers/
│   └── map_router.py          # NEW - Map API endpoints (simple: lat/lon only)
├── core/
│   └── map_utils.py           # NEW - Map utilities and KML generation (minimal)
web/
├── static/
│   └── js/
│       └── map_generator.js    # NEW - Frontend map handling (basic Leaflet)
└── templates/
    └── home.html              # MODIFY - Add map section
```

**Simplified Implementation:**
- Track display: Just lat/long points connected by lines
- Speed/h shading: Not included in Phase 1
- Waypoints: Not included in Phase 1
- Sensor overlays: Not included in Phase 1

## Security Considerations
- ✅ Use existing `get_current_active_user` authentication
- ✅ Respect role-based mission access (pilot vs admin)
- ✅ Validate mission_id belongs to accessible missions
- ✅ Rate limiting via existing cache system
- ✅ Reuse access control from `load_data_source()` in `app.py`

## Performance Considerations
- Cache telemetry data (already implemented)
- Limit track points for performance (100-1000 points)
- Use progressive enhancement for map display
- Lazy-load map on user request

## Testing Strategy
- Test with single mission
- Test with multiple missions (2-3)
- Test KML export in Google Maps
- Test with different time ranges
- Test with missing/invalid telemetry data
- Test with users of different roles

## Future Enhancements
- Real-time track updates for active missions
- Historical track comparison
- Weather overlay on tracks
- Waypoint annotations
- Speed heat map visualization
- Track sharing via generated URLs

