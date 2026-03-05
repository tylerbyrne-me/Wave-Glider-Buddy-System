/**
 * @file my_pic_handoffs.js
 * @description Display user's PIC handoff submissions
 */

import { checkAuth, logout } from "/static/js/auth.js";
import { apiRequest, showToast } from "/static/js/api.js";
import { renderPicHandoffDetails } from "/static/js/pic_handoff_details.js";

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
        modalTitle.textContent = `Details for: ${form.form_title} (Mission: ${form.mission_id})`;
        modalBody.innerHTML = renderPicHandoffDetails(form, changedItemIds || []);
        formDetailsModal.show();
    }

    fetchMyPicHandoffs();
});