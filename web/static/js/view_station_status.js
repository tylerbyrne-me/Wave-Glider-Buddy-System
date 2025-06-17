document.addEventListener('DOMContentLoaded', async function () { 
    const stationStatusTableBody = document.getElementById('stationStatusTableBody');
    const searchInput = document.getElementById('searchInput');
    const loadingSpinner = document.getElementById('loadingSpinner');
    const downloadCsvBtn = document.getElementById('downloadCsvBtn');
    const downloadCsvDropdownToggle = document.getElementById('downloadCsvDropdownToggle');

    // New modal and form elements
    const editLogStationModalEl = document.getElementById('editLogStationModal');
    const stationEditLogForm = document.getElementById('stationEditLogForm');

    let allStationsData = [];
    let currentSort = { column: 'station_id', order: 'asc' };
    let isAdmin = false;

    // Function to initialize the page: check role, then fetch data
    async function initializePage() {
        if (loadingSpinner) loadingSpinner.style.display = 'block'; // Show spinner early
        if (stationStatusTableBody) {
            // Update colspan to 7 for the new table structure
            stationStatusTableBody.innerHTML = '<tr><td colspan="7" class="text-center">Initializing...</td></tr>';
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
            } else {
                isAdmin = false;
                if (downloadCsvBtn) downloadCsvBtn.style.display = 'none'; // Hide for non-admin
                if (downloadCsvDropdownToggle) downloadCsvDropdownToggle.style.display = 'none';
            }
        } catch (error) {
            console.warn("Could not determine user role for edit functionality.", error);
            isAdmin = false; // Default to non-admin on error
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
            // fetchWithAuth should be available from auth.js
            if (typeof fetchWithAuth !== 'function') {
                throw new Error("fetchWithAuth function is not available. auth.js might not be loaded correctly.");
            }
            const response = await fetchWithAuth('/api/stations/status_overview');
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({ detail: 'Failed to fetch station statuses' }));
                throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
            }
            allStationsData = await response.json();
            renderTable(allStationsData);
        } catch (error) {
            console.error('Error fetching station statuses:', error);
            stationStatusTableBody.innerHTML = `<tr><td colspan="7" class="text-center text-danger">Error loading data: ${error.message}</td></tr>`;
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
                stationStatusTableBody.innerHTML = `<tr><td colspan="7" class="text-center">No stations match your filter "${currentFilter}".</td></tr>`;
            } else {
                stationStatusTableBody.innerHTML = '<tr><td colspan="7" class="text-center">No station data available.</td></tr>';
            }
            return;
        }

        stationsToRender.forEach(station => {
            const row = stationStatusTableBody.insertRow();
            const idCell = row.insertCell();
            // For the main table, station_id comes from the status_overview endpoint
            const displayStationId = station.station_id || 'N/A';

            if (isAdmin) {
                const editButton = document.createElement('button');
                editButton.classList.add('btn', 'btn-sm', 'btn-outline-primary');
                editButton.textContent = displayStationId;
                editButton.title = `Edit / Log for ${displayStationId}`;
                editButton.onclick = () => openEditLogModal(station.station_id); // station.station_id is the key
                idCell.appendChild(editButton);
            } else {
                idCell.textContent = displayStationId;
            }

            row.insertCell().textContent = station.serial_number || 'N/A';
            row.insertCell().textContent = station.modem_address !== null ? station.modem_address : 'N/A';
            row.insertCell().textContent = station.station_settings || '---'; // New column

            // --- Status Cell Text and Row Coloring ---            
            const statusCell = row.insertCell();
            statusCell.textContent = station.status_text || 'N/A'; // Text comes directly from backend
            
            row.insertCell().textContent = station.last_offload_timestamp_str || 'N/A'; // Renamed to "Last Log Update"
            row.insertCell().textContent = station.vrl_file_name || '---'; // New column
            // Clear all potential status color classes from the row first
            row.classList.remove(
                'status-awaiting-offload', 'status-offloaded', 'status-failed-offload',
                'status-skipped', 'status-unknown'
                // Also remove old classes if they were different and might conflict
                // 'status-up-to-date', 'status-needs-attention', 'status-pending-overdue', 'status-never-offloaded'
            );
            // Apply new class based on station.status_color (which is a key from backend)
            if (station.status_color === 'grey') {
                row.classList.add('status-awaiting-offload');
            } else if (station.status_color === 'green') { // Or "blue" if backend sends that for offloaded
                row.classList.add('status-offloaded');
            } else if (station.status_color === 'red') {
                row.classList.add('status-failed-offload');
            } else if (station.status_color === 'yellow' || station.status_color === 'orange') { // For skipped
                row.classList.add('status-skipped');
            } else {
                row.classList.add('status-unknown'); // Fallback for any other color_key or "Unknown" status_text
            }
        });
        updateSortIcons();
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

    async function openEditLogModal(stationId) {
        if (!isAdmin || !editLogStationModalInstance) return;
        
        currentEditingStationId = stationId;
        if (stationEditLogForm) stationEditLogForm.reset(); // Clear previous data
        
        document.getElementById('modalStationIdDisplay').textContent = stationId;
        document.getElementById('formStationId').value = stationId; // Hidden input

        if (loadingSpinner) loadingSpinner.style.display = 'block';

        try {
            const response = await fetchWithAuth(`/api/station_metadata/${stationId}`);
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({ detail: 'Failed to fetch station details.' }));
                throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
            }

            const stationData = await response.json();

            // Populate Station Information
            document.getElementById('formSerialNumber').value = stationData.serial_number || '';
            document.getElementById('formModemAddress').value = stationData.modem_address !== null ? stationData.modem_address : '';
            document.getElementById('formBottomDepth').value = stationData.bottom_depth_m !== null ? stationData.bottom_depth_m : '';
            document.getElementById('formWaypointNumber').value = stationData.waypoint_number || '';
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
            const localDate = new Date(val);
            if (!isNaN(localDate.valueOf())) {
                return localDate.toISOString();
            }
        }
        return null;
    }

    const saveStationInfoBtn = document.getElementById('saveStationInfoBtn');
    if (saveStationInfoBtn) {
        saveStationInfoBtn.addEventListener('click', async () => {
        if (!currentEditingStationId) return;
        if (loadingSpinner) loadingSpinner.style.display = 'block';

        const payload = {
            serial_number: document.getElementById('formSerialNumber').value.trim() || null,
            modem_address: parseInt(document.getElementById('formModemAddress').value.trim(), 10) || null,
            bottom_depth_m: parseFloat(document.getElementById('formBottomDepth').value) || null,
            waypoint_number: document.getElementById('formWaypointNumber').value.trim() || null,
            last_offload_by_glider: document.getElementById('formLastOffloadByGlider').value.trim() || null,
            station_settings: document.getElementById('formStationSettings').value.trim() || null,
            notes: document.getElementById('formStationNotes').value.trim() || null
        };
        // Handle display_status_override explicitly to send null if empty string
        let overrideStatus = document.getElementById('formDisplayStatusOverride').value;
        payload.display_status_override = overrideStatus === "" ? null : overrideStatus;
        // Filter out null values if backend expects only provided fields
        Object.keys(payload).forEach(key => (payload[key] === null || payload[key] === '') && delete payload[key]);
        if (payload.modem_address && isNaN(payload.modem_address)) delete payload.modem_address;
        if (payload.bottom_depth_m && isNaN(payload.bottom_depth_m)) delete payload.bottom_depth_m;

        try {
            const response = await fetchWithAuth(`/api/station_metadata/${currentEditingStationId}`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(payload)
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({ detail: 'Failed to save station info.' }));
                throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
            }
            
            await fetchStationStatuses();
            if (editLogStationModalInstance) editLogStationModalInstance.hide();
            alert('Station information saved successfully!');
        } catch (error) {
            console.error("Error saving station info:", error);
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
                arrival_date: getIsoFromDatetimeLocal('formArrivalDate'),
                distance_command_sent_m: parseFloat(document.getElementById('formDistanceSent').value) || null,
                time_first_command_sent_utc: getIsoFromDatetimeLocal('formTimeFirstCommand'),
                offload_start_time_utc: getIsoFromDatetimeLocal('formOffloadStartTime'),
                offload_end_time_utc: getIsoFromDatetimeLocal('formOffloadEndTime'),
                departure_date: getIsoFromDatetimeLocal('formDepartureDate'),
                was_offloaded: document.getElementById('formWasOffloaded').checked,
                vrl_file_name: document.getElementById('formVrlFileName').value.trim() || null,
                offload_notes_file_size: document.getElementById('formOffloadNotesFileSize').value.trim() || null,
            };
             // Filter out null values if backend expects only provided fields
            Object.keys(payload).forEach(key => payload[key] === null && delete payload[key]);
             if (payload.distance_command_sent_m && isNaN(payload.distance_command_sent_m)) delete payload.distance_command_sent_m;

            try {
                const response = await fetchWithAuth(`/api/station_metadata/${currentEditingStationId}/offload_logs/`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({ detail: 'Failed to log new offload.' }));
                    throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
                }
                await fetchStationStatuses(); // Refresh table
                alert('New offload logged successfully!');
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
                console.error("Error logging new offload:", error);
                alert(`Error: ${error.message}`);
            } finally {
                if (loadingSpinner) loadingSpinner.style.display = 'none';
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
    await initializePage();
});