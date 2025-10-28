/**
 * Map Generator - Mission Track Visualization
 * 
 * Provides interactive map display for mission tracks using Leaflet.js
 */

let missionMap = null;
let missionTracks = [];

/**
 * Initialize the mission map and auto-load active missions
 */
function initializeMissionMap() {
    // Check if map container exists
    const mapContainer = document.getElementById('missionMapContainer');
    if (!mapContainer) {
        console.error('Map container not found: missionMapContainer');
        return;
    }

    // Map configuration
    const defaultCenter = [40.0, -74.0]; // Center around North Atlantic
    const defaultZoom = 6;

    // Create map
    missionMap = L.map('missionMapContainer', {
        center: defaultCenter,
        zoom: defaultZoom,
        worldCopyJump: true
    });

    // Add tile layer (OpenStreetMap)
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap contributors',
        maxZoom: 18
    }).addTo(missionMap);

    console.log('Mission map initialized');
    console.log('Map object:', missionMap);
    console.log('Map container size:', mapContainer.offsetWidth, 'x', mapContainer.offsetHeight);

    // Auto-load active missions from data attributes
    const mapCard = document.getElementById('missionMapContainer')?.closest('.card-body');
    if (mapCard) {
        const activeMissionsData = mapCard.getAttribute('data-active-missions');
        const defaultHours = mapCard.getAttribute('data-default-hours') || '24';
        
        if (activeMissionsData) {
            try {
                const activeMissions = JSON.parse(activeMissionsData);
                
                if (activeMissions && activeMissions.length > 0) {
                    console.log(`Auto-loading ${activeMissions.length} active missions (last ${defaultHours} hours)`);
                    
                    // Load all active missions automatically
                    loadMultipleMissionTracks(activeMissions, parseInt(defaultHours));
                } else {
                    console.log('No active missions to load');
                }
            } catch (error) {
                console.error('Error parsing active missions data:', error);
            }
        }
    }
}

/**
 * Load and display a single mission track
 */
async function loadMissionTrack(missionId, hoursBack = 72) {
    if (!missionMap) {
        console.error('Map not initialized');
        return;
    }

    try {
        console.log(`Loading track for mission ${missionId} (last ${hoursBack} hours)`);
        
        const response = await fetch(`/api/map/telemetry/${missionId}?hours_back=${hoursBack}`);
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const data = await response.json();
        
        if (!data.track_points || data.track_points.length === 0) {
            console.warn(`No track points for mission ${missionId}`);
            displayNoTrackMessage(missionId);
            return;
        }

        // Clear existing tracks
        clearTracks();

        // Add track to map
        const trackLayer = L.polyline(
            data.track_points.map(point => [point.lat, point.lon]),
            {
                color: '#3388ff',
                weight: 3,
                opacity: 0.8
            }
        ).addTo(missionMap);

        // Store track info
        missionTracks.push({
            missionId: missionId,
            layer: trackLayer,
            pointCount: data.point_count,
            bounds: data.bounds
        });

        // Fit map to track
        if (data.bounds) {
            missionMap.fitBounds([
                [data.bounds.south, data.bounds.west],
                [data.bounds.north, data.bounds.east]
            ], {
                padding: [50, 50]
            });
        }

        // Update track info
        updateTrackInfo(missionId, data.point_count, data.bounds);

    } catch (error) {
        console.error(`Error loading track for mission ${missionId}:`, error);
        displayErrorMessage(`Error loading track: ${error.message}`);
    }
}

/**
 * Load and display multiple mission tracks
 */
async function loadMultipleMissionTracks(missionIds, hoursBack = 72) {
    if (!missionMap) {
        console.error('Map not initialized');
        return;
    }

    try {
        console.log(`Loading tracks for missions: ${missionIds.join(', ')}`);
        
        const missionIdParam = missionIds.join(',');
        const response = await fetch(`/api/map/multiple?mission_ids=${missionIdParam}&hours_back=${hoursBack}`);
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const data = await response.json();
        
        // Clear existing tracks
        clearTracks();

        // Color palette for multiple tracks (distinct colors for better visibility)
        const colors = ['#3388ff', '#dc143c', '#32cd32', '#ff8c00', '#9370db', '#ff69b4', '#00ced1', '#ffa500'];
        
        let colorIndex = 0;
        for (const [missionId, trackData] of Object.entries(data.missions)) {
            if (!trackData.track_points || trackData.track_points.length === 0) {
                console.warn(`No track points for mission ${missionId}`);
                continue;
            }

            const color = colors[colorIndex % colors.length];

            // Add track to map
            const trackLayer = L.polyline(
                trackData.track_points.map(point => [point.lat, point.lon]),
                {
                    color: color,
                    weight: 3,
                    opacity: 0.8
                }
            ).addTo(missionMap);

            // Store track info
            missionTracks.push({
                missionId: missionId,
                layer: trackLayer,
                pointCount: trackData.point_count,
                bounds: trackData.bounds
            });

            colorIndex++;
        }

        // Fit map to show all tracks
        if (missionTracks.length > 0) {
            const group = new L.featureGroup(missionTracks.map(t => t.layer));
            missionMap.fitBounds(group.getBounds(), {
                padding: [50, 50]
            });
        }

        // Update track info
        updateMultipleTrackInfo(data.missions);

    } catch (error) {
        console.error('Error loading multiple tracks:', error);
        displayErrorMessage(`Error loading tracks: ${error.message}`);
    }
}

/**
 * Clear all tracks from the map
 */
function clearTracks() {
    if (missionTracks.length > 0) {
        missionTracks.forEach(track => {
            missionMap.removeLayer(track.layer);
        });
        missionTracks = [];
    }
}

/**
 * Update track info display
 */
function updateTrackInfo(missionId, pointCount, bounds) {
    const infoElement = document.getElementById('mapTrackInfo');
    if (!infoElement) return;

    let infoHTML = `
        <div class="alert alert-info mb-2">
            <strong>Mission ${missionId}</strong><br>
            Track points: ${pointCount.toLocaleString()}
        </div>
    `;

    infoElement.innerHTML = infoHTML;
}

/**
 * Update track info for multiple missions
 */
function updateMultipleTrackInfo(missionsData) {
    const infoElement = document.getElementById('mapTrackInfo');
    if (!infoElement) return;

    let totalPoints = 0;
    const missionList = [];
    
    for (const [missionId, data] of Object.entries(missionsData)) {
        if (data.point_count > 0) {
            totalPoints += data.point_count;
            missionList.push({ id: missionId, points: data.point_count });
        }
    }
    
    if (missionList.length === 0) {
        infoElement.innerHTML = '<div class="alert alert-warning">No track data available</div>';
        return;
    }
    
    let infoHTML = '<div class="alert alert-info mb-2">';
    infoHTML += `<strong>${missionList.length} Mission${missionList.length > 1 ? 's' : ''} Loaded</strong> - ${totalPoints.toLocaleString()} total track points<br>`;
    infoHTML += '<small>';
    infoHTML += missionList.map(m => `Mission ${m.id}: ${m.points.toLocaleString()} pts`).join(' • ');
    infoHTML += '</small>';
    infoHTML += '</div>';
    
    infoElement.innerHTML = infoHTML;
}

/**
 * Display no track message
 */
function displayNoTrackMessage(missionId) {
    const infoElement = document.getElementById('mapTrackInfo');
    if (infoElement) {
        infoElement.innerHTML = `
            <div class="alert alert-warning">
                No track data available for mission ${missionId}
            </div>
        `;
    }
}

/**
 * Display error message
 */
function displayErrorMessage(message) {
    const infoElement = document.getElementById('mapTrackInfo');
    if (infoElement) {
        infoElement.innerHTML = `
            <div class="alert alert-danger">
                ${message}
            </div>
        `;
    }
}

/**
 * Generate and download Live KML network link
 */
async function generateLiveKML() {
    const missionSelect = document.getElementById('mapMissionSelect');
    const hoursBackInput = document.getElementById('mapHoursBack');
    const selectedMission = missionSelect ? missionSelect.value : null;
    const hoursBack = hoursBackInput ? parseInt(hoursBackInput.value) : 72;
    
    if (!selectedMission || selectedMission === '') {
        displayLiveKMLStatus('Please select a mission', 'danger');
        return;
    }
    
    // Determine mission IDs
    let missionIds = [];
    if (selectedMission === 'all') {
        const mapCard = document.getElementById('missionMapContainer')?.closest('.card-body');
        const activeMissionsData = mapCard?.getAttribute('data-active-missions');
        if (activeMissionsData) {
            missionIds = JSON.parse(activeMissionsData);
            
            // Show recommendation for multi-mission
            if (missionIds.length > 1) {
                displayLiveKMLStatus(
                    `ℹ️ Multi-mission tokens work best for 72 hours or less. For longer periods, generate separate tokens per mission for better performance.`,
                    'info'
                );
            }
        } else {
            displayLiveKMLStatus('No active missions available', 'danger');
            return;
        }
    } else {
        missionIds = [selectedMission];
    }
    
    try {
        // Check if multi-mission with long time range
        if (selectedMission === 'all' && hoursBack > 72) {
            const proceed = confirm(
                '⚠️ Multi-mission Live KML tokens are only recommended for time periods of 72 hours or less.\n\n' +
                'For longer time periods, generate separate tokens for each mission for better performance.\n\n' +
                'Continue anyway?'
            );
            if (!proceed) {
                displayLiveKMLStatus('Operation cancelled. Please generate tokens for individual missions for better performance.', 'info');
                return;
            }
        }
        
        displayLiveKMLStatus('Generating live KML link...', 'info');
        
        // Create live KML token
        const response = await fetch('/api/kml/create_live', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                mission_ids: missionIds,
                hours_back: hoursBack,
                description: `Live track for ${missionIds.join(', ')}`
            })
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to create live KML token');
        }
        
        const data = await response.json();
        
        // Download the network link file
        const downloadResponse = await fetch(`/api/kml/network_link/${data.token}`);
        const blob = await downloadResponse.blob();
        
        // Create download link and trigger download
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `live_track_${data.token.substring(0, 8)}.kml`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
        
        // Display success message
        displayLiveKMLStatus(
            `✓ Live KML generated! Token expires ${new Date(data.expires_at).toLocaleDateString()}<br>` +
            `<small>Save this file and open in Google Earth for auto-updating tracks</small>`,
            'success'
        );
        
    } catch (error) {
        console.error('Error generating live KML:', error);
        displayLiveKMLStatus(
            `Error: ${error.message}`,
            'danger'
        );
    }
}

/**
 * Display live KML status message
 */
function displayLiveKMLStatus(message, type) {
    const statusElement = document.getElementById('liveKMLStatus');
    if (statusElement) {
        const alertClass = type === 'success' ? 'alert-success' : 
                          type === 'danger' ? 'alert-danger' : 
                          'alert-info';
        statusElement.innerHTML = `<div class="alert ${alertClass} alert-dismissible fade show" role="alert">${message}<button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button></div>`;
    }
}

/**
 * Download KML file for a mission
 */
async function downloadMissionKML(missionId, hoursBack = 72) {
    try {
        const url = `/api/map/kml/${missionId}?hours_back=${hoursBack}`;
        
        // Trigger download
        const link = document.createElement('a');
        link.href = url;
        link.download = `mission_${missionId}_track.kml`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        
        console.log(`KML download triggered for mission ${missionId}`);
    } catch (error) {
        console.error(`Error downloading KML for mission ${missionId}:`, error);
        displayErrorMessage(`Error downloading KML: ${error.message}`);
    }
}

/**
 * Handle mission selection dropdown
 */
document.addEventListener('DOMContentLoaded', function() {
    console.log('DOM loaded, checking for map container...');
    
    // Check if Leaflet is available
    if (typeof L === 'undefined') {
        console.error('Leaflet library not loaded');
        return;
    }
    
    // This will be called when the map section is loaded
    const mapContainer = document.getElementById('missionMapContainer');
    
    if (mapContainer) {
        console.log('Map container found, initializing...');
        // Initialize map when container is present
        initializeMissionMap();
        
        // Set up event listeners for controls
        const generateBtn = document.getElementById('generateMapBtn');
        const downloadBtn = document.getElementById('downloadKMLBtn');
        const missionSelect = document.getElementById('mapMissionSelect');
        const hoursBackInput = document.getElementById('mapHoursBack');
        
        if (generateBtn) {
            generateBtn.addEventListener('click', function() {
                const selectedMission = missionSelect ? missionSelect.value : null;
                const hoursBack = hoursBackInput ? parseInt(hoursBackInput.value) : 72;
                
                if (!selectedMission || selectedMission === '') {
                    displayErrorMessage('Please select a mission');
                    return;
                }
                
                if (selectedMission === 'all') {
                    // Load all active missions
                    const mapCard = document.getElementById('missionMapContainer')?.closest('.card-body');
                    const activeMissionsData = mapCard?.getAttribute('data-active-missions');
                    
                    if (activeMissionsData) {
                        try {
                            const activeMissions = JSON.parse(activeMissionsData);
                            loadMultipleMissionTracks(activeMissions, hoursBack);
                        } catch (error) {
                            console.error('Error parsing active missions:', error);
                            displayErrorMessage('Error loading missions');
                        }
                    } else {
                        displayErrorMessage('No active missions available');
                    }
                } else {
                    loadMissionTrack(selectedMission, hoursBack);
                }
            });
        }
        
        if (downloadBtn) {
            downloadBtn.addEventListener('click', function() {
                const selectedMission = missionSelect ? missionSelect.value : null;
                const hoursBack = hoursBackInput ? parseInt(hoursBackInput.value) : 72;
                
                if (selectedMission) {
                    downloadMissionKML(selectedMission, hoursBack);
                } else {
                    displayErrorMessage('Please select a mission');
                }
            });
        }
        
        // Live KML button
        const liveKMLBtn = document.getElementById('downloadLiveKMLBtn');
        if (liveKMLBtn) {
            liveKMLBtn.addEventListener('click', async function() {
                await generateLiveKML();
            });
        }
    } else {
        console.log('Map container not found on page load, retrying in 500ms...');
        // Retry after a short delay in case the page is still loading
        setTimeout(function() {
            const retryContainer = document.getElementById('missionMapContainer');
            if (retryContainer) {
                console.log('Map container found on retry, initializing...');
                initializeMissionMap();
            } else {
                console.log('Map container still not found after retry');
            }
        }, 500);
    }
});


