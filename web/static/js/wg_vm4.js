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

    let currentStationData = null; // To store fetched station metadata
    let searchTimeout; // For debouncing search

    /**
     * Search for stations by query string
     * @param {string} query - Search query (minimum 2 characters)
     */
    async function searchStations(query) {
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
        stationMetadataError.style.display = 'none';
        stationMetadataDisplay.style.display = 'none';
        currentStationData = null;
        if(submitOffloadLogBtn) submitOffloadLogBtn.disabled = true;

        try {
            currentStationData = await apiRequest(`/api/station_metadata/${stationId}`, 'GET');
            displayStationMetadata(currentStationData);
            buildOffloadLogFormFields(currentStationData);
            if(submitOffloadLogBtn) submitOffloadLogBtn.disabled = false;
        } catch (error) {
            showToast(`Error fetching station metadata: ${error.message}`, 'danger');
            stationMetadataError.textContent = `Error: ${error.message}`;
            stationMetadataError.style.display = 'block';
        }
    }

    function displayStationMetadata(data) {
        if (!data) return;
        document.getElementById('metaSerial').textContent = data.serial_number || 'N/A';
        document.getElementById('metaModemAddr').textContent = data.modem_address !== null ? data.modem_address : 'N/A';
        document.getElementById('metaDepth').textContent = data.bottom_depth_m !== null ? data.bottom_depth_m : 'N/A';
        document.getElementById('metaWp').textContent = data.waypoint_number || 'N/A';
                // Display last_offload_timestamp_utc if available in station metadata
        const metaLastOffloadTimestampElement = document.getElementById('metaLastOffloadTimestamp');
        if (metaLastOffloadTimestampElement) { // Check if the element exists
            metaLastOffloadTimestampElement.textContent = data.last_offload_timestamp_utc ?
                new Date(data.last_offload_timestamp_utc).toLocaleString() : 'N/A';
        }
        document.getElementById('metaLastOffload').textContent = data.last_offload_by_glider || 'N/A';
        document.getElementById('metaSettings').textContent = data.station_settings || 'N/A';
        document.getElementById('metaLastOffload').textContent = data.last_offload_by_glider || 'N/A';
        document.getElementById('metaSettings').textContent = data.station_settings || 'N/A';
        
        const notesContainer = document.getElementById('metaNotesContainer');
        const notesSpan = document.getElementById('metaNotes');
        if (data.notes) {
            notesSpan.textContent = data.notes;
            notesContainer.style.display = 'block';
        } else {
            notesContainer.style.display = 'none';
        }
        stationMetadataDisplay.style.display = 'block';
    }

    if (stationIdSearchInput) {
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
    }

    if (fetchStationDataBtn) {
        fetchStationDataBtn.addEventListener('click', () => {
            if(stationIdSearchInput) fetchStationMetadata(stationIdSearchInput.value.trim());
            if(stationSearchResultsContainer) stationSearchResultsContainer.style.display = 'none';
        });
    }

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
                        {id: "arrival_date_log", label: "Arrival Date/Time (UTC)", item_type: "datetime-local", required: true},
                        {id: "distance_cmd_sent_m_log", label: "Distance when command sent (m)", item_type: "text_input", placeholder: "e.g., 300", required: true},
                        {id: "time_first_cmd_sent_utc_log", label: "Time first command sent (UTC)", item_type: "datetime-local", required: true},
                        {id: "start_time_remote_offload_utc_log", label: "Start Time - remote offload (UTC)", item_type: "datetime-local", required: true},
                        {id: "end_time_offload_completed_utc_log", label: "End Time - Offload completed (UTC)", item_type: "datetime-local", required: true},
                        {id: "departure_date_log", label: "Departure Date/Time (UTC)", item_type: "datetime-local", required: true},
                    ]
                },
                {
                    id: "offload_results_ui",
                    title: "Offload Results & Notes",
                    items: [
                        {id: "offloaded_status_log", label: "Offloaded", item_type: "dropdown", options: ["Yes", "No", "Partial"], required: true},
                        {id: "elapsed_time_offload_log_display", label: "Elapsed Time for Offload", item_type: "static_text", value: "N/A"},
                        {id: "total_time_station_log_display", label: "Total time at Station", item_type: "static_text", value: "N/A"},
                        {id: "comments_log", label: "Comments", item_type: "text_area", placeholder: "Offload details..."},
                        {id: "vrl_file_name_log", label: "VRL File Name", item_type: "text_input", placeholder: "e.g., VR4-UWM_XXXXXX.vrl"},
                        {id: "vrl_file_size_log", label: "VRL File Size (bytes)", item_type: "text_input", placeholder: "e.g., 5161"},
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
                formGroup.appendChild(label);

                const inputContainer = document.createElement('div');
                inputContainer.classList.add('col-sm-8');

                let inputElement;
                if (item.item_type === 'datetime-local') {
                    inputElement = document.createElement('input');
                    inputElement.type = 'datetime-local';
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
                
                if (inputElement) inputContainer.appendChild(inputElement);
                formGroup.appendChild(inputContainer);
                offloadLogFormFieldsContainer.appendChild(formGroup);
            });
        });
        addTimeCalculationListeners();
    }

    function calculateTimeDifference(startStr, endStr) {
        if (!startStr || !endStr) return "N/A";
        const startDate = new Date(startStr);
        const endDate = new Date(endStr);
        if (isNaN(startDate) || isNaN(endDate) || endDate < startDate) return "Invalid dates";

        let diffMs = endDate - startDate;
        const hours = Math.floor(diffMs / 3600000);
        diffMs %= 3600000;
        const minutes = Math.floor(diffMs / 60000);
        return `${hours}h ${minutes}m`;
    }

    function addTimeCalculationListeners() {
        const startTimeOffload = document.getElementById('start_time_remote_offload_utc_log');
        const endTimeOffload = document.getElementById('end_time_offload_completed_utc_log');
        const arrivalTime = document.getElementById('arrival_date_log');
        const departureTime = document.getElementById('departure_date_log');

        const elapsedDisplay = document.getElementById('elapsed_time_offload_log_display');
        const totalTimeDisplay = document.getElementById('total_time_station_log_display');

        function updateElapsed() {
            if (elapsedDisplay) elapsedDisplay.textContent = calculateTimeDifference(startTimeOffload?.value, endTimeOffload?.value);
        }
        function updateTotal() {
            if (totalTimeDisplay) totalTimeDisplay.textContent = calculateTimeDifference(arrivalTime?.value, departureTime?.value);
        }

        [startTimeOffload, endTimeOffload].forEach(el => el?.addEventListener('change', updateElapsed));
        [arrivalTime, departureTime].forEach(el => el?.addEventListener('change', updateTotal));
    }

    if (wgVm4OffloadForm) {
        wgVm4OffloadForm.addEventListener('submit', async function(event) {
            event.preventDefault();
            if(offloadSubmissionStatus) offloadSubmissionStatus.innerHTML = '<div class="alert alert-info">Submitting log...</div>';
            if(submitOffloadLogBtn) submitOffloadLogBtn.disabled = true;

            if (!currentStationData) {
                if(offloadSubmissionStatus) offloadSubmissionStatus.innerHTML = '<div class="alert alert-danger">No station data loaded. Please load station first.</div>';
                if(submitOffloadLogBtn) submitOffloadLogBtn.disabled = false;
                return;
            }

            const formData = new FormData(wgVm4OffloadForm);
            const missionId = document.body.dataset.missionId;
            // Ensure fetchCurrentUserDetailsAndUpdateUI is available (e.g., from dashboard.js)
            const currentUser = typeof fetchCurrentUserDetailsAndUpdateUI === 'function' ? await fetchCurrentUserDetailsAndUpdateUI() : null;
            const username = currentUser ? currentUser.username : 'unknown_user';

            const sections_data = [
                { 
                    id: "station_identification", title: "Station Identification", items: [
                        {id: "station_id_for_offload", label: "Station ID", item_type: "autofilled_value", value: currentStationData.station_id},
                        {id: "serial_number_log", label: "Serial Number", item_type: "autofilled_value", value: currentStationData.serial_number},
                        {id: "modem_address_log", label: "Modem Address", item_type: "autofilled_value", value: String(currentStationData.modem_address)},
                        {id: "bottom_depth_m_log", label: "Bottom Depth (m)", item_type: "autofilled_value", value: String(currentStationData.bottom_depth_m)},
                        {id: "waypoint_number_log", label: "WP #", item_type: "autofilled_value", value: currentStationData.waypoint_number},
                        {id: "last_offload_by_glider_log", label: "Last Offload by Glider", item_type: "autofilled_value", value: currentStationData.last_offload_by_glider},
                        {id: "station_settings_log", label: "Station Settings", item_type: "autofilled_value", value: currentStationData.station_settings},
                    ]
                },
                { 
                    id: "offload_parameters", title: "Offload Parameters & Timings", items: [
                        {id: "arrival_date_log", label: "Arrival Date/Time (UTC)", item_type: "datetime-local", value: formData.get('arrival_date_log')},
                        {id: "distance_cmd_sent_m_log", label: "Distance when command sent (m)", item_type: "text_input", value: formData.get('distance_cmd_sent_m_log')},
                        {id: "time_first_cmd_sent_utc_log", label: "Time first command sent (UTC)", item_type: "datetime-local", value: formData.get('time_first_cmd_sent_utc_log')},
                        {id: "start_time_remote_offload_utc_log", label: "Start Time - remote offload (UTC)", item_type: "datetime-local", value: formData.get('start_time_remote_offload_utc_log')},
                        {id: "end_time_offload_completed_utc_log", label: "End Time - Offload completed (UTC)", item_type: "datetime-local", value: formData.get('end_time_offload_completed_utc_log')},
                        {id: "departure_date_log", label: "Departure Date/Time (UTC)", item_type: "datetime-local", value: formData.get('departure_date_log')},
                    ]
                },
                { 
                    id: "offload_results", title: "Offload Results & Notes", items: [
                        {id: "offloaded_status_log", label: "Offloaded", item_type: "dropdown", value: formData.get('offloaded_status_log')},
                        {id: "elapsed_time_offload_log", label: "Elapsed Time for Offload", item_type: "static_text", value: document.getElementById('elapsed_time_offload_log_display')?.textContent || 'N/A'},
                        {id: "total_time_station_log", label: "Total time at Station", item_type: "static_text", value: document.getElementById('total_time_station_log_display')?.textContent || 'N/A'},
                        {id: "comments_log", label: "Comments", item_type: "text_area", value: formData.get('comments_log')},
                        {id: "vrl_file_name_log", label: "VRL File Name", item_type: "text_input", value: formData.get('vrl_file_name_log')},
                        {id: "vrl_file_size_log", label: "VRL File Size (bytes)", item_type: "text_input", value: formData.get('vrl_file_size_log')},
                        {id: "otn_metadata_notes_log", label: "OTN Metadata Notes", item_type: "text_area", value: formData.get('otn_metadata_notes_log')},
                    ]
                },
                { 
                    id: "sign_off", title: "Sign Off", items: [
                        {id: "logged_by_log", label: "Logged By", item_type: "autofilled_value", value: username }
                    ]
                }
            ];

            const payload = {
                mission_id: missionId,
                form_type: "wg_vm4_offload_log",
                form_title: `VM4 Offload Log: ${currentStationData.station_id} - Mission ${missionId}`,
                sections_data: sections_data
            };

            try {
                const result = await apiRequest(`/api/forms/${missionId}`, 'POST', payload);
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
    }
    // Initial call to clear/setup form fields
    buildOffloadLogFormFields(null);
}

// Note: The call to initializeWgVm4OffloadSection() will be made from dashboard.js
// when the WG-VM4 detail view is activated.
// Do NOT use DOMContentLoaded here if this script is loaded after dashboard.js
// and relies on dashboard.js to call its initialization function.
