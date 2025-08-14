import { getUserProfile, checkAuth } from "/static/js/auth.js";
import { fetchWithAuth, showToast, apiRequest } from "/static/js/api.js";

document.addEventListener('DOMContentLoaded', function() {
    // --- MODAL AND FORM ELEMENTS ---
    const goalModalElement = document.getElementById('goalModal');
    const goalModal = goalModalElement ? new bootstrap.Modal(goalModalElement) : null;
    const goalModalLabel = document.getElementById('goalModalLabel');
    const goalForm = document.getElementById('goalForm');
    const goalIdInput = document.getElementById('goalIdInput');
    const goalDescriptionInput = document.getElementById('goalDescriptionInput');
    const saveGoalBtn = document.getElementById('saveGoalBtn');
    const reportModalElement = document.getElementById('reportModal');
    const reportModal = reportModalElement ? new bootstrap.Modal(reportModalElement) : null;
    const reportModalLabel = document.getElementById('reportModalLabel');
    const reportMissionIdInput = document.getElementById('reportMissionId');
    const generateReportBtn = document.getElementById('generateReportBtn');
    const saveToOverviewSwitch = document.getElementById('saveToOverview');
    const customFilenameGroup = document.getElementById('customFilenameGroup');
    const customFilenameInput = document.getElementById('customFilename');

    // --- USER CONTEXT ---
    const container = document.querySelector('.container[data-user-role]');
    const USER_ROLE = container ? container.dataset.userRole : '';
    const USER_ID = container ? parseInt(container.dataset.userId, 10) : null;

    // --- UTILITY FUNCTIONS ---
    // Simple HTML escape function to prevent XSS
    const escapeHTML = (str) => {
        return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#039;');
    };

    // --- DATA LOADING FUNCTIONS ---
    const loadAnnouncements = async () => {
        const panel = document.getElementById('announcementsPanel');
        try {
            const announcements = await apiRequest('/api/announcements/active', 'GET');
            const converter = new showdown.Converter();
            if (announcements.length > 0) {
                panel.innerHTML = announcements.map(a => `
                    <div class="alert alert-info" role="alert">
                        <h5 class="alert-heading">Announcement</h5>
                        ${converter.makeHtml(a.content)}
                        <hr>
                        <p class="mb-0 small text-muted">Posted by ${a.created_by_username} on ${new Date(a.created_at_utc).toLocaleDateString()}</p>
                    </div>
                `).join('');
            } else {
                panel.innerHTML = '<div class="alert alert-light">No active announcements.</div>';
            }
        } catch (error) {
            panel.innerHTML = '<div class="alert alert-warning">Could not load announcements.</div>';
        }
    };

    const loadUpcomingShifts = async () => {
        const content = document.getElementById('upcomingShiftsContent');
        try {
            const shifts = await apiRequest('/api/schedule/my-upcoming-shifts', 'GET');
            if (shifts.length > 0) {
                content.innerHTML = '<ul class="list-group list-group-flush">' + shifts.map(s => `
                    <li class="list-group-item">
                        <strong>Mission ${s.mission_id}</strong><br>
                        <small>${new Date(s.start_time_utc).toLocaleString()} - ${new Date(s.end_time_utc).toLocaleString()}</small>
                    </li>
                `).join('') + '</ul>';
            } else {
                content.innerHTML = '<p class="text-muted p-2">You have no upcoming shifts.</p>';
            }
        } catch (error) {
            content.innerHTML = '<p class="text-danger p-2">Could not load shifts.</p>';
        }
    };

    const loadTimesheetStatus = async () => {
        const content = document.getElementById('timesheetStatusContent');
        try {
            const status = await apiRequest('/api/timesheets/my-timesheet-status', 'GET');
            content.innerHTML = `
                <ul class="list-group list-group-flush">
                    <li class="list-group-item d-flex justify-content-between align-items-center">
                        Current Period
                        <span class="badge bg-primary rounded-pill">${status.current_period_status}</span>
                    </li>
                    <li class="list-group-item d-flex justify-content-between align-items-center">
                        Hours Logged
                        <span>${status.hours_this_period.toFixed(2)}</span>
                    </li>
                </ul>`;
        } catch (error) {
            content.innerHTML = '<p class="text-danger p-2">Could not load timesheet status.</p>';
        }
    };

    // --- MISSION GOAL AND NOTE LOGIC ---

    const getMissionContext = (element) => {
        const missionSection = element.closest('.mission-info-section');
        if (!missionSection) return null;
        const missionId = missionSection.dataset.missionId;
        return { missionSection, missionId };
    };

    // Handle opening the modal for ADDING a new goal
    const handleAddGoalClick = (target) => {
        const context = getMissionContext(target);
        if (!context) return;

        goalForm.reset();
        goalIdInput.value = '';
        goalModalLabel.textContent = `Add Goal for Mission ${context.missionId}`;
        // Store missionId on the modal form for the save function to use
        goalForm.dataset.missionId = context.missionId;
        goalModal.show();
    };

    // Handle opening the modal for EDITING an existing goal
    const handleEditGoalClick = (target) => {
        const context = getMissionContext(target);
        const goalId = target.dataset.goalId;
        const description = target.dataset.description;
        if (!context || !goalId) return;

        goalForm.reset();
        goalIdInput.value = goalId;
        goalDescriptionInput.value = description;
        goalModalLabel.textContent = `Edit Goal for Mission ${context.missionId}`;
        goalForm.dataset.missionId = context.missionId;
        goalModal.show();
    };

    // Handle SAVE button click in the modal (for both add and edit)
    const handleSaveGoal = async () => {
        const missionId = goalForm.dataset.missionId;
        const goalId = goalIdInput.value;
        const description = goalDescriptionInput.value.trim();

        if (!description || !missionId) {
            showToast('Description cannot be empty.', 'danger');
            return;
        }

        const isEditing = !!goalId;
        const url = isEditing ? `/api/missions/${missionId}/goals/${goalId}` : `/api/missions/${missionId}/goals`;
        const method = isEditing ? 'PUT' : 'POST';

        // Find the mission section to update based on the missionId from the form
        const missionSection = document.querySelector(`.mission-info-section[data-mission-id="${missionId}"]`);
        if (!missionSection) {
            console.error(`Could not find mission section for mission ID: ${missionId}`);
            return;
        }

        try {
            const savedGoal = await apiRequest(url, method, { description });
            showToast(`Goal ${isEditing ? 'updated' : 'added'} successfully.`);

            if (isEditing) {
                const goalItem = missionSection.querySelector(`li[data-goal-id="${goalId}"]`);
                if (goalItem) {
                    goalItem.querySelector('.form-check-label').textContent = description;
                    goalItem.querySelector('.edit-goal-btn').dataset.description = description;
                }
            } else {
                // Add the newly created goal to the list dynamically
                addGoalToList(missionId, missionSection, savedGoal);
            }

            goalModal.hide();
            updateGoalPlaceholder(missionSection);
        } catch (error) {
            // Error toast is shown by apiRequest
        }
    };

    // Handle DELETING a goal
    const handleDeleteGoal = async (target) => {
        const context = getMissionContext(target);
        const goalId = target.dataset.goalId;
        if (!context || !goalId) return;

        if (confirm('Are you sure you want to delete this goal?')) {
            try {
                await apiRequest(`/api/missions/${context.missionId}/goals/${goalId}`, 'DELETE');
                showToast('Goal deleted successfully.');
                const goalItem = target.closest('li[data-goal-id]');
                if (goalItem) {
                    const list = goalItem.parentElement;
                    goalItem.remove();
                    updateGoalPlaceholder(list.closest('.mission-info-section'));
                }
            } catch (error) {
                // Error toast is shown by apiRequest
            }
        }
    };

    // Handle COMPLETING/UNCOMPLETING a goal
    const handleToggleGoal = async (target) => {
        const context = getMissionContext(target);
        const goalId = target.dataset.goalId;
        if (!context || !goalId) return;

        const isCompleted = target.checked;
        try {
            // The API returns the full updated goal object, including completer info
            const updatedGoal = await apiRequest(`/api/missions/${context.missionId}/goals/${goalId}/toggle`, 'POST', { is_completed: isCompleted });
            showToast(`Goal marked as ${isCompleted ? 'complete' : 'incomplete'}.`);
            
            updateGoalCompletion(target.closest('li[data-goal-id]'), updatedGoal);
        } catch (error) {
            target.checked = !isCompleted; // Revert checkbox on failure
        }
    };

    // Handle ADDING a note
    const handleAddNote = async (target) => {
        const context = getMissionContext(target);
        if (!context) return;

        const textarea = context.missionSection.querySelector('.new-mission-note-content');
        const content = textarea.value.trim();

        if (!content) {
            showToast('Note content cannot be empty.', 'danger');
            return;
        }

        try {
            const newNote = await apiRequest(`/api/missions/${context.missionId}/notes`, 'POST', { content });
            if (newNote) {
                showToast('Note added successfully.');
                // Add the new note to the list
                addNoteToList(context.missionSection, newNote);
            } else {
                // Fallback if API doesn't return the new note
                window.location.reload();
            }
            textarea.value = ''; // Clear textarea after adding

        } catch (error) {
            // Error toast is shown by apiRequest
        }
    };

    // Handle DELETING a note
    const handleDeleteNote = async (target) => {
        const context = getMissionContext(target);
        const noteId = target.dataset.noteId;
        if (!context || !noteId) return;

        if (confirm('Are you sure you want to delete this note?')) {
            try {
                await apiRequest(`/api/missions/${context.missionId}/notes/${noteId}`, 'DELETE');
                showToast('Note deleted successfully.');
                const noteItem = target.closest('li[data-note-id]');
                if (noteItem) {
                    const list = noteItem.parentElement;
                    noteItem.remove();
                    updateNotePlaceholder(list.closest('.mission-info-section'));
                }
            } catch (error) {
                // Error toast is shown by apiRequest
            }
        }
    };


    // --- DYNAMIC DOM MANIPULATION HELPERS ---

    const updateGoalPlaceholder = (missionSection) => {
        const goalsList = missionSection.querySelector('.mission-goals-list');
        const placeholder = goalsList.querySelector('.no-mission-goals-placeholder');
        // If the list is empty, add a placeholder.
        if (goalsList.children.length === 0 && !placeholder) {
            goalsList.innerHTML = '<li class="list-group-item text-muted no-mission-goals-placeholder">No mission goals have been defined.</li>';
        } 
        // If the list has items and a placeholder, remove the placeholder.
        else if (goalsList.children.length > 1 && placeholder) {
            placeholder.remove();
        }
    };

    const updateNotePlaceholder = (missionSection) => {
        const notesList = missionSection.querySelector('.mission-notes-list');
        const placeholder = notesList.querySelector('.no-mission-notes-placeholder');
        if (notesList.children.length === 0 && !placeholder) {
            notesList.innerHTML = '<li class="list-group-item text-muted no-mission-notes-placeholder">No mission notes have been added.</li>';
        } else if (notesList.children.length > 0 && placeholder) {
            placeholder.remove();
        }
    };


    // Dynamically update goal completion state
    const updateGoalCompletion = (goalItem, updatedGoal) => {
        const label = goalItem.querySelector('.form-check-label');
        if (updatedGoal.is_completed) {
            label.classList.add('text-decoration-line-through', 'text-muted');
        } else {
            label.classList.remove('text-decoration-line-through', 'text-muted');
        }

        // Add or remove the "Completed by" badge
        let completedBadge = goalItem.querySelector('.badge.bg-success');
        if (updatedGoal.is_completed) {
            if (!completedBadge) {
                completedBadge = document.createElement('span');
                completedBadge.className = 'badge bg-success rounded-pill small ms-2';
                goalItem.appendChild(completedBadge); // Append it to the list item
            }
            completedBadge.textContent = `By: ${updatedGoal.completed_by_username}`;
            completedBadge.title = `Completed at ${new Date(updatedGoal.completed_at_utc).toLocaleString()}`;
        } else if (completedBadge) {
            completedBadge.remove();
        }
    };

    // Add a new goal to the list
    const addGoalToList = (missionId, missionSection, goal) => {
        const goalsList = missionSection.querySelector('.mission-goals-list');
        const newGoalItem = createGoalListItem(missionId, goal);
        
        const placeholder = goalsList.querySelector('.no-mission-goals-placeholder');
        if (placeholder) {
            placeholder.remove();
        }
        
        goalsList.appendChild(newGoalItem);
    };

    // Helper function to create a goal list item
    const createGoalListItem = (missionId, goal) => {
        const li = document.createElement('li');
        li.className = 'list-group-item d-flex justify-content-between align-items-start';
        li.dataset.goalId = goal.id;

        const isCompleted = goal.is_completed;
        const completedClass = isCompleted ? 'text-decoration-line-through text-muted' : '';
        
        let adminButtons = '';
        if (USER_ROLE === 'admin') {
            adminButtons = `
                <button class="btn btn-sm btn-link p-0 ms-2 edit-goal-btn" title="Edit Goal" data-goal-id="${goal.id}" data-description="${escapeHTML(goal.description)}"><i class="fas fa-pencil-alt"></i></button>
                <button class="btn btn-sm btn-link p-0 ms-2 text-danger delete-goal-btn" title="Delete Goal" data-goal-id="${goal.id}"><i class="fas fa-trash-alt"></i></button>
            `;
        }

        let completedBadge = '';
        if (isCompleted && goal.completed_by_username) {
            const completedDate = goal.completed_at_utc ? new Date(goal.completed_at_utc).toLocaleString() : '';
            completedBadge = `
                <span class="badge bg-success rounded-pill small ms-2" title="Completed at ${completedDate}">
                    By: ${goal.completed_by_username}
                </span>
            `;
        }

        li.innerHTML = `
            <div class="form-check flex-grow-1">
                <input class="form-check-input mission-goal-checkbox" type="checkbox" value="" id="goal-${missionId}-${goal.id}" data-goal-id="${goal.id}" ${isCompleted ? 'checked' : ''}>
                <label class="form-check-label ${completedClass}" for="goal-${missionId}-${goal.id}">
                    ${escapeHTML(goal.description)}
                </label>
                ${adminButtons}
            </div>
            ${completedBadge}
        `;

        return li;
    };

    // Add a new note to the list
    const addNoteToList = (missionSection, note) => {
        const notesList = missionSection.querySelector('.mission-notes-list');
        const newNoteItem = createNoteListItem(note);

        const placeholder = notesList.querySelector('.no-mission-notes-placeholder');
        if (placeholder) {
            placeholder.remove();
        }

        notesList.appendChild(newNoteItem);
    };

    // Helper function to create a note list item
    const createNoteListItem = (note) => {
        const li = document.createElement('li');
        li.className = 'list-group-item d-flex justify-content-between align-items-start';
        li.dataset.noteId = note.id;

        let deleteButton = '';
        if (USER_ROLE === 'admin' || (USER_ID && USER_ID === note.created_by_user_id)) {
            deleteButton = `<button class="btn btn-sm btn-outline-danger delete-note-btn ms-2" title="Delete Note" data-note-id="${note.id}"><i class="fas fa-trash-alt"></i></button>`;
        }

        li.innerHTML = `
            <div>
                <p class="mb-1">${escapeHTML(note.content)}</p>
                <small class="text-muted">&mdash; ${note.created_by_username || 'Unknown'} on ${new Date(note.created_at_utc).toLocaleString()}</small>
            </div>
            ${deleteButton}
        `;
        return li;
    };

    // --- REPORT GENERATION LOGIC ---

    const handleOpenReportModal = (button) => {
        const context = getMissionContext(button);
        if (!context || !reportModal) return;

        reportModalLabel.textContent = `Generate Report for Mission ${context.missionId}`;
        reportMissionIdInput.value = context.missionId;

        // Reset form fields to default state
        document.getElementById('startDate').value = '';
        document.getElementById('endDate').value = '';
        document.getElementById('includeTelemetry').checked = true;
        document.getElementById('includePower').checked = true;
        document.getElementById('includeCtd').checked = true;
        document.getElementById('includeWeather').checked = true;
        document.getElementById('includeWave').checked = true;
        document.getElementById('saveToOverview').checked = true;
        // Ensure the custom filename field is hidden and cleared on open
        customFilenameGroup.style.display = 'none';
        customFilenameInput.value = '';

        reportModal.show();
    };

    const handleGenerateReport = async () => {
        const missionId = reportMissionIdInput.value;
        const startDate = document.getElementById('startDate').value;
        const endDate = document.getElementById('endDate').value;
        const saveToOverview = document.getElementById('saveToOverview').checked;
        const customFilename = document.getElementById('customFilename').value.trim();

        const plotsToInclude = Array.from(document.querySelectorAll('#reportForm input[type="checkbox"]:checked'))
                                    .map(checkbox => checkbox.value);

        if (!missionId) {
            showToast('Mission ID is missing.', 'danger');
            return;
        }

        const options = {
            start_date: startDate || null,
            end_date: endDate || null,
            plots_to_include: plotsToInclude,
            save_to_overview: saveToOverview,
            custom_filename: customFilename || null
        };

        generateReportBtn.disabled = true;
        generateReportBtn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Generating...';

        try {
            const result = await apiRequest(`/api/reporting/missions/${missionId}/generate-weekly-report`, 'POST', options);
            showToast('Report generated successfully!', 'success');
            reportModal.hide();

            if (saveToOverview) {
                const missionSection = document.querySelector(`.mission-info-section[data-mission-id="${missionId}"]`);
                if (missionSection && result.weekly_report_url) {
                    const viewReportLink = missionSection.querySelector(`.view-report-link`);
                    if (viewReportLink) {
                        viewReportLink.href = result.weekly_report_url;
                        viewReportLink.style.display = 'inline-block';
                    }
                }
            } else {
                // If not saving to overview, open the report in a new tab for immediate viewing/download
                window.open(result.weekly_report_url, '_blank');
            }

        } finally {
            generateReportBtn.disabled = false;
            generateReportBtn.innerHTML = 'Generate Report';
        }
    };

    // --- EVENT LISTENER FOR REPORT MODAL SWITCH ---
    if (saveToOverviewSwitch) {
        saveToOverviewSwitch.addEventListener('change', (e) => {
            if (e.target.checked) {
                // If saving to overview, hide and clear the custom name field
                customFilenameGroup.style.display = 'none';
                customFilenameInput.value = '';
            } else {
                // If not saving, show the custom name field
                customFilenameGroup.style.display = 'block';
            }
        });
    }

    // --- GLOBAL EVENT LISTENER (EVENT DELEGATION) ---
    document.body.addEventListener('click', (e) => {
        const target = e.target;

        // Goal buttons
        if (target.closest('.add-goal-btn')) {
            e.preventDefault();
            handleAddGoalClick(target.closest('.add-goal-btn'));
        } else if (target.closest('.edit-goal-btn')) {
            e.preventDefault();
            handleEditGoalClick(target.closest('.edit-goal-btn'));
        } else if (target.closest('.delete-goal-btn')) {
            e.preventDefault();
            handleDeleteGoal(target.closest('.delete-goal-btn'));
        } else if (target.closest('#saveGoalBtn')) {
            e.preventDefault();
            handleSaveGoal();
        }

        // Note buttons
        else if (target.closest('.add-mission-note-btn')) {
            e.preventDefault();
            handleAddNote(target.closest('.add-mission-note-btn'));
        } else if (target.closest('.delete-note-btn')) {
            e.preventDefault();
            handleDeleteNote(target.closest('.delete-note-btn'));
        }

        // Report Generation buttons
        else if (target.closest('.generate-report-modal-btn')) {
            e.preventDefault();
            handleOpenReportModal(target.closest('.generate-report-modal-btn'));
        } else if (target.closest('#generateReportBtn')) {
            e.preventDefault();
            handleGenerateReport();
        }
    });

    // Separate listener for checkbox changes
    document.body.addEventListener('change', (e) => {
        const target = e.target;
        if (target.matches('.mission-goal-checkbox')) {
            handleToggleGoal(target);
        }
    });

    // --- INITIALIZATION ---
    const initializePage = () => {
        // Load sidebar and announcement data
        loadAnnouncements();
        loadUpcomingShifts();
        loadTimesheetStatus();

        // If a specific tab is targeted in the URL, show it
        const urlParams = new URLSearchParams(window.location.search);
        const missionTab = urlParams.get('mission_tab');
        if (missionTab) {
            const tabEl = document.querySelector(`#tab-${missionTab}`);
            if (tabEl) {
                const tab = new bootstrap.Tab(tabEl);
                tab.show();
            }
        }
    };

    initializePage();
});