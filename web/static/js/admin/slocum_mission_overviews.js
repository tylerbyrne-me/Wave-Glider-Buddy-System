/**
 * @file slocum_mission_overviews.js
 * @description Admin Slocum mission overviews: Sensor Tracker sync, briefing goals/comments, reports.
 * Mirrors the Wave Glider Manage Mission Overviews page layout and interactions.
 */

import { checkAuth, getUserProfile } from '/static/js/auth.js';
import { apiRequest, showToast, fetchWithAuth } from '/static/js/api.js';
import { formatUtcDateTime } from '/static/js/datetime_utils.js';

document.addEventListener('DOMContentLoaded', async () => {
    if (!await checkAuth()) return;

    const user = await getUserProfile();
    if (!user || user.role !== 'admin') {
        document.body.innerHTML = '<div class="container mt-5"><div class="alert alert-danger">Access Denied. You must be an administrator to view this page.</div></div>';
        return;
    }

    // --- Selector ---
    const missionSelect = document.getElementById('missionSelect');
    const missionSpinner = document.getElementById('missionSpinner');
    const parsedIdentity = document.getElementById('parsedIdentity');
    const overviewFormContainer = document.getElementById('overviewFormContainer');
    const editingMissionTitle = document.getElementById('editingMissionTitle');

    // --- Sensor Tracker ---
    const stMissionCode = document.getElementById('stMissionCode');
    const syncSensorTrackerBtn = document.getElementById('syncSensorTrackerBtn');
    const forceMetadataSync = document.getElementById('forceMetadataSync');
    const sensorTrackerSyncStatus = document.getElementById('sensorTrackerSyncStatus');
    const sensorTrackerLastSync = document.getElementById('sensorTrackerLastSync');
    const sensorTrackerMetadataContainer = document.getElementById('sensorTrackerMetadataContainer');
    const sensorTrackerMetadataPlaceholder = document.getElementById('sensorTrackerMetadataPlaceholder');

    // --- Briefing ---
    const currentPlanContainer = document.getElementById('currentPlanContainer');
    const currentPlanLink = document.getElementById('currentPlanLink');
    const removePlanBtn = document.getElementById('removePlanBtn');
    const documentUpload = document.getElementById('documentUpload');
    const uploadPlanBtn = document.getElementById('uploadPlanBtn');
    const planUploadStatus = document.getElementById('planUploadStatus');
    const saveSensorCardsBtn = document.getElementById('saveSensorCardsBtn');
    const sensorCardsStatus = document.getElementById('sensorCardsStatus');
    const saveChecklistRefsBtn = document.getElementById('saveChecklistRefsBtn');
    const checklistRefsStatus = document.getElementById('checklistRefsStatus');
    const refBatteryPack = document.getElementById('refBatteryPack');
    const refGliderDepthClass = document.getElementById('refGliderDepthClass');
    const DEFAULT_SENSOR_CARDS = ['ctd'];
    const CHECKLIST_REF_NUMERIC_KEYS = new Set([
        'endurance_amphr_total',
        'min_voltage',
        'max_voltage',
        'max_vacuum',
        'vacuum_at_depth',
        'vacuum_at_surface',
        'amphr_per_day_budget',
    ]);
    let checklistPresets = {
        battery_packs: [],
        glider_depth_classes: [],
    };
    const missionNotesList = document.getElementById('adminMissionNotesList');
    const newMissionNoteContent = document.getElementById('newMissionNoteContent');
    const addMissionNoteBtn = document.getElementById('addMissionNoteBtn');
    const missionGoalsList = document.getElementById('adminMissionGoalsList');
    const addGoalBtn = document.getElementById('addGoalBtn');
    const goalModalElement = document.getElementById('goalModal');
    const goalModal = goalModalElement ? new bootstrap.Modal(goalModalElement) : null;
    const goalModalLabel = document.getElementById('goalModalLabel');
    const goalIdInput = document.getElementById('goalIdInput');
    const goalDescriptionInput = document.getElementById('goalDescriptionInput');
    const saveGoalBtn = document.getElementById('saveGoalBtn');

    // --- Reports ---
    const weeklyReportContainer = document.getElementById('weeklyReportContainer');
    const weeklyReportSelect = document.getElementById('weeklyReportSelect');
    const weeklyReportLink = document.getElementById('weeklyReportLink');
    const weeklyReportFilename = document.getElementById('weeklyReportFilename');
    const weeklyReportBadge = document.getElementById('weeklyReportBadge');
    const noReportsContainer = document.getElementById('noReportsContainer');
    const generateReportBtn = document.getElementById('generateReportBtn');
    const reportGenerationSpinner = document.getElementById('reportGenerationSpinner');
    const reportStatus = document.getElementById('reportStatus');
    const reportResult = document.getElementById('reportResult');
    const reportDownloadLink = document.getElementById('reportDownloadLink');

    let currentDatasetId = null;
    let currentInfo = null;
    let currentReports = [];

    const escapeHtml = (str) => String(str ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#039;');
    const formatTimestamp = (value) => (value ? formatUtcDateTime(value) : '-');

    // --- Sensor Tracker rendering (mirrors WG stTitle/stStart/... layout) ---
    function renderInstrumentGroup(items, containerId, listId, serialId) {
        const container = document.getElementById(containerId);
        const list = document.getElementById(listId);
        const serialEl = serialId ? document.getElementById(serialId) : null;
        if (!items.length) {
            container.style.display = 'none';
            return false;
        }
        if (serialEl) {
            const loggerSerial = items[0].data_logger_serial;
            if (loggerSerial) {
                serialEl.textContent = `Serial: ${loggerSerial}`;
                serialEl.style.display = 'block';
            } else {
                serialEl.style.display = 'none';
            }
        }
        list.innerHTML = '';
        items.forEach(inst => {
            const li = document.createElement('li');
            li.className = 'mb-1';
            const name = inst.instrument_name || inst.instrument_long_name || inst.instrument_identifier;
            const serial = inst.instrument_serial ? ` (${inst.instrument_serial})` : '';
            li.innerHTML = `<strong>${escapeHtml(name)}</strong>${escapeHtml(serial)}`;
            list.appendChild(li);
        });
        container.style.display = 'block';
        return true;
    }

    function renderSensorTracker(deployment, instruments) {
        if (!deployment) {
            sensorTrackerMetadataContainer.style.display = 'none';
            sensorTrackerMetadataPlaceholder.style.display = 'block';
            sensorTrackerLastSync.textContent = 'Last synced: --';
            return;
        }
        sensorTrackerMetadataPlaceholder.style.display = 'none';

        sensorTrackerLastSync.textContent = `Last synced: ${deployment.last_synced_at ? formatTimestamp(deployment.last_synced_at) : '--'}`;
        document.getElementById('stTitle').textContent = deployment.title || '-';
        document.getElementById('stStart').textContent = deployment.start_time ? formatUtcDateTime(deployment.start_time) : '-';
        document.getElementById('stEnd').textContent = deployment.end_time ? formatUtcDateTime(deployment.end_time) : '-';
        document.getElementById('stPlatform').textContent = deployment.platform_name || '-';

        const repoCell = document.getElementById('stDataRepo');
        if (deployment.data_repository_link) {
            const repoLink = document.createElement('a');
            repoLink.href = deployment.data_repository_link;
            repoLink.target = '_blank';
            repoLink.rel = 'noopener noreferrer';
            repoLink.textContent = deployment.data_repository_link;
            repoLink.className = 'text-break';
            repoCell.innerHTML = '';
            repoCell.appendChild(repoLink);
        } else {
            repoCell.textContent = '-';
        }

        document.getElementById('stDescription').textContent = deployment.deployment_comment || '-';

        const allInstruments = instruments || [];
        const hasFlight = renderInstrumentGroup(
            allInstruments.filter(i => i.data_logger_type === 'flight'),
            'stFlightInstrumentsContainer', 'stFlightInstruments', 'stFlightComputerSerial'
        );
        const hasScience = renderInstrumentGroup(
            allInstruments.filter(i => i.data_logger_type === 'science'),
            'stScienceInstrumentsContainer', 'stScienceInstruments', 'stScienceComputerSerial'
        );
        const hasPlatform = renderInstrumentGroup(
            allInstruments.filter(i => i.is_platform_direct),
            'stPlatformInstrumentsContainer', 'stPlatformInstruments', null
        );
        document.getElementById('stInstrumentsContainer').style.display =
            (hasFlight || hasScience || hasPlatform) ? 'flex' : 'none';

        sensorTrackerMetadataContainer.style.display = 'block';
    }

    // --- Briefing rendering (mirrors WG comments/goals lists) ---
    function renderMissionNotes(notes) {
        if (!currentInfo?.deployment) {
            missionNotesList.innerHTML = '<li class="list-group-item text-muted no-mission-notes-placeholder">Unable to load comments for this dataset.</li>';
            return;
        }
        if (!notes || notes.length === 0) {
            missionNotesList.innerHTML = '<li class="list-group-item text-muted no-mission-notes-placeholder">No mission comments have been added.</li>';
            return;
        }
        missionNotesList.innerHTML = notes.map(note => `
            <li class="list-group-item d-flex justify-content-between align-items-start" data-note-id="${note.id}">
                <div class="flex-grow-1">
                    <p class="mb-1">${escapeHtml(note.content)}</p>
                    <small class="text-muted">
                        &mdash; ${escapeHtml(note.created_by_username || 'Unknown')} on ${formatTimestamp(note.created_at_utc)}
                    </small>
                </div>
                <div class="d-flex flex-column gap-1 ms-2">
                    <button class="btn btn-sm btn-outline-danger delete-note-btn" title="Delete Comment" data-note-id="${note.id}">
                        <i class="fas fa-trash-alt"></i>
                    </button>
                </div>
            </li>
        `).join('');
    }

    function renderMissionGoals(goals) {
        if (!currentInfo?.deployment) {
            missionGoalsList.innerHTML = '<li class="list-group-item text-muted no-mission-goals-placeholder">Unable to load goals for this dataset.</li>';
            return;
        }
        if (!goals || goals.length === 0) {
            missionGoalsList.innerHTML = '<li class="list-group-item text-muted no-mission-goals-placeholder">No mission goals have been defined.</li>';
            return;
        }
        missionGoalsList.innerHTML = goals.map(goal => `
            <li class="list-group-item d-flex justify-content-between align-items-start" data-goal-id="${goal.id}">
                <div class="form-check flex-grow-1">
                    <input class="form-check-input mission-goal-checkbox" type="checkbox" id="goal-${goal.id}" data-goal-id="${goal.id}" ${goal.is_completed ? 'checked' : ''}>
                    <label class="form-check-label ${goal.is_completed ? 'text-decoration-line-through text-muted' : ''}" for="goal-${goal.id}">
                        ${escapeHtml(goal.description)}
                    </label>
                    <button class="btn btn-sm btn-link p-0 ms-2 edit-goal-btn" title="Edit Goal" data-goal-id="${goal.id}" data-description="${escapeHtml(goal.description)}">
                        <i class="fas fa-pencil-alt"></i>
                    </button>
                    <button class="btn btn-sm btn-link p-0 ms-2 text-danger delete-goal-btn" title="Delete Goal" data-goal-id="${goal.id}">
                        <i class="fas fa-trash-alt"></i>
                    </button>
                </div>
                ${goal.is_completed ? `
                    <span class="badge bg-success rounded-pill small ms-2" title="Completed at ${formatTimestamp(goal.completed_at_utc)}">
                        By: ${escapeHtml(goal.completed_by_username || '')}
                    </span>
                ` : ''}
            </li>
        `).join('');
    }

    function setPlanActionsEnabled(isEnabled) {
        if (documentUpload) documentUpload.disabled = !isEnabled;
        if (uploadPlanBtn) uploadPlanBtn.disabled = !isEnabled;
        if (removePlanBtn) removePlanBtn.disabled = !isEnabled;
        document.querySelectorAll('.slocum-sensor-card-checkbox').forEach((cb) => {
            cb.disabled = !isEnabled;
        });
        if (saveSensorCardsBtn) saveSensorCardsBtn.disabled = !isEnabled;
        document.querySelectorAll('.checklist-ref-input').forEach((input) => {
            input.disabled = !isEnabled;
        });
        if (saveChecklistRefsBtn) saveChecklistRefsBtn.disabled = !isEnabled;
    }

    function getSelectedSensorCards() {
        return Array.from(document.querySelectorAll('.slocum-sensor-card-checkbox:checked')).map((cb) => cb.value);
    }

    function setSelectedSensorCards(cards) {
        const enabled = new Set(Array.isArray(cards) ? cards : DEFAULT_SENSOR_CARDS);
        document.querySelectorAll('.slocum-sensor-card-checkbox').forEach((cb) => {
            cb.checked = enabled.has(cb.value);
        });
    }

    function renderSensorCards(documentCardsJson) {
        let cards = DEFAULT_SENSOR_CARDS;
        if (documentCardsJson) {
            try {
                const parsed = JSON.parse(documentCardsJson);
                if (Array.isArray(parsed)) cards = parsed;
            } catch (_) {
                cards = DEFAULT_SENSOR_CARDS;
            }
        }
        setSelectedSensorCards(cards);
        if (sensorCardsStatus) sensorCardsStatus.innerHTML = '';
    }

    function renderChecklistReferences(rawJson) {
        let refs = {};
        if (rawJson) {
            try {
                const parsed = JSON.parse(rawJson);
                if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) refs = parsed;
            } catch (_) {
                refs = {};
            }
        }
        document.querySelectorAll('.checklist-ref-input').forEach((input) => {
            const key = input.dataset.refKey;
            const value = refs[key];
            input.value = value == null ? '' : String(value);
        });
        // Re-apply preset expansion into empty numeric fields for display convenience
        applyBatteryPackPreset(refBatteryPack?.value || '', { overwrite: false });
        applyGliderDepthPreset(refGliderDepthClass?.value || '', { overwrite: false });
        if (checklistRefsStatus) checklistRefsStatus.innerHTML = '';
    }

    function setChecklistInputValue(refKey, value, { overwrite }) {
        const input = document.querySelector(`.checklist-ref-input[data-ref-key="${refKey}"]`);
        if (!input || input.tagName === 'SELECT') return;
        if (!overwrite && (input.value || '').trim() !== '') return;
        input.value = value == null ? '' : String(value);
    }

    function applyBatteryPackPreset(packId, { overwrite } = { overwrite: true }) {
        const pack = (checklistPresets.battery_packs || []).find((p) => p.id === packId);
        if (!pack) return;
        setChecklistInputValue('endurance_amphr_total', pack.endurance_amphr_total, { overwrite });
        setChecklistInputValue('min_voltage', pack.min_voltage, { overwrite });
        setChecklistInputValue('max_voltage', pack.max_voltage, { overwrite });
    }

    function applyGliderDepthPreset(depthId, { overwrite } = { overwrite: true }) {
        const depth = (checklistPresets.glider_depth_classes || []).find((p) => p.id === depthId);
        if (!depth) return;
        setChecklistInputValue('vacuum_at_depth', depth.vacuum_at_depth, { overwrite });
        setChecklistInputValue('vacuum_at_surface', depth.vacuum_at_surface, { overwrite });
        setChecklistInputValue('max_vacuum', depth.max_vacuum ?? depth.vacuum_at_surface, { overwrite });
    }

    function populateChecklistPresetSelects() {
        if (refBatteryPack) {
            const current = refBatteryPack.value;
            refBatteryPack.innerHTML = '<option value="">Select pack…</option>';
            (checklistPresets.battery_packs || []).forEach((pack) => {
                const opt = document.createElement('option');
                opt.value = pack.id;
                opt.textContent = `${pack.label} (${pack.endurance_amphr_total} Ah, ${pack.min_voltage}–${pack.max_voltage} V)`;
                refBatteryPack.appendChild(opt);
            });
            if (current) refBatteryPack.value = current;
        }
        if (refGliderDepthClass) {
            const current = refGliderDepthClass.value;
            refGliderDepthClass.innerHTML = '<option value="">Select shallow/deep…</option>';
            (checklistPresets.glider_depth_classes || []).forEach((depth) => {
                const opt = document.createElement('option');
                opt.value = depth.id;
                opt.textContent = `${depth.label} (~${depth.vacuum_at_depth} mmHg depth / ~${depth.vacuum_at_surface} mmHg surface)`;
                refGliderDepthClass.appendChild(opt);
            });
            if (current) refGliderDepthClass.value = current;
        }
    }

    async function loadChecklistPresets() {
        try {
            checklistPresets = await apiRequest('/api/slocum/checklist-presets', 'GET');
            populateChecklistPresetSelects();
        } catch (error) {
            console.warn('Failed to load checklist presets', error);
        }
    }

    function collectChecklistReferences() {
        const out = {};
        document.querySelectorAll('.checklist-ref-input').forEach((input) => {
            const key = input.dataset.refKey;
            if (!key) return;
            const raw = (input.value || '').trim();
            if (!raw) return;
            if (CHECKLIST_REF_NUMERIC_KEYS.has(key)) {
                const num = Number(raw);
                if (!Number.isNaN(num)) out[key] = num;
                else out[key] = raw;
            } else {
                out[key] = raw;
            }
        });
        return out;
    }

    function renderPlanDocument(documentUrl) {
        if (documentUrl && currentPlanContainer && currentPlanLink) {
            currentPlanLink.href = documentUrl;
            currentPlanLink.textContent = documentUrl.split('/').pop();
            currentPlanContainer.style.display = 'block';
        } else if (currentPlanContainer) {
            currentPlanContainer.style.display = 'none';
            if (currentPlanLink) {
                currentPlanLink.href = '#';
                currentPlanLink.textContent = '';
            }
        }
        if (planUploadStatus) planUploadStatus.innerHTML = '';
        if (documentUpload) documentUpload.value = '';
    }

    function renderBriefing(info) {
        const hasDeployment = Boolean(info.deployment);
        const deploymentLinkAlert = document.getElementById('deploymentLinkAlert');
        if (deploymentLinkAlert) deploymentLinkAlert.style.display = hasDeployment ? 'none' : 'block';
        setPlanActionsEnabled(hasDeployment);
        renderSensorCards(info.deployment?.enabled_sensor_cards || null);
        renderChecklistReferences(info.deployment?.checklist_reference_values || null);
        renderPlanDocument(info.deployment?.document_url || null);
        renderMissionNotes(info.notes);
        renderMissionGoals(info.goals);
    }

    // --- Reports ---
    function renderWeeklyReportSelection() {
        const idx = weeklyReportSelect.selectedIndex;
        const report = currentReports[idx];
        if (!report) return;
        weeklyReportLink.href = report.url;
        weeklyReportFilename.textContent = report.filename;
        weeklyReportBadge.style.display = idx === 0 ? 'inline-block' : 'none';
    }

    async function loadReports(datasetId) {
        try {
            const payload = await apiRequest(`/api/slocum/reporting/datasets/${encodeURIComponent(datasetId)}/reports`, 'GET');
            currentReports = payload?.reports || [];
            if (!currentReports.length) {
                weeklyReportContainer.style.display = 'none';
                noReportsContainer.style.display = 'block';
                return;
            }
            noReportsContainer.style.display = 'none';
            weeklyReportSelect.innerHTML = currentReports.map((r, i) =>
                `<option value="${i}">${escapeHtml(r.filename)}</option>`
            ).join('');
            weeklyReportSelect.selectedIndex = 0;
            renderWeeklyReportSelection();
            weeklyReportContainer.style.display = 'block';
        } catch (error) {
            weeklyReportContainer.style.display = 'none';
            noReportsContainer.style.display = 'block';
        }
    }

    // --- Loading ---
    async function loadDatasetInfo(datasetId) {
        currentDatasetId = datasetId;
        missionSpinner.style.display = 'inline-flex';
        try {
            const info = await apiRequest(`/api/slocum/datasets/${encodeURIComponent(datasetId)}/info`, 'GET');
            currentInfo = info;

            const parsed = info.parsed_dataset;
            if (parsed) {
                const mode = parsed.mode ? ` (${parsed.mode})` : '';
                parsedIdentity.textContent = `${parsed.glider_name} · start ${parsed.start_date} · deployment #${parsed.deployment_number}${mode}`;
                stMissionCode.textContent = `m${parsed.deployment_number}`;
            } else {
                parsedIdentity.textContent = 'Could not parse dataset id.';
                stMissionCode.textContent = '--';
            }

            editingMissionTitle.textContent = `Editing Overview for: ${datasetId}`;
            renderSensorTracker(info.sensor_tracker_deployment, info.sensor_tracker_instruments);
            renderBriefing(info);
            overviewFormContainer.style.display = 'block';
            reportResult.style.display = 'none';
            reportStatus.innerHTML = '';
            if (cacheInspectorStatus) {
                cacheInspectorStatus.textContent = `Ready to inspect mirror for ${datasetId}.`;
            }
            if (cacheInspectorTableBody) {
                cacheInspectorTableBody.innerHTML = '<tr><td colspan="7" class="text-muted small">No dataset inspection run yet.</td></tr>';
            }
            if (cacheMirrorMetaSummary) cacheMirrorMetaSummary.textContent = 'No mirror metadata loaded yet.';
            if (cacheProfileSummary) cacheProfileSummary.textContent = 'No profile summary loaded yet.';
            if (cacheOverageSummary) cacheOverageSummary.textContent = 'No overage cache summary loaded yet.';
            if (overageInspectorTableBody) {
                overageInspectorTableBody.innerHTML = '<tr><td colspan="7" class="text-muted small">No overage entries for this dataset.</td></tr>';
            }
            await loadReports(datasetId);
        } catch (error) {
            showToast(`Error loading dataset info: ${error.message}`, 'danger');
        } finally {
            missionSpinner.style.display = 'none';
        }
    }

    async function loadDatasets() {
        missionSpinner.style.display = 'inline-block';
        try {
            let active = [];
            let historical = [];
            try {
                active = await apiRequest('/api/slocum/available_datasets', 'GET') || [];
            } catch (_) {}
            try {
                historical = await apiRequest('/api/slocum/available_historical_datasets', 'GET') || [];
            } catch (_) {}

            missionSelect.innerHTML = '<option selected disabled>-- Select a Dataset --</option>';

            if (active.length > 0) {
                const activeGroup = document.createElement('optgroup');
                activeGroup.label = 'Active Missions';
                active.forEach(datasetId => {
                    const option = document.createElement('option');
                    option.value = datasetId;
                    option.textContent = datasetId;
                    activeGroup.appendChild(option);
                });
                missionSelect.appendChild(activeGroup);
            }

            if (historical.length > 0) {
                const historicalGroup = document.createElement('optgroup');
                historicalGroup.label = 'Historical Missions';
                historical.forEach(datasetId => {
                    const option = document.createElement('option');
                    option.value = datasetId;
                    option.textContent = datasetId;
                    historicalGroup.appendChild(option);
                });
                missionSelect.appendChild(historicalGroup);
            }

            if (active.length === 0 && historical.length === 0) {
                missionSelect.innerHTML = '<option selected disabled>No datasets available</option>';
            }
        } catch (error) {
            showToast(`Error loading datasets: ${error.message}`, 'danger');
            missionSelect.innerHTML = `<option selected disabled>Error: ${escapeHtml(error.message)}</option>`;
        } finally {
            missionSpinner.style.display = 'none';
        }
    }

    // --- Event handlers ---
    missionSelect.addEventListener('change', async () => {
        if (!missionSelect.value) return;
        await loadDatasetInfo(missionSelect.value);
    });

    syncSensorTrackerBtn.addEventListener('click', async () => {
        if (!currentDatasetId) return;
        sensorTrackerSyncStatus.textContent = 'Syncing...';
        syncSensorTrackerBtn.disabled = true;
        try {
            const force = forceMetadataSync?.checked ? '?force_refresh=true' : '';
            const info = await apiRequest(
                `/api/slocum/datasets/${encodeURIComponent(currentDatasetId)}/sensor-tracker/sync${force}`,
                'POST'
            );
            currentInfo = info;
            renderSensorTracker(info.sensor_tracker_deployment, info.sensor_tracker_instruments);
            sensorTrackerSyncStatus.textContent = 'Synced.';
            showToast('Sensor Tracker metadata synced.', 'success');
        } catch (error) {
            sensorTrackerSyncStatus.textContent = '';
            showToast(`Sync failed: ${error.message}`, 'danger');
        } finally {
            syncSensorTrackerBtn.disabled = false;
        }
    });

    if (saveSensorCardsBtn) {
        saveSensorCardsBtn.addEventListener('click', async () => {
            const deploymentId = currentInfo?.deployment?.id;
            if (!deploymentId) {
                showToast('Deployment metadata unavailable for this dataset.', 'warning');
                return;
            }
            const enabledSensorCards = getSelectedSensorCards();
            saveSensorCardsBtn.disabled = true;
            if (sensorCardsStatus) sensorCardsStatus.innerHTML = '<div class="alert alert-info py-2 mb-0">Saving...</div>';
            try {
                await apiRequest(`/api/slocum/deployments/${deploymentId}/sensor-cards`, 'PUT', {
                    enabled_sensor_cards: enabledSensorCards,
                });
                showToast('Sensor cards saved.', 'success');
                if (sensorCardsStatus) sensorCardsStatus.innerHTML = '<div class="alert alert-success py-2 mb-0">Saved.</div>';
                await loadDatasetInfo(currentDatasetId);
            } catch (error) {
                showToast(`Failed to save sensor cards: ${error.message}`, 'danger');
                if (sensorCardsStatus) {
                    sensorCardsStatus.innerHTML = `<div class="alert alert-danger py-2 mb-0">${escapeHtml(error.message)}</div>`;
                }
            } finally {
                setPlanActionsEnabled(Boolean(currentInfo?.deployment));
            }
        });
    }

    if (saveChecklistRefsBtn) {
        saveChecklistRefsBtn.addEventListener('click', async () => {
            const deploymentId = currentInfo?.deployment?.id;
            if (!deploymentId) {
                showToast('Deployment metadata unavailable for this dataset.', 'warning');
                return;
            }
            saveChecklistRefsBtn.disabled = true;
            if (checklistRefsStatus) checklistRefsStatus.innerHTML = '<div class="alert alert-info py-2 mb-0">Saving...</div>';
            try {
                await apiRequest(`/api/slocum/deployments/${deploymentId}/checklist-references`, 'PUT', {
                    checklist_reference_values: collectChecklistReferences(),
                });
                showToast('Checklist references saved.', 'success');
                if (checklistRefsStatus) checklistRefsStatus.innerHTML = '<div class="alert alert-success py-2 mb-0">Saved.</div>';
                await loadDatasetInfo(currentDatasetId);
            } catch (error) {
                showToast(`Failed to save checklist references: ${error.message}`, 'danger');
                if (checklistRefsStatus) {
                    checklistRefsStatus.innerHTML = `<div class="alert alert-danger py-2 mb-0">${escapeHtml(error.message)}</div>`;
                }
            } finally {
                setPlanActionsEnabled(Boolean(currentInfo?.deployment));
            }
        });
    }

    if (refBatteryPack) {
        refBatteryPack.addEventListener('change', () => {
            applyBatteryPackPreset(refBatteryPack.value, { overwrite: true });
        });
    }
    if (refGliderDepthClass) {
        refGliderDepthClass.addEventListener('change', () => {
            applyGliderDepthPreset(refGliderDepthClass.value, { overwrite: true });
        });
    }
    const refVacuumAtSurface = document.getElementById('refVacuumAtSurface');
    if (refVacuumAtSurface) {
        refVacuumAtSurface.addEventListener('change', () => {
            const maxVacuum = document.getElementById('refMaxVacuum');
            if (maxVacuum && (refVacuumAtSurface.value || '').trim() !== '') {
                maxVacuum.value = refVacuumAtSurface.value;
            }
        });
    }

    // Formal plan upload / remove
    if (uploadPlanBtn) {
        uploadPlanBtn.addEventListener('click', async () => {
            const deploymentId = currentInfo?.deployment?.id;
            const fileToUpload = documentUpload?.files?.[0];
            if (!deploymentId) {
                showToast('Deployment metadata unavailable for this dataset.', 'warning');
                return;
            }
            if (!fileToUpload) {
                showToast('Select a plan document to upload.', 'warning');
                return;
            }
            uploadPlanBtn.disabled = true;
            if (planUploadStatus) planUploadStatus.innerHTML = '<div class="alert alert-info py-2 mb-0">Uploading plan...</div>';
            const formData = new FormData();
            formData.append('file', fileToUpload);
            try {
                const response = await fetchWithAuth(`/api/slocum/deployments/${deploymentId}/plan/upload`, {
                    method: 'POST',
                    body: formData,
                });
                if (!response.ok) {
                    const err = await response.json().catch(() => ({}));
                    throw new Error(err.detail || 'Plan upload failed.');
                }
                const result = await response.json();
                showToast('Formal plan uploaded.', 'success');
                if (planUploadStatus) planUploadStatus.innerHTML = '<div class="alert alert-success py-2 mb-0">Plan uploaded.</div>';
                renderPlanDocument(result.file_url || result.document_url);
                await loadDatasetInfo(currentDatasetId);
            } catch (error) {
                showToast(`Plan upload failed: ${error.message}`, 'danger');
                if (planUploadStatus) planUploadStatus.innerHTML = `<div class="alert alert-danger py-2 mb-0">${escapeHtml(error.message)}</div>`;
            } finally {
                setPlanActionsEnabled(Boolean(currentInfo?.deployment));
            }
        });
    }

    if (removePlanBtn) {
        removePlanBtn.addEventListener('click', async () => {
            const deploymentId = currentInfo?.deployment?.id;
            if (!deploymentId) return;
            if (!confirm('Remove the current formal plan document?')) return;
            removePlanBtn.disabled = true;
            try {
                await apiRequest(`/api/slocum/deployments/${deploymentId}/plan`, 'DELETE');
                showToast('Plan document removed.', 'success');
                renderPlanDocument(null);
                await loadDatasetInfo(currentDatasetId);
            } catch (error) {
                showToast(`Failed to remove plan: ${error.message}`, 'danger');
            } finally {
                removePlanBtn.disabled = !currentInfo?.deployment;
            }
        });
    }

    // Comments
    addMissionNoteBtn.addEventListener('click', async () => {
        const deploymentId = currentInfo?.deployment?.id;
        const content = newMissionNoteContent.value.trim();
        if (!deploymentId) {
            showToast('Deployment metadata unavailable for this dataset.', 'warning');
            return;
        }
        if (!content) return;
        try {
            await apiRequest(`/api/slocum/deployments/${deploymentId}/notes`, 'POST', { content });
            newMissionNoteContent.value = '';
            await loadDatasetInfo(currentDatasetId);
        } catch (error) {
            showToast(`Error adding comment: ${error.message}`, 'danger');
        }
    });

    missionNotesList.addEventListener('click', async (e) => {
        const deleteBtn = e.target.closest('.delete-note-btn');
        if (!deleteBtn) return;
        if (!confirm('Delete this comment?')) return;
        try {
            await apiRequest(`/api/slocum/deployments/notes/${deleteBtn.dataset.noteId}`, 'DELETE');
            await loadDatasetInfo(currentDatasetId);
        } catch (error) {
            showToast(`Error deleting comment: ${error.message}`, 'danger');
        }
    });

    // Goals (modal add/edit, checkbox toggle, delete — same as WG)
    addGoalBtn.addEventListener('click', () => {
        if (!currentInfo?.deployment) {
            showToast('Deployment metadata unavailable for this dataset.', 'warning');
            return;
        }
        goalModalLabel.textContent = 'Add Mission Goal';
        goalIdInput.value = '';
        goalDescriptionInput.value = '';
        goalModal?.show();
    });

    saveGoalBtn.addEventListener('click', async () => {
        const deploymentId = currentInfo?.deployment?.id;
        const description = goalDescriptionInput.value.trim();
        if (!deploymentId || !description) return;
        try {
            if (goalIdInput.value) {
                await apiRequest(`/api/slocum/deployments/goals/${goalIdInput.value}`, 'PUT', { description });
            } else {
                await apiRequest(`/api/slocum/deployments/${deploymentId}/goals`, 'POST', { description });
            }
            goalModal?.hide();
            await loadDatasetInfo(currentDatasetId);
        } catch (error) {
            showToast(`Error saving goal: ${error.message}`, 'danger');
        }
    });

    missionGoalsList.addEventListener('click', async (e) => {
        const editBtn = e.target.closest('.edit-goal-btn');
        if (editBtn) {
            goalModalLabel.textContent = 'Edit Mission Goal';
            goalIdInput.value = editBtn.dataset.goalId;
            goalDescriptionInput.value = editBtn.dataset.description || '';
            goalModal?.show();
            return;
        }
        const deleteBtn = e.target.closest('.delete-goal-btn');
        if (deleteBtn) {
            if (!confirm('Delete this goal?')) return;
            try {
                await apiRequest(`/api/slocum/deployments/goals/${deleteBtn.dataset.goalId}`, 'DELETE');
                await loadDatasetInfo(currentDatasetId);
            } catch (error) {
                showToast(`Error deleting goal: ${error.message}`, 'danger');
            }
        }
    });

    missionGoalsList.addEventListener('change', async (e) => {
        const checkbox = e.target.closest('.mission-goal-checkbox');
        if (!checkbox) return;
        const deploymentId = currentInfo?.deployment?.id;
        if (!deploymentId) return;
        try {
            await apiRequest(
                `/api/slocum/deployments/${deploymentId}/goals/${checkbox.dataset.goalId}/toggle`,
                'POST',
                { is_completed: checkbox.checked }
            );
            await loadDatasetInfo(currentDatasetId);
        } catch (error) {
            checkbox.checked = !checkbox.checked;
            showToast(`Error updating goal: ${error.message}`, 'danger');
        }
    });

    // --- Cached Dataset Inspector ---
    const cacheInspectorHoursBack = document.getElementById('cacheInspectorHoursBack');
    const runCacheInspectorBtn = document.getElementById('runCacheInspectorBtn');
    const rebuildCtdMirrorBtn = document.getElementById('rebuildCtdMirrorBtn');
    const purgeOverageCacheBtn = document.getElementById('purgeOverageCacheBtn');
    const cacheInspectorStatus = document.getElementById('cacheInspectorStatus');
    const cacheInspectorTableBody = document.getElementById('cacheInspectorTableBody');
    const overageInspectorTableBody = document.getElementById('overageInspectorTableBody');
    const cacheMirrorMetaSummary = document.getElementById('cacheMirrorMetaSummary');
    const cacheProfileSummary = document.getElementById('cacheProfileSummary');
    const cacheOverageSummary = document.getElementById('cacheOverageSummary');

    const formatIsoOrDash = (value) => {
        if (!value) return '—';
        try {
            return formatUtcDateTime(value) || String(value);
        } catch (_) {
            return String(value);
        }
    };

    const summarizeColumnCounts = (bundleName, bundle) => {
        if (!bundle) return '—';
        if (bundleName === 'ctd') {
            const parts = [
                `science: ${bundle.science_rows ?? 0}`,
                `Temp: ${bundle.column_nonnull?.Temperature ?? 0}`,
                `Cond: ${bundle.column_nonnull?.Conductivity ?? 0}`,
                `Dens: ${bundle.column_nonnull?.Density ?? 0}`,
                `Depth: ${bundle.depth_nonnull ?? 0}`,
                `Pres: ${bundle.pressure_nonnull ?? 0}`,
            ];
            return parts.join(' · ');
        }
        const counts = bundle.column_nonnull || {};
        const preferred = ['MDepth', 'MBattery', 'Latitude', 'Longitude', 'MHeading'];
        const parts = preferred
            .filter((key) => key in counts)
            .map((key) => `${key}: ${counts[key]}`);
        if (parts.length) return parts.join(' · ');
        const entries = Object.entries(counts).slice(0, 5);
        return entries.length ? entries.map(([k, v]) => `${k}: ${v}`).join(' · ') : '—';
    };

    const renderCacheInspectorRows = (report) => {
        if (!cacheInspectorTableBody) return;
        const bundles = report?.bundles || {};
        const rows = ['dashboard', 'ctd', 'profile'].map((name) => {
            if (name === 'profile') {
                const profile = report?.profile || {};
                const err = profile.error;
                return {
                    bundle: 'profile (chart)',
                    mirrorRows: '—',
                    rowsInWindow: profile.points ?? 0,
                    keyNonNull: Object.entries(profile.ranges || {})
                        .map(([k, r]) => `${k}: ${r?.min != null ? Number(r.min).toFixed(2) : '—'}–${r?.max != null ? Number(r.max).toFixed(2) : '—'}`)
                        .join(' · ') || '—',
                    fileModified: '—',
                    dataRange: '—',
                    status: err ? `error: ${err}` : 'ok',
                };
            }
            const bundle = bundles[name] || {};
            const start = formatIsoOrDash(bundle.time_start);
            const end = formatIsoOrDash(bundle.time_end);
            return {
                bundle: name,
                mirrorRows: bundle.mirror_rows ?? 0,
                rowsInWindow: bundle.rows_in_window ?? 0,
                keyNonNull: summarizeColumnCounts(name, bundle),
                fileModified: formatIsoOrDash(bundle.file_modification_time),
                dataRange: bundle.time_start || bundle.time_end ? `${start} → ${end}` : '—',
                status: bundle.cached ? 'ok' : 'missing',
            };
        });

        cacheInspectorTableBody.innerHTML = rows.map((row) => `
            <tr>
                <td><code>${escapeHtml(row.bundle)}</code></td>
                <td>${escapeHtml(String(row.mirrorRows))}</td>
                <td>${escapeHtml(String(row.rowsInWindow))}</td>
                <td class="small">${escapeHtml(row.keyNonNull)}</td>
                <td>${escapeHtml(row.fileModified)}</td>
                <td class="small">${escapeHtml(row.dataRange)}</td>
                <td>${escapeHtml(row.status)}</td>
            </tr>
        `).join('');
    };

    const formatBytes = (value) => {
        const n = Number(value) || 0;
        if (n < 1024) return `${n} B`;
        if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
        return `${(n / (1024 * 1024)).toFixed(1)} MB`;
    };

    const renderOverageRows = (overage) => {
        if (!overageInspectorTableBody) return;
        const entries = Array.isArray(overage?.entries) ? overage.entries : [];
        if (!entries.length) {
            overageInspectorTableBody.innerHTML = '<tr><td colspan="7" class="text-muted small">No overage entries for this dataset.</td></tr>';
            return;
        }
        overageInspectorTableBody.innerHTML = entries.map((entry) => {
            const range = `${formatIsoOrDash(entry.normalized_start)} → ${formatIsoOrDash(entry.normalized_end)}`;
            const status = entry.expired ? 'expired' : (entry.exists ? 'valid' : 'missing parquet');
            return `
                <tr>
                    <td><code>${escapeHtml(entry.bundle || '—')}</code></td>
                    <td>${escapeHtml(String(entry.row_count ?? 0))}</td>
                    <td>${escapeHtml(formatBytes(entry.byte_size))}</td>
                    <td class="small">${escapeHtml(range)}</td>
                    <td>${escapeHtml(formatIsoOrDash(entry.created_at))}</td>
                    <td>${escapeHtml(formatIsoOrDash(entry.expires_at))}</td>
                    <td>${escapeHtml(status)}</td>
                </tr>
            `;
        }).join('');
    };

    const renderInspectorSummaries = (report) => {
        const meta = report?.meta || {};
        if (cacheMirrorMetaSummary) {
            cacheMirrorMetaSummary.textContent = [
                `dataset_id: ${report?.dataset_id || currentDatasetId || '—'}`,
                `is_historical: ${Boolean(report?.is_historical)}`,
                `last_sync_timestamp: ${formatIsoOrDash(meta.last_sync_timestamp)}`,
                `last_data_timestamp: ${formatIsoOrDash(meta.last_data_timestamp)}`,
                `archived: ${meta.archived ?? '—'}`,
            ].join('\n');
        }
        const profile = report?.profile || {};
        if (cacheProfileSummary) {
            const ranges = profile.ranges || {};
            cacheProfileSummary.textContent = [
                `profile points (science + depth): ${profile.points ?? 0}`,
                `temperature range: ${ranges.temperature?.min ?? '—'} → ${ranges.temperature?.max ?? '—'}`,
                `conductivity range: ${ranges.conductivity?.min ?? '—'} → ${ranges.conductivity?.max ?? '—'}`,
                `density range: ${ranges.density?.min ?? '—'} → ${ranges.density?.max ?? '—'}`,
                profile.error ? `error: ${profile.error}` : 'status: ok',
            ].join('\n');
        }
        const overage = report?.overage || {};
        if (cacheOverageSummary) {
            const stats = overage.stats || {};
            cacheOverageSummary.textContent = [
                `valid entries: ${overage.entry_count ?? 0}`,
                `expired entries: ${overage.expired_count ?? 0}`,
                `total bytes: ${formatBytes(overage.total_bytes)}`,
                `ttl_hours: ${overage.ttl_hours ?? 24}`,
                `hits/misses/fetches: ${stats.hits ?? 0}/${stats.misses ?? 0}/${stats.fetches ?? 0}`,
            ].join('\n');
        }
        renderOverageRows(overage);
    };

    async function runDatasetCacheInspection() {
        if (!currentDatasetId) {
            showToast('Select a dataset first.', 'warning');
            return;
        }
        const parsedHours = parseInt(cacheInspectorHoursBack?.value || '72', 10);
        const hoursBack = Number.isNaN(parsedHours) ? 72 : Math.max(1, Math.min(8760, parsedHours));
        if (cacheInspectorStatus) {
            cacheInspectorStatus.textContent = `Inspecting mirror for ${currentDatasetId} (last ${hoursBack}h)...`;
        }
        if (runCacheInspectorBtn) runCacheInspectorBtn.disabled = true;
        try {
            const report = await apiRequest(
                `/api/slocum/cache-inspect/${encodeURIComponent(currentDatasetId)}?hours_back=${hoursBack}`,
                'GET'
            );
            renderInspectorSummaries(report);
            renderCacheInspectorRows(report);
            if (cacheInspectorStatus) {
                const ctd = report?.bundles?.ctd || {};
                const profilePts = report?.profile?.points ?? 0;
                const overageCount = report?.overage?.entry_count ?? 0;
                cacheInspectorStatus.textContent =
                    `Inspection complete for ${currentDatasetId}. ` +
                    `CTD science rows in window: ${ctd.science_rows ?? 0}; profile points: ${profilePts}; ` +
                    `overage entries: ${overageCount}.`;
            }
        } catch (error) {
            if (cacheInspectorStatus) {
                cacheInspectorStatus.textContent = `Inspection failed: ${error.message}`;
            }
            showToast(`Cache inspection failed: ${error.message}`, 'danger');
        } finally {
            if (runCacheInspectorBtn) runCacheInspectorBtn.disabled = false;
        }
    }

    async function rebuildCtdMirror() {
        if (!currentDatasetId) {
            showToast('Select a dataset first.', 'warning');
            return;
        }
        if (!confirm(
            `Rebuild the CTD parquet mirror for ${currentDatasetId}?\n\n` +
            'This clears the cached CTD file and re-fetches from ERDDAP without 15-minute decimation ' +
            'so dive/climb profiles are preserved. It may take a minute.'
        )) {
            return;
        }
        const parsedHours = parseInt(cacheInspectorHoursBack?.value || '72', 10);
        const hoursBack = Number.isNaN(parsedHours) ? 72 : Math.max(1, Math.min(8760, parsedHours));
        if (cacheInspectorStatus) {
            cacheInspectorStatus.textContent = `Rebuilding undecimated CTD mirror for ${currentDatasetId}...`;
        }
        if (rebuildCtdMirrorBtn) rebuildCtdMirrorBtn.disabled = true;
        if (runCacheInspectorBtn) runCacheInspectorBtn.disabled = true;
        try {
            const summary = await apiRequest(
                `/api/slocum/mirror/${encodeURIComponent(currentDatasetId)}/sync?rebuild_ctd=true&hours_back=${hoursBack}`,
                'POST'
            );
            const ctdBundle = summary?.bundles?.ctd || {};
            showToast(
                `CTD rebuilt: ${ctdBundle.fetched_rows ?? ctdBundle.rows ?? 0} rows fetched.`,
                'success'
            );
            await runDatasetCacheInspection();
        } catch (error) {
            if (cacheInspectorStatus) {
                cacheInspectorStatus.textContent = `CTD rebuild failed: ${error.message}`;
            }
            showToast(`CTD rebuild failed: ${error.message}`, 'danger');
        } finally {
            if (rebuildCtdMirrorBtn) rebuildCtdMirrorBtn.disabled = false;
            if (runCacheInspectorBtn) runCacheInspectorBtn.disabled = false;
        }
    }

    async function purgeOverageCache() {
        if (!currentDatasetId) {
            showToast('Select a dataset first.', 'warning');
            return;
        }
        if (!confirm(
            `Purge temporary overage cache entries for ${currentDatasetId}?\n\n` +
            'This removes valid and expired 24h overage files for the dataset. The rolling 72h mirror is untouched.'
        )) {
            return;
        }
        if (purgeOverageCacheBtn) purgeOverageCacheBtn.disabled = true;
        try {
            const summary = await apiRequest(
                `/api/slocum/overage-cache/purge?dataset_id=${encodeURIComponent(currentDatasetId)}&force_all=true`,
                'POST'
            );
            showToast(`Removed ${summary?.removed_files ?? 0} overage file(s).`, 'success');
            await runDatasetCacheInspection();
        } catch (error) {
            showToast(`Overage purge failed: ${error.message}`, 'danger');
        } finally {
            if (purgeOverageCacheBtn) purgeOverageCacheBtn.disabled = false;
        }
    }

    if (runCacheInspectorBtn) {
        runCacheInspectorBtn.addEventListener('click', runDatasetCacheInspection);
    }
    if (rebuildCtdMirrorBtn) {
        rebuildCtdMirrorBtn.addEventListener('click', rebuildCtdMirror);
    }
    if (purgeOverageCacheBtn) {
        purgeOverageCacheBtn.addEventListener('click', purgeOverageCache);
    }

    // Reports
    weeklyReportSelect.addEventListener('change', renderWeeklyReportSelection);

    generateReportBtn.addEventListener('click', async () => {
        if (!currentDatasetId) return;
        reportGenerationSpinner.style.display = 'inline-flex';
        generateReportBtn.disabled = true;
        reportStatus.innerHTML = '';
        reportResult.style.display = 'none';
        try {
            const result = await apiRequest(
                `/api/slocum/reporting/datasets/${encodeURIComponent(currentDatasetId)}/generate-weekly-report`,
                'POST'
            );
            reportDownloadLink.href = result.report_url;
            reportResult.style.display = 'block';
            showToast('Weekly report generated.', 'success');
            await loadReports(currentDatasetId);
        } catch (error) {
            reportStatus.innerHTML = `<div class="alert alert-danger">${escapeHtml(error.message)}</div>`;
        } finally {
            reportGenerationSpinner.style.display = 'none';
            generateReportBtn.disabled = false;
        }
    });

    await loadChecklistPresets();
    await loadDatasets();
});
