/**
 * @file dashboard.js
 * @description Main dashboard with sensor data visualization
 */

import { checkAuth, logout } from '/static/js/auth.js';
import { apiRequest, fetchWithAuth, showToast } from '/static/js/api.js';

document.addEventListener('DOMContentLoaded', async function() {
    // --- Authentication Check ---
    if (!await checkAuth()) {
        return; // Stop further execution if not authenticated and redirection is handled by checkAuth
    }
    const missionId = document.body.dataset.missionId;
    // console.log("Dashboard.js: missionId from body.dataset:", missionId); // DEBUG
    const missionSelector = document.getElementById('missionSelector'); // Keep this
    const isHistorical = document.body.dataset.isHistorical === 'true';
    const isRealtimeMission = !isHistorical && document.body.dataset.isRealtime === 'true';
    const USER_ROLE = document.body.dataset.userRole || '';
    const USERNAME = document.body.dataset.username || '';
    const urlParams = new URLSearchParams(window.location.search);
    
    // Get enabled sensors from backend configuration
    const enabledSensorsStr = document.body.dataset.enabledSensors || '';
    const enabledSensors = enabledSensorsStr ? enabledSensorsStr.split(',') : [];
    
    // Helper function to check if a sensor is enabled
    function isSensorEnabled(sensorName) {
        return enabledSensors.length === 0 || enabledSensors.includes(sensorName);
    }

    // --- Mission Media ---
    const missionMediaForm = document.getElementById('missionMediaUploadForm');
    const missionMediaFile = document.getElementById('missionMediaFile');
    const missionMediaOperation = document.getElementById('missionMediaOperation');
    const missionMediaCaption = document.getElementById('missionMediaCaption');
    const missionMediaGallery = document.getElementById('missionMediaGallery');
    const missionMediaUploadBtn = document.getElementById('missionMediaUploadBtn');
    const missionMediaUploadSpinner = document.getElementById('missionMediaUploadSpinner');
    const overviewPlanContainer = document.getElementById('overviewPlanContainer');
    const overviewPlanLink = document.getElementById('overviewPlanLink');
    const overviewPlanEmpty = document.getElementById('overviewPlanEmpty');
    const overviewWeeklyReportContainer = document.getElementById('overviewWeeklyReportContainer');
    const overviewWeeklyReportLink = document.getElementById('overviewWeeklyReportLink');
    const overviewEndReportContainer = document.getElementById('overviewEndReportContainer');
    const overviewEndReportLink = document.getElementById('overviewEndReportLink');
    const overviewNoReports = document.getElementById('overviewNoReports');
    const overviewSensorTrackerContainer = document.getElementById('overviewSensorTrackerContainer');
    const overviewSensorTrackerEmpty = document.getElementById('overviewSensorTrackerEmpty');
    const overviewStTitle = document.getElementById('overviewStTitle');
    const overviewStStart = document.getElementById('overviewStStart');
    const overviewStEnd = document.getElementById('overviewStEnd');
    const overviewStPlatform = document.getElementById('overviewStPlatform');
    const overviewStDataRepo = document.getElementById('overviewStDataRepo');
    const overviewStDescription = document.getElementById('overviewStDescription');
    const overviewStInstruments = document.getElementById('overviewStInstruments');
    const overviewStInstrumentsList = document.getElementById('overviewStInstrumentsList');
    const dashboardMissionNotesList = document.getElementById('dashboardMissionNotesList');
    const dashboardMissionGoalsList = document.getElementById('dashboardMissionGoalsList');
    const goalModalElement = document.getElementById('goalModal');
    const goalModal = goalModalElement ? new bootstrap.Modal(goalModalElement) : null;
    const goalModalLabel = document.getElementById('goalModalLabel');
    const goalForm = document.getElementById('goalForm');
    const goalIdInput = document.getElementById('goalIdInput');
    const goalDescriptionInput = document.getElementById('goalDescriptionInput');
    const saveGoalBtn = document.getElementById('saveGoalBtn');

    const escapeHtml = (value) => {
        if (value === null || value === undefined) return '';
        return String(value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    };

    const formatTimestamp = (value) => {
        if (!value) return '-';
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return '-';
        return date.toLocaleString('en-US', {
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            timeZoneName: 'short'
        });
    };

    const renderMediaEmpty = (message) => {
        if (!missionMediaGallery) return;
        missionMediaGallery.innerHTML = `<div class="text-muted small">${message}</div>`;
    };

    const renderMediaCard = (media, canDelete) => {
        const col = document.createElement('div');
        col.className = 'col-md-4 mission-media-item';
        col.dataset.mediaId = media.id;

        const caption = media.caption ? escapeHtml(media.caption) : '';
        const operation = media.operation_type ? escapeHtml(media.operation_type) : 'Unspecified';
        const uploadedBy = escapeHtml(media.uploaded_by_username || 'Unknown');
        const isVideo = media.media_type === 'video';
        const mediaPreview = isVideo
            ? `<video class="card-img-top" controls preload="metadata" style="height: 150px; object-fit: cover;">
                    <source src="${media.file_url}">
               </video>`
            : `<a href="${media.file_url}" target="_blank" rel="noopener noreferrer">
                    <img src="${media.file_url}" class="card-img-top" alt="${caption || 'Mission media'}" style="height: 150px; object-fit: cover;">
               </a>`;

        const approvalStatus = media.approval_status || 'approved';
        const statusBadge = approvalStatus === 'pending'
            ? '<span class="badge bg-warning text-dark">Pending</span>'
            : approvalStatus === 'rejected'
                ? '<span class="badge bg-danger">Rejected</span>'
                : '<span class="badge bg-success">Approved</span>';
        const approveButtons = USER_ROLE === 'admin' && approvalStatus === 'pending'
            ? `<button type="button" class="btn btn-sm btn-success mt-2 mission-media-approve-btn" data-media-id="${media.id}">Approve</button>
               <button type="button" class="btn btn-sm btn-outline-warning mt-2 mission-media-reject-btn" data-media-id="${media.id}">Reject</button>`
            : '';
        const deleteButton = canDelete
            ? `<button type="button" class="btn btn-sm btn-outline-danger mt-2 mission-media-delete-btn" data-media-id="${media.id}">Delete</button>`
            : '';

        col.innerHTML = `
            <div class="card h-100">
                ${mediaPreview}
                <div class="card-body p-2">
                    <div class="small text-muted mb-1">${operation.charAt(0).toUpperCase() + operation.slice(1)} • ${uploadedBy}</div>
                    <div class="mb-1">${statusBadge}</div>
                    ${caption ? `<div class="small">${caption}</div>` : ''}
                    <div class="d-flex flex-wrap gap-2">
                        ${approveButtons}
                        ${deleteButton}
                    </div>
                </div>
            </div>
        `;
        return col;
    };

    const renderMissionNotes = (notes) => {
        if (!dashboardMissionNotesList) return;
        if (!notes || notes.length === 0) {
            dashboardMissionNotesList.innerHTML = '<li class="list-group-item text-muted no-mission-notes-placeholder">No mission comments have been added.</li>';
            return;
        }
        dashboardMissionNotesList.innerHTML = notes.map(note => {
            const canDelete = USER_ROLE === 'admin' || (USERNAME && note.created_by_username === USERNAME);
            return `
                <li class="list-group-item d-flex justify-content-between align-items-start" data-note-id="${note.id}">
                    <div>
                        <p class="mb-1">${escapeHtml(note.content)}</p>
                        <small class="text-muted">
                            &mdash; ${escapeHtml(note.created_by_username || 'Unknown')} on ${formatTimestamp(note.created_at_utc)}
                        </small>
                    </div>
                    ${canDelete ? `
                        <button class="btn btn-sm btn-outline-danger delete-note-btn ms-2" title="Delete Note" data-note-id="${note.id}">
                            <i class="fas fa-trash-alt"></i>
                        </button>
                    ` : ''}
                </li>
            `;
        }).join('');
    };

    const renderMissionGoals = (goals) => {
        if (!dashboardMissionGoalsList) return;
        if (!goals || goals.length === 0) {
            dashboardMissionGoalsList.innerHTML = '<li class="list-group-item text-muted no-mission-goals-placeholder">No mission goals have been defined.</li>';
            return;
        }
        dashboardMissionGoalsList.innerHTML = goals.map(goal => {
            const adminControls = USER_ROLE === 'admin'
                ? `
                    <button class="btn btn-sm btn-link p-0 ms-2 edit-goal-btn" title="Edit Goal" data-goal-id="${goal.id}" data-description="${escapeHtml(goal.description)}">
                        <i class="fas fa-pencil-alt"></i>
                    </button>
                    <button class="btn btn-sm btn-link p-0 ms-2 text-danger delete-goal-btn" title="Delete Goal" data-goal-id="${goal.id}">
                        <i class="fas fa-trash-alt"></i>
                    </button>
                `
                : '';
            const completedBadge = goal.is_completed
                ? `<span class="badge bg-success rounded-pill small ms-2" title="Completed at ${formatTimestamp(goal.completed_at_utc)}">
                        By: ${escapeHtml(goal.completed_by_username || '')}
                   </span>`
                : '';
            return `
                <li class="list-group-item d-flex justify-content-between align-items-start" data-goal-id="${goal.id}">
                    <div class="form-check flex-grow-1">
                        <input class="form-check-input mission-goal-checkbox" type="checkbox" id="goal-${goal.id}" data-goal-id="${goal.id}" ${goal.is_completed ? 'checked' : ''}>
                        <label class="form-check-label ${goal.is_completed ? 'text-decoration-line-through text-muted' : ''}" for="goal-${goal.id}">
                            ${escapeHtml(goal.description)}
                        </label>
                        ${adminControls}
                    </div>
                    ${completedBadge}
                </li>
            `;
        }).join('');
    };

    const loadMissionMedia = async () => {
        if (!missionMediaGallery) return;
        if (!missionId) {
            renderMediaEmpty('No mission selected.');
            return;
        }
        try {
            const includePending = USER_ROLE === 'admin' ? 'true' : 'false';
            const mediaItems = await apiRequest(`/api/missions/${missionId}/media?include_pending=${includePending}`, 'GET');
            if (!mediaItems || mediaItems.length === 0) {
                renderMediaEmpty('No media uploaded for this mission yet.');
                return;
            }
            missionMediaGallery.innerHTML = '';
            mediaItems.forEach((media) => {
                const canDelete = USER_ROLE === 'admin' || (USERNAME && media.uploaded_by_username === USERNAME);
                missionMediaGallery.appendChild(renderMediaCard(media, canDelete));
            });
        } catch (error) {
            renderMediaEmpty(`Failed to load media: ${error.message}`);
        }
    };

    if (missionMediaForm) {
        missionMediaForm.addEventListener('submit', async (event) => {
            event.preventDefault();
            if (!missionId) return;
            const fileToUpload = missionMediaFile ? missionMediaFile.files[0] : null;
            if (!fileToUpload) {
                showToast('Please select a media file to upload.', 'warning');
                return;
            }

            if (missionMediaUploadBtn) missionMediaUploadBtn.disabled = true;
            if (missionMediaUploadSpinner) missionMediaUploadSpinner.style.display = 'inline';

            const formData = new FormData();
            formData.append('file', fileToUpload);

            const params = new URLSearchParams();
            if (missionMediaCaption && missionMediaCaption.value.trim()) {
                params.append('caption', missionMediaCaption.value.trim());
            }
            if (missionMediaOperation && missionMediaOperation.value) {
                params.append('operation_type', missionMediaOperation.value);
            }
            const queryString = params.toString();
            const uploadUrl = `/api/missions/${missionId}/media/upload${queryString ? `?${queryString}` : ''}`;

            try {
                const response = await fetchWithAuth(uploadUrl, {
                    method: 'POST',
                    body: formData
                });
                if (!response.ok) {
                    const err = await response.json();
                    throw new Error(err.detail || 'Media upload failed.');
                }
                const media = await response.json();
                if (media.approval_status === 'pending') {
                    showToast('Media submitted for admin approval.', 'info');
                } else {
                    showToast('Media uploaded successfully!', 'success');
                }
                if (missionMediaFile) missionMediaFile.value = '';
                if (missionMediaCaption) missionMediaCaption.value = '';
                if (missionMediaOperation) missionMediaOperation.value = '';
                await loadMissionMedia();
            } catch (error) {
                showToast(`Upload failed: ${error.message}`, 'danger');
            } finally {
                if (missionMediaUploadBtn) missionMediaUploadBtn.disabled = false;
                if (missionMediaUploadSpinner) missionMediaUploadSpinner.style.display = 'none';
            }
        });
    }

    if (missionMediaGallery) {
        missionMediaGallery.addEventListener('click', async (event) => {
            const approveBtn = event.target.closest('.mission-media-approve-btn');
            if (approveBtn && USER_ROLE === 'admin') {
                const mediaId = approveBtn.dataset.mediaId;
                if (!mediaId) return;
                try {
                    await apiRequest(`/api/missions/${missionId}/media/${mediaId}/approve`, 'PUT');
                    showToast('Media approved.', 'success');
                    await loadMissionMedia();
                } catch (error) {
                    showToast(`Approval failed: ${error.message}`, 'danger');
                }
                return;
            }

            const rejectBtn = event.target.closest('.mission-media-reject-btn');
            if (rejectBtn && USER_ROLE === 'admin') {
                const mediaId = rejectBtn.dataset.mediaId;
                if (!mediaId) return;
                if (!confirm('Reject this media item?')) return;
                try {
                    await apiRequest(`/api/missions/${missionId}/media/${mediaId}/reject`, 'PUT');
                    showToast('Media rejected.', 'success');
                    await loadMissionMedia();
                } catch (error) {
                    showToast(`Rejection failed: ${error.message}`, 'danger');
                }
                return;
            }

            const deleteBtn = event.target.closest('.mission-media-delete-btn');
            if (!deleteBtn || !missionId) return;
            const mediaId = deleteBtn.dataset.mediaId;
            if (!mediaId) return;
            if (!confirm('Delete this media item?')) return;

            try {
                await apiRequest(`/api/missions/${missionId}/media/${mediaId}`, 'DELETE');
                showToast('Media deleted.', 'success');
                await loadMissionMedia();
            } catch (error) {
                showToast(`Delete failed: ${error.message}`, 'danger');
            }
        });
    }

    document.body.addEventListener('click', async (event) => {
        const addNoteBtn = event.target.closest('.add-mission-note-btn');
        if (addNoteBtn) {
            event.preventDefault();
            if (!missionId) return;
            const textarea = document.querySelector('.new-mission-note-content');
            const content = textarea ? textarea.value.trim() : '';
            if (!content) {
                showToast('Comment cannot be empty.', 'danger');
                return;
            }
            try {
                await apiRequest(`/api/missions/${missionId}/notes`, 'POST', { content });
                if (USER_ROLE === 'admin') {
                    showToast('Comment added successfully.', 'success');
                } else {
                    showToast('Comment submitted for admin approval.', 'success');
                }
                if (textarea) textarea.value = '';
                await loadMissionOverview();
            } catch (error) {
                showToast(`Failed to add comment: ${error.message}`, 'danger');
            }
            return;
        }

        const deleteNoteBtn = event.target.closest('.delete-note-btn');
        if (deleteNoteBtn) {
            event.preventDefault();
            if (!missionId) return;
            const noteId = deleteNoteBtn.dataset.noteId;
            if (!noteId) return;
            if (!confirm('Delete this comment?')) return;
            try {
                await apiRequest(`/api/missions/notes/${noteId}`, 'DELETE');
                showToast('Comment deleted.', 'success');
                await loadMissionOverview();
            } catch (error) {
                showToast(`Failed to delete comment: ${error.message}`, 'danger');
            }
            return;
        }

        const addGoalBtn = event.target.closest('.add-goal-btn');
        if (addGoalBtn) {
            event.preventDefault();
            if (USER_ROLE !== 'admin' || !goalModal) return;
            goalForm.reset();
            goalIdInput.value = '';
            goalModalLabel.textContent = `Add Goal for Mission ${missionId}`;
            goalForm.dataset.missionId = missionId;
            goalModal.show();
            return;
        }

        const editGoalBtn = event.target.closest('.edit-goal-btn');
        if (editGoalBtn) {
            event.preventDefault();
            if (USER_ROLE !== 'admin' || !goalModal) return;
            const goalId = editGoalBtn.dataset.goalId;
            const description = editGoalBtn.dataset.description || '';
            goalForm.reset();
            goalIdInput.value = goalId;
            goalDescriptionInput.value = description;
            goalModalLabel.textContent = `Edit Goal for Mission ${missionId}`;
            goalForm.dataset.missionId = missionId;
            goalModal.show();
            return;
        }

        const deleteGoalBtn = event.target.closest('.delete-goal-btn');
        if (deleteGoalBtn) {
            event.preventDefault();
            if (USER_ROLE !== 'admin') return;
            const goalId = deleteGoalBtn.dataset.goalId;
            if (!goalId) return;
            if (!confirm('Delete this goal?')) return;
            try {
                await apiRequest(`/api/missions/goals/${goalId}`, 'DELETE');
                showToast('Goal deleted.', 'success');
                await loadMissionOverview();
            } catch (error) {
                showToast(`Failed to delete goal: ${error.message}`, 'danger');
            }
            return;
        }
    });

    document.body.addEventListener('change', async (event) => {
        const goalCheckbox = event.target.closest('.mission-goal-checkbox');
        if (!goalCheckbox) return;
        if (!missionId) return;
        const goalId = goalCheckbox.dataset.goalId;
        if (!goalId) return;
        const isCompleted = goalCheckbox.checked;
        try {
            await apiRequest(`/api/missions/${missionId}/goals/${goalId}/toggle`, 'POST', { is_completed: isCompleted });
            await loadMissionOverview();
        } catch (error) {
            goalCheckbox.checked = !isCompleted;
            showToast(`Failed to update goal: ${error.message}`, 'danger');
        }
    });

    if (saveGoalBtn) {
        saveGoalBtn.addEventListener('click', async () => {
            if (USER_ROLE !== 'admin') return;
            const goalId = goalIdInput.value;
            const description = goalDescriptionInput.value.trim();
            if (!description) {
                showToast('Goal description cannot be empty.', 'danger');
                return;
            }
            const isEditing = !!goalId;
            const url = isEditing ? `/api/missions/goals/${goalId}` : `/api/missions/${missionId}/goals`;
            const method = isEditing ? 'PUT' : 'POST';
            try {
                await apiRequest(url, method, { description });
                if (goalModal) goalModal.hide();
                await loadMissionOverview();
            } catch (error) {
                showToast(`Failed to save goal: ${error.message}`, 'danger');
            }
        });
    }

    const loadMissionOverview = async () => {
        if (!missionId) return;
        try {
            const missionInfo = await apiRequest(`/api/missions/${missionId}/info`, 'GET');
            const overview = missionInfo?.overview || null;
            const weeklyReportUrl = overview?.weekly_report_url || null;
            const endReportUrl = overview?.end_of_mission_report_url || null;
            const planUrl = overview?.document_url || null;

            if (planUrl && overviewPlanLink && overviewPlanContainer && overviewPlanEmpty) {
                overviewPlanLink.href = planUrl;
                overviewPlanLink.textContent = planUrl.split('/').pop();
                overviewPlanContainer.style.display = 'block';
                overviewPlanEmpty.style.display = 'none';
            } else if (overviewPlanEmpty && overviewPlanContainer) {
                overviewPlanContainer.style.display = 'none';
                overviewPlanEmpty.style.display = 'block';
            }

            let hasReports = false;
            if (weeklyReportUrl && overviewWeeklyReportContainer && overviewWeeklyReportLink) {
                overviewWeeklyReportLink.href = weeklyReportUrl;
                overviewWeeklyReportLink.textContent = weeklyReportUrl.split('/').pop();
                overviewWeeklyReportContainer.style.display = 'block';
                hasReports = true;
            } else if (overviewWeeklyReportContainer) {
                overviewWeeklyReportContainer.style.display = 'none';
            }
            if (endReportUrl && overviewEndReportContainer && overviewEndReportLink) {
                overviewEndReportLink.href = endReportUrl;
                overviewEndReportLink.textContent = endReportUrl.split('/').pop();
                overviewEndReportContainer.style.display = 'block';
                hasReports = true;
            } else if (overviewEndReportContainer) {
                overviewEndReportContainer.style.display = 'none';
            }
            if (overviewNoReports) {
                overviewNoReports.style.display = hasReports ? 'none' : 'block';
            }

            const deployment = missionInfo?.sensor_tracker_deployment || null;
            const instruments = missionInfo?.sensor_tracker_instruments || [];
            if (deployment && overviewSensorTrackerContainer && overviewSensorTrackerEmpty) {
                overviewSensorTrackerContainer.style.display = 'block';
                overviewSensorTrackerEmpty.style.display = 'none';
                if (overviewStTitle) overviewStTitle.textContent = deployment.title || '-';
                if (overviewStStart) overviewStStart.textContent = deployment.start_time ? new Date(deployment.start_time).toLocaleString() : '-';
                if (overviewStEnd) overviewStEnd.textContent = deployment.end_time ? new Date(deployment.end_time).toLocaleString() : '-';
                if (overviewStPlatform) overviewStPlatform.textContent = deployment.platform_name || '-';
                if (overviewStDataRepo) {
                    if (deployment.data_repository_link) {
                        overviewStDataRepo.innerHTML = '';
                        const link = document.createElement('a');
                        link.href = deployment.data_repository_link;
                        link.target = '_blank';
                        link.rel = 'noopener noreferrer';
                        link.textContent = deployment.data_repository_link;
                        overviewStDataRepo.appendChild(link);
                    } else {
                        overviewStDataRepo.textContent = '-';
                    }
                }
                if (overviewStDescription) overviewStDescription.textContent = deployment.deployment_comment || '-';

                if (overviewStInstruments && overviewStInstrumentsList) {
                    overviewStInstrumentsList.innerHTML = '';
                    if (instruments.length > 0) {
                        instruments.forEach(inst => {
                            const li = document.createElement('li');
                            const name = inst.instrument_name || inst.instrument_identifier || 'Instrument';
                            const serial = inst.instrument_serial ? ` (${inst.instrument_serial})` : '';
                            li.textContent = `${name}${serial}`;
                            overviewStInstrumentsList.appendChild(li);
                        });
                        overviewStInstruments.style.display = 'block';
                    } else {
                        overviewStInstruments.style.display = 'none';
                    }
                }
            } else if (overviewSensorTrackerContainer && overviewSensorTrackerEmpty) {
                overviewSensorTrackerContainer.style.display = 'none';
                overviewSensorTrackerEmpty.style.display = 'block';
            }

            renderMissionNotes(missionInfo?.notes || []);
            renderMissionGoals(missionInfo?.goals || []);
        } catch (error) {
            if (overviewPlanEmpty) overviewPlanEmpty.textContent = 'Failed to load overview.';
        }
    };

    // Initial media load
    loadMissionMedia();
    loadMissionOverview();

    let powerChartInstance = null;
    let ctdChartInstance = null;
    let weatherSensorChartInstance = null;
    let waveChartInstance = null;
    let vr2cChartInstance = null;
    let ctdProfileChartInstance = null; // Instance for the new CTD profile chart
    let solarPanelChartInstance = null; // Instance for the new solar panel chart
    let fluorometerChartInstance = null;
    let wgVm4ChartInstance = null; // New WG-VM4 chart
    let waveHeightDirectionChartInstance = null; // Keep this for Hs vs Dp
    let waveSpectrumChartInstance = null; // Instance for the new Wave Spectrum chart
    let telemetryChartInstance = null; // Instance for the new Telemetry chart
    let navigationCurrentChartInstance = null; // Instance for Ocean Current chart
    let navigationHeadingDiffChartInstance = null; // Instance for Heading Difference chart

    // --- Chart Color Variables ---
    // We use 'let' so we can update them when the theme changes.
    let chartTextColor, chartGridColor, miniChartLineColor;

    // Function to update the color variables from CSS
    function updateChartColorVariables() {
        const styles = getComputedStyle(document.documentElement);
        chartTextColor = styles.getPropertyValue('--text-color').trim();
        chartGridColor = styles.getPropertyValue('--card-border').trim();
        miniChartLineColor = styles.getPropertyValue('--active-card-accent').trim();
    }

    // Initial call to set colors on page load
    updateChartColorVariables();
    const miniChartInstances = {};

    // Helper function to show spinner with animation restart
    function showChartSpinner(spinner) {
        if (spinner) {
            // Remove and re-add the spinner-border class to restart animation
            spinner.classList.remove('spinner-border');
            // Use requestAnimationFrame to ensure the class removal is processed
            requestAnimationFrame(() => {
                spinner.style.display = 'block';
                spinner.classList.add('spinner-border');
            });
        }
    }

    // Helper function to hide spinner
    function hideChartSpinner(spinner) {
        if (spinner) {
            spinner.style.display = 'none';
        }
    }

    // Centralized Chart Colors
    const CHART_COLORS = {
        POWER_BATTERY: 'rgba(54, 162, 235, 1)',
        POWER_SOLAR: 'rgba(255, 159, 64, 1)',
        POWER_DRAW: 'rgba(255, 99, 132, 1)',
        CTD_TEMP: 'rgba(0, 191, 255, 1)',
        CTD_SALINITY: 'rgba(255, 105, 180, 1)',
        CTD_CONDUCTIVITY: 'rgba(123, 104, 238, 1)', // Medium Slate Blue
        CTD_DO: 'rgba(60, 179, 113, 1)', // Medium Sea Green (re-use from weather)
        WEATHER_AIR_TEMP: 'rgba(255, 99, 71, 1)',
        WEATHER_WIND_SPEED: 'rgba(60, 179, 113, 1)',
        WAVES_SIG_HEIGHT: 'rgba(255, 206, 86, 1)',
        WAVES_PERIOD: 'rgba(153, 102, 255, 1)',
        VR2C_DETECTION: 'rgba(75, 192, 192, 1)', // Teal
        WG_VM4_CH0_DETECTION: 'rgba(255, 159, 64, 1)', // Orange for WG-VM4 Channel 0
        WAVE_SPECTRUM: 'rgba(255, 99, 132, 1)', // A distinct color for the spectrum line
        FLUORO_C_AVG_PRIMARY: 'rgba(75, 192, 192, 1)', // Teal for C1_Avg
        SOLAR_PANEL_1: 'rgba(255, 215, 0, 1)', // Gold
        SOLAR_PANEL_2: 'rgba(173, 216, 230, 1)', // Light Blue
        SOLAR_PANEL_4: 'rgba(144, 238, 144, 1)', // Light Green
        FLUORO_TEMP: 'rgba(255, 99, 132, 1)', // Red for Fluorometer Temp
        NAV_SPEED: 'rgba(138, 43, 226, 1)', // BlueViolet for Glider Speed
        NAV_SOG: 'rgba(0, 128, 0, 0.7)',   // Green (slightly transparent) for SOG
        NAV_HEADING: 'rgba(255, 140, 0, 1)', // DarkOrange for Heading
        OCEAN_CURRENT_SPEED: 'rgba(30, 144, 255, 1)', // DodgerBlue
        OCEAN_CURRENT_DIRECTION: 'rgba(255, 69, 0, 1)', // OrangeRed
        HEADING_DIFF: 'rgba(218, 112, 214, 1)' // Orchid
    };

    const currentSource = urlParams.get('source') || 'remote';
    const currentLocalPath = urlParams.get('local_path') || '';
    // auotrefresh timer and countdown
    const autoRefreshIntervalMinutes = 5;
    let autoRefreshEnabled = true; // Default to true, will be updated by checkbox/localStorage
    let countdownTimer = null;

    // Date range functionality is now handled per-report-type by checking input values directly

    // Date range utility functions
    function initializeDateRangeInputs() {
        const dateRangeInputs = document.querySelectorAll('.date-range-input');
        dateRangeInputs.forEach(input => {
            // Don't set default values - let users choose their own dates
            // Only add event listeners
            input.addEventListener('change', handleDateRangeChange);
            input.addEventListener('input', handleDateRangeChange); // Also listen to input events for real-time updates
            
            // Check if this input already has a value and trigger the change handler
            if (input.value) {
                handleDateRangeChange({ target: input });
            }
        });
    }

    function initializeClearButtons() {
        const clearButtons = document.querySelectorAll('[id^="clear-date-"]');
        clearButtons.forEach(button => {
            button.addEventListener('click', function() {
                const reportType = this.id.replace('clear-date-', '');
                clearDateRange(reportType);
            });
        });
    }

    function initializeAllDateRangeStates() {
        // Get all unique report types from date range inputs
        const reportTypes = new Set();
        document.querySelectorAll('.date-range-input').forEach(input => {
            if (input.dataset.reportType) {
                reportTypes.add(input.dataset.reportType);
            }
        });
        
        // Initialize state for each report type
        reportTypes.forEach(reportType => {
            const startInput = document.getElementById(`start-date-${reportType}`);
            const endInput = document.getElementById(`end-date-${reportType}`);
            const clearButton = document.getElementById(`clear-date-${reportType}`);
            
            if (startInput && endInput) {
                const startValue = startInput.value;
                const endValue = endInput.value;
                
                // Show/hide clear button based on existing values
                if (clearButton) {
                    if (startValue || endValue) {
                        clearButton.style.display = 'inline-block';
                    } else {
                        clearButton.style.display = 'none';
                    }
                }
                
                // Set hours input state based on date range
                const hoursInput = document.getElementById(`hours-back-${reportType}`);
                if (hoursInput) {
                    if (startValue && endValue) {
                        hoursInput.disabled = true;
                        hoursInput.style.opacity = '0.5';
                    } else {
                        hoursInput.disabled = false;
                        hoursInput.style.opacity = '1';
                    }
                }
            }
        });
    }

    function handleDateRangeChange(event) {
        const input = event.target;
        const reportType = input.dataset.reportType;
        
        // Get both start and end inputs for this report type
        const startInput = document.getElementById(`start-date-${reportType}`);
        const endInput = document.getElementById(`end-date-${reportType}`);
        const clearButton = document.getElementById(`clear-date-${reportType}`);
        
        if (startInput && endInput) {
            const startValue = startInput.value;
            const endValue = endInput.value;
            
            // Show/hide clear button based on whether any date is set
            if (clearButton) {
                if (startValue || endValue) {
                    clearButton.style.display = 'inline-block';
                } else {
                    clearButton.style.display = 'none';
                }
            }
            
            // Check if both dates are provided
            if (startValue && endValue) {
                const startDate = new Date(startValue);
                const endDate = new Date(endValue);
                
                // Validate date range
                if (startDate >= endDate) {
                    displayGlobalError('Start date must be before end date.');
                    return;
                }
                
                // Disable hours back input when date range is active
                const hoursInput = document.getElementById(`hours-back-${reportType}`);
                if (hoursInput) {
                    hoursInput.disabled = true;
                    hoursInput.style.opacity = '0.5';
                }
            } else {
                // If either date is cleared, re-enable hours back input
                const hoursInput = document.getElementById(`hours-back-${reportType}`);
                if (hoursInput) {
                    hoursInput.disabled = false;
                    hoursInput.style.opacity = '1';
                }
            }
            
            // Always reload chart data when date inputs change
            const loader = getSensorLoader(reportType);
            if (loader) {
                loader();
            }
        }
    }

    function clearDateRange(reportType) {
        const startInput = document.getElementById(`start-date-${reportType}`);
        const endInput = document.getElementById(`end-date-${reportType}`);
        const clearButton = document.getElementById(`clear-date-${reportType}`);
        
        if (startInput) {
            startInput.value = '';
        }
        if (endInput) {
            endInput.value = '';
        }
        
        // Hide the clear button
        if (clearButton) {
            clearButton.style.display = 'none';
        }
        
        // Re-enable hours back input
        const hoursInput = document.getElementById(`hours-back-${reportType}`);
        if (hoursInput) {
            hoursInput.disabled = false;
            hoursInput.style.opacity = '1';
        }
        
        // Reload chart data
        const loader = getSensorLoader(reportType);
        if (loader) {
            loader();
        }
    }


    function startCountdownTimer() {
        const countdownElement = document.getElementById('refreshCountdown');
        if (!countdownElement) return;
        if (!autoRefreshEnabled) return; // Don't start if disabled

        let remainingSeconds = autoRefreshIntervalMinutes * 60;

        function updateCountdownDisplay() {
            const minutes = Math.floor(remainingSeconds / 60);
            const seconds = remainingSeconds % 60;
            const display = `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
            countdownElement.textContent = ` (Next refresh in ${display})`;

            if (remainingSeconds <= 0) {
                clearInterval(countdownTimer); // Stop the countdown
                countdownElement.textContent = ''; // Clear when done
            } else {
                remainingSeconds--;
            }
        }
        updateCountdownDisplay();
        countdownTimer = setInterval(updateCountdownDisplay, 1000);
    }

    const dataSourceModalEl = document.getElementById('dataSourceModal'); // Get the modal element
    if (dataSourceModalEl) {
        const localPathInputGroup = document.getElementById('localPathInputGroup');
        const customLocalPathInput = document.getElementById('customLocalPath');
        const applyDataSourceBtn = document.getElementById('applyDataSource');

        document.querySelectorAll('input[name="dataSourceOption"]').forEach(radio => {
            radio.addEventListener('change', function() {
                if (this.value === 'local') {
                    localPathInputGroup.style.display = 'block';
                } else {
                    localPathInputGroup.style.display = 'none';
                }
            });
        });

        applyDataSourceBtn.addEventListener('click', function() {
            const selectedSource = document.querySelector('input[name="dataSourceOption"]:checked').value;
            let newLocalPath = '';
            if (selectedSource === 'local') {
                newLocalPath = customLocalPathInput.value.trim();
            }

            const currentUrl = new URL(window.location.href);
            currentUrl.searchParams.set('source', selectedSource);
            if (newLocalPath) {
                currentUrl.searchParams.set('local_path', newLocalPath);
            } else {
                currentUrl.searchParams.delete('local_path');
            }
            const modalInstance = bootstrap.Modal.getInstance(dataSourceModalEl);
            if (modalInstance) {
                modalInstance.hide();
            }
            setTimeout(() => { window.location.href = currentUrl.toString(); }, 150);
        });
    }

    // Fetch and populate missions *after* auth check and other initial setup


    // --- Auto-Refresh Toggle Logic ---
    const autoRefreshToggle = document.getElementById('autoRefreshToggleBanner');

    // Cache polling for real-time missions
    // Note: Background cache refresh runs every 10 minutes (configured in .env)
    // Polling every 30 seconds ensures we detect updates within 30 seconds of cache refresh
    let cachePollInterval = null;
    const CACHE_POLL_INTERVAL_MS = 30000; // Poll every 30 seconds (cache refreshes every 10 min)

    async function pollCacheStatus() {
        // Debug logging
        if (!isRealtimeMission) {
            console.debug('Cache polling skipped: Not a real-time mission');
            return;
        }
        if (!autoRefreshEnabled) {
            console.debug('Cache polling skipped: Auto-refresh disabled');
            return;
        }

        try {
            console.debug(`Polling cache status for mission ${missionId}...`);
            const cacheStatus = await apiRequest(`/api/cache-status/${missionId}`, 'GET');
            console.debug('Cache status received:', cacheStatus);
            
            // Track if any cache has been updated
            let cacheUpdated = false;
            let updatedReportTypes = [];
            
            // Check each report type for updates
            for (const [reportType, status] of Object.entries(cacheStatus)) {
                const stored = cacheTimestamps.get(reportType);
                
                // If we have stored timestamps, compare with server
                if (stored && status.cache_timestamp) {
                    const storedTime = new Date(stored.cache_timestamp);
                    const serverTime = new Date(status.cache_timestamp);
                    
                    // If server cache timestamp is newer, data has been updated
                    if (serverTime > storedTime) {
                        const timeDiff = (serverTime - storedTime) / 1000; // seconds
                        console.log(`Cache updated for ${reportType}: stored=${stored.cache_timestamp}, server=${status.cache_timestamp}, diff=${timeDiff.toFixed(1)}s`);
                        cacheUpdated = true;
                        updatedReportTypes.push(reportType);
                        // Update stored timestamp
                        cacheTimestamps.set(reportType, {
                            cache_timestamp: status.cache_timestamp,
                            last_data_timestamp: status.last_data_timestamp
                        });
                    } else {
                        console.debug(`Cache for ${reportType} unchanged: stored=${stored.cache_timestamp}, server=${status.cache_timestamp}`);
                    }
                } else if (status.cache_timestamp && !stored) {
                    // First time seeing this report type with cache data
                    console.debug(`Initializing cache timestamp for ${reportType}: ${status.cache_timestamp}`);
                    cacheTimestamps.set(reportType, {
                        cache_timestamp: status.cache_timestamp,
                        last_data_timestamp: status.last_data_timestamp
                    });
                } else if (!status.cache_timestamp) {
                    console.debug(`No cache timestamp available for ${reportType}`);
                }
            }
            
            // If any cache was updated, force a full page refresh
            if (cacheUpdated) {
                console.log(`Cache refresh detected for: ${updatedReportTypes.join(', ')}. Reloading page...`);
                // Use window.location.reload(true) to force a hard refresh (bypass cache)
                window.location.reload(true);
            } else {
                console.debug('No cache updates detected in this poll');
            }
        } catch (error) {
            console.warn('Error polling cache status:', error);
            // Don't show toast for polling errors to avoid spam
        }
    }

    function updateAutoRefreshState(isEnabled) {
        autoRefreshEnabled = isEnabled;
        localStorage.setItem('autoRefreshEnabled', isEnabled);
        if (isEnabled && isRealtimeMission) {
            startCountdownTimer(); // Restart countdown if enabled and on a real-time mission
            // Start cache polling
            if (!cachePollInterval) {
                console.log(`Starting cache polling: interval=${CACHE_POLL_INTERVAL_MS}ms, mission=${missionId}, isRealtime=${isRealtimeMission}`);
                cachePollInterval = setInterval(pollCacheStatus, CACHE_POLL_INTERVAL_MS);
                // Do an initial poll immediately
                pollCacheStatus();
            }
        } else {
            clearInterval(countdownTimer);
            // Stop cache polling
            if (cachePollInterval) {
                console.log('Stopping cache polling');
                clearInterval(cachePollInterval);
                cachePollInterval = null;
            }
            const countdownElement = document.getElementById('refreshCountdown');
            if (countdownElement) countdownElement.textContent = ''; // Clear countdown display
        }
    }

    if (autoRefreshToggle) {
        const savedPreference = localStorage.getItem('autoRefreshEnabled');
        if (savedPreference !== null) {
            autoRefreshToggle.checked = JSON.parse(savedPreference);
        }
        updateAutoRefreshState(autoRefreshToggle.checked); // Initialize based on current state (saved or default)

        autoRefreshToggle.addEventListener('change', function() {
            updateAutoRefreshState(this.checked);
        });
    }

    // Legacy auto-refresh (full page reload) - keep as fallback for very long periods
    // Cache polling will handle most refreshes, but this ensures we refresh even if polling fails
    if (isRealtimeMission) {
        setTimeout(function() {
            if (autoRefreshEnabled && !document.querySelector('.modal.show')) { 
                // Fallback: refresh after the configured interval even if polling didn't detect changes
                // This handles edge cases where cache timestamps might not change but data did
                console.log('Fallback auto-refresh triggered after interval');
                window.location.reload(true); 
            }
        }, autoRefreshIntervalMinutes * 60 * 1000);
    }

    function displayGlobalError(message) {
        const errorDiv = document.getElementById('generalErrorDisplay');
        errorDiv.textContent = message || 'An error occurred. Please check console or try again later.';
        errorDiv.style.display = 'block';
    }
    // Refresh Data Button Logic
    /**
     * Fetches chart data from the API for a given report type and mission.
     * @param {string} reportType - The type of report (e.g., 'power', 'ctd').
     * @param {string} mission - The mission ID.
     * @param {number} hours - The number of hours back to fetch data for.
     * @returns {Promise<Array<Object>|null>} A promise that resolves with the chart data array or null if fetching fails.
     */
    // Store cache timestamps for each report type
    const cacheTimestamps = new Map(); // reportType -> { cache_timestamp, last_data_timestamp }

    async function fetchChartData(reportType, mission) {
        const chartCanvas = document.getElementById(`${reportType}Chart`); 
        const spinner = chartCanvas ? chartCanvas.parentElement.querySelector('.chart-spinner') : null;
        showChartSpinner(spinner);

        // Find controls specific to this report type, if they exist.
        const hoursInput = document.querySelector(`.hours-back-input[data-report-type="${reportType}"]`);
        const granularitySelect = document.querySelector(`.granularity-select[data-report-type="${reportType}"]`);

        const hours = hoursInput ? hoursInput.value : 72; // Default to 72 if no input found
        const granularity = granularitySelect ? granularitySelect.value : 15; // Default to 15 min if no select found

        try {
            // Check if date range is enabled for this report type
            const startInput = document.getElementById(`start-date-${reportType}`);
            const endInput = document.getElementById(`end-date-${reportType}`);
            const isDateRangeActive = startInput && endInput && startInput.value && endInput.value;
            
            let apiUrl;
            if (isDateRangeActive) {
                // Use date range mode - don't include hours_back parameter
                apiUrl = `/api/data/${reportType}/${mission}?granularity_minutes=${granularity}`;
                
                // Add date range parameters
                const startDate = new Date(startInput.value);
                const endDate = new Date(endInput.value);
                const startISO = startDate.toISOString();
                const endISO = endDate.toISOString();
                apiUrl += `&start_date=${encodeURIComponent(startISO)}&end_date=${encodeURIComponent(endISO)}`;
                
                // Date range mode
            } else {
                // Use hours back mode
                apiUrl = `/api/data/${reportType}/${mission}?hours_back=${hours}&granularity_minutes=${granularity}`;
            }
            
            apiUrl += `&source=${currentSource}`;
            if (currentSource === 'local' && currentLocalPath) {
                apiUrl += `&local_path=${encodeURIComponent(currentLocalPath)}`;
            }
            if (urlParams.has('refresh') && urlParams.get('refresh') === 'true') {
                apiUrl += `&refresh=true`;
            }
            
            const response = await apiRequest(apiUrl, 'GET');
            
            // Handle new response format with cache metadata
            let data;
            if (response && typeof response === 'object' && 'data' in response) {
                // New format with cache_metadata
                data = response.data;
                // Store cache timestamps
                if (response.cache_metadata) {
                    cacheTimestamps.set(reportType, {
                        cache_timestamp: response.cache_metadata.cache_timestamp,
                        last_data_timestamp: response.cache_metadata.last_data_timestamp,
                        file_modification_time: response.cache_metadata.file_modification_time
                    });
                }
            } else {
                // Legacy format (array directly) - backward compatibility
                data = response;
            }
            
            return data;
        } catch (error) {
            showToast(`Error loading ${reportType} data: ${error.message}`, 'danger');
            displayGlobalError(`Network error while fetching ${reportType} chart data.`);
            return null;
        } finally {
            hideChartSpinner(spinner);
        }
    }

    /**
     * Renders the LARGE Power Chart using Chart.js.
     * @param {Array<Object>|null} chartData - The data array fetched from the API.
     */
    function renderPowerChart(chartData) {
        // console.log('Attempting to render Power Chart. Data received:', chartData);
        const ctx = document.getElementById('powerChart').getContext('2d');
        const spinner = ctx.canvas.parentElement.querySelector('.chart-spinner');
        hideChartSpinner(spinner); // Hide spinner before rendering or showing "no data"


        if (!chartData || chartData.length === 0) {
            // console.log('No data or empty data array for Power Chart.');
            // Display a message on the canvas if no data
            ctx.font = "16px Arial";
            ctx.fillStyle = "grey";
            ctx.textAlign = "center";
            ctx.fillText("No power trend data available to display.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            if (powerChartInstance) { powerChartInstance.destroy(); powerChartInstance = null; }
            return;
        }

        const datasets = [];
        // Dynamically add datasets based on available data
        if (chartData.some(d => d.BatteryWattHours !== null && d.BatteryWattHours !== undefined)) {
            datasets.push({
                label: 'Battery (Wh)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.BatteryWattHours })),
                borderColor: CHART_COLORS.POWER_BATTERY,
                yAxisID: 'yBattery', // Assign to new right-hand Y-axis
                tension: 0.1, fill: false
            });
        }
        if (chartData.some(d => d.PowerDrawWatts !== null && d.PowerDrawWatts !== undefined)) {
            datasets.push({
                label: 'Power Draw (W)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.PowerDrawWatts })),
                borderColor: CHART_COLORS.POWER_DRAW,
                yAxisID: 'ySolar', // Share with Solar Input
                tension: 0.1, fill: false
            });
        }

        if (datasets.length === 0) {
            // console.warn('Power Chart: No valid datasets could be formed from the provided chartData.');
            ctx.font = "16px Arial";
            ctx.fillStyle = "grey";
            ctx.textAlign = "center";
            ctx.fillText("No plottable power data found.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            if (powerChartInstance) { powerChartInstance.destroy(); powerChartInstance = null; }
            return;
        }

        if (powerChartInstance) {
            powerChartInstance.destroy(); // Clear previous chart if any
        }

        powerChartInstance = new Chart(ctx, {
            type: 'line',
            data: { datasets: datasets },
            options: {
                responsive: true, // Keep responsive
                maintainAspectRatio: false, // Keep aspect ratio false
                scales: {
                    x: {
                        type: 'time',
                        time: { unit: 'hour', tooltipFormat: 'MMM d, yyyy HH:mm', displayFormats: { hour: 'MMM d HH:mm', day: 'MMM d' } },
                        title: { display: true, text: 'Time', color: chartTextColor },
                        ticks: {
                            color: chartTextColor,
                            maxRotation: 0,
                            autoSkip: true,
                            autoSkipPadding: 20
                        },
                        grid: { color: chartGridColor }
                    },
                    ySolar: { type: 'linear', position: 'left', title: { display: true, text: 'Watts (W)', color: chartTextColor }, ticks: { color: chartTextColor }, grid: { color: chartGridColor } },
                    yBattery: { type: 'linear', position: 'right', title: { display: true, text: 'Watt-hours (Wh)', color: chartTextColor }, ticks: { color: chartTextColor }, grid: { drawOnChartArea: false } } // New axis for Battery
                },
                plugins: { tooltip: { mode: 'index', intersect: false }, legend: { position: 'top', labels: { color: chartTextColor } } }
            }
        });
    }

    /**
     * Renders the CTD Chart using Chart.js.
     * @param {Array<Object>|null} chartData - The data array fetched from the API.
     */
    function renderCtdChart(chartData) { // This function was missing in the previous diff
        // console.log('Attempting to render CTD Chart. Data received:', chartData);
        const ctx = document.getElementById('ctdChart').getContext('2d');
        const spinner = ctx.canvas.parentElement.querySelector('.chart-spinner');
        hideChartSpinner(spinner);

        if (!chartData || chartData.length === 0) {
            // console.log('No data or empty data array for CTD Chart.');
            ctx.font = "16px Arial";
            ctx.fillStyle = "grey";
            ctx.textAlign = "center";
            ctx.fillText("No CTD trend data available to display.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            if (ctdChartInstance) { ctdChartInstance.destroy(); ctdChartInstance = null; }
            return;
        }

        const datasets = [];
        if (chartData.some(d => d.WaterTemperature !== null && d.WaterTemperature !== undefined)) {
            datasets.push({
                label: 'Water Temp (°C)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.WaterTemperature })),
                borderColor: CHART_COLORS.CTD_TEMP,
                yAxisID: 'yTemp', // Assign to a specific Y axis
                tension: 0.1, fill: false
            });
        }
        if (chartData.some(d => d.Salinity !== null && d.Salinity !== undefined)) {
            datasets.push({
                label: 'Salinity (PSU)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.Salinity })),
                borderColor: CHART_COLORS.CTD_SALINITY,
                yAxisID: 'ySalinity', // Assign to a different Y axis
                tension: 0.1, fill: false
            });
        }
        // Add other CTD metrics (Conductivity, DissolvedOxygen, Pressure) similarly, potentially on new axes or separate charts

        if (datasets.length === 0) {
            // console.warn('CTD Chart: No valid datasets could be formed from the provided chartData.');
            ctx.font = "16px Arial";
            ctx.fillStyle = "grey";
            ctx.textAlign = "center";
            ctx.fillText("No plottable CTD data found.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            if (ctdChartInstance) { ctdChartInstance.destroy(); ctdChartInstance = null; }
            return;
        }

        if (ctdChartInstance) {
            ctdChartInstance.destroy();
        }

        ctdChartInstance = new Chart(ctx, {
            type: 'line',
            data: { datasets: datasets },
            options: {
                                responsive: true, // Keep responsive
                maintainAspectRatio: false, // Keep aspect ratio false
                scales: {
                    x: {
                        type: 'time',
                        time: { unit: 'hour', tooltipFormat: 'MMM d, yyyy HH:mm', displayFormats: { hour: 'MMM d HH:mm', day: 'MMM d' } },
                        title: { display: true, text: 'Time', color: chartTextColor },
                        ticks: {
                            color: chartTextColor,
                            maxRotation: 0,
                            autoSkip: true,
                            autoSkipPadding: 20
                        },
                        grid: { color: chartGridColor }
                    },
                    yTemp: { type: 'linear', position: 'left', title: { display: true, text: 'Temperature (°C)', color: chartTextColor }, ticks: { color: chartTextColor }, grid: { color: chartGridColor } },
                    ySalinity: { type: 'linear', position: 'right', title: { display: true, text: 'Salinity (PSU)', color: chartTextColor }, ticks: { color: chartTextColor }, grid: { drawOnChartArea: false } } // Secondary axis for Salinity
                },
                plugins: { tooltip: { mode: 'index', intersect: false }, legend: { position: 'top', labels: { color: chartTextColor } } }
            }
        });
    }

    // Fetch and render the CTD chart on page load (only if enabled)
    if (isSensorEnabled('ctd')) {
        fetchChartData('ctd', missionId).then(data => {
            renderCtdChart(data); // Existing chart for Temp & Salinity
            renderCtdProfileChart(data); // New chart for Temp, Conductivity, DO
        });
    }
    // Fetch and render the Weather Sensor chart on page load (only if enabled)
    if (isSensorEnabled('weather')) {
        fetchChartData('weather', missionId).then(data => {
            renderWeatherSensorChart(data);
        });
    }

    // Fetch Power and Solar data concurrently, then render their charts (only if power is enabled)
    if (isSensorEnabled('power')) {
        Promise.all([
            fetchChartData('power', missionId),
            fetchChartData('solar', missionId)
        ]).then(([powerData, solarData]) => {
            renderPowerChart(powerData); // Renders power chart (now without total solar)
            renderSolarPanelChart(solarData, powerData); // Pass both solar (individual) and power (for total solar) data
        }).catch(error => {
            showToast(`Error loading power/solar data: ${error.message}`, 'danger');
            renderPowerChart(null);
            renderSolarPanelChart(null, null);
        });
    }
    
    // If Navigation is the default active view, fetch telemetry data (only if enabled)
    if (isSensorEnabled('navigation')) {
        fetchChartData('telemetry', missionId).then(data => {
            renderTelemetryChart(data);
            renderNavigationCurrentChart(data);
            renderNavigationHeadingDiffChart(data);
        });
    }
    
    /**
     * Renders the CTD Profile Chart using Chart.js.
     * Plots Water Temperature (left Y1), Conductivity (right Y), Dissolved Oxygen (left Y2).
     * @param {Array<Object>|null} chartData - The data array fetched from the API.
     */
    function renderCtdProfileChart(chartData) {
        const canvas = document.getElementById('ctdProfileChart');
        if (!canvas) {
            return; // Canvas not found - silent fail (DOM issue)
        }
        const ctx = canvas.getContext('2d');
        const spinner = ctx.canvas.parentElement.querySelector('.chart-spinner');
        hideChartSpinner(spinner);

        if (!chartData || chartData.length === 0) {
            // console.log('No data or empty data array for CTD Profile Chart.');
            ctx.font = "16px Arial"; ctx.fillStyle = "grey"; ctx.textAlign = "center";
            ctx.fillText("No CTD profile data available.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            if (ctdProfileChartInstance) { ctdProfileChartInstance.destroy(); ctdProfileChartInstance = null; }
            return;
        }

        const datasets = []; // Define datasets here
        // Water Temperature (Left Y-axis 1, more transparent)
        if (chartData.some(d => d.WaterTemperature !== null && d.WaterTemperature !== undefined)) {
            datasets.push({
                label: 'Water Temp (°C)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.WaterTemperature })),
                borderColor: CHART_COLORS.CTD_TEMP.replace('1)', '0.2)'), // Make Water Temp more transparent
                yAxisID: 'yTemp',
                tension: 0.1, fill: false
            });
        }
        
        // Conductivity (Right Y-axis, now more transparent)
        if (chartData.some(d => d.Conductivity !== null && d.Conductivity !== undefined)) {
            datasets.push({
                label: 'Conductivity (S/m)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.Conductivity })),
                borderColor: CHART_COLORS.CTD_CONDUCTIVITY.replace('1)', '0.2)'), // Make Conductivity more transparent
                yAxisID: 'yCond',
                tension: 0.1, fill: false
            });
        }
        // Dissolved Oxygen (Left Y-axis 2, hidden, now less transparent relative to others)
        if (chartData.some(d => d.DissolvedOxygen !== null && d.DissolvedOxygen !== undefined)) {
            datasets.push({
                label: 'DO (Hz)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.DissolvedOxygen })),
                borderColor: CHART_COLORS.CTD_DO, // Use original alpha (1.0), making it the most opaque
                yAxisID: 'yDO',
                tension: 0.1, fill: false
            });
        }

        if (datasets.length === 0) {
            // console.warn('CTD Profile Chart: No valid datasets could be formed.');
            ctx.font = "16px Arial"; ctx.fillStyle = "grey"; ctx.textAlign = "center";
            ctx.fillText("No plottable CTD profile data found.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            if (ctdProfileChartInstance) { ctdProfileChartInstance.destroy(); ctdProfileChartInstance = null; }
            return;
        }

        if (ctdProfileChartInstance) { ctdProfileChartInstance.destroy(); }

        ctdProfileChartInstance = new Chart(ctx, {
            type: 'line',
            data: { datasets: datasets },
            options: {
                responsive: true, maintainAspectRatio: false,
                scales: {
                    x: { type: 'time', time: { unit: 'hour', tooltipFormat: 'MMM d, yyyy HH:mm', displayFormats: { hour: 'MMM d HH:mm', day: 'MMM d' } }, title: { display: true, text: 'Time', color: chartTextColor }, ticks: { color: chartTextColor, maxRotation: 0, autoSkip: true, autoSkipPadding: 20 }, grid: { color: chartGridColor } },
                    yTemp: { type: 'linear', position: 'left', title: { display: true, text: 'Temperature (°C)', color: chartTextColor }, ticks: { color: chartTextColor }, grid: { color: chartGridColor } },
                    yCond: { type: 'linear', position: 'right', title: { display: true, text: 'Conductivity (S/m)', color: chartTextColor }, ticks: { color: chartTextColor }, grid: { drawOnChartArea: false } },
                    yDO: { type: 'linear', position: 'left', display: false, grid: { drawOnChartArea: false } } // Hidden Y-axis for DO
                },
                plugins: { tooltip: { mode: 'index', intersect: false }, legend: { position: 'top', labels: { color: chartTextColor } } }
            }
        });
    }

    function renderWeatherSensorChart(chartData) { // This function was missing in the previous diff
        // console.log('Attempting to render Weather Chart. Data received:', chartData);
        const ctx = document.getElementById('weatherSensorChart').getContext('2d');
        const spinner = ctx.canvas.parentElement.querySelector('.chart-spinner');
        hideChartSpinner(spinner);

        if (!chartData || chartData.length === 0) {
            // console.log('No data or empty data array for Weather Chart.');
            ctx.font = "16px Arial";
            ctx.fillStyle = "grey";
            ctx.textAlign = "center";
            ctx.fillText("No weather sensor trend data available to display.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            if (weatherSensorChartInstance) { weatherSensorChartInstance.destroy(); weatherSensorChartInstance = null; }
            return;
        }

        const datasets = [];
        if (chartData.some(d => d.AirTemperature !== null && d.AirTemperature !== undefined)) {
            datasets.push({
                label: 'Air Temp (°C)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.AirTemperature })),
                borderColor: CHART_COLORS.WEATHER_AIR_TEMP,
                yAxisID: 'yTemp',
                tension: 0.1, fill: false
            });
        }
        if (chartData.some(d => d.WindSpeed !== null && d.WindSpeed !== undefined)) {
            datasets.push({
                label: 'Wind Speed (kt)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.WindSpeed })),
                borderColor: CHART_COLORS.WEATHER_WIND_SPEED,
                yAxisID: 'yWind',
                tension: 0.1, fill: false
            });
        }
        if (chartData.some(d => d.WindGust !== null && d.WindGust !== undefined)) {
            datasets.push({
                label: 'Wind Gust (kt)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.WindGust })),
                borderColor: CHART_COLORS.WEATHER_WIND_SPEED.replace('1)', '0.7)'), // Lighter version of wind speed
                borderDash: [5, 5], // Dashed line for gusts
                yAxisID: 'yWind', // Share axis with WindSpeed
                tension: 0.1, fill: false
            });
        }

        if (datasets.length === 0) {
            // console.warn('Weather Chart: No valid datasets could be formed from the provided chartData.');
            ctx.font = "16px Arial";
            ctx.fillStyle = "grey";
            ctx.textAlign = "center";
            ctx.fillText("No plottable weather data found.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            if (weatherSensorChartInstance) { weatherSensorChartInstance.destroy(); weatherSensorChartInstance = null; }
            return;
        }

        if (weatherSensorChartInstance) {
            weatherSensorChartInstance.destroy();
        }

        weatherSensorChartInstance = new Chart(ctx, {
            type: 'line',
            data: { datasets: datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: {
                        type: 'time',
                        time: { unit: 'hour', tooltipFormat: 'MMM d, yyyy HH:mm', displayFormats: { hour: 'MMM d HH:mm', day: 'MMM d' } },
                        title: { display: true, text: 'Time', color: chartTextColor },
                        ticks: {
                            color: chartTextColor,
                            maxRotation: 0,
                            autoSkip: true,
                            autoSkipPadding: 20
                        },
                        grid: { color: chartGridColor }
                    },
                    yTemp: { type: 'linear', position: 'left', title: { display: true, text: 'Temperature (°C)', color: chartTextColor }, ticks: { color: chartTextColor }, grid: { color: chartGridColor } },
                    yWind: { type: 'linear', position: 'right', title: { display: true, text: 'Wind (kt)', color: chartTextColor }, ticks: { color: chartTextColor, beginAtZero: true }, grid: { drawOnChartArea: false, color: chartGridColor } }
                },
                plugins: { tooltip: { mode: 'index', intersect: false }, legend: { position: 'top', labels: { color: chartTextColor } } }
            }
        });
    }

    /**
     * Fetches weather forecast data from the API.
     * @param {string} mission - The mission ID.
     */
    // --- Weather Forecast ---
    async function fetchForecastData(mission) {
        try {
            const initialForecastArea = document.getElementById('forecastInitial');
            // Spinner management removed for forecast
            if (initialForecastArea) initialForecastArea.style.display = 'none'; // Ensure content area is hidden

            // Check if this is a historical mission
            const isHistorical = document.body.dataset.isHistorical === 'true';

            let forecastApiUrl = `/api/forecast/${mission}`;
            const forecastParams = new URLSearchParams();
            forecastParams.append('source', currentSource);
            if (currentSource === 'local' && currentLocalPath) {
                forecastParams.append('local_path', currentLocalPath);
            }
            // Pass refresh parameter to forecast API if present in main page URL
            if (urlParams.has('refresh') && urlParams.get('refresh') === 'true') {
                forecastParams.append('refresh', 'true');
            }
            // Pass is_historical parameter
            if (isHistorical) {
                forecastParams.append('is_historical', 'true');
            }
            
            // Add date range parameters if date range is enabled for weather
            const startInput = document.getElementById('start-date-weather');
            const endInput = document.getElementById('end-date-weather');
            if (startInput && endInput && startInput.value && endInput.value) {
                const startDate = new Date(startInput.value);
                const endDate = new Date(endInput.value);
                forecastParams.append('start_date', startDate.toISOString());
                forecastParams.append('end_date', endDate.toISOString());
            }
            const forecastData = await apiRequest(`${forecastApiUrl}?${forecastParams.toString()}`, 'GET');
            return forecastData;
        } catch (error) {
            showToast(`Error loading forecast: ${error.message}`, 'danger');
            displayGlobalError('Failed to load weather forecast.');
            return null;
        }
    }

    // WMO Weather code descriptions (simplified)
    // Source: https://open-meteo.com/en/docs (Weather WMO Code Table)
    const WMO_WEATHER_CODES = {
        0: 'Clear sky',
        1: 'Mainly clear',
        2: 'Partly cloudy',
        3: 'Overcast',
        45: 'Fog',
        48: 'Depositing rime fog',
        51: 'Light drizzle',
        53: 'Moderate drizzle',
        55: 'Dense drizzle',
        56: 'Light freezing drizzle',
        57: 'Dense freezing drizzle',
        61: 'Slight rain',
        63: 'Moderate rain',
        65: 'Heavy rain',
        66: 'Light freezing rain',
        67: 'Heavy freezing rain',
        71: 'Slight snow fall',
        73: 'Moderate snow fall',
        75: 'Heavy snow fall',
        77: 'Snow grains',
        80: 'Slight rain showers',
        81: 'Moderate rain showers',
        82: 'Violent rain showers',
        85: 'Slight snow showers',
        86: 'Heavy snow showers',
        95: 'Thunderstorm', // Slight or moderate
        96: 'Thunderstorm with slight hail',
        99: 'Thunderstorm with heavy hail',
    };

    function getWeatherDescription(code) {
        return WMO_WEATHER_CODES[code] || 'Unknown';
    }

    /**
     * Renders the weather forecast table.
     * @param {Object|null} forecastData - The forecast data object fetched from the API.
     */

    function renderForecast(forecastData) {
        const initialContainer = document.getElementById('forecastInitial');
        const extendedContainer = document.getElementById('forecastExtendedContent');
        const toggleButton = document.getElementById('toggleForecastBtn');
        // Spinner management removed for forecast

        if (!forecastData || !forecastData.hourly || !forecastData.hourly.time || forecastData.hourly.time.length === 0) {
            initialContainer.innerHTML = '<p class="text-muted">Forecast data is currently unavailable.</p>';
            if (extendedContainer) extendedContainer.innerHTML = '';
            if (toggleButton) toggleButton.style.display = 'none';
        } else {
            // Add a title indicating the forecast type
            let forecastTitle = 'Weather Forecast';
 // The 'forecast_type' is added by our backend wrapper in forecast.py
            if (forecastData.forecast_type === 'marine') {
                forecastTitle += ' (Marine & General)';
            } else if (forecastData.forecast_type === 'general') {
                forecastTitle += ' (General Weather)'; // Simplified title
            }
            initialContainer.innerHTML = `<h5 class="text-muted fst-italic">${forecastTitle}</h5>`; // Prepend title

            const hourly = forecastData.hourly;
            const units = forecastData.hourly_units || {}; // Get units from the forecast data
            const totalHoursAvailable = hourly.time.length;

            const createTableHtml = (startHour, endHour) => {
                let tableHtml = '<table class="table table-sm table-striped table-hover">';
                tableHtml += '<thead><tr>' +
                             '<th>Time</th>' +
                             '<th>Weather</th>' +
                             `<th>Air Temp (${units.temperature_2m || '°C'})</th>` + // Default unit if not provided
                             `<th>Precip (${units.precipitation || 'mm'})</th>` +   // Default unit
                             `<th>Wind (${units.windspeed_10m || 'm/s'} @ ${units.winddirection_10m || '°'})</th>`; // Default units
                tableHtml += '</tr></thead>';
                tableHtml += '<tbody>';

                for (let i = startHour; i < endHour && i < totalHoursAvailable; i++) {
                    const time = new Date(hourly.time[i]).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
                    
                    const weatherCode = (hourly.weathercode && hourly.weathercode[i] !== null) ? hourly.weathercode[i] : 'N/A';
                    const weatherDisplay = getWeatherDescription(weatherCode);

                    const airTemp = (hourly.temperature_2m && hourly.temperature_2m[i] !== null) ? hourly.temperature_2m[i].toFixed(1) : 'N/A';
                    const precip = (hourly.precipitation && hourly.precipitation[i] !== null) ? hourly.precipitation[i].toFixed(1) : 'N/A';
                    
                    // Wind data (speed and direction)
                    const windSpeed = (hourly.windspeed_10m && hourly.windspeed_10m[i] !== null) ? hourly.windspeed_10m[i].toFixed(1) : 'N/A';
                    const windDir = (hourly.winddirection_10m && hourly.winddirection_10m[i] !== null) ? hourly.winddirection_10m[i].toFixed(0) : 'N/A';
                    const windDisplay = windSpeed !== 'N/A' ? `${windSpeed} @ ${windDir}°` : 'N/A';

                    tableHtml += `<tr>` +
                                 `<td>${time}</td>` +
                                 `<td>${weatherDisplay}</td>` +
                                 `<td>${airTemp}</td>` +
                                 `<td>${precip}</td>` +
                                 `<td>${windDisplay}</td>` +
                                 `</tr>`;
                }
                tableHtml += '</tbody></table>';
                return tableHtml;
            };

            const initialHours = 12;
            // Append the table to the initial container, after the title
            initialContainer.innerHTML += createTableHtml(0, initialHours);

            const extendedStartHour = initialHours;
            const maxExtendedHours = 48; // Show up to 48 hours total when expanded

            if (totalHoursAvailable > initialHours) {
                extendedContainer.innerHTML = createTableHtml(extendedStartHour, Math.min(totalHoursAvailable, maxExtendedHours));
                toggleButton.style.display = 'block'; // Show the button
                
                const collapseElement = document.getElementById('forecastExtended');
                // Listener to update button text
                collapseElement.addEventListener('show.bs.collapse', function () {
                    toggleButton.textContent = 'Show Less';
                });
                collapseElement.addEventListener('hide.bs.collapse', function () {
                    toggleButton.textContent = 'Show More';
                });
                // Set initial text
                if (!collapseElement.classList.contains('show')) {
                     toggleButton.textContent = 'Show More';
                } else {
                     toggleButton.textContent = 'Show Less';
                }
            } else {
                if (extendedContainer) extendedContainer.innerHTML = '';
                if (toggleButton) toggleButton.style.display = 'none';
         }          }
         // Ensure spinner is hidden and content area is visible
         // Spinner management removed for forecast

        initialContainer.style.display = 'block';

        // Populate forecast metadata
        const metaInfoContainer = document.getElementById('forecastMetaInfo');
        if (metaInfoContainer) {
            if (forecastData && forecastData.fetched_at_utc && forecastData.latitude_used !== undefined && forecastData.longitude_used !== undefined) {
                const fetchedDate = new Date(forecastData.fetched_at_utc);
                const formattedTime = fetchedDate.toLocaleString('en-GB', { // en-GB for 24-hour format
                    timeZone: 'UTC',
                    year: 'numeric',
                    month: 'short',
                    day: 'numeric',
                    hour: '2-digit', // Corrected: Use forecastData
                    minute: '2-digit', // Corrected: Use forecastData
                    hour12: false // Corrected: Use forecastData
                }); // Corrected: Use forecastData
                const lat = parseFloat(forecastData.latitude_used).toFixed(3); // Corrected: Use forecastData
                const lon = parseFloat(forecastData.longitude_used).toFixed(3); // Corrected: Use forecastData
            metaInfoContainer.textContent = `Forecast fetched: ${fetchedDate.toLocaleString('en-GB', { timeZone: 'UTC', year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false })} UTC for Lat: ${lat}, Lon: ${lon}`;
             metaInfoContainer.style.display = 'block';
            } else {
                metaInfoContainer.textContent = ''; // Clear if no data
                metaInfoContainer.style.display = 'none'; // Hide if no data
            }
        }
    }

    async function fetchMarineForecastData(mission) {
        try {
            const initialMarineForecastArea = document.getElementById('marineForecastInitial');
            if (initialMarineForecastArea) initialMarineForecastArea.style.display = 'none';

            // Check if this is a historical mission
            const isHistorical = document.body.dataset.isHistorical === 'true';

            let marineForecastApiUrl = `/api/marine_forecast/${mission}`;
            const forecastParams = new URLSearchParams();
            // Marine forecast might need lat/lon explicitly if not inferred by backend for this specific endpoint
            // For now, assuming backend handles it or we pass lat/lon if available from telemetry summary
            // Example: if (currentGliderLat && currentGliderLon) {
            //    forecastParams.append('lat', currentGliderLat);
            //    forecastParams.append('lon', currentGliderLon);
            // }
            forecastParams.append('source', currentSource); // Keep consistent with other data calls
            if (currentSource === 'local' && currentLocalPath) {
                forecastParams.append('local_path', currentLocalPath);
            }
            if (urlParams.has('refresh') && urlParams.get('refresh') === 'true') {
                forecastParams.append('refresh', 'true');
            }
            // Pass is_historical parameter
            if (isHistorical) {
                forecastParams.append('is_historical', 'true');
            }
            
            // Add date range parameters if date range is enabled for waves
            const startInput = document.getElementById('start-date-waves');
            const endInput = document.getElementById('end-date-waves');
            if (startInput && endInput && startInput.value && endInput.value) {
                const startDate = new Date(startInput.value);
                const endDate = new Date(endInput.value);
                forecastParams.append('start_date', startDate.toISOString());
                forecastParams.append('end_date', endDate.toISOString());
            }
            const marineForecastData = await apiRequest(`${marineForecastApiUrl}?${forecastParams.toString()}`, 'GET');
            return marineForecastData;
        } catch (error) {
            showToast(`Error loading marine forecast: ${error.message}`, 'danger');
            displayGlobalError('Failed to load marine forecast.');
            return null;
        }
    }


    // Fetch and render forecast
    fetchForecastData(missionId).then(data => {
        renderForecast(data);
    });
    /**
     * Renders the Wave Chart using Chart.js.
     * @param {Array<Object>|null} chartData - The data array fetched from the API.
     */
    function renderWaveChart(chartData) { 
        // console.log('Attempting to render Wave Chart. Data received:', chartData);
        const ctx = document.getElementById('waveChart').getContext('2d');
        const spinner = ctx.canvas.parentElement.querySelector('.chart-spinner');
        hideChartSpinner(spinner);

                if (!chartData || chartData.length === 0) {
            // console.log('No data or empty data array for Wave Chart.');
            ctx.font = "16px Arial";
            ctx.fillStyle = "grey";
            ctx.textAlign = "center";
            ctx.fillText("No wave trend data available to display.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            if (waveChartInstance) { waveChartInstance.destroy(); waveChartInstance = null; }
            return;
        }

        const datasets = [];
        if (chartData.some(d => d.SignificantWaveHeight !== null && d.SignificantWaveHeight !== undefined)) {
            datasets.push({
                label: 'Sig. Wave Height (m)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.SignificantWaveHeight })),
                borderColor: CHART_COLORS.WAVES_SIG_HEIGHT,
                yAxisID: 'yHeight',
                tension: 0.1, fill: false
            });
        }
        if (chartData.some(d => d.WavePeriod !== null && d.WavePeriod !== undefined)) {
            datasets.push({
                label: 'Wave Period (s)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.WavePeriod })),
                borderColor: CHART_COLORS.WAVES_PERIOD,
                yAxisID: 'yPeriod',
                tension: 0.1, fill: false
            });
        }

        if (datasets.length === 0) {
            // console.warn('Wave Chart: No valid datasets could be formed from the provided chartData.');
            ctx.font = "16px Arial";
            ctx.fillStyle = "grey";
            ctx.textAlign = "center";
            ctx.fillText("No plottable wave data found.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            if (waveChartInstance) { waveChartInstance.destroy(); waveChartInstance = null; }
            return;
        }

        if (waveChartInstance) {
            waveChartInstance.destroy();
        }

        waveChartInstance = new Chart(ctx, {
            type: 'line',
            data: { datasets: datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: {
                        type: 'time',
                        time: { unit: 'hour', tooltipFormat: 'MMM d, yyyy HH:mm', displayFormats: { hour: 'MMM d HH:mm', day: 'MMM d' } },
                        title: { display: true, text: 'Time', color: chartTextColor },
                        ticks: {
                            color: chartTextColor,
                            maxRotation: 0,
                            autoSkip: true,
                            autoSkipPadding: 20
                        },
                        grid: { color: chartGridColor }
                    },
                    yHeight: { type: 'linear', position: 'left', title: { display: true, text: 'Wave Height (m)', color: chartTextColor }, ticks: { color: chartTextColor }, grid: { color: chartGridColor } },
                    yPeriod: { type: 'linear', position: 'right', title: { display: true, text: 'Wave Period (s)', color: chartTextColor }, ticks: { color: chartTextColor }, grid: { drawOnChartArea: false, color: chartGridColor } }
                },
                plugins: { tooltip: { mode: 'index', intersect: false }, legend: { position: 'top', labels: { color: chartTextColor } } }
            }
        });
    }

    function renderMarineForecast(marineForecastData) {
        const initialContainer = document.getElementById('marineForecastInitial');
        const extendedContainer = document.getElementById('marineForecastExtendedContent');
        const toggleButton = document.getElementById('toggleMarineForecastBtn');
        const metaInfoContainer = document.getElementById('marineForecastMetaInfo');

        if (!initialContainer || !extendedContainer || !toggleButton || !metaInfoContainer) {
            return; // Missing DOM elements - silent fail (DOM issue)
        }

        if (!marineForecastData || !marineForecastData.hourly || !marineForecastData.hourly.time || marineForecastData.hourly.time.length === 0) {
            initialContainer.innerHTML = '<p class="text-muted">Marine forecast data is currently unavailable.</p>';
            initialContainer.style.display = 'block';
            extendedContainer.innerHTML = '';
            toggleButton.style.display = 'none';
            metaInfoContainer.style.display = 'none';
            return;
        }

        let forecastTitle = 'Marine Forecast'; // Already specific
        initialContainer.innerHTML = `<h5 class="text-muted fst-italic">${forecastTitle}</h5>`;

        const hourly = marineForecastData.hourly;
        const units = marineForecastData.hourly_units || {};
        const totalHoursAvailable = hourly.time.length;

        const createMarineTableHtml = (startHour, endHour) => {
            let tableHtml = '<table class="table table-sm table-striped table-hover">';
            tableHtml += '<thead><tr>' +
                         '<th>Time</th>' +
                         `<th>Wave Ht (${units.wave_height || 'm'})</th>` +
                         `<th>Wave Prd (${units.wave_period || 's'})</th>` +
                         `<th>Wave Dir (${units.wave_direction || '°'})</th>` +
                         `<th>Current (${units.ocean_current_velocity || 'm/s'} @ ${units.ocean_current_direction || '°'})</th>`;
            tableHtml += '</tr></thead>';
            tableHtml += '<tbody>';

            for (let i = startHour; i < endHour && i < totalHoursAvailable; i++) {
                const time = new Date(hourly.time[i]).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
                const waveHeight = (hourly.wave_height && hourly.wave_height[i] !== null) ? hourly.wave_height[i].toFixed(1) : 'N/A';
                const wavePeriod = (hourly.wave_period && hourly.wave_period[i] !== null) ? hourly.wave_period[i].toFixed(1) : 'N/A';
                const waveDir = (hourly.wave_direction && hourly.wave_direction[i] !== null) ? hourly.wave_direction[i].toFixed(0) : 'N/A';
                const currentSpeed = (hourly.ocean_current_velocity && hourly.ocean_current_velocity[i] !== null) ? hourly.ocean_current_velocity[i].toFixed(2) : 'N/A';
                const currentDir = (hourly.ocean_current_direction && hourly.ocean_current_direction[i] !== null) ? hourly.ocean_current_direction[i].toFixed(0) : 'N/A';
                const currentDisplay = currentSpeed !== 'N/A' ? `${currentSpeed} @ ${currentDir}°` : 'N/A';

                tableHtml += `<tr><td>${time}</td><td>${waveHeight}</td><td>${wavePeriod}</td><td>${waveDir}</td><td>${currentDisplay}</td></tr>`;
            }
            tableHtml += '</tbody></table>';
            return tableHtml;
        };

        const initialHours = 12;
        initialContainer.innerHTML += createMarineTableHtml(0, initialHours);
        initialContainer.style.display = 'block';

        const extendedStartHour = initialHours;
        const maxExtendedHours = 48;

        if (totalHoursAvailable > initialHours) {
            extendedContainer.innerHTML = createMarineTableHtml(extendedStartHour, Math.min(totalHoursAvailable, maxExtendedHours));
            toggleButton.style.display = 'block';
            const collapseElement = document.getElementById('marineForecastExtended');
            collapseElement.addEventListener('show.bs.collapse', () => { toggleButton.textContent = 'Show Less'; });
            collapseElement.addEventListener('hide.bs.collapse', () => { toggleButton.textContent = 'Show More'; });
            toggleButton.textContent = collapseElement.classList.contains('show') ? 'Show Less' : 'Show More';
        } else {
            extendedContainer.innerHTML = '';
            toggleButton.style.display = 'none';
        }

        if (marineForecastData.fetched_at_utc && marineForecastData.latitude_used !== undefined) {
            const fetchedDate = new Date(marineForecastData.fetched_at_utc);
            metaInfoContainer.textContent = `Forecast fetched: ${fetchedDate.toLocaleTimeString('en-GB', { timeZone: 'UTC', year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false })} UTC for Lat: ${parseFloat(marineForecastData.latitude_used).toFixed(3)}, Lon: ${parseFloat(marineForecastData.longitude_used).toFixed(3)}`;
            metaInfoContainer.style.display = 'block';
        } else {
            metaInfoContainer.style.display = 'none';
        }
    }

    // Fetch and render the Wave chart on page load (only if enabled)
    if (isSensorEnabled('waves')) {
        fetchChartData('waves', missionId).then(data => {
            renderWaveChart(data); // Renders Hs vs Tp chart (time-series)
            renderWaveHeightDirectionChart(data); // Call the reinstated function
        }); // Wave spectrum is loaded on demand when its detail card is clicked
    }
    
    /**
     * Renders the VR2C Chart using Chart.js.
     * @param {Array<Object>|null} chartData - The data array fetched from the API.
     */
    function renderVr2cChart(chartData) {
        // console.log('Attempting to render VR2C Chart. Data received:', chartData);
        const ctx = document.getElementById('vr2cChart').getContext('2d');
        const spinner = ctx.canvas.parentElement.querySelector('.chart-spinner');
        hideChartSpinner(spinner);

        if (!chartData || chartData.length === 0) {
            // console.log('No data or empty data array for VR2C Chart.');
            ctx.font = "16px Arial";
            ctx.fillStyle = "grey";
            ctx.textAlign = "center";
            ctx.fillText("No VR2C trend data available to display.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            if (vr2cChartInstance) { vr2cChartInstance.destroy(); vr2cChartInstance = null; }
            return;
        }

        const datasets = [];
        if (chartData.some(d => d.DetectionCount !== null && d.DetectionCount !== undefined)) {
            datasets.push({
                label: 'Detection Count (DC)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.DetectionCount })),
                borderColor: CHART_COLORS.VR2C_DETECTION,
                yAxisID: 'yCounts',
                tension: 0.1, fill: false
            });
        }
        if (chartData.some(d => d.PingCountDelta !== null && d.PingCountDelta !== undefined)) {
            datasets.push({
                label: 'Ping Count Delta (ΔPC/hr)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.PingCountDelta })),
                borderColor: CHART_COLORS.POWER_DRAW, // Re-use a contrasting color like red
                yAxisID: 'yDelta', // Assign to new right-hand Y-axis
                tension: 0.1, fill: false, // No fill for delta
                borderDash: [5, 5] // Optional: make it dashed
            });
        }

        if (datasets.length === 0) {
            // console.warn('VR2C Chart: No valid datasets could be formed from the provided chartData.');
            ctx.font = "16px Arial";
            ctx.fillStyle = "grey";
            ctx.textAlign = "center";
            ctx.fillText("No plottable VR2C data found.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            if (vr2cChartInstance) { vr2cChartInstance.destroy(); vr2cChartInstance = null; }
            return;
        }

        if (vr2cChartInstance) {
            vr2cChartInstance.destroy();
        }

        vr2cChartInstance = new Chart(ctx, {
            type: 'line',
            data: { datasets: datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: { type: 'time', time: { unit: 'hour', tooltipFormat: 'MMM d, yyyy HH:mm', displayFormats: { hour: 'MMM d HH:mm', day: 'MMM d' } }, title: { display: true, text: 'Time', color: chartTextColor }, ticks: { color: chartTextColor, maxRotation: 0, autoSkip: true, autoSkipPadding: 20 }, grid: { color: chartGridColor } },
                    yCounts: { type: 'linear', position: 'left', title: { display: true, text: 'Detection Count (DC)', color: chartTextColor }, ticks: { color: chartTextColor, beginAtZero: true }, grid: { color: chartGridColor } },
                    yDelta: { type: 'linear', position: 'right', title: { display: true, text: 'Ping Count Delta (ΔPC/hr)', color: chartTextColor }, ticks: { color: chartTextColor /* beginAtZero: false might be better for deltas */ }, grid: { drawOnChartArea: false } }
                },
                plugins: { tooltip: { mode: 'index', intersect: false }, legend: { position: 'top', labels: { color: chartTextColor } } }
            }
        });
    }
        /**
     * Renders the Wave Height vs. Direction Chart using Chart.js.
     * @param {Array<Object>|null} chartData - The data array fetched from the API.
     */
    function renderWaveHeightDirectionChart(chartData) {
        const canvas = document.getElementById('waveHeightDirectionChart');
        if (!canvas) { return; } // Canvas not found - silent fail (DOM issue)
        const ctx = canvas.getContext('2d');
        const spinner = ctx.canvas.parentElement.querySelector('.chart-spinner');
        hideChartSpinner(spinner);

        if (!chartData || chartData.length === 0) {
            ctx.font = "16px Arial"; ctx.fillStyle = "grey"; ctx.textAlign = "center";
            ctx.fillText("No wave Ht/Dir data available.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            if (waveHeightDirectionChartInstance) { waveHeightDirectionChartInstance.destroy(); waveHeightDirectionChartInstance = null; }
            return;
        }

        const datasets = [];
        if (chartData.some(d => d.SignificantWaveHeight !== null && d.SignificantWaveHeight !== undefined)) {
            datasets.push({
                label: 'Sig. Wave Height (m)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.SignificantWaveHeight })),
                borderColor: CHART_COLORS.WAVES_SIG_HEIGHT,
                yAxisID: 'yHeight',
                tension: 0.1, fill: false
            });
        }
        if (chartData.some(d => d.MeanWaveDirection !== null && d.MeanWaveDirection !== undefined)) {
            datasets.push({
                label: 'Mean Wave Dir (°)',
                data: chartData.map(item => {
                    let waveDirNum = parseFloat(item.MeanWaveDirection);
                    // Filter out specific outlier values for wave direction
                    if (waveDirNum === 9999 || waveDirNum === -9999) {
                        waveDirNum = null; // Chart.js will skip null points
                    }
                    return { x: new Date(item.Timestamp), y: waveDirNum };
                }),
                borderColor: CHART_COLORS.CTD_SALINITY.replace('1)', '0.7)'), // Re-use a color
                yAxisID: 'yDirection',
                tension: 0.1, fill: false
            });
        }

        if (datasets.length === 0) {
            ctx.font = "16px Arial"; ctx.fillStyle = "grey"; ctx.textAlign = "center";
            ctx.fillText("No plottable wave Ht/Dir data.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            if (waveHeightDirectionChartInstance) { waveHeightDirectionChartInstance.destroy(); waveHeightDirectionChartInstance = null; }
            return;
        }

        if (waveHeightDirectionChartInstance) { waveHeightDirectionChartInstance.destroy(); }
        waveHeightDirectionChartInstance = new Chart(ctx, {
            type: 'line',
            data: { datasets: datasets },
            options: {
                responsive: true, maintainAspectRatio: false,
                scales: {
                    x: { type: 'time', time: { unit: 'hour', tooltipFormat: 'MMM d, yyyy HH:mm', displayFormats: { hour: 'MMM d HH:mm', day: 'MMM d' } }, title: { display: true, text: 'Time', color: chartTextColor }, ticks: { color: chartTextColor, maxRotation: 0, autoSkip: true }, grid: { color: chartGridColor } },
                    yHeight: { type: 'linear', position: 'left', title: { display: true, text: 'Wave Height (m)', color: chartTextColor }, ticks: { color: chartTextColor, beginAtZero: true }, grid: { color: chartGridColor } },
                    yDirection: { type: 'linear', position: 'right', title: { display: true, text: 'Wave Direction (°)', color: chartTextColor }, ticks: { color: chartTextColor, min: 0, max: 360 }, grid: { drawOnChartArea: false } }
                },
                plugins: { tooltip: { mode: 'index', intersect: false }, legend: { position: 'top', labels: { color: chartTextColor } } }
            }
        });
    }

    // Fetch and render the VR2C chart on page load (only if enabled)
    if (isSensorEnabled('vr2c')) {
        fetchChartData('vr2c', missionId).then(data => {
            renderVr2cChart(data);
        });
    }

    // Fetch and render the Fluorometer chart on page load (only if enabled)
    if (isSensorEnabled('fluorometer')) {
        fetchChartData('fluorometer', missionId).then(data => {
            renderFluorometerChart(data);
        });
    }

    // Fetch and render the WG-VM4 chart on page load (only if enabled)
    if (isSensorEnabled('wg_vm4')) {
        fetchChartData('wg_vm4', missionId).then(data => {
            renderWgVm4Chart(data);
        });
    }

    /**
     * Fetches and renders the latest wave spectrum data.
     * @param {string} mission - The mission ID.
     */
    async function fetchAndRenderWaveSpectrum(mission) {
        const canvas = document.getElementById('waveSpectrumChart');
        if (!canvas) { return; } // Canvas not found - silent fail (DOM issue)
        const ctx = canvas.getContext('2d');
        const spinner = ctx.canvas.parentElement.querySelector('.chart-spinner');
        showChartSpinner(spinner);

        try {
            let apiUrl = `/api/wave_spectrum/${mission}`;
            const spectrumParams = new URLSearchParams();
            spectrumParams.append('source', currentSource);
            if (currentSource === 'local' && currentLocalPath) {
                spectrumParams.append('local_path', currentLocalPath);
            }
            if (urlParams.has('refresh') && urlParams.get('refresh') === 'true') {
                spectrumParams.append('refresh', 'true');
            }
            
            // Add date range parameters if date range is enabled for waves
            const startInput = document.getElementById('start-date-waves');
            const endInput = document.getElementById('end-date-waves');
            if (startInput && endInput && startInput.value && endInput.value) {
                const startDate = new Date(startInput.value);
                const endDate = new Date(endInput.value);
                spectrumParams.append('start_date', startDate.toISOString());
                spectrumParams.append('end_date', endDate.toISOString());
            }
            // Note: We are NOT passing a specific timestamp here, relying on the backend to get the latest
            // unless a specific timestamp selection UI is added later.
            const spectrumData = await apiRequest(`${apiUrl}?${spectrumParams.toString()}`, 'GET');
            renderWaveSpectrumChart(spectrumData);
        } catch (error) {
            showToast(`Error loading wave spectrum: ${error.message}`, 'danger');
            displayGlobalError('Network error while fetching wave spectrum data.');
            renderWaveSpectrumChart(null); // Render empty chart
        } finally {
            hideChartSpinner(spinner);
        }
    }

    /**
     * Renders the Wave Energy Spectrum Chart using Chart.js.
     * @param {Array<Object>|null} spectrumData - The data array [{x: freq, y: efth}] fetched from the API.
     */
    function renderWaveSpectrumChart(spectrumData) {
        const canvas = document.getElementById('waveSpectrumChart');
        if (!canvas) return; 
        const ctx = canvas.getContext('2d');

        if (waveSpectrumChartInstance) { waveSpectrumChartInstance.destroy(); }

        if (!spectrumData || spectrumData.length === 0) {
            ctx.font = "16px Arial"; ctx.fillStyle = "grey"; ctx.textAlign = "center";
            ctx.fillText("No wave spectrum data available.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            return;
        }

        waveSpectrumChartInstance = new Chart(ctx, {
            type: 'line', 
            data: { datasets: [{ label: 'Energy Density (m²/Hz)', data: spectrumData, borderColor: CHART_COLORS.WAVE_SPECTRUM, borderWidth: 2, pointRadius: 0, tension: 0.1, fill: false }] },
            options: {
                responsive: true, maintainAspectRatio: false,
                scales: {
                    x: { type: 'linear', position: 'bottom', title: { display: true, text: 'Frequency (Hz)', color: chartTextColor }, ticks: { color: chartTextColor }, grid: { color: chartGridColor } },
                    y: { type: 'linear', position: 'left', title: { display: true, text: 'Energy Density (m²/Hz)', color: chartTextColor }, ticks: { color: chartTextColor, beginAtZero: true }, grid: { color: chartGridColor } }
                },
                plugins: { tooltip: { mode: 'index', intersect: false }, legend: { position: 'top', labels: { color: chartTextColor } } }
            }
        });
    }

     /**
     * Renders the Fluorometer Chart using Chart.js.
     * @param {Array<Object>|null} chartData - The data array fetched from the API.
     */
    function renderFluorometerChart(chartData) {
        const canvas = document.getElementById('fluorometerChart');
        if (!canvas) { return; } // Canvas not found - silent fail (DOM issue)
        const ctx = canvas.getContext('2d');
        const spinner = ctx.canvas.parentElement.querySelector('.chart-spinner');
        hideChartSpinner(spinner);

        if (!chartData || chartData.length === 0) {
            ctx.font = "16px Arial"; ctx.fillStyle = "grey"; ctx.textAlign = "center";
            ctx.fillText("No fluorometer data available.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            if (fluorometerChartInstance) { fluorometerChartInstance.destroy(); fluorometerChartInstance = null; }
            return;
        }

        const datasets = [];
        if (chartData.some(d => d.C1_Avg !== null && d.C1_Avg !== undefined)) {
            datasets.push({
                label: 'C1 Avg',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.C1_Avg })),
                borderColor: CHART_COLORS.FLUORO_C_AVG_PRIMARY,
                yAxisID: 'yPrimary',
                tension: 0.1, fill: false
            });
        }
        if (chartData.some(d => d.C2_Avg !== null && d.C2_Avg !== undefined)) {
            datasets.push({
                label: 'C2 Avg',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.C2_Avg })),
                borderColor: CHART_COLORS.WAVES_SIG_HEIGHT, // Re-use a distinct color
                yAxisID: 'yPrimary', // Share the primary Y-axis
                tension: 0.1, fill: false
            });
        }
        if (chartData.some(d => d.C3_Avg !== null && d.C3_Avg !== undefined)) {
            datasets.push({
                label: 'C3 Avg',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.C3_Avg })),
                borderColor: CHART_COLORS.WAVES_PERIOD, // Re-use another distinct color
                yAxisID: 'yPrimary', // Share the primary Y-axis
                tension: 0.1, fill: false
            });
        }
        if (chartData.some(d => d.Temperature_Fluor !== null && d.Temperature_Fluor !== undefined)) {
            datasets.push({
                label: 'Temperature (°C)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.Temperature_Fluor })),
                borderColor: CHART_COLORS.FLUORO_TEMP, // Use a distinct color
                yAxisID: 'yTemp', // Use a secondary axis for temperature
                tension: 0.1, fill: false
            });
        }

        if (datasets.length === 0) {
            ctx.font = "16px Arial"; ctx.fillStyle = "grey"; ctx.textAlign = "center";
            ctx.fillText("No plottable fluorometer data.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            if (fluorometerChartInstance) { fluorometerChartInstance.destroy(); fluorometerChartInstance = null; }
            return;
        }

        if (fluorometerChartInstance) { fluorometerChartInstance.destroy(); }
        fluorometerChartInstance = new Chart(ctx, {
            type: 'line',
            data: { datasets: datasets },
            options: {
                responsive: true, maintainAspectRatio: false,
                scales: {
                    x: { type: 'time', time: { unit: 'hour', tooltipFormat: 'MMM d, yyyy HH:mm', displayFormats: { hour: 'MMM d HH:mm', day: 'MMM d' } }, title: { display: true, text: 'Time', color: chartTextColor }, ticks: { color: chartTextColor, maxRotation: 0, autoSkip: true }, grid: { color: chartGridColor } },
                    yPrimary: { type: 'linear', position: 'left', title: { display: true, text: 'Fluorescence Units', color: chartTextColor }, ticks: { color: chartTextColor }, grid: { color: chartGridColor } },
                    yTemp: { type: 'linear', position: 'right', title: { display: true, text: 'Temperature (°C)', color: chartTextColor }, ticks: { color: chartTextColor }, grid: { drawOnChartArea: false } }
                },
                plugins: { tooltip: { mode: 'index', intersect: false }, legend: { position: 'top', labels: { color: chartTextColor } } }
            }
        });
    }

  
    /**
     * Renders the Solar Panel Chart using Chart.js.
     * @param {Array<Object>|null} chartData - The data array fetched from the API.
     * @param {Array<Object>|null} powerData - The data array for the main power report, used for total solar input.
     */
    function renderSolarPanelChart(chartData, powerData) {
        // console.log('Attempting to render Solar Panel Chart. Data received:', chartData);
        const ctx = document.getElementById('solarPanelChart')?.getContext('2d');
        const spinner = ctx.canvas.parentElement.querySelector('.chart-spinner');
        hideChartSpinner(spinner);

        if (!chartData || chartData.length === 0) {
            // console.log('No data or empty data array for Solar Panel Chart.');
            ctx.font = "16px Arial";
            ctx.fillStyle = "grey";
            ctx.textAlign = "center";
            ctx.fillText("No solar panel trend data available.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            if (solarPanelChartInstance) { solarPanelChartInstance.destroy(); solarPanelChartInstance = null; }
            return;
        }

        const datasets = [];
        // Add Total Solar Input from powerData
        if (powerData && powerData.some(d => d.SolarInputWatts !== null && d.SolarInputWatts !== undefined)) {
            datasets.push({
                label: 'Total Solar Input (W)',
                data: powerData.map(item => ({ x: new Date(item.Timestamp), y: item.SolarInputWatts })),
                borderColor: CHART_COLORS.POWER_SOLAR, // Use the existing color for total solar
                yAxisID: 'yTotalSolar', // Assign to the new right y-axis
                borderDash: [5, 5], // Optional: Differentiate with a dashed line
                tension: 0.1, fill: false
            });
        }
        if (chartData.some(d => d.Panel1Power !== null && d.Panel1Power !== undefined)) {
            datasets.push({
                label: 'Panel 1 Power (W)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.Panel1Power })),
                borderColor: CHART_COLORS.SOLAR_PANEL_1,
                yAxisID: 'yIndividualPanels', // Assign to the left y-axis
                tension: 0.1, fill: false
            });
        }
        if (chartData.some(d => d.Panel2Power !== null && d.Panel2Power !== undefined)) {
            datasets.push({
                label: 'Panel 2 Power (W)', // Corresponds to panelPower3 from CSV
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.Panel2Power })),
                borderColor: CHART_COLORS.SOLAR_PANEL_2,
                yAxisID: 'yIndividualPanels', // Assign to the left y-axis
                tension: 0.1, fill: false
            });
        }
        if (chartData.some(d => d.Panel4Power !== null && d.Panel4Power !== undefined)) {
            datasets.push({
                label: 'Panel 4 Power (W)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.Panel4Power })),
                borderColor: CHART_COLORS.SOLAR_PANEL_4,
                yAxisID: 'yIndividualPanels', // Assign to the left y-axis
                tension: 0.1, fill: false
            });
        }

        if (datasets.length === 0) {
            // console.warn('Solar Panel Chart: No valid datasets could be formed.');
            ctx.font = "16px Arial"; ctx.fillStyle = "grey"; ctx.textAlign = "center";
            ctx.fillText("No plottable solar panel data found.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            if (solarPanelChartInstance) { solarPanelChartInstance.destroy(); solarPanelChartInstance = null; }
            return;
        }

        if (solarPanelChartInstance) { solarPanelChartInstance.destroy(); }

        solarPanelChartInstance = new Chart(ctx, {
            type: 'line',
            data: { datasets: datasets },
            options: {
                responsive: true, maintainAspectRatio: false,
                scales: {
                    x: { type: 'time', time: { unit: 'hour', tooltipFormat: 'MMM d, yyyy HH:mm', displayFormats: { hour: 'MMM d HH:mm', day: 'MMM d' } }, title: { display: true, text: 'Time', color: chartTextColor }, ticks: { color: chartTextColor, maxRotation: 0, autoSkip: true, autoSkipPadding: 20 }, grid: { color: chartGridColor } },
                    yIndividualPanels: { // Y-axis for individual panel powers
                        type: 'linear',
                        position: 'left',
                        title: { display: true, text: 'Panel Power (W)', color: chartTextColor },
                        ticks: { color: chartTextColor, beginAtZero: true },
                        grid: { color: chartGridColor }
                    },
                    yTotalSolar: { // New Y-axis for Total Solar Input
                        type: 'linear',
                        position: 'right',
                        title: { display: true, text: 'Total Solar (W)', color: chartTextColor },
                        ticks: { color: chartTextColor, beginAtZero: true },
                        grid: { drawOnChartArea: false } // Only draw grid lines for the primary y-axis (left)
                    }
                },
                plugins: { tooltip: { mode: 'index', intersect: false }, legend: { position: 'top', labels: { color: chartTextColor } } }
            }
        });
    }

    /**
     * Renders the Telemetry Chart (Glider Speed/Heading) using Chart.js.
     * @param {Array<Object>|null} chartData - The data array fetched from the API.
     */
    function renderTelemetryChart(chartData) { // Renamed from renderNavigationChart
        const canvas = document.getElementById('telemetryChart'); // Updated ID
        if (!canvas) { return; } // Canvas not found - silent fail (DOM issue)
        const ctx = canvas.getContext('2d');
        const spinner = ctx.canvas.parentElement.querySelector('.chart-spinner');
        hideChartSpinner(spinner);

        if (!chartData || chartData.length === 0) {
            ctx.font = "16px Arial"; ctx.fillStyle = "grey"; ctx.textAlign = "center";
            ctx.fillText("No navigation trend data available.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            if (telemetryChartInstance) { telemetryChartInstance.destroy(); telemetryChartInstance = null; } // Updated instance variable
            return;
        }

        const datasets = [];
        if (chartData.some(d => d.GliderSpeed !== null && d.GliderSpeed !== undefined)) {
            datasets.push({
                label: 'Glider Speed (knots)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.GliderSpeed })),
                borderColor: CHART_COLORS.NAV_SPEED,
                yAxisID: 'ySpeed',
                tension: 0.1, fill: false
            });
        }
        if (chartData.some(d => d.SpeedOverGround !== null && d.SpeedOverGround !== undefined)) {
            datasets.push({
                label: 'SOG (knots)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.SpeedOverGround })),
                borderColor: CHART_COLORS.NAV_SOG,
                yAxisID: 'ySpeed', // Share Y-axis with GliderSpeed
                borderDash: [5, 5], // Dashed line
                tension: 0.1, fill: false
            });
        }
        if (chartData.some(d => d.GliderHeading !== null && d.GliderHeading !== undefined)) {
            datasets.push({
                label: 'Glider Heading (°)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.GliderHeading })),
                borderColor: CHART_COLORS.NAV_HEADING,
                yAxisID: 'yHeading',
                tension: 0.1, fill: false
            });
        }

        if (datasets.length === 0) {
            ctx.font = "16px Arial"; ctx.fillStyle = "grey"; ctx.textAlign = "center";
            ctx.fillText("No plottable navigation data found.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            if (telemetryChartInstance) { telemetryChartInstance.destroy(); telemetryChartInstance = null; } // Updated instance variable
            return;
        }

        if (telemetryChartInstance) { telemetryChartInstance.destroy(); } // Updated instance variable
        telemetryChartInstance = new Chart(ctx, { // Updated instance variable
            type: 'line',
            data: { datasets: datasets },
            options: {
                responsive: true, maintainAspectRatio: false,
                scales: {
                    x: { type: 'time', time: { unit: 'hour', tooltipFormat: 'MMM d, yyyy HH:mm', displayFormats: { hour: 'MMM d HH:mm', day: 'MMM d' } }, title: { display: true, text: 'Time', color: chartTextColor }, ticks: { color: chartTextColor, maxRotation: 0, autoSkip: true }, grid: { color: chartGridColor } },
                    ySpeed: { type: 'linear', position: 'left', title: { display: true, text: 'Speed (knots)', color: chartTextColor }, ticks: { color: chartTextColor, beginAtZero: true }, grid: { color: chartGridColor } },
                    yHeading: { type: 'linear', position: 'right', title: { display: true, text: 'Heading (°)', color: chartTextColor }, ticks: { color: chartTextColor, min: 0, max: 360 }, grid: { drawOnChartArea: false } }
                },
                plugins: { tooltip: { mode: 'index', intersect: false }, legend: { position: 'top', labels: { color: chartTextColor } } }
            }
        });
    }

    /**
     * Renders the Navigation Ocean Current Chart using Chart.js.
     * @param {Array<Object>|null} chartData - The data array fetched from the API.
     */
    function renderNavigationCurrentChart(chartData) {
        const canvas = document.getElementById('telemetryCurrentChart');
        if (!canvas) { return; } // Canvas not found - silent fail (DOM issue)
        const ctx = canvas.getContext('2d');
        const spinner = ctx.canvas.parentElement.querySelector('.chart-spinner');
        hideChartSpinner(spinner);

        if (!chartData || chartData.length === 0) {
            ctx.font = "16px Arial"; ctx.fillStyle = "grey"; ctx.textAlign = "center";
            ctx.fillText("No ocean current data available.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            if (navigationCurrentChartInstance) { navigationCurrentChartInstance.destroy(); navigationCurrentChartInstance = null; }
            return;
        }

        const datasets = [];
        if (chartData.some(d => d.OceanCurrentSpeed !== null && d.OceanCurrentSpeed !== undefined)) {
            datasets.push({
                label: 'Ocean Current Speed (kn)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.OceanCurrentSpeed })),
                borderColor: CHART_COLORS.OCEAN_CURRENT_SPEED,
                yAxisID: 'ySpeed',
                tension: 0.1, fill: false
            });
        }
        if (chartData.some(d => d.OceanCurrentDirection !== null && d.OceanCurrentDirection !== undefined)) {
            datasets.push({
                label: 'Ocean Current Dir (°)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.OceanCurrentDirection })),
                borderColor: CHART_COLORS.OCEAN_CURRENT_DIRECTION,
                yAxisID: 'yDirection',
                tension: 0.1, fill: false
            });
        }
        if (chartData.some(d => d.SpeedOverGround !== null && d.SpeedOverGround !== undefined)) {
            datasets.push({
                label: 'SOG (knots)', // Will use yDirection axis
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.SpeedOverGround })),
                borderColor: CHART_COLORS.NAV_SOG.replace('0.7)', '0.5)'), // Make it 50% transparent
                yAxisID: 'ySpeed', // Plot SOG against the speed axis
                borderDash: [5, 5],
                tension: 0.1, fill: false
            });
        }

        if (datasets.length === 0) {
            ctx.font = "16px Arial"; ctx.fillStyle = "grey"; ctx.textAlign = "center";
            ctx.fillText("No plottable ocean current data.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            if (navigationCurrentChartInstance) { navigationCurrentChartInstance.destroy(); navigationCurrentChartInstance = null; }
            return;
        }

        if (navigationCurrentChartInstance) { navigationCurrentChartInstance.destroy(); }
        navigationCurrentChartInstance = new Chart(ctx, {
            type: 'line',
            data: { datasets: datasets },
            options: {
                responsive: true, maintainAspectRatio: false,
                scales: {
                    x: { type: 'time', time: { unit: 'hour', tooltipFormat: 'MMM d, yyyy HH:mm', displayFormats: { hour: 'MMM d HH:mm', day: 'MMM d' } }, title: { display: true, text: 'Time', color: chartTextColor }, ticks: { color: chartTextColor, maxRotation: 0, autoSkip: true }, grid: { color: chartGridColor } },
                    ySpeed: { type: 'linear', position: 'left', title: { display: true, text: 'Speed (knots)', color: chartTextColor }, ticks: { color: chartTextColor, beginAtZero: true }, grid: { color: chartGridColor } },
                    yDirection: { type: 'linear', position: 'right', title: { display: true, text: 'Direction (°)', color: chartTextColor }, ticks: { color: chartTextColor, min: 0, max: 360 }, grid: { drawOnChartArea: false } }
                },
                plugins: { tooltip: { mode: 'index', intersect: false }, legend: { position: 'top', labels: { color: chartTextColor } } }
            }
        });
    }

    /**
     * Renders the Navigation Heading Difference Chart using Chart.js.
     * @param {Array<Object>|null} chartData - The data array fetched from the API.
     */
    function renderNavigationHeadingDiffChart(chartData) {
        const canvas = document.getElementById('telemetryHeadingDiffChart');
        if (!canvas) { return; } // Canvas not found - silent fail (DOM issue)
        const ctx = canvas.getContext('2d');
        const spinner = ctx.canvas.parentElement.querySelector('.chart-spinner');
        hideChartSpinner(spinner);

        if (!chartData || chartData.length === 0) {
            ctx.font = "16px Arial"; ctx.fillStyle = "grey"; ctx.textAlign = "center";
            ctx.fillText("No heading difference data available.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            if (navigationHeadingDiffChartInstance) { navigationHeadingDiffChartInstance.destroy(); navigationHeadingDiffChartInstance = null; }
            return;
        }

        const datasets = [];
        // Calculate Heading Difference
        const headingDiffData = chartData.map(item => {
            let diff = null;
            if (item.HeadingSubDegrees !== null && item.DesiredBearingDegrees !== null) {
                diff = item.HeadingSubDegrees - item.DesiredBearingDegrees;
                // Normalize to -180 to 180 range
                while (diff > 180) diff -= 360;
                while (diff < -180) diff += 360;
            }
            return { x: new Date(item.Timestamp), y: diff };
        }).filter(item => item.y !== null);

        if (headingDiffData.length > 0) {
            datasets.push({
                label: 'Sub Heading Diff (°)',
                data: headingDiffData,
                borderColor: CHART_COLORS.HEADING_DIFF,
                yAxisID: 'yDiff',
                tension: 0.1, fill: false
            });
        }

        if (chartData.some(d => d.OceanCurrentSpeed !== null && d.OceanCurrentSpeed !== undefined)) {
            datasets.push({
                label: 'Ocean Current Speed (kn)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.OceanCurrentSpeed })),
                borderColor: CHART_COLORS.OCEAN_CURRENT_SPEED.replace('1)', '0.7)'), // Slightly transparent
                borderDash: [5, 5],
                yAxisID: 'ySpeed',
                tension: 0.1, fill: false
            });
        }

        if (datasets.length === 0) {
            ctx.font = "16px Arial"; ctx.fillStyle = "grey"; ctx.textAlign = "center";
            ctx.fillText("No plottable heading diff data.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            if (navigationHeadingDiffChartInstance) { navigationHeadingDiffChartInstance.destroy(); navigationHeadingDiffChartInstance = null; }
            return;
        }

        if (navigationHeadingDiffChartInstance) { navigationHeadingDiffChartInstance.destroy(); }
        navigationHeadingDiffChartInstance = new Chart(ctx, {
            type: 'line',
            data: { datasets: datasets },
            options: {
                responsive: true, maintainAspectRatio: false,
                scales: {
                    x: { type: 'time', time: { unit: 'hour', tooltipFormat: 'MMM d, yyyy HH:mm', displayFormats: { hour: 'MMM d HH:mm', day: 'MMM d' } }, title: { display: true, text: 'Time', color: chartTextColor }, ticks: { color: chartTextColor, maxRotation: 0, autoSkip: true }, grid: { color: chartGridColor } },
                    ySpeed: { type: 'linear', position: 'left', title: { display: true, text: 'Ocean Current (kn)', color: chartTextColor }, ticks: { color: chartTextColor, beginAtZero: true }, grid: { color: chartGridColor } },
                    yDiff: { type: 'linear', position: 'right', title: { display: true, text: 'Heading Diff (°)', color: chartTextColor }, ticks: { color: chartTextColor, min: -180, max: 180 }, grid: { drawOnChartArea: false } }
                },
                plugins: { tooltip: { mode: 'index', intersect: false }, legend: { position: 'top', labels: { color: chartTextColor } } }
            }
        });
    }

    /**
     * Renders the WG-VM4 Chart using Chart.js.
     * @param {Array<Object>|null} chartData - The data array fetched from the API.
     */
    function renderWgVm4Chart(chartData) {
        const canvas = document.getElementById('wgVm4Chart');
        if (!canvas) { return; } // Canvas not found - silent fail (DOM issue)
        const ctx = canvas.getContext('2d');
        const spinner = ctx.canvas.parentElement.querySelector('.chart-spinner');
        hideChartSpinner(spinner);

        if (!chartData || chartData.length === 0) {
            ctx.font = "16px Arial"; ctx.fillStyle = "grey"; ctx.textAlign = "center";
            ctx.fillText("No WG-VM4 trend data available.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            if (wgVm4ChartInstance) { wgVm4ChartInstance.destroy(); wgVm4ChartInstance = null; }
            return;
        }

        const datasets = [];
        // Assuming 'Channel0DetectionCount' and 'Channel1DetectionCount' from processor
        if (chartData.some(d => d.Channel0DetectionCount !== null && d.Channel0DetectionCount !== undefined)) {
            datasets.push({
                label: 'Ch0 Detections',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.Channel0DetectionCount })),
                borderColor: CHART_COLORS.WG_VM4_CH0_DETECTION,
                yAxisID: 'yDetections',
                tension: 0.1, fill: false
            });
        }
        if (chartData.some(d => d.Channel1DetectionCount !== null && d.Channel1DetectionCount !== undefined)) {
            datasets.push({
                label: 'Ch1 Detections',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.Channel1DetectionCount })),
                borderColor: CHART_COLORS.CTD_SALINITY, // Re-use a contrasting color
                yAxisID: 'yDetections', // Share the same axis
                tension: 0.1, fill: false,
                borderDash: [5, 5] // Optional: dashed line for second channel
            });
        }

        if (datasets.length === 0) {
            ctx.font = "16px Arial"; ctx.fillStyle = "grey"; ctx.textAlign = "center";
            ctx.fillText("No plottable WG-VM4 data found.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            if (wgVm4ChartInstance) { wgVm4ChartInstance.destroy(); wgVm4ChartInstance = null; }
            return;
        }

        if (wgVm4ChartInstance) { wgVm4ChartInstance.destroy(); }
        wgVm4ChartInstance = new Chart(ctx, {
            type: 'line',
            data: { datasets: datasets },
            options: {
                responsive: true, maintainAspectRatio: false,
                scales: {
                    x: { type: 'time', time: { unit: 'hour', tooltipFormat: 'MMM d, yyyy HH:mm', displayFormats: { hour: 'MMM d HH:mm', day: 'MMM d' } }, title: { display: true, text: 'Time', color: chartTextColor }, ticks: { color: chartTextColor, maxRotation: 0, autoSkip: true }, grid: { color: chartGridColor } },
                    yDetections: { type: 'linear', position: 'left', title: { display: true, text: 'Detection Counts', color: chartTextColor }, ticks: { color: chartTextColor, beginAtZero: true }, grid: { color: chartGridColor } }
                },
                plugins: { tooltip: { mode: 'index', intersect: false }, legend: { position: 'top', labels: { color: chartTextColor } } }
            }
        });
    }

    // Refresh Data Button Logic (Moved here for better organization)
    const refreshDataBtn = document.getElementById('refreshDataBtnBanner');
    if (refreshDataBtn) {
        refreshDataBtn.addEventListener('click', function() {
            const currentUrl = new URL(window.location.href);
            currentUrl.searchParams.set('refresh', 'true'); // Add refresh parameter
            window.location.href = currentUrl.toString(); // Reload the page
        });
    }
    // Reminder: Revisit threshold highlighting values
    // console.log("Reminder: Revisit and fine-tune threshold highlighting values in index.html for summaries.");

    // --- Error Category Chart Rendering ---
    function renderErrorCategoryChart() {
        const canvas = document.getElementById('errorCategoryChart');
        if (!canvas) {
            return; // Canvas not found - silent fail (DOM issue)
        }
        
        const ctx = canvas.getContext('2d');
        
        // Get error analysis data from the template
        const errorAnalysis = window.errorAnalysisData || {};
        const categories = errorAnalysis.categories || {};
        
        if (Object.keys(categories).length === 0) {
            // Hide the chart container and show no data message
            const container = canvas.closest('.chart-container');
            const noDataMessage = document.getElementById('noErrorDataMessage');
            if (container) {
                container.style.display = 'none';
            }
            if (noDataMessage) {
                noDataMessage.style.display = 'block';
            }
            return;
        }
        
        // Show the chart container and hide no data message
        const container = canvas.closest('.chart-container');
        const noDataMessage = document.getElementById('noErrorDataMessage');
        if (container) {
            container.style.display = 'block';
        }
        if (noDataMessage) {
            noDataMessage.style.display = 'none';
        }
        
        // Prepare chart data
        const labels = Object.keys(categories).map(cat => cat.charAt(0).toUpperCase() + cat.slice(1));
        const data = Object.values(categories).map(cat => cat.count);
        
        // Color mapping to match Bootstrap card colors
        const colorMap = {
            'navigation': '#0d6efd',      // Primary blue
            'communication': '#ffc107',    // Warning yellow
            'system_operations': '#dc3545', // Danger red
            'environmental': '#0dcaf0',    // Info teal
            'unknown': '#6c757d'          // Secondary gray
        };
        
        const colors = Object.keys(categories).map(cat => colorMap[cat] || '#6c757d');
        
        // Destroy existing chart if it exists
        if (window.errorCategoryChartInstance) {
            window.errorCategoryChartInstance.destroy();
        }
        
        window.errorCategoryChartInstance = new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: labels,
                datasets: [{
                    data: data,
                    backgroundColor: colors.slice(0, labels.length),
                    borderWidth: 2,
                    borderColor: '#fff'
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                aspectRatio: 1,
                layout: {
                    padding: {
                        top: 10,
                        bottom: 10,
                        left: 10,
                        right: 10
                    }
                },
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            usePointStyle: true,
                            padding: 15,
                            font: {
                                size: 11
                            },
                            boxWidth: 12
                        }
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                const category = context.label.toLowerCase();
                                const categoryData = categories[category];
                                const total = data.reduce((a, b) => a + b, 0);
                                const percentage = ((context.parsed / total) * 100).toFixed(1);
                                return `${context.label}: ${context.parsed} errors (${percentage}%)`;
                            }
                        }
                    }
                },
                onResize: function(chart, size) {
                    // Ensure chart doesn't exceed container bounds
                    if (size.height > 300) {
                        chart.resize(300, 300);
                    }
                }
            }
        });
    }

    // --- NEW: Mini Chart Rendering ---
    function renderMiniChart(canvasId, trendData, chartColor = miniChartLineColor) {
        // console.log(`Attempting to render mini chart for canvas ID: ${canvasId} with data length: ${trendData ? trendData.length : 'null'}`);
        const canvas = document.getElementById(canvasId);
        if (!canvas) {
            return; // Canvas not found - silent fail (DOM issue)
        }
        const ctx = canvas.getContext('2d');

        if (miniChartInstances[canvasId]) {
            miniChartInstances[canvasId].destroy();
        }

        if (!trendData || trendData.length === 0) { // Check moved to caller, but safe to keep
            // console.log(`No data points to render for mini chart ${canvasId}.`);
            return;
        }

        const dataPoints = trendData.map(item => ({
            x: new Date(item.Timestamp), // Ensure Timestamp is parsed as Date
            y: item.value
        }));

        // Log first few parsed dates to check validity
        // if (dataPoints.length > 0) {
            // console.log(`  First 3 parsed timestamps for ${canvasId}:`, dataPoints.slice(0, 3).map(p => p.x));
        // }

        // Calculate min and max for y-axis to "stretch" the view
        let yMin = Infinity;
        let yMax = -Infinity;
        dataPoints.forEach(point => {
            if (point.y < yMin) yMin = point.y;
            if (point.y > yMax) yMax = point.y;
        });

        let yAxisMin, yAxisMax;
        const range = yMax - yMin;

        if (range === 0) { // Handle flat line data
            yAxisMin = yMin - 1; // Add some arbitrary padding
            yAxisMax = yMax + 1;
        } else {
            const padding = range * 0.10; // 10% padding
            yAxisMin = yMin - padding;
            yAxisMax = yMax + padding;
        }

        // console.log(`Rendering Chart.js instance for ${canvasId}`);
        miniChartInstances[canvasId] = new Chart(ctx, {
            type: 'line',
            data: {
                datasets: [{
                    data: dataPoints,
                    borderColor: chartColor, // Use the passed chartColor
                    borderWidth: 1.5, // Keep it slightly thicker
                    pointRadius: 0, // No points on mini charts
                    tension: 0.1,   // straight line for mini trend
                    fill: false
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: false, // No animation for mini charts
                scales: {
                    x: {
                        type: 'time', 
                        display: false, // Final: Hide x-axis
                        // ticks: { color: 'lime', font: { size: 7 }, autoSkip: true, maxRotation: 0, minRotation: 0 }, // TEMPORARY: For x-axis debugging
                        grid: { display: false } // Optionally hide x-axis grid lines for mini chart
                    }, 
                    y: { 
                        display: false, // Keep y-axis hidden for final appearance
                        min: yAxisMin, // Set calculated min
                        max: yAxisMax, // Set calculated max
                        // grace: '10%' // Not needed if min/max are manually set with padding
                    }
                },
                plugins: {
                    legend: { 
                        display: false // Keep legend hidden
                    }, 
                    tooltip: { enabled: false } // Keep tooltips disabled
                },
                layout: {
                    padding: { // Minimal padding
                        left: 1,
                        right: 1,
                        top: 3,
                        bottom: 1
                    }
                }
            }
        });
        // console.log(`Mini chart ${canvasId} should be rendered.`);
    }

    // --- NEW: Initialize Mini Charts ---
    function initializeMiniCharts() {
        // console.log("Initializing mini charts...");
        const summaryCards = document.querySelectorAll('#left-nav-panel .summary-card');
        summaryCards.forEach(card => {
            const category = card.dataset.category; // e.g., "power", "ctd", "navigation"
            const miniChartCanvasId = `mini${category === 'waves' ? 'Wave' : category.charAt(0).toUpperCase() + category.slice(1)}Chart`;
            const canvasElement = document.getElementById(miniChartCanvasId);
            // console.log(`Processing mini chart for category: ${category}, canvas ID: ${miniChartCanvasId}`);

            if (canvasElement) { // Only try to render if a canvas exists
                const trendDataJson = card.dataset.miniTrend;
                // console.log(`  Raw mini-trend JSON for ${category}:`, trendDataJson);
                if (trendDataJson) {
                    // Ensure the string is not empty before trying to parse
                    if (trendDataJson.trim() === "") {
                        // console.log(`  Skipping empty mini-trend JSON for ${category}.`);
                        return; // Skip to the next card
                    }
                    try {
                        const trendData = JSON.parse(trendDataJson);
                        if (trendData && trendData.length > 0) {
                            let specificColor = miniChartLineColor; // Default color
                            // Assign specific colors based on category, matching large charts
                            switch (category) {
                                case 'power': // NetPowerWatts mini-trend. Using SolarInputWatts color as a proxy.
                                    specificColor = CHART_COLORS.POWER_SOLAR;
                                    break;
                                case 'ctd': // WaterTemperature mini-trend
                                    specificColor = CHART_COLORS.CTD_TEMP;
                                    break;
                                case 'weather': // WindSpeed mini-trend
                                    specificColor = CHART_COLORS.WEATHER_WIND_SPEED;
                                    break;
                                case 'waves': // SignificantWaveHeight mini-trend
                                    specificColor = CHART_COLORS.WAVES_SIG_HEIGHT;
                                    break;
                                case 'vr2c': // DetectionCount mini-trend
                                    specificColor = CHART_COLORS.VR2C_DETECTION;
                                    break;
                                case 'fluorometer': // C1_Avg mini-trend
                                    specificColor = CHART_COLORS.FLUORO_C_AVG_PRIMARY;
                                    break;
                                case 'navigation': // GliderSpeed mini-trend
                                    specificColor = CHART_COLORS.NAV_SPEED;
                                    break;
                                case 'wg_vm4': // Channel0DetectionCount mini-trend
                                    specificColor = CHART_COLORS.WG_VM4_CH0_DETECTION;
                                    break;
                                // Add other cases as needed
                            }
                            renderMiniChart(miniChartCanvasId, trendData, specificColor);
                        } else {
                            // console.log(`  No data points to render for mini chart ${category} (data is empty or null).`);
                        }
                    } catch (e) {
                        // Silent fail for parsing errors (data issue)
                    }
                }
            }
        });
    }

    // --- NEW: Left Panel Click Handler ---
    function handleLeftPanelClicks() {
        const summaryCards = document.querySelectorAll('#left-nav-panel .summary-card');
        const detailViews = document.querySelectorAll('#main-display-area .category-detail-view');

        summaryCards.forEach(card => {
            card.addEventListener('click', function() {
                summaryCards.forEach(c => c.classList.remove('active-card'));
                this.classList.add('active-card');
                const category = this.dataset.category;
                detailViews.forEach(view => view.style.display = 'none');
                const activeDetailView = document.getElementById(`detail-${category}`);
                if (activeDetailView) {
                    activeDetailView.style.display = 'block';

                    // Special handling for Waves to trigger spectrum load when its detail view is shown
                    if (category === 'waves') {
                        // The main wave charts are reloaded by the generic loader below
                        fetchAndRenderWaveSpectrum(missionId);
                        // Fetch and render marine forecast when Waves detail is shown
                        fetchMarineForecastData(missionId).then(data => renderMarineForecast(data));
                    } else if (category === 'wg_vm4') {
                        // Initialize the offload log section specific to WG-VM4
                        if (typeof initializeWgVm4OffloadSection === 'function') initializeWgVm4OffloadSection();
                    }
                    // Generic loader for all cards to ensure data is refreshed on click
                    const loader = getSensorLoader(category);
                    if (loader) {
                        loader();
                    }
                }
            });
        });
    }

    function getSensorLoader(reportType) {
        // Map the UI category 'navigation' to the data/API report type 'telemetry'.
        // This allows the 'navigation' card click and initial load to trigger the 'telemetry' data loader,
        // while the controls within the detail view can still correctly use 'telemetry'.
        if (reportType === 'navigation') {
            reportType = 'telemetry';
        }
        const loaders = {
            'power': () => isSensorEnabled('power') ? Promise.all([fetchChartData('power', missionId), fetchChartData('solar', missionId)]).then(([powerData, solarData]) => {
                renderPowerChart(powerData);
                renderSolarPanelChart(solarData, powerData);
            }).catch(error => { showToast(`Error loading power/solar data: ${error.message}`, 'danger'); renderPowerChart(null); renderSolarPanelChart(null, null); }) : Promise.resolve(),
            'ctd': () => isSensorEnabled('ctd') ? fetchChartData('ctd', missionId).then(data => {
                renderCtdChart(data);
                renderCtdProfileChart(data);
            }) : Promise.resolve(),
            'weather': () => isSensorEnabled('weather') ? fetchChartData('weather', missionId).then(data => renderWeatherSensorChart(data)) : Promise.resolve(),
            'waves': () => isSensorEnabled('waves') ? fetchChartData('waves', missionId).then(data => {
                renderWaveChart(data);
                renderWaveHeightDirectionChart(data);
            }) : Promise.resolve(),
            'vr2c': () => isSensorEnabled('vr2c') ? fetchChartData('vr2c', missionId).then(data => renderVr2cChart(data)) : Promise.resolve(),
            'fluorometer': () => isSensorEnabled('fluorometer') ? fetchChartData('fluorometer', missionId).then(data => renderFluorometerChart(data)) : Promise.resolve(),
            'wg_vm4': () => isSensorEnabled('wg_vm4') ? fetchChartData('wg_vm4', missionId).then(data => renderWgVm4Chart(data)) : Promise.resolve(),
            'telemetry': () => isSensorEnabled('navigation') ? fetchChartData('telemetry', missionId).then(data => { // This key is used by controls and mapped from 'navigation'
                renderTelemetryChart(data); // Updated function name
                renderNavigationCurrentChart(data);
                renderNavigationHeadingDiffChart(data);
            }).catch(error => { showToast(`Error loading telemetry data: ${error.message}`, 'danger'); renderTelemetryChart(null); renderNavigationCurrentChart(null); renderNavigationHeadingDiffChart(null); }) : Promise.resolve(), // Add catch for telemetry
            'errors': () => isSensorEnabled('errors') ? Promise.resolve().then(() => {
                renderErrorCategoryChart();
            }) : Promise.resolve()
        };
        return loaders[reportType];
    }

    function initializeInteractiveControls() {
        document.querySelectorAll('.hours-back-input, .granularity-select, .date-range-input').forEach(input => {
            input.addEventListener('change', (event) => {
                const reportType = event.target.dataset.reportType;
                const loader = getSensorLoader(reportType);
                if (loader) {
                    loader();
                }
            });
        });
    }
    
    function initializeRefreshButtons() {
        document.querySelectorAll('.refresh-chart-button').forEach(button => {
            button.addEventListener('click', (event) => {
                const reportType = event.target.dataset.reportType;
                const loader = getSensorLoader(reportType);
                if (loader) loader();
            });
        });
    }

    // --- Theme Change Handler ---
    function updateAllChartInstances() {
        const chartInstances = [
            powerChartInstance, ctdChartInstance, weatherSensorChartInstance,
            waveChartInstance, vr2cChartInstance, ctdProfileChartInstance,
            solarPanelChartInstance, fluorometerChartInstance, wgVm4ChartInstance,
            waveHeightDirectionChartInstance, waveSpectrumChartInstance,
            telemetryChartInstance, navigationCurrentChartInstance,
            navigationHeadingDiffChartInstance
        ];

        chartInstances.forEach(chart => {
            if (chart) {
                // Update scales
                Object.keys(chart.options.scales).forEach(scaleKey => {
                    const scale = chart.options.scales[scaleKey];
                    if (scale.title) scale.title.color = chartTextColor;
                    if (scale.ticks) scale.ticks.color = chartTextColor;
                    if (scale.grid && scale.grid.drawOnChartArea !== false) {
                        scale.grid.color = chartGridColor;
                    }
                });
                // Update legend
                if (chart.options.plugins.legend) {
                    chart.options.plugins.legend.labels.color = chartTextColor;
                }
                chart.update('none'); // Update without animation
            }
        });
        
        // Re-render mini charts as their colors are in the dataset
        initializeMiniCharts();
    }

    function initializeDownloadButtons() {
        document.querySelectorAll('.download-csv-btn').forEach(button => {
            button.addEventListener('click', function(e) {
                e.preventDefault();
                const reportType = this.dataset.reportType;
                downloadChartDataAsCsv(reportType);
            });
        });

        document.querySelectorAll('.save-charts-btn').forEach(button => {
            button.addEventListener('click', function(e) {
                e.preventDefault();
                const category = this.dataset.reportType; // This is the category like 'navigation'
                const highRes = this.dataset.highRes === 'true';
                saveChartsAsPng(category, highRes);
            });
        });
    }

    function downloadChartDataAsCsv(reportType) {
        const mission = document.body.dataset.missionId;
        const hoursInput = document.querySelector(`.hours-back-input[data-report-type="${reportType}"]`);
        const granularitySelect = document.querySelector(`.granularity-select[data-report-type="${reportType}"]`);

        const hours = hoursInput ? hoursInput.value : 72;
        const granularity = granularitySelect ? granularitySelect.value : 15;

        // Use the new unified CSV download endpoint
        let apiUrl = `/api/sensor_csv/${reportType}?mission=${mission}&hours_back=${hours}&granularity_minutes=${granularity}`;
        
        // Add date range parameters if date range is enabled
        const startInput = document.getElementById(`start-date-${reportType}`);
        const endInput = document.getElementById(`end-date-${reportType}`);
        if (startInput && endInput && startInput.value && endInput.value) {
            const startDate = new Date(startInput.value);
            const endDate = new Date(endInput.value);
            const startISO = startDate.toISOString();
            const endISO = endDate.toISOString();
            apiUrl += `&start_date=${encodeURIComponent(startISO)}&end_date=${encodeURIComponent(endISO)}`;
        }

        // Trigger download by navigating to the URL
        window.location.href = apiUrl;
    }

    // Function to enhance Chart.js for high-resolution rendering
    function enhanceChartForHighRes(chartInstance) {
        if (!chartInstance) return;
        
        // Store original options for restoration
        const originalOptions = JSON.parse(JSON.stringify(chartInstance.options));
        
        // Enhance font sizes for high-resolution
        const fontMultiplier = 1.5; // Moderate font size increase 
        
        // Update scales
        Object.keys(chartInstance.options.scales).forEach(scaleKey => {
            const scale = chartInstance.options.scales[scaleKey];
            if (scale.title) {
                scale.title.font = { size: (scale.title.font?.size || 14) * fontMultiplier };
            }
            if (scale.ticks) {
                scale.ticks.font = { size: (scale.ticks.font?.size || 12) * fontMultiplier };
            }
        });
        
        // Update legend
        if (chartInstance.options.plugins.legend) {
            chartInstance.options.plugins.legend.labels.font = { 
                size: (chartInstance.options.plugins.legend.labels.font?.size || 12) * fontMultiplier 
            };
        }
        
        // Update tooltip
        if (chartInstance.options.plugins.tooltip) {
            chartInstance.options.plugins.tooltip.titleFont = { 
                size: (chartInstance.options.plugins.tooltip.titleFont?.size || 12) * fontMultiplier 
            };
            chartInstance.options.plugins.tooltip.bodyFont = { 
                size: (chartInstance.options.plugins.tooltip.bodyFont?.size || 12) * fontMultiplier 
            };
        }
        
        // Update datasets for thicker lines
        chartInstance.data.datasets.forEach(dataset => {
            if (dataset.borderWidth) {
                dataset.borderWidth = dataset.borderWidth * 2; // Thicker lines
            }
            if (dataset.pointRadius !== undefined) {
                dataset.pointRadius = dataset.pointRadius * 2; // Larger points
            }
        });
        
        // Force update
        chartInstance.update('none');
        
        return originalOptions;
    }
    
    // Function to restore Chart.js to original state
    function restoreChartFromHighRes(chartInstance, originalOptions) {
        if (!chartInstance || !originalOptions) return;
        
        // Restore options
        chartInstance.options = originalOptions;
        chartInstance.update('none');
    }

    function saveChartsAsPng(category, highResolution = false) {
        const detailView = document.getElementById(`detail-${category}`);
        if (!detailView) {
            return; // Detail view not found - silent fail (DOM issue)
        }

        const mission = document.body.dataset.missionId;
        const canvases = detailView.querySelectorAll('canvas');
        if (canvases.length === 0) {
            alert(`No charts found to save for the ${category} view.`);
            return;
        }

        const chartInstanceMap = { 'powerChart': powerChartInstance, 'solarPanelChart': solarPanelChartInstance, 'ctdChart': ctdChartInstance, 'ctdProfileChart': ctdProfileChartInstance, 'weatherSensorChart': weatherSensorChartInstance, 'waveChart': waveChartInstance, 'waveHeightDirectionChart': waveHeightDirectionChartInstance, 'waveSpectrumChart': waveSpectrumChartInstance, 'vr2cChart': vr2cChartInstance, 'fluorometerChart': fluorometerChartInstance, 'wgVm4Chart': wgVm4ChartInstance, 'telemetryChart': telemetryChartInstance, 'telemetryCurrentChart': navigationCurrentChartInstance, 'telemetryHeadingDiffChart': navigationHeadingDiffChartInstance };

        // Store original chart states for restoration
        const originalStates = {};

        canvases.forEach(canvas => {
            const chartId = canvas.id;
            const chartInstance = chartInstanceMap[chartId];

            if (chartInstance) {
                // Enhance chart for high-resolution if needed
                if (highResolution) {
                    originalStates[chartId] = enhanceChartForHighRes(chartInstance);
                }
                
                const newCanvas = document.createElement('canvas');
                
                if (highResolution) {
                    // Enhanced high-resolution scaling: 4x for dramatic quality improvement
                    const scaleFactor = 4;
                    newCanvas.width = chartInstance.canvas.width * scaleFactor;
                    newCanvas.height = chartInstance.canvas.height * scaleFactor;
                    const newCtx = newCanvas.getContext('2d');
                    
                    // Enhanced image smoothing for better quality
                    newCtx.imageSmoothingEnabled = true;
                    newCtx.imageSmoothingQuality = 'high';
                    
                    // Set background color
                    const bodyStyles = getComputedStyle(document.body);
                    const bgColor = bodyStyles.getPropertyValue('--bs-body-bg').trim();
                    newCtx.fillStyle = bgColor;
                    newCtx.fillRect(0, 0, newCanvas.width, newCanvas.height);
                    
                    // Scale and draw the chart with enhanced quality
                    newCtx.scale(scaleFactor, scaleFactor);
                    newCtx.drawImage(chartInstance.canvas, 0, 0);
                    
                    // Additional quality enhancements
                    newCtx.textRenderingOptimization = 'optimizeQuality';
                    newCtx.textBaseline = 'alphabetic';
                } else {
                    // Standard resolution
                    newCanvas.width = chartInstance.canvas.width;
                    newCanvas.height = chartInstance.canvas.height;
                    const newCtx = newCanvas.getContext('2d');
                    const bodyStyles = getComputedStyle(document.body);
                    const bgColor = bodyStyles.getPropertyValue('--bs-body-bg').trim();
                    newCtx.fillStyle = bgColor;
                    newCtx.fillRect(0, 0, newCanvas.width, newCanvas.height);
                    newCtx.drawImage(chartInstance.canvas, 0, 0);
                }
                
                const image = newCanvas.toDataURL('image/png');
                const link = document.createElement('a');
                link.href = image;
                const suffix = highResolution ? '_high_res' : '';
                link.download = `${mission}_${chartId}${suffix}.png`;
                document.body.appendChild(link);
                link.click();
                document.body.removeChild(link);
            } else {
                console.warn(`No chart instance found for canvas with ID: ${chartId}`);
            }
        });
        
        // Restore all charts to original state after high-res export
        if (highResolution) {
            canvases.forEach(canvas => {
                const chartId = canvas.id;
                const chartInstance = chartInstanceMap[chartId];
                if (chartInstance && originalStates[chartId]) {
                    restoreChartFromHighRes(chartInstance, originalStates[chartId]);
                }
            });
        }
    }

    // Observer to watch for theme changes on the <html> element
    const observer = new MutationObserver((mutations) => {
        for (const mutation of mutations) {
            if (mutation.type === 'attributes' && mutation.attributeName === 'data-bs-theme') {
                // A brief delay allows the browser to compute the new CSS variable values
                setTimeout(() => {
                    updateChartColorVariables(); // Get new colors from CSS
                    updateAllChartInstances();   // Apply new colors to existing charts
                }, 50);
                break; // No need to check other mutations
            }
        }
    });
    observer.observe(document.documentElement, { attributes: true });

    // Initialize new UI features
    initializeMiniCharts();
    handleLeftPanelClicks();
    initializeInteractiveControls();
    initializeDownloadButtons();
    initializeDateRangeInputs();
    initializeClearButtons();
    
    // Ensure all date range inputs are properly initialized
    initializeAllDateRangeStates();
    
    // Add a global function to force refresh date range states (for debugging)
    window.refreshDateRangeStates = initializeAllDateRangeStates;
    
    // Add a global function to clear all date ranges (for debugging)
    window.clearAllDateRanges = function() {
        const reportTypes = new Set();
        document.querySelectorAll('.date-range-input').forEach(input => {
            if (input.dataset.reportType) {
                reportTypes.add(input.dataset.reportType);
            }
        });
        reportTypes.forEach(reportType => {
            clearDateRange(reportType);
        });
    };

    // Initial data load for the default active view (Navigation)
    // This ensures the main chart for the default view loads without needing a click.
    const defaultActiveCategory = document.querySelector('#left-nav-panel .summary-card.active-card')?.dataset.category;
    if (defaultActiveCategory === 'waves') {
        // If waves is the default, also fetch its marine forecast
        fetchAndRenderWaveSpectrum(missionId); // Already there for spectrum
        fetchMarineForecastData(missionId).then(data => renderMarineForecast(data));

    } else {
        // For other default active categories, ensure their data is loaded
        const loader = getSensorLoader(defaultActiveCategory);
        if (loader) loader();
    }
});