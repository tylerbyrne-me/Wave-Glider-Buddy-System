/**
 * @file wg_vm4.js
 * @description WG-VM4 Offload Log Management
 * 
 * Handles station metadata search and offload log submission for WG-VM4 stations
 */

import { apiRequest, showToast } from '/static/js/api.js';

/**
 * Initialize the WG-VM4 offload section
 */
export function initializeWgVm4OffloadSection() {
    // DOM element getters
    const stationIdSearchInput = document.getElementById('stationIdSearch');
    const fetchStationDataBtn = document.getElementById('fetchStationDataBtn');
    const stationMetadataDisplay = document.getElementById('stationMetadataDisplay');
    const stationMetadataError = document.getElementById('stationMetadataError');
    const offloadLogFormFieldsContainer = document.getElementById('offloadLogFormFieldsContainer');
    const wgVm4OffloadForm = document.getElementById('wgVm4OffloadForm');
    const submitOffloadLogBtn = document.getElementById('submitOffloadLogBtn');
    const offloadSubmissionStatus = document.getElementById('offloadSubmissionStatus');
    const stationSearchResultsContainer = document.getElementById('stationSearchResults');
    if (!stationIdSearchInput || !fetchStationDataBtn || !wgVm4OffloadForm || !offloadLogFormFieldsContainer) return;
    if (wgVm4OffloadForm.dataset.vm4Initialized === 'true') return;
    wgVm4OffloadForm.dataset.vm4Initialized = 'true';

    let currentStationData = null; // To store fetched station metadata
    let searchTimeout; // For debouncing search

    /**
     * Search for stations by query string
     * @param {string} query - Search query (minimum 2 characters)
     */
    async function searchStations(query) {
        if (!stationSearchResultsContainer) return;
        if (!query || query.length < 2) { // Min 2 chars to search
            stationSearchResultsContainer.innerHTML = '';
            stationSearchResultsContainer.style.display = 'none';
            return;
        }
        try {
            const stations = await apiRequest(`/api/station_metadata/?query=${encodeURIComponent(query)}&limit=5`, 'GET');
            stationSearchResultsContainer.innerHTML = '';
            if (stations.length > 0) {
                stations.forEach(station => {
                    const item = document.createElement('a');
                    item.classList.add('list-group-item', 'list-group-item-action', 'py-1');
                    item.href = '#';
                    item.textContent = station.station_id;
                    item.addEventListener('click', (e) => {
                        e.preventDefault();
                        stationIdSearchInput.value = station.station_id;
                        stationSearchResultsContainer.style.display = 'none';
                        fetchStationMetadata(station.station_id);
                    });
                    stationSearchResultsContainer.appendChild(item);
                });
                stationSearchResultsContainer.style.display = 'block';
            } else {
                stationSearchResultsContainer.style.display = 'none';
            }
        } catch (error) {
            showToast(`Error searching stations: ${error.message}`, 'danger');
            stationSearchResultsContainer.style.display = 'none';
        }
    }

    /**
     * Fetch metadata for a specific station
     * @param {string} stationId - Station identifier
     */
    async function fetchStationMetadata(stationId) {
        if (!stationId) return;
        if (stationMetadataError) stationMetadataError.style.display = 'none';
        if (stationMetadataDisplay) stationMetadataDisplay.style.display = 'none';
        const metaLastLogStatusClear = document.getElementById('metaLastLogStatus');
        if (metaLastLogStatusClear) metaLastLogStatusClear.textContent = 'N/A';
        currentStationData = null;
        if(submitOffloadLogBtn) submitOffloadLogBtn.disabled = true;

        try {
            currentStationData = await apiRequest(`/api/station_metadata/${stationId}`, 'GET');
            const flagState = await apiRequest(`/api/station_metadata/${stationId}/flag_state`, 'GET');
            currentStationData.station_flag_state = flagState;
            displayStationMetadata(currentStationData);
            buildOffloadLogFormFields(currentStationData);
            if(submitOffloadLogBtn) submitOffloadLogBtn.disabled = false;
        } catch (error) {
            showToast(`Error fetching station metadata: ${error.message}`, 'danger');
            if (stationMetadataError) {
                stationMetadataError.textContent = `Error: ${error.message}`;
                stationMetadataError.style.display = 'block';
            }
        }
    }

    function toUtcDisplay(value) {
        if (!value) return 'N/A';
        const parsed = new Date(value);
        if (Number.isNaN(parsed.valueOf())) return String(value);
        return parsed.toISOString().replace('T', ' ').replace('.000Z', ' UTC');
    }

    function formatUtcMinutePrecision(value) {
        const parsed = new Date(value);
        if (Number.isNaN(parsed.valueOf())) return '';
        return parsed.toISOString().slice(0, 16).replace('T', ' ');
    }

    /** Matches server `_offload_log_sort_key`: end → start → log row time. */
    function offloadLogEffectiveTsMs(log) {
        const raw = log.offload_end_time_utc ?? log.offload_start_time_utc ?? log.log_timestamp_utc;
        if (!raw) return Number.NEGATIVE_INFINITY;
        const ms = new Date(raw).valueOf();
        return Number.isNaN(ms) ? Number.NEGATIVE_INFINITY : ms;
    }

    function pickLatestOffloadLog(logs) {
        if (!logs || logs.length === 0) return null;
        return logs.reduce((best, log) => {
            const ts = offloadLogEffectiveTsMs(log);
            const bestTs = offloadLogEffectiveTsMs(best);
            if (ts > bestTs) return log;
            if (ts < bestTs) return best;
            const id = log.id ?? 0;
            const bestId = best.id ?? 0;
            return id >= bestId ? log : best;
        });
    }

    function deriveLastLogTimeAndStatus(data) {
        const latest = pickLatestOffloadLog(data.offload_logs);
        const timeRaw = latest?.log_timestamp_utc ?? data.last_offload_timestamp_utc;
        const override = String(data.display_status_override || '').toUpperCase();
        if (override === 'SKIPPED') {
            return { timeRaw, statusLabel: 'Skipped' };
        }
        const was = latest ? latest.was_offloaded : data.was_last_offload_successful;
        if (was === true) return { timeRaw, statusLabel: 'Offloaded' };
        if (was === false) return { timeRaw, statusLabel: 'Failed' };
        if (timeRaw) return { timeRaw, statusLabel: 'Unknown' };
        return { timeRaw: null, statusLabel: 'N/A' };
    }

    function displayStationMetadata(data) {
        if (!data) return;
        const metaSerial = document.getElementById('metaSerial');
        const metaModemAddr = document.getElementById('metaModemAddr');
        const metaDepth = document.getElementById('metaDepth');
        const metaWp = document.getElementById('metaWp');
        const metaLastOffload = document.getElementById('metaLastOffload');
        const metaSettings = document.getElementById('metaSettings');
        const metaLastLogStatus = document.getElementById('metaLastLogStatus');
        if (metaSerial) metaSerial.textContent = data.serial_number || 'N/A';
        if (metaModemAddr) metaModemAddr.textContent = data.modem_address !== null ? data.modem_address : 'N/A';
        if (metaDepth) metaDepth.textContent = data.bottom_depth_m !== null ? data.bottom_depth_m : 'N/A';
        if (metaWp) metaWp.textContent = data.waypoint_number || 'N/A';
        const { timeRaw, statusLabel } = deriveLastLogTimeAndStatus(data);
        const metaLastOffloadTimestampElement = document.getElementById('metaLastOffloadTimestamp');
        if (metaLastOffloadTimestampElement) metaLastOffloadTimestampElement.textContent = toUtcDisplay(timeRaw);
        if (metaLastLogStatus) metaLastLogStatus.textContent = statusLabel;
        if (metaLastOffload) metaLastOffload.textContent = data.last_offload_by_glider || 'N/A';
        if (metaSettings) metaSettings.textContent = data.station_settings || 'N/A';
        const isFlagged = Boolean(data.station_flag_state?.is_flagged);
        const metaLastOffloadEl = document.getElementById('metaLastOffload');
        if (metaLastOffloadEl && isFlagged) {
            metaLastOffloadEl.textContent = `${metaLastOffloadEl.textContent} [FLAGGED]`;
        }
        
        const notesContainer = document.getElementById('metaNotesContainer');
        const notesSpan = document.getElementById('metaNotes');
        const otnMetadata = data.otn_metadata ?? data.notes;
        if (otnMetadata && notesContainer && notesSpan) {
            notesSpan.textContent = otnMetadata;
            notesContainer.style.display = 'block';
        } else if (notesContainer) {
            notesContainer.style.display = 'none';
        }
        if (stationMetadataDisplay) stationMetadataDisplay.style.display = 'block';
    }

    stationIdSearchInput.addEventListener('keyup', (e) => {
        clearTimeout(searchTimeout);
        if (e.key === 'Enter') {
            fetchStationMetadata(stationIdSearchInput.value.trim());
            if(stationSearchResultsContainer) stationSearchResultsContainer.style.display = 'none';
        } else {
            searchTimeout = setTimeout(() => {
                searchStations(stationIdSearchInput.value.trim());
            }, 300);
        }
    });
    document.addEventListener('click', function(event) {
        if (stationSearchResultsContainer && stationIdSearchInput &&
            !stationIdSearchInput.contains(event.target) && 
            !stationSearchResultsContainer.contains(event.target)) {
            stationSearchResultsContainer.style.display = 'none';
        }
    });

    fetchStationDataBtn.addEventListener('click', () => {
        fetchStationMetadata(stationIdSearchInput.value.trim());
        if(stationSearchResultsContainer) stationSearchResultsContainer.style.display = 'none';
    });

    // --- Form Building & Submission ---
    function buildOffloadLogFormFields(stationData) { // stationData can be null to clear/init form
        if(!offloadLogFormFieldsContainer) return;
        offloadLogFormFieldsContainer.innerHTML = ''; 

        const formSchema = { 
            sections: [
                {
                    id: "offload_parameters_ui", 
                    title: "Offload Parameters & Timings",
                    items: [
                        {
                            id: "arrival_date_log",
                            label: "Arrival Date/Time (UTC)",
                            item_type: "datetime-local",
                            required: false,
                            tooltip: "If different than Time first command sent UTC",
                        },
                        {id: "distance_cmd_sent_m_log", label: "Distance when command sent (m)", item_type: "text_input", placeholder: "e.g., 300", required: true},
                        {id: "time_first_cmd_sent_utc_log", label: "Time first command sent (UTC)", item_type: "datetime-local", required: true},
                        {id: "start_time_remote_offload_utc_log", label: "Start Time - remote offload (UTC)", item_type: "datetime-local", required: true},
                        {id: "end_time_offload_completed_utc_log", label: "End Time - Offload completed (UTC)", item_type: "datetime-local", required: true},
                        {
                            id: "departure_date_log",
                            label: "Departure Date/Time (UTC)",
                            item_type: "datetime-local",
                            required: false,
                            tooltip: "If different than End Time - Offload Completed UTC",
                        },
                    ]
                },
                {
                    id: "offload_results_ui",
                    title: "Offload Results & Notes",
                    items: [
                        {id: "offloaded_status_log", label: "Offloaded", item_type: "dropdown", options: ["Yes", "No", "Partial"], required: true},
                        {id: "comments_log", label: "Comments", item_type: "text_area", placeholder: "Offload details..."},
                        {id: "vrl_file_name_log", label: "VRL File Name", item_type: "text_input", placeholder: "e.g., VR4-UWM_XXXXXX.vrl"},
                        {id: "vrl_file_size_log", label: "VRL File Size (bytes)", item_type: "text_input", placeholder: "e.g., 5161"},
                        {id: "flag_station_for_season_log", label: "Flag station for season", item_type: "dropdown", options: ["No", "Yes"], required: false},
                        {id: "flag_note_log", label: "Flag note", item_type: "text_area", placeholder: "Reason this station needs attention"},
                        {id: "otn_metadata_notes_log", label: "OTN Metadata Notes", item_type: "text_area", placeholder: "Notes for OTN..."},
                    ]
                }
            ]
        };

        formSchema.sections.forEach(section => {
            section.items.forEach(item => {
                const formGroup = document.createElement('div');
                formGroup.classList.add('mb-2', 'row');

                const label = document.createElement('label');
                label.htmlFor = item.id;
                label.textContent = item.label + (item.required ? '*' : '');
                label.classList.add('col-sm-4', 'col-form-label', 'col-form-label-sm');
                if (item.tooltip) {
                    label.title = item.tooltip;
                    label.setAttribute('data-bs-toggle', 'tooltip');
                    label.setAttribute('data-bs-placement', 'top');
                }
                formGroup.appendChild(label);

                const inputContainer = document.createElement('div');
                inputContainer.classList.add('col-sm-8');

                let inputElement;
                if (item.item_type === 'datetime-local') {
                    inputElement = document.createElement('input');
                    inputElement.type = 'text';
                    inputElement.inputMode = 'numeric';
                    inputElement.placeholder = 'YYYY-MM-DD HH:mm';
                    inputElement.pattern = '^\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}$';
                    inputElement.title = 'Use UTC 24hr format: YYYY-MM-DD HH:mm';
                } else if (item.item_type === 'text_input') {
                    inputElement = document.createElement('input');
                    inputElement.type = 'text';
                } else if (item.item_type === 'text_area') {
                    inputElement = document.createElement('textarea');
                    inputElement.rows = 2;
                } else if (item.item_type === 'dropdown') {
                    inputElement = document.createElement('select');
                    item.options.forEach(opt => {
                        const option = document.createElement('option');
                        option.value = opt;
                        option.textContent = opt;
                        inputElement.appendChild(option);
                    });
                } else if (item.item_type === 'static_text') {
                    inputElement = document.createElement('p');
                    inputElement.textContent = item.value || 'N/A';
                    inputElement.classList.add('form-control-plaintext', 'form-control-sm', 'mb-0', 'pt-1');
                }

                if (inputElement && item.item_type !== 'static_text') {
                    inputElement.id = item.id;
                    inputElement.name = item.id;
                    inputElement.classList.add('form-control', 'form-control-sm');
                    if (item.placeholder) inputElement.placeholder = item.placeholder;
                    if (item.required) inputElement.required = true;
                }

                if (inputElement && item.item_type === 'datetime-local') {
                    const inputGroup = document.createElement('div');
                    inputGroup.classList.add('input-group', 'input-group-sm');
                    inputGroup.appendChild(inputElement);
                    const nowBtn = document.createElement('button');
                    nowBtn.type = 'button';
                    nowBtn.classList.add('btn', 'btn-outline-secondary', 'vm4-now-btn');
                    nowBtn.textContent = 'Now';
                    nowBtn.dataset.targetInputId = item.id;
                    inputGroup.appendChild(nowBtn);
                    inputContainer.appendChild(inputGroup);
                } else if (inputElement) {
                    inputContainer.appendChild(inputElement);
                }
                formGroup.appendChild(inputContainer);
                offloadLogFormFieldsContainer.appendChild(formGroup);
            });
        });
        if (window.bootstrap?.Tooltip) {
            offloadLogFormFieldsContainer
                .querySelectorAll('[data-bs-toggle="tooltip"]')
                .forEach((el) => new window.bootstrap.Tooltip(el));
        }
        updateConditionalOffloadRequirements();
    }

    function updateConditionalOffloadRequirements() {
        const offloadedStatusEl = document.getElementById('offloaded_status_log');
        const startTimeEl = document.getElementById('start_time_remote_offload_utc_log');
        const endTimeEl = document.getElementById('end_time_offload_completed_utc_log');
        if (!offloadedStatusEl || !startTimeEl || !endTimeEl) return;

        const isOffloadFailed = String(offloadedStatusEl.value || '').trim().toLowerCase() === 'no';
        startTimeEl.required = !isOffloadFailed;
        endTimeEl.required = !isOffloadFailed;
    }

    function getIsoFromUtcDatetimeLocal(value) {
        if (!value) return null;
        const normalized = String(value).trim().replace(' ', 'T');
        if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(normalized)) return null;
        const parsed = new Date(`${normalized}Z`);
        if (Number.isNaN(parsed.valueOf())) return null;
        return parsed.toISOString();
    }

    function getUtcNowDatetimeLocalValue() {
        return formatUtcMinutePrecision(new Date().toISOString());
    }

    function toNullableTrimmed(value) {
        const normalized = typeof value === 'string' ? value.trim() : '';
        return normalized || null;
    }

    function buildUserNotes(baseComments, offloadedStatus) {
        const notes = [];
        if (baseComments) notes.push(baseComments);
        if (offloadedStatus === 'Partial') notes.push('[VM4] Marked Partial in dashboard form.');
        return notes.length ? notes.join('\n\n') : null;
    }

    wgVm4OffloadForm.addEventListener('submit', async function(event) {
        event.preventDefault();
        if(offloadSubmissionStatus) offloadSubmissionStatus.innerHTML = '<div class="alert alert-info">Submitting log...</div>';
        if(submitOffloadLogBtn) submitOffloadLogBtn.disabled = true;

        if (!currentStationData || !currentStationData.station_id) {
            if(offloadSubmissionStatus) offloadSubmissionStatus.innerHTML = '<div class="alert alert-danger">No station data loaded. Please load station first.</div>';
            if(submitOffloadLogBtn) submitOffloadLogBtn.disabled = false;
            return;
        }

        const formData = new FormData(wgVm4OffloadForm);
        const missionIdForSheet = (document.body.dataset.missionId || '').trim();
        const offloadedStatus = String(formData.get('offloaded_status_log') || '').trim();
        const normalizedWasOffloaded = offloadedStatus === 'Yes' ? true : offloadedStatus === 'No' || offloadedStatus === 'Partial' ? false : null;
        const notes = buildUserNotes(toNullableTrimmed(formData.get('comments_log')), offloadedStatus);
        const otnMetadata = toNullableTrimmed(formData.get('otn_metadata_notes_log'));
        const shouldFlagStation = String(formData.get('flag_station_for_season_log') || '').trim() === 'Yes';
        const flagNote = toNullableTrimmed(formData.get('flag_note_log'));
        const distanceRaw = String(formData.get('distance_cmd_sent_m_log') || '').trim();
        const parsedDistance = distanceRaw ? Number(distanceRaw) : null;
        const payload = {
            arrival_date: getIsoFromUtcDatetimeLocal(formData.get('arrival_date_log')),
            distance_command_sent_m: Number.isNaN(parsedDistance) ? null : parsedDistance,
            time_first_command_sent_utc: getIsoFromUtcDatetimeLocal(formData.get('time_first_cmd_sent_utc_log')),
            offload_start_time_utc: getIsoFromUtcDatetimeLocal(formData.get('start_time_remote_offload_utc_log')),
            offload_end_time_utc: getIsoFromUtcDatetimeLocal(formData.get('end_time_offload_completed_utc_log')),
            departure_date: getIsoFromUtcDatetimeLocal(formData.get('departure_date_log')),
            was_offloaded: normalizedWasOffloaded,
            vrl_file_name: toNullableTrimmed(formData.get('vrl_file_name_log')),
            offload_notes_file_size: toNullableTrimmed(formData.get('vrl_file_size_log')),
            user_notes: notes,
            ...(missionIdForSheet ? { mission_id: missionIdForSheet } : {}),
        };
        Object.keys(payload).forEach((key) => {
            if (payload[key] === null || payload[key] === '') delete payload[key];
        });

        try {
            await apiRequest(`/api/station_metadata/${encodeURIComponent(currentStationData.station_id)}/offload_logs/`, 'POST', payload);
            if (otnMetadata) {
                await apiRequest(
                    `/api/station_metadata/${encodeURIComponent(currentStationData.station_id)}`,
                    'PUT',
                    { otn_metadata: otnMetadata }
                );
            }
            if (shouldFlagStation) {
                await apiRequest(
                    `/api/station_metadata/${encodeURIComponent(currentStationData.station_id)}/flag`,
                    'POST',
                    { is_flagged: true, note: flagNote }
                );
            }
            const missionId = missionIdForSheet;
            if (missionId) {
                await apiRequest(
                    `/api/station_metadata/${encodeURIComponent(currentStationData.station_id)}`,
                    'PUT',
                    { last_offload_by_glider: missionId }
                );
            }
            showToast(`Log for station ${currentStationData.station_id} submitted successfully!`, 'success');
            if(offloadSubmissionStatus) offloadSubmissionStatus.innerHTML = `<div class="alert alert-success">Log for station ${currentStationData.station_id} submitted successfully!</div>`;
            wgVm4OffloadForm.reset();
            if(stationMetadataDisplay) stationMetadataDisplay.style.display = 'none';
            currentStationData = null;
            if(submitOffloadLogBtn) submitOffloadLogBtn.disabled = true;
            if(stationIdSearchInput) stationIdSearchInput.value = '';
            buildOffloadLogFormFields(null); 
        } catch (error) {
            showToast(`Error submitting offload log: ${error.message}`, 'danger');
            if(offloadSubmissionStatus) offloadSubmissionStatus.innerHTML = `<div class="alert alert-danger">Submission failed: ${error.message}</div>`;
        } finally {
            if(submitOffloadLogBtn) submitOffloadLogBtn.disabled = !currentStationData; 
        }
    });

    wgVm4OffloadForm.addEventListener('click', function(event) {
        const nowBtn = event.target.closest('.vm4-now-btn');
        if (!nowBtn) return;
        const targetInputId = nowBtn.dataset.targetInputId;
        if (!targetInputId) return;
        const input = document.getElementById(targetInputId);
        if (!input) return;
        input.value = getUtcNowDatetimeLocalValue();
        input.dispatchEvent(new Event('change', { bubbles: true }));
    });
    wgVm4OffloadForm.addEventListener('change', function(event) {
        if (event.target && event.target.id === 'offloaded_status_log') {
            updateConditionalOffloadRequirements();
        }
    });
    // Initial call to clear/setup form fields
    buildOffloadLogFormFields(null);
}

// Note: The call to initializeWgVm4OffloadSection() will be made from dashboard.js
// when the WG-VM4 detail view is activated.
// Do NOT use DOMContentLoaded here if this script is loaded after dashboard.js
// and relies on dashboard.js to call its initialization function.
