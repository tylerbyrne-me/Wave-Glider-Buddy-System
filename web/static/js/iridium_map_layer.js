/**
 * @file iridium_map_layer.js
 * @description Iridium constellation overlay for the home-page Leaflet map.
 *
 * - Fetches cached TLEs from /api/map/iridium/tles
 * - Propagates with satellite.js (SGP4)
 * - Shows sats above loaded gliders (elev >= 8.2°), elevation-mask footprints,
 *   and a next-pass timeline for the selected observer
 */

import { showToast, fetchWithAuth } from '/static/js/api.js';

const TLE_URL = '/api/map/iridium/tles';
const MIN_ELEVATION_DEG = 8.2;
const EARTH_RADIUS_M = 6371000;
const TICK_MS = 5000;
const PASS_HORIZON_MS = 2 * 60 * 60 * 1000;
const PASS_STEP_MS = 30 * 1000;
const IRIDIUM_PANE = 'iridiumPane';
const IRIDIUM_PANE_Z = 450;
const MARKER_COLOR = '#c45c26';
const FOOTPRINT_COLOR = '#c45c26';

let missionMapRef = null;
let getObserversRef = null;
let isIridiumEnabled = false;
let tickTimer = null;
let satRecords = [];
let tleMeta = null;
let markerLayerGroup = null;
let footprintLayerGroup = null;
let lastPassScanAt = 0;
const PASS_SCAN_INTERVAL_MS = 60000;

/**
 * @param {import('leaflet').Map} map
 * @param {() => Array<{id: string, label: string, lat: number, lon: number}>} getObservers
 */
export function bindIridiumOverlayContext(map, getObservers) {
    missionMapRef = map;
    getObserversRef = getObservers;
}

function getSatelliteApi() {
    return typeof window !== 'undefined' ? window.satellite : undefined;
}

function ensureIridiumPane() {
    if (!missionMapRef) {
        return;
    }
    if (!missionMapRef.getPane(IRIDIUM_PANE)) {
        missionMapRef.createPane(IRIDIUM_PANE);
        missionMapRef.getPane(IRIDIUM_PANE).style.zIndex = String(IRIDIUM_PANE_Z);
    }
}

function getObservers() {
    if (!getObserversRef) {
        return [];
    }
    return (getObserversRef() || []).filter(
        (obs) =>
            obs &&
            Number.isFinite(obs.lat) &&
            Number.isFinite(obs.lon) &&
            Math.abs(obs.lat) <= 90 &&
            Math.abs(obs.lon) <= 180
    );
}

/**
 * Footprint ground radius from satellite altitude and minimum elevation mask.
 * @param {number} altitudeM
 * @param {number} minElevDeg
 * @returns {number} radius in meters
 */
export function footprintRadiusMeters(altitudeM, minElevDeg = MIN_ELEVATION_DEG) {
    if (!Number.isFinite(altitudeM) || altitudeM <= 0) {
        return 0;
    }
    const eps = (minElevDeg * Math.PI) / 180;
    const ratio = EARTH_RADIUS_M / (EARTH_RADIUS_M + altitudeM);
    const cosTerm = ratio * Math.cos(eps);
    if (cosTerm >= 1) {
        return 0;
    }
    const rho = Math.acos(cosTerm) - eps;
    if (!Number.isFinite(rho) || rho <= 0) {
        return 0;
    }
    return EARTH_RADIUS_M * rho;
}

function degrees(radians) {
    return (radians * 180) / Math.PI;
}

function formatUtcTime(date) {
    if (!(date instanceof Date) || Number.isNaN(date.getTime())) {
        return '—';
    }
    return date.toISOString().replace('T', ' ').replace(/\.\d{3}Z$/, ' UTC');
}

function formatDuration(ms) {
    if (!Number.isFinite(ms) || ms < 0) {
        return '—';
    }
    const totalSec = Math.round(ms / 1000);
    const h = Math.floor(totalSec / 3600);
    const m = Math.floor((totalSec % 3600) / 60);
    const s = totalSec % 60;
    if (h > 0) {
        return `${h}h ${m}m`;
    }
    if (m > 0) {
        return `${m}m ${s}s`;
    }
    return `${s}s`;
}

function buildSatRecords(satellites) {
    const api = getSatelliteApi();
    if (!api) {
        throw new Error('satellite.js is not loaded');
    }
    const records = [];
    for (const sat of satellites || []) {
        if (!sat?.line1 || !sat?.line2) {
            continue;
        }
        try {
            const satrec = api.twoline2satrec(sat.line1, sat.line2);
            if (!satrec || satrec.error) {
                continue;
            }
            records.push({
                noradId: sat.norad_id,
                name: sat.name || `NORAD ${sat.norad_id}`,
                satrec,
            });
        } catch {
            // Skip malformed TLEs
        }
    }
    return records;
}

/**
 * Propagate one sat at date; return geodetic + ECF position or null.
 * @param {{satrec: object, name: string, noradId?: number}} record
 * @param {Date} date
 */
function propagateGeodetic(record, date) {
    const api = getSatelliteApi();
    if (!api) {
        return null;
    }
    const pv = api.propagate(record.satrec, date);
    if (!pv?.position || pv.position.x == null) {
        return null;
    }
    const gmst = api.gstime(date);
    const gd = api.eciToGeodetic(pv.position, gmst);
    const ecf = api.eciToEcf(pv.position, gmst);
    return {
        lat: degrees(gd.latitude),
        lon: degrees(gd.longitude),
        altM: gd.height * 1000,
        positionEcf: ecf,
    };
}

/**
 * Look angles from observer to satellite ECF position.
 * @returns {{elevationDeg: number, azimuthDeg: number}|null}
 */
function lookAngles(observer, positionEcf, date) {
    const api = getSatelliteApi();
    if (!api || !positionEcf) {
        return null;
    }
    const toRad = api.degreesToRadians
        ? (deg) => api.degreesToRadians(deg)
        : (deg) => (deg * Math.PI) / 180;
    const observerGd = {
        longitude: toRad(observer.lon),
        latitude: toRad(observer.lat),
        height: 0,
    };
    const look = api.ecfToLookAngles(observerGd, positionEcf);
    return {
        elevationDeg: degrees(look.elevation),
        azimuthDeg: degrees(look.azimuth),
    };
}

function clearMapLayers() {
    if (markerLayerGroup && missionMapRef) {
        missionMapRef.removeLayer(markerLayerGroup);
    }
    if (footprintLayerGroup && missionMapRef) {
        missionMapRef.removeLayer(footprintLayerGroup);
    }
    markerLayerGroup = null;
    footprintLayerGroup = null;
}

function stopTick() {
    if (tickTimer) {
        clearInterval(tickTimer);
        tickTimer = null;
    }
}

function setControlsEnabled(enabled) {
    const select = document.getElementById('iridiumObserverSelect');
    if (select) {
        select.disabled = !enabled;
    }
}

function syncObserverSelect(observers) {
    const select = document.getElementById('iridiumObserverSelect');
    if (!select) {
        return;
    }
    const previous = select.value;
    select.innerHTML = '';
    if (!observers.length) {
        const opt = document.createElement('option');
        opt.value = '';
        opt.textContent = 'No glider positions loaded';
        select.appendChild(opt);
        return;
    }
    for (const obs of observers) {
        const opt = document.createElement('option');
        opt.value = obs.id;
        opt.textContent = obs.label || obs.id;
        select.appendChild(opt);
    }
    if (previous && observers.some((o) => o.id === previous)) {
        select.value = previous;
    }
}

function renderPassPanel(html) {
    const panel = document.getElementById('iridiumPassPanel');
    if (panel) {
        panel.innerHTML = html;
    }
}

function selectedObserver(observers) {
    const select = document.getElementById('iridiumObserverSelect');
    const id = select?.value;
    if (id) {
        const match = observers.find((o) => o.id === id);
        if (match) {
            return match;
        }
    }
    return observers[0] || null;
}

/**
 * Scan next PASS_HORIZON_MS for AOS / peak / LOS for one observer.
 */
function scanNextPass(observer, now = new Date()) {
    if (!observer || !satRecords.length) {
        return null;
    }

    const samples = [];
    for (let t = 0; t <= PASS_HORIZON_MS; t += PASS_STEP_MS) {
        const date = new Date(now.getTime() + t);
        let bestElev = -90;
        let bestName = null;
        for (const record of satRecords) {
            const geo = propagateGeodetic(record, date);
            if (!geo) {
                continue;
            }
            const look = lookAngles(observer, geo.positionEcf, date);
            if (!look) {
                continue;
            }
            if (look.elevationDeg > bestElev) {
                bestElev = look.elevationDeg;
                bestName = record.name;
            }
        }
        samples.push({
            time: date,
            elev: bestElev,
            inView: bestElev >= MIN_ELEVATION_DEG,
            name: bestName,
        });
    }

    const currentlyInView = samples[0]?.inView;
    let aosIndex = -1;
    if (currentlyInView) {
        aosIndex = 0;
    } else {
        for (let i = 1; i < samples.length; i += 1) {
            if (!samples[i - 1].inView && samples[i].inView) {
                aosIndex = i;
                break;
            }
        }
    }
    if (aosIndex < 0) {
        return { currentlyInView: false, noneInHorizon: true };
    }

    let peak = samples[aosIndex];
    let losIndex = aosIndex;
    for (let i = aosIndex; i < samples.length; i += 1) {
        if (samples[i].elev > peak.elev) {
            peak = samples[i];
        }
        if (samples[i].inView) {
            losIndex = i;
        }
        if (i > aosIndex && !samples[i].inView) {
            losIndex = i - 1;
            break;
        }
    }

    const aos = samples[aosIndex];
    const los = samples[losIndex];
    return {
        currentlyInView: Boolean(currentlyInView),
        noneInHorizon: false,
        aosTime: aos.time,
        aosSat: aos.name,
        peakTime: peak.time,
        peakElev: peak.elev,
        peakSat: peak.name,
        losTime: los.time,
        gapMs: currentlyInView ? 0 : aos.time.getTime() - now.getTime(),
    };
}

function updatePassPanel(observers, force = false) {
    const now = Date.now();
    if (!force && now - lastPassScanAt < PASS_SCAN_INTERVAL_MS) {
        return;
    }
    lastPassScanAt = now;

    const observer = selectedObserver(observers);
    if (!observer) {
        renderPassPanel('<span class="text-muted">Load a mission track to see next Iridium pass.</span>');
        return;
    }

    const result = scanNextPass(observer, new Date());
    if (!result) {
        renderPassPanel('<span class="text-muted">Unable to compute pass timeline.</span>');
        return;
    }
    if (result.noneInHorizon) {
        renderPassPanel(
            `<div><strong>${observer.label}</strong>: no pass with elev ≥ ${MIN_ELEVATION_DEG}° in the next 2 hours.</div>`
        );
        return;
    }

    const status = result.currentlyInView
        ? `<span class="text-success fw-semibold">In pass now</span>`
        : `Next AOS in <strong>${formatDuration(result.gapMs)}</strong>`;

    renderPassPanel(`
        <div class="small">
            <div class="mb-1"><strong>${observer.label}</strong> — ${status}</div>
            <div>AOS: ${formatUtcTime(result.aosTime)}${result.aosSat ? ` (${result.aosSat})` : ''}</div>
            <div>Peak: ${result.peakElev.toFixed(1)}° at ${formatUtcTime(result.peakTime)}${result.peakSat ? ` (${result.peakSat})` : ''}</div>
            <div>LOS: ${formatUtcTime(result.losTime)}</div>
        </div>
    `);
}

function redrawOverlay() {
    if (!isIridiumEnabled || !missionMapRef || !satRecords.length) {
        return;
    }

    const observers = getObservers();
    syncObserverSelect(observers);
    ensureIridiumPane();

    const now = new Date();
    const inViewByNorad = new Map();

    for (const record of satRecords) {
        const geo = propagateGeodetic(record, now);
        if (!geo) {
            continue;
        }
        const visibleFor = [];
        let bestElev = -90;
        let bestAz = 0;
        for (const obs of observers) {
            const look = lookAngles(obs, geo.positionEcf, now);
            if (!look || look.elevationDeg < MIN_ELEVATION_DEG) {
                continue;
            }
            visibleFor.push({
                id: obs.id,
                label: obs.label,
                elev: look.elevationDeg,
                az: look.azimuthDeg,
            });
            if (look.elevationDeg > bestElev) {
                bestElev = look.elevationDeg;
                bestAz = look.azimuthDeg;
            }
        }
        if (!visibleFor.length) {
            continue;
        }
        const key = String(record.noradId ?? record.name);
        inViewByNorad.set(key, {
            record,
            geo,
            visibleFor,
            bestElev,
            bestAz,
        });
    }

    clearMapLayers();
    markerLayerGroup = L.layerGroup().addTo(missionMapRef);
    footprintLayerGroup = L.layerGroup().addTo(missionMapRef);

    for (const entry of inViewByNorad.values()) {
        const { record, geo, visibleFor, bestElev, bestAz } = entry;
        const radiusM = footprintRadiusMeters(geo.altM, MIN_ELEVATION_DEG);
        if (radiusM > 0) {
            L.circle([geo.lat, geo.lon], {
                radius: radiusM,
                color: FOOTPRINT_COLOR,
                weight: 1,
                opacity: 0.55,
                fillColor: FOOTPRINT_COLOR,
                fillOpacity: 0.08,
                pane: IRIDIUM_PANE,
                interactive: false,
            }).addTo(footprintLayerGroup);
        }

        const gliderList = visibleFor
            .map((v) => `${v.label}: ${v.elev.toFixed(1)}° elev / ${v.az.toFixed(0)}° az`)
            .join('<br>');
        const popup = [
            `<strong>${record.name}</strong>`,
            record.noradId != null ? `NORAD ${record.noradId}` : null,
            `Alt ${ (geo.altM / 1000).toFixed(0) } km`,
            `Best elev ${bestElev.toFixed(1)}° · az ${bestAz.toFixed(0)}°`,
            gliderList,
        ]
            .filter(Boolean)
            .join('<br>');

        L.circleMarker([geo.lat, geo.lon], {
            radius: 6,
            color: '#ffffff',
            weight: 2,
            fillColor: MARKER_COLOR,
            fillOpacity: 1,
            pane: IRIDIUM_PANE,
        })
            .bindPopup(popup)
            .addTo(markerLayerGroup);
    }

    const countEl = document.getElementById('iridiumInViewCount');
    if (countEl) {
        countEl.textContent = observers.length
            ? `${inViewByNorad.size} in view (≥ ${MIN_ELEVATION_DEG}°)`
            : 'No observers';
    }

    updatePassPanel(observers);
}

async function fetchTles() {
    const response = await fetchWithAuth(TLE_URL);
    if (!response.ok) {
        let detail = `TLE fetch failed (${response.status})`;
        try {
            const body = await response.json();
            if (body?.detail) {
                detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
            }
        } catch {
            // keep status-based message
        }
        const err = new Error(detail);
        err.status = response.status;
        throw err;
    }
    return response.json();
}

function formatCacheAge(ageSeconds) {
    if (!Number.isFinite(ageSeconds) || ageSeconds < 0) {
        return null;
    }
    if (ageSeconds < 90) {
        return `${Math.round(ageSeconds)}s`;
    }
    if (ageSeconds < 3600) {
        return `${(ageSeconds / 60).toFixed(1)}m`;
    }
    return `${(ageSeconds / 3600).toFixed(1)}h`;
}

function updateTleMeta(payload) {
    const metaEl = document.getElementById('iridiumTleMeta');
    if (!metaEl) {
        return;
    }
    const count = (payload.satellites || []).length;
    const parts = [`${count} sats`, payload.source || 'Iridium-E'];
    const ageLabel = formatCacheAge(payload.age_seconds);
    if (ageLabel) {
        parts.push(`age ${ageLabel}`);
    }
    if (payload.stale) {
        parts.push('stale');
    }
    if (payload.rate_limit_reason === 'upstream_ttl_gate') {
        parts.push('rate-limited');
    } else if (payload.rate_limit_reason === 'upstream_error') {
        parts.push('upstream error');
    }
    metaEl.textContent = parts.join(' · ');
}

async function enableOverlay() {
    if (!missionMapRef) {
        throw new Error('Map not initialized');
    }
    const payload = await fetchTles();
    satRecords = buildSatRecords(payload.satellites);
    if (!satRecords.length) {
        throw new Error('No usable Iridium TLEs in response');
    }
    tleMeta = {
        fetchedAt: payload.fetched_at,
        source: payload.source,
        count: satRecords.length,
        cacheHit: payload.cache_hit,
        stale: Boolean(payload.stale),
        ageSeconds: payload.age_seconds,
    };
    updateTleMeta(payload);
    if (payload.stale) {
        showToast(
            'Iridium TLEs are stale (CelesTrak refresh waiting on TTL). Showing last cached constellation.',
            'warning'
        );
    }
    isIridiumEnabled = true;
    setControlsEnabled(true);
    lastPassScanAt = 0;
    redrawOverlay();
    stopTick();
    tickTimer = setInterval(redrawOverlay, TICK_MS);
}

function disableOverlay() {
    isIridiumEnabled = false;
    stopTick();
    clearMapLayers();
    setControlsEnabled(false);
    satRecords = [];
    tleMeta = null;
    const countEl = document.getElementById('iridiumInViewCount');
    if (countEl) {
        countEl.textContent = '';
    }
    const metaEl = document.getElementById('iridiumTleMeta');
    if (metaEl) {
        metaEl.textContent = '';
    }
    renderPassPanel('<span class="text-muted">Enable Iridium overlay to see next-pass timing.</span>');
}

async function applyIridiumLayerState() {
    if (!isIridiumEnabled) {
        disableOverlay();
        return;
    }
    try {
        await enableOverlay();
    } catch (error) {
        const message = error?.message || 'Unknown error';
        const hint =
            /rate-limited|empty|CelesTrak|502|503/i.test(message)
                ? ' Retry later, or ask an admin to check CelesTrak egress / cache status (purge only if needed, then wait for the 2h TTL).'
                : '';
        showToast(`Iridium overlay error: ${message}.${hint}`, 'danger');
        isIridiumEnabled = false;
        const toggle = document.getElementById('iridiumLayerToggle');
        if (toggle) {
            toggle.checked = false;
        }
        disableOverlay();
    }
}

export function refreshIridiumLayerIfActive() {
    if (!isIridiumEnabled) {
        return;
    }
    lastPassScanAt = 0;
    redrawOverlay();
}

export function initIridiumOverlay() {
    const toggle = document.getElementById('iridiumLayerToggle');
    if (!toggle) {
        return;
    }

    toggle.addEventListener('change', async () => {
        isIridiumEnabled = toggle.checked;
        if (isIridiumEnabled) {
            await applyIridiumLayerState();
        } else {
            disableOverlay();
        }
    });

    const select = document.getElementById('iridiumObserverSelect');
    if (select) {
        select.addEventListener('change', () => {
            if (!isIridiumEnabled) {
                return;
            }
            lastPassScanAt = 0;
            updatePassPanel(getObservers(), true);
        });
    }

    renderPassPanel('<span class="text-muted">Enable Iridium overlay to see next-pass timing.</span>');
}
