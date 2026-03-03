/**
 * @file my_pic_handoffs.js
 * @description Display user's PIC handoff submissions
 */

import { checkAuth, logout } from "/static/js/auth.js";
import { apiRequest, showToast } from "/static/js/api.js";

document.addEventListener('DOMContentLoaded', async function () {
    if (!await checkAuth()) {
        return;
    }

    const spinner = document.getElementById('myPicHandoffsSpinner');
    const tableContainer = document.getElementById('myPicHandoffsTableContainer');
    const tableBody = document.getElementById('myPicHandoffsTableBody');
    const noFormsMessage = document.getElementById('noMyPicHandoffsMessage');
    const closeButton = document.getElementById('closeMyHandoffsBtn');

    const modalElement = document.getElementById('myPicHandoffsFormDetailsModal');
    const modalTitle = document.getElementById('myPicHandoffsFormDetailsModalLabel');
    const modalBody = document.getElementById('myPicHandoffsFormDetailsContent');
    let formDetailsModal;
    if (modalElement) {
        formDetailsModal = new bootstrap.Modal(modalElement);
    }

    if (closeButton) {
        closeButton.addEventListener('click', () => { // Keep close button as requested
            window.close(); // Consider providing a fallback if window.close() is blocked
            // Fallback: window.location.href = '/wave-glider/home';
        });
    }

    async function fetchMyPicHandoffs() {
        spinner.style.display = 'block';
        tableContainer.style.display = 'none';
        noFormsMessage.style.display = 'none';

        try {
            const forms = await apiRequest('/api/forms/pic_handoffs/my', 'GET');
            renderFormsTable(forms);
        } catch (error) {
            showToast(`Error loading PIC Handoffs: ${error.message}`, 'danger');
            tableBody.innerHTML = `<tr><td colspan="4" class="text-center text-danger">Error loading submissions: ${error.message}</td></tr>`;
            noFormsMessage.textContent = `Error: ${error.message}`;
            noFormsMessage.style.display = 'block';
        } finally {
            spinner.style.display = 'none';
            tableContainer.style.display = 'block';
        }
    }

    function renderFormsTable(forms) {
        tableBody.innerHTML = ''; // Clear existing rows

        if (!forms || forms.length === 0) {
            noFormsMessage.style.display = 'block';
            return;
        }
        noFormsMessage.style.display = 'none';

        forms.forEach(form => {
            const row = tableBody.insertRow();
            row.insertCell().textContent = form.mission_id;
            row.insertCell().textContent = form.form_title;
            // *** THIS IS THE FIX ***
            // Ensure the timestamp string is parsed as UTC by appending 'Z' if it's not already in ISO format.
            const submissionTimestampStr = form.submission_timestamp.endsWith('Z') ? form.submission_timestamp : form.submission_timestamp + 'Z';
            const submissionDate = new Date(submissionTimestampStr);

            // Use toLocaleString for robust, standardized formatting.
            const datePart = submissionDate.toLocaleDateString('en-US', {
                year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC'
            });
            const timePart = submissionDate.toLocaleTimeString('en-GB', {
                hour: '2-digit', minute: '2-digit', timeZone: 'UTC'
            });
            row.insertCell().textContent = `${datePart.replace(',', '')} ${timePart} UTC`;

            const actionsCell = row.insertCell();
            const viewButton = document.createElement('button');
            viewButton.classList.add('btn', 'btn-sm', 'btn-info');
            viewButton.textContent = 'View Details';
            viewButton.addEventListener('click', async () => {
                try {
                    const r = await apiRequest(`/api/forms/id/${form.id}/with-changes`, 'GET');
                    displayFormDetailsInModal(r.form, r.changed_item_ids || []);
                } catch (e) {
                    showToast(`Error loading form: ${e.message}`, 'danger');
                }
            });
            actionsCell.appendChild(viewButton);
        });
    }

    function displayFormDetailsInModal(form, changedItemIds = []) {
        if (!formDetailsModal || !modalTitle || !modalBody) {
            console.error("Modal elements not found for displaying form details.");
            alert("Could not display form details. Modal components missing.");
            return;
        }
        const changedSet = new Set(Array.isArray(changedItemIds) ? changedItemIds : []);
        modalTitle.textContent = `Details for: ${form.form_title} (Mission: ${form.mission_id})`; // Keep title format

        // Re-using the robust time formatting for the modal view as well.
        const submissionTimestampStr = form.submission_timestamp.endsWith('Z') ? form.submission_timestamp : form.submission_timestamp + 'Z';
        const submissionDate = new Date(submissionTimestampStr);
        const formattedTime = submissionDate.toLocaleString('en-GB', { timeZone: 'UTC', dateStyle: 'medium', timeStyle: 'medium', hour12: false }) + ' UTC';
        let contentHtml = `<p><strong>Submitted by:</strong> ${form.submitted_by_username} at ${formattedTime}</p><hr>`;

        if (form.sections_data && Array.isArray(form.sections_data)) {
            form.sections_data.forEach(section => {
                contentHtml += `<h4>${section.title}</h4>`;
                if (section.section_comment) {
                    contentHtml += `<p class="text-muted"><em>Section Comment: ${section.section_comment}</em></p>`;
                }
                contentHtml += '<ul class="list-group list-group-flush mb-3">';
                if (section.items && Array.isArray(section.items)) {
                    section.items.forEach(item => {
                        const isChanged = item.id && changedSet.has(item.id);
                        const liClass = isChanged ? 'list-group-item bg-dark text-light pic-handoff-item-changed' : 'list-group-item bg-dark text-light';
                        contentHtml += `<li class="${liClass}" data-item-id="${item.id || ''}"><strong>${item.label}:</strong> `;
                        let valuePart;
                        if (item.id && String(item.id).startsWith('sensor_') && String(item.id).endsWith('_status')) {
                            const v = item.value;
                            valuePart = (v !== undefined && v !== null && String(v).trim() !== '') ? String(v) : (item.is_checked ? 'On' : 'Off');
                        } else if (item.item_type === 'checkbox') {
                            valuePart = item.is_checked ? 'Checked' : 'Not Checked';
                        } else if (item.id === 'user_comments_val') {
                            valuePart = (item.value && String(item.value).trim()) ? item.value : 'No included comments';
                        } else if (item.item_type === 'autofilled_value' || item.item_type === 'static_text') {
                            valuePart = `${item.value || 'N/A'}`;
                        } else {
                            valuePart = `${item.value || '<em>Not provided</em>'}`;
                        }
                        if (item.is_verified === false) {
                            valuePart = `<span class="pic-unverified-value">${valuePart}</span>`;
                        }
                        contentHtml += valuePart;
                        if (isChanged) {
                            contentHtml += ` <span class="badge bg-warning text-dark">Changes since last PIC</span>`;
                        }
                        if (item.is_verified) {
                            contentHtml += ` <span class="badge bg-success">Verified</span>`;
                        }
                        if (item.comment) {
                            contentHtml += `<br><small class="text-muted"><em>Comment: ${item.comment}</em></small>`;
                        }
                        contentHtml += `</li>`;
                    });
                }
                contentHtml += '</ul>';
            });
        } else {
            contentHtml += '<p>No detailed section data available.</p>';
        }
        modalBody.innerHTML = contentHtml;
        formDetailsModal.show();
    }

    fetchMyPicHandoffs();
});