document.addEventListener('DOMContentLoaded', async function () { // Make async
    if (typeof initializeCurrentUserForScheduler === 'function') {
        await initializeCurrentUserForScheduler(); // Wait for user to be fetched
    } else {
        console.warn("initializeCurrentUserForScheduler function not found. User info might be unavailable for scheduler.");
    }

    // Check auth again, especially if initializeCurrentUser might log out or if it's the first check
    if (typeof checkAuth === 'function' && !checkAuth()) {
        console.log("Schedule.js: checkAuth() failed. Aborting scheduler initialization.");
        return;
    }

    // Initialize DayPilot Scheduler
    const scheduler = new DayPilot.Scheduler("dp"); // "dp" is the ID of the div in schedule.html

    // Configuration: Default to "SlotDay" view
    let currentScale = "SlotDay"; // Only "SlotDay" will be used
    let currentStartDate = DayPilot.Date.today().firstDayOfWeek(); // Start of the current week
    let currentDays = 7; // Number of days to show
    let isSchedulerInitialized = false; // Flag to track initialization

    // Define resources for the "SlotDay" view (Time Slots as Rows)
    const timeSlotResources = [
        { name: "23:00 - 02:00", id: "SLOT_23_02" },
        { name: "02:00 - 05:00", id: "SLOT_02_05" },
        { name: "05:00 - 08:00", id: "SLOT_05_08" },
        { name: "08:00 - 11:00", id: "SLOT_08_11" },
        { name: "11:00 - 14:00", id: "SLOT_11_14" },
        { name: "14:00 - 17:00", id: "SLOT_14_17" },
        { name: "17:00 - 20:00", id: "SLOT_17_20" },
        { name: "20:00 - 23:00", id: "SLOT_20_23" }
    ];

    // UI Elements
    const prevBtn = document.getElementById('prevBtn');
    const todayBtn = document.getElementById('todayBtn');
    const nextBtn = document.getElementById('nextBtn');
    const dateRangeDisplay = document.getElementById('dateRangeDisplay');
    const downloadStartDateInput = document.getElementById('downloadStartDate');
    const downloadEndDateInput = document.getElementById('downloadEndDate');
    const downloadFormatSelect = document.getElementById('downloadFormat');
    const downloadUserScopeSelect = document.getElementById('downloadUserScope');
    const downloadScheduleBtn = document.getElementById('downloadScheduleBtn');

    // Define resources (these will be your columns, e.g., days of the week)
    // This will be dynamically set based on the view

    // Function to update scheduler configuration based on scale
    function updateSchedulerConfig(schedulerInstance) {
        // Directly set properties on the schedulerInstance
        schedulerInstance.startDate = currentStartDate;
        schedulerInstance.days = currentDays; // This might be updated by the SlotDay logic
        schedulerInstance.rowHeaderWidth = 100; 
        schedulerInstance.heightSpec = "Max"; 
        schedulerInstance.width = "100%";
        schedulerInstance.rowHeaderWidthSpec = "Fixed";

        // Event handlers are set globally on the scheduler object once, so no need to set them here.
        // e.g., schedulerInstance.timeRangeSelectedHandling = "JavaScript"; is already set.

        // Adjust time headers based on scale
        // Only "SlotDay" configuration is needed now
        if (currentScale === "SlotDay") { 
            schedulerInstance.resources = timeSlotResources; 
            schedulerInstance.scale = "Day"; 
            schedulerInstance.timeHeaders = [
                { groupBy: "Month", format: "MMMM yyyy" },
                { groupBy: "Day", format: "ddd d" } // e.g., "Sun 15"
            ];
            schedulerInstance.cellDuration = 24 * 60; 
            currentDays = 7; // Show a week of days
            schedulerInstance.days = currentDays; // Ensure this is updated on the instance
            // cellWidth and cellWidthSpec will be handled by applyCalculatedCellWidth

        } else {
            console.error("Unsupported scale selected:", currentScale); // Should not happen
        }

        // Update the displayed date range text
        updateDateRangeDisplay();
    }

    // Function to apply the calculated cell width
    function applyCalculatedCellWidth(schedulerInstance) {
         // Try to calculate cellWidth manually
        const dpContainer = document.getElementById("dp");
        if (dpContainer && dpContainer.clientWidth > 0) {
            // Use the rowHeaderWidth that will be applied to the scheduler
            const rowHeaderWidth = schedulerInstance.rowHeaderWidth || 100; // Use instance value or default
            const availableTimelineWidth = dpContainer.clientWidth - rowHeaderWidth;
            
            // Use the number of days that will be applied to the scheduler
            const numDays = schedulerInstance.days || 7; // Use instance value or default

            if (availableTimelineWidth > 0 && numDays > 0) {
                const calculatedCellWidth = Math.floor(availableTimelineWidth / numDays);
                schedulerInstance.cellWidth = calculatedCellWidth; // Set explicit cell width on the instance
                schedulerInstance.cellWidthSpec = "Fixed"; // Ensure spec is Fixed
                console.log(`Calculated cellWidth: ${calculatedCellWidth}px for container width ${dpContainer.clientWidth}px`);
            } else {
                schedulerInstance.cellWidthSpec = "Auto"; // Fallback if calculation is not possible
                 console.warn("Could not calculate cellWidth, falling back to Auto.");
            }
        } else {
            schedulerInstance.cellWidthSpec = "Auto"; // Fallback if dpContainer not ready
             console.warn("dpContainer not ready, falling back to Auto cellWidthSpec.");
        }
    }

    // Helper function to safely call scheduler.message or fallback
    function safeSchedulerMessage(html, options) {
        if (scheduler && typeof scheduler.message === 'function') {
            if (options) {
                scheduler.message(html, options);
            } else {
                scheduler.message(html);
            }
        } else {
            console.warn("scheduler.message is not a function. Falling back to DayPilot.Modal.alert. Message:", html, "Scheduler instance:", scheduler);
            // Fallback to DayPilot.Modal.alert for a consistent look, though it's not auto-hiding.
            // You could also use a simple window.alert() if DayPilot.Modal is also problematic.
            if (typeof DayPilot !== "undefined" && DayPilot.Modal && typeof DayPilot.Modal.alert === 'function') {
                DayPilot.Modal.alert(html.toString()); // Modal.alert expects a string
            } else {
                alert(html.toString().replace(/<[^>]*>?/gm, '')); // Basic strip HTML for plain alert
            }
        }
    }
    // Load events from the backend
    // Pass start and end dates to the API
    async function loadScheduleEvents(start, end) {
        try {
            // Assuming fetchWithAuth is defined in your global scope or another JS file
            // and handles adding the Authorization header.
            // If not, you might need a simpler fetch for now if the endpoint is public
            // or implement fetchWithAuth.            
            const startDateString = start.toString(); // Full ISO string e.g., "2023-10-26T00:00:00"
            const endDateString = end.toString();     // Full ISO string
            const apiUrl = `/api/schedule/events?start=${encodeURIComponent(startDateString)}&end=${encodeURIComponent(endDateString)}`;
            const response = await fetchWithAuth(apiUrl); // Use fetchWithAuth from main.js
            console.log("Fetch response received:", response.status);

            if (!response.ok) {
                 if (response.status === 401 || response.status === 403) {
                    console.warn(`Auth error (${response.status}) fetching schedule events. Redirecting to login.`);
                    logout(); // Assuming logout is available from auth.js
                    return;
                }
                const errorData = await response.json();
                console.error("Error loading schedule events:", response.status, errorData.detail);
                safeSchedulerMessage("Error loading schedule: " + (errorData.detail || "Server error"));
                return;
            }
            const events = await response.json();
            console.log("Events data received:", events);
            // DayPilot expects date strings in ISO format or DayPilot.Date objects
            // The backend should provide ISO strings (e.g., "2023-10-26T10:00:00Z") or DayPilot.Date compatible strings
            scheduler.events.list = events;
            console.log("Scheduler: Updating with new event data.");
            scheduler.update();
            // The main update will be handled by refreshSchedulerAndUpdateView after this function returns,
            // or by the forced "Full" update on initial load.
            // Avoid calling scheduler.update() here directly if refreshSchedulerAndUpdateView will call it. 
        } catch (error) {
            console.error("Failed to fetch schedule events:", error); // Keep console error
            safeSchedulerMessage("Failed to load schedule events. Check console for details.");
        }
    }

    // Renamed to reflect it's for general refresh, not just initial
    async function refreshSchedulerAndUpdateView(isInitialCall = false) {
        console.log(`refreshSchedulerAndUpdateView called. isInitialCall: ${isInitialCall}`);
        const previousScrollX = isSchedulerInitialized ? scheduler.getScrollX() : 0;
        const previousScrollY = isSchedulerInitialized ? scheduler.getScrollY() : 0;

        updateSchedulerConfig(scheduler); // Apply current date/scale config to the scheduler instance
        applyCalculatedCellWidth(scheduler); // Calculate and apply cell width
        if (!isSchedulerInitialized) {
            console.log("Scheduler: Initializing for the first time.");
            // Set event handlers once before init if they weren't set globally earlier
            // However, they are already set globally on the `scheduler` object in your current code.
            // When initializing, the config is applied via scheduler.init()
            // The properties set on the scheduler instance before init are used.
            scheduler.init(); // Initialize the scheduler only once
            isSchedulerInitialized = true;
        }

        const apiEndDate = currentStartDate.addDays(currentDays);
        await loadScheduleEvents(currentStartDate, apiEndDate); // Await event loading

                // Restore scroll position after events are loaded and scheduler might have updated
        if (!isInitialCall && isSchedulerInitialized) {
            scheduler.scrollTo(previousScrollX, previousScrollY);
        }

        if (isInitialCall) {
            // After the very first init and event load, force a full layout update
            // This is the most critical part for fixing the width
            setTimeout(() => {
                if (scheduler && scheduler.initialized) {
                    console.log("Scheduler: Forcing a final layout update with updateMode: 'Full' after initial load.");
                    scheduler.update({ updateMode: "Full" });
                    
                    const matrix = document.querySelector(`#${scheduler.id} .scheduler_default_matrix`);
                    if (matrix) {
                        console.log(`Scheduler matrix width after forced FULL update: ${matrix.style.width || getComputedStyle(matrix).width}`);
                    }
                     // Restore scroll again if needed, as "Full" update might reset it
                    scheduler.scrollTo(previousScrollX, previousScrollY);
                }
            }, 300); // Delay to allow DOM to settle after init and first event render
        } else if (isSchedulerInitialized) {
            // For subsequent refreshes (not the initial one), a simple update is usually enough after loading events.
            scheduler.update();

        }
    }


    // --- DayPilot Event Handlers ---


    // --- Shift Sign-up and Management ---
    scheduler.timeRangeSelectedHandling = "JavaScript"; // Enable custom handling
    scheduler.onTimeRangeSelected = async function (args) {
        let isValidSelection = false;
        let modalTitle = "";

        if (currentScale === "SlotDay") {
            // In SlotDay view, args.resource is the slot ID (e.g., "SLOT_02_05")
            // args.start is the beginning of the day cell.
            // The "3-hour block" is defined by the resource (row) itself.
            isValidSelection = true;
            const resourceObj = timeSlotResources.find(r => r.id === args.resource);
            const slotName = resourceObj ? resourceObj.name : args.resource;
            modalTitle = `Sign up for ${slotName} on ${args.start.toString("dddd, MMM d")}?`;
        }

        if (isValidSelection) {
            if (!window.currentUser || !window.currentUser.username) {
                safeSchedulerMessage("Error: User information not available. Please log in again.", { cssClass: "error", delay: 3000 });
                scheduler.clearSelection();
                return;
            }
            const currentUsername = window.currentUser.username;

            const modal = await DayPilot.Modal.confirm(modalTitle, {
                okText: "Sign Up",
                cancelText: "Cancel"
            });
            
            scheduler.clearSelection();

            if (modal.result) { // User clicked "Sign Up"
                const newEventData = {
                    start: args.start.toString(), // For SlotDay, this is the day start. For others, actual shift start.
                    end: args.end.toString(),     // For SlotDay, this is the day end. For others, actual shift end.
                    id: DayPilot.guid(),
                    resource: args.resource,
                    text: currentUsername,
                };

                try {
                    const response = await fetchWithAuth('/api/schedule/events', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(newEventData),
                    });

                    if (!response.ok) {
                        const errorData = await response.json().catch(() => ({ detail: "Server error during sign-up." }));
                        safeSchedulerMessage("Error signing up: " + (errorData.detail || "Server error"), { cssClass: "error", delay: 3000 });
                        return;
                    }
                    // const createdEvent = await response.json(); // Backend returns the created event
                    // If backend returns the created event with its DB ID, you could add it directly:
                    // scheduler.events.add(new DayPilot.Event(createdEvent));
                    // However, refreshScheduler() reloads all events, ensuring consistency,
                    safeSchedulerMessage(`Shift added for ${currentUsername}.`);
                    refreshSchedulerAndUpdateView(); // Reload all events to ensure consistency

                } catch (error) {
                    safeSchedulerMessage("Network error signing up: " + error.message, { cssClass: "error", delay: 3000 });
                }
            }
        } else {
            const errorMessage = "Invalid selection."; // Simplified as other views are removed
            safeSchedulerMessage(errorMessage, { delay: 4000 });
            scheduler.clearSelection();
        }
    };

    scheduler.eventClickHandling = "JavaScript"; // Custom handling for event clicks
    scheduler.onEventClick = async function(args) {
        const eventData = args.e.data;
        if (!window.currentUser || !window.currentUser.username) {
            DayPilot.Modal.alert("User information not available. Please log in again.");
            return;
        }
        const currentUsername = window.currentUser.username;

        if (eventData.text === currentUsername) { // User clicked their own shift
            const modal = await DayPilot.Modal.confirm("Do you want to unassign yourself from this shift?", { okText: "Unassign", cancelText: "Cancel" });
            if (modal.result) {
                try {
                    const response = await fetchWithAuth(`/api/schedule/events/${eventData.id}`, { method: 'DELETE' });
                    if (!response.ok) { throw new Error((await response.json()).detail || "Server error during unassignment."); }
                    // scheduler.events.remove(args.e); // Optimistic update
                    // Refreshing the whole scheduler is safer to ensure consistency and re-fetch data                    
                    safeSchedulerMessage(`Shift unassigned.`); // Corrected message
                    refreshSchedulerAndUpdateView(); // Reload all events to ensure consistency
                } catch (error) { safeSchedulerMessage("Error unassigning: " + error.message, { cssClass: "error", delay: 3000 }); }
            }
        } else {
            // Display shift details and PIC Handoff links
            let modalContent = `<b>Shift Details:</b><br/>Pilot: ${eventData.text}<br/>Start: ${args.e.start().toString("MM/dd/yyyy HH:mm")}<br/>End: ${args.e.end().toString("MM/dd/yyyy HH:mm")}`;

            try {
                    const handoffResponse = await fetchWithAuth(`/api/schedule/events/${eventData.id}/pic_handoffs`);
                    if (handoffResponse.ok) {
                        const handoffForms = await handoffResponse.json();
                        if (handoffForms.length > 0) {
                            modalContent += `<br/><br/><b>PIC Handoffs during this shift:</b><ul>`;
                            const twentyFourHoursAgo = new Date(new Date().getTime() - (24 * 60 * 60 * 1000));
                            handoffForms.forEach(form => {
                                const submissionTime = new Date(form.submission_timestamp);
                                const isRecent = submissionTime > twentyFourHoursAgo;
                                // Link to new view_pic_handoffs.html for recent, existing view_forms.html for older
                                // We'll assume view_pic_handoffs.html can handle form_id and mission_id
                                const viewUrl = isRecent ?
                                    `/view_pic_handoffs.html?form_id=${form.form_db_id}&mission_id=${form.mission_id}` :
                                    `/view_forms.html?form_id=${form.form_db_id}`; // Assuming view_forms.html can take form_id

                                modalContent += `<li><a href="${viewUrl}" target="_blank">${form.mission_id} - PIC Handoff (${submissionTime.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})} UTC)</a> by ${form.submitted_by_username}</li>`;
                            });
                            modalContent += `</ul>`;
                        } else {
                            modalContent += `<br/><br/><i>No PIC Handoff forms found for this shift and mission.</i>`;
                        } // "and mission" part of the message can be removed or generalized now
                    } else {
                        console.error("Error fetching PIC Handoffs:", handoffResponse.status);
                        modalContent += `<br/><br/><i>Could not load PIC Handoff information.</i>`;
                    }
                } catch (error) {
                    console.error("Network error fetching PIC Handoffs:", error);
                    modalContent += `<br/><br/><i>Error loading PIC Handoff information.</i>`;
                }

            DayPilot.Modal.alert(modalContent, {width: 450}); // Increased width for more content
        }
    };

    // --- Highlight Current Day ---
    scheduler.onBeforeCellRender = function(args) {
        // console.log("onBeforeCellRender: cell.start:", args.cell.start, "today:", DayPilot.Date.today());
        if (args.cell.start.getDatePart().getTime() === DayPilot.Date.today().getTime()) {
            // Using a more distinct color for highlighting the current day.
            // This is a light blue, adjust as needed for your theme.
            args.cell.backColor = "#e3f2fd"; // A light blue, for example
            // console.log("Highlighting current day:", args.cell.start);
        }
    };


    // --- Optional: Event Customization & Interaction ---

    // Example: Customize event appearance (you can do more with CSS as well)
    // scheduler.onBeforeEventRender = function(args) {
    //     if (args.data.isLite) { // Assuming you add an 'isLite' property to your event data
    //         args.data.backColor = "#e6ffe6";
    //         args.data.borderColor = "#6aa84f";
    //         args.data.fontColor = "#38761d";
    //     }
    //     if (args.data.text.includes("Meeting")) {
    //          args.data.barColor = "red";
    //     }
    // };

    // Example: Handle event clicks
    // scheduler.onEventClick = function(args) {
    //     alert("Clicked event: " + args.e.text() + "\nID: " + args.e.id());
    //     // You could open a modal for editing, show details, etc.
    // };

    // Example: Enable drag-and-drop for moving events
    // scheduler.eventMoveHandling = "Update"; // Options: "Update", "CallBack", "PostBack", "Notify", "Disabled"
    // scheduler.onEventMoved = function (args) {
    //     scheduler.message("Moved event: " + args.e.text() + " to " + args.newStart + " on resource " + args.newResource);
    //     // Here you would typically send an update to your backend
    // };

    // Example: Enable drag-and-drop for resizing events
    // scheduler.eventResizeHandling = "Update";
    // scheduler.onEventResized = function (args) {
    //     scheduler.message("Resized event: " + args.e.text() + " to " + args.newStart + " - " + args.newEnd);
    //     // Here you would typically send an update to your backend
    // };

    // Example: Enable creating events by selecting a time range
    // scheduler.timeRangeSelectedHandling = "Enabled"; // Options: "Enabled", "CallBack", "PostBack", "Disabled"
    // scheduler.onTimeRangeSelected = function (args) {
    //     DayPilot.Modal.prompt("New event text:", "Event").then(function(modal) {
    //         scheduler.clearSelection();
    //         if (!modal.result) { return; }
    //         scheduler.events.add({
    //             start: args.start,
    //             end: args.end,
    //             id: DayPilot.guid(), // Generate a new unique ID
    //             resource: args.resource,
    //             text: modal.result
    //         });
    //         scheduler.message("Created new event.");
    //         // Here you would typically send the new event to your backend
    //     });
    // };

    // --- Navigation and Scale Change Handlers ---

    function updateDateRangeDisplay() {
        let text = "";
        // Only "SlotDay" view is active, which is weekly
        if (currentScale === "SlotDay") { 
            const endDate = currentStartDate.addDays(6); // Assuming 7 days shown
            text = `${currentStartDate.toString("MMMM d, yyyy")} - ${endDate.toString("MMMM d, yyyy")}`;
        }
         if (dateRangeDisplay) {
             dateRangeDisplay.textContent = text;
         }
    }

    prevBtn.addEventListener('click', function() {
        // "SlotDay" navigates by week
        currentStartDate = currentStartDate.addDays(-7);
        refreshSchedulerAndUpdateView();
    });

    todayBtn.addEventListener('click', function() {
        // "SlotDay" resets to current week
        currentStartDate = DayPilot.Date.today().firstDayOfWeek();
        refreshSchedulerAndUpdateView();
    });

    nextBtn.addEventListener('click', function() {
        // "SlotDay" navigates by week
        currentStartDate = currentStartDate.addDays(7);
        refreshSchedulerAndUpdateView();
    });

    // Remove scaleSelector event listener as it's no longer needed
    // const scaleSelector = document.getElementById('scaleSelector');
    // if (scaleSelector) {
    //     scaleSelector.addEventListener('change', function() { /* ... */ });
    // }

    // Disable "My Shifts" option if no user is logged in
    if (downloadUserScopeSelect && (!window.currentUser || !window.currentUser.username)) {
        const myShiftsOption = downloadUserScopeSelect.querySelector('option[value="my_shifts"]');
        if (myShiftsOption) {
            myShiftsOption.disabled = true;
        }
    }
    // --- Download Schedule Handler ---
    if (downloadScheduleBtn) {
        downloadScheduleBtn.addEventListener('click', handleDownloadSchedule);
    }

    async function handleDownloadSchedule() {
        const startDate = downloadStartDateInput.value; // "YYYY-MM-DD"
        const endDate = downloadEndDateInput.value;
        const format = downloadFormatSelect.value;
        const userScope = downloadUserScopeSelect.value;

        if (!startDate || !endDate) {
            safeSchedulerMessage("Please select both a start and end date for the download.", { cssClass: "error", delay: 3000 });
            return;
        }
        if (new Date(startDate) > new Date(endDate)) {
            safeSchedulerMessage("Start date cannot be after end date.", { cssClass: "error", delay: 3000 });
            return;
        }

        let apiUrl = `/api/schedule/download?start_date=${encodeURIComponent(startDate)}&end_date=${encodeURIComponent(endDate)}&format=${encodeURIComponent(format)}&user_scope=${encodeURIComponent(userScope)}`;

        let filenameSuffix = "";
        if (userScope === "my_shifts" && window.currentUser && window.currentUser.username) {
            filenameSuffix = `_${window.currentUser.username.replace(/[^a-zA-Z0-9]/g, '_')}`;
        }

        try {
            const response = await fetchWithAuth(apiUrl, { method: 'GET' }); // Assumes fetchWithAuth can handle non-JSON responses

            if (!response.ok) {
                const errorText = await response.text(); // Try to get text for more detailed error
                console.error("Error downloading schedule:", response.status, errorText);
                safeSchedulerMessage(`Error ${response.status} downloading: ${errorText || 'Server error'}`, { cssClass: "error", delay: 5000 });
                return;
            }

            const blob = await response.blob();
            const filename = `schedule_${startDate.replace(/-/g, '')}_to_${endDate.replace(/-/g, '')}${filenameSuffix}.${format}`;
            const link = document.createElement('a');
            link.href = URL.createObjectURL(blob);
            link.download = filename;
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            URL.revokeObjectURL(link.href);
            safeSchedulerMessage("Schedule download started.", { delay: 2000 });

        } catch (error) {
            console.error("Failed to download schedule:", error);
            safeSchedulerMessage("Network error downloading schedule: " + error.message, { cssClass: "error", delay: 3000 });
        }
    }

    // Initialize the scheduler
    console.log("Calling initial refreshScheduler.");
    setTimeout(() => {
        refreshSchedulerAndUpdateView(true); // Pass true for isInitialCall to trigger the forced update
    }, 250); // Initial deferral for the entire sequence
});
