/**
 * @file admin_mission_overviews.js
 * @description Admin mission overview management
 */

import { checkAuth, getUserProfile } from '/static/js/auth.js';
import { apiRequest, showToast, fetchWithAuth } from '/static/js/api.js';

document.addEventListener('DOMContentLoaded', async function() {
    if (!await checkAuth()) return;

    // Admin role verification
    getUserProfile().then(user => {
        if (!user || user.role !== 'admin') {
            document.body.innerHTML = '<div class="container mt-5"><div class="alert alert-danger">Access Denied. You must be an administrator to view this page.</div></div>';
            return;
        }
        initializePage();
    });

    function initializePage() {
        const missionSelect = document.getElementById('missionSelect');
        const missionSpinner = document.getElementById('missionSpinner');
        const overviewFormContainer = document.getElementById('overviewFormContainer');
        const overviewForm = document.getElementById('overviewForm');
        const editingMissionTitle = document.getElementById('editingMissionTitle');
        const documentUrlInput = document.getElementById('documentUrlInput'); // This is now the hidden input
        const documentUploadInput = document.getElementById('documentUpload');
        const currentPlanContainer = document.getElementById('currentPlanContainer');
        const currentPlanLink = document.getElementById('currentPlanLink');
        const removePlanBtn = document.getElementById('removePlanBtn');
        const commentsTextarea = document.getElementById('comments');
        const saveStatusDiv = document.getElementById('saveStatus');
        const saveBtn = document.getElementById('saveOverviewBtn');
        const selectAllSensorsBtn = document.getElementById('selectAllSensors');
        const deselectAllSensorsBtn = document.getElementById('deselectAllSensors');

        let selectedMissionId = null;

        const escapeHtml = (value) => {
            if (value === null || value === undefined) return '';
            return String(value)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#039;');
        };

        // Report Generation Elements
        const reportGenerationContainer = document.getElementById('reportGenerationContainer');
        const reportGenerationPlaceholder = document.getElementById('reportGenerationPlaceholder');
        const reportTypeSelect = document.getElementById('reportTypeSelect');
        const forceRefreshCheckbox = document.getElementById('forceRefreshSensorTracker');
        const generateReportBtn = document.getElementById('generateReportBtn');
        const reportGenerationSpinner = document.getElementById('reportGenerationSpinner');
        const reportStatus = document.getElementById('reportStatus');
        const reportResult = document.getElementById('reportResult');
        const reportDownloadLink = document.getElementById('reportDownloadLink');

        // Mission Media Elements
        const mediaUploadForm = document.getElementById('mediaUploadForm');
        const mediaFileInput = document.getElementById('mediaFileInput');
        const mediaOperationSelect = document.getElementById('mediaOperationSelect');
        const mediaCaptionInput = document.getElementById('mediaCaptionInput');
        const mediaUploadBtn = document.getElementById('mediaUploadBtn');
        const mediaUploadSpinner = document.getElementById('mediaUploadSpinner');
        const missionMediaGallery = document.getElementById('missionMediaGallery');
        const mediaEditModalElement = document.getElementById('mediaEditModal');
        const mediaEditModal = mediaEditModalElement ? new bootstrap.Modal(mediaEditModalElement) : null;
        const mediaEditId = document.getElementById('mediaEditId');
        const mediaEditCaption = document.getElementById('mediaEditCaption');
        const mediaEditOperation = document.getElementById('mediaEditOperation');
        const mediaEditDisplayOrder = document.getElementById('mediaEditDisplayOrder');
        const mediaEditFeatured = document.getElementById('mediaEditFeatured');
        const mediaEditSaveBtn = document.getElementById('mediaEditSaveBtn');

        // Show/hide report generation based on mission selection
        function updateReportGenerationVisibility() {
            if (!reportGenerationContainer || !reportGenerationPlaceholder) {
                // Elements don't exist, skip silently
                return;
            }
            if (selectedMissionId) {
                reportGenerationContainer.style.display = 'block';
                reportGenerationPlaceholder.style.display = 'none';
            } else {
                reportGenerationContainer.style.display = 'none';
                reportGenerationPlaceholder.style.display = 'block';
            }
        }

        // Update force refresh checkbox based on report type
        if (reportTypeSelect && forceRefreshCheckbox) {
            reportTypeSelect.addEventListener('change', function() {
                if (reportTypeSelect.value === 'end_of_mission') {
                    forceRefreshCheckbox.checked = true;
                    forceRefreshCheckbox.disabled = true;
                } else {
                    forceRefreshCheckbox.disabled = false;
                }
            });
        }

        // Generate report handler
        if (generateReportBtn) {
            generateReportBtn.addEventListener('click', async function() {
                if (!selectedMissionId) {
                    showToast('Please select a mission first', 'warning');
                    return;
                }

                generateReportBtn.disabled = true;
                if (reportGenerationSpinner) reportGenerationSpinner.style.display = 'inline';
                if (reportStatus) reportStatus.innerHTML = '';
                if (reportResult) reportResult.style.display = 'none';

                const reportType = reportTypeSelect ? reportTypeSelect.value : 'weekly';
                const forceRefresh = forceRefreshCheckbox ? forceRefreshCheckbox.checked : false;

                try {
                    if (reportStatus) {
                        reportStatus.innerHTML = '<div class="alert alert-info">Generating report... This may take a moment.</div>';
                    }

                    const response = await apiRequest(
                        `/api/reporting/missions/${selectedMissionId}/generate-report-with-sensor-tracker`,
                        'POST',
                        {
                            report_type: reportType,
                            force_refresh_sensor_tracker: forceRefresh,
                            save_to_overview: true
                        }
                    );

                    // Determine which report URL to use based on the report type that was just generated
                    let reportUrl = null;
                    if (reportType === 'end_of_mission') {
                        reportUrl = response.end_of_mission_report_url || response.weekly_report_url; // Fallback to weekly if end_of_mission not available
                    } else {
                        reportUrl = response.weekly_report_url || response.end_of_mission_report_url; // Fallback to end_of_mission if weekly not available
                    }
                    
                    if (response && reportUrl) {
                        if (reportDownloadLink) {
                            reportDownloadLink.href = reportUrl;
                            reportDownloadLink.textContent = `Download ${reportType === 'end_of_mission' ? 'End of Mission' : 'Weekly'} Report`;
                        }
                        if (reportResult) reportResult.style.display = 'block';
                        if (reportStatus) {
                            reportStatus.innerHTML = '<div class="alert alert-success">Report generated successfully!</div>';
                        }
                        showToast('Report generated successfully!', 'success');
                        
                        // Reload mission info to update report links
                        const missionInfo = await apiRequest(`/api/missions/${selectedMissionId}/info`, 'GET');
                        if (missionInfo.overview) {
                            // Update report containers
                            const weeklyReportContainer = document.getElementById('weeklyReportContainer');
                            const weeklyReportLink = document.getElementById('weeklyReportLink');
                            const endOfMissionReportContainer = document.getElementById('endOfMissionReportContainer');
                            const endOfMissionReportLink = document.getElementById('endOfMissionReportLink');
                            const noReportsContainer = document.getElementById('noReportsContainer');
                            
                            let hasReports = false;
                            
                            // Update weekly report display
                            const weeklyReportFilename = document.getElementById('weeklyReportFilename');
                            if (missionInfo.overview.weekly_report_url) {
                                const weeklyFilename = missionInfo.overview.weekly_report_url.split('/').pop();
                                weeklyReportLink.href = missionInfo.overview.weekly_report_url;
                                if (weeklyReportFilename) {
                                    weeklyReportFilename.textContent = weeklyFilename;
                                } else {
                                    weeklyReportLink.textContent = weeklyFilename;
                                }
                                weeklyReportContainer.style.display = 'block';
                                hasReports = true;
                            } else {
                                weeklyReportContainer.style.display = 'none';
                            }
                            
                            // Update end of mission report display
                            const endOfMissionReportFilename = document.getElementById('endOfMissionReportFilename');
                            if (missionInfo.overview.end_of_mission_report_url) {
                                const eomFilename = missionInfo.overview.end_of_mission_report_url.split('/').pop();
                                endOfMissionReportLink.href = missionInfo.overview.end_of_mission_report_url;
                                if (endOfMissionReportFilename) {
                                    endOfMissionReportFilename.textContent = eomFilename;
                                } else {
                                    endOfMissionReportLink.textContent = eomFilename;
                                }
                                endOfMissionReportContainer.style.display = 'block';
                                hasReports = true;
                            } else {
                                endOfMissionReportContainer.style.display = 'none';
                            }
                            
                            noReportsContainer.style.display = hasReports ? 'none' : 'block';
                        }
                    } else {
                        throw new Error('Report generation completed but no URL was returned');
                    }

                } catch (error) {
                    if (reportStatus) {
                        reportStatus.innerHTML = `<div class="alert alert-danger">Failed to generate report: ${error.message}</div>`;
                    }
                    showToast(`Report generation failed: ${error.message}`, 'danger');
                } finally {
                    generateReportBtn.disabled = false;
                    if (reportGenerationSpinner) reportGenerationSpinner.style.display = 'none';
                }
            });
        }

        // Sensor card management functions
        function getEnabledSensorCards() {
            const checkboxes = document.querySelectorAll('.sensor-card-checkbox:checked');
            return Array.from(checkboxes).map(cb => cb.value);
        }

        function setEnabledSensorCards(enabledCards) {
            // First, uncheck all checkboxes
            document.querySelectorAll('.sensor-card-checkbox').forEach(cb => {
                cb.checked = false;
            });
            
            // Then check the enabled ones
            if (enabledCards && Array.isArray(enabledCards)) {
                enabledCards.forEach(cardType => {
                    const checkbox = document.querySelector(`input[value="${cardType}"]`);
                    if (checkbox) {
                        checkbox.checked = true;
                    }
                });
            }
        }

        function loadSensorCardConfiguration(missionInfo) {
            if (missionInfo.overview && missionInfo.overview.enabled_sensor_cards) {
                try {
                    const enabledCards = JSON.parse(missionInfo.overview.enabled_sensor_cards);
                    setEnabledSensorCards(enabledCards);
                } catch (error) {
                    console.error('Error parsing enabled sensor cards:', error);
                    setEnabledSensorCards(['navigation', 'power', 'ctd', 'weather', 'waves', 'vr2c', 'fluorometer', 'wg_vm4', 'ais', 'errors']);
                }
            } else {
                setEnabledSensorCards(['navigation', 'power', 'ctd', 'weather', 'waves', 'vr2c', 'fluorometer', 'wg_vm4', 'ais', 'errors']);
            }
        }

        // Event listeners for sensor card buttons
        selectAllSensorsBtn.addEventListener('click', function() {
            document.querySelectorAll('.sensor-card-checkbox').forEach(cb => {
                cb.checked = true;
            });
        });

        deselectAllSensorsBtn.addEventListener('click', function() {
            document.querySelectorAll('.sensor-card-checkbox').forEach(cb => {
                cb.checked = false;
            });
        });


        /**
         * Load available missions (active + historical)
         */
        async function loadMissions() {
            missionSpinner.style.display = 'inline-block';
            try {
                const allMissions = await apiRequest('/api/available_all_missions', 'GET');

                missionSelect.innerHTML = '<option selected disabled>-- Select a Mission --</option>';
                
                // Add active missions
                if (allMissions.active && allMissions.active.length > 0) {
                    const activeGroup = document.createElement('optgroup');
                    activeGroup.label = 'Active Missions';
                    allMissions.active.forEach(missionId => {
                        const option = document.createElement('option');
                        option.value = missionId;
                        option.textContent = missionId;
                        activeGroup.appendChild(option);
                    });
                    missionSelect.appendChild(activeGroup);
                }
                
                // Add historical missions
                if (allMissions.historical && allMissions.historical.length > 0) {
                    const historicalGroup = document.createElement('optgroup');
                    historicalGroup.label = 'Historical Missions';
                    allMissions.historical.forEach(missionId => {
                        const option = document.createElement('option');
                        option.value = missionId;
                        option.textContent = missionId;
                        historicalGroup.appendChild(option);
                    });
                    missionSelect.appendChild(historicalGroup);
                }
                
                // If no missions found
                if ((!allMissions.active || allMissions.active.length === 0) && 
                    (!allMissions.historical || allMissions.historical.length === 0)) {
                    missionSelect.innerHTML = '<option selected disabled>No missions available</option>';
                }
            } catch (error) {
                showToast(`Error loading missions: ${error.message}`, 'danger');
                missionSelect.innerHTML = `<option selected disabled>Error: ${error.message}</option>`;
            } finally {
                missionSpinner.style.display = 'none';
            }
        }

        missionSelect.addEventListener('change', async function() {
            selectedMissionId = this.value;
            updateReportGenerationVisibility(); // Update report generation visibility
            if (!selectedMissionId) {
                overviewFormContainer.style.display = 'none';
                if (missionMediaGallery) {
                    missionMediaGallery.innerHTML = '<div class="text-muted small">Select a mission to view uploaded media.</div>';
                }
                return;
            }

            missionSpinner.style.display = 'inline-block';
            saveStatusDiv.innerHTML = '';

            try {
                const missionInfo = await apiRequest(`/api/missions/${selectedMissionId}/info`, 'GET');

                editingMissionTitle.textContent = `Editing Overview for: ${selectedMissionId}`;
                
                // Reset form state (only once)
                overviewForm.reset();
                currentPlanContainer.style.display = 'none';
                documentUrlInput.value = '';
                
                // Get report container elements (declare once)
                const weeklyReportContainer = document.getElementById('weeklyReportContainer');
                const weeklyReportLink = document.getElementById('weeklyReportLink');
                const endOfMissionReportContainer = document.getElementById('endOfMissionReportContainer');
                const endOfMissionReportLink = document.getElementById('endOfMissionReportLink');
                const noReportsContainer = document.getElementById('noReportsContainer');
                
                // Reset report containers
                if (weeklyReportContainer) weeklyReportContainer.style.display = 'none';
                if (endOfMissionReportContainer) endOfMissionReportContainer.style.display = 'none';
                if (noReportsContainer) noReportsContainer.style.display = 'none';

                if (missionInfo.overview) {
                    commentsTextarea.value = missionInfo.overview.comments || '';
                    
                    // Display mission reports
                    
                    let hasReports = false;
                    
                    // Display weekly report
                    const weeklyReportFilename = document.getElementById('weeklyReportFilename');
                    if (missionInfo.overview.weekly_report_url) {
                        const weeklyFilename = missionInfo.overview.weekly_report_url.split('/').pop();
                        weeklyReportLink.href = missionInfo.overview.weekly_report_url;
                        if (weeklyReportFilename) {
                            weeklyReportFilename.textContent = weeklyFilename;
                        } else {
                            weeklyReportLink.textContent = weeklyFilename;
                        }
                        weeklyReportContainer.style.display = 'block';
                        hasReports = true;
                    } else {
                        weeklyReportContainer.style.display = 'none';
                    }
                    
                    // Display end of mission report
                    const endOfMissionReportFilename = document.getElementById('endOfMissionReportFilename');
                    if (missionInfo.overview.end_of_mission_report_url) {
                        const eomFilename = missionInfo.overview.end_of_mission_report_url.split('/').pop();
                        endOfMissionReportLink.href = missionInfo.overview.end_of_mission_report_url;
                        if (endOfMissionReportFilename) {
                            endOfMissionReportFilename.textContent = eomFilename;
                        } else {
                            endOfMissionReportLink.textContent = eomFilename;
                        }
                        endOfMissionReportContainer.style.display = 'block';
                        hasReports = true;
                    } else {
                        endOfMissionReportContainer.style.display = 'none';
                    }
                    
                    noReportsContainer.style.display = hasReports ? 'none' : 'block';
                    
                    // Display mission plan
                    if (missionInfo.overview.document_url) {
                        currentPlanLink.href = missionInfo.overview.document_url;
                        currentPlanLink.textContent = missionInfo.overview.document_url.split('/').pop();
                        currentPlanContainer.style.display = 'block';
                        documentUrlInput.value = missionInfo.overview.document_url; // Store current URL
                    }
                }
                
                // Display Sensor Tracker metadata
                const sensorTrackerContainer = document.getElementById('sensorTrackerMetadataContainer');
                const sensorTrackerPlaceholder = document.getElementById('sensorTrackerMetadataPlaceholder');
                
                if (missionInfo.sensor_tracker_deployment) {
                    const deployment = missionInfo.sensor_tracker_deployment;
                    const instruments = missionInfo.sensor_tracker_instruments || [];
                    
                    // Populate basic fields
                    document.getElementById('stTitle').textContent = deployment.title || '-';
                    
                    if (deployment.start_time) {
                        const startDate = new Date(deployment.start_time);
                        document.getElementById('stStart').textContent = startDate.toLocaleString('en-US', {
                            year: 'numeric',
                            month: '2-digit',
                            day: '2-digit',
                            hour: '2-digit',
                            minute: '2-digit',
                            timeZoneName: 'short'
                        });
                    } else {
                        document.getElementById('stStart').textContent = '-';
                    }
                    
                    if (deployment.end_time) {
                        const endDate = new Date(deployment.end_time);
                        document.getElementById('stEnd').textContent = endDate.toLocaleString('en-US', {
                            year: 'numeric',
                            month: '2-digit',
                            day: '2-digit',
                            hour: '2-digit',
                            minute: '2-digit',
                            timeZoneName: 'short'
                        });
                    } else {
                        document.getElementById('stEnd').textContent = '-';
                    }
                    
                    document.getElementById('stPlatform').textContent = deployment.platform_name || '-';
                    
                    if (deployment.data_repository_link) {
                        const repoLink = document.createElement('a');
                        repoLink.href = deployment.data_repository_link;
                        repoLink.target = '_blank';
                        repoLink.rel = 'noopener noreferrer';
                        repoLink.textContent = deployment.data_repository_link;
                        repoLink.className = 'text-break';
                        document.getElementById('stDataRepo').innerHTML = '';
                        document.getElementById('stDataRepo').appendChild(repoLink);
                    } else {
                        document.getElementById('stDataRepo').textContent = '-';
                    }
                    
                    if (deployment.deployment_comment) {
                        document.getElementById('stDescription').textContent = deployment.deployment_comment;
                    } else {
                        document.getElementById('stDescription').textContent = '-';
                    }
                    
                    // Group instruments
                    const platformInstruments = instruments.filter(inst => inst.is_platform_direct);
                    const scienceInstruments = instruments.filter(inst => inst.data_logger_type === 'science');
                    
                    // Display platform instruments
                    const platformContainer = document.getElementById('stPlatformInstrumentsContainer');
                    const platformList = document.getElementById('stPlatformInstruments');
                    if (platformInstruments.length > 0) {
                        platformList.innerHTML = '';
                        platformInstruments.forEach(inst => {
                            const li = document.createElement('li');
                            li.className = 'mb-1';
                            const name = inst.instrument_name || inst.instrument_identifier;
                            const serial = inst.instrument_serial ? ` (${inst.instrument_serial})` : '';
                            li.innerHTML = `<strong>${name}</strong>${serial}`;
                            platformList.appendChild(li);
                        });
                        platformContainer.style.display = 'block';
                    } else {
                        platformContainer.style.display = 'none';
                    }
                    
                    // Display science instruments
                    const scienceContainer = document.getElementById('stScienceInstrumentsContainer');
                    const scienceList = document.getElementById('stScienceInstruments');
                    if (scienceInstruments.length > 0) {
                        scienceList.innerHTML = '';
                        scienceInstruments.forEach(inst => {
                            const li = document.createElement('li');
                            li.className = 'mb-1';
                            const name = inst.instrument_name || inst.instrument_identifier;
                            const serial = inst.instrument_serial ? ` (${inst.instrument_serial})` : '';
                            li.innerHTML = `<strong>${name}</strong>${serial}`;
                            scienceList.appendChild(li);
                        });
                        scienceContainer.style.display = 'block';
                    } else {
                        scienceContainer.style.display = 'none';
                    }
                    
                    // Show instruments container if we have any instruments
                    const instrumentsContainer = document.getElementById('stInstrumentsContainer');
                    if (platformInstruments.length > 0 || scienceInstruments.length > 0) {
                        instrumentsContainer.style.display = 'block';
                    } else {
                        instrumentsContainer.style.display = 'none';
                    }
                    
                    // Show the metadata container
                    if (sensorTrackerContainer) sensorTrackerContainer.style.display = 'block';
                    if (sensorTrackerPlaceholder) sensorTrackerPlaceholder.style.display = 'none';
                } else {
                    // No Sensor Tracker data available
                    if (sensorTrackerContainer) sensorTrackerContainer.style.display = 'none';
                    if (sensorTrackerPlaceholder) sensorTrackerPlaceholder.style.display = 'block';
                }
                
                // Load sensor card configuration AFTER form reset
                // Use setTimeout to ensure DOM is fully updated
                setTimeout(() => {
                    loadSensorCardConfiguration(missionInfo);
                }, 10);
                
                // Show the form container
                if (overviewFormContainer) {
                    overviewFormContainer.style.display = 'block';
                } else {
                    console.error('overviewFormContainer not found!');
                }
                
                // Update report generation visibility after mission is loaded
                updateReportGenerationVisibility();

                // Load mission media after mission is loaded
                await loadMissionMedia();

            } catch (error) {
                saveStatusDiv.innerHTML = `<div class="alert alert-danger">Error loading data: ${error.message}</div>`;
                overviewFormContainer.style.display = 'none';
                updateReportGenerationVisibility(); // Hide report section on error too
            } finally {
                missionSpinner.style.display = 'none';
            }
        });

        function renderMediaEmpty(message) {
            if (!missionMediaGallery) return;
            missionMediaGallery.innerHTML = `<div class="text-muted small">${message}</div>`;
        }

        function renderMediaCard(media) {
            const operation = media.operation_type ? media.operation_type : 'Unspecified';
            const caption = media.caption ? media.caption : '';
            const safeCaption = escapeHtml(caption);
            const safeOperation = escapeHtml(operation);
            const safeUploadedBy = escapeHtml(media.uploaded_by_username || 'Unknown');
            const approvalStatus = media.approval_status || 'approved';
            const statusBadge = approvalStatus === 'pending'
                ? '<span class="badge bg-warning text-dark">Pending</span>'
                : approvalStatus === 'rejected'
                    ? '<span class="badge bg-danger">Rejected</span>'
                    : '<span class="badge bg-success">Approved</span>';
            const isVideo = media.media_type === 'video';
            const mediaPreview = isVideo
                ? `<video class="card-img-top" controls preload="metadata" style="height: 150px; object-fit: cover;">
                        <source src="${media.file_url}">
                   </video>`
                : `<a href="${media.file_url}" target="_blank" rel="noopener noreferrer">
                        <img src="${media.file_url}" class="card-img-top" alt="${safeCaption || 'Mission media'}" style="height: 150px; object-fit: cover;">
                   </a>`;

            return `
                <div class="col-md-4 mission-media-item" data-media-id="${media.id}">
                    <div class="card h-100">
                        ${mediaPreview}
                        <div class="card-body p-2">
                            <div class="small text-muted mb-1">${safeOperation.charAt(0).toUpperCase() + safeOperation.slice(1)} • ${safeUploadedBy}</div>
                            <div class="mb-1">${statusBadge}</div>
                            ${safeCaption ? `<div class="small">${safeCaption}</div>` : ''}
                            <div class="mt-2 d-flex gap-2">
                                <button type="button" class="btn btn-sm btn-outline-secondary media-edit-btn"
                                    data-media-id="${media.id}"
                                    data-caption="${safeCaption}"
                                    data-operation="${escapeHtml(media.operation_type || '')}"
                                    data-display-order="${media.display_order}"
                                    data-featured="${media.is_featured}">
                                    Edit
                                </button>
                                <button type="button" class="btn btn-sm btn-outline-danger media-delete-btn" data-media-id="${media.id}">
                                    Delete
                                </button>
                                ${approvalStatus === 'pending' ? `
                                    <button type="button" class="btn btn-sm btn-success media-approve-btn" data-media-id="${media.id}">Approve</button>
                                    <button type="button" class="btn btn-sm btn-outline-warning media-reject-btn" data-media-id="${media.id}">Reject</button>
                                ` : ''}
                            </div>
                        </div>
                    </div>
                </div>
            `;
        }

        async function loadMissionMedia() {
            if (!missionMediaGallery) return;
            if (!selectedMissionId) {
                renderMediaEmpty('Select a mission to view uploaded media.');
                return;
            }

            try {
                const mediaItems = await apiRequest(`/api/missions/${selectedMissionId}/media?include_pending=true`, 'GET');
                if (!mediaItems || mediaItems.length === 0) {
                    renderMediaEmpty('No media uploaded for this mission yet.');
                    return;
                }
                missionMediaGallery.innerHTML = mediaItems.map(renderMediaCard).join('');
            } catch (error) {
                renderMediaEmpty(`Failed to load media: ${error.message}`);
            }
        }

        if (mediaUploadBtn) {
            mediaUploadBtn.addEventListener('click', async function(event) {
                event.preventDefault();
                if (!selectedMissionId) return;

                const fileToUpload = mediaFileInput ? mediaFileInput.files[0] : null;
                if (!fileToUpload) {
                    showToast('Please select a media file to upload.', 'warning');
                    return;
                }

                mediaUploadBtn.disabled = true;
                if (mediaUploadSpinner) mediaUploadSpinner.style.display = 'inline';

                const formData = new FormData();
                formData.append('file', fileToUpload);

                const params = new URLSearchParams();
                if (mediaCaptionInput && mediaCaptionInput.value.trim()) {
                    params.append('caption', mediaCaptionInput.value.trim());
                }
                if (mediaOperationSelect && mediaOperationSelect.value) {
                    params.append('operation_type', mediaOperationSelect.value);
                }
                const queryString = params.toString();
                const uploadUrl = `/api/missions/${selectedMissionId}/media/upload${queryString ? `?${queryString}` : ''}`;

                try {
                    const uploadResponse = await fetchWithAuth(uploadUrl, {
                        method: 'POST',
                        body: formData
                    });
                    if (!uploadResponse.ok) {
                        const err = await uploadResponse.json();
                        throw new Error(err.detail || 'Media upload failed.');
                    }
                    showToast('Media uploaded successfully!', 'success');
                    if (mediaFileInput) mediaFileInput.value = '';
                    if (mediaCaptionInput) mediaCaptionInput.value = '';
                    if (mediaOperationSelect) mediaOperationSelect.value = '';
                    await loadMissionMedia();
                } catch (error) {
                    showToast(`Upload failed: ${error.message}`, 'danger');
                } finally {
                    mediaUploadBtn.disabled = false;
                    if (mediaUploadSpinner) mediaUploadSpinner.style.display = 'none';
                }
            });
        }

        document.body.addEventListener('click', async function(event) {
            const editBtn = event.target.closest('.media-edit-btn');
            if (editBtn) {
                event.preventDefault();
                if (!mediaEditModal) return;

                mediaEditId.value = editBtn.dataset.mediaId;
                mediaEditCaption.value = editBtn.dataset.caption || '';
                mediaEditOperation.value = editBtn.dataset.operation || '';
                mediaEditDisplayOrder.value = editBtn.dataset.displayOrder || 0;
                mediaEditFeatured.checked = editBtn.dataset.featured === 'true';
                mediaEditModal.show();
                return;
            }

            const deleteBtn = event.target.closest('.media-delete-btn');
            if (deleteBtn) {
                event.preventDefault();
                if (!selectedMissionId) return;
                const mediaId = deleteBtn.dataset.mediaId;
                if (!mediaId) return;
                if (!confirm('Delete this media item?')) return;

                try {
                    await apiRequest(`/api/missions/${selectedMissionId}/media/${mediaId}`, 'DELETE');
                    showToast('Media deleted.', 'success');
                    await loadMissionMedia();
                } catch (error) {
                    showToast(`Delete failed: ${error.message}`, 'danger');
                }
            }

            const approveBtn = event.target.closest('.media-approve-btn');
            if (approveBtn) {
                event.preventDefault();
                if (!selectedMissionId) return;
                const mediaId = approveBtn.dataset.mediaId;
                if (!mediaId) return;
                try {
                    await apiRequest(`/api/missions/${selectedMissionId}/media/${mediaId}/approve`, 'PUT');
                    showToast('Media approved.', 'success');
                    await loadMissionMedia();
                } catch (error) {
                    showToast(`Approval failed: ${error.message}`, 'danger');
                }
            }

            const rejectBtn = event.target.closest('.media-reject-btn');
            if (rejectBtn) {
                event.preventDefault();
                if (!selectedMissionId) return;
                const mediaId = rejectBtn.dataset.mediaId;
                if (!mediaId) return;
                if (!confirm('Reject this media item?')) return;
                try {
                    await apiRequest(`/api/missions/${selectedMissionId}/media/${mediaId}/reject`, 'PUT');
                    showToast('Media rejected.', 'success');
                    await loadMissionMedia();
                } catch (error) {
                    showToast(`Rejection failed: ${error.message}`, 'danger');
                }
            }
        });

        if (mediaEditSaveBtn) {
            mediaEditSaveBtn.addEventListener('click', async function() {
                if (!selectedMissionId || !mediaEditId.value) return;

                const payload = {
                    caption: mediaEditCaption.value.trim() || null,
                    operation_type: mediaEditOperation.value || null,
                    display_order: parseInt(mediaEditDisplayOrder.value || '0', 10),
                    is_featured: mediaEditFeatured.checked
                };

                try {
                    await apiRequest(`/api/missions/${selectedMissionId}/media/${mediaEditId.value}`, 'PUT', payload);
                    showToast('Media updated.', 'success');
                    if (mediaEditModal) mediaEditModal.hide();
                    await loadMissionMedia();
                } catch (error) {
                    showToast(`Update failed: ${error.message}`, 'danger');
                }
            });
        }

        removePlanBtn.addEventListener('click', function() {
            if (confirm('Are you sure you want to remove the current mission plan document? This will be saved on the next "Save Overview" click.')) {
                documentUrlInput.value = ''; // Clear the URL
                currentPlanContainer.style.display = 'none';
                // Optionally clear the file input if a file was selected but not yet uploaded
                documentUploadInput.value = '';
            }
        });

        overviewForm.addEventListener('submit', async function(event) {
            event.preventDefault();
            if (!selectedMissionId) return;

            saveBtn.disabled = true;
            saveStatusDiv.innerHTML = '<div class="alert alert-info">Saving...</div>';

            let fileUrl = documentUrlInput.value; // Start with the existing URL

            // Step 1: Handle file upload if a new file is selected
            const fileToUpload = documentUploadInput.files[0];
            if (fileToUpload) {
                saveStatusDiv.innerHTML = '<div class="alert alert-info">Uploading file...</div>';
                const formData = new FormData();
                formData.append('file', fileToUpload);

                try {
                    const uploadResponse = await fetchWithAuth(`/api/missions/${selectedMissionId}/overview/upload_plan`, {
                        method: 'POST',
                        body: formData
                    });

                    if (!uploadResponse.ok) {
                        const err = await uploadResponse.json();
                        throw new Error(err.detail || 'File upload failed.');
                    }
                    const uploadResult = await uploadResponse.json();
                    fileUrl = uploadResult.file_url; // Update fileUrl with the new URL
                    saveStatusDiv.innerHTML = '<div class="alert alert-info">File uploaded. Saving overview...</div>';

                } catch (error) {
                    saveStatusDiv.innerHTML = `<div class="alert alert-danger">Upload failed: ${error.message}</div>`;
                    saveBtn.disabled = false;
                    return; // Stop if upload fails
                }
            }

            // Step 2: Save the overview with the (potentially new) URL, comments, and sensor cards
            const enabledSensorCards = getEnabledSensorCards();
            
            const payload = {
                document_url: fileUrl || null, // Use the final URL, or null if removed
                comments: commentsTextarea.value.trim() || null,
                enabled_sensor_cards: enabledSensorCards.length > 0 ? JSON.stringify(enabledSensorCards) : null
            };

            try {
                const savedOverview = await apiRequest(`/api/missions/${selectedMissionId}/overview`, 'PUT', payload);
                showToast('Overview saved successfully!', 'success');
                saveStatusDiv.innerHTML = '<div class="alert alert-success">Overview saved successfully!</div>';
                
                // Update the UI with the new state without a full reload
                documentUploadInput.value = ''; // Clear the file input
                if (savedOverview && savedOverview.document_url) {
                    currentPlanLink.href = savedOverview.document_url;
                    currentPlanLink.textContent = savedOverview.document_url.split('/').pop();
                    currentPlanContainer.style.display = 'block';
                    documentUrlInput.value = savedOverview.document_url;
                } else {
                    currentPlanContainer.style.display = 'none';
                    documentUrlInput.value = '';
                }

            } catch (error) {
                showToast(`Save failed: ${error.message}`, 'danger');
                saveStatusDiv.innerHTML = `<div class="alert alert-danger">Save failed: ${error.message}</div>`;
            } finally {
                saveBtn.disabled = false;
            }
        });

        // Initial load
        loadMissions();
        
        // Initial visibility
        updateReportGenerationVisibility();
    }
});