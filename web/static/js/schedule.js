document.addEventListener('DOMContentLoaded', async function () {
    if (typeof initializeCurrentUserForScheduler === 'function') {
        await initializeCurrentUserForScheduler(); // Wait for user to be fetched
    } else {
        console.warn("initializeCurrentUserForScheduler function not found. User info might be unavailable for scheduler.");
    }

    if (typeof checkAuth === 'function' && !checkAuth()) {
        console.log("Schedule.js: checkAuth() failed. Aborting scheduler initialization.");
        return;
    }

    // UI Elements
    const calendarEl = document.getElementById('calendar');
    const prevBtn = document.getElementById('prevBtn');
    const todayBtn = document.getElementById('todayBtn');
    const nextBtn = document.getElementById('nextBtn');
    const dateRangeDisplay = document.getElementById('dateRangeDisplay');

    // Download Controls
    const downloadStartDateInput = document.getElementById('downloadStartDate');
    const downloadEndDateInput = document.getElementById('downloadEndDate');
    const downloadFormatSelect = document.getElementById('downloadFormat');
    const downloadUserScopeSelect = document.getElementById('downloadUserScope');
    const downloadScheduleBtn = document.getElementById('downloadScheduleBtn');

    // --- FullCalendar Initialization ---
    const calendar = new FullCalendar.Calendar(calendarEl, {
        initialView: 'timeGridWeek',
        headerToolbar: false, // We use our own custom buttons
        allDaySlot: false, // No all-day slot needed for shifts
        height: 'auto', // Adjust height to content
        slotMinTime: "00:00:00",
        slotMaxTime: "24:00:00",
        selectable: true,
        selectMirror: true,
        nowIndicator: true,

        // Fetch events from our backend
        events: async function(fetchInfo, successCallback, failureCallback) {
            try {
                const apiUrl = `/api/schedule/events?start=${fetchInfo.start.toISOString()}&end=${fetchInfo.end.toISOString()}`;
                const response = await fetchWithAuth(apiUrl);

                if (!response.ok) {
                    if (response.status === 401 || response.status === 403) {
                        console.warn(`Auth error (${response.status}) fetching schedule events. Redirecting to login.`);
                        logout();
                        return;
                    }
                    const errorData = await response.json();
                    throw new Error(errorData.detail || "Server error");
                }

                const events = await response.json();
                // Map backend event format to FullCalendar format
                const formattedEvents = events.map(event => ({
                    id: event.id,
                    title: event.text,
                    start: event.start,
                    end: event.end,
                    resourceId: event.resource, // Keep resource for potential future use
                    backgroundColor: event.backColor,
                    borderColor: event.backColor
                }));
                successCallback(formattedEvents);
            } catch (error) {
                console.error("Failed to fetch schedule events:", error);
                failureCallback(error);
            }
        },

        // Handle creating a new shift
        select: async function(selectionInfo) {
            if (!window.currentUser || !window.currentUser.username) {
                alert("Error: User information not available. Please log in again.");
                return;
            }

            const modalTitle = `Sign up for shift on ${selectionInfo.start.toLocaleDateString()} from ${selectionInfo.start.toLocaleTimeString()} to ${selectionInfo.end.toLocaleTimeString()}?`;
            if (confirm(modalTitle)) {
                const newEventData = {
                    start: selectionInfo.start.toISOString(),
                    end: selectionInfo.end.toISOString(),
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
                    calendar.refetchEvents(); // Reload events to show the new one
                } catch (error) {
                    alert("Error signing up: " + error.message);
                }
            }
            calendar.unselect(); // Clear the selection
        },

        // Handle clicking an existing shift
        eventClick: async function(clickInfo) {
            const event = clickInfo.event;

            if (!window.currentUser || !window.currentUser.username) {
                alert("User information not available. Please log in again.");
                return;
            }

            if (event.title === window.currentUser.username) { // User clicked their own shift
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
                }
            } else { // Clicked someone else's shift
                let modalContent = `<b>Shift Details:</b><br/>Pilot: ${event.title}<br/>Start: ${event.start.toLocaleString()}<br/>End: ${event.end.toLocaleString()}`;

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
                alert(modalDiv.innerText); // Basic alert for simplicity
            }
        },

        // Update the date range display when the view changes
        datesSet: function(dateInfo) {
            updateDateRangeDisplay(dateInfo.start, dateInfo.end);
        }
    });

    calendar.render();

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

    prevBtn.addEventListener('click', () => calendar.prev());
    todayBtn.addEventListener('click', () => calendar.today());
    nextBtn.addEventListener('click', () => calendar.next());

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

    // Disable "My Shifts" option if no user is logged in
    if (downloadUserScopeSelect && (!window.currentUser || !window.currentUser.username)) {
        const myShiftsOption = downloadUserScopeSelect.querySelector('option[value="my_shifts"]');
        if (myShiftsOption) {
            myShiftsOption.disabled = true;
        }
    }
});

