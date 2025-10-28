# Live KML Network Link Feature Plan

## Overview

Enable users to generate a shareable token/URL that Google Earth can subscribe to for live-updating mission tracks. When the application's cache refreshes with new telemetry data, Google Earth will automatically fetch the updated KML.

## Technical Background

### Google Earth Network Links
- Google Earth supports `<NetworkLink>` elements that point to a URL
- Google Earth periodically fetches the URL (configurable refresh interval)
- The fetched KML is displayed and updated automatically
- Supports both HTTP and authenticated URLs

### KML NetworkLink Element Structure
```xml
<NetworkLink>
  <name>Mission Track - Live</name>
  <refreshVisibility>1</refreshVisibility>
  <Link>
    <href>https://yourserver.com/api/kml/live/TOKEN_HERE</href>
    <refreshMode>onInterval</refreshMode>
    <refreshInterval>300</refreshInterval> <!-- 5 minutes -->
  </Link>
</NetworkLink>
```

## System Architecture

### 1. Token Generation and Management

**Database Schema Addition:**
```python
class LiveKMLToken(SQLModel, table=True):
    """Stores tokens for live KML network links"""
    
    # Primary fields
    token: str = Field(primary_key=True, max_length=64)  # Secure random token
    mission_id: str  # Which mission this token tracks
    user_id: int = Field(foreign_key="users.id")  # Who created it
    
    # Configuration
    hours_back: int = 72  # How many hours of history to include
    refresh_interval_minutes: int = 5  # How often Google Earth refreshes
    
    # Security
    is_active: bool = True
    expires_at: Optional[datetime] = None  # Optional expiration
    access_count: int = 0  # Track usage
    last_accessed_at: Optional[datetime] = None
    
    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: int = Field(foreign_key="users.id")  # User who created it
    description: Optional[str] = None  # Optional note about the token
```

**Token Generation:**
- Use `secrets.token_urlsafe(32)` for secure random tokens
- Store in database with mission/user association
- Generate unique token per user+mission combination

### 2. API Endpoints

#### 2.1 Create Live KML Link
```
POST /api/kml/create_live
```

**Request:**
```json
{
  "mission_id": "m209",
  "hours_back": 72,
  "refresh_interval_minutes": 5,
  "description": "Live track for office display"
}
```

**Response:**
```json
{
  "token": "AbC123XyZ...",
  "network_link_kml": "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<kml>...",
  "embed_url": "https://yourserver.com/api/kml/live/AbC123XyZ...",
  "expires_at": "2024-12-31T23:59:59Z",
  "qr_code_url": "https://yourserver.com/api/kml/qr/AbC123XyZ..."
}
```

#### 2.2 Serve Live KML Data
```
GET /api/kml/live/{token}
```

**Response:**
- Returns KML XML with latest cached data for the mission
- Uses existing `generate_kml_from_track_points()` function
- Bypasses authentication (token is authentication)
- Updates `access_count` and `last_accessed_at` on each request
- Validates token expiration
- Validates token is active

**Security Checks:**
- Token exists and is active
- Token not expired (if expiration set)
- Rate limiting per token (prevent abuse)
- Optional IP whitelist per token

#### 2.3 Manage Live Tokens
```
GET /api/kml/tokens - List user's tokens
DELETE /api/kml/tokens/{token} - Revoke token
POST /api/kml/tokens/{token}/regenerate - Generate new token (invalidate old)
```

#### 2.4 Download Network Link KML File
```
GET /api/kml/download/{token}
```

**Response:**
- Returns a `.kml` file containing the `<NetworkLink>` element
- User saves this file and opens in Google Earth
- Google Earth then subscribes to the live feed

### 3. Security Considerations

#### 3.1 Token Security
- **Random Generation**: Use cryptographically secure random tokens
- **Length**: 32-64 characters minimum
- **Uniqueness**: Ensure no collisions
- **Non-guessable**: Do not base on user/mission IDs

#### 3.2 Access Control
- Token provides access to only the specified mission
- User can only create tokens for their own missions (or system-wide)
- Admin role can create tokens for any mission
- Optional expiration dates for time-limited access

#### 3.3 Rate Limiting
- **Per-token rate limiting**: Max requests per time period
- Example: 100 requests per hour per token
- Prevents abuse/bot traffic
- Track and alert on suspicious patterns

#### 3.4 Audit Trail
- Log all token access (timestamp, IP, user agent)
- Track access patterns
- Alert on unusual activity (mass requests, new IPs)
- Store access history for security reviews

#### 3.5 Data Exposure
- Only serve telemetry data for the specified mission
- No mission details, user info, or other sensitive data
- Stripped-down KML with just coordinates
- Consider embedding timestamp for cache validation

### 4. Performance Optimization

#### 4.1 Caching Strategy
- Cache the generated KML per mission+hours_back
- Cache invalidation when new telemetry arrives
- Use FastAPI's dependency caching or Redis
- Cache duration: 1-5 minutes based on refresh interval

#### 4.2 Response Optimization
- Stream large KML responses
- Compress KML output (minimize whitespace)
- Add ETags for conditional GET requests
- Implement `Last-Modified` headers

#### 4.3 Database Optimization
- Index `token` field for fast lookups
- Index `mission_id` and `user_id` for queries
- Archive old/inactive tokens
- Query optimization for access tracking

### 5. User Interface Components

#### 5.1 Token Management Page
```
/kml-tokens.html
```

**Features:**
- List of active tokens (mission, created date, access count)
- Create new token button
- Copy token URL button
- Download network link file button
- Revoke token button
- QR code for easy mobile sharing
- Access history/logs

#### 5.2 Token Creation Modal
**Fields:**
- Mission selection dropdown
- Time range (hours back) - default 72
- Refresh interval dropdown (1 min, 5 min, 15 min, 30 min)
- Expiration date (optional)
- Description/notes (optional)

**Actions:**
- Generate token button
- Show generated URL
- Copy to clipboard
- Download network link file
- Display QR code
- Show embed instructions

#### 5.3 Integration in Mission Detail View
Add "Live Map" button next to existing "Download KML" button:
```
[Download KML] [Live Map Link] [Export PNG]
```

### 6. Implementation Phases

#### Phase 1: Core Infrastructure (Priority 1)
**Estimated Effort**: 4-6 hours

**Tasks:**
1. Create `LiveKMLToken` SQLModel
2. Create database migration
3. Add token generation utility functions
4. Implement `POST /api/kml/create_live` endpoint
5. Implement `GET /api/kml/live/{token}` endpoint
6. Add basic security checks (active, not expired)
7. Test with Google Earth

**Deliverables:**
- Working live KML endpoint
- Token generation
- Basic security

---

#### Phase 2: Management Interface (Priority 2)
**Estimated Effort**: 3-4 hours

**Tasks:**
1. Create token management UI (`/kml-tokens.html`)
2. Create token creation modal
3. Add "Live Map" buttons to mission views
4. Implement token listing endpoint
5. Implement token deletion endpoint
6. Add copy-to-clipboard functionality
7. Add download network link file functionality

**Deliverables:**
- Full token management UI
- User can create and manage tokens
- Download ready-to-use KML file

---

#### Phase 3: Enhanced Features (Priority 3)
**Estimated Effort**: 3-4 hours

**Tasks:**
1. Add QR code generation for tokens
2. Implement rate limiting per token
3. Add access logging and analytics
4. Add token expiration functionality
5. Implement regeneration feature
6. Add access history view

**Deliverables:**
- QR codes for easy sharing
- Rate limiting protection
- Access history tracking

---

#### Phase 4: Optimization and Monitoring (Priority 4)
**Estimated Effort**: 2-3 hours

**Tasks:**
1. Implement KML response caching
2. Add ETag support
3. Add response compression
4. Monitor performance metrics
5. Add admin dashboard for token analytics
6. Alert on unusual access patterns

**Deliverables:**
- Optimized performance
- Monitoring and alerting
- Analytics dashboard

---

## Example User Flow

### Creating a Live Link
1. User navigates to mission detail page
2. Clicks "Generate Live Map Link" button
3. Modal opens with options:
   - Mission: m209 (auto-selected)
   - Time range: 72 hours
   - Refresh interval: 5 minutes
   - Expiration: None (optional)
   - Description: "Office monitor"
4. User clicks "Generate"
5. System creates token and displays:
   - Live URL: `https://yourserver.com/api/kml/live/ABC123...`
   - Download button for network link file
   - QR code for mobile
   - Instructions for use

### Using in Google Earth
1. User downloads the network link file
2. Opens in Google Earth (double-click or drag-drop)
3. Google Earth automatically fetches latest track data
4. Track appears on map
5. Every 5 minutes, Google Earth refreshes data
6. User sees updated track as new telemetry arrives

---

## Use Cases

### 1. Office Display Monitor
- TV/monitor showing live mission progress
- Google Earth open all day
- Auto-updates every 5 minutes
- No manual refresh needed

### 2. Mission Control
- Operations center tracking multiple missions
- Each mission has separate live feed
- Different refresh rates for different missions
- Custom colors per mission

### 3. Stakeholder Updates
- Share link with mission sponsors
- They can open in Google Earth from their computer
- Always shows latest data
- No need to download new files

### 4. Emergency Response
- Generate temporary token for emergency monitoring
- Set short expiration (e.g., 24 hours)
- Watch specific mission in real-time
- Revoke after emergency resolved

---

## Security Model

### Access Levels
1. **Public Token**: Anyone with URL can access (least secure)
2. **Authenticated Token**: Validates token+user combo (medium security)
3. **IP Whitelist**: Token + IP address must match (high security)
4. **Expiring Token**: Valid only for set time period (time-limited)

### Recommended Defaults
- Token length: 32 characters minimum
- Expiration: Optional (off by default)
- Rate limit: 100 requests/hour
- Access logging: Enabled
- IP tracking: Enabled

---

## Technical Considerations

### KML Generation for Live Feeds
- Include `when` timestamps for each point
- Add `<gx:Track>` elements for time-based rendering
- Support animated playback in Google Earth
- Include `<camera>` for automatic navigation to latest position

### Network Link Settings
```xml
<NetworkLink>
  <refreshVisibility>1</refreshVisibility>
  <flyToView>0</flyToView>  <!-- Don't auto-fly to updates -->
  <Link>
    <href>...</href>
    <refreshMode>onInterval</refreshMode>
    <refreshInterval>300</refreshInterval>
    <viewRefreshMode>never</viewRefreshMode>  <!-- Don't change user's view -->
  </Link>
</NetworkLink>
```

### Caching Considerations
- Cache generated KML for 1-5 minutes
- Invalidate cache when new telemetry arrives
- Use ETag headers for Google Earth caching
- Consider Redis for distributed caching

### Database Performance
- Archive old tokens (older than 1 year, inactive 30+ days)
- Index on frequently queried fields
- Consider separate table for access logs

---

## Future Enhancements

### 1. Multi-Mission Tokens
- Generate token for multiple missions at once
- Color-coded tracks per mission
- Combined view in single KML

### 2. Custom Styling
- User-configurable colors per token
- Line width, opacity settings
- Custom icons/waypoints

### 3. Scheduled Tokens
- Only active during specific time windows
- Auto-expire at mission end
- Pause/resume functionality

### 4. Web-Based Viewer
- Embed live map in web page
- No Google Earth needed
- HTML/JavaScript viewer using Leaflet
- Token-based access

### 5. Export Statistics
- Track usage per token
- Show most-viewed missions
- Dashboard for monitoring

---

## Additional Planning Considerations

### 1. KML NetworkLink vs Full KML Refresh

**Two Approaches:**

**A. NetworkLink with Change Detection**
- Google Earth fetches KML every 10 minutes
- Returns ONLY new points since last fetch
- More efficient, smaller responses
- Requires tracking "last fetch" per token
- More complex to implement

**B. Full KML Refresh**
- Google Earth fetches complete KML every 10 minutes
- Returns all points for time range
- Simpler to implement
- Larger responses for long time ranges
- **Recommendation: Start with this, optimize later**

### 2. Timestamp Inclusion for Animated Playback

**Should we include `<when>` timestamps for time-based visualization?**

```xml
<gx:Track>
  <when>2024-01-15T12:00:00Z</when>
  <when>2024-01-15T12:01:00Z</when>
  ...
</gx:Track>
```

**Pros:**
- Google Earth can animate track over time
- Users can scrub through timeline
- More informative visualization

**Cons:**
- Larger KML files
- Slightly more complex generation

**Recommendation: Include timestamps for enhanced UX**

### 3. Waypoints and Markers in Live KML

**Should we include start/end markers in live KML?**

- Start marker (green circle)
- End marker (red circle)
- Popups with timestamp info

**Recommendation: Yes, add start/end markers**

### 4. Mission Status Handling

**How should completed missions be handled in live KML?**

Options:
- **A. Continue showing track** (historical track remains visible)
- **B. Change line style** (dashed/solid to indicate live vs historical)
- **C. Add status indicator** (marker showing "mission completed")

**Recommendation: Continue showing track, add status badge**

### 5. Token Expiration Behavior

**Current Decision**: Expire Dec 31, 23:59:59 of issue year

**Considerations:**
- What if Google Earth fetches expired token?
  - Return 401 with message
  - Return empty KML with error message
- Should we return different response?
  - Clear error: "Token expired on Dec 31, 2024"
  - Return last known data?
  - **Recommendation: Return clear error message**

### 6. Rate Limiting Strategy

**Decision**: Link to `background_cache_refresh_interval_minutes=10`

**Limits:**
- Token: 10 requests per 10 minutes (once per minute as buffer)
- Global: Consider system-wide limit for all tokens
- Malicious detection: Alert if token exceeds 2x normal rate

**Implementation:**
```python
# Rate limiting per token
@limiter.limit("10/hour")  # Allowing up to 10x refresh rate for buffer
```

### 7. Cache Behavior for Live KML

**Decision**: Cache KMLs respecting 10min refresh

**Implementation Strategy:**

1. Generate KML when token accessed
2. Cache KML with TTL = 10 minutes
3. Cache key: `live_kml:{token}`
4. Invalidate after cache refresh interval

**Cache Warming:**
- Optionally pre-generate KMLs after each background refresh
- Reduces latency on token access
- Trades memory for speed

### 8. Multiple Mission Handling

**Decision**: Append points, no duplicate colors

**Challenge:** If token is for multiple missions, how to handle?

**Options:**
1. **Separate colors per mission** (inherent, already supported)
2. **Combined track** (single line with color transitions)
3. **Separate tracks** (multiple `<Placemark>` elements)

**Recommendation: Separate tracks per mission, unique colors**

**Color Assignment:**
- Maintain consistent color palette
- Same mission always gets same color
- Multi-mission tokens cycle through palette

### 9. NetworkLink Configuration

**Proposed Settings:**
```xml
<NetworkLink>
  <name>Mission m209 Live Track</name>
  <description>Automatically updating mission track</description>
  <refreshVisibility>1</refreshVisibility>  <!-- Show when refreshed -->
  <flyToView>0</flyToView>  <!-- Don't auto-fly to latest position -->
  <Link>
    <href>https://server.com/api/kml/live/TOKEN</href>
    <refreshMode>onInterval</refreshMode>
    <refreshInterval>600</refreshInterval>  <!-- 10 minutes -->
    <viewRefreshMode>never</viewRefreshMode>  <!-- Don't change user's view -->
    <viewFormat/>  <!-- No additional params -->
    <viewBoundScale>0.5</viewBoundScale>
  </Link>
</NetworkLink>
```

### 10. Error Handling in KML

**What should be returned if:**
- Token expired: Clear error in KML
- Mission has no data: Empty track or message?
- Rate limit exceeded: HTTP 429 vs KML with message?
- Mission not found: HTTP 404 vs descriptive KML?

**Recommendation:**
- Always return valid KML
- Use `<description>` for error messages
- HTTP status codes for client detection

### 11. Database Schema Finalization

**Final Schema Based on Decisions:**

```python
class LiveKMLToken(SQLModel, table=True):
    token: str = Field(primary_key=True, max_length=64)
    mission_ids: List[str] = Field(default_factory=list)  # Support multiple
    user_id: int = Field(foreign_key="users.id")
    
    hours_back: int = 72
    refresh_interval_minutes: int = 10  # From settings
    
    is_active: bool = True
    expires_at: datetime  # Dec 31, current year
    access_count: int = 0
    last_accessed_at: Optional[datetime] = None
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: int = Field(foreign_key="users.id")
    description: Optional[str] = None
    
    # Future enhancements
    color_scheme: Optional[str] = None  # Custom colors
    include_markers: bool = True  # Start/end markers
    include_timestamps: bool = True  # For animation
```

### 12. Caching Implementation

**Two-Level Caching:**

1. **FastAPI response caching:**
   ```python
   @cache(expire=600)  # 10 minutes
   async def generate_live_kml(token):
       ...
   ```

2. **Redis/LRUCache for KML content:**
   - Cache generated KML XML
   - Invalidate on mission data update
   - Cache key: mission_id + hours_back + last_update_time

**Cache Invalidation Strategy:**
- After background cache refresh completes
- After any mission data is manually refreshed
- On token request (check if cache stale)

### 13. Performance Optimization

**For Large Time Ranges (e.g., 720 hours = 30 days):**

1. **Point downsampling**: Max points per mission (~2000)
2. **Gzip compression**: Compress KML responses
3. **Incremental updates**: Only return new points (Phase 2)

**Estimated KML Sizes:**
- 72 hours: ~500-1000 points per mission
- 720 hours: ~10,000+ points per mission
- **Recommendation**: Enforce max_points in KML generation

### 14. User Interface Considerations

**Token Creation Flow:**
1. User clicks "Generate Live Map Link" on mission
2. Modal shows:
   - Mission(s): [m209] (selected)
   - Time range: 72 hours
   - Description: "Office monitor"
3. Generate button → Creates token
4. Display results:
   - Network link file download
   - Direct URL (for sharing)
   - QR code (for mobile)
   - Expires: Dec 31, 2024

**Token Management:**
- List on mission detail page
- Revoke button
- Copy URL button
- Show access count

### 15. Security Checklist

- [x] Public tokens (no auth required)
- [x] Rate limiting (10/hour per token)
- [x] Expiration (Dec 31)
- [ ] Token revocation capability
- [ ] Audit logging (if needed later)
- [ ] Malicious activity detection
- [ ] XSS prevention in KML content
- [ ] SQL injection prevention in token lookup

### 16. Testing Considerations

**Test Cases:**
1. Create token → Download KML → Open in Google Earth
2. Verify auto-refresh every 10 minutes
3. Test token expiration
4. Test multiple missions in one token
5. Test rate limiting (rapid requests)
6. Test with no data available
7. Test long time ranges (performance)
8. Test concurrent token access

**Mock Data for Testing:**
- Generate test telemetry data
- Verify KML structure
- Test refresh behavior

## Final Decisions Summary

1. ✅ **Token Type**: Public, shareable links
2. ✅ **Expiration**: Dec 31, 23:59:59 of issue year
3. ✅ **Refresh Rate**: 10 minutes (link to cache refresh)
4. ✅ **Points**: Append, multi-mission support
5. ✅ **Rate Limiting**: 10/hour per token (1x cache refresh + buffer)
6. ✅ **Caching**: 10-minute TTL, respect cache refresh
7. ✅ **Security**: Public tokens, rate limit protection
8. ✅ **Tracking**: Access count, no IP logging initially
9. ✅ **Implementation**: Full KML refresh approach (simpler start)

---

## Recommended Implementation Order

### Quick Start (Next Session)
1. Create `LiveKMLToken` model and migration
2. Implement `GET /api/kml/live/{token}` endpoint
3. Add token generation endpoint
4. Test with Google Earth manually

### MVP (Minimal Viable Product)
- Create/manage tokens via API
- Download network link file
- Basic token security
- Rate limiting

### Full Feature
- UI for token management
- QR codes
- Access logging
- Analytics dashboard
- Multi-mission support

