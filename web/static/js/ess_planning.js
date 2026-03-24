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

    function bearingFromDegToCanvasUnit(fromDeg) {
        const r = (fromDeg % 360 + 360) % 360 * Math.PI / 180;
        return { ux: Math.sin(r), uy: -Math.cos(r) };
    }

    function drawArrow(ctx, x0, y0, x1, y1, color, lineW, headLen) {
        const dx = x1 - x0;
        const dy = y1 - y0;
        const len = Math.hypot(dx, dy);
        if (len < 0.001) return;
        const ux = dx / len;
        const uy = dy / len;
        const bx = x1 - ux * headLen;
        const by = y1 - uy * headLen;
        const perpX = -uy;
        const perpY = ux;
        const hw = headLen * 0.55;
        ctx.strokeStyle = color;
        ctx.fillStyle = color;
        ctx.lineWidth = lineW;
        ctx.lineJoin = 'round';
        ctx.beginPath();
        ctx.moveTo(x0, y0);
        ctx.lineTo(bx, by);
        ctx.stroke();
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(bx + perpX * hw, by + perpY * hw);
        ctx.lineTo(bx - perpX * hw, by - perpY * hw);
        ctx.closePath();
        ctx.fill();
    }

    function drawLabelWithHalo(ctx, text, px, py, fill, stroke) {
        ctx.font = '12px sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        const padX = 4;
        const padY = 3;
        const tw = ctx.measureText(text).width;
        const th = 12;
        const bx = px - tw / 2 - padX;
        const by = py - th / 2 - padY;
        const bw = tw + padX * 2;
        const bh = th + padY * 2;
        const rr = 4;
        ctx.fillStyle = 'rgba(255,255,255,0.95)';
        ctx.strokeStyle = 'rgba(0,0,0,0.12)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        if (typeof ctx.roundRect === 'function') {
            ctx.roundRect(bx, by, bw, bh, rr);
        } else {
            ctx.rect(bx, by, bw, bh);
        }
        ctx.fill();
        ctx.stroke();
        ctx.fillStyle = fill || '#212529';
        ctx.fillText(text, px, py);
    }

    function drawDiagram(data) {
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        const w = canvas.width;
        const h = canvas.height;
        ctx.clearRect(0, 0, w, h);
        if (!data || !data.wp1) return;

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

        const cx = (x1 + x2 + x3 + x4) / 4;
        const cy = (y1 + y2 + y3 + y4) / 4;
        const bxMin = Math.min(x1, x2, x3, x4);
        const bxMax = Math.max(x1, x2, x3, x4);
        const byMin = Math.min(y1, y2, y3, y4);
        const byMax = Math.max(y1, y2, y3, y4);
        const patCx = (bxMin + bxMax) / 2;
        const patCy = (byMin + byMax) / 2;
        const boxPad = 14;
        const xmin = bxMin - boxPad;
        const xmax = bxMax + boxPad;
        const ymin = byMin - boxPad;
        const ymax = byMax + boxPad;

        function rayExitDistAlongRay(px, py, ux, uy, xmin0, xmax0, ymin0, ymax0) {
            let tMin = Infinity;
            if (Math.abs(ux) > 1e-9) {
                for (let xv = 0; xv < 2; xv++) {
                    const xb = xv === 0 ? xmin0 : xmax0;
                    const t = (xb - px) / ux;
                    if (t > 0) {
                        const yy = py + t * uy;
                        if (yy >= ymin0 - 1e-6 && yy <= ymax0 + 1e-6) tMin = Math.min(tMin, t);
                    }
                }
            }
            if (Math.abs(uy) > 1e-9) {
                for (let yv = 0; yv < 2; yv++) {
                    const yb = yv === 0 ? ymin0 : ymax0;
                    const t = (yb - py) / uy;
                    if (t > 0) {
                        const xx = px + t * ux;
                        if (xx >= xmin0 - 1e-6 && xx <= xmax0 + 1e-6) tMin = Math.min(tMin, t);
                    }
                }
            }
            return tMin === Infinity ? Math.max(xmax0 - xmin0, ymax0 - ymin0) * 0.25 : tMin;
        }

        const markerR = 5;
        const waveBodyLen = 22;

        function drawSegmentDirectionArrow(ax, ay, bx, by, color, lineW, headLen, along) {
            const frac = along == null ? 0.5 : along;
            const dx = bx - ax;
            const dy = by - ay;
            const len = Math.hypot(dx, dy);
            if (len < 8) return;
            const ux = dx / len;
            const uy = dy / len;
            const cap = Math.min(18, Math.max(10, len * 0.2));
            const mx = ax + (bx - ax) * frac;
            const my = ay + (by - ay) * frac;
            const s0x = mx - ux * cap * 0.5;
            const s0y = my - uy * cap * 0.5;
            const s1x = mx + ux * cap * 0.5;
            const s1y = my + uy * cap * 0.5;
            drawArrow(ctx, s0x, s0y, s1x, s1y, color, lineW, headLen);
        }

        ctx.strokeStyle = '#e85d04';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.lineTo(x3, y3);
        ctx.lineTo(x4, y4);
        ctx.closePath();
        ctx.stroke();

        const travelColor = '#198754';
        const edgeLens = [
            Math.hypot(x2 - x1, y2 - y1),
            Math.hypot(x3 - x2, y3 - y2),
            Math.hypot(x4 - x3, y4 - y3),
            Math.hypot(x1 - x4, y1 - y4)
        ];
        const edgeOrder = [0, 1, 2, 3].sort(function (a, b) {
            return edgeLens[b] - edgeLens[a];
        });
        const long1 = edgeOrder[0];
        const long2 = edgeOrder[1];
        const alongFor = function (idx) {
            if (idx === long1) return 0.30;
            if (idx === long2) return 0.70;
            return 0.5;
        };
        drawSegmentDirectionArrow(x1, y1, x2, y2, travelColor, 2, 7, alongFor(0));
        drawSegmentDirectionArrow(x2, y2, x3, y3, travelColor, 2, 7, alongFor(1));
        drawSegmentDirectionArrow(x3, y3, x4, y4, travelColor, 2, 7, alongFor(2));
        drawSegmentDirectionArrow(x4, y4, x1, y1, travelColor, 2, 7, alongFor(3));

        ctx.fillStyle = '#000';
        [[x1, y1], [x2, y2], [x3, y3], [x4, y4]].forEach(function (pt) {
            ctx.beginPath();
            ctx.arc(pt[0], pt[1], markerR, 0, Math.PI * 2);
            ctx.fill();
        });

        const labels = [[x1, y1, 'WP 1'], [x2, y2, 'WP 2'], [x3, y3, 'WP 3'], [x4, y4, 'WP 4']];
        labels.forEach(function (a) {
            const vx = a[0] - cx;
            const vy = a[1] - cy;
            const vlen = Math.hypot(vx, vy) || 1;
            const ox = (vx / vlen) * (markerR + 22);
            const oy = (vy / vlen) * (markerR + 22);
            drawLabelWithHalo(ctx, a[2], a[0] + ox, a[1] + oy);
        });

        const deg = getWaveDirectionDeg();
        if (deg != null) {
            const waveFrom = bearingFromDegToCanvasUnit(deg);
            const tExit = rayExitDistAlongRay(patCx, patCy, waveFrom.ux, waveFrom.uy, xmin, xmax, ymin, ymax);
            const tipDist = tExit + 6;
            const tailDist = tipDist + waveBodyLen;
            const tailX = patCx + tailDist * waveFrom.ux;
            const tailY = patCy + tailDist * waveFrom.uy;
            const tipX = patCx + tipDist * waveFrom.ux;
            const tipY = patCy + tipDist * waveFrom.uy;
            drawArrow(ctx, tailX, tailY, tipX, tipY, '#0d6efd', 2.5, 9);
            const waveLabel = 'Waves from ' + Math.round(deg) + '\u00B0';
            const margin = 12;
            const clamp = function (v, lo, hi) { return Math.max(lo, Math.min(hi, v)); };
            const midWx = (tipX + tailX) / 2;
            const midWy = (tipY + tailY) / 2;
            const lxo = waveFrom.uy * 12;
            const lyo = -waveFrom.ux * 12;
            drawLabelWithHalo(
                ctx, waveLabel,
                clamp(midWx + lxo, margin, w - margin),
                clamp(midWy + lyo, margin, h - margin),
                '#0d6efd'
            );
        }
    }

    function recalc() {
        fetchWaypoints().then(function (data) {
            state.waypoints = data;
            updateOutput(data);
            drawDiagram(data);
        }).catch(function () {
            state.waypoints = null;
            updateOutput(null);
            drawDiagram(null);
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
