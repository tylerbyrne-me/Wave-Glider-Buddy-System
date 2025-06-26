document.addEventListener('DOMContentLoaded', async function () {
    // This function was moved from schedule.html to make this script more self-contained.
    async function initializeCurrentUserForScheduler() {
        if (typeof getUserProfile === 'function') {
            window.currentUser = await getUserProfile(); // from auth.js
            if (!window.currentUser) {
                console.warn("Schedule page: Current user not available. Interactive features might be limited.");
            }
        } else {
            console.error("Schedule page: getUserProfile function not found. Ensure auth.js is loaded before schedule.js.");
        }
    }
    await initializeCurrentUserForScheduler(); // Wait for user to be fetched

    // Explicitly check if the FullCalendar library has loaded.
    if (typeof FullCalendar === 'undefined') {
        console.error('FullCalendar is not loaded. Please check the script path in schedule.html and ensure the file is accessible.');
        document.getElementById('calendar').innerHTML = '<div class="alert alert-danger" role="alert"><strong>Error:</strong> Could not load the calendar library. Please check the file path.</div>';
        return; // Stop execution
    }

    if (typeof checkAuth === 'function' && !checkAuth()) {
        console.log("Schedule.js: checkAuth() failed. Aborting calendar initialization.");
        return;
    }

    // UI Elements
    const calendarEl = document.getElementById('calendar');
    const dateRangeDisplay = document.getElementById('dateRangeDisplay');

    // Download Controls
    const downloadStartDateInput = document.getElementById('downloadStartDate');
    const downloadEndDateInput = document.getElementById('downloadEndDate');
    const downloadFormatSelect = document.getElementById('downloadFormat');
    const downloadUserScopeSelect = document.getElementById('downloadUserScope');
    const downloadScheduleBtn = document.getElementById('downloadScheduleBtn');

    // Block Out Time Modal Elements
    const blockTimeBtn = document.getElementById('blockTimeBtn');
    const blockTimeModal = new bootstrap.Modal(document.getElementById('blockTimeModal'));
    const unavailabilityStartDateInput = document.getElementById('unavailabilityStartDate');
    const unavailabilityEndDateInput = document.getElementById('unavailabilityEndDate');
    const unavailabilityReasonInput = document.getElementById('unavailabilityReason');
    const submitBlockTimeBtn = document.getElementById('submitBlockTimeBtn');
    const blockTimeErrorDiv = document.getElementById('blockTimeError');

    let mainCalendar; // Only one calendar instance now


    // --- FullCalendar Initialization ---
    mainCalendar = new FullCalendar.Calendar(calendarEl, {
        initialView: 'dayGridMonth', // Default view is month
        timeZone: 'local', // Explicitly set to local timezone for display
        headerToolbar: {
            left: 'prev,next today', // Navigation buttons
            center: 'title', // Month/Week/Day title
            right: 'dayGridMonth,timeGridWeek,timeGridDay,listWeek' // View buttons
        },        allDaySlot: true, // Enable the all-day slot to display unavailability
        dayMaxEvents: 3, // Show 3 events max before displaying a "+more" link
        eventMinHeight: 20, // Ensure events have a minimum height even without text
        height: 'auto', // Adjust height to content
        slotMinTime: "00:00:00",
        slotMaxTime: "24:00:00",
        selectable: true,
        selectMirror: true,
        nowIndicator: true,

        // Fetch events from our backend
        // This will be set later by mainCalendar.setOption('events', ...)

        // Handle creating a new shift
        select: async function(selectionInfo) {
            if (!window.currentUser || !window.currentUser.username) {
                alert("Error: User information not available. Please log in again.");
                return;
            }

            const modalTitle = `Sign up for shift on ${selectionInfo.start.toLocaleDateString()} from ${selectionInfo.start.toLocaleTimeString()} to ${selectionInfo.end.toLocaleTimeString()}?`;
            if (confirm(modalTitle)) {
                // --- Timezone Correction ---
                // The server is likely performing a double UTC conversion. To counteract this,
                // we adjust the time on the client before sending it. We convert the local
                // time (e.g., 2:00 AM ADT) to a new Date object that represents the same
                // clock time in UTC (2:00 AM UTC).
                const start = selectionInfo.start;
                const end = selectionInfo.end;

                // getTimezoneOffset() returns the difference in minutes between UTC and local time.
                // For ADT (UTC-3), this is 180. We subtract this offset.
                const offsetMinutes = start.getTimezoneOffset();
                const correctedStart = new Date(start.getTime() - (offsetMinutes * 60 * 1000));
                const correctedEnd = new Date(end.getTime() - (offsetMinutes * 60 * 1000));

                const newEventData = {
                    start: correctedStart.toISOString(),
                    end: correctedEnd.toISOString(),
                    resource: 'default', // FullCalendar needs a resource, even if not displayed
                    text: window.currentUser.username,
                };

                try {
                    const response = await fetchWithAuth('/api/schedule/events', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(newEventData),
                    });

                    if (!response.ok) {
                        const errorData = await response.json().catch(() => ({ detail: "Server error during sign-up." }));
                        throw new Error(errorData.detail || "Server error");
                    }
                    alert(`Shift added for ${window.currentUser.username}.`);
                    mainCalendar.refetchEvents(); // Reload events to show the new one
                } catch (error) {
                    alert("Error signing up: " + error.message);
                }
            }
            calendar.unselect(); // Clear the selection
        }, // End select callback

        // Handle clicking an existing shift
        eventClick: async function(clickInfo) {
            const event = clickInfo.event;
            const originalTitle = event.extendedProps.originalTitle; // Get original title for logic


            if (!window.currentUser || !window.currentUser.username) {
                alert("User information not available. Please log in again.");
                return;
            }

            // Handle unavailability event click
            if (event.extendedProps.type === "unavailability") {
                if (confirm(`Do you want to remove this unavailability: ${event.title}?`)) {
                    try {
                        const response = await fetchWithAuth(`/api/schedule/unavailability/${event.id.replace('unavail-', '')}`, { method: 'DELETE' });
                        if (!response.ok) { throw new Error((await response.json()).detail || "Server error during unavailability removal."); }
                        alert("Unavailability removed.");
                        event.remove(); // Optimistic update
                    } catch (error) {
                        alert("Error removing unavailability: " + error.message);
                    }
                }
            } else if (originalTitle === window.currentUser.username) { // User clicked their own shift
                if (confirm("Do you want to unassign yourself from this shift?")) {
                    try {
                        const response = await fetchWithAuth(`/api/schedule/events/${event.id}`, { method: 'DELETE' });
                        if (!response.ok) {
                            throw new Error((await response.json()).detail || "Server error during unassignment.");
                        }
                        alert(`Shift unassigned.`);
                        event.remove(); // Optimistic update
                    } catch (error) {
                        alert("Error unassigning: " + error.message);
                    }
                } // End confirm
            } else { // Clicked someone else's shift
                let modalContent = `<b>Shift Details:</b><br/>Pilot: ${originalTitle}<br/>Start: ${event.start.toLocaleString()}<br/>End: ${event.end.toLocaleString()}`;

                try {
                    const handoffResponse = await fetchWithAuth(`/api/schedule/events/${event.id}/pic_handoffs`);
                    if (handoffResponse.ok) {
                        const handoffForms = await handoffResponse.json();
                        if (handoffForms.length > 0) {
                            modalContent += `<br/><br/><b>PIC Handoffs during this shift:</b><ul>`;
                            handoffForms.forEach(form => {
                                const submissionTime = new Date(form.submission_timestamp);
                                const viewUrl = `/view_pic_handoffs.html?form_id=${form.form_db_id}&mission_id=${form.mission_id}`;
                                modalContent += `<li><a href="${viewUrl}" target="_blank">${form.mission_id} - PIC Handoff (${submissionTime.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})})</a> by ${form.submitted_by_username}</li>`;
                            });
                            modalContent += `</ul>`;
                        } else {
                            modalContent += `<br/><br/><i>No PIC Handoff forms found for this shift.</i>`;
                        }
                    } else {
                        modalContent += `<br/><br/><i>Could not load PIC Handoff information.</i>`;
                    }
                } catch (error) {
                    console.error("Network error fetching PIC Handoffs:", error);
                    modalContent += `<br/><br/><i>Error loading PIC Handoff information.</i>`;
                }

                // Simple alert modal for now. Can be replaced with a Bootstrap modal.
                const modalDiv = document.createElement('div');
                modalDiv.innerHTML = modalContent;
                alert(modalDiv.innerText); // Basic alert for simplicity, replace with Bootstrap modal for better UX
            }
        },

        // Update the date range display when the view changes
        datesSet: function(dateInfo) {
            updateDateRangeDisplay(dateInfo.start, dateInfo.end);
        }
    });

    // Define the event fetching function once, to be reused by all calendars
    async function fetchAllScheduleEvents(fetchInfo, successCallback, failureCallback) {
        try {
            // Fetch all events (shifts and unavailabilities) from the combined endpoint
            const response = await fetchWithAuth(`/api/schedule/events?start=${fetchInfo.start.toISOString()}&end=${fetchInfo.end.toISOString()}`);

            if (!response.ok) {
                if (response.status === 401 || response.status === 403) {
                    console.warn(`Auth error (${response.status}) fetching schedule events. Redirecting to login.`);
                    logout();
                    return;
                }
                const errorData = await response.json().catch(() => ({ detail: "Server error fetching schedule events." }));
                throw new Error(errorData.detail || "Server error fetching schedule events.");
            }
            const events = await response.json(); // This now contains both shifts and unavailabilities

            const allEvents = [];
            events.forEach(event => {
                allEvents.push({
                    id: event.id,
                    title: event.type === 'shift' ? '' : event.text, // Set empty title for shifts
                    start: event.start, // Already datetime from backend
                    end: event.end,     // Already datetime from backend
                    allDay: event.allDay, // Pass allDay property for unavailability events
                    resourceId: event.resource,
                    backgroundColor: event.backColor,
                    borderColor: event.backColor,
                    editable: event.editable,
                    startEditable: event.startEditable,
                    durationEditable: event.durationEditable,
                    resourceEditable: event.resourceEditable,
                    overlap: event.overlap,
                    display: event.display,
                    // Add classNames for unavailability events based on role
                    classNames: event.type === "unavailability" 
                        ? [`fc-event-unavailability-${event.user_role}`] 
                        : ['fc-event-shift'], // Add a class for shift events
                    extendedProps: { // Store original data for popups
                        type: event.type,
                        originalTitle: event.text,
                        user_role: event.user_role
                    }                });
            });
            successCallback(allEvents);
        } catch (error) {
            console.error("Failed to fetch schedule events:", error);
            failureCallback(error);
        }
    }

    // Update mainCalendar to use the new fetchAllScheduleEvents function
    mainCalendar.setOption('events', fetchAllScheduleEvents);
    mainCalendar.render();

    // --- Navigation and UI Update Handlers ---
    function updateDateRangeDisplay(start, end) {
        // FullCalendar's `end` is exclusive, so subtract one day for display
        const displayEnd = new Date(end.getTime() - 1);
        const options = { month: 'long', day: 'numeric', year: 'numeric' };
        const startStr = start.toLocaleDateString(undefined, options);
        const endStr = displayEnd.toLocaleDateString(undefined, options);

        if (dateRangeDisplay) {
            dateRangeDisplay.textContent = `${startStr} - ${endStr}`;
        }
    }

    // --- Download Logic ---
    if (downloadScheduleBtn) {
        downloadScheduleBtn.addEventListener('click', handleDownloadSchedule);
    }

    async function handleDownloadSchedule() {
        const startDate = downloadStartDateInput.value;
        const endDate = downloadEndDateInput.value;
        const format = downloadFormatSelect.value;
        const userScope = downloadUserScopeSelect.value;

        if (!startDate || !endDate) {
            alert("Please select both a start and end date for the download.");
            return;
        }
        if (new Date(startDate) > new Date(endDate)) {
            alert("Start date cannot be after end date.");
            return;
        }

        const apiUrl = `/api/schedule/download?start_date=${encodeURIComponent(startDate)}&end_date=${encodeURIComponent(endDate)}&format=${encodeURIComponent(format)}&user_scope=${encodeURIComponent(userScope)}`;

        try {
            const response = await fetchWithAuth(apiUrl, { method: 'GET' });

            if (!response.ok) {
                const errorText = await response.text();
                throw new Error(`Error ${response.status}: ${errorText || 'Server error'}`);
            }

            const blob = await response.blob();
            const filename = `schedule_${startDate.replace(/-/g, '')}_to_${endDate.replace(/-/g, '')}.${format}`;
            const link = document.createElement('a');
            link.href = URL.createObjectURL(blob);
            link.download = filename;
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            URL.revokeObjectURL(link.href);
            alert("Schedule download started.");

        } catch (error) {
            console.error("Failed to download schedule:", error);
            alert("Network error downloading schedule: " + error.message);
        }
    }

    // --- Block Out Time Logic ---
    if (blockTimeBtn) {
        blockTimeBtn.addEventListener('click', () => {
            // Pre-fill dates based on current view in main calendar
            const currentView = mainCalendar.view;
            unavailabilityStartDateInput.value = currentView.currentStart.toISOString().split('T')[0];
            unavailabilityEndDateInput.value = currentView.currentEnd.toISOString().split('T')[0];
            unavailabilityReasonInput.value = '';
            blockTimeErrorDiv.style.display = 'none'; // Hide previous errors
            blockTimeModal.show();
        });
    }

    if (submitBlockTimeBtn) {
        submitBlockTimeBtn.addEventListener('click', async () => {
            const startDate = unavailabilityStartDateInput.value;
            const endDate = unavailabilityEndDateInput.value;
            const reason = unavailabilityReasonInput.value.trim();

            if (!startDate || !endDate) {
                blockTimeErrorDiv.textContent = "Start and end dates are required.";
                blockTimeErrorDiv.style.display = 'block';
                return;
            }
            if (new Date(startDate) > new Date(endDate)) {
                blockTimeErrorDiv.textContent = "End date cannot be before start date.";
                blockTimeErrorDiv.style.display = 'block';
                return;
            }

            try {
                const response = await fetchWithAuth('/api/schedule/unavailability', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ start_time_utc: startDate, end_time_utc: endDate, reason: reason }),
                });
                if (!response.ok) { throw new Error((await response.json()).detail || "Server error blocking time."); }
                blockTimeModal.hide();
                mainCalendar.refetchEvents(); // Refresh calendar to show new unavailability
            } catch (error) {
                blockTimeErrorDiv.textContent = "Error blocking time: " + error.message;
                blockTimeErrorDiv.style.display = 'block';
            }
        });
    }

    // Disable "My Shifts" option if no user is logged in
    if (downloadUserScopeSelect && (!window.currentUser || !window.currentUser.username)) {
        const myShiftsOption = downloadUserScopeSelect.querySelector('option[value="my_shifts"]');
        if (myShiftsOption) {
            myShiftsOption.disabled = true;
        }
    }
});
