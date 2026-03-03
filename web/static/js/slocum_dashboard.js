/**
 * Slocum Glider mission dashboard – load and plot m_depth, m_altitude, m_raw_altitude, m_water_depth.
 * Fetches from /api/slocum/chart-data/{dataset_id}?variable=...&hours_back=...&granularity_minutes=...
 * Active datasets: auto-refresh (countdown + full page reload) like Wave Glider. Historical: no auto-refresh.
 */
import { apiRequest, showToast } from '/static/js/api.js';

const VARIABLES = ['m_depth', 'm_altitude', 'm_raw_altitude', 'm_water_depth'];
const DEFAULT_HOURS = 24;
const DEFAULT_GRANULARITY = 15;

const chartInstances = {};

// Chart formatting to match Wave Glider standard (time format, grid, axis labels, font sizes)
const SLOCUM_CHART_FONT = { title: 14, ticks: 12, legend: 12 };

function getSlocumChartTheme() {
    const styles = getComputedStyle(document.body);
    return {
        gridColor: styles.getPropertyValue('--card-border')?.trim() || 'rgba(255,255,255,0.12)',
        textColor: styles.getPropertyValue('--body-color')?.trim() || 'rgba(255,255,255,0.87)',
    };
}
const SLOCUM_TIME_OPTIONS = {
    unit: 'hour',
    stepSize: 2,
    tooltipFormat: 'MMM d, yyyy HH:mm',
    displayFormats: { hour: 'MMM d HH:mm', day: 'MMM d', month: 'MMM' },
};

/** Draw "No data available" on a chart canvas (shared by Overview, UWP, Nav, Power). */
function drawNoDataOnCanvas(canvas) {
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    ctx.font = '16px Arial';
    ctx.fillStyle = '#888';
    ctx.textAlign = 'center';
    ctx.fillText('No data available', canvas.width / 2, canvas.height / 2);
}

// Underwater Positioning: multi-series charts (variable key -> display label)
const UWP_CHART_COLORS = [
    'rgb(75, 192, 192)',
    'rgb(255, 99, 132)',
    'rgb(54, 162, 235)',
    'rgb(255, 206, 86)',
];
// Unit per variable: 'deg' = left Y axis (degrees), 'm' = right Y axis (meters) for dual-axis charts
const UNDERWATER_POSITIONING_CHARTS = [
    {
        key: 'uwp-pitch',
        canvasId: 'slocumChartUwpPitch',
        spinnerId: 'slocumUwpPitchSpinner',
        chartTitle: 'Pitch & Depth',
        variables: ['c_pitch', 'm_pitch', 'm_depth'],
        labels: { c_pitch: 'Commanded Pitch', m_pitch: 'Measured Pitch', m_depth: 'Measured Depth' },
        units: { c_pitch: 'deg', m_pitch: 'deg', m_depth: 'm' },
    },
    {
        key: 'uwp-roll',
        canvasId: 'slocumChartUwpRoll',
        spinnerId: 'slocumUwpRollSpinner',
        chartTitle: 'Roll & Depth',
        variables: ['m_roll', 'm_depth', 'm_pitch'],
        labels: { m_roll: 'Measured Roll', m_depth: 'Measured Depth', m_pitch: 'Measured Pitch' },
        units: { m_roll: 'deg', m_depth: 'm', m_pitch: 'deg' },
    },
    {
        key: 'uwp-altitude',
        canvasId: 'slocumChartUwpAltitude',
        spinnerId: 'slocumUwpAltitudeSpinner',
        chartTitle: 'Altitude & Depth',
        variables: ['m_altitude', 'm_raw_altitude', 'm_depth', 'm_water_depth'],
        labels: {
            m_altitude: 'Measured Altitude',
            m_raw_altitude: 'Measured Raw Altitude',
            m_depth: 'Measured Depth',
            m_water_depth: 'Measured Water Depth',
        },
        units: { m_altitude: 'm', m_raw_altitude: 'm', m_depth: 'm', m_water_depth: 'm' },
    },
];
let uwpChartsLoaded = false;

// Navigation: heading and fin charts with computed delta series
const NAVIGATION_CHARTS = [
    {
        key: 'nav-heading',
        canvasId: 'slocumChartNavHeading',
        spinnerId: 'slocumNavHeadingSpinner',
        chartTitle: 'Heading',
        variables: ['c_heading', 'm_heading'],
        computed: [
            { id: 'delta_heading', from: ['c_heading', 'm_heading'], label: 'Delta Heading', unit: 'deg', op: 'diff' },
        ],
        labels: { c_heading: 'Commanded Heading', m_heading: 'Measured Heading', delta_heading: 'Delta Heading' },
        units: { c_heading: 'deg', m_heading: 'deg', delta_heading: 'deg' },
    },
    {
        key: 'nav-fin',
        canvasId: 'slocumChartNavFin',
        spinnerId: 'slocumNavFinSpinner',
        chartTitle: 'Fin Position',
        variables: ['c_fin', 'm_fin'],
        computed: [
            { id: 'delta_fin', from: ['c_fin', 'm_fin'], label: 'Delta Fin Position', unit: 'rad', op: 'diff' },
        ],
        labels: { c_fin: 'Commanded Fin', m_fin: 'Measured Fin', delta_fin: 'Delta Fin Position' },
        units: { c_fin: 'rad', m_fin: 'rad', delta_fin: 'rad' },
    },
];
let navChartsLoaded = false;

// Power: battery and amp-hour charts (amp-hour has computed consecutive delta)
const POWER_CHARTS = [
    {
        key: 'power-battery',
        canvasId: 'slocumChartPowerBattery',
        spinnerId: 'slocumPowerBatterySpinner',
        chartTitle: 'Battery Voltage',
        variables: ['m_battery'],
        labels: { m_battery: 'Measured Battery' },
        units: { m_battery: 'V' },
    },
    {
        key: 'power-amphr',
        canvasId: 'slocumChartPowerAmphr',
        spinnerId: 'slocumPowerAmphrSpinner',
        chartTitle: 'Amp-Hour Total',
        variables: ['m_coulomb_amphr_total'],
        computed: [
            { id: 'delta_amphr_total', from: ['m_coulomb_amphr_total'], label: 'Delta Amphr Total', unit: 'A·hr', op: 'diffConsecutive' },
        ],
        labels: { m_coulomb_amphr_total: 'Amphr Total', delta_amphr_total: 'Delta Amphr Total' },
        units: { m_coulomb_amphr_total: 'A·hr', delta_amphr_total: 'A·hr' },
    },
];
let powerChartsLoaded = false;

// CTD: conductivity/temperature/pressure and density/salinity/m_depth
const CTD_CHARTS = [
    {
        key: 'ctd-conductivity-temp-pressure',
        canvasId: 'slocumChartCtdConductivityTempPressure',
        spinnerId: 'slocumCtdConductivityTempPressureSpinner',
        chartTitle: 'Conductivity, Temperature & Pressure',
        variables: ['conductivity', 'temperature', 'pressure'],
        labels: { conductivity: 'Conductivity', temperature: 'Temperature', pressure: 'Pressure' },
        units: { conductivity: 'S/m', temperature: '°C', pressure: 'dbar' },
        multiAxis: true,
    },
    {
        key: 'ctd-density-salinity-depth',
        canvasId: 'slocumChartCtdDensitySalinityDepth',
        spinnerId: 'slocumCtdDensitySalinityDepthSpinner',
        chartTitle: 'Density, Salinity & Depth',
        variables: ['density', 'salinity', 'm_depth'],
        labels: { density: 'Density', salinity: 'Salinity', m_depth: 'Depth' },
        units: { density: 'kg/m³', salinity: 'PSU', m_depth: 'm' },
        multiAxis: true,
    },
];
let ctdChartsLoaded = false;

// Auto-refresh (mirror Wave Glider dashboard)
const AUTO_REFRESH_INTERVAL_MINUTES = 5;
let autoRefreshEnabled = true;
let countdownTimer = null;
let fallbackReloadTimeoutId = null;

function getDatasetId() {
    return document.body.dataset.dataset || '';
}

function isHistoricalDataset() {
    return document.body.dataset.isHistorical === 'true';
}

function getHoursBack() {
    const el = document.getElementById('slocumHoursBack');
    return el ? parseInt(el.value, 10) || DEFAULT_HOURS : DEFAULT_HOURS;
}

function getGranularity() {
    const el = document.getElementById('slocumGranularity');
    return el ? parseInt(el.value, 10) || DEFAULT_GRANULARITY : DEFAULT_GRANULARITY;
}

/** @returns {{ startISO: string, endISO: string } | null} when both From/To are set. */
function getSlocumDateRange() {
    const startEl = document.getElementById('start-date-slocum');
    const endEl = document.getElementById('end-date-slocum');
    const startVal = startEl?.value?.trim();
    const endVal = endEl?.value?.trim();
    if (!startVal || !endVal) return null;
    const startDate = new Date(startVal);
    const endDate = new Date(endVal);
    return { startISO: startDate.toISOString(), endISO: endDate.toISOString() };
}

function isSlocumDateRangeActive() {
    return getSlocumDateRange() !== null;
}

function updateSlocumDateRangeState() {
    const startEl = document.getElementById('start-date-slocum');
    const endEl = document.getElementById('end-date-slocum');
    const clearBtn = document.getElementById('clear-date-slocum');
    const hoursEl = document.getElementById('slocumHoursBack');
    const startVal = startEl?.value?.trim();
    const endVal = endEl?.value?.trim();
    const hasRange = !!(startVal && endVal);
    if (clearBtn) clearBtn.style.display = startVal || endVal ? 'inline-block' : 'none';
    if (hoursEl) {
        hoursEl.disabled = hasRange;
        hoursEl.style.opacity = hasRange ? '0.5' : '1';
    }
}

function handleSlocumDateRangeChange() {
    const startEl = document.getElementById('start-date-slocum');
    const endEl = document.getElementById('end-date-slocum');
    updateSlocumDateRangeState();
    const startVal = startEl?.value?.trim();
    const endVal = endEl?.value?.trim();
    if (!startVal || !endVal) return;
    const startDate = new Date(startVal);
    const endDate = new Date(endVal);
    if (startDate >= endDate) {
        showToast('Start date must be before end date.', 'warning');
        return;
    }
    refreshAllCharts();
    if (uwpChartsLoaded) refreshUnderwaterPositioningCharts();
    if (navChartsLoaded) refreshNavigationCharts();
    if (powerChartsLoaded) refreshPowerCharts();
    if (ctdChartsLoaded) refreshCTDCharts();
}

function clearSlocumDateRange() {
    const startEl = document.getElementById('start-date-slocum');
    const endEl = document.getElementById('end-date-slocum');
    if (startEl) startEl.value = '';
    if (endEl) endEl.value = '';
    updateSlocumDateRangeState();
    refreshAllCharts();
    if (uwpChartsLoaded) refreshUnderwaterPositioningCharts();
    if (navChartsLoaded) refreshNavigationCharts();
    if (powerChartsLoaded) refreshPowerCharts();
    if (ctdChartsLoaded) refreshCTDCharts();
}

function initSlocumDateRangeControls() {
    const startEl = document.getElementById('start-date-slocum');
    const endEl = document.getElementById('end-date-slocum');
    const clearBtn = document.getElementById('clear-date-slocum');
    [startEl, endEl].filter(Boolean).forEach((el) => {
        el.addEventListener('change', handleSlocumDateRangeChange);
        el.addEventListener('input', handleSlocumDateRangeChange);
    });
    if (clearBtn) clearBtn.addEventListener('click', clearSlocumDateRange);
    updateSlocumDateRangeState();
}

function saveSlocumChartsAsPng(highResolution = false) {
    const overview = document.getElementById('detail-overview');
    const uwp = document.getElementById('detail-underwater_positioning');
    const nav = document.getElementById('detail-navigation');
    const power = document.getElementById('detail-power');
    const ctd = document.getElementById('detail-ctd');
    const containers = [overview, uwp, nav, power, ctd].filter(Boolean);
    const canvases = containers.flatMap((el) => Array.from(el.querySelectorAll('canvas')));
    const datasetId = getDatasetId() || 'slocum';
    const scaleFactor = highResolution ? 4 : 1;
    const bodyBg = getComputedStyle(document.body).getPropertyValue('--bs-body-bg').trim() || '#fff';
    let count = 0;
    canvases.forEach((canvas) => {
        const chart = getSlocumChartInstanceByCanvasId(canvas.id);
        if (!chart) return;
        const w = chart.canvas.width * scaleFactor;
        const h = chart.canvas.height * scaleFactor;
        const newCanvas = document.createElement('canvas');
        newCanvas.width = w;
        newCanvas.height = h;
        const ctx = newCanvas.getContext('2d');
        ctx.fillStyle = bodyBg;
        ctx.fillRect(0, 0, w, h);
        ctx.scale(scaleFactor, scaleFactor);
        ctx.drawImage(chart.canvas, 0, 0);
        const link = document.createElement('a');
        link.href = newCanvas.toDataURL('image/png');
        link.download = `${datasetId}_${canvas.id}${highResolution ? '_high_res' : ''}.png`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        count++;
    });
    if (count === 0) showToast('No charts available to save. Load the Overview or Underwater Positioning view first.', 'info');
}

function setSummary(variable, value) {
    const el = document.getElementById(`${variable}_summary`);
    if (!el) return;
    if (value == null || Number.isNaN(value)) {
        el.textContent = 'N/A';
    } else {
        el.textContent = `${Number(value).toFixed(2)} m`;
    }
}

function hideSpinner(variable) {
    const el = document.getElementById(`${variable}_spinner`);
    if (el) el.style.display = 'none';
}

function showSpinner(variable) {
    const el = document.getElementById(`${variable}_spinner`);
    if (el) el.style.display = 'block';
}

function renderChart(variable, chartData) {
    const canvasId = `slocumChart${variable.split('_').map(s => s.charAt(0).toUpperCase() + s.slice(1)).join('')}`;
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;

    if (chartInstances[variable]) {
        chartInstances[variable].destroy();
        chartInstances[variable] = null;
    }

    const data = (chartData && chartData.data) ? chartData.data : [];
    if (!data.length) {
        setSummary(variable, null);
        hideSpinner(variable);
        drawNoDataOnCanvas(canvas);
        return;
    }

    const labels = data.map(d => d.Timestamp);
    const values = data.map(d => d.Value != null ? d.Value : null);
    const lastValue = values.filter(v => v != null).pop();
    setSummary(variable, lastValue);
    hideSpinner(variable);

    const theme = getSlocumChartTheme();
    const yAxisTitles = {
        m_depth: 'Depth (m)',
        m_altitude: 'Altitude (m)',
        m_raw_altitude: 'Altitude (m)',
        m_water_depth: 'Water Depth (m)',
    };
    const yTitle = yAxisTitles[variable] || 'Value (m)';
    const title = variable.replace(/_/g, ' ') + ' (m)';
    chartInstances[variable] = new Chart(canvas, {
        type: 'line',
        data: {
            labels,
            datasets: [{
                label: `${variable.replace(/_/g, ' ')} (m)`,
                data: values,
                borderColor: 'rgb(75, 192, 192)',
                fill: false,
                tension: 0.2,
                showLine: true,
                pointRadius: 4,
                pointBackgroundColor: 'rgb(75, 192, 192)',
                pointStyle: 'circle',
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                title: {
                    display: true,
                    text: title,
                    position: 'top',
                    align: 'center',
                    color: theme.textColor,
                    font: { size: SLOCUM_CHART_FONT.title },
                },
                legend: {
                    display: true,
                    position: 'top',
                    align: 'center',
                    labels: { color: theme.textColor, font: { size: SLOCUM_CHART_FONT.legend } },
                },
            },
            scales: {
                x: {
                    type: 'time',
                    time: SLOCUM_TIME_OPTIONS,
                    title: {
                        display: true,
                        text: 'Time',
                        color: theme.textColor,
                        font: { size: SLOCUM_CHART_FONT.ticks },
                    },
                    ticks: {
                        color: theme.textColor,
                        maxRotation: 0,
                        autoSkip: true,
                        stepSize: 2,
                        font: { size: SLOCUM_CHART_FONT.ticks },
                    },
                    grid: { color: theme.gridColor },
                },
                y: {
                    title: {
                        display: true,
                        text: yTitle,
                        color: theme.textColor,
                        font: { size: SLOCUM_CHART_FONT.ticks },
                    },
                    ticks: { color: theme.textColor, font: { size: SLOCUM_CHART_FONT.ticks } },
                    grid: { color: theme.gridColor },
                },
            },
        },
    });
}

/** Build query params for Slocum chart-data or CSV (time window + granularity). */
function buildSlocumQueryParams(opts) {
    const { variable, granularity_minutes, hours_back, dateRange, is_historical } = opts;
    const params = new URLSearchParams();
    if (variable != null) params.set('variable', variable);
    params.set('granularity_minutes', String(granularity_minutes));
    if (dateRange) {
        params.set('start_date', dateRange.startISO);
        params.set('end_date', dateRange.endISO);
    } else {
        params.set('hours_back', String(hours_back));
    }
    if (is_historical) params.set('is_historical', 'true');
    return params;
}

function buildChartDataUrl(variable, hours, granularity) {
    const datasetId = getDatasetId();
    if (!datasetId) return '';
    const params = buildSlocumQueryParams({
        variable,
        granularity_minutes: granularity,
        hours_back: hours,
        dateRange: getSlocumDateRange(),
        is_historical: isHistoricalDataset(),
    });
    return `/api/slocum/chart-data/${encodeURIComponent(datasetId)}?${params.toString()}`;
}

/** Build URL for CSV download using same time/granularity as chart controls. */
function buildSlocumCsvUrl() {
    const datasetId = getDatasetId();
    if (!datasetId) return '';
    const params = buildSlocumQueryParams({
        granularity_minutes: getGranularity(),
        hours_back: getHoursBack(),
        dateRange: getSlocumDateRange(),
        is_historical: isHistoricalDataset(),
    });
    return `/api/slocum/csv/${encodeURIComponent(datasetId)}?${params.toString()}`;
}

/** Map canvas id to chartInstances key (e.g. slocumChartMDepth -> m_depth, slocumChartUwpPitch -> uwp-pitch). */
function getSlocumChartKeyFromCanvasId(canvasId) {
    if (!canvasId || !canvasId.startsWith('slocumChart')) return null;
    if (canvasId.startsWith('slocumChartUwp')) {
        const suffix = canvasId.replace('slocumChartUwp', '');
        return 'uwp-' + suffix.charAt(0).toLowerCase() + suffix.slice(1);
    }
    if (canvasId.startsWith('slocumChartNav')) {
        const suffix = canvasId.replace('slocumChartNav', '');
        return 'nav-' + suffix.charAt(0).toLowerCase() + suffix.slice(1);
    }
    if (canvasId.startsWith('slocumChartPower')) {
        const suffix = canvasId.replace('slocumChartPower', '');
        return 'power-' + suffix.charAt(0).toLowerCase() + suffix.slice(1);
    }
    if (canvasId.startsWith('slocumChartCtd')) {
        const suffix = canvasId.replace('slocumChartCtd', '');
        return 'ctd-' + suffix.charAt(0).toLowerCase() + suffix.slice(1);
    }
    const suffix = canvasId.replace('slocumChart', '');
    return suffix.replace(/([A-Z])/g, (m, i) => (i ? '_' : '') + m.toLowerCase());
}

function getSlocumChartInstanceByCanvasId(canvasId) {
    const key = getSlocumChartKeyFromCanvasId(canvasId);
    return key ? chartInstances[key] || null : null;
}

let lastDataTimestampValue = null;

/** Update the "Last data" indicator from API cache_metadata.last_data_timestamp (ISO string). */
function updateLastDataTimestamp(isoString) {
    if (!isoString) return;
    const el = document.getElementById('slocumLastDataTimestamp');
    if (!el) return;
    lastDataTimestampValue = isoString;
    try {
        const d = new Date(isoString);
        if (Number.isNaN(d.getTime())) {
            el.textContent = 'Last data: —';
            return;
        }
        const formatted = d.toLocaleString('en-CA', {
            timeZone: 'UTC',
            year: 'numeric',
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: false,
        }) + ' UTC';
        el.textContent = `Last data: ${formatted}`;
    } catch {
        el.textContent = 'Last data: —';
    }
}

async function fetchAndRender(variable) {
    const datasetId = getDatasetId();
    if (!datasetId) return;
    const hours = getHoursBack();
    const granularity = getGranularity();
    const url = buildChartDataUrl(variable, hours, granularity);
    try {
        const response = await apiRequest(url, 'GET');
        const data = response && response.data ? response : { data: [] };
        if (response?.cache_metadata?.last_data_timestamp) {
            updateLastDataTimestamp(response.cache_metadata.last_data_timestamp);
        }
        renderChart(variable, data);
    } catch (err) {
        console.error(`Slocum chart ${variable} failed:`, err);
        showToast(`Failed to load ${variable}: ${err.message}`, 'danger');
        setSummary(variable, null);
        hideSpinner(variable);
        renderChart(variable, { data: [] });
    }
}

function refreshAllCharts() {
    VARIABLES.forEach(v => showSpinner(v));
    Promise.all(VARIABLES.map(v => fetchAndRender(v)));
}

function showUwpSpinner(spinnerId) {
    const el = document.getElementById(spinnerId);
    if (el) el.style.display = 'block';
}

function hideUwpSpinner(spinnerId) {
    const el = document.getElementById(spinnerId);
    if (el) el.style.display = 'none';
}

async function fetchVariableSeries(variable) {
    const datasetId = getDatasetId();
    if (!datasetId) return { variable, data: [], lastDataTimestamp: null };
    const hours = getHoursBack();
    const granularity = getGranularity();
    const url = buildChartDataUrl(variable, hours, granularity);
    try {
        const response = await apiRequest(url, 'GET');
        const data = (response && response.data) ? response.data : [];
        const lastDataTimestamp = response?.cache_metadata?.last_data_timestamp || null;
        return { variable, data, lastDataTimestamp };
    } catch (err) {
        console.error(`Slocum UWP chart variable ${variable} failed:`, err);
        return { variable, data: [], lastDataTimestamp: null };
    }
}

function mergeSeriesByTime(seriesList) {
    const timeToIndex = new Map();
    const times = [];
    for (const { data } of seriesList) {
        for (const row of data) {
            const t = row.Timestamp;
            if (!timeToIndex.has(t)) {
                timeToIndex.set(t, times.length);
                times.push(t);
            }
        }
    }
    times.sort();
    const valueByVar = {};
    for (const { variable, data } of seriesList) {
        const rowByTime = new Map(data.map((r) => [r.Timestamp, r.Value]));
        valueByVar[variable] = times.map((t) => rowByTime.get(t) ?? null);
    }
    return { labels: times, valueByVar };
}

/** Apply computed series (deltas) to valueByVar. Mutates valueByVar. */
function applyComputed(valueByVar, computed) {
    if (!computed || !computed.length) return;
    for (const c of computed) {
        if (c.op === 'diff' && c.from && c.from.length === 2) {
            const a = valueByVar[c.from[0]];
            const b = valueByVar[c.from[1]];
            if (!a || !b) continue;
            valueByVar[c.id] = a.map((v, i) => {
                const w = b[i];
                if (v == null || w == null) return null;
                return v - w;
            });
        } else if (c.op === 'diffConsecutive' && c.from && c.from.length === 1) {
            const a = valueByVar[c.from[0]];
            if (!a) continue;
            valueByVar[c.id] = a.map((v, i) => {
                if (i === 0) return null;
                const prev = a[i - 1];
                if (v == null || prev == null) return null;
                return v - prev;
            });
        }
    }
}

/** Format unit for legend label. */
function formatUnit(unit) {
    if (unit === 'deg') return '°';
    if (unit === 'rad') return 'rad';
    if (unit === 'V') return 'V';
    if (unit === 'A·hr') return 'A·hr';
    if (unit === 'm') return 'm';
    if (unit === '°C') return '°C';
    if (unit === 'S/m') return 'S/m';
    if (unit === 'dbar') return 'dbar';
    if (unit === 'PSU') return 'PSU';
    if (unit === 'kg/m³') return 'kg/m³';
    return unit || '';
}

function renderMultiSeriesChartFromValueByVar(config, timeLabels, valueByVar, allSeriesIds) {
    const { key: chartKey, canvasId, spinnerId, chartTitle, labels, units } = config;
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    hideUwpSpinner(spinnerId);

    if (chartInstances[chartKey]) {
        chartInstances[chartKey].destroy();
        chartInstances[chartKey] = null;
    }

    if (!timeLabels.length) {
        drawNoDataOnCanvas(canvas);
        return;
    }

    const theme = getSlocumChartTheme();
    const hasDeg = allSeriesIds.some((id) => units && units[id] === 'deg');
    const hasMeters = allSeriesIds.some((id) => units && units[id] === 'm');
    const useDualAxis = hasDeg && hasMeters && !config.multiAxis;
    const useTripleAxis = config.multiAxis && allSeriesIds.length >= 3;
    const pointStyles = ['circle', 'rect', 'triangle'];

    const axisIds = useTripleAxis ? ['y', 'y1', 'y2'] : (useDualAxis ? ['y', 'y1'] : ['y']);
    const axisTitleByUnit = {
        'S/m': 'Conductivity (S/m)',
        '°C': 'Temperature (°C)',
        'dbar': 'Pressure (dbar)',
        'kg/m³': 'Density (kg/m³)',
        'PSU': 'Salinity (PSU)',
        'm': 'Depth (m)',
    };

    const datasets = allSeriesIds.map((id, i) => {
        const color = UWP_CHART_COLORS[i % UWP_CHART_COLORS.length];
        const u = units && units[id];
        const unitStr = formatUnit(u) || (u || '');
        const labelWithUnit = `${labels[id] || id} (${unitStr})`;
        const d = {
            label: labelWithUnit,
            data: valueByVar[id] || [],
            borderColor: color,
            fill: false,
            tension: 0.2,
            showLine: true,
            pointRadius: 4,
            pointBackgroundColor: color,
            pointStyle: pointStyles[i % pointStyles.length],
            borderDash: i === 1 ? [6, 3] : i === 2 ? [2, 2] : undefined,
        };
        if (useTripleAxis && axisIds[i]) {
            d.yAxisID = axisIds[i];
        } else if (useDualAxis && units && units[id]) {
            d.yAxisID = units[id] === 'deg' ? 'y' : 'y1';
        }
        return d;
    });

    const yTitle = useDualAxis ? 'Angle (°)' : (units && units[allSeriesIds[0]] === 'V' ? 'Voltage (V)' : units && units[allSeriesIds[0]] === 'A·hr' ? 'A·hr' : units && units[allSeriesIds[0]] === 'rad' ? 'Angle (rad)' : 'Value');
    const isPowerChart = !useDualAxis && !useTripleAxis && (units && (units[allSeriesIds[0]] === 'V' || units[allSeriesIds[0]] === 'A·hr'));
    const scales = {
        x: {
            type: 'time',
            time: SLOCUM_TIME_OPTIONS,
            position: 'bottom',
            title: { display: true, text: 'Time', color: theme.textColor, font: { size: SLOCUM_CHART_FONT.ticks } },
            ticks: { color: theme.textColor, maxRotation: 0, autoSkip: true, stepSize: 2, font: { size: SLOCUM_CHART_FONT.ticks } },
            grid: { color: theme.gridColor },
        },
        y: {
            position: 'left',
            title: {
                display: true,
                text: useTripleAxis ? (axisTitleByUnit[units[allSeriesIds[0]]] || (labels[allSeriesIds[0]] + ' (' + formatUnit(units[allSeriesIds[0]]) + ')')) : (useDualAxis ? 'Angle (°)' : yTitle),
                color: theme.textColor,
                font: { size: SLOCUM_CHART_FONT.ticks },
            },
            ticks: { color: theme.textColor, font: { size: SLOCUM_CHART_FONT.ticks } },
            grid: { color: theme.gridColor },
            ...(isPowerChart && { suggestedMin: 0, suggestedMax: units[allSeriesIds[0]] === 'V' ? 20 : 400 }),
        },
    };
    if (useDualAxis) {
        scales.y1 = {
            position: 'right',
            title: { display: true, text: 'Depth (m)', color: theme.textColor, font: { size: SLOCUM_CHART_FONT.ticks } },
            ticks: { color: theme.textColor, font: { size: SLOCUM_CHART_FONT.ticks } },
            grid: { drawOnChartArea: false, color: theme.gridColor },
        };
    }
    if (useTripleAxis) {
        scales.y1 = {
            position: 'right',
            title: {
                display: true,
                text: axisTitleByUnit[units[allSeriesIds[1]]] || (labels[allSeriesIds[1]] + ' (' + formatUnit(units[allSeriesIds[1]]) + ')'),
                color: theme.textColor,
                font: { size: SLOCUM_CHART_FONT.ticks },
            },
            ticks: { color: theme.textColor, font: { size: SLOCUM_CHART_FONT.ticks } },
            grid: { drawOnChartArea: false, color: theme.gridColor },
        };
        scales.y2 = {
            position: 'right',
            title: {
                display: true,
                text: axisTitleByUnit[units[allSeriesIds[2]]] || (labels[allSeriesIds[2]] + ' (' + formatUnit(units[allSeriesIds[2]]) + ')'),
                color: theme.textColor,
                font: { size: SLOCUM_CHART_FONT.ticks },
            },
            ticks: { color: theme.textColor, font: { size: SLOCUM_CHART_FONT.ticks } },
            grid: { drawOnChartArea: false, color: theme.gridColor },
        };
    }

    chartInstances[chartKey] = new Chart(canvas, {
        type: 'line',
        data: { labels: timeLabels, datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                title: { display: true, text: chartTitle || '', position: 'top', align: 'center', color: theme.textColor, font: { size: SLOCUM_CHART_FONT.title } },
                legend: { display: true, position: 'top', align: 'center', labels: { color: theme.textColor, font: { size: SLOCUM_CHART_FONT.legend } } },
            },
            scales,
        },
    });
}

function renderMultiSeriesChart(config, seriesList) {
    const { key: chartKey, canvasId, spinnerId, chartTitle, variables, labels, units } = config;
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    hideUwpSpinner(spinnerId);

    if (chartInstances[chartKey]) {
        chartInstances[chartKey].destroy();
        chartInstances[chartKey] = null;
    }

    const { labels: timeLabels, valueByVar } = mergeSeriesByTime(seriesList);
    if (!timeLabels.length) {
        drawNoDataOnCanvas(canvas);
        return;
    }

    const theme = getSlocumChartTheme();
    const hasDeg = variables.some((v) => units && units[v] === 'deg');
    const hasMeters = variables.some((v) => units && units[v] === 'm');
    const useDualAxis = hasDeg && hasMeters;
    const pointStyles = ['circle', 'rect', 'triangle'];

    const datasets = variables.map((v, i) => {
        const color = UWP_CHART_COLORS[i % UWP_CHART_COLORS.length];
        const labelWithUnit = `${labels[v] || v} (${units && units[v] === 'deg' ? '°' : 'm'})`;
        const d = {
            label: labelWithUnit,
            data: valueByVar[v] || [],
            borderColor: color,
            fill: false,
            tension: 0.2,
            showLine: true,
            pointRadius: 4,
            pointBackgroundColor: color,
            pointStyle: pointStyles[i % pointStyles.length],
            borderDash: i === 1 ? [6, 3] : undefined,
        };
        if (useDualAxis && units && units[v]) {
            d.yAxisID = units[v] === 'deg' ? 'y' : 'y1';
        }
        return d;
    });

    const scales = {
        x: {
            type: 'time',
            time: SLOCUM_TIME_OPTIONS,
            position: 'bottom',
            title: {
                display: true,
                text: 'Time',
                color: theme.textColor,
                font: { size: SLOCUM_CHART_FONT.ticks },
            },
            ticks: {
                color: theme.textColor,
                maxRotation: 0,
                autoSkip: true,
                stepSize: 2,
                font: { size: SLOCUM_CHART_FONT.ticks },
            },
            grid: { color: theme.gridColor },
        },
        y: {
            position: 'left',
            title: {
                display: true,
                text: useDualAxis ? 'Angle (°)' : 'Depth / Altitude (m)',
                color: theme.textColor,
                font: { size: SLOCUM_CHART_FONT.ticks },
            },
            ticks: { color: theme.textColor, font: { size: SLOCUM_CHART_FONT.ticks } },
            grid: { color: theme.gridColor },
        },
    };
    if (useDualAxis) {
        scales.y1 = {
            position: 'right',
            title: {
                display: true,
                text: 'Depth (m)',
                color: theme.textColor,
                font: { size: SLOCUM_CHART_FONT.ticks },
            },
            ticks: { color: theme.textColor, font: { size: SLOCUM_CHART_FONT.ticks } },
            grid: { drawOnChartArea: false, color: theme.gridColor },
        };
    }

    chartInstances[chartKey] = new Chart(canvas, {
        type: 'line',
        data: { labels: timeLabels, datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                title: {
                    display: true,
                    text: chartTitle || '',
                    position: 'top',
                    align: 'center',
                    color: theme.textColor,
                    font: { size: SLOCUM_CHART_FONT.title },
                },
                legend: {
                    display: true,
                    position: 'top',
                    align: 'center',
                    labels: { color: theme.textColor, font: { size: SLOCUM_CHART_FONT.legend } },
                },
            },
            scales,
        },
    });
}

async function fetchAndRenderUwpChart(config) {
    showUwpSpinner(config.spinnerId);
    const seriesList = await Promise.all(
        config.variables.map((v) => fetchVariableSeries(v))
    );
    const latestTs = seriesList
        .map((s) => s.lastDataTimestamp)
        .filter(Boolean)
        .sort()
        .pop();
    if (latestTs) updateLastDataTimestamp(latestTs);
    renderMultiSeriesChart(config, seriesList);
}

async function fetchAndRenderChartWithComputed(config) {
    showUwpSpinner(config.spinnerId);
    const seriesList = await Promise.all(
        config.variables.map((v) => fetchVariableSeries(v))
    );
    const latestTs = seriesList
        .map((s) => s.lastDataTimestamp)
        .filter(Boolean)
        .sort()
        .pop();
    if (latestTs) updateLastDataTimestamp(latestTs);
    const { labels: timeLabels, valueByVar } = mergeSeriesByTime(seriesList);
    applyComputed(valueByVar, config.computed || []);
    const allSeriesIds = config.variables.concat((config.computed || []).map((c) => c.id));
    renderMultiSeriesChartFromValueByVar(config, timeLabels, valueByVar, allSeriesIds);
}

function loadUnderwaterPositioningCharts() {
    if (uwpChartsLoaded) return;
    uwpChartsLoaded = true;
    refreshUnderwaterPositioningCharts();
}

function loadNavigationCharts() {
    if (navChartsLoaded) return;
    navChartsLoaded = true;
    refreshNavigationCharts();
}

function refreshNavigationCharts() {
    NAVIGATION_CHARTS.forEach((cfg) => fetchAndRenderChartWithComputed(cfg));
}

function loadPowerCharts() {
    if (powerChartsLoaded) return;
    powerChartsLoaded = true;
    refreshPowerCharts();
}

function refreshPowerCharts() {
    POWER_CHARTS.forEach((cfg) => fetchAndRenderChartWithComputed(cfg));
}

function loadCTDCharts() {
    if (ctdChartsLoaded) return;
    ctdChartsLoaded = true;
    refreshCTDCharts();
}

function refreshCTDCharts() {
    CTD_CHARTS.forEach((cfg) => fetchAndRenderChartWithComputed(cfg));
}

function refreshUnderwaterPositioningCharts() {
    UNDERWATER_POSITIONING_CHARTS.forEach((c) => showUwpSpinner(c.spinnerId));
    Promise.all(
        UNDERWATER_POSITIONING_CHARTS.map((config) =>
            fetchAndRenderUwpChart(config).catch((err) => {
                showToast(`Underwater Positioning chart failed: ${err.message}`, 'danger');
                hideUwpSpinner(config.spinnerId);
            })
        )
    );
}

function handleLeftPanelClicks() {
    const summaryCards = document.querySelectorAll('#left-nav-panel .summary-card');
    const detailViews = document.querySelectorAll('#main-display-area .category-detail-view');

    summaryCards.forEach(card => {
        card.addEventListener('click', function () {
            summaryCards.forEach(c => c.classList.remove('active-card'));
            this.classList.add('active-card');
            const category = this.dataset.category;
            detailViews.forEach(view => { view.style.display = 'none'; });
            const activeDetailView = document.getElementById(`detail-${category}`);
            if (activeDetailView) {
                activeDetailView.style.display = 'block';
            }
            const sectionTitleEl = document.getElementById('slocum-section-title');
            if (sectionTitleEl) {
                const titles = { overview: 'Overview', underwater_positioning: 'Underwater Positioning', navigation: 'Navigation', power: 'Power', ctd: 'CTD' };
                sectionTitleEl.textContent = titles[category] || 'Overview';
            }
            if (category === 'underwater_positioning') loadUnderwaterPositioningCharts();
            else if (category === 'navigation') loadNavigationCharts();
            else if (category === 'power') loadPowerCharts();
            else if (category === 'ctd') loadCTDCharts();
        });
    });
}

function startCountdownTimer() {
    const countdownElement = document.getElementById('refreshCountdown');
    if (!countdownElement) return;
    if (!autoRefreshEnabled) return;

    let remainingSeconds = AUTO_REFRESH_INTERVAL_MINUTES * 60;

    function updateCountdownDisplay() {
        const minutes = Math.floor(remainingSeconds / 60);
        const seconds = remainingSeconds % 60;
        const display = `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
        countdownElement.textContent = ` (Next refresh in ${display})`;

        if (remainingSeconds <= 0) {
            if (countdownTimer) clearInterval(countdownTimer);
            countdownTimer = null;
            countdownElement.textContent = '';
        } else {
            remainingSeconds--;
        }
    }
    updateCountdownDisplay();
    countdownTimer = setInterval(updateCountdownDisplay, 1000);
}

function updateAutoRefreshState(isEnabled) {
    autoRefreshEnabled = isEnabled;
    try {
        localStorage.setItem('autoRefreshEnabled', JSON.stringify(isEnabled));
    } catch (e) { /* ignore */ }

    const isRealtime = !isHistoricalDataset();
    if (isEnabled && isRealtime) {
        startCountdownTimer();
        if (fallbackReloadTimeoutId) clearTimeout(fallbackReloadTimeoutId);
        fallbackReloadTimeoutId = setTimeout(() => {
            if (autoRefreshEnabled && !document.querySelector('.modal.show')) {
                const url = new URL(window.location.href);
                url.searchParams.set('refresh', 'true');
                window.location.href = url.toString();
            }
            fallbackReloadTimeoutId = null;
        }, AUTO_REFRESH_INTERVAL_MINUTES * 60 * 1000);
    } else {
        if (countdownTimer) {
            clearInterval(countdownTimer);
            countdownTimer = null;
        }
        if (fallbackReloadTimeoutId) {
            clearTimeout(fallbackReloadTimeoutId);
            fallbackReloadTimeoutId = null;
        }
        const countdownElement = document.getElementById('refreshCountdown');
        if (countdownElement) countdownElement.textContent = '';
    }
}

function initAutoRefresh() {
    const isRealtime = !isHistoricalDataset();
    if (!isRealtime) return;

    const autoRefreshToggle = document.getElementById('autoRefreshToggleBanner');
    if (!autoRefreshToggle) return;

    const saved = localStorage.getItem('autoRefreshEnabled');
    if (saved !== null) {
        try {
            autoRefreshToggle.checked = JSON.parse(saved);
        } catch (e) { /* use default */ }
    }
    updateAutoRefreshState(autoRefreshToggle.checked);

    autoRefreshToggle.addEventListener('change', function () {
        updateAutoRefreshState(this.checked);
    });
}

document.addEventListener('DOMContentLoaded', () => {
    const datasetId = getDatasetId();
    if (!datasetId) {
        const errEl = document.getElementById('slocumDashboardError');
        if (errEl) {
            errEl.textContent = 'Missing dataset. Go to Slocum Home and select a dataset.';
            errEl.style.display = 'block';
        }
        return;
    }

    refreshAllCharts();

    const hoursSelect = document.getElementById('slocumHoursBack');
    function refreshAllLoadedCharts() {
        refreshAllCharts();
        if (uwpChartsLoaded) refreshUnderwaterPositioningCharts();
        if (navChartsLoaded) refreshNavigationCharts();
        if (powerChartsLoaded) refreshPowerCharts();
        if (ctdChartsLoaded) refreshCTDCharts();
    }

    if (hoursSelect) {
        hoursSelect.addEventListener('change', refreshAllLoadedCharts);
    }

    const granularitySelect = document.getElementById('slocumGranularity');
    if (granularitySelect) {
        granularitySelect.addEventListener('change', refreshAllLoadedCharts);
    }

    const refreshBtn = document.getElementById('slocumRefreshCharts');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', refreshAllLoadedCharts);
    }

    initSlocumDateRangeControls();

    const csvDownloadBtn = document.getElementById('slocum-download-csv');
    if (csvDownloadBtn) {
        csvDownloadBtn.addEventListener('click', (e) => {
            e.preventDefault();
            const url = buildSlocumCsvUrl();
            if (url) window.location.href = url;
            else showToast('Cannot build download URL. Check dataset.', 'warning');
        });
    }
    document.querySelectorAll('[id^="slocum-save-charts-png"]').forEach((btn) => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            const highRes = e.currentTarget.dataset.highRes === 'true';
            saveSlocumChartsAsPng(highRes);
        });
    });

    initAutoRefresh();
    handleLeftPanelClicks();
});
