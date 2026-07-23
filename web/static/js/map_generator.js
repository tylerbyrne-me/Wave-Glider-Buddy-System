/**
 * @file map_generator.js
 * @description Map Generator - Mission Track Visualization
 * 
 * Provides interactive map display for mission tracks using Leaflet.js
 */

import { apiRequest, showToast } from '/static/js/api.js';
import { formatUtcDate } from '/static/js/datetime_utils.js';
import {
    bindWindOverlayContext,
    initWindOverlay,
    refreshWindLayerIfActive,
} from '/static/js/weather_map_layer.js';
import {
    bindIridiumOverlayContext,
    initIridiumOverlay,
    refreshIridiumLayerIfActive,
} from '/static/js/iridium_map_layer.js';

/** All track polyline layers (Wave Glider + Slocum) for bbox / z-order helpers. */
function getAllTrackLayers() {
    return [...missionTracks, ...slocumTracks].map((track) => track.layer).filter(Boolean);
}

/** Current glider positions for Iridium look-angle / next-pass calculations. */
function getIridiumObservers() {
    const observers = [];
    for (const track of missionTracks) {
        const latlng = track.positionLayer?.getLatLng?.();
        if (!latlng || !Number.isFinite(latlng.lat) || !Number.isFinite(latlng.lng)) {
            continue;
        }
        observers.push({
            id: `wg:${track.missionId}`,
            label: track.missionId,
            lat: latlng.lat,
            lon: latlng.lng,
        });
    }
    for (const track of slocumTracks) {
        const latlng = track.positionLayer?.getLatLng?.();
        if (!latlng || !Number.isFinite(latlng.lat) || !Number.isFinite(latlng.lng)) {
            continue;
        }
        const datasetId = track.datasetId || track.missionId;
        observers.push({
            id: `slocum:${datasetId}`,
            label: datasetId,
            lat: latlng.lat,
            lon: latlng.lng,
        });
    }
    return observers;
}

function notifyWindOverlayTracksChanged() {
    refreshWindLayerIfActive();
    refreshIridiumLayerIfActive();
}

let missionMap = null;
let missionTracks = [];
let slocumTracks = [];

/** Slocum track color palette (teal/green for visual distinction from Wave Glider blue/red) */
const SLOCUM_COLORS = ['#008b8b', '#20b2aa', '#2e8b57', '#3cb371', '#48d1cc', '#5f9ea0', '#66cdaa', '#7fffd4'];

/**
 * Marker at the latest GPS sample on a track (current glider position).
 * @param {Array<{lat:number, lon:number, timestamp?: string}>} trackPoints
 * @param {string} color - track color
 * @param {string} label - id shown in popup (mission or dataset)
 * @param {string|null} [dashboardUrl=null] - optional link to mission/dataset dashboard
 * @returns {L.CircleMarker|null}
 */
function createCurrentPositionMarker(trackPoints, color, label, dashboardUrl = null) {
    if (!missionMap || !trackPoints || trackPoints.length === 0) return null;
    const last = trackPoints[trackPoints.length - 1];
    if (!Number.isFinite(last.lat) || !Number.isFinite(last.lon)) return null;
    const marker = L.circleMarker([last.lat, last.lon], {
        radius: 8,
        color: '#ffffff',
        weight: 3,
        fillColor: color,
        fillOpacity: 1,
        opacity: 1
    }).addTo(missionMap);
    const ts = last.timestamp ? `<br><small>${last.timestamp}</small>` : '';
    const dashboardLink = dashboardUrl
        ? `<br><a href="${dashboardUrl}" class="btn btn-link btn-sm p-0">Dashboard</a>`
        : '';
    marker.bindPopup(
        `<strong>Current position</strong><br>${label}<br>` +
        `${Number(last.lat).toFixed(4)}, ${Number(last.lon).toFixed(4)}${ts}${dashboardLink}`
    );
    return marker;
}

function removeTrackExtraLayers(track) {
    if (!missionMap || !track) return;
    if (track.positionLayer) missionMap.removeLayer(track.positionLayer);
    if (track.waypointLayer) missionMap.removeLayer(track.waypointLayer);
}
function to_iso_utc_from_input(value) {
    if (!value) return null;
    const trimmedValue = value.trim();
    if (!trimmedValue) return null;
    const utcPattern = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?Z$/;
    if (!utcPattern.test(trimmedValue)) return null;
    const utcIso = trimmedValue;
    const parsedMs = Date.parse(utcIso);
    if (Number.isNaN(parsedMs)) return null;
    return utcIso;
}

function get_map_time_range_params() {
    const modeSelect = document.getElementById('mapTimeRangeMode');
    const hoursBackInput = document.getElementById('mapHoursBack');
    const startDateInput = document.getElementById('mapStartDate');
    const endDateInput = document.getElementById('mapEndDate');
    const mode = modeSelect ? modeSelect.value : 'preset';
    if (mode === 'full') return { full_range: 'true' };
    if (mode === 'custom') {
        const startISO = to_iso_utc_from_input(startDateInput ? startDateInput.value : '');
        const endISO = to_iso_utc_from_input(endDateInput ? endDateInput.value : '');
        if (!startISO || !endISO) throw new Error('Enter start and end in UTC ISO format (YYYY-MM-DDTHH:MM[:SS]Z).');
        if (Date.parse(startISO) > Date.parse(endISO)) throw new Error('Start date/time must be before end date/time.');
        return { start_date: startISO, end_date: endISO };
    }
    const hoursBack = hoursBackInput ? parseInt(hoursBackInput.value, 10) : 72;
    if (Number.isNaN(hoursBack) || hoursBack < 1) throw new Error('Invalid preset time range.');
    return { hours_back: String(hoursBack) };
}

/** Convert shared map time-range params to Slocum API query params. */
function to_slocum_time_query(timeRangeParams = {}) {
    if (timeRangeParams.full_range === 'true') {
        // Slocum API has no full_range; use max hours_back (1 year).
        return { hours_back: '8760' };
    }
    if (timeRangeParams.start_date && timeRangeParams.end_date) {
        return { time_start: timeRangeParams.start_date, time_end: timeRangeParams.end_date };
    }
    return { hours_back: String(timeRangeParams.hours_back || 72) };
}

function resolve_slocum_time_range_params() {
    if (document.getElementById('mapTimeRangeMode')) {
        return get_map_time_range_params();
    }
    const hoursBackSelect = document.getElementById('slocumHoursBack');
    const hoursBack = hoursBackSelect ? parseInt(hoursBackSelect.value, 10) || 72 : 72;
    return { hours_back: String(hoursBack) };
}

function to_query_string(params) {
    const searchParams = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
        if (value !== null && value !== undefined && value !== '') searchParams.set(key, value);
    });
    return searchParams.toString();
}

function apply_map_time_range_visibility() {
    const modeSelect = document.getElementById('mapTimeRangeMode');
    const hoursBackInput = document.getElementById('mapHoursBack');
    const customContainer = document.getElementById('mapCustomDateRange');
    if (!modeSelect || !hoursBackInput || !customContainer) return;
    const isCustom = modeSelect.value === 'custom';
    const isPreset = modeSelect.value === 'preset';
    hoursBackInput.style.display = isPreset ? '' : 'none';
    customContainer.style.display = isCustom ? '' : 'none';
}

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

    // Auto-load primary-platform tracks from data attributes.
    // Cross-platform overlays (e.g. WG missions on Slocum home) stay opt-in via checkboxes.
    const mapCard = document.getElementById('missionMapContainer')?.closest('.card-body');
    if (mapCard) {
        const platform = mapCard.getAttribute('data-platform') || 'wave_glider';
        const activeMissionsData = mapCard.getAttribute('data-active-missions');
        const defaultHours = mapCard.getAttribute('data-default-hours') || '24';

        if (platform !== 'slocum' && activeMissionsData) {
            try {
                const activeMissions = JSON.parse(activeMissionsData);

                if (activeMissions && activeMissions.length > 0) {
                    loadMultipleMissionTracks(activeMissions, { hours_back: String(parseInt(defaultHours, 10) || 24) });
                }
            } catch (error) {
                showToast('Error loading active missions data', 'danger');
            }
        }
    }

    bindWindOverlayContext(missionMap, getAllTrackLayers);
    initWindOverlay();
    bindIridiumOverlayContext(missionMap, getIridiumObservers);
    initIridiumOverlay();
}

/**
 * Load and display a single mission track
 * @param {string} missionId - Mission identifier
 * @param {number} hoursBack - Number of hours of history to retrieve
 */
async function loadMissionTrack(missionId, queryParams = { hours_back: '72' }) {
    if (!missionMap) {
        showToast('Map not initialized', 'danger');
        return;
    }

    try {
        const queryString = to_query_string(queryParams);
        const data = await apiRequest(`/api/map/telemetry/${missionId}?${queryString}`, 'GET');
        
        if (!data.track_points || data.track_points.length === 0) {
            displayNoTrackMessage(missionId);
            return;
        }

        // Clear existing tracks
        clearTracks();

        const color = '#3388ff';
        // Add track to map
        const trackLayer = L.polyline(
            data.track_points.map(point => [point.lat, point.lon]),
            {
                color,
                weight: 3,
                opacity: 0.8
            }
        ).addTo(missionMap);

        const positionLayer = createCurrentPositionMarker(
            data.track_points,
            color,
            `Mission ${missionId}`,
            `/wave-glider?mission=${encodeURIComponent(missionId)}`
        );

        // Store track info
        missionTracks.push({
            missionId: missionId,
            layer: trackLayer,
            positionLayer,
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
        notifyWindOverlayTracksChanged();

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
async function loadMultipleMissionTracks(missionIds, queryParams = { hours_back: '72' }) {
    if (!missionMap) {
        showToast('Map not initialized', 'danger');
        return;
    }

    try {
        const missionIdParam = missionIds.join(',');
        const queryString = to_query_string({ mission_ids: missionIdParam, ...queryParams });
        const data = await apiRequest(`/api/map/multiple?${queryString}`, 'GET');
        
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

            const positionLayer = createCurrentPositionMarker(
                trackData.track_points,
                color,
                `Mission ${missionId}`,
                `/wave-glider?mission=${encodeURIComponent(missionId)}`
            );

            // Store track info
            missionTracks.push({
                missionId: missionId,
                layer: trackLayer,
                positionLayer,
                pointCount: trackData.point_count,
                bounds: trackData.bounds
            });

            colorIndex++;
        }

        // Fit map to show all tracks
        if (missionTracks.length > 0) {
            fitMapToAllTracks();
        }

        // Update track info
        updateMultipleTrackInfo(data.missions);
        notifyWindOverlayTracksChanged();

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
            if (missionMap && track.layer) missionMap.removeLayer(track.layer);
            removeTrackExtraLayers(track);
        });
        missionTracks = [];
    }
    notifyWindOverlayTracksChanged();
}

/**
 * Clear all Slocum tracks from the map
 */
function clearSlocumTracks() {
    if (slocumTracks.length > 0) {
        slocumTracks.forEach(track => {
            if (missionMap && track.layer) missionMap.removeLayer(track.layer);
            removeTrackExtraLayers(track);
        });
        slocumTracks = [];
    }
    notifyWindOverlayTracksChanged();
}

/**
 * Fit map to all Wave Glider and Slocum layers (including position/waypoint markers).
 */
function fitMapToAllTracks() {
    if (!missionMap) return;
    const layers = [];
    missionTracks.forEach((t) => {
        if (t.layer) layers.push(t.layer);
        if (t.positionLayer) layers.push(t.positionLayer);
    });
    slocumTracks.forEach((t) => {
        if (t.layer) layers.push(t.layer);
        if (t.positionLayer) layers.push(t.positionLayer);
        if (t.waypointLayer) layers.push(t.waypointLayer);
    });
    if (layers.length === 0) return;
    const group = new L.featureGroup(layers);
    missionMap.fitBounds(group.getBounds(), { padding: [50, 50] });
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
 * @param {object|number} timeRangeOrHours - Shared time-range params, or legacy hours_back number
 * @param {number} colorIndex - Index into SLOCUM_COLORS for multi-track styling
 */
async function loadSlocumTrack(datasetId, timeRangeOrHours = 72, colorIndex = 0) {
    if (!missionMap) {
        showToast('Map not initialized', 'danger');
        return;
    }
    try {
        const timeRangeParams = typeof timeRangeOrHours === 'number'
            ? { hours_back: String(timeRangeOrHours) }
            : (timeRangeOrHours || { hours_back: '72' });
        const queryParams = to_slocum_time_query(timeRangeParams);
        const queryString = to_query_string(queryParams);
        const data = await apiRequest(`/api/map/slocum/telemetry/${encodeURIComponent(datasetId)}?${queryString}`, 'GET');
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
                opacity: 0.8
            }
        ).addTo(missionMap);

        const positionLayer = createCurrentPositionMarker(
            data.track_points,
            color,
            datasetId,
            `/slocum?dataset=${encodeURIComponent(datasetId)}`
        );

        let waypointLayer = null;
        const wpt = data.current_waypoint;
        if (wpt && Number.isFinite(wpt.lat) && Number.isFinite(wpt.lon)) {
            waypointLayer = L.circleMarker([wpt.lat, wpt.lon], {
                radius: 7,
                color: '#1a1a1a',
                weight: 2,
                fillColor: '#f8f9fa',
                fillOpacity: 0.95
            }).addTo(missionMap);
            waypointLayer.bindPopup(
                `<strong>Commanded waypoint</strong><br>${datasetId}<br>` +
                `${Number(wpt.lat).toFixed(4)}, ${Number(wpt.lon).toFixed(4)}`
            );
        }

        slocumTracks.push({
            datasetId: datasetId,
            layer: trackLayer,
            positionLayer,
            waypointLayer: waypointLayer,
            pointCount: data.point_count,
            bounds: data.bounds
        });
        fitMapToAllTracks();
        updateSlocumTrackInfo();
        notifyWindOverlayTracksChanged();
    } catch (error) {
        showToast(`Error loading Slocum track ${datasetId}: ${error.message}`, 'danger');
    }
}

/**
 * Load multiple Slocum datasets (clears existing Slocum tracks first).
 */
async function loadMultipleSlocumTracks(datasetIds, timeRangeParams = { hours_back: '72' }) {
    if (!missionMap || !datasetIds || datasetIds.length === 0) return;
    clearSlocumTracks();
    for (let i = 0; i < datasetIds.length; i++) {
        await loadSlocumTrack(datasetIds[i], timeRangeParams, i);
    }
}

/**
 * Download KML for a Slocum dataset track.
 */
async function downloadSlocumKML(datasetId, timeRangeParams = { hours_back: '72' }) {
    try {
        const queryParams = to_slocum_time_query(timeRangeParams);
        const queryString = to_query_string(queryParams);
        const url = `/api/map/slocum/kml/${encodeURIComponent(datasetId)}?${queryString}`;
        const link = document.createElement('a');
        link.href = url;
        link.download = `slocum_${datasetId}_track.kml`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    } catch (error) {
        showToast(`Error downloading KML for ${datasetId}: ${error.message}`, 'danger');
        displayErrorMessage(`Error downloading KML: ${error.message}`);
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
    const wptCount = slocumTracks.filter((t) => t.waypointLayer).length;
    let html = '<div class="alert alert-secondary mb-2"><strong>Slocum gliders</strong> – ';
    html += `${slocumTracks.length} dataset(s), ${totalPoints.toLocaleString()} points`;
    if (wptCount > 0) {
        html += ` · ${wptCount} waypoint(s)`;
    }
    html += '</div>';
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
    removeTrackExtraLayers(track);
    slocumTracks.splice(idx, 1);
    updateSlocumTrackInfo();
    notifyWindOverlayTracksChanged();
}

/**
 * Initialize Slocum dataset picker and wire events.
 * Works with the WG-home overlay section and/or Slocum-home toolbar (browse/clear/select).
 */
function initSlocumUI() {
    if (!missionMap) return;
    const section = document.getElementById('slocumDatasetsSection');
    const activeList = document.getElementById('slocumActiveList');
    const clearBtn = document.getElementById('slocumClearTracksBtn');
    const browseBtn = document.getElementById('slocumBrowseBtn');
    const searchBtn = document.getElementById('slocumSearchBtn');
    const searchInput = document.getElementById('slocumSearchInput');
    const searchResults = document.getElementById('slocumSearchResults');
    const browseModal = document.getElementById('slocumBrowseModal');
    const datasetSelect = document.getElementById('mapDatasetSelect');
    const mapCard = document.getElementById('missionMapContainer')?.closest('.card-body');
    const isSlocumHome = mapCard?.getAttribute('data-platform') === 'slocum';

    if (!section && !browseBtn && !datasetSelect && !clearBtn) return;

    function getTimeRangeForSlocumLoad() {
        return resolve_slocum_time_range_params();
    }

    function populateDatasetSelect(active) {
        if (!datasetSelect) return;
        const previous = datasetSelect.value || 'all';
        datasetSelect.innerHTML = '<option value="all">All Active Datasets</option>';
        (active || []).forEach((ds) => {
            const id = ds.datasetID || ds.datasetId || 'unknown';
            const title = ds.title || id;
            const opt = document.createElement('option');
            opt.value = id;
            opt.textContent = title;
            datasetSelect.appendChild(opt);
        });
        if ([...datasetSelect.options].some((o) => o.value === previous)) {
            datasetSelect.value = previous;
        }
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
        active.forEach((ds) => {
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
                    try {
                        const timeRangeParams = getTimeRangeForSlocumLoad();
                        const colorIndex = slocumTracks.length;
                        await loadSlocumTrack(datasetId, timeRangeParams, colorIndex);
                    } catch (error) {
                        this.checked = false;
                        showToast(error.message || 'Invalid time range', 'danger');
                    }
                } else {
                    removeSlocumTrack(datasetId);
                }
            });
        });
    }

    setLoading(true);
    loadSlocumDatasets()
        .then(async (data) => {
            setLoading(false);
            renderActiveList(data.active);
            populateDatasetSelect(data.active);
            if (isSlocumHome && data.active && data.active.length > 0) {
                const ids = data.active.map((ds) => ds.datasetID || ds.datasetId).filter(Boolean);
                try {
                    const timeRangeParams = getTimeRangeForSlocumLoad();
                    await loadMultipleSlocumTracks(ids, timeRangeParams);
                    if (activeList) {
                        activeList.querySelectorAll('.slocum-dataset-cb').forEach((cb) => {
                            if (ids.includes(cb.getAttribute('data-dataset-id'))) cb.checked = true;
                        });
                    }
                } catch (error) {
                    showToast(error.message || 'Failed to auto-load Slocum tracks', 'warning');
                }
            }
        })
        .catch(() => {
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
                list.forEach((ds) => {
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
                        try {
                            const timeRangeParams = getTimeRangeForSlocumLoad();
                            const colorIndex = slocumTracks.length;
                            await loadSlocumTrack(datasetId, timeRangeParams, colorIndex);
                        } catch (error) {
                            showToast(error.message || 'Invalid time range', 'danger');
                            return;
                        }
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

const WG_OVERLAY_COLORS = ['#3388ff', '#dc143c', '#32cd32', '#ff8c00', '#9370db', '#ff69b4', '#00ced1', '#ffa500'];

/**
 * Add a Wave Glider track without clearing existing mission tracks (overlay mode).
 */
async function loadWgOverlayTrack(missionId, queryParams = { hours_back: '72' }, colorIndex = 0) {
    if (!missionMap) {
        showToast('Map not initialized', 'danger');
        return;
    }
    if (missionTracks.some((t) => t.missionId === missionId)) return;
    try {
        const queryString = to_query_string(queryParams);
        const data = await apiRequest(`/api/map/telemetry/${missionId}?${queryString}`, 'GET');
        if (!data.track_points || data.track_points.length === 0) {
            showToast(`No track data for mission ${missionId}`, 'warning');
            return;
        }
        const color = WG_OVERLAY_COLORS[colorIndex % WG_OVERLAY_COLORS.length];
        const trackLayer = L.polyline(
            data.track_points.map((point) => [point.lat, point.lon]),
            { color, weight: 3, opacity: 0.8 }
        ).addTo(missionMap);
        const positionLayer = createCurrentPositionMarker(
            data.track_points,
            color,
            `Mission ${missionId}`,
            `/wave-glider?mission=${encodeURIComponent(missionId)}`
        );
        missionTracks.push({
            missionId,
            layer: trackLayer,
            positionLayer,
            pointCount: data.point_count,
            bounds: data.bounds
        });
        fitMapToAllTracks();
        updateWgTrackInfo();
        notifyWindOverlayTracksChanged();
    } catch (error) {
        showToast(`Error loading Wave Glider track ${missionId}: ${error.message}`, 'danger');
    }
}

function removeMissionTrack(missionId) {
    const idx = missionTracks.findIndex((t) => t.missionId === missionId);
    if (idx === -1) return;
    const track = missionTracks[idx];
    if (missionMap && track.layer) missionMap.removeLayer(track.layer);
    removeTrackExtraLayers(track);
    missionTracks.splice(idx, 1);
    updateWgTrackInfo();
    notifyWindOverlayTracksChanged();
}

function updateWgTrackInfo() {
    const infoElement = document.getElementById('wgTrackInfo');
    if (!infoElement) return;
    if (missionTracks.length === 0) {
        infoElement.innerHTML = '';
        return;
    }
    const totalPoints = missionTracks.reduce((sum, t) => sum + (t.pointCount || 0), 0);
    infoElement.innerHTML =
        `<div class="alert alert-secondary mb-2"><strong>Wave Gliders</strong> – ` +
        `${missionTracks.length} mission(s), ${totalPoints.toLocaleString()} points</div>`;
}

/**
 * Initialize Wave Glider overlay checkboxes on Slocum home.
 */
function initWgOverlayUI() {
    const section = document.getElementById('wgMissionsSection');
    if (!section || !missionMap) return;
    const activeList = document.getElementById('wgActiveList');
    const clearBtn = document.getElementById('wgClearTracksBtn');

    function getTimeRangeForWgLoad() {
        return get_map_time_range_params();
    }

    if (activeList) {
        activeList.querySelectorAll('.wg-mission-cb').forEach((cb) => {
            cb.addEventListener('change', async function () {
                const missionId = this.getAttribute('data-mission-id') || this.value;
                if (this.checked) {
                    try {
                        const timeRangeParams = getTimeRangeForWgLoad();
                        const colorIndex = missionTracks.length;
                        await loadWgOverlayTrack(missionId, timeRangeParams, colorIndex);
                    } catch (error) {
                        this.checked = false;
                        showToast(error.message || 'Invalid time range', 'danger');
                    }
                } else {
                    removeMissionTrack(missionId);
                }
            });
        });
    }

    if (clearBtn) {
        clearBtn.addEventListener('click', () => {
            clearTracks();
            updateWgTrackInfo();
            if (activeList) {
                activeList.querySelectorAll('.wg-mission-cb').forEach((cb) => { cb.checked = false; });
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
 * Generate and download Live KML network link (Wave Glider or Slocum home).
 */
async function generateLiveKML() {
    const mapCard = document.getElementById('missionMapContainer')?.closest('.card-body');
    const platform = mapCard?.getAttribute('data-platform') || 'wave_glider';
    const isSlocum = platform === 'slocum';
    const missionSelect = document.getElementById('mapMissionSelect');
    const datasetSelect = document.getElementById('mapDatasetSelect');
    const resourceSelect = isSlocum ? datasetSelect : missionSelect;
    const selectedValue = resourceSelect ? resourceSelect.value : null;
    const resourceNoun = isSlocum ? 'dataset' : 'mission';

    let hoursBack = 72;
    try {
        const timeRangeParams = get_map_time_range_params();
        if (!timeRangeParams.hours_back) {
            displayLiveKMLStatus('Live KML supports preset hour ranges only. Switch Time Range mode to "Preset range".', 'info');
            return;
        }
        hoursBack = parseInt(timeRangeParams.hours_back, 10) || 72;
    } catch (error) {
        displayLiveKMLStatus(error.message, 'danger');
        return;
    }

    if (!selectedValue || selectedValue === '') {
        displayLiveKMLStatus(`Please select a ${resourceNoun}`, 'danger');
        return;
    }

    let resourceIds = [];
    if (selectedValue === 'all') {
        if (isSlocum && datasetSelect) {
            resourceIds = [...datasetSelect.options]
                .map((o) => o.value)
                .filter((v) => v && v !== 'all');
        } else {
            const activeMissionsData = mapCard?.getAttribute('data-active-missions');
            if (activeMissionsData) {
                try {
                    resourceIds = JSON.parse(activeMissionsData);
                } catch (_err) {
                    resourceIds = [];
                }
            }
        }
        if (!resourceIds.length) {
            displayLiveKMLStatus(`No active ${resourceNoun}s available`, 'danger');
            return;
        }
        if (resourceIds.length > 1) {
            displayLiveKMLStatus(
                `Multi-${resourceNoun} tokens work best for 72 hours or less. For longer periods, generate separate tokens for better performance.`,
                'info'
            );
        }
    } else {
        resourceIds = [selectedValue];
    }

    try {
        if (selectedValue === 'all' && hoursBack > 72) {
            const proceed = confirm(
                `Multi-${resourceNoun} Live KML tokens are only recommended for time periods of 72 hours or less.\n\n` +
                `For longer time periods, generate separate tokens for each ${resourceNoun} for better performance.\n\n` +
                'Continue anyway?'
            );
            if (!proceed) {
                displayLiveKMLStatus(
                    `Operation cancelled. Please generate tokens for individual ${resourceNoun}s for better performance.`,
                    'info'
                );
                return;
            }
        }

        displayLiveKMLStatus('Generating live KML link...', 'info');

        const data = await apiRequest('/api/kml/create_live', 'POST', {
            mission_ids: resourceIds,
            hours_back: hoursBack,
            platform,
            description: `Live ${isSlocum ? 'Slocum' : 'Wave Glider'} track for ${resourceIds.join(', ')}`
        });

        const downloadResponse = await fetch(`/api/kml/network_link/${data.token}`);
        const blob = await downloadResponse.blob();

        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `live_track_${data.token.substring(0, 8)}.kml`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);

        const expiresAtUtc = formatUtcDate(data.expires_at);
        displayLiveKMLStatus(
            `✓ Live KML generated! Token expires ${expiresAtUtc}<br>` +
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
async function downloadMissionKML(missionId, queryParams = { hours_back: '72' }) {
    try {
        const queryString = to_query_string(queryParams);
        const url = `/api/map/kml/${missionId}?${queryString}`;
        
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
        // Slocum dataset picker (when feature enabled and section/controls present)
        initSlocumUI();
        // Wave Glider overlay on Slocum home
        initWgOverlayUI();

        // Set up event listeners for controls
        const generateBtn = document.getElementById('generateMapBtn');
        const downloadBtn = document.getElementById('downloadKMLBtn');
        const missionSelect = document.getElementById('mapMissionSelect');
        const datasetSelect = document.getElementById('mapDatasetSelect');
        
        if (generateBtn) {
            generateBtn.addEventListener('click', function() {
                try {
                    const timeRangeParams = get_map_time_range_params();

                    // Slocum home: dataset selector drives the map
                    if (datasetSelect && !missionSelect) {
                        const selectedDataset = datasetSelect.value;
                        if (!selectedDataset || selectedDataset === '') {
                            displayErrorMessage('Please select a dataset');
                            return;
                        }
                        if (selectedDataset === 'all') {
                            const ids = [...datasetSelect.options]
                                .map((o) => o.value)
                                .filter((v) => v && v !== 'all');
                            if (ids.length === 0) {
                                displayErrorMessage('No active datasets available');
                                return;
                            }
                            loadMultipleSlocumTracks(ids, timeRangeParams);
                            const activeList = document.getElementById('slocumActiveList');
                            if (activeList) {
                                activeList.querySelectorAll('.slocum-dataset-cb').forEach((cb) => {
                                    cb.checked = ids.includes(cb.getAttribute('data-dataset-id'));
                                });
                            }
                        } else {
                            clearSlocumTracks();
                            loadSlocumTrack(selectedDataset, timeRangeParams, 0).then(() => {
                                const activeList = document.getElementById('slocumActiveList');
                                if (activeList) {
                                    activeList.querySelectorAll('.slocum-dataset-cb').forEach((cb) => {
                                        cb.checked = cb.getAttribute('data-dataset-id') === selectedDataset;
                                    });
                                }
                            });
                        }
                        return;
                    }

                    const selectedMission = missionSelect ? missionSelect.value : null;
                    if (!selectedMission || selectedMission === '') {
                        displayErrorMessage('Please select a mission');
                        return;
                    }
                    if (selectedMission === 'all') {
                        const mapCard = document.getElementById('missionMapContainer')?.closest('.card-body');
                        const activeMissionsData = mapCard?.getAttribute('data-active-missions');
                        
                        if (activeMissionsData) {
                            try {
                                const activeMissions = JSON.parse(activeMissionsData);
                                loadMultipleMissionTracks(activeMissions, timeRangeParams);
                            } catch (error) {
                                showToast('Error loading missions', 'danger');
                                displayErrorMessage('Error loading missions');
                            }
                        } else {
                            displayErrorMessage('No active missions available');
                        }
                    } else {
                        loadMissionTrack(selectedMission, timeRangeParams);
                    }
                } catch (error) {
                    displayErrorMessage(error.message);
                }
            });
        }
        
        if (downloadBtn) {
            downloadBtn.addEventListener('click', function() {
                try {
                    const timeRangeParams = get_map_time_range_params();

                    if (datasetSelect && !missionSelect) {
                        const selectedDataset = datasetSelect.value;
                        if (!selectedDataset || selectedDataset === '') {
                            displayErrorMessage('Please select a dataset');
                            return;
                        }
                        if (selectedDataset === 'all') {
                            displayErrorMessage('Multi-dataset KML export is not available as a static download. Use "Live KML" to export all active datasets.');
                            return;
                        }
                        downloadSlocumKML(selectedDataset, timeRangeParams);
                        return;
                    }

                    const selectedMission = missionSelect ? missionSelect.value : null;
                    if (!selectedMission || selectedMission === '') {
                        displayErrorMessage('Please select a mission');
                        return;
                    }
                    if (selectedMission === 'all') {
                        displayErrorMessage('Multi-mission KML export is not available as a static download. Use "Live KML" to export all active missions.');
                        return;
                    }
                    downloadMissionKML(selectedMission, timeRangeParams);
                } catch (error) {
                    displayErrorMessage(error.message);
                }
            });
        }
        const timeRangeModeSelect = document.getElementById('mapTimeRangeMode');
        if (timeRangeModeSelect) {
            timeRangeModeSelect.addEventListener('change', apply_map_time_range_visibility);
            apply_map_time_range_visibility();
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
    loadMultipleSlocumTracks,
    removeSlocumTrack,
    updateSlocumTrackInfo,
    initSlocumUI,
    initWgOverlayUI,
    loadWgOverlayTrack,
    removeMissionTrack,
    updateWgTrackInfo,
    generateLiveKML,
    downloadMissionKML,
    downloadSlocumKML
};


