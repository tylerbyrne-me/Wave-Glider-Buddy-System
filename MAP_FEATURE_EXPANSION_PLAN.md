# Map Feature Expansion Plan

## Current Status (Phase 1 - COMPLETE ✅)
- ✅ Basic lat/long track plotting
- ✅ Multiple missions on one map (color-coded)
- ✅ Auto-loading active missions (last 24 hours)
- ✅ KML export for Google Maps
- ✅ Mission selection dropdown
- ✅ Time range selection (24h, 72h, week, month)
- ✅ Interactive map controls (pan, zoom, click tracks)

## Phase 2: Enhanced Visualization

### 2.1 Speed-Based Track Coloring
**Goal**: Color-code track segments by speed over ground to visualize mission behavior

**Technical Approach**:
- Use telemetry `SpeedOverGround` column to determine colors
- Color gradient: Blue (slow) → Green (normal) → Yellow/Orange (fast) → Red (very fast)
- Segment-based coloring (interpolate between points)
- Add legend showing speed ranges

**UI Components**:
- Toggle switch: "Speed Coloring" (on/off)
- Legend showing speed ranges and corresponding colors

**Backend Changes**:
- `map_utils.py`: Add `prepare_track_points_with_speed()` function
- Return speed data alongside lat/long in API response
- Calculate color based on speed value

**Frontend Changes**:
- Update `map_generator.js` to create color-coded polyline segments
- Add speed legend component
- Add toggle control in UI

**Estimated Effort**: 2-3 hours

---

### 2.2 Interactive Track Markers
**Goal**: Add clickable markers at key points (start, end, waypoints, significant events)

**Features**:
- Start point marker (green circle with icon)
- End point marker (red circle with icon)  
- Timestamp labels on hover
- Click markers for detailed info popup (timestamp, coordinates, speed, heading)
- Custom markers every N points for long tracks

**UI Components**:
- Info popup with formatted timestamp and data
- Option to show/hide markers (toggle)

**Technical Approach**:
- Add markers at track start/end
- Popup content: timestamp, lat/long, speed, heading
- Use custom Leaflet icons

**Estimated Effort**: 2-3 hours

---

### 2.3 Track Smoothing and Density Control
**Goal**: Allow users to visualize tracks at different detail levels

**Features**:
- Track density slider (show every Nth point)
- Track smoothing toggle (average positions over time windows)
- Performance optimization for very long tracks

**Use Cases**:
- Full detail: All points for precise analysis
- Medium detail: Every 10th point for faster rendering
- Low detail: Every 100th point for overview

**Technical Approach**:
- Add density parameter to backend (`downsample_factor`)
- Frontend slider controls how many points to display
- Optional interpolation for smoother visual appearance

**Estimated Effort**: 2-3 hours

---

## Phase 3: Advanced Analytics

### 3.1 Track Statistics Overlay
**Goal**: Display key metrics about the selected track(s)

**Statistics to Display**:
- Total distance traveled (using Haversine formula)
- Average speed over ground
- Max/min speed
- Time range (earliest/latest timestamp)
- Number of data points
- Total time duration

**UI Components**:
- Statistics panel above or beside map
- Auto-update when track changes
- Per-mission stats when multiple missions shown

**Technical Approach**:
- Add statistics calculation to `map_utils.py`
- Return statistics in API response alongside track points
- Display in info panel

**Estimated Effort**: 2-3 hours

---

### 3.2 Mission Comparison Tools
**Goal**: Compare multiple missions side-by-side

**Features**:
- Side-by-side distance comparison
- Speed profile comparison
- Timeline overlay (when were missions in same area)
- Show/hide individual missions (checkboxes)
- Summary comparison table

**UI Components**:
- Mission selection checkboxes
- Comparison mode toggle
- Comparison statistics table

**Technical Approach**:
- Track visibility state for each mission
- Compare statistics across selected missions
- Optional overlapping area detection

**Estimated Effort**: 4-5 hours

---

## Phase 4: Sensor Data Integration

### 4.1 Sensor Data Overlays
**Goal**: Visualize additional telemetry data on the map

**Sensor Options**:
- **Speed Over Ground**: Color-coded tracks (already planned in Phase 2.1)
- **Glider Heading**: Arrow markers showing direction
- **Solar Power**: Color overlay or markers for low power events
- **Wave Height/Speed**: Themed markers or color zones
- **Custom sensors**: Configurable based on available telemetry data

**UI Components**:
- Sensor selection dropdown/multi-select
- Style selector for each sensor (color, marker, overlay)
- Sensor legend

**Technical Approach**:
- Query additional sensor data in API
- Return sensor values alongside track points
- Frontend rendering based on selected sensors
- Consider performance with multiple sensor layers

**Estimated Effort**: 4-6 hours

---

### 4.2 Real-Time Position Indicator
**Goal**: Show current/last known position with timestamp

**Features**:
- Pulsing marker for "current" position
- Timestamp display of last update
- Auto-refresh option (configurable interval)
- Different marker style for real-time vs historical data

**UI Components**:
- Auto-refresh toggle
- Last update timestamp display
- Refresh button (manual)

**Technical Approach**:
- Query most recent telemetry record
- Display with special marker/icon
- Optional WebSocket for live updates (future)

**Estimated Effort**: 2-3 hours

---

## Phase 5: Export and Sharing

### 5.1 Enhanced Export Options
**Goal**: Support multiple export formats

**Export Formats**:
- ✅ KML (already implemented)
- PNG export (screenshot of map view)
- PDF export (map + statistics)
- CSV export (track points with metadata)
- GeoJSON export

**UI Components**:
- Export dropdown menu
- File naming convention
- Export resolution options (for PNG)

**Technical Approach**:
- Add screenshot capability (html2canvas or similar)
- Backend CSV/GeoJSON generation
- PDF generation with report layout

**Estimated Effort**: 3-4 hours

---

### 5.2 Shareable Links
**Goal**: Generate shareable URLs for specific map views

**Features**:
- Generate URL with mission/time range parameters
- Shareable link button
- Deep linking to specific missions/time ranges
- "View on Google Maps" integration

**Technical Approach**:
- Update URL query parameters
- Parse URL on page load to restore view
- Copy-to-clipboard functionality

**Estimated Effort**: 2-3 hours

---

## Phase 6: Performance and UX Improvements

### 6.1 Map Performance Optimization
**Goal**: Handle large datasets efficiently

**Optimizations**:
- Point clustering for zoomed-out views
- Progressive loading (show overview, then add detail)
- Web Workers for data processing
- Lazy loading of track data

**Target Metrics**:
- Load time < 2 seconds for 72 hours of data
- Smooth zoom/pan with 10,000+ points
- Memory efficient for multiple missions

**Estimated Effort**: 4-6 hours

---

### 6.2 User Experience Enhancements
**Goal**: Improve usability and discoverability

**Enhancements**:
- **Loading indicators**: Show progress while fetching data
- **Error handling**: User-friendly error messages
- **Help tooltips**: Explain features to new users
- **Keyboard shortcuts**: Quick actions
- **Customizable map layers**: Satellite, terrain, etc.
- **Bookmark views**: Save favorite zoom levels/regions
- **Search**: Jump to specific coordinates or mission area
- **Undo/redo**: For filter/toggle changes

**Estimated Effort**: 3-4 hours

---

## Recommended Implementation Order

### Priority 1 (High Impact, Low Effort):
1. **Track Statistics Overlay** (Phase 3.1) - Users want to see mission metrics
2. **Enhanced Export Options** (Phase 5.1) - PNG/PDF export valuable for reports

### Priority 2 (High Impact, Medium Effort):
3. **Speed-Based Track Coloring** (Phase 2.1) - Shows mission behavior visually
4. **Interactive Track Markers** (Phase 2.2) - Improves data discovery

### Priority 3 (Medium Impact, Variable Effort):
5. **Track Smoothing and Density** (Phase 2.3) - Performance improvement
6. **Sensor Data Overlays** (Phase 4.1) - Extends functionality
7. **User Experience Enhancements** (Phase 6.2) - Polish

### Priority 4 (Future Enhancements):
8. **Mission Comparison Tools** (Phase 3.2)
9. **Real-Time Position Indicator** (Phase 4.2)
10. **Shareable Links** (Phase 5.2)
11. **Performance Optimization** (Phase 6.1)

---

## Quick Wins (Next Session)

If implementing immediately, I recommend starting with:

1. **Track Statistics** - Show total distance, avg speed, etc. (1-2 hours)
2. **Speed Coloring** - Color-code tracks by speed (2-3 hours)
3. **Interactive Markers** - Add start/end points with info (1-2 hours)

These three features would make the map much more useful and informative while maintaining good performance.

