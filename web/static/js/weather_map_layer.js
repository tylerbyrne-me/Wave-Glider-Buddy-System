/**
 * @file weather_map_layer.js
 * @description Open-Meteo raster wind overlay for the home-page Leaflet map.
 *
 * Data volume controls:
 * - Tiles load only when the wind toggle is on (lazy).
 * - syncWeatherRequestBounds() limits OM partial fetches to viewport ∩ track region (no clippingOptions).
 * - maxZoom capped at 8 (tiles are visually similar below z12 per Open-Meteo docs).
 * - latest.json metadata is fetched once per session from Buddy cache API; time slider changes are debounced.
 */

import { showToast, fetchWithAuth } from '/static/js/api.js';

const WIND_META_URL = '/api/map/weather/manifest';
/**
 * OM tile request variable. Despite the name, Open-Meteo's reader loads both U and V
 * components and derives total wind speed (sqrt(u^2 + v^2)) for raster coloring.
 */
const WIND_REQUEST_VARIABLE = 'wind_u_component_10m';
/** Color scale key for total wind speed magnitude (m/s). */
const WIND_LEGEND_VARIABLE = 'wind';
const WIND_LAYER_MAX_ZOOM = 12;
const REGION_BBOX_PAD_DEG = 1.0;
const FALLBACK_BOUNDS = [-78.0, 36.0, -70.0, 44.0];
const FORECAST_HORIZON_MS = 7 * 24 * 60 * 60 * 1000;
const TIME_STEP_INTERVAL_HOURS = 3;
const TIME_SLIDER_DEBOUNCE_MS = 300;

let missionMapRef = null;
let getTrackLayersRef = null;
let leafletAdapter = null;
let windLayer = null;
let windMetaCache = null;
let windTimeSteps = [];
let isWindEnabled = false;
let isProtocolRegistered = false;
let timeSliderDebounceTimer = null;

/**
 * @param {import('leaflet').Map} map
 * @param {() => import('leaflet').Layer[]} getTrackLayers
 */
export function bindWindOverlayContext(map, getTrackLayers) {
    missionMapRef = map;
    getTrackLayersRef = getTrackLayers;
}

/**
 * Derive [west, south, east, north] clipping bounds from loaded tracks.
 * @returns {[number, number, number, number]}
 */
export function getActiveRegionBounds() {
    if (!getTrackLayersRef) {
        return FALLBACK_BOUNDS;
    }

    const layers = getTrackLayersRef().filter(Boolean);
    if (layers.length === 0) {
        return FALLBACK_BOUNDS;
    }

    const group = L.featureGroup(layers);
    if (!group.getBounds().isValid()) {
        return FALLBACK_BOUNDS;
    }

    const bounds = group.getBounds();
    return [
        bounds.getWest() - REGION_BBOX_PAD_DEG,
        bounds.getSouth() - REGION_BBOX_PAD_DEG,
        bounds.getEast() + REGION_BBOX_PAD_DEG,
        bounds.getNorth() + REGION_BBOX_PAD_DEG,
    ];
}

function getOmWeatherMapLayer() {
    return typeof window !== 'undefined' ? window.OMWeatherMapLayer : undefined;
}

function rgbaToCss(color) {
    const [r, g, b, a = 1] = color;
    return `rgba(${r}, ${g}, ${b}, ${a})`;
}

function formatLegendValue(value) {
    if (!Number.isFinite(value)) {
        return '—';
    }
    if (Math.abs(value) >= 10) {
        return String(Math.round(value));
    }
    if (Number.isInteger(value)) {
        return String(value);
    }
    return value.toFixed(1);
}

/**
 * Build legend gradient/min/max from the same color scale the map tiles use.
 * @param {{type: string, breakpoints?: number[], colors?: number[][], min?: number, max?: number, unit?: string}} colorScale
 */
function buildLegendFromColorScale(colorScale) {
    if (colorScale.type === 'breakpoint' && colorScale.breakpoints?.length && colorScale.colors?.length) {
        const min = colorScale.breakpoints[0];
        const max = colorScale.breakpoints[colorScale.breakpoints.length - 1];
        const range = max - min || 1;
        const stops = colorScale.breakpoints.map((breakpoint, index) => {
            const pct = ((breakpoint - min) / range) * 100;
            const color = colorScale.colors[Math.min(index, colorScale.colors.length - 1)];
            return `${rgbaToCss(color)} ${pct}%`;
        });
        return {
            gradient: `linear-gradient(to right, ${stops.join(', ')})`,
            min,
            max,
            unit: colorScale.unit || '',
        };
    }

    if (colorScale.type === 'rgba' && colorScale.colors?.length) {
        const stops = colorScale.colors.map((color, index) => {
            const pct = (index / Math.max(1, colorScale.colors.length - 1)) * 100;
            return `${rgbaToCss(color)} ${pct}%`;
        });
        return {
            gradient: `linear-gradient(to right, ${stops.join(', ')})`,
            min: colorScale.min,
            max: colorScale.max,
            unit: colorScale.unit || '',
        };
    }

    return null;
}

function updateWindLegend() {
    const container = document.getElementById('windLegend');
    const bar = document.getElementById('windLegendBar');
    const minEl = document.getElementById('windLegendMin');
    const maxEl = document.getElementById('windLegendMax');
    const titleEl = document.getElementById('windLegendTitle');
    if (!container || !bar || !minEl || !maxEl || !titleEl) {
        return;
    }

    if (!isWindEnabled) {
        container.classList.add('opacity-50');
        titleEl.textContent = 'Legend:';
        bar.style.background = 'linear-gradient(to right, #ccc, #999)';
        minEl.textContent = '—';
        maxEl.textContent = '—';
        return;
    }

    const omLayer = getOmWeatherMapLayer();
    if (!omLayer?.getColorScale) {
        return;
    }

    const colorScale = omLayer.getColorScale(WIND_LEGEND_VARIABLE, false);
    const legend = buildLegendFromColorScale(colorScale);
    if (!legend) {
        return;
    }

    container.classList.remove('opacity-50');
    titleEl.textContent = legend.unit ? `Legend (${legend.unit}):` : 'Legend:';
    bar.style.background = legend.gradient;
    minEl.textContent = formatLegendValue(legend.min);
    maxEl.textContent = formatLegendValue(legend.max);
}

/**
 * Limit OM partial fetches to the intersection of map viewport and padded track region.
 * Avoids clippingOptions.bounds, which can yield blank raster tiles in the Leaflet adapter.
 */
function syncWeatherRequestBounds() {
    const omLayer = getOmWeatherMapLayer();
    if (!omLayer?.updateCurrentBounds || !missionMapRef) {
        return;
    }

    const [regionWest, regionSouth, regionEast, regionNorth] = getActiveRegionBounds();
    const view = missionMapRef.getBounds();
    const west = Math.max(regionWest, view.getWest());
    const south = Math.max(regionSouth, view.getSouth());
    const east = Math.min(regionEast, view.getEast());
    const north = Math.min(regionNorth, view.getNorth());

    if (west < east && south < north) {
        omLayer.updateCurrentBounds([west, south, east, north]);
        return;
    }

    omLayer.updateCurrentBounds([
        view.getWest(),
        view.getSouth(),
        view.getEast(),
        view.getNorth(),
    ]);
}

function ensureWindPane() {
    if (!missionMapRef || missionMapRef.getPane('windWeatherPane')) {
        return;
    }
    missionMapRef.createPane('windWeatherPane');
    const pane = missionMapRef.getPane('windWeatherPane');
    if (pane) {
        pane.style.zIndex = '350';
    }
}

function ensureLeafletAdapter() {
    if (leafletAdapter) {
        return leafletAdapter;
    }

    const omLayer = getOmWeatherMapLayer();
    if (!omLayer) {
        throw new Error('Open-Meteo weather map layer library is not loaded');
    }
    if (typeof L === 'undefined') {
        throw new Error('Leaflet is not loaded');
    }

    leafletAdapter = omLayer.addLeafletProtocolSupport(L);

    if (!isProtocolRegistered) {
        leafletAdapter.addProtocol('om', omLayer.omProtocol);
        isProtocolRegistered = true;
    }

    return leafletAdapter;
}

/**
 * Fetch and cache model metadata (valid_times, variables).
 * @returns {Promise<{valid_times: string[], variables: string[]}>}
 */
export async function fetchWindMeta() {
    if (windMetaCache) {
        return windMetaCache;
    }

    const response = await fetchWithAuth(WIND_META_URL);
    if (!response.ok) {
        throw new Error(`Failed to load wind metadata (${response.status})`);
    }

    const data = await response.json();
    if (!Array.isArray(data.valid_times) || data.valid_times.length === 0) {
        throw new Error('Wind metadata has no valid forecast times');
    }
    if (!Array.isArray(data.variables) || !data.variables.includes(WIND_REQUEST_VARIABLE)) {
        throw new Error(`Wind variable "${WIND_REQUEST_VARIABLE}" is not available for this model`);
    }

    windMetaCache = data;
    return data;
}

/**
 * Build slider steps: current time + 3-hourly forecast out to 7 days.
 * @param {string[]} validTimes
 * @returns {Array<{label: string, timeStep: string, validTime: string|null}>}
 */
function buildWindTimeSteps(validTimes) {
    const steps = [{
        label: 'Current',
        timeStep: 'current_time_1H',
        validTime: null,
    }];

    validTimes.forEach((validTime, index) => {
        if (index === 0) {
            return;
        }
        const validMs = Date.parse(validTime);
        if (Number.isNaN(validMs)) {
            return;
        }
        const nowMs = Date.now();
        if (validMs - nowMs > FORECAST_HORIZON_MS) {
            return;
        }
        if (validMs < nowMs - 60 * 60 * 1000) {
            return;
        }
        if (index % TIME_STEP_INTERVAL_HOURS !== 0) {
            return;
        }

        steps.push({
            label: formatWindTimeLabel(validTime),
            timeStep: `valid_times_${index}`,
            validTime,
        });
    });

    return steps;
}

function formatWindTimeLabel(isoTime) {
    const parsed = Date.parse(isoTime);
    if (Number.isNaN(parsed)) {
        return isoTime;
    }
    return new Date(parsed).toISOString().replace('T', ' ').replace(':00.000Z', 'Z');
}

function padUtc(value) {
    return String(value).padStart(2, '0');
}

/**
 * Resolve manifest timestep to a proxied .om URL on Buddy (same-origin, disk-backed).
 * @param {string} timeStep
 * @returns {Promise<string>}
 */
async function resolveWindOmBaseUrl(timeStep) {
    const meta = await fetchWindMeta();
    if (meta.om_proxy_urls?.[timeStep]) {
        const proxyPath = meta.om_proxy_urls[timeStep];
        return `${window.location.origin}${proxyPath.startsWith('/') ? '' : '/'}${proxyPath}`;
    }

    const modelRun = new Date(meta.reference_time);
    if (Number.isNaN(modelRun.getTime())) {
        throw new Error('Wind metadata has an invalid reference_time');
    }

    let validDate;
    if (timeStep.startsWith('valid_times_')) {
        const index = parseInt(timeStep.slice('valid_times_'.length), 10);
        validDate = new Date(meta.valid_times[index]);
    } else {
        const nowMs = Date.now();
        let nearestTime = meta.valid_times[0];
        let nearestDiff = Infinity;
        meta.valid_times.forEach((validTime) => {
            const diff = Math.abs(Date.parse(validTime) - nowMs);
            if (diff < nearestDiff) {
                nearestDiff = diff;
                nearestTime = validTime;
            }
        });
        validDate = new Date(nearestTime);
    }

    if (Number.isNaN(validDate.getTime())) {
        throw new Error('Could not resolve a valid forecast time for the wind layer');
    }

    const omPath = [
        modelRun.getUTCFullYear(),
        padUtc(modelRun.getUTCMonth() + 1),
        padUtc(modelRun.getUTCDate()),
        `${padUtc(modelRun.getUTCHours())}00Z`,
        `${validDate.getUTCFullYear()}-${padUtc(validDate.getUTCMonth() + 1)}-${padUtc(validDate.getUTCDate())}T${padUtc(validDate.getUTCHours())}00.om`,
    ].join('/');

    const params = new URLSearchParams({ variable: WIND_REQUEST_VARIABLE });
    return `${window.location.origin}/api/map/weather/om/data_spatial/dwd_icon/${omPath}?${params.toString()}`;
}

function getWindOpacity() {
    const opacityInput = document.getElementById('windOpacity');
    if (!opacityInput) {
        return 0.7;
    }
    const value = parseInt(opacityInput.value, 10);
    if (Number.isNaN(value)) {
        return 0.7;
    }
    return Math.min(1, Math.max(0, value / 100));
}

function updateWindOpacityLabel() {
    const label = document.getElementById('windOpacityValue');
    const opacityInput = document.getElementById('windOpacity');
    if (!label || !opacityInput) {
        return;
    }
    label.textContent = `${opacityInput.value}%`;
}

function updateWindTimeLabel() {
    const label = document.getElementById('windTimeLabel');
    const slider = document.getElementById('windTimeSlider');
    if (!label || !slider || windTimeSteps.length === 0) {
        return;
    }
    const step = windTimeSteps[parseInt(slider.value, 10)] || windTimeSteps[0];
    label.textContent = step.label;
}

function attachWindLayerDiagnostics(layer) {
    if (!layer || typeof layer.on !== 'function') {
        return;
    }

    layer.on('tileerror', (event) => {
        console.warn('[wind-overlay] tile load error', event?.error || event);
    });
}

export function removeWindLayer() {
    if (windLayer && missionMapRef) {
        missionMapRef.removeLayer(windLayer);
    }
    windLayer = null;
}

/**
 * @param {string} timeStep
 */
export async function addWindLayer(timeStep) {
    if (!missionMapRef || !isWindEnabled) {
        return;
    }

    ensureWindPane();
    const adapter = ensureLeafletAdapter();
    syncWeatherRequestBounds();
    removeWindLayer();

    const omBaseUrl = await resolveWindOmBaseUrl(timeStep);
    const tileUrl = `om://${omBaseUrl}`;
    windLayer = adapter.createTileLayer(tileUrl, {
        opacity: getWindOpacity(),
        maxZoom: WIND_LAYER_MAX_ZOOM,
        pane: 'windWeatherPane',
        attribution: 'Wind: <a href="https://open-meteo.com/" target="_blank" rel="noopener">Open-Meteo</a> / DWD ICON',
    });
    attachWindLayerDiagnostics(windLayer);
    windLayer.addTo(missionMapRef);

    if (typeof windLayer.redraw === 'function') {
        windLayer.redraw();
    }
    if (typeof missionMapRef.invalidateSize === 'function') {
        missionMapRef.invalidateSize();
    }
}

function getSelectedWindTimeStep() {
    const slider = document.getElementById('windTimeSlider');
    if (!slider || windTimeSteps.length === 0) {
        return 'current_time_1H';
    }
    const index = parseInt(slider.value, 10);
    const step = windTimeSteps[index] || windTimeSteps[0];
    return step.timeStep;
}

async function applyWindLayerState() {
    if (!isWindEnabled) {
        removeWindLayer();
        updateWindLegend();
        return;
    }

    try {
        await fetchWindMeta();
        await addWindLayer(getSelectedWindTimeStep());
        updateWindLegend();
    } catch (error) {
        showToast(`Wind overlay error: ${error.message}`, 'danger');
        isWindEnabled = false;
        const toggle = document.getElementById('windLayerToggle');
        if (toggle) {
            toggle.checked = false;
        }
        removeWindLayer();
        updateWindLegend();
    }
}

export function refreshWindLayerIfActive() {
    if (!isWindEnabled) {
        return;
    }
    applyWindLayerState();
}

async function populateWindTimeSlider() {
    const slider = document.getElementById('windTimeSlider');
    if (!slider) {
        return;
    }

    const meta = await fetchWindMeta();
    windTimeSteps = buildWindTimeSteps(meta.valid_times);
    slider.min = '0';
    slider.max = String(Math.max(0, windTimeSteps.length - 1));
    slider.value = '0';
    slider.disabled = windTimeSteps.length <= 1;
    updateWindTimeLabel();
}

function setWindControlsEnabled(enabled) {
    const timeSlider = document.getElementById('windTimeSlider');
    const opacityInput = document.getElementById('windOpacity');
    if (timeSlider) {
        timeSlider.disabled = !enabled || windTimeSteps.length <= 1;
    }
    if (opacityInput) {
        opacityInput.disabled = !enabled;
    }
}

/**
 * Wire wind overlay UI when the feature-gated section is present.
 */
export function initWindOverlay() {
    const section = document.getElementById('windWeatherSection');
    if (!section || !missionMapRef) {
        return;
    }

    const toggle = document.getElementById('windLayerToggle');
    const opacityInput = document.getElementById('windOpacity');
    const timeSlider = document.getElementById('windTimeSlider');

    updateWindOpacityLabel();
    updateWindLegend();

    populateWindTimeSlider().catch((error) => {
        showToast(`Failed to load wind forecast times: ${error.message}`, 'warning');
    });

    if (toggle) {
        toggle.addEventListener('change', async function() {
            isWindEnabled = this.checked;
            setWindControlsEnabled(isWindEnabled);
            if (isWindEnabled) {
                try {
                    await populateWindTimeSlider();
                } catch (error) {
                    showToast(`Failed to load wind forecast times: ${error.message}`, 'danger');
                    this.checked = false;
                    isWindEnabled = false;
                    setWindControlsEnabled(false);
                    return;
                }
            }
            await applyWindLayerState();
        });
    }

    if (opacityInput) {
        opacityInput.addEventListener('input', function() {
            updateWindOpacityLabel();
            if (windLayer) {
                windLayer.setOpacity(getWindOpacity());
            }
        });
    }

    if (timeSlider) {
        timeSlider.addEventListener('input', function() {
            updateWindTimeLabel();
            if (!isWindEnabled) {
                return;
            }
            if (timeSliderDebounceTimer) {
                clearTimeout(timeSliderDebounceTimer);
            }
            timeSliderDebounceTimer = setTimeout(() => {
                applyWindLayerState();
            }, TIME_SLIDER_DEBOUNCE_MS);
        });
    }

    if (missionMapRef) {
        missionMapRef.on('moveend', () => {
            if (!isWindEnabled) {
                return;
            }
            syncWeatherRequestBounds();
            if (windLayer && typeof windLayer.redraw === 'function') {
                windLayer.redraw();
            }
        });
    }
}
