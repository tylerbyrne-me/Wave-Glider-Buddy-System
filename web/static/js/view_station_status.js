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
        
        // Initialize season management if admin
        if (isAdmin) {
            await initializeSeasonManagement();
        }
    }

    async function fetchStationStatuses() {
        if (!stationStatusTableBody) return; // Guard if element not found
        if (loadingSpinner) loadingSpinner.style.display = 'block'; // Show spinner during fetch

        try {
            let url = '/api/stations/status_overview';
            if (selectedSeasonYear !== null) {
                url += `?season_year=${selectedSeasonYear}`;
            }
            allStationsData = await apiRequest(url, 'GET');
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
            editButton.onclick = () => openEditLogModal(station.station_id, station);
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
            "latest_was_offloaded", "latest_offload_notes_file_size",
            // VM4 Remote Health fields (from latest offload)
            "remote_health_model_id", "remote_health_serial_number", "remote_health_modem_address",
            "remote_health_temperature_c", "remote_health_tilt_rad", "remote_health_humidity"
        ];
        const displayHeaders = [ // User-friendly headers for the CSV file
            "Station ID", "Serial Number", "Modem Address",
            "Station Settings", "Status", "Last Log Update (UTC)", "VRL File Name",
            // Display headers for new fields
            "Arrival Date (UTC)", "Distance Cmd Sent (m)",
            "Time First Cmd Sent (UTC)", "Offload Start (UTC)",
            "Offload End (UTC)", "Departure Date (UTC)",
            "Offloaded Successfully", "Offload Notes/File Size",
            // VM4 Remote Health headers
            "Remote Health Model ID", "Remote Health Serial Number", "Remote Health Modem Address",
            "Remote Health Temperature (C)", "Remote Health Tilt (Rad)", "Remote Health Humidity"
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

    async function openEditLogModal(stationId, stationRow) {
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
        
        // Show latest offload remote health (VM4) when available from overview row
        const rhSection = document.getElementById('latestRemoteHealthSection');
        const row = stationRow || (Array.isArray(allStationsData) ? allStationsData.find(s => s.station_id === stationId) : null);
        if (rhSection && row && (row.remote_health_model_id != null || row.remote_health_temperature_c != null || row.remote_health_humidity != null)) {
            rhSection.style.display = 'block';
            document.getElementById('displayRemoteHealthModelId').textContent = row.remote_health_model_id != null ? row.remote_health_model_id : '—';
            document.getElementById('displayRemoteHealthSerialNumber').textContent = row.remote_health_serial_number != null ? row.remote_health_serial_number : '—';
            document.getElementById('displayRemoteHealthModemAddress').textContent = row.remote_health_modem_address != null ? row.remote_health_modem_address : '—';
            document.getElementById('displayRemoteHealthTemperatureC').textContent = row.remote_health_temperature_c != null ? row.remote_health_temperature_c : '—';
            document.getElementById('displayRemoteHealthTiltRad').textContent = row.remote_health_tilt_rad != null ? row.remote_health_tilt_rad : '—';
            document.getElementById('displayRemoteHealthHumidity').textContent = row.remote_health_humidity != null ? row.remote_health_humidity : '—';
        } else if (rhSection) {
            rhSection.style.display = 'none';
        }

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
                
                // Populate season dropdown
                populateUploadSeasonDropdown();
                
                uploadCsvModalInstance.show();
            }
        });
    }

    function populateUploadSeasonDropdown() {
        const uploadSeasonYear = document.getElementById('uploadSeasonYear');
        if (!uploadSeasonYear) return;

        // Clear existing options
        uploadSeasonYear.innerHTML = '<option value="">Current Active Season</option>';

        // Add all seasons
        allSeasons.forEach(season => {
            const option = document.createElement('option');
            option.value = season.year;
            option.textContent = `${season.year}${season.is_active ? ' (Active)' : ' (Closed)'}`;
            uploadSeasonYear.appendChild(option);
        });
    }

    if (submitUploadBtn) {
        submitUploadBtn.addEventListener('click', async () => {
            if (!csvFile.files || csvFile.files.length === 0) {
                uploadResult.innerHTML = '<div class="alert alert-warning">Please select a file to upload.</div>';
                return;
            }

            const file = csvFile.files[0];
            const uploadSeasonYear = document.getElementById('uploadSeasonYear');
            const selectedSeasonYear = uploadSeasonYear ? uploadSeasonYear.value : '';

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
                
                // Build URL with season_year parameter if specified
                let uploadUrl = '/api/station_metadata/upload_csv/';
                if (selectedSeasonYear) {
                    uploadUrl += `?season_year=${encodeURIComponent(selectedSeasonYear)}`;
                }
                
                // Note: Don't set Content-Type for FormData - browser sets it with boundary
                const response = await fetch(uploadUrl, {
                    method: 'POST',
                    headers: headers,
                    body: formData
                });

                const resultData = await response.json();

                if (!response.ok && response.status !== 207) { // 207 is Multi-Status for partial success
                    throw new Error(resultData.detail || 'An unknown error occurred during upload.');
                }

                let alertClass = response.status === 207 ? 'alert-warning' : 'alert-success';
                let toastType = response.status === 207 ? 'warning' : (resultData.warnings ? 'info' : 'success');
                showToast(resultData.message, toastType);
                let resultHtml = `<div class="alert ${alertClass}">${resultData.message}</div>`;
                
                // Display warnings (duplicate checks)
                if (resultData.warnings && resultData.warnings.length > 0) {
                    resultHtml += '<div class="mt-3"><h6><i class="fas fa-exclamation-triangle me-2"></i>Warnings (Duplicates Detected):</h6><ul class="list-group">';
                    resultData.warnings.forEach(warning => {
                        const warningClass = warning.type.includes('in_csv') ? 'list-group-item-warning' : 'list-group-item-info';
                        resultHtml += `<li class="list-group-item ${warningClass} bg-dark text-light">`;
                        resultHtml += `<strong>${warning.message}</strong>`;
                        if (warning.duplicates && warning.duplicates.length > 0) {
                            resultHtml += `<br><small>Values: ${warning.duplicates.join(', ')}</small>`;
                        }
                        resultHtml += `</li>`;
                    });
                    resultHtml += '</ul></div>';
                }
                
                // Display errors
                if (resultData.errors && resultData.errors.length > 0) {
                    resultHtml += '<div class="mt-3"><h6><i class="fas fa-times-circle me-2"></i>Errors:</h6><ul class="list-group">';
                    resultData.errors.forEach(err => {
                        resultHtml += `<li class="list-group-item list-group-item-danger bg-dark text-light">${err}</li>`;
                    });
                    resultHtml += '</ul></div>';
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

    // ============================================================================
    // Field Season Management Functions
    // ============================================================================
    
    let activeSeason = null;
    let allSeasons = [];
    let selectedSeasonYear = null; // null = active season

    // Initialize season management UI
    async function initializeSeasonManagement() {
        if (!isAdmin) {
            return; // Only show for admins
        }

        const seasonManagementSection = document.getElementById('seasonManagementSection');
        if (seasonManagementSection) {
            seasonManagementSection.style.display = 'block';
        }

        await fetchActiveSeason();
        await fetchAllSeasons();
        setupSeasonEventListeners();
        
        // Populate upload season dropdown when seasons are loaded
        populateUploadSeasonDropdown();
        
        // Update statistics display for currently selected season
        if (selectedSeasonYear) {
            await updateSeasonStatisticsDisplay(selectedSeasonYear);
        } else if (activeSeason) {
            await updateSeasonStatisticsDisplay(activeSeason.year);
        }
    }

    async function fetchActiveSeason() {
        try {
            activeSeason = await apiRequest('/api/field_seasons/active', 'GET');
            const activeSeasonDisplay = document.getElementById('activeSeasonDisplay');
            if (activeSeasonDisplay) {
                activeSeasonDisplay.textContent = activeSeason.year || 'No active season';
            }
            updateSeasonButtons();
            
            // If no season is selected and we have an active season, show its stats
            if (!selectedSeasonYear && activeSeason) {
                await updateSeasonStatisticsDisplay(activeSeason.year);
            }
        } catch (error) {
            console.warn('No active season found or error fetching:', error);
            activeSeason = null;
            const activeSeasonDisplay = document.getElementById('activeSeasonDisplay');
            if (activeSeasonDisplay) {
                activeSeasonDisplay.textContent = 'No active season';
            }
            updateSeasonButtons();
        }
    }

    function updateSeasonButtons() {
        const createSeasonBtn = document.getElementById('createSeasonBtn');
        const closeSeasonBtn = document.getElementById('closeSeasonBtn');
        const prepareNextSeasonBtn = document.getElementById('prepareNextSeasonBtn');

        if (activeSeason) {
            // Active season exists - show close/prepare buttons, hide create button
            if (createSeasonBtn) createSeasonBtn.style.display = 'none';
            if (closeSeasonBtn) closeSeasonBtn.style.display = 'inline-block';
            if (prepareNextSeasonBtn) prepareNextSeasonBtn.style.display = 'inline-block';
        } else {
            // No active season - show create button, hide close/prepare buttons
            if (createSeasonBtn) createSeasonBtn.style.display = 'inline-block';
            if (closeSeasonBtn) closeSeasonBtn.style.display = 'none';
            if (prepareNextSeasonBtn) prepareNextSeasonBtn.style.display = 'none';
        }
    }

    async function fetchAllSeasons() {
        try {
            allSeasons = await apiRequest('/api/field_seasons/', 'GET');
            const seasonSelector = document.getElementById('seasonSelector');
            const downloadSeasonYear = document.getElementById('downloadSeasonYear');
            
            if (seasonSelector) {
                // Clear existing options except first
                seasonSelector.innerHTML = '<option value="">Current Active Season</option>';
                allSeasons.forEach(season => {
                    const option = document.createElement('option');
                    option.value = season.year;
                    option.textContent = `${season.year}${season.is_active ? ' (Active)' : ' (Closed)'}`;
                    seasonSelector.appendChild(option);
                });
            }
            
            if (downloadSeasonYear) {
                downloadSeasonYear.innerHTML = '<option value="">Select a season...</option>';
                allSeasons.forEach(season => {
                    if (!season.is_active) { // Only show closed seasons for download
                        const option = document.createElement('option');
                        option.value = season.year;
                        option.textContent = `${season.year}`;
                        downloadSeasonYear.appendChild(option);
                    }
                });
            }
        } catch (error) {
            console.error('Error fetching seasons:', error);
        }
    }

    function setupSeasonEventListeners() {
        const closeSeasonBtn = document.getElementById('closeSeasonBtn');
        const prepareNextSeasonBtn = document.getElementById('prepareNextSeasonBtn');
        const seasonSelector = document.getElementById('seasonSelector');
        const confirmDownloadBtn = document.getElementById('confirmDownloadBtn');
        const confirmCloseSeasonBtn = document.getElementById('confirmCloseSeasonBtn');
        const closeSeasonYear = document.getElementById('closeSeasonYear');

        // Close season button now opens modal instead of directly closing
        // The modal will handle the actual close action

        if (prepareNextSeasonBtn) {
            prepareNextSeasonBtn.addEventListener('click', handlePrepareNextSeason);
        }

        if (seasonSelector) {
            seasonSelector.addEventListener('change', handleSeasonSelection);
        }

        if (confirmDownloadBtn) {
            confirmDownloadBtn.addEventListener('click', handleDownloadPreviousSeason);
        }

        if (confirmCloseSeasonBtn) {
            confirmCloseSeasonBtn.addEventListener('click', handleCloseSeason);
        }

        if (closeSeasonYear) {
            closeSeasonYear.addEventListener('change', updateCloseSeasonPreview);
        }

        // Clear all functionality
        const confirmClearAllCheck = document.getElementById('confirmClearAllCheck');
        const confirmClearAllBtn = document.getElementById('confirmClearAllBtn');
        
        if (confirmClearAllCheck) {
            confirmClearAllCheck.addEventListener('change', function() {
                if (confirmClearAllBtn) {
                    confirmClearAllBtn.disabled = !this.checked;
                }
            });
        }

        if (confirmClearAllBtn) {
            confirmClearAllBtn.addEventListener('click', handleClearAll);
        }

        // Create season functionality
        const confirmCreateSeasonBtn = document.getElementById('confirmCreateSeasonBtn');
        if (confirmCreateSeasonBtn) {
            confirmCreateSeasonBtn.addEventListener('click', handleCreateSeason);
        }

        // Manage seasons functionality
        const manageSeasonSelector = document.getElementById('manageSeasonSelector');
        const setActiveSeasonBtn = document.getElementById('setActiveSeasonBtn');
        const editSeasonBtn = document.getElementById('editSeasonBtn');
        const deleteSeasonBtn = document.getElementById('deleteSeasonBtn');
        const confirmEditSeasonBtn = document.getElementById('confirmEditSeasonBtn');
        const confirmDeleteSeasonBtn = document.getElementById('confirmDeleteSeasonBtn');
        const confirmDeleteSeasonCheck = document.getElementById('confirmDeleteSeasonCheck');

        if (manageSeasonSelector) {
            manageSeasonSelector.addEventListener('change', handleManageSeasonSelection);
        }

        if (setActiveSeasonBtn) {
            setActiveSeasonBtn.addEventListener('click', handleSetActiveSeason);
        }

        if (editSeasonBtn) {
            editSeasonBtn.addEventListener('click', handleEditSeason);
        }

        if (deleteSeasonBtn) {
            deleteSeasonBtn.addEventListener('click', handleDeleteSeason);
        }

        if (confirmEditSeasonBtn) {
            confirmEditSeasonBtn.addEventListener('click', handleConfirmEditSeason);
        }

        if (confirmDeleteSeasonBtn) {
            confirmDeleteSeasonBtn.addEventListener('click', handleConfirmDeleteSeason);
        }

        if (confirmDeleteSeasonCheck) {
            confirmDeleteSeasonCheck.addEventListener('change', function() {
                if (confirmDeleteSeasonBtn) {
                    confirmDeleteSeasonBtn.disabled = !this.checked;
                }
            });
        }

        // Populate manage seasons dropdown when modal opens
        const manageSeasonsModal = document.getElementById('manageSeasonsModal');
        if (manageSeasonsModal) {
            manageSeasonsModal.addEventListener('show.bs.modal', function() {
                populateManageSeasonsDropdown();
            });
        }

        // Process VM4 functionality
        const confirmProcessVm4Btn = document.getElementById('confirmProcessVm4Btn');
        if (confirmProcessVm4Btn) {
            confirmProcessVm4Btn.addEventListener('click', handleProcessVm4);
        }

        // Populate VM4 season dropdown when modal opens
        const processVm4Modal = document.getElementById('processVm4Modal');
        if (processVm4Modal) {
            processVm4Modal.addEventListener('show.bs.modal', function() {
                populateProcessVm4SeasonDropdown();
            });
        }

        // Set default year when create season modal opens
        const createSeasonModal = document.getElementById('createSeasonModal');
        if (createSeasonModal) {
            createSeasonModal.addEventListener('show.bs.modal', function() {
                const newSeasonYear = document.getElementById('newSeasonYear');
                if (newSeasonYear && !newSeasonYear.value) {
                    // Set to current year as default
                    newSeasonYear.value = new Date().getFullYear();
                }
            });
        }

        // Populate close season dropdown when modal is shown
        const closeSeasonModal = document.getElementById('closeSeasonModal');
        if (closeSeasonModal) {
            closeSeasonModal.addEventListener('show.bs.modal', function() {
                populateCloseSeasonDropdown();
            });
        }
    }

    function populateCloseSeasonDropdown() {
        const closeSeasonYear = document.getElementById('closeSeasonYear');
        if (!closeSeasonYear) return;

        // Clear existing options
        closeSeasonYear.innerHTML = '<option value="">Select a season...</option>';

        // Add active/open seasons (not yet closed)
        allSeasons.forEach(season => {
            if (season.is_active && !season.closed_at_utc) {
                const option = document.createElement('option');
                option.value = season.year;
                option.textContent = `${season.year}${season.is_active ? ' (Active)' : ''}`;
                closeSeasonYear.appendChild(option);
            }
        });

        // If there's an active season, select it by default
        if (activeSeason) {
            closeSeasonYear.value = activeSeason.year.toString();
            updateCloseSeasonPreview();
        }
    }

    function updateCloseSeasonPreview() {
        const closeSeasonYear = document.getElementById('closeSeasonYear');
        const preview = document.getElementById('closeSeasonPreview');
        const previewList = document.getElementById('closeSeasonPreviewList');

        if (!closeSeasonYear || !preview || !previewList) return;

        const selectedYear = closeSeasonYear.value;
        if (!selectedYear) {
            preview.style.display = 'none';
            return;
        }

        // Show preview of what will be closed
        preview.style.display = 'block';
        previewList.innerHTML = `
            <li><strong>Season Year:</strong> ${selectedYear}</li>
            <li>All stations for ${selectedYear} will be archived</li>
            <li>All offload logs for ${selectedYear} will be archived</li>
            <li>Season statistics will be generated</li>
            <li>Further modifications to archived data will be prevented</li>
        `;
    }

    async function handleCloseSeason() {
        const closeSeasonYear = document.getElementById('closeSeasonYear');
        const closeSeasonModal = bootstrap.Modal.getInstance(document.getElementById('closeSeasonModal'));

        if (!closeSeasonYear || !closeSeasonYear.value) {
            showToast('Please select a season to close', 'warning');
            return;
        }

        const year = parseInt(closeSeasonYear.value);

        // Final confirmation
        const confirmMessage = `Are you sure you want to close the ${year} field season?\n\n` +
            `This will:\n` +
            `- Archive all stations and offload logs for ${year}\n` +
            `- Generate season statistics\n` +
            `- Prevent further modifications to archived data\n\n` +
            `This action cannot be undone.`;

        if (!confirm(confirmMessage)) {
            return;
        }

        try {
            showToast('Closing season...', 'info');
            const result = await apiRequest(`/api/field_seasons/${year}/close`, 'POST');
            showToast(`Season ${year} closed successfully!`, 'success');
            
            // Close modal
            if (closeSeasonModal) {
                closeSeasonModal.hide();
            }
            
            // Refresh seasons and data
            await fetchAllSeasons();
            await fetchActiveSeason();
            await fetchStationStatuses();
            
            // Update statistics display on page
            await updateSeasonStatisticsDisplay(year);
            
            // Also show statistics in modal
            await showSeasonStatistics(year);
        } catch (error) {
            showToast(`Error closing season: ${error.message}`, 'danger');
            console.error('Error closing season:', error);
        }
    }

    async function handlePrepareNextSeason() {
        if (!activeSeason) {
            showToast('No active season found', 'warning');
            return;
        }

        try {
            // Export master list
            const url = `/api/field_seasons/${activeSeason.year}/master_list/export`;
            const response = await fetch(url, {
                method: 'GET',
                headers: {
                    'Authorization': `Bearer ${localStorage.getItem('accessToken')}`
                }
            });

            if (!response.ok) {
                throw new Error('Failed to export master list');
            }

            const blob = await response.blob();
            const downloadUrl = window.URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = downloadUrl;
            link.download = `master_list_${activeSeason.year}.csv`;
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            window.URL.revokeObjectURL(downloadUrl);

            showToast('Master list exported successfully! Edit and re-upload to create next season.', 'success');
        } catch (error) {
            showToast(`Error preparing master list: ${error.message}`, 'danger');
            console.error('Error preparing master list:', error);
        }
    }

    async function handleSeasonSelection(event) {
        const year = event.target.value ? parseInt(event.target.value) : null;
        selectedSeasonYear = year;
        
        // Refresh table with selected season filter
        await fetchStationStatuses();
        
        // Update statistics display
        // If no year selected, show active season stats if available
        if (year) {
            await updateSeasonStatisticsDisplay(year);
        } else if (activeSeason) {
            await updateSeasonStatisticsDisplay(activeSeason.year);
        } else {
            // Hide stats if no season available
            const seasonStatsDisplay = document.getElementById('seasonStatsDisplay');
            if (seasonStatsDisplay) {
                seasonStatsDisplay.style.display = 'none';
            }
        }
    }

    async function handleDownloadPreviousSeason() {
        const downloadSeasonYear = document.getElementById('downloadSeasonYear');
        const downloadStationType = document.getElementById('downloadStationType');
        const downloadModal = bootstrap.Modal.getInstance(document.getElementById('downloadPreviousSeasonModal'));

        if (!downloadSeasonYear || !downloadSeasonYear.value) {
            showToast('Please select a season year', 'warning');
            return;
        }

        const year = parseInt(downloadSeasonYear.value);
        const stationType = downloadStationType ? downloadStationType.value : null;

        try {
            let url = `/api/field_seasons/${year}/download`;
            if (stationType) {
                url += `?station_type=${encodeURIComponent(stationType)}`;
            }

            const response = await fetch(url, {
                method: 'GET',
                headers: {
                    'Authorization': `Bearer ${localStorage.getItem('accessToken')}`
                }
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || 'Failed to download data');
            }

            const blob = await response.blob();
            const downloadUrl = window.URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = downloadUrl;
            
            let filename = `station_offloads_${year}`;
            if (stationType) {
                filename += `_${stationType.toUpperCase()}`;
            }
            filename += '.csv';
            
            link.download = filename;
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            window.URL.revokeObjectURL(downloadUrl);

            showToast('Download started!', 'success');
            if (downloadModal) {
                downloadModal.hide();
            }
        } catch (error) {
            showToast(`Error downloading data: ${error.message}`, 'danger');
            console.error('Error downloading season data:', error);
        }
    }

    async function updateSeasonStatisticsDisplay(year) {
        const seasonStatsDisplay = document.getElementById('seasonStatsDisplay');
        const seasonStatsContent = document.getElementById('seasonStatsContent');
        
        if (!seasonStatsDisplay || !seasonStatsContent) return;
        
        // If no season selected, hide the display
        if (!year) {
            seasonStatsDisplay.style.display = 'none';
            return;
        }
        
        try {
            // Show loading state
            seasonStatsDisplay.style.display = 'block';
            seasonStatsContent.innerHTML = `
                <div class="text-center text-muted">
                    <i class="fas fa-spinner fa-spin me-2"></i>Loading statistics...
                </div>
            `;
            
            const statistics = await apiRequest(`/api/field_seasons/${year}/summary`, 'GET');
            
            // Format the statistics HTML
            let statsHtml = `
                <div class="row">
                    <div class="col-md-6">
                        <h6 class="text-info">Overview</h6>
                        <ul class="list-unstyled">
                            <li><strong>Total Stations:</strong> ${statistics.total_stations}</li>
                            <li><strong>Unique Stations Deployed:</strong> ${statistics.unique_stations_deployed}</li>
                            <li><strong>Total Offload Attempts:</strong> ${statistics.total_offload_attempts}</li>
                        </ul>
                    </div>
                    <div class="col-md-6">
                        <h6 class="text-info">Success Rates</h6>
                        <ul class="list-unstyled">
                            <li><strong>Successful Offloads:</strong> <span class="text-success">${statistics.successful_offloads}</span></li>
                            <li><strong>Failed Offloads:</strong> <span class="text-danger">${statistics.failed_offloads}</span></li>
                            ${statistics.failed_stations !== undefined ? `<li><strong>Failed Stations:</strong> <span class="text-danger">${statistics.failed_stations}</span></li>` : ''}
                            <li><strong>Skipped Stations:</strong> <span class="text-warning">${statistics.skipped_stations}</span></li>
                            <li><strong>Success Rate:</strong> <span class="fw-bold">${statistics.success_rate}%</span></li>
                        </ul>
                    </div>
                </div>
                <div class="row mt-3">
                    <div class="col-md-6">
                        <h6 class="text-info">Stations by Type</h6>
                        <ul class="list-unstyled">
                            ${Object.entries(statistics.stations_by_type || {}).map(([type, count]) => 
                                `<li><strong>${type}:</strong> ${count}</li>`
                            ).join('')}
                        </ul>
                    </div>
                    <div class="col-md-6">
                        <h6 class="text-info">Timing</h6>
                        <ul class="list-unstyled">
                            <li><strong>Average Time at Station:</strong> ${statistics.average_time_at_station_hours ? statistics.average_time_at_station_hours.toFixed(2) + ' hours' : 'N/A'}</li>
                            <li><strong>First Offload:</strong> ${statistics.first_offload_date ? new Date(statistics.first_offload_date).toLocaleString() : 'N/A'}</li>
                            <li><strong>Last Offload:</strong> ${statistics.last_offload_date ? new Date(statistics.last_offload_date).toLocaleString() : 'N/A'}</li>
                        </ul>
                    </div>
                </div>
            `;
            
            // Add connection attempt statistics if available
            if (statistics.total_connection_attempts !== undefined) {
                statsHtml += `
                    <div class="row mt-3">
                        <div class="col-12">
                            <h6 class="text-info">Connection Attempts</h6>
                            <div class="row">
                                <div class="col-md-3">
                                    <ul class="list-unstyled">
                                        <li><strong>Total Attempts:</strong> ${statistics.total_connection_attempts}</li>
                                        <li><strong>Stations with Attempts:</strong> ${statistics.stations_with_attempts || 0}</li>
                                    </ul>
                                </div>
                                <div class="col-md-3">
                                    <ul class="list-unstyled">
                                        <li><strong>Stations with Multiple Attempts:</strong> ${statistics.stations_with_multiple_attempts || 0}</li>
                                        <li><strong>Avg Attempts per Station:</strong> ${statistics.average_attempts_per_station || 0}</li>
                                    </ul>
                                </div>
                            </div>
                        </div>
                    </div>
                `;
            }
            
            // Add success by station type if available
            if (statistics.success_by_station_type && Object.keys(statistics.success_by_station_type).length > 0) {
                statsHtml += `
                    <div class="row mt-3">
                        <div class="col-12">
                            <h6 class="text-info">Success Rate by Station Type</h6>
                            <div class="table-responsive">
                                <table class="table table-sm table-dark">
                                    <thead>
                                        <tr>
                                            <th>Type</th>
                                            <th>Total</th>
                                            <th>Successful</th>
                                            <th>Failed</th>
                                            <th>Skipped</th>
                                            <th>Success Rate</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        ${Object.entries(statistics.success_by_station_type).map(([type, data]) => 
                                            `<tr>
                                                <td><strong>${type}</strong></td>
                                                <td>${data.total}</td>
                                                <td class="text-success">${data.successful}</td>
                                                <td class="text-danger">${data.failed}</td>
                                                <td class="text-warning">${data.skipped}</td>
                                                <td><strong>${data.success_rate}%</strong></td>
                                            </tr>`
                                        ).join('')}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    </div>
                `;
            }
            
            // Add success by mission if available
            if (statistics.success_by_mission && Object.keys(statistics.success_by_mission).length > 0) {
                statsHtml += `
                    <div class="row mt-3">
                        <div class="col-12">
                            <h6 class="text-info">Success Rate by Mission</h6>
                            <div class="table-responsive">
                                <table class="table table-sm table-dark">
                                    <thead>
                                        <tr>
                                            <th>Mission ID</th>
                                            <th>Total</th>
                                            <th>Successful</th>
                                            <th>Failed</th>
                                            <th>Skipped</th>
                                            <th>Success Rate</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        ${Object.entries(statistics.success_by_mission).map(([mission, data]) => 
                                            `<tr>
                                                <td><strong>${mission}</strong></td>
                                                <td>${data.total}</td>
                                                <td class="text-success">${data.successful}</td>
                                                <td class="text-danger">${data.failed}</td>
                                                <td class="text-warning">${data.skipped}</td>
                                                <td><strong>${data.success_rate}%</strong></td>
                                            </tr>`
                                        ).join('')}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    </div>
                `;
            }
            
            // Add detailed station attempt information if available
            if (statistics.station_attempt_details && Object.keys(statistics.station_attempt_details).length > 0) {
                // Show stations with multiple attempts in a collapsible section
                const stationsWithMultipleAttempts = Object.entries(statistics.station_attempt_details)
                    .filter(([stationId, details]) => details.attempt_count > 1)
                    .sort((a, b) => b[1].attempt_count - a[1].attempt_count);
                
                if (stationsWithMultipleAttempts.length > 0) {
                    statsHtml += `
                        <div class="row mt-3">
                            <div class="col-12">
                                <h6 class="text-info">
                                    <button class="btn btn-sm btn-outline-info" type="button" data-bs-toggle="collapse" data-bs-target="#stationAttemptDetails" aria-expanded="false">
                                        <i class="fas fa-chevron-down me-1"></i>Station Attempt Details (${stationsWithMultipleAttempts.length} stations with multiple attempts)
                                    </button>
                                </h6>
                                <div class="collapse mt-2" id="stationAttemptDetails">
                                    <div class="table-responsive">
                                        <table class="table table-sm table-dark">
                                            <thead>
                                                <tr>
                                                    <th>Station ID</th>
                                                    <th>Attempt Count</th>
                                                    <th>Attempt Timestamps</th>
                                                </tr>
                                            </thead>
                                            <tbody>
                                                ${stationsWithMultipleAttempts.map(([stationId, details]) => 
                                                    `<tr>
                                                        <td><strong>${stationId}</strong></td>
                                                        <td><span class="badge bg-warning">${details.attempt_count}</span></td>
                                                        <td>
                                                            <small>
                                                                ${details.attempt_timestamps.map(ts => 
                                                                    new Date(ts).toLocaleString()
                                                                ).join('<br>')}
                                                            </small>
                                                        </td>
                                                    </tr>`
                                                ).join('')}
                                            </tbody>
                                        </table>
                                    </div>
                                </div>
                            </div>
                        </div>
                    `;
                }
            }
            
            seasonStatsContent.innerHTML = statsHtml;
        } catch (error) {
            // If season doesn't have statistics yet (not closed), show a message
            if (error.message && error.message.includes('404')) {
                seasonStatsContent.innerHTML = `
                    <div class="alert alert-info mb-0">
                        <i class="fas fa-info-circle me-2"></i>
                        Statistics will be available after this season is closed.
                    </div>
                `;
            } else {
                seasonStatsContent.innerHTML = `
                    <div class="alert alert-warning mb-0">
                        <i class="fas fa-exclamation-triangle me-2"></i>
                        Error loading statistics: ${error.message}
                    </div>
                `;
                console.error('Error fetching season statistics:', error);
            }
        }
    }

    async function showSeasonStatistics(year) {
        try {
            const statistics = await apiRequest(`/api/field_seasons/${year}/summary`, 'GET');
            
            const modalBody = document.getElementById('seasonStatsModalBody');
            if (modalBody) {
                let modalHtml = `
                    <div class="row">
                        <div class="col-md-6">
                            <h6>Overview</h6>
                            <ul class="list-unstyled">
                                <li><strong>Total Stations:</strong> ${statistics.total_stations}</li>
                                <li><strong>Unique Stations Deployed:</strong> ${statistics.unique_stations_deployed}</li>
                                <li><strong>Total Offload Attempts:</strong> ${statistics.total_offload_attempts}</li>
                            </ul>
                        </div>
                        <div class="col-md-6">
                            <h6>Success Rates</h6>
                            <ul class="list-unstyled">
                                <li><strong>Successful Offloads:</strong> <span class="text-success">${statistics.successful_offloads}</span></li>
                                <li><strong>Failed Offloads:</strong> <span class="text-danger">${statistics.failed_offloads}</span></li>
                                ${statistics.failed_stations !== undefined ? `<li><strong>Failed Stations:</strong> <span class="text-danger">${statistics.failed_stations}</span></li>` : ''}
                                <li><strong>Skipped Stations:</strong> <span class="text-warning">${statistics.skipped_stations}</span></li>
                                <li><strong>Success Rate:</strong> <span class="fw-bold">${statistics.success_rate}%</span></li>
                            </ul>
                        </div>
                    </div>
                    <div class="row mt-3">
                        <div class="col-md-6">
                            <h6>Stations by Type</h6>
                            <ul class="list-unstyled">
                                ${Object.entries(statistics.stations_by_type || {}).map(([type, count]) => 
                                    `<li><strong>${type}:</strong> ${count}</li>`
                                ).join('')}
                            </ul>
                        </div>
                        <div class="col-md-6">
                            <h6>Timing</h6>
                            <ul class="list-unstyled">
                                <li><strong>Average Time at Station:</strong> ${statistics.average_time_at_station_hours ? statistics.average_time_at_station_hours.toFixed(2) + ' hours' : 'N/A'}</li>
                                <li><strong>First Offload:</strong> ${statistics.first_offload_date ? new Date(statistics.first_offload_date).toLocaleString() : 'N/A'}</li>
                                <li><strong>Last Offload:</strong> ${statistics.last_offload_date ? new Date(statistics.last_offload_date).toLocaleString() : 'N/A'}</li>
                            </ul>
                        </div>
                    </div>
                `;
                
                // Add connection attempt statistics if available
                if (statistics.total_connection_attempts !== undefined) {
                    modalHtml += `
                        <div class="row mt-3">
                            <div class="col-12">
                                <h6>Connection Attempts</h6>
                                <div class="row">
                                    <div class="col-md-3">
                                        <ul class="list-unstyled">
                                            <li><strong>Total Attempts:</strong> ${statistics.total_connection_attempts}</li>
                                            <li><strong>Stations with Attempts:</strong> ${statistics.stations_with_attempts || 0}</li>
                                        </ul>
                                    </div>
                                    <div class="col-md-3">
                                        <ul class="list-unstyled">
                                            <li><strong>Stations with Multiple Attempts:</strong> ${statistics.stations_with_multiple_attempts || 0}</li>
                                            <li><strong>Avg Attempts per Station:</strong> ${statistics.average_attempts_per_station || 0}</li>
                                        </ul>
                                    </div>
                                </div>
                            </div>
                        </div>
                    `;
                }
                
                // Add success by station type if available
                if (statistics.success_by_station_type && Object.keys(statistics.success_by_station_type).length > 0) {
                    modalHtml += `
                        <div class="row mt-3">
                            <div class="col-12">
                                <h6>Success Rate by Station Type</h6>
                                <div class="table-responsive">
                                    <table class="table table-sm">
                                        <thead>
                                            <tr>
                                                <th>Type</th>
                                                <th>Total</th>
                                                <th>Successful</th>
                                                <th>Failed</th>
                                                <th>Skipped</th>
                                                <th>Success Rate</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            ${Object.entries(statistics.success_by_station_type).map(([type, data]) => 
                                                `<tr>
                                                    <td><strong>${type}</strong></td>
                                                    <td>${data.total}</td>
                                                    <td class="text-success">${data.successful}</td>
                                                    <td class="text-danger">${data.failed}</td>
                                                    <td class="text-warning">${data.skipped}</td>
                                                    <td><strong>${data.success_rate}%</strong></td>
                                                </tr>`
                                            ).join('')}
                                        </tbody>
                                    </table>
                                </div>
                            </div>
                        </div>
                    `;
                }
                
                // Add success by mission if available
                if (statistics.success_by_mission && Object.keys(statistics.success_by_mission).length > 0) {
                    modalHtml += `
                        <div class="row mt-3">
                            <div class="col-12">
                                <h6>Success Rate by Mission</h6>
                                <div class="table-responsive">
                                    <table class="table table-sm">
                                        <thead>
                                            <tr>
                                                <th>Mission ID</th>
                                                <th>Total</th>
                                                <th>Successful</th>
                                                <th>Failed</th>
                                                <th>Skipped</th>
                                                <th>Success Rate</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            ${Object.entries(statistics.success_by_mission).map(([mission, data]) => 
                                                `<tr>
                                                    <td><strong>${mission}</strong></td>
                                                    <td>${data.total}</td>
                                                    <td class="text-success">${data.successful}</td>
                                                    <td class="text-danger">${data.failed}</td>
                                                    <td class="text-warning">${data.skipped}</td>
                                                    <td><strong>${data.success_rate}%</strong></td>
                                                </tr>`
                                            ).join('')}
                                        </tbody>
                                    </table>
                                </div>
                            </div>
                        </div>
                    `;
                }
                
                // Add connection attempt statistics if available
                if (statistics.total_connection_attempts !== undefined) {
                    modalHtml += `
                        <div class="row mt-3">
                            <div class="col-12">
                                <h6>Connection Attempts</h6>
                                <div class="row">
                                    <div class="col-md-3">
                                        <ul class="list-unstyled">
                                            <li><strong>Total Attempts:</strong> ${statistics.total_connection_attempts}</li>
                                            <li><strong>Stations with Attempts:</strong> ${statistics.stations_with_attempts || 0}</li>
                                        </ul>
                                    </div>
                                    <div class="col-md-3">
                                        <ul class="list-unstyled">
                                            <li><strong>Stations with Multiple Attempts:</strong> ${statistics.stations_with_multiple_attempts || 0}</li>
                                            <li><strong>Avg Attempts per Station:</strong> ${statistics.average_attempts_per_station || 0}</li>
                                        </ul>
                                    </div>
                                </div>
                            </div>
                        </div>
                    `;
                }
                
                // Add detailed station attempt information if available
                if (statistics.station_attempt_details && Object.keys(statistics.station_attempt_details).length > 0) {
                    // Show stations with multiple attempts in a collapsible section
                    const stationsWithMultipleAttempts = Object.entries(statistics.station_attempt_details)
                        .filter(([stationId, details]) => details.attempt_count > 1)
                        .sort((a, b) => b[1].attempt_count - a[1].attempt_count);
                    
                    if (stationsWithMultipleAttempts.length > 0) {
                        modalHtml += `
                            <div class="row mt-3">
                                <div class="col-12">
                                    <h6>
                                        <button class="btn btn-sm btn-outline-secondary" type="button" data-bs-toggle="collapse" data-bs-target="#modalStationAttemptDetails" aria-expanded="false">
                                            <i class="fas fa-chevron-down me-1"></i>Station Attempt Details (${stationsWithMultipleAttempts.length} stations with multiple attempts)
                                        </button>
                                    </h6>
                                    <div class="collapse mt-2" id="modalStationAttemptDetails">
                                        <div class="table-responsive">
                                            <table class="table table-sm">
                                                <thead>
                                                    <tr>
                                                        <th>Station ID</th>
                                                        <th>Attempt Count</th>
                                                        <th>Attempt Timestamps</th>
                                                    </tr>
                                                </thead>
                                                <tbody>
                                                    ${stationsWithMultipleAttempts.map(([stationId, details]) => 
                                                        `<tr>
                                                            <td><strong>${stationId}</strong></td>
                                                            <td><span class="badge bg-warning">${details.attempt_count}</span></td>
                                                            <td>
                                                                <small>
                                                                    ${details.attempt_timestamps.map(ts => 
                                                                        new Date(ts).toLocaleString()
                                                                    ).join('<br>')}
                                                                </small>
                                                            </td>
                                                        </tr>`
                                                    ).join('')}
                                                </tbody>
                                            </table>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        `;
                    }
                }
                
                modalBody.innerHTML = modalHtml;
            }

            const modal = new bootstrap.Modal(document.getElementById('seasonStatsModal'));
            modal.show();
        } catch (error) {
            showToast(`Error fetching statistics: ${error.message}`, 'danger');
            console.error('Error fetching season statistics:', error);
        }
    }

    // Note: Season filtering would require API endpoint modification
    // For now, the status_overview endpoint shows current active season data

    async function handleClearAll() {
        const confirmClearAllCheck = document.getElementById('confirmClearAllCheck');
        const clearAllModal = bootstrap.Modal.getInstance(document.getElementById('clearAllModal'));

        if (!confirmClearAllCheck || !confirmClearAllCheck.checked) {
            showToast('Please confirm that you understand this will delete all data', 'warning');
            return;
        }

        // Final confirmation
        const finalConfirm = confirm(
            'FINAL WARNING: This will permanently delete ALL stations and offload logs.\n\n' +
            'This action cannot be undone.\n\n' +
            'Are you absolutely sure you want to proceed?'
        );

        if (!finalConfirm) {
            return;
        }

        try {
            showToast('Clearing all data...', 'info');
            const result = await apiRequest('/api/stations/clear_all?confirm=true', 'DELETE');
            
            // Close modal
            if (clearAllModal) {
                clearAllModal.hide();
            }
            
            // Reset checkbox
            if (confirmClearAllCheck) {
                confirmClearAllCheck.checked = false;
            }
            const confirmClearAllBtn = document.getElementById('confirmClearAllBtn');
            if (confirmClearAllBtn) {
                confirmClearAllBtn.disabled = true;
            }
            
            showToast('All data cleared successfully', 'success');
            
            // Refresh data (will be empty now)
            await fetchStationStatuses();
            await fetchAllSeasons();
            await fetchActiveSeason();
        } catch (error) {
            showToast(`Error clearing data: ${error.message}`, 'danger');
            console.error('Error clearing all data:', error);
        }
    }

    function populateManageSeasonsDropdown() {
        const manageSeasonSelector = document.getElementById('manageSeasonSelector');
        if (!manageSeasonSelector) return;

        manageSeasonSelector.innerHTML = '<option value="">Select a season...</option>';
        allSeasons.forEach(season => {
            const option = document.createElement('option');
            option.value = season.year;
            option.textContent = `${season.year}${season.is_active ? ' (Active)' : ' (Closed)'}`;
            manageSeasonSelector.appendChild(option);
        });
    }

    async function handleManageSeasonSelection(event) {
        const year = event.target.value ? parseInt(event.target.value) : null;
        const seasonDetailsDisplay = document.getElementById('seasonDetailsDisplay');
        const setActiveSeasonBtn = document.getElementById('setActiveSeasonBtn');
        const editSeasonBtn = document.getElementById('editSeasonBtn');
        const deleteSeasonBtn = document.getElementById('deleteSeasonBtn');

        if (!year) {
            if (seasonDetailsDisplay) seasonDetailsDisplay.style.display = 'none';
            if (setActiveSeasonBtn) setActiveSeasonBtn.disabled = true;
            if (editSeasonBtn) editSeasonBtn.disabled = true;
            if (deleteSeasonBtn) deleteSeasonBtn.disabled = true;
            return;
        }

        const season = allSeasons.find(s => s.year === year);
        if (!season) {
            showToast('Season not found', 'warning');
            return;
        }

        // Display season details
        if (seasonDetailsDisplay) {
            seasonDetailsDisplay.innerHTML = `
                <div class="card bg-secondary">
                    <div class="card-body">
                        <h6>Season Details</h6>
                        <ul class="list-unstyled mb-0">
                            <li><strong>Year:</strong> ${season.year}</li>
                            <li><strong>Status:</strong> ${season.is_active ? 'Active' : 'Closed'}</li>
                            <li><strong>Created:</strong> ${new Date(season.created_at_utc).toLocaleString()}</li>
                            ${season.closed_at_utc ? `<li><strong>Closed:</strong> ${new Date(season.closed_at_utc).toLocaleString()}</li>` : ''}
                            ${season.closed_by_username ? `<li><strong>Closed By:</strong> ${season.closed_by_username}</li>` : ''}
                        </ul>
                    </div>
                </div>
            `;
            seasonDetailsDisplay.style.display = 'block';
        }

        // Enable/disable buttons based on season state
        if (setActiveSeasonBtn) {
            setActiveSeasonBtn.disabled = season.is_active;
        }
        if (editSeasonBtn) {
            editSeasonBtn.disabled = false;
        }
        if (deleteSeasonBtn) {
            deleteSeasonBtn.disabled = season.is_active; // Can't delete active season
        }
    }

    async function handleSetActiveSeason() {
        const manageSeasonSelector = document.getElementById('manageSeasonSelector');
        if (!manageSeasonSelector || !manageSeasonSelector.value) {
            showToast('Please select a season', 'warning');
            return;
        }

        const year = parseInt(manageSeasonSelector.value);
        const finalConfirm = confirm(
            `Set season ${year} as the active season?\n\n` +
            `This will deactivate all other seasons.`
        );

        if (!finalConfirm) {
            return;
        }

        try {
            showToast('Setting active season...', 'info');
            const result = await apiRequest(`/api/field_seasons/${year}/set_active`, 'POST');
            showToast(`Season ${year} is now active!`, 'success');
            
            // Refresh data
            await fetchAllSeasons();
            await fetchActiveSeason();
            await fetchStationStatuses();
            
            // Close modal
            const manageSeasonsModal = bootstrap.Modal.getInstance(document.getElementById('manageSeasonsModal'));
            if (manageSeasonsModal) {
                manageSeasonsModal.hide();
            }
        } catch (error) {
            showToast(`Error setting active season: ${error.message}`, 'danger');
            console.error('Error setting active season:', error);
        }
    }

    function handleEditSeason() {
        const manageSeasonSelector = document.getElementById('manageSeasonSelector');
        if (!manageSeasonSelector || !manageSeasonSelector.value) {
            showToast('Please select a season', 'warning');
            return;
        }

        const year = parseInt(manageSeasonSelector.value);
        const season = allSeasons.find(s => s.year === year);
        if (!season) {
            showToast('Season not found', 'warning');
            return;
        }

        // Populate edit modal
        const editSeasonYear = document.getElementById('editSeasonYear');
        const editSeasonIsActive = document.getElementById('editSeasonIsActive');
        
        if (editSeasonYear) editSeasonYear.value = year;
        if (editSeasonIsActive) editSeasonIsActive.checked = season.is_active;

        // Show edit modal
        const editSeasonModal = new bootstrap.Modal(document.getElementById('editSeasonModal'));
        editSeasonModal.show();
    }

    async function handleConfirmEditSeason() {
        const editSeasonYear = document.getElementById('editSeasonYear');
        const editSeasonIsActive = document.getElementById('editSeasonIsActive');
        const editSeasonModal = bootstrap.Modal.getInstance(document.getElementById('editSeasonModal'));

        if (!editSeasonYear || !editSeasonYear.value) {
            showToast('Season year not found', 'warning');
            return;
        }

        const year = parseInt(editSeasonYear.value);
        const isActive = editSeasonIsActive ? editSeasonIsActive.checked : false;

        try {
            showToast('Updating season...', 'info');
            const updateData = {
                is_active: isActive
            };

            const result = await apiRequest(`/api/field_seasons/${year}`, 'PUT', updateData);
            showToast(`Season ${year} updated successfully!`, 'success');
            
            // Close modal
            if (editSeasonModal) {
                editSeasonModal.hide();
            }
            
            // Refresh data
            await fetchAllSeasons();
            await fetchActiveSeason();
            
            // Refresh manage seasons dropdown
            populateManageSeasonsDropdown();
        } catch (error) {
            showToast(`Error updating season: ${error.message}`, 'danger');
            console.error('Error updating season:', error);
        }
    }

    function handleDeleteSeason() {
        const manageSeasonSelector = document.getElementById('manageSeasonSelector');
        if (!manageSeasonSelector || !manageSeasonSelector.value) {
            showToast('Please select a season', 'warning');
            return;
        }

        const year = parseInt(manageSeasonSelector.value);
        const season = allSeasons.find(s => s.year === year);
        if (!season) {
            showToast('Season not found', 'warning');
            return;
        }

        if (season.is_active) {
            showToast('Cannot delete the active season. Set another season as active first.', 'warning');
            return;
        }

        // Show delete modal
        const deleteSeasonModal = new bootstrap.Modal(document.getElementById('deleteSeasonModal'));
        deleteSeasonModal.show();
        
        // Store the year in the modal for confirmation
        const deleteSeasonYearInput = document.createElement('input');
        deleteSeasonYearInput.type = 'hidden';
        deleteSeasonYearInput.id = 'deleteSeasonYearValue';
        deleteSeasonYearInput.value = year;
        const deleteSeasonModalBody = document.getElementById('deleteSeasonModal').querySelector('.modal-body');
        if (deleteSeasonModalBody && !document.getElementById('deleteSeasonYearValue')) {
            deleteSeasonModalBody.appendChild(deleteSeasonYearInput);
        } else if (document.getElementById('deleteSeasonYearValue')) {
            document.getElementById('deleteSeasonYearValue').value = year;
        }
    }

    async function handleConfirmDeleteSeason() {
        const confirmDeleteSeasonCheck = document.getElementById('confirmDeleteSeasonCheck');
        const deleteSeasonModal = bootstrap.Modal.getInstance(document.getElementById('deleteSeasonModal'));
        const deleteSeasonYearValue = document.getElementById('deleteSeasonYearValue');

        if (!confirmDeleteSeasonCheck || !confirmDeleteSeasonCheck.checked) {
            showToast('Please confirm deletion', 'warning');
            return;
        }

        if (!deleteSeasonYearValue || !deleteSeasonYearValue.value) {
            showToast('Season year not found', 'warning');
            return;
        }

        const year = parseInt(deleteSeasonYearValue.value);

        const finalConfirm = confirm(
            `FINAL WARNING: Delete season ${year}?\n\n` +
            `This will delete the season record only.\n` +
            `Stations and offload logs will remain in the database.\n\n` +
            `This action cannot be undone.`
        );

        if (!finalConfirm) {
            return;
        }

        try {
            showToast('Deleting season...', 'info');
            const result = await apiRequest(`/api/field_seasons/${year}?confirm=true`, 'DELETE');
            showToast(`Season ${year} deleted successfully!`, 'success');
            
            // Close modal
            if (deleteSeasonModal) {
                deleteSeasonModal.hide();
            }
            
            // Reset checkbox
            if (confirmDeleteSeasonCheck) {
                confirmDeleteSeasonCheck.checked = false;
            }
            const confirmDeleteSeasonBtn = document.getElementById('confirmDeleteSeasonBtn');
            if (confirmDeleteSeasonBtn) {
                confirmDeleteSeasonBtn.disabled = true;
            }
            
            // Refresh data
            await fetchAllSeasons();
            await fetchActiveSeason();
            populateManageSeasonsDropdown();
        } catch (error) {
            showToast(`Error deleting season: ${error.message}`, 'danger');
            console.error('Error deleting season:', error);
        }
    }

    function populateProcessVm4SeasonDropdown() {
        const processVm4SeasonYear = document.getElementById('processVm4SeasonYear');
        if (!processVm4SeasonYear) return;

        // Keep the default option
        processVm4SeasonYear.innerHTML = '<option value="">Use station\'s season or active season (default)</option>';
        
        // Add all seasons
        if (allSeasons && allSeasons.length > 0) {
            allSeasons.forEach(season => {
                const option = document.createElement('option');
                option.value = season.year;
                option.textContent = `${season.year}${season.is_active ? ' (Active)' : season.closed_at_utc ? ' (Closed)' : ''}`;
                processVm4SeasonYear.appendChild(option);
            });
        }
    }

    async function handleProcessVm4() {
        const processVm4MissionId = document.getElementById('processVm4MissionId');
        const processVm4Force = document.getElementById('processVm4Force');
        const processVm4SeasonYear = document.getElementById('processVm4SeasonYear');
        const processVm4Result = document.getElementById('processVm4Result');
        const processVm4Modal = bootstrap.Modal.getInstance(document.getElementById('processVm4Modal'));

        if (!processVm4MissionId || !processVm4MissionId.value.trim()) {
            showToast('Please enter a mission ID', 'warning');
            return;
        }

        const missionId = processVm4MissionId.value.trim();
        const force = processVm4Force ? processVm4Force.checked : false;
        const fieldSeasonYear = processVm4SeasonYear && processVm4SeasonYear.value ? parseInt(processVm4SeasonYear.value) : null;

        try {
            if (processVm4Result) {
                processVm4Result.innerHTML = '<div class="alert alert-info">Processing VM4 offloads...</div>';
            }
            showToast('Processing VM4 offloads...', 'info');

            let url = `/api/missions/${encodeURIComponent(missionId)}/process_vm4_offloads`;
            const params = [];
            if (force) {
                params.push('force=true');
            }
            if (fieldSeasonYear) {
                params.push(`field_season_year=${fieldSeasonYear}`);
            }
            if (params.length > 0) {
                url += '?' + params.join('&');
            }

            const result = await apiRequest(url, 'POST');
            
            // Display results
            if (processVm4Result) {
                let resultHtml = `<div class="alert alert-success">${result.message}</div>`;
                if (result.field_season_year) {
                    resultHtml += `<div class="alert alert-info">All offload logs assigned to field season ${result.field_season_year}</div>`;
                }
                if (result.remote_health && Object.keys(result.remote_health).length > 0) {
                    resultHtml += `<div class="alert alert-secondary"><strong>Remote Health attach:</strong> ` +
                        `rows=${result.remote_health.rows_processed ?? 0}, ` +
                        `updated=${result.remote_health.logs_updated ?? 0}, ` +
                        `stations_matched=${result.remote_health.stations_matched ?? 0}, ` +
                        `no_station=${result.remote_health.no_station ?? 0}, ` +
                        `no_matching_log=${result.remote_health.no_matching_log ?? 0}` +
                        `</div>`;
                }
                if (result.statistics) {
                    resultHtml += '<div class="mt-3"><h6>Processing Statistics:</h6><ul class="list-group">';
                    Object.entries(result.statistics).forEach(([key, value]) => {
                        resultHtml += `<li class="list-group-item bg-dark text-light"><strong>${key}:</strong> ${value}</li>`;
                    });
                    resultHtml += '</ul></div>';
                }
                processVm4Result.innerHTML = resultHtml;
            }

            showToast('VM4 processing completed!', 'success');
            
            // Refresh station data
            await fetchStationStatuses();
        } catch (error) {
            showToast(`Error processing VM4 offloads: ${error.message}`, 'danger');
            if (processVm4Result) {
                processVm4Result.innerHTML = `<div class="alert alert-danger">Error: ${error.message}</div>`;
            }
            console.error('Error processing VM4 offloads:', error);
        }
    }

    async function handleCreateSeason() {
        const newSeasonYear = document.getElementById('newSeasonYear');
        const setAsActiveCheck = document.getElementById('setAsActiveCheck');
        const createSeasonModal = bootstrap.Modal.getInstance(document.getElementById('createSeasonModal'));

        if (!newSeasonYear || !newSeasonYear.value) {
            showToast('Please enter a season year', 'warning');
            return;
        }

        const year = parseInt(newSeasonYear.value);
        if (isNaN(year) || year < 2000 || year > 2100) {
            showToast('Please enter a valid year between 2000 and 2100', 'warning');
            return;
        }

        try {
            showToast('Creating season...', 'info');
            const seasonData = {
                year: year,
                is_active: setAsActiveCheck ? setAsActiveCheck.checked : true
            };

            const result = await apiRequest('/api/field_seasons/', 'POST', seasonData);
            
            // Close modal
            if (createSeasonModal) {
                createSeasonModal.hide();
            }
            
            // Reset form
            if (newSeasonYear) newSeasonYear.value = '';
            if (setAsActiveCheck) setAsActiveCheck.checked = true;
            
            showToast(`Season ${year} created successfully!`, 'success');
            
            // Refresh seasons and data
            await fetchAllSeasons();
            await fetchActiveSeason();
            await fetchStationStatuses();
        } catch (error) {
            showToast(`Error creating season: ${error.message}`, 'danger');
            console.error('Error creating season:', error);
        }
    }
});