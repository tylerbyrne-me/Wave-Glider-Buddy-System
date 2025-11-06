/**
 * @file view_forms.js
 * @description View and display submitted forms for missions
 */

import { checkAuth, logout } from '/static/js/auth.js';
import { apiRequest, showToast } from '/static/js/api.js';

document.addEventListener('DOMContentLoaded', async function () {
    if (!await checkAuth()) {
        // If checkAuth redirects, this script might not fully execute, which is fine.
        return;
    }

    const formsTableBody = document.getElementById('formsTableBody');
    const formsSpinner = document.getElementById('formsSpinner');
    const formsTableContainer = document.getElementById('formsTableContainer');
    const noFormsMessage = document.getElementById('noFormsMessage');
    const formDetailsModal = new bootstrap.Modal(document.getElementById('formDetailsModal'));
    const formDetailsContentElement = document.getElementById('formDetailsContent'); // Updated ID
    const backToDashboardBtn = document.getElementById('backToDashboardBtn');
    const userRole = document.body.dataset.userRole; // Get user role

    const urlParams = new URLSearchParams(window.location.search);
    const formIdToAutoOpen = urlParams.get('form_id');

    /**
     * Fetches and displays all submitted forms
     */
    async function fetchAndDisplayForms() {
        formsSpinner.style.display = 'block';
        formsTableContainer.style.display = 'none';
        noFormsMessage.style.display = 'none';

        try {
            const forms = await apiRequest('/api/forms/all', 'GET');

            formsTableBody.innerHTML = ''; // Clear existing rows

            if (forms.length === 0) {
                noFormsMessage.style.display = 'block';
                formsTableContainer.style.display = 'block'; // Ensure container is visible to show the message
                
            } else {
                const picHandoffHighlightedForMission = {}; // Object to track missions for PIC Handoff highlight

                forms.forEach((form, index) => { // Added index
                    const row = formsTableBody.insertRow();

                    // General highlight for the absolute most recent form if user is a pilot
                    if (userRole === 'pilot' && index === 0 && !formIdToAutoOpen) { // Highlight if pilot and first (most recent) form, and not auto-opening
                        row.classList.add('table-info'); // Light blue highlight
                    }

                    // Specific highlight for the most recent "PIC Handoff Checklist" per mission_id
                    // This applies to any user viewing the forms.
                    if (form.form_type === "pic_handoff_checklist") {
                        if (!picHandoffHighlightedForMission[form.mission_id]) {
                            row.classList.add('pic-handoff-highlight'); // New custom class for light blue highlight
                            picHandoffHighlightedForMission[form.mission_id] = true;
                        }
                    }

                    row.insertCell().textContent = form.mission_id;
                    row.insertCell().textContent = form.form_type;
                    row.insertCell().textContent = form.form_title;
                    row.insertCell().textContent = form.submitted_by_username;
                    // Ensure the timestamp string is parsed as UTC by appending 'Z' if it's not already in ISO format.
                    // This prevents the browser from interpreting a naive timestamp (e.g., "YYYY-MM-DD HH:MM:SS") as local time.
                    const submissionTimestampStr = form.submission_timestamp.endsWith('Z') ? form.submission_timestamp : form.submission_timestamp + 'Z';
                    const submissionDate = new Date(submissionTimestampStr);
                    // Standardize UTC time formatting for consistency and robustness.
                    const datePart = submissionDate.toLocaleDateString('en-US', {
                        year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC'
                    });
                    const timePart = submissionDate.toLocaleTimeString('en-GB', {
                        hour: '2-digit', minute: '2-digit', timeZone: 'UTC'
                    });
                    // Combine parts to match the original format "Mon Day Year HH:MM UTC"
                    row.insertCell().textContent = `${datePart.replace(',', '')} ${timePart} UTC`;
                    
                    const actionsCell = row.insertCell();
                    const viewButton = document.createElement('button');
                    viewButton.classList.add('btn', 'btn-sm', 'btn-outline-info');
                    viewButton.textContent = 'View Details';
                    viewButton.onclick = () => {
                        document.getElementById('formDetailsModalLabel').textContent = `Details for: ${form.form_title} (${form.form_type})`;
                        renderFormDetailsInModal(form);
                        formDetailsModal.show();
                    };
                    actionsCell.appendChild(viewButton);

                    // If this form is the one to auto-open, click its view button
                    if (formIdToAutoOpen && form.id.toString() === formIdToAutoOpen) {
                        viewButton.click();
                    }
                });
                formsTableContainer.style.display = 'block';
            }
        } catch (error) {
            showToast(`Error loading forms: ${error.message}`, 'danger');
            formsTableBody.innerHTML = `<tr><td colspan="6" class="text-center text-danger">Error loading forms: ${error.message}</td></tr>`;
            formsTableContainer.style.display = 'block'; // Show table container to display error
            noFormsMessage.style.display = 'none';
        } finally {
            formsSpinner.style.display = 'none';
        }
    }

    /**
     * Renders form details in the modal
     * @param {Object} form - The form object to render
     */
    function renderFormDetailsInModal(form) {
        formDetailsContentElement.innerHTML = ''; // Clear previous content

        if (form.sections_data && form.sections_data.length > 0) {
            form.sections_data.forEach(section => {
                const sectionDiv = document.createElement('div');
                sectionDiv.classList.add('mb-4'); // Spacing between sections

                const sectionTitle = document.createElement('h5');
                sectionTitle.textContent = section.title;
                sectionDiv.appendChild(sectionTitle);

                if (section.section_comment) {
                    const sectionCommentP = document.createElement('p');
                    sectionCommentP.classList.add('text-muted', 'fst-italic', 'ms-2');
                    sectionCommentP.textContent = `Section Notes: ${section.section_comment}`;
                    sectionDiv.appendChild(sectionCommentP);
                }

                const itemList = document.createElement('ul');
                itemList.classList.add('list-group', 'list-group-flush');

                section.items.forEach(item => {
                    const listItem = document.createElement('li');
                    listItem.classList.add('list-group-item', 'bg-transparent'); // bg-transparent for dark mode
                    
                    let itemValueDisplay = '';
                    if (item.item_type === 'checkbox') {
                        itemValueDisplay = item.is_checked ? 'Checked' : 'Unchecked';
                    } else if (item.item_type === 'autofilled_value' || item.item_type === 'static_text') {
                        itemValueDisplay = item.value || 'N/A';
                    } else { // text_input, text_area
                        itemValueDisplay = item.value || '(empty)';
                    }
                    listItem.innerHTML = `<strong>${item.label}:</strong> ${itemValueDisplay}`;
                    if (item.comment) {
                        listItem.innerHTML += `<br><small class="text-info ms-3"><em>Comment: ${item.comment}</em></small>`;
                    }
                    itemList.appendChild(listItem);
                });
                sectionDiv.appendChild(itemList);
                formDetailsContentElement.appendChild(sectionDiv);
            });
        } else {
            formDetailsContentElement.textContent = 'No detailed section data available for this form.';
        }
    }

    // Initial load
    fetchAndDisplayForms();

    // Event listener for the "Close Page" button
    if (backToDashboardBtn) { // Keep close button as requested
        backToDashboardBtn.addEventListener('click', function(event) {
            event.preventDefault(); // Prevent default anchor behavior
            window.close();
        });
    }
});