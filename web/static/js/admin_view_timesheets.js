import { checkAuth, getUserProfile } from '/static/js/auth.js';
import { fetchWithAuth } from '/static/js/api.js';

document.addEventListener('DOMContentLoaded', function() {
    if (!checkAuth()) return;

    const payPeriodSelect = document.getElementById('payPeriodSelectAdmin');
    const payPeriodSpinner = document.getElementById('payPeriodSpinnerAdmin');
    const timesheetsSpinner = document.getElementById('timesheetsSpinner');
    const tableContainer = document.getElementById('timesheetsTableContainer');
    const exportCsvBtn = document.getElementById('exportTimesheetsCsvBtn');
    const tableBody = document.getElementById('timesheetsTableBody');

    // Timesheet Action Modal Elements
    const timesheetActionModal = new bootstrap.Modal(document.getElementById('timesheetActionModal'));
    const timesheetActionModalLabel = document.getElementById('timesheetActionModalLabel');
    const actionVerbSpan = document.getElementById('actionVerb');
    const modalPilotNameSpan = document.getElementById('modalPilotName');
    const modalPayPeriodNameSpan = document.getElementById('modalPayPeriodName');
    const modalTimesheetIdInput = document.getElementById('modalTimesheetId');
    const modalActionTypeInput = document.getElementById('modalActionType');
    const reviewerNotesTextarea = document.getElementById('reviewerNotes');
    const adjustedHoursInput = document.getElementById('adjustedHours');
    const submitTimesheetActionBtn = document.getElementById('submitTimesheetActionBtn');
    const timesheetActionErrorDiv = document.getElementById('timesheetActionError');

    // Timesheet History Modal Elements
    const timesheetHistoryModal = new bootstrap.Modal(document.getElementById('timesheetHistoryModal'));
    const historyPilotNameSpan = document.getElementById('historyPilotName');
    const historyPayPeriodNameSpan = document.getElementById('historyPayPeriodName');
    const historySpinner = document.getElementById('historySpinner');
    const historyTableContainer = document.getElementById('historyTableContainer');
    const historyTableBody = document.getElementById('historyTableBody');

    async function fetchAllPayPeriods() {
        try {
            // Use the admin endpoint to get all periods, not just open ones
            const response = await fetchWithAuth('/api/admin/pay_periods');
            if (!response.ok) throw new Error('Failed to load pay periods.');
            const periods = await response.json();

            payPeriodSelect.innerHTML = '<option value="" selected disabled>-- Select a Period --</option>';
            if (periods.length > 0) {
                periods.forEach(period => {
                    const option = document.createElement('option');
                    option.value = period.id;
                    option.textContent = `${period.name} (${period.start_date} to ${period.end_date})`;
                    payPeriodSelect.appendChild(option);
                });
                payPeriodSelect.disabled = false;
            } else {
                payPeriodSelect.innerHTML = '<option selected>No pay periods found.</option>';
            }
        } catch (error) {
            console.error("Error fetching pay periods:", error);
            payPeriodSelect.innerHTML = `<option selected>Error: ${error.message}</option>`;
        } finally {
            payPeriodSpinner.style.display = 'none';
        }
    }

    payPeriodSelect.addEventListener('change', async function() {
        const periodId = this.value;
        if (!periodId) {
            tableContainer.style.display = 'none';
            exportCsvBtn.style.display = 'none';
            return;
        }

        timesheetsSpinner.style.display = 'block';
        tableContainer.style.display = 'none';
        tableBody.innerHTML = '';

        exportCsvBtn.style.display = 'none'; // Hide until data is loaded

        try {
            const response = await fetchWithAuth(`/api/admin/timesheets?pay_period_id=${periodId}`);
            if (!response.ok) throw new Error('Failed to fetch timesheets for this period.');
            const timesheets = await response.json();
            renderTable(timesheets, periodId);
        } catch (error) {
            tableBody.innerHTML = `<tr><td colspan="7" class="text-center text-danger">${error.message}</td></tr>`;
        } finally {
            timesheetsSpinner.style.display = 'none';
            tableContainer.style.display = 'block';
        }
    });

    function renderTable(timesheets, payPeriodId) {
        tableBody.innerHTML = ''; // Clear previous results
        if (timesheets.length === 0) {
            tableBody.innerHTML = '<tr><td colspan="7" class="text-center">No timesheets submitted for this period yet.</td></tr>';
            exportCsvBtn.style.display = 'none';
            return;
        }
        exportCsvBtn.style.display = 'inline-block'; // Show export button if there's data

        timesheets.forEach(ts => {
            const submissionDate = new Date(ts.submission_timestamp);
            const row = document.createElement('tr');

            let statusBadgeClass = 'bg-info';
            if (ts.status === 'approved') {
                statusBadgeClass = 'bg-success';
            } else if (ts.status === 'rejected') {
                statusBadgeClass = 'bg-danger';
            }

            const actionsHtml = `
                <div class="btn-group btn-group-sm" role="group">
                    <button class="btn btn-success approve-btn" data-id="${ts.id}" data-pilot="${ts.username}" data-payperiod="${ts.pay_period_name}" data-calculated-hours="${ts.calculated_hours}" data-adjusted-hours="${ts.adjusted_hours || ''}" ${ts.status !== 'submitted' ? 'disabled' : ''} title="Approve"><i class="fas fa-check"></i></button>
                    <button class="btn btn-warning reject-btn" data-id="${ts.id}" data-pilot="${ts.username}" data-payperiod="${ts.pay_period_name}" data-calculated-hours="${ts.calculated_hours}" data-adjusted-hours="${ts.adjusted_hours || ''}" ${ts.status !== 'submitted' ? 'disabled' : ''} title="Reject"><i class="fas fa-times"></i></button>
                    <button class="btn btn-info history-btn" data-id="${ts.id}" data-pilot="${ts.username}" data-payperiod="${ts.pay_period_name}" title="View History"><i class="fas fa-history"></i></button>
                </div>
            `;

            const adjustedHoursDisplay = ts.adjusted_hours !== null ? ts.adjusted_hours.toFixed(2) : '<em>N/A</em>';

            row.innerHTML = `
                <td>${ts.username}</td>
                <td>${ts.calculated_hours.toFixed(2)}</td>
                <td>${adjustedHoursDisplay}</td>
                <td>${submissionDate.toISOString().slice(0, 19).replace('T', ' ')}</td>
                <td><span class="badge ${statusBadgeClass}">${ts.status}</span></td>
                <td>${ts.reviewer_notes || '<em>None</em>'}</td>
                <td>${ts.notes || '<em>No notes</em>'}</td>
                <td>${actionsHtml}</td>
            `;
            tableBody.appendChild(row);
        });

        // Add event listeners for the dynamically created buttons
        tableBody.querySelectorAll('.approve-btn').forEach(button => {
            button.addEventListener('click', function() {
                openTimesheetActionModal(this.dataset, 'approve');
            });
        });
        tableBody.querySelectorAll('.reject-btn').forEach(button => {
            button.addEventListener('click', function() {
                openTimesheetActionModal(this.dataset, 'reject');
            });
        });
        tableBody.querySelectorAll('.history-btn').forEach(button => {
            button.addEventListener('click', function() {
                const dataset = this.dataset;
                historyPilotNameSpan.textContent = dataset.pilot;
                historyPayPeriodNameSpan.textContent = dataset.payperiod;
                loadAndShowHistory(dataset.id);
            });
        });
    }

    function openTimesheetActionModal(dataset, actionType) {
        timesheetActionModalLabel.textContent = `${actionType.charAt(0).toUpperCase() + actionType.slice(1)} Timesheet`;
        actionVerbSpan.textContent = actionType;
        modalPilotNameSpan.textContent = dataset.pilot;
        modalPayPeriodNameSpan.textContent = dataset.payperiod;
        modalTimesheetIdInput.value = dataset.id;
        modalActionTypeInput.value = actionType;

        // Pre-fill adjusted hours input with existing adjusted value.
        // The placeholder will show the calculated value as a fallback reference.
        if (dataset.adjustedHours) {
            adjustedHoursInput.value = parseFloat(dataset.adjustedHours).toFixed(2);
        } else {
            adjustedHoursInput.value = ''; // Clear it if no adjusted hours are set
        }
        adjustedHoursInput.placeholder = `Calculated: ${parseFloat(dataset.calculatedHours).toFixed(2)}. Leave blank to use this value.`;

        reviewerNotesTextarea.value = ''; // Clear previous notes
        timesheetActionErrorDiv.style.display = 'none';
        submitTimesheetActionBtn.classList.remove('btn-success', 'btn-danger');
        submitTimesheetActionBtn.classList.add(actionType === 'approve' ? 'btn-success' : 'btn-danger');
        submitTimesheetActionBtn.textContent = actionType.charAt(0).toUpperCase() + actionType.slice(1);
        timesheetActionModal.show();
    }

    submitTimesheetActionBtn.addEventListener('click', async function() {
        const timesheetId = modalTimesheetIdInput.value;
        const actionType = modalActionTypeInput.value;
        const reviewerNotes = reviewerNotesTextarea.value.trim();
        const adjustedHoursValue = adjustedHoursInput.value.trim();

        if (!reviewerNotes) {
            timesheetActionErrorDiv.textContent = "Reviewer notes are required.";
            timesheetActionErrorDiv.style.display = 'block';
            return;
        }

        timesheetActionErrorDiv.style.display = 'none';
        submitTimesheetActionBtn.disabled = true;

        const payload = {
            status: actionType === 'approve' ? 'approved' : 'rejected',
            reviewer_notes: reviewerNotes
        };

        if (adjustedHoursValue !== "") {
            payload.adjusted_hours = parseFloat(adjustedHoursValue);
            if (isNaN(payload.adjusted_hours)) {
                submitTimesheetActionBtn.disabled = false; // Re-enable button
                timesheetActionErrorDiv.textContent = "Adjusted hours must be a valid number.";
                timesheetActionErrorDiv.style.display = 'block';
                return;
            }
        } else {
            // If the field is blank, we explicitly send null to clear any previous adjustment.
            // The backend PATCH logic will handle this.
            // Note: We only need to send this if we want to be able to *clear* an adjustment.
            // If we only want to set/update, we can omit this else block. Let's include it for completeness.
            payload.adjusted_hours = null;
        }

        try {
            const response = await fetchWithAuth(`/api/admin/timesheets/${timesheetId}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || 'Failed to update timesheet status.');
            }

            timesheetActionModal.hide();
            // Re-fetch timesheets for the current period to update the table
            payPeriodSelect.dispatchEvent(new Event('change')); 
        } catch (error) {
            timesheetActionErrorDiv.textContent = error.message;
            timesheetActionErrorDiv.style.display = 'block';
        } finally {
            submitTimesheetActionBtn.disabled = false;
        }
    });

    async function loadAndShowHistory(timesheetId) {
        historySpinner.style.display = 'block';
        historyTableContainer.style.display = 'none';
        historyTableBody.innerHTML = '';
        timesheetHistoryModal.show();
    
        try {
            const response = await fetchWithAuth(`/api/admin/timesheets/${timesheetId}/history`);
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || 'Failed to load submission history.');
            }
            const history = await response.json();
    
            let historyHtml = '';
            if (history.length === 0) {
                historyHtml = '<tr><td colspan="6" class="text-center text-muted">No history found.</td></tr>';
            } else {
                history.forEach(ts => {
                    const submissionDate = new Date(ts.submission_timestamp).toISOString().slice(0, 19).replace('T', ' ');
                    
                    let statusBadge;
                    if (ts.is_active) {
                        switch (ts.status) {
                            case 'submitted': statusBadge = '<span class="badge bg-primary">Active (Submitted)</span>'; break;
                            case 'approved': statusBadge = '<span class="badge bg-success">Active (Approved)</span>'; break;
                            case 'rejected': statusBadge = '<span class="badge bg-danger">Active (Rejected)</span>'; break;
                        }
                    } else {
                        statusBadge = '<span class="badge bg-secondary">Superseded</span>';
                    }
    
                    const calculatedHours = parseFloat(ts.calculated_hours).toFixed(2);
                    const adjustedHours = ts.adjusted_hours !== null ? parseFloat(ts.adjusted_hours).toFixed(2) : '<em>N/A</em>';
                    const pilotNotes = ts.notes || '<em>-</em>';
                    const adminNotes = ts.reviewer_notes || '<em>-</em>';
                    
                    const rowClass = ts.is_active ? 'table-info' : '';
    
                    historyHtml += `
                        <tr class="${rowClass}">
                            <td>${submissionDate}</td>
                            <td>${statusBadge}</td>
                            <td>${calculatedHours}</td>
                            <td>${adjustedHours}</td>
                            <td>${pilotNotes}</td>
                            <td>${adminNotes}</td>
                        </tr>
                    `;
                });
            }
            historyTableBody.innerHTML = historyHtml;
    
        } catch (error) {
            console.error('Error fetching timesheet history:', error);
            historyTableBody.innerHTML = `<tr><td colspan="6" class="text-center text-danger">Error: ${error.message}</td></tr>`;
        } finally {
            historySpinner.style.display = 'none';
            historyTableContainer.style.display = 'block';
        }
    }

    // Export to CSV functionality
    exportCsvBtn.addEventListener('click', async function() {
        const payPeriodId = payPeriodSelect.value;
        if (!payPeriodId) {
            alert("Please select a pay period first.");
            return;
        }

        try {
            const response = await fetchWithAuth(`/api/admin/timesheets/export_csv?pay_period_id=${payPeriodId}`);
            if (!response.ok) throw new Error('Failed to export timesheets to CSV.');
            
            const blob = await response.blob();
            const contentDisposition = response.headers.get('Content-Disposition');
            let filename = 'timesheets.csv';
            if (contentDisposition && contentDisposition.indexOf('filename=') !== -1) {
                filename = contentDisposition.split('filename=')[1].split(';')[0].replace(/"/g, '');
            }

            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            a.remove();
        } catch (error) {
            alert("Error exporting timesheets: " + error.message);
            console.error("Export error:", error);
        }
    });

    // Initial load
    fetchAllPayPeriods();
});