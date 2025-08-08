import { getUserProfile, checkAuth } from "/static/js/auth.js";
import { fetchWithAuth } from "/static/js/api.js";

document.addEventListener('DOMContentLoaded', async function () {
    // This function was moved from schedule.html to make this script more self-contained.
    const LRI_PILOT_USERNAME = "LRI_PILOT"; // Must match the username in auth_utils.py

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

    // Block LRI Time Modal Elements
    const blockLriTimeBtn = document.getElementById('blockLriTimeBtn');
    const blockLriTimeModal = new bootstrap.Modal(document.getElementById('blockLriTimeModal'));
    const lriBlockStartDateInput = document.getElementById('lriBlockStartDate');
    const lriBlockEndDateInput = document.getElementById('lriBlockEndDate');
    const submitBlockLriTimeBtn = document.getElementById('submitBlockLriTimeBtn');
    const blockLriTimeErrorDiv = document.getElementById('blockLriTimeError');

    // Clear Range Modal Elements
    const clearRangeBtn = document.getElementById('clearRangeBtn');
    const clearRangeModal = new bootstrap.Modal(document.getElementById('clearRangeModal'));
    const clearStartDateInput = document.getElementById('clearStartDate');
    const clearEndDateInput = document.getElementById('clearEndDate');
    const submitClearRangeBtn = document.getElementById('submitClearRangeBtn');
    const clearRangeErrorDiv = document.getElementById('clearRangeError');

    let mainCalendar; // Only one calendar instance now


    // --- FullCalendar Initialization ---
    mainCalendar = new FullCalendar.Calendar(calendarEl, {
        initialView: 'dayGridMonth', // Default view is month
        timeZone: 'America/Halifax', // Force display in Atlantic Daylight Time (ADT)
        headerToolbar: {
            left: 'prev,next today', // Navigation buttons
            center: 'title', // Month/Week/Day title
            right: 'dayGridMonth,timeGridWeek,timeGridDay,listWeek' // View buttons
        },        allDaySlot: true, // Enable the all-day slot to display unavailability
        dayMaxEvents: 3, // Show 3 events max before displaying a "+more" link
        slotDuration: '03:00:00', // Set the duration of each time slot to 3 hours
        slotLabelInterval: '03:00', // Display a label for each 3-hour slot
        slotLabelFormat: {
            hour: 'numeric',
            minute: '2-digit',
            meridiem: 'short'
        }, // Format the slot labels to show the start time of the 3-hour block
        eventMinHeight: 20, // Ensure events have a minimum height even without text
        height: 'auto', // Let the content define the height to avoid rendering bugs with vh units
        slotMinTime: "02:00:00", // Start the grid at 02:00 local time to align with shift blocks
        slotMaxTime: "26:00:00", // End the grid at 02:00 local time the next day (24 hours later)
        selectable: false, // Disable drag-to-select, we will use dateClick
        selectMirror: false,
        nowIndicator: true,

        // Fetch events from our backend
        // This will be set later by mainCalendar.setOption('events', ...)

        // Handle creating a new shift by clicking on a time slot
        dateClick: async function(info) {
            // Only allow creating shifts in time-gridded views (Week or Day)
            if (!info.view.type.startsWith('timeGrid')) {
                alert("Please switch to Week or Day view to add a shift by clicking on a time slot.");
                return;
            }
            if (!window.currentUser || !window.currentUser.username) {
                alert("Error: User information not available. Please log in again.");
                return;
            }

            // Determine the precise 3-hour slot based on the clicked time
            const slot = getSlotForTime(info.date);
            if (!slot) {
                console.error("Could not determine a valid shift slot for the clicked time.");
                return; // Should not happen if logic is correct
            }

            const modalTitle = `Sign up for shift on ${slot.start.toLocaleDateString()} from ${slot.start.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})} to ${slot.end.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}?`;
            if (confirm(modalTitle)) {
                // Add a flag to prevent multiple submissions.
                if (this.isSubmitting) return; // If already submitting, ignore click
                this.isSubmitting = true;

                const newEventData = {
                    start: slot.start.toISOString(),
                    end: slot.end.toISOString(),
                    // Use the slot's start time as a unique resource ID to prevent double booking
                    resource: slot.start.toISOString(),
                    text: window.currentUser.username,
                };

                try {
                    const response = await fetchWithAuth('/api/schedule/shifts', { // Use new shifts endpoint
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify(newEventData),
                    });

                    if (!response.ok) {
                        const errorData = await response.json().catch(() => ({
                            detail: "Server error during sign-up."
                        }));
                        throw new Error(errorData.detail || "Server error");
                    }
                    alert(`Shift added for ${window.currentUser.username}.`);
                    mainCalendar.refetchEvents(); // Reload events to show the new one
                    // Clear the submission flag after a short delay.
                    setTimeout(() => { this.isSubmitting = false; }, 1000);

                } catch (error) {
                    alert("Error signing up: " + error.message);
                }
            }
        }, // End dateClick callback

        // Handle clicking an existing shift
        eventClick: async function(clickInfo) {
            const event = clickInfo.event;
            const originalTitle = event.extendedProps.originalTitle; // Get original title for logic


            if (!window.currentUser || !window.currentUser.username) {
                alert("User information not available. Please log in again.");
                return;
            }
            
            // Handle LRI block event click
            if (event.extendedProps.type === "lri_block") {
                if (window.currentUser.role === 'admin') {
                    if (confirm(`Do you want to remove this LRI Block?`)) {
                        try {
                            const response = await fetchWithAuth(`/api/schedule/lri_blocks/${event.id}`, { method: 'DELETE' });
                            if (!response.ok) { throw new Error((await response.json()).detail || "Server error during LRI block removal."); }
                            alert("LRI Block removed.");
                            event.remove(); // Optimistic update
                        } catch (error) { alert("Error removing LRI Block: " + error.message); }
                    }
                } else { alert("This slot is reserved for LRI."); }
                return; // Stop further processing for LRI blocks
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
                    try { // Use new shifts endpoint
                        const response = await fetchWithAuth(`/api/schedule/shifts/${event.id}`, { method: 'DELETE' });
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
        },

        // Add tooltips to events
        eventDidMount: function(info) {
            const eventType = info.event.extendedProps.type;
            let tooltipText = '';
            
            if (eventType === "lri_block" || eventType === "holiday" || eventType === "unavailability") {
                tooltipText = info.event.title; // Title already contains the descriptive text
            } else if (eventType === "shift") {
                // For shifts, combine pilot name and time range
                const originalTitle = info.event.extendedProps.originalTitle;
                tooltipText = `Pilot: ${originalTitle}\n${info.event.start.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})} - ${info.event.end.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}`;
            }

            if (tooltipText) {
                info.el.title = tooltipText;
            }
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
                    groupId: event.groupId, // Pass groupId for event merging
                    display: event.display,
                    // Add classNames for unavailability events based on role
                    classNames: event.type === "lri_block"
                        ? [`fc-event-lri-block`]
                        : event.type === "unavailability" 
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

    /**
     * Determines the correct 3-hour shift slot for a given clicked time.
     * Shift start times are fixed in ADT (UTC-3).
     * @param {Date} clickedDate The date/time the user clicked on the calendar.
     * @returns {{start: Date, end: Date}|null} An object with start and end Date objects for the slot, or null.
     */
    function getSlotForTime(clickedDate) {
        // Since FullCalendar is now in ADT, clickedDate is already in ADT.
        const clickedAdtHour = clickedDate.getHours();

        // Valid ADT start hours for the 3-hour blocks.
        const validStartHours = [2, 5, 8, 11, 14, 17, 20, 23];
        let slotStartHour = -1;

        // Handle the 23:00 shift which spans midnight
        if (clickedAdtHour >= 23 || clickedAdtHour < 2) {
            slotStartHour = 23;
        } else {
            // Find the latest valid start hour that is less than or equal to the clicked hour
            for (let i = validStartHours.length - 1; i >= 0; i--) {
                if (clickedAdtHour >= validStartHours[i]) {
                    slotStartHour = validStartHours[i];
                    break;
                }
            }
        }

        if (slotStartHour === -1) {
            console.error("Could not determine a valid shift slot for hour:", clickedAdtHour);
            return null; // Should not happen
        }

        const slotStartDate = new Date(clickedDate.getFullYear(), clickedDate.getMonth(), clickedDate.getDate());
        slotStartDate.setHours(slotStartHour, 0, 0, 0);
        
        const slotEndDate = new Date(slotStartDate.getTime() + (3 * 60 * 60 * 1000)); // Add 3 hours

        console.log("getSlotForTime - clickedDate:", clickedDate.toISOString());
        console.log("getSlotForTime - slot:", {start: slotStartDate.toISOString(), end: slotEndDate.toISOString()});

        return { start: slotStartDate, end: slotEndDate };
    }
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

    // --- Block LRI Time Logic ---
    if (blockLriTimeBtn) {
        // Show button only for admins
        if (window.currentUser && window.currentUser.role === 'admin') {
            blockLriTimeBtn.style.display = 'inline-block';
        }
        blockLriTimeBtn.addEventListener('click', () => {
            // Pre-fill dates based on current view in main calendar
            const currentView = mainCalendar.view;
            lriBlockStartDateInput.value = currentView.currentStart.toISOString().split('T')[0];
            lriBlockEndDateInput.value = currentView.currentEnd.toISOString().split('T')[0];
            blockLriTimeErrorDiv.style.display = 'none'; // Hide previous errors
            blockLriTimeModal.show();
        });
    }

    if (submitBlockLriTimeBtn) {
        submitBlockLriTimeBtn.addEventListener('click', async () => {
            const startDate = lriBlockStartDateInput.value;
            const endDate = lriBlockEndDateInput.value;

            if (!startDate || !endDate) {
                blockLriTimeErrorDiv.textContent = "Start and end dates are required.";
                blockLriTimeErrorDiv.style.display = 'block';
                return;
            }
            if (new Date(startDate) > new Date(endDate)) {
                blockLriTimeErrorDiv.textContent = "End date cannot be before start date.";
                blockLriTimeErrorDiv.style.display = 'block';
                return;
            }

            try {
                const response = await fetchWithAuth('/api/schedule/lri_blocks', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ 
                        start_date: startDate, 
                        end_date: endDate,
                        reason: "LRI Piloting Block" // Optional reason
                    }),
                });
                if (!response.ok) { 
                    throw new Error((await response.json()).detail || "Server error blocking LRI time."); 
                }
                blockLriTimeModal.hide();
                mainCalendar.refetchEvents(); // Refresh calendar to show new LRI blocks
            } catch (error) {
                blockLriTimeErrorDiv.textContent = "Error blocking LRI time: " + error.message;
                blockLriTimeErrorDiv.style.display = 'block';
            }
        });
    }

    // --- Clear Date Range Logic (Admin Only) ---
    if (clearRangeBtn) {
        // Show button only for admins
        if (window.currentUser && window.currentUser.role === 'admin') {
            clearRangeBtn.style.display = 'inline-block';
        }
        clearRangeBtn.addEventListener('click', () => {
            // Pre-fill dates based on current view in main calendar
            const currentView = mainCalendar.view;
            clearStartDateInput.value = currentView.currentStart.toISOString().split('T')[0];
            // Default end date to be same as start date for convenience
            clearEndDateInput.value = currentView.currentStart.toISOString().split('T')[0];
            clearRangeErrorDiv.style.display = 'none'; // Hide previous errors
            clearRangeModal.show();
        });
    }

    if (submitClearRangeBtn) {
        submitClearRangeBtn.addEventListener('click', async () => {
            const startDate = clearStartDateInput.value;
            const endDate = clearEndDateInput.value;

            if (!startDate || !endDate) {
                clearRangeErrorDiv.textContent = "Start and end dates are required.";
                clearRangeErrorDiv.style.display = 'block';
                return;
            }
            if (new Date(startDate) > new Date(endDate)) {
                clearRangeErrorDiv.textContent = "End date cannot be before start date.";
                clearRangeErrorDiv.style.display = 'block';
                return;
            }

            if (confirm(`Are you sure you want to clear ALL shifts, LRI blocks, and unavailability from ${startDate} to ${endDate}? This action cannot be undone.`)) {
                try {
                    const apiUrl = `/api/schedule/clear_range?start_date=${encodeURIComponent(startDate)}&end_date=${encodeURIComponent(endDate)}`;
                    const response = await fetchWithAuth(apiUrl, { method: 'DELETE' });
                    if (!response.ok) { throw new Error((await response.json()).detail || "Server error during clear operation."); }
                    alert(`All shifts and blocks from ${startDate} to ${endDate} cleared successfully.`);
                    clearRangeModal.hide();
                    mainCalendar.refetchEvents(); // Reload events
                } catch (error) {
                    clearRangeErrorDiv.textContent = "Error clearing range: " + error.message;
                    clearRangeErrorDiv.style.display = 'block';
                }
            }
        });
    }
});
