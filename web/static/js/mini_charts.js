/**
 * Shared left-nav summary-card mini-trend sparklines (Wave Glider + Slocum).
 * Expects Chart.js + chartjs-adapter-date-fns on the page.
 */
const MINI_CHART_COLORS = {
    POWER_SOLAR: 'rgba(255, 159, 64, 1)',
    CTD_TEMP: 'rgba(0, 191, 255, 1)',
    WEATHER_WIND_SPEED: 'rgba(60, 179, 113, 1)',
    WAVES_SIG_HEIGHT: 'rgba(255, 206, 86, 1)',
    VR2C_DETECTION: 'rgba(75, 192, 192, 1)',
    FLUORO_C_AVG_PRIMARY: 'rgba(75, 192, 192, 1)',
    NAV_SPEED: 'rgba(138, 43, 226, 1)',
    WG_VM4_CH0_DETECTION: 'rgba(255, 159, 64, 1)',
};

const miniChartInstances = {};

function getDefaultMiniChartLineColor() {
    try {
        return getComputedStyle(document.documentElement)
            .getPropertyValue('--active-card-accent')
            .trim() || 'rgba(13, 110, 253, 1)';
    } catch (_) {
        return 'rgba(13, 110, 253, 1)';
    }
}

function colorForCategory(category, fallbackColor) {
    switch (category) {
        case 'power':
            return MINI_CHART_COLORS.POWER_SOLAR;
        case 'ctd':
            return MINI_CHART_COLORS.CTD_TEMP;
        case 'weather':
            return MINI_CHART_COLORS.WEATHER_WIND_SPEED;
        case 'waves':
            return MINI_CHART_COLORS.WAVES_SIG_HEIGHT;
        case 'vr2c':
            return MINI_CHART_COLORS.VR2C_DETECTION;
        case 'fluorometer':
            return MINI_CHART_COLORS.FLUORO_C_AVG_PRIMARY;
        case 'navigation':
            return MINI_CHART_COLORS.NAV_SPEED;
        case 'wg_vm4':
            return MINI_CHART_COLORS.WG_VM4_CH0_DETECTION;
        default:
            return fallbackColor;
    }
}

function miniChartCanvasIdForCategory(category) {
    if (category === 'waves') return 'miniWaveChart';
    return `mini${category.charAt(0).toUpperCase()}${category.slice(1)}Chart`;
}

/**
 * Render a sparkline on the given canvas.
 * @param {string} canvasId
 * @param {Array<{Timestamp: string, value: number}>} trendData
 * @param {string} [chartColor]
 */
export function renderMiniChart(canvasId, trendData, chartColor = getDefaultMiniChartLineColor()) {
    if (typeof Chart === 'undefined') return;
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    if (miniChartInstances[canvasId]) {
        miniChartInstances[canvasId].destroy();
        delete miniChartInstances[canvasId];
    }

    if (!trendData || trendData.length === 0) return;

    const dataPoints = trendData.map((item) => ({
        x: new Date(item.Timestamp),
        y: item.value,
    }));

    let yMin = Infinity;
    let yMax = -Infinity;
    dataPoints.forEach((point) => {
        if (point.y < yMin) yMin = point.y;
        if (point.y > yMax) yMax = point.y;
    });

    let yAxisMin;
    let yAxisMax;
    const range = yMax - yMin;
    if (range === 0) {
        yAxisMin = yMin - 1;
        yAxisMax = yMax + 1;
    } else {
        const padding = range * 0.10;
        yAxisMin = yMin - padding;
        yAxisMax = yMax + padding;
    }

    miniChartInstances[canvasId] = new Chart(ctx, {
        type: 'line',
        data: {
            datasets: [{
                data: dataPoints,
                borderColor: chartColor,
                borderWidth: 1.5,
                pointRadius: 0,
                tension: 0.1,
                fill: false,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            scales: {
                x: {
                    type: 'time',
                    display: false,
                    grid: { display: false },
                },
                y: {
                    display: false,
                    min: yAxisMin,
                    max: yAxisMax,
                },
            },
            plugins: {
                legend: { display: false },
                tooltip: { enabled: false },
            },
            layout: {
                padding: { left: 1, right: 1, top: 3, bottom: 1 },
            },
        },
    });
}

/**
 * Initialize mini charts for all summary cards under rootSelector.
 * @param {string} [rootSelector='#left-nav-panel']
 */
export function initializeMiniCharts(rootSelector = '#left-nav-panel') {
    const defaultColor = getDefaultMiniChartLineColor();
    const root = document.querySelector(rootSelector) || document;
    const summaryCards = root.querySelectorAll('.summary-card');

    summaryCards.forEach((card) => {
        const category = card.dataset.category;
        if (!category) return;
        const canvasId = miniChartCanvasIdForCategory(category);
        const canvasElement = document.getElementById(canvasId);
        if (!canvasElement) return;

        const trendDataJson = card.dataset.miniTrend;
        if (!trendDataJson || trendDataJson.trim() === '') return;

        try {
            const trendData = JSON.parse(trendDataJson);
            if (trendData && trendData.length > 0) {
                renderMiniChart(canvasId, trendData, colorForCategory(category, defaultColor));
            }
        } catch (_) {
            // Ignore malformed embedded trend JSON
        }
    });
}

export { MINI_CHART_COLORS };
