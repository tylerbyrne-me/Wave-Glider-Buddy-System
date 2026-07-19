/**
 * Slocum daily pilot checklist form: render schema, refresh autofill, submit/edit,
 * and Plot-it popups for selected autofilled series.
 */
import { apiRequest, showToast } from '/static/js/api.js';
import { checkAuth } from '/static/js/auth.js';

/** Mirror of backend CHECKLIST_PLOTTABLE_ITEMS keys — add entries there first. */
const PLOTTABLE_ITEM_IDS = new Set([
    'depth_rate_val',
    'vacuum_val',
    'roll_val',
    'pitch_val',
    'fin_val',
    'battpos_val',
    'oil_vol_val',
]);

document.addEventListener('DOMContentLoaded', async () => {
    if (!(await checkAuth())) return;

    const datasetId = document.body.dataset.datasetId;
    const editFormId = document.body.dataset.editFormId
        ? Number(document.body.dataset.editFormId)
        : null;

    const formTitle = document.getElementById('formTitle');
    const formDescription = document.getElementById('formDescription');
    const formSpinner = document.getElementById('formSpinner');
    const checklistForm = document.getElementById('slocumChecklistForm');
    const formSectionsContainer = document.getElementById('formSectionsContainer');
    const submissionStatus = document.getElementById('submissionStatus');
    const editModeBanner = document.getElementById('editModeBanner');
    const submitBtn = document.getElementById('submitChecklistBtn');
    const backLink = document.getElementById('backToDashboardLink');

    let currentSchema = null;
    let unverifiedModal = null;
    let plotModal = null;
    let plotChart = null;
    let activePlotItemId = null;

    const modalEl = document.getElementById('unverifiedConfirmModal');
    if (modalEl && window.bootstrap) {
        unverifiedModal = new bootstrap.Modal(modalEl);
    }

    const plotModalEl = document.getElementById('checklistPlotModal');
    if (plotModalEl && window.bootstrap) {
        plotModal = new bootstrap.Modal(plotModalEl);
        plotModalEl.addEventListener('hidden.bs.modal', () => {
            applyPlotReviewToForm();
            destroyPlotChart();
            setPlotStatus('');
            activePlotItemId = null;
            const commentEl = document.getElementById('checklistPlotComment');
            const verifiedEl = document.getElementById('checklistPlotVerified');
            if (commentEl) commentEl.value = '';
            if (verifiedEl) verifiedEl.checked = false;
        });
        // Keep chart sized when the fullscreen modal finishes opening / window resizes
        plotModalEl.addEventListener('shown.bs.modal', () => {
            if (plotChart) plotChart.resize();
        });
        window.addEventListener('resize', () => {
            if (plotChart && plotModalEl.classList.contains('show')) plotChart.resize();
        });
    }

    if (!datasetId) {
        if (formSpinner) formSpinner.style.display = 'none';
        if (submissionStatus) {
            submissionStatus.innerHTML = '<div class="alert alert-danger">Missing dataset id.</div>';
        }
        return;
    }

    if (backLink) {
        const isHistorical = /_delayed$/.test(datasetId);
        backLink.href = isHistorical
            ? `/slocum/historical?dataset=${encodeURIComponent(datasetId)}`
            : `/slocum?dataset=${encodeURIComponent(datasetId)}`;
    }

    function escapeHtml(value) {
        if (value === null || value === undefined) return '';
        return String(value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function chartThemeColors() {
        // Plot modal is always dark; prefer readable light labels over page CSS vars
        // which can resolve too dark for legend/axis text on bg-dark.
        const styles = getComputedStyle(document.documentElement);
        const pageText = styles.getPropertyValue('--text-color').trim();
        const pageBorder = styles.getPropertyValue('--card-border').trim();
        return {
            text: '#e9ecef',
            muted: '#adb5bd',
            border: pageBorder || 'rgba(255, 255, 255, 0.15)',
            depth: '#4dabf7',
            value: '#ffc078',
            commanded: '#69db7c',
            pageText: pageText || '#e9ecef',
        };
    }

    function nearestWholeDepthMeters(depthPts, dataIndex, timestamp) {
        if (Array.isArray(depthPts) && dataIndex >= 0 && dataIndex < depthPts.length) {
            const aligned = depthPts[dataIndex]?.y;
            if (aligned != null && !Number.isNaN(Number(aligned))) {
                return Math.round(Number(aligned));
            }
        }
        if (!timestamp || !Array.isArray(depthPts) || !depthPts.length) return null;
        const target = new Date(timestamp).getTime();
        if (Number.isNaN(target)) return null;
        let best = null;
        let bestDelta = Infinity;
        for (const pt of depthPts) {
            if (pt?.y == null || Number.isNaN(Number(pt.y))) continue;
            const t = new Date(pt.x).getTime();
            if (Number.isNaN(t)) continue;
            const delta = Math.abs(t - target);
            if (delta < bestDelta) {
                bestDelta = delta;
                best = Math.round(Number(pt.y));
            }
        }
        return best;
    }

    function destroyPlotChart() {
        if (plotChart) {
            plotChart.destroy();
            plotChart = null;
        }
    }

    function setPlotStatus(message, isError = false) {
        const el = document.getElementById('checklistPlotStatus');
        if (!el) return;
        el.textContent = message || '';
        el.classList.toggle('text-danger', !!isError);
        el.classList.toggle('text-muted', !isError);
    }

    function loadPlotReviewFromForm(itemId) {
        const commentEl = document.getElementById('checklistPlotComment');
        const verifiedEl = document.getElementById('checklistPlotVerified');
        const formComment = document.querySelector(`[name="${itemId}_comment"]`);
        const formVerified = document.getElementById(`${itemId}_verified`);
        if (commentEl) commentEl.value = formComment ? formComment.value : '';
        if (verifiedEl) verifiedEl.checked = formVerified ? !!formVerified.checked : false;
    }

    function applyPlotReviewToForm() {
        if (!activePlotItemId) return;
        const commentEl = document.getElementById('checklistPlotComment');
        const verifiedEl = document.getElementById('checklistPlotVerified');
        const formComment = document.querySelector(`[name="${activePlotItemId}_comment"]`);
        const formVerified = document.getElementById(`${activePlotItemId}_verified`);
        if (formComment && commentEl) formComment.value = commentEl.value;
        if (formVerified && verifiedEl) formVerified.checked = !!verifiedEl.checked;
    }

    function buildSavedItemsById(sectionsData) {
        const map = {};
        (sectionsData || []).forEach((section) => {
            (section.items || []).forEach((item) => {
                if (item && item.id) map[item.id] = item;
            });
        });
        return map;
    }

    function applySavedValuesToForm(savedItemsById, sectionsData) {
        Object.entries(savedItemsById).forEach(([id, item]) => {
            const el = document.getElementById(id);
            if (!el) return;
            const itemType = item.item_type || '';
            if (itemType === 'autofilled_value' || itemType === 'static_text') {
                // keep live/static display; restore verify + comment only
            } else if (el.tagName === 'SELECT' || el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
                if (item.value != null) el.value = item.value;
            }
            const commentEl = document.querySelector(`[name="${id}_comment"]`);
            if (commentEl && item.comment != null) commentEl.value = item.comment;
            const verifiedEl = document.getElementById(`${id}_verified`);
            if (verifiedEl && item.is_verified != null) verifiedEl.checked = !!item.is_verified;
            if (itemType === 'checkbox' && el.type === 'checkbox') {
                el.checked = !!item.is_checked;
            }
        });
        (sectionsData || []).forEach((section) => {
            if (!section?.id || section.section_comment == null) return;
            const sectionCommentEl = document.getElementById(`${section.id}_comment`);
            if (sectionCommentEl) sectionCommentEl.value = section.section_comment;
        });
    }

    function wirePlotButtons(root) {
        (root || document).querySelectorAll('[data-checklist-plot-item]').forEach((btn) => {
            btn.addEventListener('click', () => {
                const itemId = btn.getAttribute('data-checklist-plot-item');
                if (itemId) openChecklistPlot(itemId);
            });
        });
    }

    function parseGliderNameFromDatasetId(id) {
        const match = String(id || '').trim().match(/^([A-Za-z0-9]+)_(\d{8})_(\d+)(?:_(realtime|delayed))?$/i);
        if (match) return match[1];
        const fallback = String(id || '').trim().match(/^([A-Za-z0-9]+)_/);
        return fallback ? fallback[1] : (id || 'unknown');
    }

    function formatYYYYMMDD(isoOrDate) {
        if (isoOrDate == null || isoOrDate === '') return null;
        const d = new Date(isoOrDate);
        if (Number.isNaN(d.getTime())) return null;
        const y = d.getUTCFullYear();
        const m = String(d.getUTCMonth() + 1).padStart(2, '0');
        const day = String(d.getUTCDate()).padStart(2, '0');
        return `${y}${m}${day}`;
    }

    function dataWindowYYYYMMDD(...seriesList) {
        const times = [];
        for (const series of seriesList) {
            for (const pt of series || []) {
                if (pt?.x == null) continue;
                const t = new Date(pt.x).getTime();
                if (!Number.isNaN(t)) times.push(t);
            }
        }
        if (!times.length) return null;
        times.sort((a, b) => a - b);
        const start = formatYYYYMMDD(times[0]);
        const end = formatYYYYMMDD(times[times.length - 1]);
        if (!start || !end) return null;
        return start === end ? start : `${start}–${end}`;
    }

    function buildPlotHeading({ vehicleName, variableLabel, unit, windowLabel, commandedLabel }) {
        const varBit = unit ? `${variableLabel} (${unit})` : variableLabel;
        const cmdBit = commandedLabel
            ? (unit ? ` / ${commandedLabel} (${unit})` : ` / ${commandedLabel}`)
            : '';
        const dateBit = windowLabel ? ` · ${windowLabel}` : '';
        return {
            modalTitle: `${vehicleName} · ${varBit}${cmdBit}${dateBit}`,
            chartTitle: [
                `${vehicleName} · ${varBit}${cmdBit}`,
                windowLabel ? `Data window (UTC): ${windowLabel}` : 'Data window (UTC): N/A',
            ],
        };
    }

    async function openChecklistPlot(itemId) {
        if (!plotModal || typeof Chart === 'undefined') {
            showToast('Charting is unavailable in this browser session.', 'danger');
            return;
        }
        activePlotItemId = itemId;
        loadPlotReviewFromForm(itemId);
        const vehicleName = parseGliderNameFromDatasetId(datasetId);
        const titleEl = document.getElementById('checklistPlotModalLabel');
        if (titleEl) titleEl.textContent = `${vehicleName} · Loading plot…`;
        destroyPlotChart();
        setPlotStatus('Loading series…');
        plotModal.show();

        try {
            const payload = await apiRequest(
                `/api/slocum/checklists/${encodeURIComponent(datasetId)}/series?item_id=${encodeURIComponent(itemId)}`,
                'GET',
            );
            const label = payload.label || itemId;
            const unit = payload.unit || '';
            const commandedLabel = payload.commanded_label || null;
            const depthPts = (payload.depth || []).map((p) => ({ x: p.t, y: p.v }));
            const valuePts = (payload.values || []).map((p) => ({ x: p.t, y: p.v }));
            const commandedPts = (payload.commanded || []).map((p) => ({ x: p.t, y: p.v }));
            const windowLabel = dataWindowYYYYMMDD(depthPts, valuePts, commandedPts);
            const heading = buildPlotHeading({
                vehicleName,
                variableLabel: label,
                unit,
                windowLabel,
                commandedLabel,
            });
            if (titleEl) titleEl.textContent = heading.modalTitle;

            const depthValid = depthPts.filter((p) => p.y != null && !Number.isNaN(p.y)).length;
            const valueValid = valuePts.filter((p) => p.y != null && !Number.isNaN(p.y)).length;
            const commandedValid = commandedPts.filter((p) => p.y != null && !Number.isNaN(p.y)).length;
            if (!depthValid && !valueValid && !commandedValid) {
                setPlotStatus('No samples in the checklist window.', true);
                return;
            }
            const cmdStatus = commandedLabel
                ? ` / ${commandedValid} commanded`
                : '';
            setPlotStatus(
                `${vehicleName} · ${windowLabel || 'no dates'} · `
                + `${valueValid} measured${cmdStatus} / ${depthValid} depth sample(s) (full resolution)`,
            );
            renderPlotChart(label, unit, depthPts, valuePts, heading.chartTitle, {
                commandedPts,
                commandedLabel,
            });
        } catch (error) {
            setPlotStatus(`Failed to load plot: ${error.message}`, true);
            showToast(`Plot failed: ${error.message}`, 'danger');
        }
    }

    function renderPlotChart(label, unit, depthPts, valuePts, chartTitleLines = null, extras = {}) {
        destroyPlotChart();
        const canvas = document.getElementById('checklistPlotCanvas');
        if (!canvas) return;
        const colors = chartThemeColors();
        const commandedPts = extras.commandedPts || [];
        const commandedLabel = extras.commandedLabel || null;
        const measuredAxisTitle = unit ? `${label} (${unit})` : label;
        const commandedAxisTitle = commandedLabel
            ? (unit ? `${commandedLabel} (${unit})` : commandedLabel)
            : null;
        const valueAxisTitle = commandedAxisTitle
            ? `${measuredAxisTitle} / ${commandedAxisTitle}`
            : measuredAxisTitle;
        const depthAxisTitle = 'Depth (m)';
        const titleText = Array.isArray(chartTitleLines) && chartTitleLines.length
            ? chartTitleLines
            : [`${valueAxisTitle}  ·  ${depthAxisTitle}`];

        const datasets = [
            {
                type: 'line',
                label: depthAxisTitle,
                data: depthPts,
                borderColor: colors.depth,
                backgroundColor: colors.depth,
                yAxisID: 'y',
                showLine: true,
                pointRadius: 0,
                pointHoverRadius: 0,
                borderWidth: 1.75,
                tension: 0.05,
                spanGaps: false,
                order: 3,
            },
            {
                type: 'scatter',
                label: measuredAxisTitle,
                data: valuePts,
                borderColor: colors.value,
                backgroundColor: colors.value,
                pointBackgroundColor: colors.value,
                pointBorderColor: colors.value,
                yAxisID: 'y2',
                pointRadius: 3.5,
                pointHoverRadius: 6,
                order: 1,
            },
        ];
        if (commandedAxisTitle && commandedPts.length) {
            datasets.push({
                type: 'scatter',
                label: commandedAxisTitle,
                data: commandedPts,
                borderColor: colors.commanded,
                backgroundColor: colors.commanded,
                pointBackgroundColor: colors.commanded,
                pointBorderColor: colors.commanded,
                yAxisID: 'y2',
                pointRadius: 3.5,
                pointHoverRadius: 6,
                pointStyle: 'triangle',
                order: 2,
            });
        }

        plotChart = new Chart(canvas.getContext('2d'), {
            data: { datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                layout: {
                    padding: { top: 8, right: 12, bottom: 4, left: 8 },
                },
                interaction: { mode: 'nearest', intersect: true, axis: 'xy' },
                plugins: {
                    title: {
                        display: true,
                        text: titleText,
                        color: colors.text,
                        font: { size: 15, weight: '600' },
                        padding: { bottom: 10 },
                    },
                    legend: {
                        display: true,
                        position: 'top',
                        labels: {
                            color: colors.text,
                            usePointStyle: true,
                            pointStyle: 'rectRounded',
                            padding: 16,
                            font: { size: 13 },
                            generateLabels(chart) {
                                const dsList = chart.data.datasets || [];
                                return dsList.map((ds, i) => ({
                                    text: ds.label || `Series ${i + 1}`,
                                    fillStyle: ds.borderColor || ds.backgroundColor,
                                    strokeStyle: ds.borderColor || ds.backgroundColor,
                                    fontColor: colors.text,
                                    hidden: !chart.isDatasetVisible(i),
                                    datasetIndex: i,
                                    pointStyle: ds.type === 'scatter'
                                        ? (ds.pointStyle || 'circle')
                                        : 'line',
                                }));
                            },
                        },
                    },
                    tooltip: {
                        backgroundColor: 'rgba(33, 37, 41, 0.95)',
                        titleColor: colors.text,
                        bodyColor: colors.text,
                        borderColor: colors.border,
                        borderWidth: 1,
                        callbacks: {
                            title(items) {
                                const ts = items?.[0]?.parsed?.x;
                                if (ts == null) return '';
                                try {
                                    return new Date(ts).toISOString().replace('.000Z', 'Z');
                                } catch {
                                    return String(items[0].label || '');
                                }
                            },
                            label(ctx) {
                                const v = ctx.parsed?.y;
                                const name = ctx.dataset.label || 'Value';
                                if (v == null || Number.isNaN(v)) return `${name}: N/A`;

                                if (ctx.dataset.type === 'scatter' || ctx.dataset.yAxisID === 'y2') {
                                    const depthM = nearestWholeDepthMeters(
                                        depthPts,
                                        -1,
                                        ctx.parsed?.x ?? ctx.raw?.x,
                                    );
                                    const depthBit = depthM == null ? 'Depth: N/A' : `Depth: ${depthM} m`;
                                    return [
                                        `${name}: ${Number(v).toFixed(3)}`,
                                        depthBit,
                                    ];
                                }

                                return `${name}: ${Math.round(Number(v))} m`;
                            },
                        },
                    },
                    zoom: {
                        limits: {
                            x: { min: 'original', max: 'original' },
                        },
                        pan: {
                            enabled: true,
                            mode: 'x',
                        },
                        zoom: {
                            wheel: { enabled: true },
                            pinch: { enabled: true },
                            mode: 'x',
                        },
                    },
                },
                scales: {
                    x: {
                        type: 'time',
                        title: {
                            display: true,
                            text: 'Time (UTC)',
                            color: colors.text,
                            font: { size: 13, weight: '600' },
                            padding: { top: 8 },
                        },
                        ticks: { color: colors.muted, maxRotation: 0 },
                        grid: { color: colors.border },
                    },
                    y: {
                        type: 'linear',
                        position: 'left',
                        reverse: true,
                        title: {
                            display: true,
                            text: depthAxisTitle,
                            color: colors.depth,
                            font: { size: 13, weight: '600' },
                        },
                        ticks: { color: colors.depth },
                        grid: { color: colors.border },
                    },
                    y2: {
                        type: 'linear',
                        position: 'right',
                        title: {
                            display: true,
                            text: valueAxisTitle,
                            color: colors.value,
                            font: { size: 13, weight: '600' },
                        },
                        ticks: { color: colors.value },
                        grid: { drawOnChartArea: false },
                    },
                },
            },
        });
    }

    const resetZoomBtn = document.getElementById('checklistPlotResetZoomBtn');
    if (resetZoomBtn) {
        resetZoomBtn.addEventListener('click', () => {
            if (plotChart && typeof plotChart.resetZoom === 'function') {
                plotChart.resetZoom();
            }
        });
    }

    function renderSchema(schema, savedSubmission = null) {
        currentSchema = schema;
        if (formTitle) formTitle.textContent = schema.title || 'Slocum Daily Checklist';
        if (formDescription) formDescription.textContent = schema.description || '';
        formSectionsContainer.innerHTML = '';

        (schema.sections || []).forEach((section) => {
            const sectionDiv = document.createElement('div');
            sectionDiv.className = 'form-section';
            sectionDiv.dataset.sectionId = section.id;
            sectionDiv.innerHTML = `<h3 class="h5 mb-3">${section.title || section.id}</h3>`;

            (section.items || []).forEach((item) => {
                const itemDiv = document.createElement('div');
                itemDiv.className = 'form-item mb-3';
                itemDiv.dataset.itemId = item.id;

                let inputHtml = '';
                let labelContent = `${escapeHtml(item.label || item.id)}${item.required ? '<span class="text-danger">*</span>' : ''}`;
                const value = item.value != null && item.value !== '' ? item.value : '';
                const valueEsc = escapeHtml(value);
                const placeholderEsc = escapeHtml(item.placeholder || '');
                const isPlottable = item.item_type === 'autofilled_value' && PLOTTABLE_ITEM_IDS.has(item.id);

                switch (item.item_type) {
                    case 'autofilled_value':
                        inputHtml = isPlottable
                            ? `<div class="checklist-plot-wrap">
                                <div class="autofilled-value" id="${item.id}">${valueEsc || 'N/A'}</div>
                                <button type="button" class="btn btn-outline-secondary btn-sm checklist-plot-btn"
                                    data-checklist-plot-item="${escapeHtml(item.id)}" title="Plot over time with depth">
                                    Plot
                                </button>
                               </div>`
                            : `<div class="autofilled-value" id="${item.id}">${valueEsc || 'N/A'}</div>`;
                        break;
                    case 'static_text':
                        inputHtml = `<div class="static-text" id="${item.id}">${valueEsc || '—'}</div>`;
                        break;
                    case 'text_input':
                        inputHtml = `<input type="text" class="form-control" id="${item.id}" name="${item.id}" value="${valueEsc}" placeholder="${placeholderEsc}" ${item.required ? 'required' : ''}>`;
                        break;
                    case 'text_area':
                        inputHtml = `<textarea class="form-control" id="${item.id}" name="${item.id}" rows="3" placeholder="${placeholderEsc}" ${item.required ? 'required' : ''}>${valueEsc}</textarea>`;
                        break;
                    case 'dropdown': {
                        const options = (item.options || [])
                            .map((opt) => {
                                const optEsc = escapeHtml(opt);
                                return `<option value="${optEsc}" ${value === opt ? 'selected' : ''}>${optEsc}</option>`;
                            })
                            .join('');
                        inputHtml = `<select class="form-select" id="${item.id}" name="${item.id}" ${item.required ? 'required' : ''}>
                            <option value="" ${!value ? 'selected' : ''} disabled>Select…</option>
                            ${options}
                        </select>`;
                        break;
                    }
                    case 'checkbox':
                        inputHtml = `<div class="form-check">
                            <input class="form-check-input" type="checkbox" id="${item.id}" name="${item.id}" ${item.is_checked ? 'checked' : ''}>
                            <label class="form-check-label" for="${item.id}">Checked</label>
                        </div>`;
                        break;
                    default:
                        inputHtml = `<input type="text" class="form-control" id="${item.id}" name="${item.id}" value="${value}">`;
                }

                const showItemComment = item.item_type !== 'text_area';
                const showVerified = item.item_type === 'autofilled_value' || item.item_type === 'static_text';

                itemDiv.innerHTML = `
                    <div class="row align-items-center">
                        <div class="col-md-3">
                            <label for="${item.id}" class="form-label mb-0">${labelContent}</label>
                        </div>
                        <div class="col-md-4">${inputHtml}</div>
                        <div class="col-md-3">
                            ${showItemComment ? `<textarea class="form-control form-control-sm" name="${item.id}_comment" rows="1" placeholder="Comment..."></textarea>` : ''}
                        </div>
                        <div class="col-md-2">
                            ${showVerified ? `
                            <div class="form-check">
                                <input class="form-check-input" type="checkbox" id="${item.id}_verified" name="${item.id}_verified" value="true">
                                <label class="form-check-label" for="${item.id}_verified">Verified</label>
                            </div>` : ''}
                        </div>
                    </div>
                `;
                sectionDiv.appendChild(itemDiv);
            });

            if (section.section_comment != null) {
                const notes = document.createElement('div');
                notes.className = 'mt-3';
                notes.innerHTML = `
                    <label for="${section.id}_comment" class="form-label">Section Notes:</label>
                    <textarea class="form-control" id="${section.id}_comment" name="${section.id}_comment" rows="2" placeholder="Overall notes for this section...">${section.section_comment || ''}</textarea>
                `;
                sectionDiv.appendChild(notes);
            }

            formSectionsContainer.appendChild(sectionDiv);
        });

        wirePlotButtons(formSectionsContainer);

        checklistForm.style.display = 'block';
        if (formSpinner) formSpinner.style.display = 'none';

        if (savedSubmission) {
            applySavedValuesToForm(
                buildSavedItemsById(savedSubmission.sections_data),
                savedSubmission.sections_data,
            );
            if (editModeBanner) {
                editModeBanner.style.display = 'block';
                editModeBanner.textContent = `Editing submission #${savedSubmission.id} by ${savedSubmission.submitted_by_username || 'unknown'}. Save will update this record.`;
            }
            if (submitBtn) submitBtn.textContent = 'Save Changes';
        }
    }

    function buildSectionsDataFromForm() {
        if (!currentSchema) return [];
        return (currentSchema.sections || []).map((section) => {
            const sectionCommentEl = document.getElementById(`${section.id}_comment`);
            const items = (section.items || []).map((item) => {
                const el = document.getElementById(item.id);
                const verifiedEl = document.getElementById(`${item.id}_verified`);
                const commentEl = document.querySelector(`[name="${item.id}_comment"]`);
                let value = null;
                let isChecked = null;
                if (item.item_type === 'autofilled_value' || item.item_type === 'static_text') {
                    value = el ? el.textContent : item.value;
                } else if (item.item_type === 'checkbox') {
                    isChecked = el ? el.checked : false;
                    value = isChecked ? 'true' : 'false';
                } else if (el) {
                    value = el.value;
                }
                return {
                    id: item.id,
                    label: item.label,
                    item_type: item.item_type,
                    value,
                    is_checked: isChecked,
                    is_verified: verifiedEl ? verifiedEl.checked : null,
                    comment: commentEl ? commentEl.value : null,
                    required: !!item.required,
                    options: item.options || null,
                    placeholder: item.placeholder || null,
                };
            });
            return {
                id: section.id,
                title: section.title,
                items,
                section_comment: sectionCommentEl ? sectionCommentEl.value : section.section_comment,
            };
        });
    }

    function countUnverified(sectionsData) {
        let count = 0;
        (sectionsData || []).forEach((section) => {
            (section.items || []).forEach((item) => {
                if (
                    (item.item_type === 'autofilled_value' || item.item_type === 'static_text')
                    && item.is_verified === false
                ) {
                    count += 1;
                }
            });
        });
        return count;
    }

    async function performSubmission(sectionsData) {
        if (submissionStatus) submissionStatus.innerHTML = '';
        const payload = {
            mission_id: datasetId,
            form_type: currentSchema?.form_type || 'slocum_daily_checklist',
            form_title: currentSchema?.title || 'Slocum Daily Pilot Checklist',
            sections_data: sectionsData,
        };
        try {
            if (editFormId) {
                await apiRequest(`/api/slocum/checklists/id/${editFormId}`, 'PUT', payload);
                showToast('Checklist updated.', 'success');
            } else {
                await apiRequest(`/api/slocum/checklists/${encodeURIComponent(datasetId)}`, 'POST', payload);
                showToast('Checklist submitted.', 'success');
            }
            window.location.href = backLink?.href || `/slocum?dataset=${encodeURIComponent(datasetId)}`;
        } catch (error) {
            if (submissionStatus) {
                submissionStatus.innerHTML = `<div class="alert alert-danger">Failed to save: ${error.message}</div>`;
            }
            showToast(`Failed to save checklist: ${error.message}`, 'danger');
        }
    }

    async function fetchAndRender() {
        if (formSpinner) formSpinner.style.display = 'block';
        checklistForm.style.display = 'none';
        try {
            const schema = await apiRequest(
                `/api/slocum/checklists/${encodeURIComponent(datasetId)}/template`,
                'GET',
            );
            let saved = null;
            if (editFormId) {
                saved = await apiRequest(`/api/slocum/checklists/id/${editFormId}`, 'GET');
            }
            renderSchema(schema, saved);
        } catch (error) {
            if (formSpinner) formSpinner.style.display = 'none';
            if (submissionStatus) {
                submissionStatus.innerHTML = `<div class="alert alert-danger">Failed to load checklist: ${error.message}</div>`;
            }
        }
    }

    const refreshBtn = document.getElementById('refreshFormDataBtn');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', async () => {
            refreshBtn.disabled = true;
            const original = refreshBtn.textContent;
            refreshBtn.textContent = 'Refreshing…';
            try {
                const schema = await apiRequest(
                    `/api/slocum/checklists/${encodeURIComponent(datasetId)}/template`,
                    'GET',
                );
                currentSchema = schema;
                let updated = 0;
                for (const section of schema.sections || []) {
                    for (const item of section.items || []) {
                        if (!item.id) continue;
                        if (item.item_type === 'autofilled_value' || item.item_type === 'static_text') {
                            const el = document.getElementById(item.id);
                            if (el && (el.classList.contains('autofilled-value') || el.classList.contains('static-text'))) {
                                el.textContent = item.value != null && item.value !== '' ? item.value : 'N/A';
                                updated += 1;
                            }
                        }
                    }
                }
                showToast(`Refreshed ${updated} autofilled field(s).`, 'success');
            } catch (error) {
                showToast(`Refresh failed: ${error.message}`, 'danger');
            } finally {
                refreshBtn.disabled = false;
                refreshBtn.textContent = original;
            }
        });
    }

    checklistForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        const sectionsData = buildSectionsDataFromForm();
        const unverified = countUnverified(sectionsData);
        if (unverified > 0 && unverifiedModal) {
            const submitAnyway = document.getElementById('unverifiedSubmitBtn');
            const cancelBtn = document.getElementById('unverifiedCancelSubmissionBtn');
            const onSubmit = () => {
                unverifiedModal.hide();
                performSubmission(sectionsData);
                cleanup();
            };
            const onCancel = () => {
                unverifiedModal.hide();
                cleanup();
            };
            function cleanup() {
                submitAnyway?.removeEventListener('click', onSubmit);
                cancelBtn?.removeEventListener('click', onCancel);
            }
            submitAnyway?.addEventListener('click', onSubmit);
            cancelBtn?.addEventListener('click', onCancel);
            unverifiedModal.show();
            return;
        }
        await performSubmission(sectionsData);
    });

    await fetchAndRender();
});
