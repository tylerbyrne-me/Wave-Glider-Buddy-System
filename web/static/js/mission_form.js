/**
 * @file mission_form.js
 * @description Mission form rendering and submission
 */

import { checkAuth } from '/static/js/auth.js';
import { apiRequest, showToast } from '/static/js/api.js';

document.addEventListener('DOMContentLoaded', async function () {
    if (!await checkAuth()) {
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

    /**
     * Fetch and render the form schema
     */
    async function fetchAndRenderFormSchema() {
        formSpinner.style.display = 'block';
        missionReportForm.style.display = 'none';
        try {
            const schema = await apiRequest(`/api/forms/${missionId}/template/${formType}`, 'GET');

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

                    let labelContent = `${item.label}${item.required ? '<span class="text-danger">*</span>' : ''}`;
                    let inputHtml = '';
                    switch (item.item_type) {
                        case 'checkbox':
                            inputHtml = `<div class="form-check mt-2">
                                           <input class="form-check-input" type="checkbox" id="${item.id}" name="${item.id}" ${item.is_checked ? 'checked' : ''} ${item.required ? 'required' : ''}>
                                           <label class="form-check-label" for="${item.id}">Check if complete/verified</label>
                                         </div>`;
                            break;
                        case 'text_input': {
                            const textHint = (item.hint || '').replace(/"/g, '&quot;');
                            const textTitleAttr = textHint ? ` title="${textHint}"` : '';
                            const textHintClass = textHint ? ' form-control--has-tooltip' : '';
                            inputHtml = `<input type="text" class="form-control${textHintClass}" id="${item.id}" name="${item.id}" value="${item.value || ''}" placeholder="${item.placeholder || ''}"${textTitleAttr} ${item.required ? 'required' : ''}>`;
                            break;
                        }
                        case 'text_area':
                            inputHtml = `<textarea class="form-control" id="${item.id}" name="${item.id}" rows="2" placeholder="${item.placeholder || ''}" ${item.required ? 'required' : ''}>${item.value || ''}</textarea>`; // Adjusted rows
                            break;
                        case 'autofilled_value': {
                            const hint = (item.hint || '').replace(/"/g, '&quot;');
                            const titleAttr = hint ? ` title="${hint}"` : '';
                            const hintClass = hint ? ' autofilled-value--has-tooltip' : '';
                            inputHtml = `<div class="autofilled-value${hintClass}" id="${item.id}"${titleAttr}>${item.value || 'N/A'}</div>`;
                            break;
                        }
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
                        case 'sensor_status': {
                            let lastTimeStr = 'N/A';
                            let dropdownValue = 'Off';
                            if (item.value) {
                                try {
                                    const parsed = typeof item.value === 'string' ? JSON.parse(item.value) : item.value;
                                    lastTimeStr = parsed.last_time_str ?? 'N/A';
                                    dropdownValue = (parsed.value === 'On' || parsed.default_on) ? 'On' : 'Off';
                                } catch (_) { /* keep defaults */ }
                            }
                            labelContent = `${item.label}${item.required ? '<span class="text-danger">*</span>' : ''}<br><small class="text-muted">Last data: ${lastTimeStr}</small>`;
                            inputHtml = `<select class="form-select" id="${item.id}" name="${item.id}">
                                <option value="On" ${dropdownValue === 'On' ? 'selected' : ''}>On</option>
                                <option value="Off" ${dropdownValue === 'Off' ? 'selected' : ''}>Off</option>
                            </select>`;
                            break;
                        }
                    }

                    // When item has a hint, append a visible "?" icon next to the label for tooltip
                    if (item.hint) {
                        const hintEscaped = (item.hint || '').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
                        labelContent += ` <span class="sampling-hint-icon" title="${hintEscaped}" aria-label="Help">?</span>`;
                    }

                    // Omit per-item "Comment..." for text_area (e.g. User Comments) to avoid comment-for-comment
                    const showItemComment = item.item_type !== 'text_area';
                    // New 4-column layout using Bootstrap grid
                    itemDiv.innerHTML = `
                        <div class="row align-items-center">
                            <div class="col-md-3">
                                <label for="${item.id}" class="form-label mb-0">${labelContent}</label>
                            </div>
                            <div class="col-md-4">
                                ${inputHtml}
                            </div>
                            <div class="col-md-3">
                                ${showItemComment ? `<textarea class="form-control form-control-sm" name="${item.id}_comment" rows="1" placeholder="Comment..."></textarea>` : ''}
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

            // Refresh data button: re-fetch template and update only autopopulated fields (keeps pilot's inputs/comments/verified state)
            const refreshFormDataBtn = document.getElementById('refreshFormDataBtn');
            if (refreshFormDataBtn) {
                refreshFormDataBtn.addEventListener('click', async function () {
                    const btn = this;
                    const originalText = btn.textContent;
                    btn.disabled = true;
                    btn.textContent = 'Refreshing…';
                    try {
                        const schema = await apiRequest(`/api/forms/${missionId}/template/${formType}`, 'GET');
                        let updated = 0;
                        for (const section of schema.sections || []) {
                            for (const item of section.items || []) {
                                const itemType = item.item_type || '';
                                const id = item.id;
                                if (!id) continue;
                                if (itemType === 'autofilled_value' || itemType === 'static_text') {
                                    const el = document.getElementById(id);
                                    if (el && (el.classList.contains('autofilled-value') || el.classList.contains('static-text'))) {
                                        el.textContent = item.value != null && item.value !== '' ? item.value : 'N/A';
                                        updated++;
                                    }
                                } else if (itemType === 'sensor_status') {
                                    let lastTimeStr = 'N/A';
                                    if (item.value) {
                                        try {
                                            const parsed = typeof item.value === 'string' ? JSON.parse(item.value) : item.value;
                                            lastTimeStr = parsed.last_time_str ?? 'N/A';
                                        } catch (_) { /* ignore */ }
                                    }
                                    const itemRow = document.querySelector(`.form-item[data-item-id="${id}"]`);
                                    const small = itemRow?.querySelector('label small.text-muted');
                                    if (small) {
                                        small.textContent = `Last data: ${lastTimeStr}`;
                                        updated++;
                                    }
                                }
                            }
                        }
                        showToast(updated > 0 ? 'Autopopulated data refreshed.' : 'No autopopulated fields to update.', 'success');
                    } catch (err) {
                        showToast(`Refresh failed: ${err.message}`, 'danger');
                    } finally {
                        btn.disabled = false;
                        btn.textContent = originalText;
                    }
                });
            }

        } catch (error) {
            showToast(`Error loading form: ${error.message}`, 'danger');
            formTitleElement.textContent = 'Error Loading Form';
            formDescriptionElement.textContent = error.message;
            submissionStatusDiv.innerHTML = `<div class="alert alert-danger">${error.message}</div>`;
        } finally {
            formSpinner.style.display = 'none';
        }
    }

    const unverifiedModalEl = document.getElementById('unverifiedConfirmModal');
    const unverifiedModal = unverifiedModalEl ? new bootstrap.Modal(unverifiedModalEl) : null;
    const unverifiedSubmitBtn = document.getElementById('unverifiedSubmitBtn');
    const unverifiedCancelBtn = document.getElementById('unverifiedCancelSubmissionBtn');

    async function performSubmission() {
        submissionStatusDiv.innerHTML = '<div class="alert alert-info">Submitting form...</div>';

        const sectionsData = [];
        document.querySelectorAll('.form-section').forEach(sectionElem => {
            const sectionTitle = sectionElem.querySelector('h3').textContent;
            const sectionId = sectionElem.id || sectionTitle.toLowerCase().replace(/\s+/g, '_');
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
                    item_type: '',
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
                } else {
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
            const result = await apiRequest(`/api/forms/${missionId}`, 'POST', submissionPayload);
            const submissionTimestampStr = result.submission_timestamp.endsWith('Z') ? result.submission_timestamp : result.submission_timestamp + 'Z';
            const submissionTime = new Date(submissionTimestampStr);
            const formattedTime = submissionTime.toLocaleString('en-GB', { timeZone: 'UTC', dateStyle: 'medium', timeStyle: 'medium', hour12: false }) + ' UTC';
            showToast('Form submitted successfully!', 'success');
            submissionStatusDiv.innerHTML = `<div class="alert alert-success">Form submitted successfully at ${formattedTime} by ${result.submitted_by_username}!</div>`;
            missionReportForm.reset();
            setTimeout(() => { window.close(); }, 1500);
        } catch (error) {
            showToast(`Error submitting form: ${error.message}`, 'danger');
            submissionStatusDiv.innerHTML = `<div class="alert alert-danger">Submission failed: ${error.message}</div>`;
        }
    }

    missionReportForm.addEventListener('submit', async function (event) {
        event.preventDefault();

        const verifiedInputs = missionReportForm.querySelectorAll('input[name$="_verified"]');
        const hasUnverified = Array.from(verifiedInputs).some(el => el.type === 'checkbox' && !el.checked);
        if (hasUnverified) {
            if (unverifiedModal && unverifiedSubmitBtn && unverifiedCancelBtn) {
                unverifiedSubmitBtn.onclick = () => {
                    unverifiedSubmitBtn.onclick = null;
                    unverifiedCancelBtn.onclick = null;
                    unverifiedModal.hide();
                    performSubmission();
                };
                unverifiedCancelBtn.onclick = () => {
                    unverifiedSubmitBtn.onclick = null;
                    unverifiedCancelBtn.onclick = null;
                    unverifiedModal.hide();
                };
                unverifiedModal.show();
                return;
            }
            if (!window.confirm('Some entries have not been verified. Submit anyway? If information could not be verified, we recommend adding a comment below explaining why it is wrong or missing.')) {
                return;
            }
        }

        await performSubmission();
    });

    // Initial load
    fetchAndRenderFormSchema();
});