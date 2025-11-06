/**
 * @file my_timesheets.js
 * @description Display user's timesheet submissions
 */

import { checkAuth } from '/static/js/auth.js';
import { apiRequest, showToast } from '/static/js/api.js';

document.addEventListener('DOMContentLoaded', async function() {
    if (!await checkAuth()) return;

    const tableBody = document.getElementById('timesheetsTableBody');

    /**
     * Load user's timesheet submissions
     */
    async function loadMyTimesheets() {
        try {
            const timesheets = await apiRequest('/api/timesheets/my_submissions', 'GET');

            if (timesheets.length === 0) {
                tableBody.innerHTML = '<tr><td colspan="7" class="text-center text-muted">You have not submitted any timesheets.</td></tr>';
                return;
            }

            let tableHtml = '';
            timesheets.forEach(ts => {
                const submissionDate = new Date(ts.submission_timestamp).toLocaleString();
                
                let statusBadge;
                let actionButton = '';

                // Determine status and actions
                if (ts.is_active) {
                    switch (ts.status) {
                        case 'submitted':
                            statusBadge = '<span class="badge bg-primary">Submitted</span>';
                            break;
                        case 'approved':
                            statusBadge = '<span class="badge bg-success">Approved</span>';
                            break;
                        case 'rejected':
                            statusBadge = '<span class="badge bg-danger">Rejected</span>';
                            actionButton = `<a href="/payroll/submit.html?resubmit_for_period=${ts.pay_period_id}" class="btn btn-sm btn-warning">Edit & Resubmit</a>`;
                            break;
                    }
                } else {
                    // If it's not active, it has been superseded by a newer submission.
                    statusBadge = '<span class="badge bg-secondary">Superseded</span>';
                }

                const calculatedHours = parseFloat(ts.calculated_hours).toFixed(2);
                const adjustedHours = ts.adjusted_hours !== null ? parseFloat(ts.adjusted_hours).toFixed(2) : 'N/A';
                const reviewerNotes = ts.reviewer_notes || '<em class="text-muted">None</em>';

                // Add a class to the row if it's not active to visually distinguish it
                const rowClass = ts.is_active ? '' : 'table-secondary text-muted';

                tableHtml += `
                    <tr class="${rowClass}">
                        <td>${ts.pay_period_name}</td>
                        <td>${submissionDate}</td>
                        <td>${statusBadge}</td>
                        <td>${calculatedHours}</td>
                        <td>${adjustedHours}</td>
                        <td>${reviewerNotes}</td>
                        <td>${actionButton}</td>
                    </tr>
                `;
            });

            tableBody.innerHTML = tableHtml;

        } catch (error) {
            showToast(`Error loading timesheets: ${error.message}`, 'danger');
            tableBody.innerHTML = `<tr><td colspan="7" class="text-center text-danger">Error: ${error.message}</td></tr>`;
        }
    }

    loadMyTimesheets();
});