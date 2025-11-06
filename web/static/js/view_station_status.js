/**
 * @file view_station_status.js
 * @description Station status management and offload logging
 */

import { checkAuth, getUserProfile } from '/static/js/auth.js';
import { apiRequest, showToast } from '/static/js/api.js';

document.addEventListener('DOMContentLoaded', async function () { 
    const stationStatusTableBody = document.getElementById('stationStatusTableBody');
    const searchInput = document.getElementById('searchInput');
    const loadingSpinner = document.getElementById('loadingSpinner');
    const downloadCsvBtn = document.getElementById('downloadCsvBtn');
    const downloadCsvDropdownToggle = document.getElementById('downloadCsvDropdownToggle');
    const uploadCsvBtn = document.getElementById('uploadCsvBtn');

    // Modal and form elements
    const editLogStationModalEl = document.getElementById('editLogStationModal');
    const uploadCsvModalEl = document.getElementById('uploadCsvModal');
    const submitUploadBtn = document.getElementById('submitUploadBtn');
    const csvFile = document.getElementById('csvFile');
    const uploadResult = document.getElementById('uploadResult');

    const newStationIdContainer = document.getElementById('newStationIdContainer');
    const formNewStationId = document.getElementById('formNewStationId');
    const modalTitleAction = document.getElementById('modalTitleAction');
    const modalStationIdDisplay = document.getElementById('modalStationIdDisplay');
    const logNewOffloadSection = document.getElementById('logNewOffloadSection');

    // Validation feedback elements
    const formNewStationIdFeedback = document.getElementById('formNewStationIdFeedback');
    const formModemAddressFeedback = document.getElementById('formModemAddressFeedback');
    const formBottomDepthFeedback = document.getElementById('formBottomDepthFeedback');
    const addStationBtn = document.getElementById('addStationBtn');
    const stationEditLogForm = document.getElementById('stationEditLogForm');

    let allStationsData = [];
    let currentSort = { column: 'station_id', order: 'asc' };
    let isAdmin = false;

    const stationInfoResult = document.getElementById('stationInfoResult'); // For displaying save/add result
    // Function to initialize the page: check role, then fetch data
    async function initializePage() {
        if (loadingSpinner) loadingSpinner.style.display = 'block'; // Show spinner early
        if (stationStatusTableBody) {
            // Update colspan to 8 for the new table structure with an Actions column
            stationStatusTableBody.innerHTML = '<tr><td colspan="8" class="text-center">Initializing...</td></tr>';
        }

        if (typeof checkAuth !== 'function' || !checkAuth()) {
            if (stationStatusTableBody) stationStatusTableBody.innerHTML = '<tr><td colspan="7" class="text-center text-danger">Authentication required. Please log in.</td></tr>';
            if (loadingSpinner) loadingSpinner.style.display = 'none';
            return;
        }

        try {
            // getUserProfile should be available from auth.js
            if (typeof getUserProfile !== 'function') {
                throw new Error("getUserProfile function is not available. auth.js might not be loaded correctly.");
            }
            const profile = await getUserProfile();
            if (profile && profile.role === 'admin') {
                isAdmin = true;
                if (downloadCsvBtn) downloadCsvBtn.style.display = 'block'; // Show CSV download for admin
                if (downloadCsvDropdownToggle) downloadCsvDropdownToggle.style.display = 'block';
                if (uploadCsvBtn) uploadCsvBtn.style.display = 'block'; // Show upload button for admin
                if (addStationBtn) addStationBtn.style.display = 'block'; // Show add station button for admin
            } else {
                isAdmin = false;
                if (downloadCsvBtn) downloadCsvBtn.style.display = 'none'; // Hide for non-admin
                if (downloadCsvDropdownToggle) downloadCsvDropdownToggle.style.display = 'none';
                if (uploadCsvBtn) uploadCsvBtn.style.display = 'none'; // Hide for non-admin
            }
        } catch (error) {
            console.warn("Could not determine user role for edit functionality.", error);
            isAdmin = false; // Default to non-admin on error
            if (uploadCsvBtn) uploadCsvBtn.style.display = 'none';
            if (downloadCsvBtn) downloadCsvBtn.style.display = 'none';
            if (downloadCsvDropdownToggle) downloadCsvDropdownToggle.style.display = 'none';
        }

        await fetchStationStatuses(); // Now fetch data
        if (loadingSpinner) loadingSpinner.style.display = 'none';
    }

    async function fetchStationStatuses() {
        if (!stationStatusTableBody) return; // Guard if element not found
        if (loadingSpinner) loadingSpinner.style.display = 'block'; // Show spinner during fetch

        try {
            allStationsData = await apiRequest('/api/stations/status_overview', 'GET');
            renderTable(allStationsData);
        } catch (error) {
            showToast(`Error loading station statuses: ${error.message}`, 'danger');
            stationStatusTableBody.innerHTML = `<tr><td colspan="8" class="text-center text-danger">Error loading data: ${error.message}</td></tr>`;
        } finally {
            if (loadingSpinner) loadingSpinner.style.display = 'none';
        }
    }


    function renderTable(stationsToRender) {
        if (!stationStatusTableBody) return;
        stationStatusTableBody.innerHTML = ''; // Clear existing rows

        if (!stationsToRender || stationsToRender.length === 0) {
            const currentFilter = searchInput ? searchInput.value : "";
            if (currentFilter) {
                stationStatusTableBody.innerHTML = `<tr><td colspan="8" class="text-center">No stations match your filter "${currentFilter}".</td></tr>`;
            } else {
                stationStatusTableBody.innerHTML = '<tr><td colspan="8" class="text-center">No station data available.</td></tr>';
            }
            return;
        }

        stationsToRender.forEach(station => {
            const row = stationStatusTableBody.insertRow();

            // Data cells (7 columns)
            row.insertCell().textContent = station.station_id || 'N/A';
            row.insertCell().textContent = station.serial_number || 'N/A';
            row.insertCell().textContent = station.modem_address !== null ? station.modem_address : 'N/A';
            row.insertCell().textContent = station.station_settings || '---';
            const statusCell = row.insertCell();
            statusCell.textContent = station.status_text || 'N/A';
            row.insertCell().textContent = station.last_offload_timestamp_str || 'N/A';
            row.insertCell().textContent = station.vrl_file_name || '---';

            // Actions cell (8th column)
            const actionsCell = row.insertCell();
            actionsCell.classList.add('text-nowrap'); // Prevent buttons from wrapping on small screens

            // The "Edit" button should be available to all authenticated users to log offloads.
            const editButton = document.createElement('button');
            editButton.classList.add('btn', 'btn-sm', 'btn-outline-primary', 'me-1');
            editButton.title = `Edit / Log for ${station.station_id}`;
            editButton.innerHTML = `<i class="fas fa-edit"></i> Edit`;
            editButton.onclick = () => openEditLogModal(station.station_id);
            actionsCell.appendChild(editButton);

            // The "Delete" button is restricted to admins.
            if (isAdmin) {
                const deleteButton = document.createElement('button');
                deleteButton.classList.add('btn', 'btn-sm', 'btn-danger');
                deleteButton.title = `Delete ${station.station_id} metadata.`;
                deleteButton.innerHTML = `<i class="fas fa-trash-alt"></i> Delete`;
                deleteButton.onclick = () => deleteStation(station.station_id);
                actionsCell.appendChild(deleteButton);
            }

            // Apply row coloring based on status
            row.classList.remove('status-awaiting-offload', 'status-offloaded', 'status-failed-offload', 'status-skipped', 'status-unknown');
            if (station.status_color === 'grey') row.classList.add('status-awaiting-offload');
            else if (station.status_color === 'green') row.classList.add('status-offloaded');
            else if (station.status_color === 'red') row.classList.add('status-failed-offload');
            else if (station.status_color === 'yellow' || station.status_color === 'orange') row.classList.add('status-skipped');
            else row.classList.add('status-unknown');
        });
        updateSortIcons();
    }

    // Helper functions for validation feedback
    function showValidationFeedback(element, feedbackElement, message) {
        element.classList.add('is-invalid');
        feedbackElement.textContent = message;
        feedbackElement.style.display = 'block'; // Make sure it's visible
    }

    function clearValidationFeedback(element, feedbackElement) {
        element.classList.remove('is-invalid');
        feedbackElement.textContent = '';
        feedbackElement.style.display = 'none'; // Hide it
    }
    function sortData(column) {
        const order = (currentSort.column === column && currentSort.order === 'asc') ? 'desc' : 'asc';
        currentSort = { column, order };

        // Create a copy of allStationsData to sort, so filtering doesn't affect the master sort order of all data
        const dataToSort = [...allStationsData];

        dataToSort.sort((a, b) => {
            let valA = a[column];
            let valB = b[column];

            if (column === 'modem_address') {
                valA = valA === null || valA === undefined ? -Infinity : Number(valA);
                valB = valB === null || valB === undefined ? -Infinity : Number(valB);
            } else if (column === 'last_offload_timestamp_str') {
                // For timestamp string, rely on ISO format for string comparison.
                // For more robust date sorting,
                // it's better to sort by the original Date object if available, or parse these strings to Dates.
                valA = valA === null || valA === undefined ? '' : String(valA);
                valB = valB === null || valB === undefined ? '' : String(valB);
            } else {
                 valA = valA === null || valA === undefined ? '' : String(valA).toLowerCase();
                 valB = valB === null || valB === undefined ? '' : String(valB).toLowerCase();
            }
            if (valA < valB) return order === 'asc' ? -1 : 1;
            if (valA > valB) return order === 'asc' ? 1 : -1;
            return 0;
        });
        
        // Update allStationsData with the new sort order if we want the master list sorted
        allStationsData = dataToSort; 
        // Then re-apply filter if any, or render all
        const searchTerm = searchInput ? searchInput.value.toLowerCase() : "";
        filterAndRender(searchTerm);
    }

    function updateSortIcons() {
        document.querySelectorAll('th[data-sort]').forEach(th => {
            const iconSpan = th.querySelector('.sort-icon');
            if (!iconSpan) return;
            iconSpan.className = 'sort-icon fas fa-sort'; // Reset with default
            if (th.dataset.sort === currentSort.column) {
                const directionClass = currentSort.order === 'asc' ? 'fa-sort-up' : 'fa-sort-down';
                iconSpan.classList.remove('fa-sort');
                iconSpan.classList.add(directionClass);
            }
        });
    }
    
    function filterAndRender(searchTerm) {
        let filteredStations = allStationsData;
        if (searchTerm) {
            filteredStations = allStationsData.filter(station => {
                return (station.station_id?.toLowerCase() || '').includes(searchTerm) ||
                       (station.serial_number?.toLowerCase() || '').includes(searchTerm) ||
                       (station.last_offload_by_glider?.toLowerCase() || '').includes(searchTerm) ||
                       (station.station_settings?.toLowerCase() || '').includes(searchTerm) ||
                       (station.modem_address?.toString().toLowerCase() || '').includes(searchTerm) || // Added modem address to filter
                       (station.vrl_file_name?.toLowerCase() || '').includes(searchTerm) ||
                       (station.status_text?.toLowerCase() || '').includes(searchTerm); // Added status text to filter
            });
        }
        renderTable(filteredStations);
    }

    if (searchInput) {
        searchInput.addEventListener('input', function () {
            filterAndRender(this.value.toLowerCase());
        });
    }

    function escapeCsvCell(cellData) {
        if (cellData === null || cellData === undefined) {
            return '';
        }
        const stringData = String(cellData);
        // If the string contains a comma, newline, or double quote, enclose in double quotes
        if (stringData.includes(',') || stringData.includes('\n') || stringData.includes('"')) {
            // Escape existing double quotes by doubling them
            return `"${stringData.replace(/"/g, '""')}"`;
        }
        return stringData;
    }

    function downloadCsv(prefixFilter = null) {
        let dataToExport = allStationsData;
        let fileName = "station_offload_status.csv";

        if (prefixFilter) {
            dataToExport = dataToExport.filter(station => 
                station.station_id && station.station_id.toLowerCase().startsWith(prefixFilter.toLowerCase())
            );
            fileName = `station_status_${prefixFilter.toLowerCase()}.csv`;
        } else {
            // If no prefix filter, use the general search input
            const searchTerm = searchInput ? searchInput.value.toLowerCase() : "";
            if (searchTerm) {
                dataToExport = dataToExport.filter(station => {
                    return (station.station_id?.toLowerCase() || '').includes(searchTerm) ||
                           (station.serial_number?.toLowerCase() || '').includes(searchTerm) ||
                           (station.station_settings?.toLowerCase() || '').includes(searchTerm) ||
                           (station.vrl_file_name?.toLowerCase() || '').includes(searchTerm);
                });
                fileName = `station_status_filtered.csv`;
            }
        }    
        if (dataToExport.length === 0) {
            alert("No data available to download (check filters).");
            return;
        } // "Station ID", "Serial Number", "Modem Address", "Station Settings", "Status", "Last Log Update", "VRL File Name"
        const headers = [ // Keys from the station object
            "station_id", "serial_number", "modem_address", "station_settings", 
            "status_text", "last_offload_timestamp_str", "vrl_file_name",
            // New fields from the latest offload log
            "latest_arrival_date", "latest_distance_command_sent_m", 
            "latest_time_first_command_sent_utc", "latest_offload_start_time_utc",
            "latest_offload_end_time_utc", "latest_departure_date",
            "latest_was_offloaded", "latest_offload_notes_file_size"
        ];
        const displayHeaders = [ // User-friendly headers for the CSV file
            "Station ID", "Serial Number", "Modem Address",
            "Station Settings", "Status", "Last Log Update (UTC)", "VRL File Name",
            // Display headers for new fields
            "Arrival Date (UTC)", "Distance Cmd Sent (m)",
            "Time First Cmd Sent (UTC)", "Offload Start (UTC)",
            "Offload End (UTC)", "Departure Date (UTC)",
            "Offloaded Successfully", "Offload Notes/File Size"
        ];
        let csvContent = displayHeaders.join(",") + "\r\n";
        dataToExport.forEach(station => {
            const row = headers.map(headerKey => escapeCsvCell(station[headerKey]));
            csvContent += row.join(",") + "\r\n";
        });
        const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
        const link = document.createElement("a");
        if (link.download !== undefined) {
            const url = URL.createObjectURL(blob);
            link.setAttribute("href", url);
            link.setAttribute("download", fileName);
            link.style.visibility = 'hidden';
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            URL.revokeObjectURL(url);
        }
    }

    // --- New Modal Handling ---
    let currentEditingStationId = null;
    let editLogStationModalInstance = null;
    if (editLogStationModalEl) {
        editLogStationModalInstance = new bootstrap.Modal(editLogStationModalEl);
    }

    let uploadCsvModalInstance = null;
    if (uploadCsvModalEl) {
        uploadCsvModalInstance = new bootstrap.Modal(uploadCsvModalEl);
    }

    async function openEditLogModal(stationId) {
        // Any authenticated user can open the modal to log an offload.
        if (!editLogStationModalInstance) return;

        currentEditingStationId = stationId;
        // Clear all validation feedback and result messages when opening modal
        clearValidationFeedback(formNewStationId, formNewStationIdFeedback);
        clearValidationFeedback(formModemAddress, formModemAddressFeedback);
        clearValidationFeedback(formBottomDepth, formBottomDepthFeedback);
        if (stationInfoResult) stationInfoResult.innerHTML = '';
        if (stationEditLogForm) stationEditLogForm.reset(); // Clear previous data
        
        // Configure modal for "Edit" mode
        if (modalTitleAction) modalTitleAction.textContent = "Edit Station / Log Offload for:";
        if (modalStationIdDisplay) modalStationIdDisplay.textContent = stationId;
        if (newStationIdContainer) newStationIdContainer.style.display = 'none';
        if (logNewOffloadSection) logNewOffloadSection.style.display = 'block';

        document.getElementById('formStationId').value = stationId; // Hidden input

        if (loadingSpinner) loadingSpinner.style.display = 'block';

        try {
            const stationData = await apiRequest(`/api/station_metadata/${stationId}`, 'GET');

            // Populate Station Information
            document.getElementById('formSerialNumber').value = stationData.serial_number || '';
            document.getElementById('formModemAddress').value = stationData.modem_address !== null ? stationData.modem_address : '';
            document.getElementById('formBottomDepth').value = stationData.bottom_depth_m !== null ? stationData.bottom_depth_m : '';
            document.getElementById('formWaypointNumber').value = stationData.waypoint_number || '';
            document.getElementById('formDeploymentLatitude').value = stationData.deployment_latitude !== null ? stationData.deployment_latitude : '';
            document.getElementById('formDeploymentLongitude').value = stationData.deployment_longitude !== null ? stationData.deployment_longitude : '';
            document.getElementById('formLastOffloadByGlider').value = stationData.last_offload_by_glider || '';
            document.getElementById('formStationSettings').value = stationData.station_settings || '';
            document.getElementById('formStationNotes').value = stationData.notes || '';
            document.getElementById('formDisplayStatusOverride').value = stationData.display_status_override || '';
            
            // Clear Log New Offload fields (as they are for a new entry)
            document.getElementById('formArrivalDate').value = '';
            document.getElementById('formDistanceSent').value = '';
            document.getElementById('formTimeFirstCommand').value = '';
            document.getElementById('formOffloadStartTime').value = '';
            document.getElementById('formOffloadEndTime').value = '';
            document.getElementById('formDepartureDate').value = '';
            document.getElementById('formVrlFileName').value = '';
            document.getElementById('formOffloadNotesFileSize').value = '';
            document.getElementById('formWasOffloaded').checked = false;

            editLogStationModalInstance.show();
        } catch (error) {

            console.error('Error opening edit modal:', error);
            alert(`Could not load station details: ${error.message}`);
        } finally {
            if (loadingSpinner) loadingSpinner.style.display = 'none';
        }
    }

    // Helper to convert datetime-local string to UTC ISO string or null
    function getIsoFromDatetimeLocal(elementId) {
        const val = document.getElementById(elementId).value;
        if (val) {
            // When a user enters a time into a datetime-local input based on a "(UTC)" label,
            // we must interpret that time as UTC. Appending 'Z' to the string tells the
            // Date constructor to parse it as UTC, not as the browser's local time.
            const utcDate = new Date(val + 'Z');
            // Check if the date is valid after parsing
            if (!isNaN(utcDate.valueOf())) {
                return utcDate.toISOString();
            }
        }
        return null;
    }

    const saveStationInfoBtn = document.getElementById('saveStationInfoBtn');
    if (saveStationInfoBtn) {
        saveStationInfoBtn.addEventListener('click', async () => {
            // Clear previous results and validation messages
            if (stationInfoResult) stationInfoResult.innerHTML = '';
            clearValidationFeedback(formNewStationId, formNewStationIdFeedback);
            clearValidationFeedback(formModemAddress, formModemAddressFeedback);
            clearValidationFeedback(formBottomDepth, formBottomDepthFeedback);
            clearValidationFeedback(document.getElementById('formDeploymentLatitude'), document.getElementById('formDeploymentLatitudeFeedback'));
            clearValidationFeedback(document.getElementById('formDeploymentLongitude'), document.getElementById('formDeploymentLongitudeFeedback'));

            if (loadingSpinner) loadingSpinner.style.display = 'block';

            const isAdding = !currentEditingStationId;
            let stationId = isAdding ? formNewStationId.value.trim() : currentEditingStationId;

            // --- Form Validation ---
            if (isAdding && !stationId) {
                showValidationFeedback(formNewStationId, formNewStationIdFeedback, 'Station ID is required.');
                if (loadingSpinner) loadingSpinner.style.display = 'none';
                formNewStationId.focus();
                return;
            }

            const modemAddressValue = document.getElementById('formModemAddress').value.trim();
            if (modemAddressValue !== '' && isNaN(parseInt(modemAddressValue, 10))) { // Check for non-empty string that's not a number
                showValidationFeedback(formModemAddress, formModemAddressFeedback, 'Modem Address must be a valid number.');
                if (loadingSpinner) loadingSpinner.style.display = 'none';
                document.getElementById('formModemAddress').focus();
                return;
            }

            const bottomDepthValue = document.getElementById('formBottomDepth').value.trim();
            if (bottomDepthValue !== '' && isNaN(parseFloat(bottomDepthValue))) { // Check for non-empty string that's not a number
                showValidationFeedback(formBottomDepth, formBottomDepthFeedback, 'Bottom Depth must be a valid number.');
                if (loadingSpinner) loadingSpinner.style.display = 'none';
                document.getElementById('formBottomDepth').focus();
                return;
            }

            const latitudeValue = document.getElementById('formDeploymentLatitude').value.trim();
            if (latitudeValue !== '' && (isNaN(parseFloat(latitudeValue)) || parseFloat(latitudeValue) < -90 || parseFloat(latitudeValue) > 90)) {
                showValidationFeedback(document.getElementById('formDeploymentLatitude'), document.getElementById('formDeploymentLatitudeFeedback'), 'Latitude must be a valid number between -90 and 90.');
                if (loadingSpinner) loadingSpinner.style.display = 'none';
                document.getElementById('formDeploymentLatitude').focus();
                return;
            }

            const longitudeValue = document.getElementById('formDeploymentLongitude').value.trim();
            if (longitudeValue !== '' && (isNaN(parseFloat(longitudeValue)) || parseFloat(longitudeValue) < -180 || parseFloat(longitudeValue) > 180)) {
                showValidationFeedback(document.getElementById('formDeploymentLongitude'), document.getElementById('formDeploymentLongitudeFeedback'), 'Longitude must be a valid number between -180 and 180.');
                if (loadingSpinner) loadingSpinner.style.display = 'none';
                document.getElementById('formDeploymentLongitude').focus();
                return;
            }
            // --- End Validation ---

            const payload = {
                station_id: stationId,
                serial_number: document.getElementById('formSerialNumber').value.trim() || null,
                modem_address: modemAddressValue ? parseInt(modemAddressValue, 10) : null,
                bottom_depth_m: bottomDepthValue ? parseFloat(bottomDepthValue) : null,
                waypoint_number: document.getElementById('formWaypointNumber').value.trim() || null,
                deployment_latitude: latitudeValue ? parseFloat(latitudeValue) : null,
                deployment_longitude: longitudeValue ? parseFloat(longitudeValue) : null,
                last_offload_by_glider: document.getElementById('formLastOffloadByGlider').value.trim() || null,
                station_settings: document.getElementById('formStationSettings').value.trim() || null,
                notes: document.getElementById('formStationNotes').value.trim() || null,
                display_status_override: document.getElementById('formDisplayStatusOverride').value || null
            };

            // Clean up payload: remove nulls for cleaner API calls
            Object.keys(payload).forEach(key => {
                if (payload[key] === null || payload[key] === '') delete payload[key];
            });
            // The NaN check is now part of the initial validation, so this is less critical but safe to keep
            if (payload.modem_address && isNaN(payload.modem_address)) delete payload.modem_address;
            if (payload.bottom_depth_m && isNaN(payload.bottom_depth_m)) delete payload.bottom_depth_m;

            try {
                const resultData = await apiRequest('/api/station_metadata/', 'POST', payload);

                // Use resultData.is_created from the backend response
                const finalSuccessMessage = resultData.is_created ?
                    'Station added successfully!' :
                    'Station information updated successfully!';
                
                showToast(finalSuccessMessage, 'success');
                if (stationInfoResult) {
                    stationInfoResult.innerHTML = `<div class="alert alert-success">${finalSuccessMessage}</div>`;
                }

                await fetchStationStatuses();
                // Do not hide modal immediately, let user see success message
                // if (editLogStationModalInstance) editLogStationModalInstance.hide();

            } catch (error) {
                showToast(`Error ${isAdding ? 'adding' : 'updating'} station: ${error.message}`, 'danger');
                alert(`Error: ${error.message}`);
            } finally {
                if (loadingSpinner) loadingSpinner.style.display = 'none';
            }
        });
    }


    const logNewOffloadBtn = document.getElementById('logNewOffloadBtn');
    if (logNewOffloadBtn) {
        logNewOffloadBtn.addEventListener('click', async () => {
            if (!currentEditingStationId) return;
            if (loadingSpinner) loadingSpinner.style.display = 'block';

            const payload = {
                // For 'date' inputs, the value is already in 'YYYY-MM-DD' format, which FastAPI handles.
                arrival_date: document.getElementById('formArrivalDate').value || null,
                distance_command_sent_m: parseFloat(document.getElementById('formDistanceSent').value) || null,
                time_first_command_sent_utc: getIsoFromDatetimeLocal('formTimeFirstCommand'),
                offload_start_time_utc: getIsoFromDatetimeLocal('formOffloadStartTime'),
                offload_end_time_utc: getIsoFromDatetimeLocal('formOffloadEndTime'),
                departure_date: document.getElementById('formDepartureDate').value || null,
                was_offloaded: document.getElementById('formWasOffloaded').checked,
                vrl_file_name: document.getElementById('formVrlFileName').value.trim() || null,
                offload_notes_file_size: document.getElementById('formOffloadNotesFileSize').value.trim() || null,
            };
             // Filter out null values if backend expects only provided fields
            Object.keys(payload).forEach(key => payload[key] === null && delete payload[key]);
             if (payload.distance_command_sent_m && isNaN(payload.distance_command_sent_m)) delete payload.distance_command_sent_m;

            try {
                await apiRequest(`/api/station_metadata/${currentEditingStationId}/offload_logs/`, 'POST', payload);
                await fetchStationStatuses(); // Refresh table
                showToast('New offload logged successfully!', 'success');
                // Clear only the offload log form fields
                document.getElementById('formArrivalDate').value = '';
                document.getElementById('formDistanceSent').value = '';
                document.getElementById('formTimeFirstCommand').value = '';
                document.getElementById('formOffloadStartTime').value = '';
                document.getElementById('formOffloadEndTime').value = '';
                document.getElementById('formDepartureDate').value = '';
                document.getElementById('formVrlFileName').value = '';
                document.getElementById('formOffloadNotesFileSize').value = '';
                document.getElementById('formWasOffloaded').checked = false;
                // Keep modal open for potentially more logs or edits
            } catch (error) {
                showToast(`Error logging offload: ${error.message}`, 'danger');
                alert(`Error: ${error.message}`);
            } finally {
                if (loadingSpinner) loadingSpinner.style.display = 'none';
            }
        });
    }

    if (uploadCsvBtn) {
        uploadCsvBtn.addEventListener('click', () => {
            if (uploadCsvModalInstance) {
                // Reset modal state before showing
                if (uploadResult) {
                    uploadResult.innerHTML = '';
                    uploadResult.className = 'mt-3';
                }
                if (csvFile) csvFile.value = '';
                if (submitUploadBtn) submitUploadBtn.disabled = false;
                uploadCsvModalInstance.show();
            }
        });
    }

    if (submitUploadBtn) {
        submitUploadBtn.addEventListener('click', async () => {
            if (!csvFile.files || csvFile.files.length === 0) {
                uploadResult.innerHTML = '<div class="alert alert-warning">Please select a file to upload.</div>';
                return;
            }

            const file = csvFile.files[0];
            const formData = new FormData();
            formData.append('file', file);

            submitUploadBtn.disabled = true;
            uploadResult.innerHTML = '<div class="alert alert-info">Uploading...</div>';

            try {
                // For FormData uploads, we need to use fetch directly since apiRequest expects JSON
                const token = localStorage.getItem('accessToken');
                const headers = {};
                if (token) {
                    headers['Authorization'] = `Bearer ${token}`;
                }
                // Note: Don't set Content-Type for FormData - browser sets it with boundary
                const response = await fetch('/api/station_metadata/upload_csv/', {
                    method: 'POST',
                    headers: headers,
                    body: formData
                });

                const resultData = await response.json();

                if (!response.ok && response.status !== 207) { // 207 is Multi-Status for partial success
                    throw new Error(resultData.detail || 'An unknown error occurred during upload.');
                }

                let alertClass = response.status === 207 ? 'alert-warning' : 'alert-success';
                showToast(resultData.message, response.status === 207 ? 'warning' : 'success');
                let resultHtml = `<div class="alert ${alertClass}">${resultData.message}</div>`;
                if (resultData.errors && resultData.errors.length > 0) {
                    resultHtml += '<h6>Errors:</h6><ul class="list-group">';
                    resultData.errors.forEach(err => {
                        resultHtml += `<li class="list-group-item list-group-item-danger bg-dark text-light">${err}</li>`;
                    });
                    resultHtml += '</ul>';
                }
                uploadResult.innerHTML = resultHtml;

                await fetchStationStatuses(); // Refresh the main station table

            } catch (error) {
                showToast(`Error uploading CSV: ${error.message}`, 'danger');
                uploadResult.innerHTML = `<div class="alert alert-danger">Upload failed: ${error.message}</div>`;
            } finally {
                submitUploadBtn.disabled = false;
            }
        });
    }

    // Remove old event delegation for 'edit-station-link' if it exists,
    // as we now add direct onclick handlers or specific buttons.
    // The old `stationStatusTableBody.addEventListener('click', function(event) { ... });`
    // that specifically looked for `edit-station-link` can be removed if it was solely for the old modal.
   // Since we are adding buttons with direct onclick, the generic listener is not strictly needed for this functionality anymore.

    // Add listeners for table headers for sorting
    document.querySelectorAll('th[data-sort]').forEach(th => {
        th.addEventListener('click', () => sortData(th.dataset.sort));
    });

    if (downloadCsvBtn) {
        // Main button downloads based on current search filter
        downloadCsvBtn.addEventListener('click', () => downloadCsv(null));
    }

    // Event listeners for prefix-specific CSV downloads
    document.querySelectorAll('.download-prefix-csv').forEach(item => {
        item.addEventListener('click', function(event) {
            event.preventDefault();
            const prefix = this.dataset.prefix;
            if (prefix) {
                downloadCsv(prefix);
            }
        });
    });

    const downloadAllFilteredLink = document.getElementById('downloadAllFilteredCsvLink');
    if (downloadAllFilteredLink) {
        downloadAllFilteredLink.addEventListener('click', (event) => {event.preventDefault(); downloadCsv(null);});
     }

    // Initial page load
    initializePage(); // No await here, as it's called within DOMContentLoaded

    
    // --- Add Station Functionality ---
    if (addStationBtn) {
        addStationBtn.addEventListener('click', () => {
            currentEditingStationId = null; // Ensure we are in "add" mode
            // Clear form fields in the modal (including hidden fields)
            if (stationEditLogForm) stationEditLogForm.reset(); // Clear all input, textarea, select
            // Clear all validation feedback and result messages when opening modal
            clearValidationFeedback(formNewStationId, formNewStationIdFeedback);
            clearValidationFeedback(formModemAddress, formModemAddressFeedback);
            clearValidationFeedback(formBottomDepth, formBottomDepthFeedback);
            if (stationInfoResult) stationInfoResult.innerHTML = '';

            // Configure modal for "Add" mode
            if (modalTitleAction) modalTitleAction.textContent = "Add New Station";
            if (modalStationIdDisplay) modalStationIdDisplay.textContent = ""; // Clear the station ID from title
            
            // Show the station ID input field for new stations
            if (newStationIdContainer) newStationIdContainer.style.display = 'block';
            if (formNewStationId) formNewStationId.value = '';

            // Hide the "Log New Offload" section, as it's not applicable for a new station
            if (logNewOffloadSection) logNewOffloadSection.style.display = 'none';

            // Show the modal
            if (editLogStationModalInstance) {
                editLogStationModalInstance.show();
            }
        });
    }

    // --- Delete Station Functionality ---
    async function deleteStation(stationId) {
        if (!isAdmin) return; // Ensure only admin can delete

        if (!confirm(`Are you sure you want to delete station "${stationId}"? This action cannot be undone.`)) {
            return;
        }

        try {
            await apiRequest(`/api/station_metadata/${stationId}`, 'DELETE');
            showToast(`Station "${stationId}" deleted successfully`, 'success');
            await fetchStationStatuses(); // Refresh the table
        } catch (error) {
            showToast(`Error deleting station: ${error.message}`, 'danger');
            console.error('Error deleting station:', error);
            alert(`Error: ${error.message}`);
        }
    }
});