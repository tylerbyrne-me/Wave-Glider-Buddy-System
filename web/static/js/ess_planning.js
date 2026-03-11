/**
 * ESS Waypoint Planner: diagram, position/wave controls, waypoint output, copy.
 */
(function () {
    const app = document.getElementById('essPlanningApp');
    if (!app) return;

    let missionId = app.dataset.missionId;
    let initialPosition = null;
    let initialWaveMeasured = null;
    let sourcePreference = (app.dataset.source || '').trim() || null;
    let localPath = (app.getAttribute('data-local-path') || '').trim() || null;
    const scriptData = document.getElementById('essInitialData');
    if (scriptData && scriptData.textContent) {
        try {
            const data = JSON.parse(scriptData.textContent.trim());
            if (data.mission_id) missionId = data.mission_id;
            if (data.initial_position && typeof data.initial_position === 'object') initialPosition = data.initial_position;
            if (data.initial_wave_measured && typeof data.initial_wave_measured === 'object') initialWaveMeasured = data.initial_wave_measured;
            if (data.source != null) sourcePreference = (data.source && String(data.source).trim()) || null;
            if (data.local_path != null) localPath = (data.local_path && String(data.local_path).trim()) || null;
        } catch (e) {}
    }

    const DEFAULT_SHORT_LEG_M = 210;
    const DEFAULT_LONG_LEG_M = 2000;

    let state = {
        lat: null,
        lon: null,
        useForecast: false,
        useCustomDir: false,
        customDir: null,
        measuredDir: null,
        measuredTs: null,
        forecastDir: null,
        forecastTs: null,
        waypoints: null
    };

    const canvas = document.getElementById('essDiagramCanvas');
    const outCurrent = document.getElementById('outCurrent');
    const outWp1 = document.getElementById('outWp1');
    const outWp2 = document.getElementById('outWp2');
    const outWp3 = document.getElementById('outWp3');
    const outWp4 = document.getElementById('outWp4');

    function getWaveDirectionDeg() {
        if (state.useCustomDir) {
            const el = document.getElementById('inputCustomWaveDir');
            if (el) {
                const n = parseFloat(el.value);
                if (!Number.isNaN(n) && n >= 0 && n <= 360) return n;
            }
            return state.customDir;
        }
        if (state.useForecast && state.forecastDir != null) return state.forecastDir;
        if (state.measuredDir != null) return state.measuredDir;
        return state.forecastDir; // fallback to forecast when no measured direction
    }

    function getShortLegM() {
        const el = document.getElementById('inputShortLegM');
        if (!el) return DEFAULT_SHORT_LEG_M;
        const n = parseFloat(el.value);
        return (!Number.isNaN(n) && n >= 1 && n <= 10000) ? n : DEFAULT_SHORT_LEG_M;
    }

    function getLongLegM() {
        const el = document.getElementById('inputLongLegM');
        if (!el) return DEFAULT_LONG_LEG_M;
        const n = parseFloat(el.value);
        return (!Number.isNaN(n) && n >= 1 && n <= 100000) ? n : DEFAULT_LONG_LEG_M;
    }

    function apiRequest(url, method, body) {
        const opts = { method: method || 'GET', headers: { 'Content-Type': 'application/json' } };
        if (body) opts.body = JSON.stringify(body);
        return fetch(url, opts).then(r => { if (!r.ok) throw new Error(r.statusText); return r.json(); });
    }

    function fetchWaypoints() {
        const deg = getWaveDirectionDeg();
        if (state.lat == null || state.lon == null || deg == null) return Promise.resolve(null);
        const shortM = getShortLegM();
        const longM = getLongLegM();
        const body = {
            lat: state.lat,
            lon: state.lon,
            wave_direction_deg: deg,
            short_leg_m: shortM,
            long_leg_m: longM
        };
        return apiRequest('/api/ess/waypoints', 'POST', body);
    }

    function updateOutput(data) {
        if (!data) {
            outCurrent.textContent = '—';
            outWp1.textContent = outWp2.textContent = outWp3.textContent = outWp4.textContent = '—';
            return;
        }
        const fmt = (p) => p ? `${p.lat.toFixed(6)}, ${p.lon.toFixed(6)}` : '—';
        outCurrent.textContent = fmt(data.current_location);
        outWp1.textContent = fmt(data.wp1);
        outWp2.textContent = fmt(data.wp2);
        outWp3.textContent = fmt(data.wp3);
        outWp4.textContent = fmt(data.wp4);
    }

    function drawDiagram(data) {
        if (!canvas || !data || !data.wp1) return;
        const ctx = canvas.getContext('2d');
        const w = canvas.width;
        const h = canvas.height;
        ctx.clearRect(0, 0, w, h);

        const points = [data.wp1, data.wp2, data.wp3, data.wp4];
        const lats = points.map(p => p.lat);
        const lons = points.map(p => p.lon);
        const latMin = Math.min(...lats);
        const latMax = Math.max(...lats);
        const lonMin = Math.min(...lons);
        const lonMax = Math.max(...lons);
        const rangeLat = (latMax - latMin) || 0.0001;
        const rangeLon = (lonMax - lonMin) || 0.0001;
        const pad = 0.2;
        const midLat = (latMin + latMax) / 2;
        const midLon = (lonMin + lonMax) / 2;
        const scaleDeg = Math.max(rangeLat, rangeLon) * (1 + 2 * pad);
        const pixelsPerDeg = Math.min(w, h) / scaleDeg;

        function toX(lon) {
            return w / 2 + (lon - midLon) * pixelsPerDeg;
        }
        function toY(lat) {
            return h / 2 - (lat - midLat) * pixelsPerDeg;
        }

        const x1 = toX(data.wp1.lon);
        const y1 = toY(data.wp1.lat);
        const x2 = toX(data.wp2.lon);
        const y2 = toY(data.wp2.lat);
        const x3 = toX(data.wp3.lon);
        const y3 = toY(data.wp3.lat);
        const x4 = toX(data.wp4.lon);
        const y4 = toY(data.wp4.lat);

        ctx.strokeStyle = '#e85d04';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.lineTo(x3, y3);
        ctx.lineTo(x4, y4);
        ctx.closePath();
        ctx.stroke();

        ctx.fillStyle = '#000';
        [[x1, y1, 'WP 1'], [x2, y2, 'WP 2'], [x3, y3, 'WP 3'], [x4, y4, 'WP 4']].forEach(function (a) {
            const [x, y, label] = a;
            ctx.beginPath();
            ctx.arc(x, y, 5, 0, Math.PI * 2);
            ctx.fill();
            ctx.font = '12px sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText(label, x, y + 18);
        });

        const deg = getWaveDirectionDeg();
        if (deg != null) {
            const cx = (x1 + x2 + x3 + x4) / 4;
            const cy = (y1 + y2 + y3 + y4) / 4;
            const rad = (90 - deg) * Math.PI / 180;
            const len = 40;
            ctx.strokeStyle = '#0d6efd';
            ctx.lineWidth = 2;
            ctx.beginPath();
            ctx.moveTo(cx, cy);
            ctx.lineTo(cx + len * Math.cos(rad), cy - len * Math.sin(rad));
            ctx.stroke();
            ctx.fillStyle = '#0d6efd';
            ctx.font = '10px sans-serif';
            ctx.textAlign = 'left';
            ctx.fillText('Wave from ' + Math.round(deg) + '\u00B0', cx + len * Math.cos(rad) + 4, cy - len * Math.sin(rad));
        }
    }

    function recalc() {
        fetchWaypoints().then(function (data) {
            state.waypoints = data;
            updateOutput(data);
            drawDiagram(data);
        }).catch(function () {
            updateOutput(null);
        });
    }

    function setPosition(lat, lon) {
        state.lat = lat;
        state.lon = lon;
        if (document.getElementById('inputLat')) document.getElementById('inputLat').value = lat != null ? lat : '';
        if (document.getElementById('inputLon')) document.getElementById('inputLon').value = lon != null ? lon : '';
        recalc();
    }

    document.getElementById('useGliderPosition').addEventListener('click', function () {
        if (initialPosition && initialPosition.lat != null && initialPosition.lon != null) {
            setPosition(initialPosition.lat, initialPosition.lon);
        }
    });

    function updatePositionFromInputs() {
        const latEl = document.getElementById('inputLat');
        const lonEl = document.getElementById('inputLon');
        if (!latEl || !lonEl) return;
        const lat = parseFloat(latEl.value);
        const lon = parseFloat(lonEl.value);
        if (!Number.isNaN(lat) && !Number.isNaN(lon)) setPosition(lat, lon);
    }
    var positionInputDebounce;
    function schedulePositionUpdate() {
        clearTimeout(positionInputDebounce);
        positionInputDebounce = setTimeout(updatePositionFromInputs, 350);
    }
    document.getElementById('inputLat').addEventListener('change', updatePositionFromInputs);
    document.getElementById('inputLat').addEventListener('input', schedulePositionUpdate);
    document.getElementById('inputLon').addEventListener('change', updatePositionFromInputs);
    document.getElementById('inputLon').addEventListener('input', schedulePositionUpdate);

    document.getElementById('waveSourceForecast').addEventListener('change', function () {
        state.useForecast = this.checked;
        recalc();
    });

    const waveSourceCustomEl = document.getElementById('waveSourceCustom');
    const inputCustomWaveDirEl = document.getElementById('inputCustomWaveDir');
    if (waveSourceCustomEl) {
        waveSourceCustomEl.addEventListener('change', function () {
            state.useCustomDir = this.checked;
            if (state.useCustomDir) {
                const forecastCb = document.getElementById('waveSourceForecast');
                if (forecastCb) forecastCb.checked = false;
                state.useForecast = false;
                if (inputCustomWaveDirEl) {
                    const n = parseFloat(inputCustomWaveDirEl.value);
                    state.customDir = (!Number.isNaN(n) && n >= 0 && n <= 360) ? n : null;
                }
            } else {
                state.customDir = null;
            }
            recalc();
        });
    }
    if (inputCustomWaveDirEl) {
        inputCustomWaveDirEl.addEventListener('input', function () {
            if (!state.useCustomDir) return;
            const n = parseFloat(this.value);
            state.customDir = (!Number.isNaN(n) && n >= 0 && n <= 360) ? n : null;
            recalc();
        });
        inputCustomWaveDirEl.addEventListener('change', function () {
            if (!state.useCustomDir) return;
            const n = parseFloat(this.value);
            state.customDir = (!Number.isNaN(n) && n >= 0 && n <= 360) ? n : null;
            recalc();
        });
    }

    const inputShortLegEl = document.getElementById('inputShortLegM');
    const inputLongLegEl = document.getElementById('inputLongLegM');
    if (inputShortLegEl) inputShortLegEl.addEventListener('change', recalc);
    if (inputShortLegEl) inputShortLegEl.addEventListener('input', function () { setTimeout(recalc, 350); });
    if (inputLongLegEl) inputLongLegEl.addEventListener('change', recalc);
    if (inputLongLegEl) inputLongLegEl.addEventListener('input', function () { setTimeout(recalc, 350); });

    document.getElementById('copyCoordinates').addEventListener('click', function () {
        if (!state.waypoints) return;
        const d = state.waypoints;
        const fmt = (p) => p ? p.lat.toFixed(6) + ', ' + p.lon.toFixed(6) : '';
        const text = 'Current location: ' + fmt(d.current_location) + '\n' +
            'WP 1: ' + fmt(d.wp1) + '\n' +
            'WP 2: ' + fmt(d.wp2) + '\n' +
            'WP 3: ' + fmt(d.wp3) + '\n' +
            'WP 4: ' + fmt(d.wp4);
        navigator.clipboard.writeText(text).then(function () {
            const btn = document.getElementById('copyCoordinates');
            const orig = btn.textContent;
            btn.textContent = 'Copied!';
            setTimeout(function () { btn.textContent = orig; }, 1500);
        });
    });

    if (initialWaveMeasured && initialWaveMeasured.direction_deg != null) {
        state.measuredDir = initialWaveMeasured.direction_deg;
        state.measuredTs = initialWaveMeasured.timestamp_str || 'N/A';
        const waveEl = document.getElementById('waveMeasuredValue');
        if (waveEl) waveEl.textContent = 'As of ' + state.measuredTs + ': ' + state.measuredDir + '\u00B0';
    }
    // Apply glider position and waypoints immediately so measured data shows without waiting for forecast
    if (initialPosition && initialPosition.lat != null && initialPosition.lon != null) {
        setPosition(initialPosition.lat, initialPosition.lon);
    }
    let marineForecastUrl = '/api/marine_forecast/' + missionId;
    const forecastParams = new URLSearchParams();
    if (sourcePreference) forecastParams.set('source', sourcePreference);
    if (localPath) forecastParams.set('local_path', localPath);
    if (forecastParams.toString()) marineForecastUrl += '?' + forecastParams.toString();
    fetch(marineForecastUrl).then(function (r) { return r.ok ? r.json() : null; }).then(function (marine) {
        if (marine && marine.hourly && marine.hourly.wave_direction && marine.hourly.wave_direction[0] != null) {
            state.forecastDir = Math.round(Number(marine.hourly.wave_direction[0]));
            const t = marine.hourly.time && marine.hourly.time[0];
            state.forecastTs = t ? new Date(t).toISOString().replace('T', ' ').slice(0, 19) + ' UTC' : 'N/A';
            const forecastEl = document.getElementById('waveForecastValue');
            if (forecastEl) forecastEl.textContent = 'As of ' + state.forecastTs + ': ' + state.forecastDir + '\u00B0';
            if (state.measuredDir == null) {
                state.useForecast = true;
                const cb = document.getElementById('waveSourceForecast');
                if (cb) cb.checked = true;
            }
        }
        recalc();
    }).catch(function () {
        recalc();
    });
})();
