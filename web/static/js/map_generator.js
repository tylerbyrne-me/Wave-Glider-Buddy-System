/**
 * @file map_generator.js
 * @description Map Generator - Mission Track Visualization
 * 
 * Provides interactive map display for mission tracks using Leaflet.js
 */

import { apiRequest, showToast } from '/static/js/api.js';

let missionMap = null;
let missionTracks = [];
let slocumTracks = [];

/** Slocum track color palette (teal/green for visual distinction from Wave Glider blue/red) */
const SLOCUM_COLORS = ['#008b8b', '#20b2aa', '#2e8b57', '#3cb371', '#48d1cc', '#5f9ea0', '#66cdaa', '#7fffd4'];

/**
 * Initialize the mission map and auto-load active missions
 */
function initializeMissionMap() {
    // Check if map container exists
    const mapContainer = document.getElementById('missionMapContainer');
    if (!mapContainer) {
        // Map container not found - this is expected if map is not on the page
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

    // Auto-load active missions from data attributes
    const mapCard = document.getElementById('missionMapContainer')?.closest('.card-body');
    if (mapCard) {
        const activeMissionsData = mapCard.getAttribute('data-active-missions');
        const defaultHours = mapCard.getAttribute('data-default-hours') || '24';
        
        if (activeMissionsData) {
            try {
                const activeMissions = JSON.parse(activeMissionsData);
                
                if (activeMissions && activeMissions.length > 0) {
                    // Load all active missions automatically
                    loadMultipleMissionTracks(activeMissions, parseInt(defaultHours));
                }
            } catch (error) {
                showToast('Error loading active missions data', 'danger');
            }
        }
    }
}

/**
 * Load and display a single mission track
 * @param {string} missionId - Mission identifier
 * @param {number} hoursBack - Number of hours of history to retrieve
 */
async function loadMissionTrack(missionId, hoursBack = 72) {
    if (!missionMap) {
        showToast('Map not initialized', 'danger');
        return;
    }

    try {
        const data = await apiRequest(`/api/map/telemetry/${missionId}?hours_back=${hoursBack}`, 'GET');
        
        if (!data.track_points || data.track_points.length === 0) {
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
        showToast(`Error loading track for mission ${missionId}: ${error.message}`, 'danger');
        displayErrorMessage(`Error loading track: ${error.message}`);
    }
}

/**
 * Load and display multiple mission tracks
 * @param {Array<string>} missionIds - Array of mission identifiers
 * @param {number} hoursBack - Number of hours of history to retrieve
 */
async function loadMultipleMissionTracks(missionIds, hoursBack = 72) {
    if (!missionMap) {
        showToast('Map not initialized', 'danger');
        return;
    }

    try {
        const missionIdParam = missionIds.join(',');
        const data = await apiRequest(`/api/map/multiple?mission_ids=${missionIdParam}&hours_back=${hoursBack}`, 'GET');
        
        // Clear existing tracks
        clearTracks();

        // Color palette for multiple tracks (distinct colors for better visibility)
        const colors = ['#3388ff', '#dc143c', '#32cd32', '#ff8c00', '#9370db', '#ff69b4', '#00ced1', '#ffa500'];
        
        let colorIndex = 0;
        for (const [missionId, trackData] of Object.entries(data.missions)) {
            if (!trackData.track_points || trackData.track_points.length === 0) {
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
        showToast(`Error loading tracks: ${error.message}`, 'danger');
        displayErrorMessage(`Error loading tracks: ${error.message}`);
    }
}

/**
 * Clear all Wave Glider tracks from the map
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
 * Clear all Slocum tracks from the map
 */
function clearSlocumTracks() {
    if (slocumTracks.length > 0) {
        slocumTracks.forEach(track => {
            missionMap.removeLayer(track.layer);
        });
        slocumTracks = [];
    }
}

/**
 * Fetch Slocum dataset list (active + available) from API
 * @returns {Promise<{active: Array, available: Array}>}
 */
async function loadSlocumDatasets() {
    const data = await apiRequest('/api/slocum/datasets', 'GET');
    return { active: data.active || [], available: data.available || [] };
}

/**
 * Load and display a single Slocum glider track
 * @param {string} datasetId - ERDDAP dataset ID
 * @param {number} hoursBack - Number of hours of history
 * @param {number} colorIndex - Index into SLOCUM_COLORS for multi-track styling
 */
async function loadSlocumTrack(datasetId, hoursBack = 72, colorIndex = 0) {
    if (!missionMap) {
        showToast('Map not initialized', 'danger');
        return;
    }
    try {
        const data = await apiRequest(`/api/map/slocum/telemetry/${encodeURIComponent(datasetId)}?hours_back=${hoursBack}`, 'GET');
        if (!data.track_points || data.track_points.length === 0) {
            showToast(`No track data for Slocum dataset ${datasetId}`, 'warning');
            return;
        }
        const color = SLOCUM_COLORS[colorIndex % SLOCUM_COLORS.length];
        const trackLayer = L.polyline(
            data.track_points.map(point => [point.lat, point.lon]),
            {
                color: color,
                weight: 3,
                opacity: 0.8,
                dashArray: '10, 10'
            }
        ).addTo(missionMap);
        slocumTracks.push({
            datasetId: datasetId,
            layer: trackLayer,
            pointCount: data.point_count,
            bounds: data.bounds
        });
        if (data.bounds) {
            const allLayers = [...missionTracks, ...slocumTracks].map(t => t.layer);
            const group = new L.featureGroup(allLayers);
            missionMap.fitBounds(group.getBounds(), { padding: [50, 50] });
        }
        updateSlocumTrackInfo();
    } catch (error) {
        showToast(`Error loading Slocum track ${datasetId}: ${error.message}`, 'danger');
    }
}

/**
 * Update Slocum track info in the UI
 */
function updateSlocumTrackInfo() {
    const infoElement = document.getElementById('slocumTrackInfo');
    if (!infoElement) return;
    if (slocumTracks.length === 0) {
        infoElement.innerHTML = '';
        return;
    }
    const totalPoints = slocumTracks.reduce((sum, t) => sum + t.pointCount, 0);
    let html = '<div class="alert alert-secondary mb-2"><strong>Slocum gliders</strong> (dashed) – ';
    html += `${slocumTracks.length} dataset(s), ${totalPoints.toLocaleString()} points</div>`;
    infoElement.innerHTML = html;
}

/**
 * Remove a single Slocum track by dataset ID
 * @param {string} datasetId
 */
function removeSlocumTrack(datasetId) {
    const idx = slocumTracks.findIndex(t => t.datasetId === datasetId);
    if (idx === -1) return;
    const track = slocumTracks[idx];
    if (missionMap && track.layer) missionMap.removeLayer(track.layer);
    slocumTracks.splice(idx, 1);
    updateSlocumTrackInfo();
}

/**
 * Initialize Slocum dataset picker and wire events (when section exists and feature enabled)
 */
function initSlocumUI() {
    const section = document.getElementById('slocumDatasetsSection');
    if (!section || !missionMap) return;
    const activeList = document.getElementById('slocumActiveList');
    const hoursBackSelect = document.getElementById('slocumHoursBack');
    const clearBtn = document.getElementById('slocumClearTracksBtn');
    const browseBtn = document.getElementById('slocumBrowseBtn');
    const searchBtn = document.getElementById('slocumSearchBtn');
    const searchInput = document.getElementById('slocumSearchInput');
    const searchResults = document.getElementById('slocumSearchResults');
    const browseModal = document.getElementById('slocumBrowseModal');

    function getHoursBack() {
        return hoursBackSelect ? parseInt(hoursBackSelect.value, 10) || 72 : 72;
    }

    function setLoading(loading) {
        if (activeList) {
            activeList.innerHTML = loading
                ? '<span class="text-muted"><span class="spinner-border spinner-border-sm me-1" role="status" aria-hidden="true"></span>Loading…</span>'
                : '';
        }
        if (browseBtn) browseBtn.disabled = loading;
    }

    function renderActiveList(active) {
        if (!activeList) return;
        if (!active || active.length === 0) {
            activeList.innerHTML = '<span class="text-muted">No active datasets configured.</span>';
            return;
        }
        let html = '<div class="d-flex flex-wrap gap-2 align-items-center">';
        active.forEach((ds, i) => {
            const id = ds.datasetID || ds.datasetId || 'unknown';
            const title = ds.title || id;
            const dashboardUrl = `/slocum?dataset=${encodeURIComponent(id)}`;
            html += `<div class="d-flex align-items-center gap-1"><label class="d-flex align-items-center gap-1 mb-0"><input type="checkbox" class="form-check-input slocum-dataset-cb" data-dataset-id="${id}"> ${title}</label><a href="${dashboardUrl}" class="btn btn-link btn-sm p-0 ms-1">Dashboard</a></div>`;
        });
        html += '</div>';
        activeList.innerHTML = html;
        activeList.querySelectorAll('.slocum-dataset-cb').forEach(cb => {
            cb.addEventListener('change', async function() {
                const datasetId = this.getAttribute('data-dataset-id');
                if (this.checked) {
                    const colorIndex = slocumTracks.length;
                    await loadSlocumTrack(datasetId, getHoursBack(), colorIndex);
                } else {
                    removeSlocumTrack(datasetId);
                }
            });
        });
    }

    setLoading(true);
    loadSlocumDatasets()
        .then(data => {
            setLoading(false);
            renderActiveList(data.active);
        })
        .catch(err => {
            setLoading(false);
            if (activeList) activeList.innerHTML = '<span class="text-danger">Failed to load datasets. Try again later.</span>';
            showToast('Failed to load Slocum datasets', 'danger');
        });

    if (clearBtn) {
        clearBtn.addEventListener('click', () => {
            clearSlocumTracks();
            updateSlocumTrackInfo();
            if (activeList) activeList.querySelectorAll('.slocum-dataset-cb').forEach(cb => { cb.checked = false; });
        });
    }

    if (browseBtn && browseModal) {
        browseBtn.addEventListener('click', () => {
            const modal = typeof bootstrap !== 'undefined' && bootstrap.Modal ? new bootstrap.Modal(browseModal) : null;
            if (modal) modal.show();
        });
    }

    if (searchBtn && searchInput && searchResults) {
        searchBtn.addEventListener('click', async () => {
            const q = searchInput.value.trim();
            if (!q) {
                searchResults.innerHTML = '<p class="text-muted">Enter a search term.</p>';
                return;
            }
            searchResults.innerHTML = '<p class="text-muted"><span class="spinner-border spinner-border-sm me-1" role="status"></span>Searching…</p>';
            searchBtn.disabled = true;
            try {
                const data = await apiRequest(`/api/slocum/datasets/search?q=${encodeURIComponent(q)}`, 'GET');
                const list = data.datasets || [];
                if (list.length === 0) {
                    searchResults.innerHTML = '<p class="text-muted">No datasets found.</p>';
                    return;
                }
                let html = '<ul class="list-group list-group-flush">';
                list.forEach((ds, i) => {
                    const id = ds.datasetID || ds.datasetId || 'unknown';
                    const title = ds.title || id;
                    const dashboardUrl = `/slocum?dataset=${encodeURIComponent(id)}`;
                    html += `<li class="list-group-item d-flex justify-content-between align-items-center">
                        <span>${title}</span>
                        <span>
                            <a href="${dashboardUrl}" class="btn btn-sm btn-outline-secondary me-1">Dashboard</a>
                            <button type="button" class="btn btn-sm btn-outline-primary add-slocum-dataset-btn" data-dataset-id="${id}">Add to map</button>
                        </span>
                    </li>`;
                });
                html += '</ul>';
                searchResults.innerHTML = html;
                searchResults.querySelectorAll('.add-slocum-dataset-btn').forEach(btn => {
                    btn.addEventListener('click', async function() {
                        const datasetId = this.getAttribute('data-dataset-id');
                        const colorIndex = slocumTracks.length;
                        await loadSlocumTrack(datasetId, getHoursBack(), colorIndex);
                        const modal = browseModal && typeof bootstrap !== 'undefined' && bootstrap.Modal ? bootstrap.Modal.getInstance(browseModal) : null;
                        if (modal) modal.hide();
                    });
                });
            } catch (err) {
                const msg = err.message || (err.detail && (typeof err.detail === 'string' ? err.detail : err.detail.detail)) || 'Search failed';
                searchResults.innerHTML = `<p class="text-danger">${msg}</p>`;
            } finally {
                searchBtn.disabled = false;
            }
        });
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
        const data = await apiRequest('/api/kml/create_live', 'POST', {
            mission_ids: missionIds,
            hours_back: hoursBack,
            description: `Live track for ${missionIds.join(', ')}`
        });
        
        // Download the network link file (this endpoint is public, no auth required)
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
        showToast(`Error generating live KML: ${error.message}`, 'danger');
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
    } catch (error) {
        showToast(`Error downloading KML for mission ${missionId}: ${error.message}`, 'danger');
        displayErrorMessage(`Error downloading KML: ${error.message}`);
    }
}

/**
 * Handle mission selection dropdown
 */
document.addEventListener('DOMContentLoaded', function() {
    // Check if Leaflet is available
    if (typeof L === 'undefined') {
        showToast('Leaflet library not loaded', 'danger');
        return;
    }
    
    // This will be called when the map section is loaded
    const mapContainer = document.getElementById('missionMapContainer');
    
    if (mapContainer) {
        // Initialize map when container is present
        initializeMissionMap();
        // Slocum dataset picker (when feature enabled and section present)
        initSlocumUI();

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
                            showToast('Error loading missions', 'danger');
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
            // Retry after a short delay in case the page is still loading
            setTimeout(function() {
                const retryContainer = document.getElementById('missionMapContainer');
                if (retryContainer) {
                    initializeMissionMap();
                }
            }, 500);
        }
});

// Export functions for use in other modules if needed
export {
    initializeMissionMap,
    loadMissionTrack,
    loadMultipleMissionTracks,
    clearTracks,
    clearSlocumTracks,
    loadSlocumDatasets,
    loadSlocumTrack,
    removeSlocumTrack,
    updateSlocumTrackInfo,
    initSlocumUI,
    generateLiveKML,
    downloadMissionKML
};


