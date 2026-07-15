/**
 * Slocum Glider mission dashboard – Overview briefing (plan/reports/ST/comments/goals/media)
 * plus CTD depth-vs-time Chart.js scatter charts colored with cmocean stops.
 * Active datasets: auto-refresh via /api/slocum/cache-status. Historical: no auto-refresh.
 */
import { apiRequest, showToast, escapeHTML, fetchWithAuth } from '/static/js/api.js';
import { datetimeLocalToUtcIso, formatUtcDateTime } from '/static/js/datetime_utils.js';

const DEFAULT_HOURS = 24;
const DEFAULT_GRANULARITY = 15;
const DASHBOARD_RECENT_NOTE_LIMIT = 4;

let currentDeploymentId = null;
let currentOverviewInfo = null;
let lastMissionNotesForEdit = [];
let activeChartCategory = null;
let ctdProfilesLoaded = false;
const ctdChartInstances = {};

let chartTextColor = '#212529';
let chartGridColor = '#dee2e6';

const USER_ROLE = document.body.dataset.userRole || '';
const USERNAME = document.body.dataset.username || '';

const escapeHtml = (str) => escapeHTML(String(str ?? ''));
const formatTimestamp = (value) => (value ? formatUtcDateTime(value) : '-');

const CTD_PROFILE_CHARTS = [
    { variable: 'temperature', canvasId: 'slocumCtdTempChart', spinnerId: 'slocumCtdTempSpinner', label: 'Sea Water Temperature' },
    { variable: 'conductivity', canvasId: 'slocumCtdConductivityChart', spinnerId: 'slocumCtdConductivitySpinner', label: 'Conductivity' },
    { variable: 'density', canvasId: 'slocumCtdDensityChart', spinnerId: 'slocumCtdDensitySpinner', label: 'Sea Water Density' },
];

// Auto-refresh via cache-status polling (no full page reload)
const AUTO_REFRESH_INTERVAL_MINUTES = 5;
const AUTO_REFRESH_POLL_INTERVAL_MS = 60 * 1000;
let autoRefreshEnabled = true;
let countdownTimer = null;
let cachePollIntervalId = null;
const slocumCacheTimestamps = new Map();

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
    const startISO = datetimeLocalToUtcIso(startVal);
    const endISO = datetimeLocalToUtcIso(endVal);
    if (!startISO || !endISO) return null;
    return { startISO, endISO };
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
    const startISO = datetimeLocalToUtcIso(startVal);
    const endISO = datetimeLocalToUtcIso(endVal);
    if (!startISO || !endISO) {
        const rangeInfoEl = document.getElementById('slocumDateRangeInfo');
        if (rangeInfoEl) {
            rangeInfoEl.textContent = 'Invalid UTC date range.';
            rangeInfoEl.className = 'text-danger small';
        }
        return;
    }
    const startDate = new Date(startISO);
    const endDate = new Date(endISO);
    if (startDate >= endDate) {
        showToast('Start date must be before end date.', 'warning');
        return;
    }
    refreshLoadedChartTabs();
}

function clearSlocumDateRange() {
    const startEl = document.getElementById('start-date-slocum');
    const endEl = document.getElementById('end-date-slocum');
    if (startEl) startEl.value = '';
    if (endEl) endEl.value = '';
    updateSlocumDateRangeState();
    refreshLoadedChartTabs();
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

function updateChartColorVariables() {
    const styles = getComputedStyle(document.documentElement);
    chartTextColor = styles.getPropertyValue('--text-color').trim() || chartTextColor;
    chartGridColor = styles.getPropertyValue('--card-border').trim() || chartGridColor;
}

function showProfileSpinner(spinnerId) {
    const el = document.getElementById(spinnerId);
    if (!el) return;
    el.style.display = 'block';
    el.classList.remove('spinner-border');
    // Restart CSS animation
    void el.offsetWidth;
    el.classList.add('spinner-border');
}

function hideProfileSpinner(spinnerId) {
    const el = document.getElementById(spinnerId);
    if (el) el.style.display = 'none';
}

function setGranularityControlEnabled(isEnabled) {
    const el = document.getElementById('slocumGranularity');
    if (!el) return;
    el.disabled = !isEnabled;
    el.style.opacity = isEnabled ? '1' : '0.5';
    el.title = isEnabled
        ? 'Set the data resampling interval.'
        : 'Resampling is not applied to CTD depth profiles.';
}

function colorForValue(value, min, max, stops) {
    if (value == null || !Number.isFinite(value) || !stops?.length) return 'rgba(128,128,128,0.6)';
    if (min == null || max == null || !Number.isFinite(min) || !Number.isFinite(max) || min === max) {
        return stops[Math.floor(stops.length / 2)];
    }
    const t = Math.max(0, Math.min(1, (value - min) / (max - min)));
    const idx = Math.min(stops.length - 1, Math.max(0, Math.round(t * (stops.length - 1))));
    return stops[idx];
}

/** Chart.js plugin: draw a vertical cmocean colorbar in the chart's right layout padding. */
const slocumColorbarPlugin = {
    id: 'slocumColorbar',
    afterDraw(chart) {
        const meta = chart.options.plugins?.slocumColorbar;
        if (!meta || !meta.stops?.length) return;
        const { ctx, chartArea } = chart;
        if (!chartArea) return;
        const barWidth = 14;
        const gap = 10;
        const x = chartArea.right + gap;
        const top = chartArea.top;
        const bottom = chartArea.bottom;
        const height = bottom - top;
        if (height <= 0) return;

        const gradient = ctx.createLinearGradient(0, bottom, 0, top);
        const n = meta.stops.length;
        meta.stops.forEach((stop, i) => {
            gradient.addColorStop(i / Math.max(1, n - 1), stop);
        });
        ctx.save();
        ctx.fillStyle = gradient;
        ctx.fillRect(x, top, barWidth, height);
        ctx.strokeStyle = chartGridColor;
        ctx.lineWidth = 1;
        ctx.strokeRect(x, top, barWidth, height);

        const labelColor = chartTextColor;
        ctx.fillStyle = labelColor;
        ctx.font = '11px sans-serif';
        ctx.textAlign = 'left';
        ctx.textBaseline = 'middle';
        const labelX = x + barWidth + 4;
        // Whole-number colorbar labels (server supplies nicified integer ranges).
        const fmt = (v) => (v == null || !Number.isFinite(Number(v)) ? '' : String(Math.round(Number(v))));
        if (meta.max != null) ctx.fillText(fmt(meta.max), labelX, top);
        if (meta.min != null) ctx.fillText(fmt(meta.min), labelX, bottom);
        if (meta.unit) {
            ctx.save();
            ctx.translate(labelX + 28, (top + bottom) / 2);
            ctx.rotate(-Math.PI / 2);
            ctx.textAlign = 'center';
            ctx.fillText(meta.unit, 0, 0);
            ctx.restore();
        }
        ctx.restore();
    },
};

function destroyCtdCharts() {
    Object.keys(ctdChartInstances).forEach((key) => {
        try { ctdChartInstances[key]?.destroy(); } catch (_) { /* ignore */ }
        delete ctdChartInstances[key];
    });
}

function drawNoDataOnCanvas(canvasId, message = 'No data available') {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const width = canvas.parentElement?.clientWidth || canvas.width || 300;
    const height = canvas.parentElement?.clientHeight || canvas.height || 300;
    canvas.width = width;
    canvas.height = height;
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = '#6c757d';
    ctx.font = '16px Arial';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(message, width / 2, height / 2);
}

function buildProfileDataset(points, variable, range, stops) {
    const min = range?.min;
    const max = range?.max;
    const data = [];
    const colors = [];
    for (const p of points || []) {
        const value = p[variable];
        if (value == null || !Number.isFinite(value) || p.depth == null || !Number.isFinite(p.depth) || !p.t) {
            continue;
        }
        data.push({ x: new Date(p.t), y: p.depth, v: value });
        colors.push(colorForValue(value, min, max, stops));
    }
    return { data, colors };
}

function renderOneProfileChart(config, payload) {
    if (typeof Chart === 'undefined') {
        console.error('Chart.js is not loaded');
        return;
    }
    const canvas = document.getElementById(config.canvasId);
    if (!canvas) return;

    const unit = payload?.units?.[config.variable] || '';
    const range = payload?.ranges?.[config.variable] || {};
    const stops = payload?.colormaps?.[config.variable] || [];
    const { data, colors } = buildProfileDataset(payload?.points, config.variable, range, stops);

    if (ctdChartInstances[config.canvasId]) {
        try { ctdChartInstances[config.canvasId].destroy(); } catch (_) { /* ignore */ }
        delete ctdChartInstances[config.canvasId];
    }

    if (!data.length) {
        drawNoDataOnCanvas(config.canvasId, `No ${config.label} data available`);
        return;
    }

    const ctx = canvas.getContext('2d');
    ctdChartInstances[config.canvasId] = new Chart(ctx, {
        type: 'scatter',
        data: {
            datasets: [{
                label: config.label,
                data,
                backgroundColor: colors,
                borderColor: colors,
                pointRadius: 2.5,
                pointHoverRadius: 4,
                pointBorderWidth: 0,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            layout: {
                padding: { right: 72 },
            },
            scales: {
                x: {
                    type: 'time',
                    time: {
                        unit: 'hour',
                        tooltipFormat: 'MMM d, yyyy HH:mm',
                        displayFormats: { hour: 'MMM d HH:mm', day: 'MMM d' },
                    },
                    title: { display: true, text: 'Time', color: chartTextColor },
                    ticks: {
                        color: chartTextColor,
                        maxRotation: 0,
                        autoSkip: true,
                        autoSkipPadding: 20,
                    },
                    grid: { color: chartGridColor },
                },
                y: {
                    type: 'linear',
                    reverse: true,
                    title: { display: true, text: 'Depth (m)', color: chartTextColor },
                    ticks: { color: chartTextColor },
                    grid: { color: chartGridColor },
                },
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    mode: 'nearest',
                    intersect: true,
                    callbacks: {
                        title(items) {
                            const raw = items?.[0]?.raw;
                            if (!raw?.x) return '';
                            const d = raw.x instanceof Date ? raw.x : new Date(raw.x);
                            return Number.isNaN(d.getTime()) ? '' : d.toISOString().replace('T', ' ').replace(/\.\d{3}Z$/, ' UTC');
                        },
                        label(item) {
                            const raw = item.raw || {};
                            const depth = Number.isFinite(raw.y) ? raw.y.toFixed(1) : '-';
                            const value = Number.isFinite(raw.v) ? raw.v.toFixed(3) : '-';
                            return [`Depth: ${depth} m`, `${config.label}: ${value}${unit ? ` ${unit}` : ''}`];
                        },
                    },
                },
                slocumColorbar: {
                    stops,
                    min: range.min,
                    max: range.max,
                    unit,
                },
            },
        },
        plugins: [slocumColorbarPlugin],
    });
}

function applyThemeToCtdCharts() {
    updateChartColorVariables();
    Object.values(ctdChartInstances).forEach((chart) => {
        if (!chart) return;
        const x = chart.options.scales?.x;
        const y = chart.options.scales?.y;
        if (x) {
            if (x.title) x.title.color = chartTextColor;
            if (x.ticks) x.ticks.color = chartTextColor;
            if (x.grid) x.grid.color = chartGridColor;
        }
        if (y) {
            if (y.title) y.title.color = chartTextColor;
            if (y.ticks) y.ticks.color = chartTextColor;
            if (y.grid) y.grid.color = chartGridColor;
        }
        chart.update('none');
    });
}

function watchThemeForProfileCharts() {
    const observer = new MutationObserver((mutations) => {
        const themeChanged = mutations.some(
            (m) => m.type === 'attributes' && (m.attributeName === 'data-bs-theme' || m.attributeName === 'data-theme')
        );
        if (!themeChanged || !ctdProfilesLoaded) return;
        setTimeout(() => applyThemeToCtdCharts(), 50);
    });
    observer.observe(document.documentElement, {
        attributes: true,
        attributeFilter: ['data-bs-theme', 'data-theme'],
    });
}

function buildProfileDataUrl() {
    const datasetId = getDatasetId();
    if (!datasetId) return '';
    const params = new URLSearchParams();
    const dateRange = getSlocumDateRange();
    if (dateRange) {
        params.set('start_date', dateRange.startISO);
        params.set('end_date', dateRange.endISO);
    } else {
        params.set('hours_back', String(getHoursBack()));
    }
    if (isHistoricalDataset()) params.set('is_historical', 'true');
    return `/api/slocum/profile-data/${encodeURIComponent(datasetId)}?${params.toString()}`;
}

function setSlocumDataSourceBadge(cacheMetadata) {
    const badge = document.getElementById('slocumDataSourceBadge');
    if (!badge) return;
    const source = cacheMetadata?.data_source || '';
    const labels = {
        mirror: { text: 'Source: 72h mirror', cls: 'text-bg-success' },
        overage_cache: { text: 'Source: temporary cache', cls: 'text-bg-info' },
        erddap_overage: { text: 'Source: ERDDAP (on demand)', cls: 'text-bg-warning' },
    };
    const mapped = labels[source] || { text: 'Source: —', cls: 'text-bg-secondary' };
    badge.className = `badge ms-1 ${mapped.cls}`;
    badge.textContent = mapped.text;
    if (cacheMetadata?.cache_expires_at) {
        badge.title = `Expires: ${cacheMetadata.cache_expires_at}`;
    } else if (source === 'mirror') {
        badge.title = 'Loaded from the rolling local mirror.';
    } else {
        badge.title = 'Where the displayed data was loaded from.';
    }
}

async function refreshCtdProfileCharts() {
    const url = buildProfileDataUrl();
    if (!url) return;
    CTD_PROFILE_CHARTS.forEach((cfg) => showProfileSpinner(cfg.spinnerId));
    const badge = document.getElementById('slocumDataSourceBadge');
    if (badge) {
        badge.className = 'badge text-bg-secondary ms-1';
        badge.textContent = 'Source: loading…';
    }
    try {
        const payload = await apiRequest(url, 'GET');
        updateChartColorVariables();
        CTD_PROFILE_CHARTS.forEach((cfg) => renderOneProfileChart(cfg, payload));
        setSlocumDataSourceBadge(payload?.cache_metadata || {});
        const lastEl = document.getElementById('slocumLastDataTimestamp');
        const lastTs = payload?.cache_metadata?.last_data_timestamp;
        if (lastEl && lastTs) {
            lastEl.textContent = `Last data: ${formatUtcDateTime(lastTs)}`;
        }
    } catch (err) {
        console.error('Failed to load CTD profile data:', err);
        showToast(`CTD profile load failed: ${err.message || err}`, 'danger');
        destroyCtdCharts();
        CTD_PROFILE_CHARTS.forEach((cfg) => drawNoDataOnCanvas(cfg.canvasId, 'Failed to load profile data'));
        setSlocumDataSourceBadge({});
    } finally {
        CTD_PROFILE_CHARTS.forEach((cfg) => hideProfileSpinner(cfg.spinnerId));
    }
}

function loadCtdProfileCharts() {
    ctdProfilesLoaded = true;
    return refreshCtdProfileCharts();
}

function saveSlocumChartsAsPng(highResolution = false) {
    if (!ctdProfilesLoaded || activeChartCategory !== 'ctd') {
        showToast('Open the CTD tab first to download profile plots.', 'info');
        return;
    }
    const detailView = document.getElementById('detail-ctd');
    if (!detailView) return;
    const datasetId = getDatasetId() || 'slocum';
    const canvases = detailView.querySelectorAll('canvas');
    let count = 0;
    const bodyStyles = getComputedStyle(document.body);
    const bgColor = bodyStyles.getPropertyValue('--bs-body-bg').trim() || '#ffffff';
    const scaleFactor = highResolution ? 4 : 1;

    canvases.forEach((canvas) => {
        const chartInstance = ctdChartInstances[canvas.id];
        if (!chartInstance) return;
        const source = chartInstance.canvas;
        const out = document.createElement('canvas');
        out.width = source.width * scaleFactor;
        out.height = source.height * scaleFactor;
        const ctx = out.getContext('2d');
        ctx.imageSmoothingEnabled = true;
        ctx.imageSmoothingQuality = 'high';
        ctx.fillStyle = bgColor;
        ctx.fillRect(0, 0, out.width, out.height);
        if (scaleFactor !== 1) ctx.scale(scaleFactor, scaleFactor);
        ctx.drawImage(source, 0, 0);
        const link = document.createElement('a');
        link.href = out.toDataURL('image/png');
        const suffix = highResolution ? '_high_res' : '';
        link.download = `${datasetId}_${canvas.id}${suffix}.png`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        count += 1;
    });
    if (count === 0) showToast('No profile charts available to save.', 'info');
}

function setChartControlsVisible(isVisible) {
    const controls = document.getElementById('slocumChartControls');
    if (!controls) return;
    if (isVisible) {
        controls.style.removeProperty('display');
        controls.classList.add('d-flex');
    } else {
        controls.classList.remove('d-flex');
        controls.style.setProperty('display', 'none', 'important');
    }
}

function refreshLoadedChartTabs() {
    if (ctdProfilesLoaded) refreshCtdProfileCharts();
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
                const titles = {
                    overview: 'Overview',
                    ctd: 'CTD',
                    dissolved_oxygen: 'Dissolved Oxygen',
                };
                sectionTitleEl.textContent = titles[category] || 'Overview';
            }
            const isOverview = category === 'overview';
            setChartControlsVisible(!isOverview);
            // CTD profiles must keep full resolution; time-mean resample would destroy structure.
            setGranularityControlEnabled(!isOverview && category !== 'ctd');
            activeChartCategory = isOverview ? null : category;
            if (category === 'ctd') loadCtdProfileCharts();
        });
    });
}

async function pollSlocumCacheStatus() {
    const datasetId = getDatasetId();
    if (!datasetId || !autoRefreshEnabled || isHistoricalDataset()) return;
    try {
        const status = await apiRequest(`/api/slocum/cache-status/${encodeURIComponent(datasetId)}`, 'GET');
        let cacheUpdated = false;
        for (const [bundle, bundleStatus] of Object.entries(status || {})) {
            const stored = slocumCacheTimestamps.get(bundle);
            const serverLast = bundleStatus?.last_data_timestamp;
            const storedLast = stored?.last_data_timestamp;
            if (storedLast && serverLast && new Date(serverLast) > new Date(storedLast)) {
                cacheUpdated = true;
            } else if (!storedLast && serverLast) {
                slocumCacheTimestamps.set(bundle, {
                    cache_timestamp: bundleStatus.cache_timestamp,
                    last_data_timestamp: serverLast,
                });
            }
            if (bundleStatus?.cache_timestamp) {
                slocumCacheTimestamps.set(bundle, {
                    cache_timestamp: bundleStatus.cache_timestamp,
                    last_data_timestamp: serverLast,
                });
            }
        }
        if (cacheUpdated) {
            refreshAllLoadedChartsQuiet();
        }
    } catch (err) {
        console.debug('Slocum cache status poll failed:', err);
    }
}

function refreshAllLoadedChartsQuiet() {
    refreshLoadedChartTabs();
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
            pollSlocumCacheStatus();
            remainingSeconds = AUTO_REFRESH_INTERVAL_MINUTES * 60;
            countdownTimer = setInterval(updateCountdownDisplay, 1000);
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
        if (cachePollIntervalId) clearInterval(cachePollIntervalId);
        cachePollIntervalId = setInterval(pollSlocumCacheStatus, AUTO_REFRESH_POLL_INTERVAL_MS);
        pollSlocumCacheStatus();
    } else {
        if (cachePollIntervalId) {
            clearInterval(cachePollIntervalId);
            cachePollIntervalId = null;
        }
        if (countdownTimer) {
            clearInterval(countdownTimer);
            countdownTimer = null;
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


// --- Overview briefing (plan / reports / ST / comments / goals / media) ---

function mediaFileUrl(media) {
    if (!media) return '';
    if (media.file_url) return media.file_url;
    const path = media.file_path || '';
    if (!path) return '';
    return path.startsWith('/') ? path : `/static/${path}`;
}

function setDeploymentActionsEnabled(isEnabled) {
    const addMediaBtn = document.getElementById('slocumAddMediaBtn');
    const noteComposer = document.querySelector('#slocumNoteComposerCard .new-mission-note-content');
    const addNoteBtn = document.querySelector('#slocumNoteComposerCard .add-mission-note-btn');
    const addGoalBtn = document.querySelector('.add-goal-btn');
    if (addMediaBtn) addMediaBtn.disabled = !isEnabled;
    if (noteComposer) noteComposer.disabled = !isEnabled;
    if (addNoteBtn) addNoteBtn.disabled = !isEnabled;
    if (addGoalBtn) addGoalBtn.disabled = !isEnabled;
}

function renderMediaEmpty(message) {
    const gallery = document.getElementById('slocumMediaGallery');
    if (!gallery) return;
    gallery.innerHTML = `<div class="text-muted small">${escapeHtml(message)}</div>`;
}

function renderMediaCard(media) {
    const col = document.createElement('div');
    col.className = 'col-md-4 mission-media-item';
    col.dataset.mediaId = media.id;
    const caption = media.caption ? escapeHtml(media.caption) : '';
    const operation = media.operation_type ? escapeHtml(media.operation_type) : 'Unspecified';
    const uploadedBy = escapeHtml(media.uploaded_by_username || 'Unknown');
    const url = mediaFileUrl(media);
    const isVideo = media.media_type === 'video';
    const mediaPreview = isVideo
        ? `<video class="card-img-top" controls preload="metadata" style="height: 150px; object-fit: cover;">
                <source src="${url}">
           </video>`
        : `<a href="${url}" target="_blank" rel="noopener noreferrer">
                <img src="${url}" class="card-img-top" alt="${caption || 'Mission media'}" style="height: 150px; object-fit: cover;">
           </a>`;
    col.innerHTML = `
        <div class="card h-100">
            ${mediaPreview}
            <div class="card-body p-2">
                <div class="small text-muted mb-1">${operation.charAt(0).toUpperCase() + operation.slice(1)} • ${uploadedBy}</div>
                ${caption ? `<div class="small">${caption}</div>` : ''}
            </div>
        </div>
    `;
    return col;
}

function renderMissionNotes(notes) {
    const list = document.getElementById('dashboardMissionNotesList');
    if (!list) return;
    const notesContainer = list.closest('.mission-notes-container');
    const existingHistory = notesContainer ? notesContainer.querySelector('.older-mission-notes-wrapper') : null;
    if (existingHistory) existingHistory.remove();

    if (!currentDeploymentId) {
        lastMissionNotesForEdit = [];
        list.innerHTML = '<li class="list-group-item text-muted no-mission-notes-placeholder">Unable to load comments for this dataset.</li>';
        return;
    }
    if (!notes || notes.length === 0) {
        lastMissionNotesForEdit = [];
        list.innerHTML = '<li class="list-group-item text-muted no-mission-notes-placeholder">No mission comments have been added.</li>';
        return;
    }

    const sortedNotes = [...notes].sort((a, b) => {
        const ta = Date.parse(a.created_at_utc || '');
        const tb = Date.parse(b.created_at_utc || '');
        if (Number.isNaN(ta) && Number.isNaN(tb)) return 0;
        if (Number.isNaN(ta)) return 1;
        if (Number.isNaN(tb)) return -1;
        return tb - ta;
    });
    const recentNotes = sortedNotes.slice(0, DASHBOARD_RECENT_NOTE_LIMIT);
    const olderNotes = sortedNotes.slice(DASHBOARD_RECENT_NOTE_LIMIT);
    lastMissionNotesForEdit = sortedNotes;

    const noteMarkup = (note) => {
        const canEdit = USER_ROLE === 'admin' || (USERNAME && note.created_by_username === USERNAME);
        return `
            <li class="list-group-item d-flex justify-content-between align-items-start" data-note-id="${note.id}">
                <div>
                    <p class="mb-1">${escapeHtml(note.content)}</p>
                    <small class="text-muted">
                        &mdash; ${escapeHtml(note.created_by_username || 'Unknown')} on ${formatTimestamp(note.created_at_utc)}
                    </small>
                </div>
                ${canEdit ? `
                    <div class="d-flex flex-shrink-0 gap-1 ms-2">
                        <button type="button" class="btn btn-sm btn-outline-secondary edit-note-btn" title="Edit comment" data-note-id="${note.id}">
                            <i class="fas fa-pencil-alt"></i>
                        </button>
                        <button type="button" class="btn btn-sm btn-outline-danger delete-note-btn" title="Delete Note" data-note-id="${note.id}">
                            <i class="fas fa-trash-alt"></i>
                        </button>
                    </div>
                ` : ''}
            </li>
        `;
    };

    list.innerHTML = recentNotes.map(noteMarkup).join('');
    if (!notesContainer || olderNotes.length === 0) return;

    const historyWrapper = document.createElement('div');
    historyWrapper.className = 'older-mission-notes-wrapper mt-2';
    historyWrapper.innerHTML = `
        <button type="button" class="btn btn-sm btn-outline-secondary toggle-older-notes-btn">
            Show older comments (${olderNotes.length})
        </button>
        <ul class="list-group older-mission-notes-list d-none mt-2">
            ${olderNotes.map(noteMarkup).join('')}
        </ul>
    `;
    const toggleButton = historyWrapper.querySelector('.toggle-older-notes-btn');
    const olderList = historyWrapper.querySelector('.older-mission-notes-list');
    toggleButton.addEventListener('click', () => {
        const isHidden = olderList.classList.toggle('d-none');
        toggleButton.textContent = isHidden
            ? `Show older comments (${olderNotes.length})`
            : `Hide older comments (${olderNotes.length})`;
    });
    const noteComposerCard = notesContainer.querySelector('.card.mt-3');
    notesContainer.insertBefore(historyWrapper, noteComposerCard || null);
}

function renderMissionGoals(goals) {
    const list = document.getElementById('dashboardMissionGoalsList');
    if (!list) return;
    if (!currentDeploymentId) {
        list.innerHTML = '<li class="list-group-item text-muted no-mission-goals-placeholder">Unable to load goals for this dataset.</li>';
        return;
    }
    if (!goals || goals.length === 0) {
        list.innerHTML = '<li class="list-group-item text-muted no-mission-goals-placeholder">No mission goals have been defined.</li>';
        return;
    }
    list.innerHTML = goals.map((goal) => {
        const adminControls = USER_ROLE === 'admin'
            ? `
                <button class="btn btn-sm btn-link p-0 ms-2 edit-goal-btn" title="Edit Goal" data-goal-id="${goal.id}" data-description="${escapeHtml(goal.description)}">
                    <i class="fas fa-pencil-alt"></i>
                </button>
                <button class="btn btn-sm btn-link p-0 ms-2 text-danger delete-goal-btn" title="Delete Goal" data-goal-id="${goal.id}">
                    <i class="fas fa-trash-alt"></i>
                </button>
            `
            : '';
        const completedBadge = goal.is_completed
            ? `<span class="badge bg-success rounded-pill small ms-2" title="Completed at ${formatTimestamp(goal.completed_at_utc)}">
                    By: ${escapeHtml(goal.completed_by_username || '')}
               </span>`
            : '';
        return `
            <li class="list-group-item d-flex justify-content-between align-items-start" data-goal-id="${goal.id}">
                <div class="form-check flex-grow-1">
                    <input class="form-check-input mission-goal-checkbox" type="checkbox" id="goal-${goal.id}" data-goal-id="${goal.id}" ${goal.is_completed ? 'checked' : ''}>
                    <label class="form-check-label ${goal.is_completed ? 'text-decoration-line-through text-muted' : ''}" for="goal-${goal.id}">
                        ${escapeHtml(goal.description)}
                    </label>
                    ${adminControls}
                </div>
                ${completedBadge}
            </li>
        `;
    }).join('');
}

function renderSlocumMedia(mediaItems) {
    const gallery = document.getElementById('slocumMediaGallery');
    if (!gallery) return;
    if (!currentDeploymentId) {
        renderMediaEmpty('Unable to load media for this dataset.');
        return;
    }
    if (!mediaItems || mediaItems.length === 0) {
        renderMediaEmpty('No media uploaded for this deployment yet.');
        return;
    }
    gallery.innerHTML = '';
    mediaItems.forEach((media) => gallery.appendChild(renderMediaCard(media)));
}

function renderPlanDocument(documentUrl) {
    const container = document.getElementById('overviewPlanContainer');
    const link = document.getElementById('overviewPlanLink');
    const empty = document.getElementById('overviewPlanEmpty');
    if (documentUrl && container && link && empty) {
        link.href = documentUrl;
        link.textContent = documentUrl.split('/').pop();
        container.style.display = 'block';
        empty.style.display = 'none';
    } else if (empty && container) {
        container.style.display = 'none';
        empty.style.display = 'block';
    }
}

function renderSensorTrackerOverview(deployment, instruments) {
    const container = document.getElementById('overviewSensorTrackerContainer');
    const empty = document.getElementById('overviewSensorTrackerEmpty');
    if (deployment && container && empty) {
        container.style.display = 'block';
        empty.style.display = 'none';
        const setText = (id, value) => {
            const el = document.getElementById(id);
            if (el) el.textContent = value || '-';
        };
        setText('overviewStTitle', deployment.title);
        setText('overviewStStart', deployment.start_time ? formatUtcDateTime(deployment.start_time) : '-');
        setText('overviewStEnd', deployment.end_time ? formatUtcDateTime(deployment.end_time) : '-');
        setText('overviewStPlatform', deployment.platform_name);
        const repo = document.getElementById('overviewStDataRepo');
        if (repo) {
            if (deployment.data_repository_link) {
                repo.innerHTML = '';
                const a = document.createElement('a');
                a.href = deployment.data_repository_link;
                a.target = '_blank';
                a.rel = 'noopener noreferrer';
                a.textContent = deployment.data_repository_link;
                repo.appendChild(a);
            } else {
                repo.textContent = '-';
            }
        }
        setText('overviewStDescription', deployment.deployment_comment || '-');
        const instrumentsWrap = document.getElementById('overviewStInstruments');
        const instrumentsList = document.getElementById('overviewStInstrumentsList');
        if (instrumentsWrap && instrumentsList) {
            instrumentsList.innerHTML = '';
            if (instruments && instruments.length) {
                instruments.forEach((inst) => {
                    const li = document.createElement('li');
                    const name = inst.instrument_name || inst.instrument_identifier || 'Instrument';
                    const serial = inst.instrument_serial ? ` (${inst.instrument_serial})` : '';
                    li.textContent = `${name}${serial}`;
                    instrumentsList.appendChild(li);
                });
                instrumentsWrap.style.display = 'block';
            } else {
                instrumentsWrap.style.display = 'none';
            }
        }
    } else if (container && empty) {
        container.style.display = 'none';
        empty.style.display = 'block';
    }
}

async function loadSlocumReports() {
    const datasetId = getDatasetId();
    const weeklyContainer = document.getElementById('overviewWeeklyReportContainer');
    const weeklyLink = document.getElementById('overviewWeeklyReportLink');
    const weeklyList = document.getElementById('overviewWeeklyReportList');
    const noReports = document.getElementById('overviewNoReports');
    if (!datasetId) return;
    try {
        const payload = await apiRequest(`/api/slocum/reporting/datasets/${encodeURIComponent(datasetId)}/reports`, 'GET');
        const reports = payload?.reports || [];
        if (!reports.length) {
            if (weeklyContainer) weeklyContainer.style.display = 'none';
            if (weeklyList) weeklyList.style.display = 'none';
            if (noReports) noReports.style.display = 'block';
            return;
        }
        if (noReports) noReports.style.display = 'none';
        const latest = reports[0];
        if (weeklyContainer && weeklyLink) {
            weeklyLink.href = latest.url;
            weeklyLink.textContent = latest.filename;
            weeklyContainer.style.display = 'block';
        }
        if (weeklyList && reports.length > 1) {
            weeklyList.innerHTML = '<div class="mt-1"><strong>All reports:</strong></div><ul class="mb-0">'
                + reports.map((r) => `<li><a href="${escapeHtml(r.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(r.filename)}</a></li>`).join('')
                + '</ul>';
            weeklyList.style.display = 'block';
        } else if (weeklyList) {
            weeklyList.style.display = 'none';
        }
    } catch (error) {
        if (weeklyContainer) weeklyContainer.style.display = 'none';
        if (weeklyList) weeklyList.style.display = 'none';
        if (noReports) {
            noReports.style.display = 'block';
            noReports.textContent = `Failed to load reports: ${error.message}`;
        }
    }
}

async function loadSlocumOverview() {
    const datasetId = getDatasetId();
    if (!datasetId) return;
    try {
        const info = await apiRequest(`/api/slocum/datasets/${encodeURIComponent(datasetId)}/info`, 'GET');
        currentOverviewInfo = info;
        currentDeploymentId = info?.deployment?.id || null;
        setDeploymentActionsEnabled(Boolean(currentDeploymentId));
        renderPlanDocument(info?.deployment?.document_url || null);
        renderSensorTrackerOverview(info?.sensor_tracker_deployment || null, info?.sensor_tracker_instruments || []);
        renderMissionNotes(info?.notes || []);
        renderMissionGoals(info?.goals || []);
        renderSlocumMedia(info?.media || []);
        if (!currentDeploymentId) {
            showToast('Unable to create deployment metadata for this dataset id.', 'warning');
        }
    } catch (error) {
        console.error('Failed to load Slocum overview:', error);
        showToast(`Failed to load overview: ${error.message}`, 'danger');
        renderMediaEmpty(`Failed to load media: ${error.message}`);
    }
}

function bindSlocumOverviewInteractions() {
    const goalModalElement = document.getElementById('goalModal');
    const goalModal = goalModalElement ? new bootstrap.Modal(goalModalElement) : null;
    const goalModalLabel = document.getElementById('goalModalLabel');
    const goalForm = document.getElementById('goalForm');
    const goalIdInput = document.getElementById('goalIdInput');
    const goalDescriptionInput = document.getElementById('goalDescriptionInput');
    const saveGoalBtn = document.getElementById('saveGoalBtn');

    const missionNoteModalElement = document.getElementById('missionNoteModal');
    const missionNoteModal = missionNoteModalElement ? new bootstrap.Modal(missionNoteModalElement) : null;
    const missionNoteModalLabel = document.getElementById('missionNoteModalLabel');
    const missionNoteIdInput = document.getElementById('missionNoteIdInput');
    const missionNoteContentInput = document.getElementById('missionNoteContentInput');
    const missionNoteIncludeReport = document.getElementById('missionNoteIncludeReport');
    const saveMissionNoteBtn = document.getElementById('saveMissionNoteBtn');

    const mediaForm = document.getElementById('slocumMediaUploadForm');
    if (mediaForm) {
        mediaForm.addEventListener('submit', async (event) => {
            event.preventDefault();
            if (!currentDeploymentId) {
                showToast('Deployment metadata unavailable for this dataset.', 'warning');
                return;
            }
            const fileInput = document.getElementById('slocumMediaFile');
            const fileToUpload = fileInput ? fileInput.files[0] : null;
            if (!fileToUpload) {
                showToast('Please select a media file to upload.', 'warning');
                return;
            }
            const uploadBtn = document.getElementById('slocumMediaUploadBtn');
            const spinner = document.getElementById('slocumMediaUploadSpinner');
            if (uploadBtn) uploadBtn.disabled = true;
            if (spinner) spinner.style.display = 'inline';
            const formData = new FormData();
            formData.append('file', fileToUpload);
            const caption = document.getElementById('slocumMediaCaption')?.value?.trim();
            const params = new URLSearchParams();
            if (caption) params.append('caption', caption);
            const query = params.toString();
            const uploadUrl = `/api/slocum/deployments/${currentDeploymentId}/media/upload${query ? `?${query}` : ''}`;
            try {
                const response = await fetchWithAuth(uploadUrl, { method: 'POST', body: formData });
                if (!response.ok) {
                    const err = await response.json().catch(() => ({}));
                    throw new Error(err.detail || 'Media upload failed.');
                }
                showToast('Media uploaded successfully!', 'success');
                if (fileInput) fileInput.value = '';
                const captionEl = document.getElementById('slocumMediaCaption');
                if (captionEl) captionEl.value = '';
                const operationEl = document.getElementById('slocumMediaOperation');
                if (operationEl) operationEl.value = '';
                await loadSlocumOverview();
            } catch (error) {
                showToast(`Upload failed: ${error.message}`, 'danger');
            } finally {
                if (uploadBtn) uploadBtn.disabled = false;
                if (spinner) spinner.style.display = 'none';
            }
        });
    }

    document.body.addEventListener('click', async (event) => {
        const addNoteBtn = event.target.closest('.add-mission-note-btn');
        if (addNoteBtn) {
            event.preventDefault();
            if (!currentDeploymentId) return;
            const textarea = document.querySelector('.new-mission-note-content');
            const content = textarea ? textarea.value.trim() : '';
            if (!content) {
                showToast('Comment cannot be empty.', 'danger');
                return;
            }
            try {
                await apiRequest(`/api/slocum/deployments/${currentDeploymentId}/notes`, 'POST', { content });
                showToast('Comment added successfully.', 'success');
                if (textarea) textarea.value = '';
                await loadSlocumOverview();
            } catch (error) {
                showToast(`Failed to add comment: ${error.message}`, 'danger');
            }
            return;
        }

        const editNoteBtn = event.target.closest('.edit-note-btn');
        if (editNoteBtn) {
            event.preventDefault();
            if (!missionNoteModal) return;
            const noteId = editNoteBtn.dataset.noteId;
            const note = lastMissionNotesForEdit.find((n) => String(n.id) === String(noteId));
            if (!note) {
                showToast('Could not load that comment. Refresh and try again.', 'warning');
                return;
            }
            if (missionNoteModalLabel) missionNoteModalLabel.textContent = 'Edit mission comment';
            if (missionNoteIdInput) missionNoteIdInput.value = noteId;
            if (missionNoteContentInput) missionNoteContentInput.value = note.content || '';
            if (missionNoteIncludeReport) missionNoteIncludeReport.checked = Boolean(note.include_in_report);
            missionNoteModal.show();
            return;
        }

        const deleteNoteBtn = event.target.closest('.delete-note-btn');
        if (deleteNoteBtn) {
            event.preventDefault();
            const noteId = deleteNoteBtn.dataset.noteId;
            if (!noteId || !confirm('Delete this comment?')) return;
            try {
                await apiRequest(`/api/slocum/deployments/notes/${noteId}`, 'DELETE');
                showToast('Comment deleted.', 'success');
                await loadSlocumOverview();
            } catch (error) {
                showToast(`Failed to delete comment: ${error.message}`, 'danger');
            }
            return;
        }

        const addGoalBtn = event.target.closest('.add-goal-btn');
        if (addGoalBtn) {
            event.preventDefault();
            if (USER_ROLE !== 'admin' || !goalModal || !currentDeploymentId) return;
            if (goalForm) goalForm.reset();
            if (goalIdInput) goalIdInput.value = '';
            if (goalModalLabel) goalModalLabel.textContent = 'Add Mission Goal';
            goalModal.show();
            return;
        }

        const editGoalBtn = event.target.closest('.edit-goal-btn');
        if (editGoalBtn) {
            event.preventDefault();
            if (USER_ROLE !== 'admin' || !goalModal) return;
            if (goalForm) goalForm.reset();
            if (goalIdInput) goalIdInput.value = editGoalBtn.dataset.goalId || '';
            if (goalDescriptionInput) goalDescriptionInput.value = editGoalBtn.dataset.description || '';
            if (goalModalLabel) goalModalLabel.textContent = 'Edit Mission Goal';
            goalModal.show();
            return;
        }

        const deleteGoalBtn = event.target.closest('.delete-goal-btn');
        if (deleteGoalBtn) {
            event.preventDefault();
            if (USER_ROLE !== 'admin') return;
            const goalId = deleteGoalBtn.dataset.goalId;
            if (!goalId || !confirm('Delete this goal?')) return;
            try {
                await apiRequest(`/api/slocum/deployments/goals/${goalId}`, 'DELETE');
                showToast('Goal deleted.', 'success');
                await loadSlocumOverview();
            } catch (error) {
                showToast(`Failed to delete goal: ${error.message}`, 'danger');
            }
        }
    });

    document.body.addEventListener('change', async (event) => {
        const goalCheckbox = event.target.closest('.mission-goal-checkbox');
        if (!goalCheckbox || !currentDeploymentId) return;
        const goalId = goalCheckbox.dataset.goalId;
        const isCompleted = goalCheckbox.checked;
        try {
            await apiRequest(
                `/api/slocum/deployments/${currentDeploymentId}/goals/${goalId}/toggle`,
                'POST',
                { is_completed: isCompleted }
            );
            await loadSlocumOverview();
        } catch (error) {
            goalCheckbox.checked = !isCompleted;
            showToast(`Failed to update goal: ${error.message}`, 'danger');
        }
    });

    if (saveGoalBtn) {
        saveGoalBtn.addEventListener('click', async () => {
            if (USER_ROLE !== 'admin' || !currentDeploymentId) return;
            const goalId = goalIdInput?.value;
            const description = goalDescriptionInput?.value.trim() || '';
            if (!description) {
                showToast('Goal description cannot be empty.', 'danger');
                return;
            }
            try {
                if (goalId) {
                    await apiRequest(`/api/slocum/deployments/goals/${goalId}`, 'PUT', { description });
                } else {
                    await apiRequest(`/api/slocum/deployments/${currentDeploymentId}/goals`, 'POST', { description });
                }
                if (goalModal) goalModal.hide();
                await loadSlocumOverview();
            } catch (error) {
                showToast(`Failed to save goal: ${error.message}`, 'danger');
            }
        });
    }

    if (saveMissionNoteBtn && missionNoteModal) {
        saveMissionNoteBtn.addEventListener('click', async () => {
            const id = missionNoteIdInput?.value;
            const content = missionNoteContentInput?.value.trim() || '';
            if (!id || !content) {
                showToast('Comment cannot be empty.', 'danger');
                return;
            }
            const payload = {
                content,
                include_in_report: Boolean(missionNoteIncludeReport?.checked),
            };
            try {
                await apiRequest(`/api/slocum/deployments/notes/${id}`, 'PUT', payload);
                missionNoteModal.hide();
                showToast('Comment updated.', 'success');
                await loadSlocumOverview();
            } catch (error) {
                showToast(`Failed to update comment: ${error.message}`, 'danger');
            }
        });
    }
}

function bindSlocumChecklistTab() {
    const datasetId = getDatasetId();
    const newLink = document.getElementById('slocumNewChecklistLink');
    if (newLink && datasetId) {
        newLink.href = `/slocum/dataset/${encodeURIComponent(datasetId)}/checklist.html`;
    }

    const checklistTab = document.getElementById('slocum-checklist-tab');
    if (checklistTab) {
        checklistTab.addEventListener('shown.bs.tab', () => {
            loadSlocumChecklists();
        });
    }
    const refreshBtn = document.getElementById('slocumChecklistsRefreshBtn');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', () => loadSlocumChecklists());
    }
}

function displaySlocumChecklistDetails(form) {
    const content = document.getElementById('slocumChecklistsFormDetailsContent');
    const title = document.getElementById('slocumChecklistsFormDetailsModalLabel');
    if (!content) return;
    if (title) {
        title.textContent = form.form_title || 'Daily Checklist';
    }
    const parts = [];
    parts.push(`<p class="small text-muted mb-3">Submitted by <strong>${escapeHtml(form.submitted_by_username || 'Unknown')}</strong> at ${escapeHtml(formatTimestamp(form.submission_timestamp))}</p>`);
    if (form.edited_by_username) {
        parts.push(`<p class="small text-muted">Last edited by ${escapeHtml(form.edited_by_username)} at ${escapeHtml(formatTimestamp(form.last_edited_timestamp))}</p>`);
    }
    (form.sections_data || []).forEach((section) => {
        parts.push(`<h6 class="mt-3">${escapeHtml(section.title || section.id)}</h6>`);
        parts.push('<dl class="row small mb-0">');
        (section.items || []).forEach((item) => {
            const verified = item.is_verified === true ? ' <span class="badge bg-success">Verified</span>' : '';
            const comment = item.comment ? `<div class="text-muted">Comment: ${escapeHtml(item.comment)}</div>` : '';
            parts.push(`
                <dt class="col-sm-4">${escapeHtml(item.label || item.id)}${verified}</dt>
                <dd class="col-sm-8">${escapeHtml(item.value != null ? String(item.value) : '—')}${comment}</dd>
            `);
        });
        parts.push('</dl>');
        if (section.section_comment) {
            parts.push(`<p class="small text-muted">Section notes: ${escapeHtml(section.section_comment)}</p>`);
        }
    });
    content.innerHTML = parts.join('');
    const modalEl = document.getElementById('slocumChecklistsFormDetailsModal');
    if (modalEl && window.bootstrap) {
        new bootstrap.Modal(modalEl).show();
    }
}

function renderSlocumChecklists(forms) {
    const latestEl = document.getElementById('slocumChecklistsLatest');
    const tableBody = document.getElementById('slocumChecklistsTableBody');
    const emptyEl = document.getElementById('slocumChecklistsEmpty');
    if (!latestEl || !tableBody) return;

    const hasForms = Array.isArray(forms) && forms.length > 0;
    if (!hasForms) {
        latestEl.innerHTML = '<div class="text-muted small">No daily checklist submissions exist for this dataset.</div>';
        tableBody.innerHTML = '<tr><td colspan="4" class="text-muted small">No daily checklist submissions exist for this dataset.</td></tr>';
        if (emptyEl) emptyEl.style.display = 'block';
        return;
    }
    if (emptyEl) emptyEl.style.display = 'none';

    const latest = forms[0];
    const datasetId = getDatasetId();
    latestEl.innerHTML = `
        <div class="d-flex justify-content-between align-items-start flex-wrap gap-2">
            <div>
                <div class="fw-bold">${escapeHtml(latest.form_title || 'Slocum Daily Pilot Checklist')}</div>
                <div class="text-muted small">
                    ${escapeHtml(formatTimestamp(latest.submission_timestamp))} • ${escapeHtml(latest.submitted_by_username || 'Unknown')}
                </div>
            </div>
            <div class="d-flex gap-2">
                <button type="button" class="btn btn-sm btn-info" id="slocumChecklistsViewLatestBtn">View Details</button>
                ${(USER_ROLE === 'admin' || (USERNAME && latest.submitted_by_username === USERNAME))
                    ? `<a class="btn btn-sm btn-outline-secondary" href="/slocum/dataset/${encodeURIComponent(datasetId)}/checklist.html?edit=${latest.id}" target="_blank" rel="noopener noreferrer">Edit</a>`
                    : ''}
            </div>
        </div>
    `;
    const viewLatestBtn = document.getElementById('slocumChecklistsViewLatestBtn');
    if (viewLatestBtn) {
        viewLatestBtn.addEventListener('click', () => displaySlocumChecklistDetails(latest));
    }

    tableBody.innerHTML = '';
    forms.forEach((form) => {
        const row = tableBody.insertRow();
        row.insertCell().textContent = form.form_title || '';
        row.insertCell().textContent = formatTimestamp(form.submission_timestamp);
        row.insertCell().textContent = form.submitted_by_username || '';
        const actionsCell = row.insertCell();
        const viewBtn = document.createElement('button');
        viewBtn.type = 'button';
        viewBtn.className = 'btn btn-sm btn-outline-info me-1';
        viewBtn.textContent = 'View';
        viewBtn.addEventListener('click', () => displaySlocumChecklistDetails(form));
        actionsCell.appendChild(viewBtn);
        if (USER_ROLE === 'admin' || (USERNAME && form.submitted_by_username === USERNAME)) {
            const editLink = document.createElement('a');
            editLink.className = 'btn btn-sm btn-outline-secondary';
            editLink.textContent = 'Edit';
            editLink.target = '_blank';
            editLink.rel = 'noopener noreferrer';
            editLink.href = `/slocum/dataset/${encodeURIComponent(datasetId)}/checklist.html?edit=${form.id}`;
            actionsCell.appendChild(editLink);
        }
    });
}

async function loadSlocumChecklists() {
    const datasetId = getDatasetId();
    const spinner = document.getElementById('slocumChecklistsSpinner');
    const latestEl = document.getElementById('slocumChecklistsLatest');
    const tableBody = document.getElementById('slocumChecklistsTableBody');
    if (!datasetId) {
        if (latestEl) latestEl.innerHTML = '<div class="text-muted small">No dataset selected.</div>';
        return;
    }
    if (spinner) spinner.style.display = 'block';
    try {
        const forms = await apiRequest(`/api/slocum/checklists/${encodeURIComponent(datasetId)}`, 'GET');
        renderSlocumChecklists(forms);
    } catch (error) {
        if (latestEl) {
            latestEl.innerHTML = `<div class="text-danger small">Failed to load checklists: ${escapeHtml(error.message)}</div>`;
        }
        if (tableBody) {
            tableBody.innerHTML = `<tr><td colspan="4" class="text-danger small">Failed to load checklists: ${escapeHtml(error.message)}</td></tr>`;
        }
    } finally {
        if (spinner) spinner.style.display = 'none';
    }
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

    setChartControlsVisible(false);
    setGranularityControlEnabled(true);
    updateChartColorVariables();
    loadSlocumOverview();
    loadSlocumReports();
    bindSlocumOverviewInteractions();
    bindSlocumChecklistTab();
    watchThemeForProfileCharts();

    const hoursSelect = document.getElementById('slocumHoursBack');
    function refreshAllLoadedCharts() {
        refreshLoadedChartTabs();
    }

    if (hoursSelect) {
        hoursSelect.addEventListener('change', refreshAllLoadedCharts);
    }

    const granularitySelect = document.getElementById('slocumGranularity');
    if (granularitySelect) {
        // Resample only applies to non-profile chart tabs (future); ignore while on CTD.
        granularitySelect.addEventListener('change', () => {
            if (activeChartCategory && activeChartCategory !== 'ctd') {
                refreshAllLoadedCharts();
            }
        });
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
