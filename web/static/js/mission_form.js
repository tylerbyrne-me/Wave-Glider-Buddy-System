document.addEventListener('DOMContentLoaded', function () {
    if (!checkAuth()) { // from auth.js
        return;
    }

    const missionId = document.body.dataset.missionId;
    const formType = document.body.dataset.formType;
    const username = document.body.dataset.username;

    const formTitleElement = document.getElementById('formTitle');
    const formDescriptionElement = document.getElementById('formDescription');
    const formSectionsContainer = document.getElementById('formSectionsContainer');
    const missionReportForm = document.getElementById('missionReportForm');
    const submissionStatusDiv = document.getElementById('submissionStatus');
    const formSpinner = document.getElementById('formSpinner');

    async function fetchAndRenderFormSchema() {
        formSpinner.style.display = 'block';
        missionReportForm.style.display = 'none';
        try {
            const response = await fetchWithAuth(`/api/forms/${missionId}/template/${formType}`);
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || `Failed to load form template (Status: ${response.status})`);
            }
            const schema = await response.json();

            formTitleElement.textContent = schema.title || 'Mission Form';
            if (schema.description) {
                formDescriptionElement.textContent = schema.description;
            }

            formSectionsContainer.innerHTML = ''; // Clear previous content

            schema.sections.forEach(section => {
                const sectionDiv = document.createElement('div');
                sectionDiv.classList.add('form-section');
                sectionDiv.innerHTML = `<h3>${section.title}</h3>`;

                section.items.forEach(item => {
                    const itemDiv = document.createElement('div');
                    itemDiv.classList.add('form-item', 'mb-3');
                    itemDiv.dataset.itemId = item.id;

                    let inputHtml = '';
                    switch (item.item_type) {
                        case 'checkbox':
                            inputHtml = `<div class="form-check mt-2">
                                           <input class="form-check-input" type="checkbox" id="${item.id}" name="${item.id}" ${item.is_checked ? 'checked' : ''} ${item.required ? 'required' : ''}>
                                           <label class="form-check-label" for="${item.id}">Check if complete/verified</label>
                                         </div>`;
                            break;
                        case 'text_input':
                            inputHtml = `<input type="text" class="form-control" id="${item.id}" name="${item.id}" value="${item.value || ''}" placeholder="${item.placeholder || ''}" ${item.required ? 'required' : ''}>`;
                            break;
                        case 'text_area':
                            inputHtml = `<textarea class="form-control" id="${item.id}" name="${item.id}" rows="2" placeholder="${item.placeholder || ''}" ${item.required ? 'required' : ''}>${item.value || ''}</textarea>`; // Adjusted rows
                            break;
                        case 'autofilled_value':
                            inputHtml = `<div class="autofilled-value" id="${item.id}">${item.value || 'N/A'}</div>`;
                            break;
                        case 'static_text':
                            inputHtml = `<p class="static-text mb-0" id="${item.id}">${item.value || ''}</p>`; // mb-0 to align better
                            break;
                        case 'dropdown':
                            inputHtml = `<select class="form-select" id="${item.id}" name="${item.id}" ${item.required ? 'required' : ''}>`;
                            if (item.placeholder) { // Optional: Add a disabled placeholder option
                                inputHtml += `<option value="" disabled ${!item.value ? 'selected' : ''}>${item.placeholder}</option>`;
                            }
                            item.options.forEach(opt => {
                                inputHtml += `<option value="${opt}" ${item.value === opt ? 'selected' : ''}>${opt}</option>`;
                            });
                            inputHtml += `</select>`;
                            break;
                    }

                    // New 4-column layout using Bootstrap grid
                    itemDiv.innerHTML = `
                        <div class="row align-items-center">
                            <div class="col-md-3">
                                <label for="${item.id}" class="form-label mb-0">${item.label}${item.required ? '<span class="text-danger">*</span>' : ''}</label>
                            </div>
                            <div class="col-md-4">
                                ${inputHtml}
                            </div>
                            <div class="col-md-3">
                                <textarea class="form-control form-control-sm" name="${item.id}_comment" rows="1" placeholder="Comment..."></textarea>
                            </div>
                            <div class="col-md-2">
                                ${ (item.item_type === 'autofilled_value' || item.item_type === 'static_text') ?
                                `
                                <div class="form-check">
                                    <input class="form-check-input" type="checkbox" id="${item.id}_verified" name="${item.id}_verified" value="true" ${item.is_verified ? 'checked' : ''}>
                                    <label class="form-check-label" for="${item.id}_verified">
                                        Verified
                                    </label>
                                </div>
                                ` :
                                '' // Render nothing if not autofilled or static text
                                }
                            </div>
                        </div>
                    `;
                    sectionDiv.appendChild(itemDiv);
                });

                if (section.section_comment) {
                    sectionDiv.innerHTML += `<div class="mt-3">
                                                <label for="${section.id}_comment" class="form-label">Section Notes:</label>
                                                <textarea class="form-control" id="${section.id}_comment" name="${section.id}_comment" rows="2" placeholder="Overall notes for this section...">${section.section_comment || ''}</textarea>
                                             </div>`;
                }
                formSectionsContainer.appendChild(sectionDiv);
            });
            missionReportForm.style.display = 'block';

            // --- Add event listener for dynamic navigation mode fields ---
            const navModeSelect = document.getElementById('navigation_mode_val');
            const targetWaypointInput = document.getElementById('target_waypoint_val');
            const targetWaypointLabel = document.querySelector('label[for="target_waypoint_val"]');
            const waypointDetailsInput = document.getElementById('waypoint_details_val');
            const waypointDetailsLabel = document.querySelector('label[for="waypoint_details_val"]');

            function updateNavFields(selectedMode) {
                if (!targetWaypointInput || !targetWaypointLabel || !waypointDetailsInput || !waypointDetailsLabel) {
                    console.warn("Navigation related form elements not found for dynamic updates.");
                    return;
                }

                switch (selectedMode) {
                    case 'FSC': // Follow Scheduled Course
                        targetWaypointLabel.textContent = 'Target Waypoint';
                        targetWaypointInput.placeholder = 'Enter target waypoint';
                        waypointDetailsLabel.textContent = 'Waypoint Start to Finish Details';
                        waypointDetailsInput.placeholder = 'e.g., 1 - 5';
                        break;
                    case 'FFB': // Follow Fixed Bearing
                        targetWaypointLabel.textContent = 'Bearing';
                        targetWaypointInput.placeholder = 'Enter bearing (e.g., 180°)';
                        waypointDetailsLabel.textContent = 'Set Distance';
                        waypointDetailsInput.placeholder = 'Enter distance (e.g., 10km)';
                        break;
                    case 'FFH': // Follow Fixed Heading
                        targetWaypointLabel.textContent = 'Heading';
                        targetWaypointInput.placeholder = 'Enter heading (e.g., 270°)';
                        waypointDetailsLabel.textContent = 'Set Distance';
                        waypointDetailsInput.placeholder = 'Enter distance (e.g., 5NM)';
                        break;
                    case 'WC': // Waypoint Circle
                        targetWaypointLabel.textContent = 'Waypoint';
                        targetWaypointInput.placeholder = 'Enter center waypoint';
                        waypointDetailsLabel.textContent = 'Circle Radius';
                        waypointDetailsInput.placeholder = 'Enter radius (e.g., 500m)';
                        break;
                    case 'FCC': // Follow Custom Course
                        targetWaypointLabel.textContent = 'Custom Course Name';
                        targetWaypointInput.placeholder = 'Enter course name';
                        waypointDetailsLabel.textContent = 'Start Waypoint';
                        waypointDetailsInput.placeholder = 'Enter starting waypoint for course';
                        break;
                    default:
                        // Default to FSC or a generic state if mode is unknown
                        targetWaypointLabel.textContent = 'Target Waypoint / Parameter 1';
                        targetWaypointInput.placeholder = 'Enter value';
                        waypointDetailsLabel.textContent = 'Details / Parameter 2';
                        waypointDetailsInput.placeholder = 'Enter value';
                        break;
                }
            }

            if (navModeSelect) {
                navModeSelect.addEventListener('change', function() {
                    updateNavFields(this.value);
                });
                // Call initially to set fields based on default/loaded value
                updateNavFields(navModeSelect.value);
            }
            // --- End dynamic navigation mode fields ---

        } catch (error) {
            console.error('Error fetching or rendering form schema:', error);
            formTitleElement.textContent = 'Error Loading Form';
            formDescriptionElement.textContent = error.message;
            submissionStatusDiv.innerHTML = `<div class="alert alert-danger">${error.message}</div>`;
        } finally {
            formSpinner.style.display = 'none';
        }
    }

    missionReportForm.addEventListener('submit', async function (event) {
        event.preventDefault();
        submissionStatusDiv.innerHTML = '<div class="alert alert-info">Submitting form...</div>';

        const formData = new FormData(missionReportForm);
        const sectionsData = [];

        // Reconstruct sections and items from the form
        document.querySelectorAll('.form-section').forEach(sectionElem => {
            const sectionTitle = sectionElem.querySelector('h3').textContent;
            const sectionId = sectionElem.id || sectionTitle.toLowerCase().replace(/\s+/g, '_'); // Fallback id
            const sectionCommentElem = sectionElem.querySelector(`textarea[name="${sectionId}_comment"]`);
            const section = {
                id: sectionId,
                title: sectionTitle,
                items: [],
                section_comment: sectionCommentElem ? sectionCommentElem.value.trim() : null
            };

            sectionElem.querySelectorAll('.form-item').forEach(itemElem => {
                const itemId = itemElem.dataset.itemId;
                const label = itemElem.querySelector('label[for="' + itemId + '"]').textContent.replace('*','').trim();
                const inputElem = missionReportForm.elements[itemId];
                const commentElem = missionReportForm.elements[`${itemId}_comment`];
                const verifiedElem = missionReportForm.elements[`${itemId}_verified`];

                const formItem = {
                    id: itemId,
                    label: label,
                    is_verified: verifiedElem ? verifiedElem.checked : null,
                    item_type: '', // Will be set by backend schema, not strictly needed for submission if backend re-validates
                    value: null,
                    is_checked: null,
                    comment: commentElem ? commentElem.value.trim() : null
                };

                if (inputElem) {
                    if (inputElem.type === 'checkbox') {
                        formItem.is_checked = inputElem.checked;
                        formItem.item_type = 'checkbox';
                    } else if (inputElem.type === 'textarea' || inputElem.type === 'text' || inputElem.tagName.toLowerCase() === 'select') {
                        formItem.value = inputElem.value.trim();
                        formItem.item_type = inputElem.type === 'textarea' ? 'text_area' : 'text_input';
                    }
                } else { // For autofilled or static, grab the displayed value if needed, or rely on schema
                    const displayElem = document.getElementById(itemId);
                    if (displayElem && (displayElem.classList.contains('autofilled-value') || displayElem.classList.contains('static-text'))) {
                        formItem.value = displayElem.textContent;
                        formItem.item_type = displayElem.classList.contains('autofilled-value') ? 'autofilled_value' : 'static_text';
                    }
                }
                section.items.push(formItem);
            });
            sectionsData.push(section);
        });

        const submissionPayload = {
            mission_id: missionId,
            form_type: formType,
            form_title: formTitleElement.textContent,
            sections_data: sectionsData
        };

        try {
            const response = await fetchWithAuth(`/api/forms/${missionId}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(submissionPayload)
            });
            const result = await response.json();
            if (response.ok) {
                // Ensure the timestamp string from the server is parsed as UTC.
                const submissionTimestampStr = result.submission_timestamp.endsWith('Z') ? result.submission_timestamp : result.submission_timestamp + 'Z';
                const submissionTime = new Date(submissionTimestampStr);
                // Using en-GB for a common 24-hour format, and explicitly stating UTC
                const formattedTime = submissionTime.toLocaleString('en-GB', { timeZone: 'UTC', dateStyle: 'medium', timeStyle: 'medium', hour12: false }) + ' UTC';
                submissionStatusDiv.innerHTML = `<div class="alert alert-success">Form submitted successfully at ${formattedTime} by ${result.submitted_by_username}!</div>`;
                missionReportForm.reset(); // Optionally reset the form
                // Close the tab after a short delay to allow the user to see the success message
                setTimeout(() => { window.close(); }, 1500); 
            } else {
                submissionStatusDiv.innerHTML = `<div class="alert alert-danger">Submission failed: ${result.detail || 'Unknown error'}</div>`;
            }
        } catch (error) {
            console.error('Error submitting form:', error);
            submissionStatusDiv.innerHTML = `<div class="alert alert-danger">Network error or unexpected issue during submission.</div>`;
        }
    });

    // Initial load
    fetchAndRenderFormSchema();
});