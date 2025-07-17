document.addEventListener('DOMContentLoaded', function() {
    if (!checkAuth()) return;

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

        let selectedMissionId = null;

        async function loadMissions() {
            missionSpinner.style.display = 'inline-block';
            try {
                const response = await fetchWithAuth('/api/available_missions');
                if (!response.ok) throw new Error('Failed to load missions.');
                const missions = await response.json();

                missionSelect.innerHTML = '<option selected disabled>-- Select a Mission --</option>';
                missions.forEach(missionId => {
                    const option = document.createElement('option');
                    option.value = missionId;
                    option.textContent = missionId;
                    missionSelect.appendChild(option);
                });
            } catch (error) {
                missionSelect.innerHTML = `<option selected disabled>Error: ${error.message}</option>`;
            } finally {
                missionSpinner.style.display = 'none';
            }
        }

        missionSelect.addEventListener('change', async function() {
            selectedMissionId = this.value;
            if (!selectedMissionId) {
                overviewFormContainer.style.display = 'none';
                return;
            }

            missionSpinner.style.display = 'inline-block';
            saveStatusDiv.innerHTML = '';
            overviewForm.reset();

            try {
                const response = await fetchWithAuth(`/api/missions/${selectedMissionId}/info`);
                if (!response.ok) throw new Error('Failed to fetch mission overview.');
                const missionInfo = await response.json();

                editingMissionTitle.textContent = `Editing Overview for: ${selectedMissionId}`;
                
                // Reset form state
                overviewForm.reset();
                currentPlanContainer.style.display = 'none';
                documentUrlInput.value = '';

                if (missionInfo.overview) {
                    commentsTextarea.value = missionInfo.overview.comments || '';
                    if (missionInfo.overview.document_url) {
                        currentPlanLink.href = missionInfo.overview.document_url;
                        currentPlanLink.textContent = missionInfo.overview.document_url.split('/').pop();
                        currentPlanContainer.style.display = 'block';
                        documentUrlInput.value = missionInfo.overview.document_url; // Store current URL
                    }
                }
                overviewFormContainer.style.display = 'block';

            } catch (error) {
                saveStatusDiv.innerHTML = `<div class="alert alert-danger">Error loading data: ${error.message}</div>`;
                overviewFormContainer.style.display = 'none';
            } finally {
                missionSpinner.style.display = 'none';
            }
        });

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

            // Step 2: Save the overview with the (potentially new) URL and comments
            const payload = {
                document_url: fileUrl || null, // Use the final URL, or null if removed
                comments: commentsTextarea.value.trim() || null
            };

            try {
                const response = await fetchWithAuth(`/api/missions/${selectedMissionId}/overview`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                if (!response.ok) {
                    const err = await response.json();
                    throw new Error(err.detail || 'Failed to save overview.');
                }
                
                const savedOverview = await response.json();

                saveStatusDiv.innerHTML = '<div class="alert alert-success">Overview saved successfully!</div>';
                
                // Update the UI with the new state without a full reload
                documentUploadInput.value = ''; // Clear the file input
                if (savedOverview.document_url) {
                    currentPlanLink.href = savedOverview.document_url;
                    currentPlanLink.textContent = savedOverview.document_url.split('/').pop();
                    currentPlanContainer.style.display = 'block';
                    documentUrlInput.value = savedOverview.document_url;
                } else {
                    currentPlanContainer.style.display = 'none';
                    documentUrlInput.value = '';
                }

            } catch (error) {
                saveStatusDiv.innerHTML = `<div class="alert alert-danger">Save failed: ${error.message}</div>`;
            } finally {
                saveBtn.disabled = false;
            }
        });

        // Initial load
        loadMissions();
    }
});