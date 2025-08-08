import { checkAuth, getUserProfile } from '/static/js/auth.js';
import { fetchWithAuth } from '/static/js/api.js';

document.addEventListener('DOMContentLoaded', function() {
    if (!checkAuth()) return;

    // Ensure user is an admin
    getUserProfile().then(user => {
        if (!user || user.role !== 'admin') {
            document.body.innerHTML = '<div class="container mt-5"><div class="alert alert-danger">Access Denied. You must be an administrator to view this page.</div></div>';
            return;
        }
        initializePage();
    });

    function initializePage() {
        // Form for creating new periods
        const createForm = document.getElementById('createPayPeriodForm');
        const createErrorDiv = document.getElementById('createPeriodError');

        // Table for existing periods
        const tableSpinner = document.getElementById('payPeriodsSpinner');
        const tableContainer = document.getElementById('payPeriodsTableContainer');
        const tableBody = document.getElementById('payPeriodsTableBody');

        // Modal for editing periods
        const editModal = new bootstrap.Modal(document.getElementById('editPayPeriodModal'));
        const editForm = document.getElementById('editPayPeriodForm');
        const editErrorDiv = document.getElementById('editPeriodError');
        const saveChangesBtn = document.getElementById('savePeriodChangesBtn');

        async function loadPayPeriods() {
            tableSpinner.style.display = 'block';
            tableContainer.style.display = 'none';
            try {
                const response = await fetchWithAuth('/api/admin/pay_periods');
                if (!response.ok) throw new Error('Failed to load pay periods.');
                const periods = await response.json();
                renderTable(periods);
            } catch (error) {
                tableBody.innerHTML = `<tr><td colspan="5" class="text-center text-danger">${error.message}</td></tr>`;
            } finally {
                tableSpinner.style.display = 'none';
                tableContainer.style.display = 'block';
            }
        }

        function renderTable(periods) {
            tableBody.innerHTML = '';
            if (periods.length === 0) {
                tableBody.innerHTML = '<tr><td colspan="5" class="text-center text-muted">No pay periods have been created.</td></tr>';
                return;
            }

            periods.forEach(period => {
                const row = document.createElement('tr');
                const statusBadge = period.status === 'open' ? '<span class="badge bg-success">Open</span>' : '<span class="badge bg-secondary">Closed</span>';
                
                row.innerHTML = `
                    <td>${period.name}</td>
                    <td>${period.start_date}</td>
                    <td>${period.end_date}</td>
                    <td>${statusBadge}</td>
                    <td>
                        <button class="btn btn-sm btn-warning edit-btn" data-id="${period.id}" data-name="${period.name}" data-start="${period.start_date}" data-end="${period.end_date}" data-status="${period.status}">Edit</button>
                        <button class="btn btn-sm btn-danger delete-btn" data-id="${period.id}" data-name="${period.name}">Delete</button>
                    </td>
                `;
                tableBody.appendChild(row);
            });
        }

        // Event Delegation for Edit and Delete buttons
        tableBody.addEventListener('click', function(event) {
            if (event.target.classList.contains('edit-btn')) {
                const data = event.target.dataset;
                document.getElementById('editPeriodId').value = data.id;
                document.getElementById('editPeriodName').value = data.name;
                document.getElementById('editPeriodStartDate').value = data.start;
                document.getElementById('editPeriodEndDate').value = data.end;
                document.getElementById('editPeriodStatus').value = data.status;
                editErrorDiv.style.display = 'none';
                editModal.show();
            }

            if (event.target.classList.contains('delete-btn')) {
                const periodId = event.target.dataset.id;
                const periodName = event.target.dataset.name;
                if (confirm(`Are you sure you want to delete the pay period "${periodName}"?\nThis cannot be undone.`)) {
                    deletePayPeriod(periodId);
                }
            }
        });

        async function deletePayPeriod(id) {
            try {
                const response = await fetchWithAuth(`/api/admin/pay_periods/${id}`, {
                    method: 'DELETE'
                });
                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(errorData.detail || 'Failed to delete pay period.');
                }
                loadPayPeriods(); // Refresh table on success
            } catch (error) {
                alert(`Error: ${error.message}`);
            }
        }

        // Handle Create Form Submission
        createForm.addEventListener('submit', async function(event) {
            event.preventDefault();
            createErrorDiv.style.display = 'none';
            const createBtn = createForm.querySelector('button[type="submit"]');
            createBtn.disabled = true;

            const payload = {
                name: document.getElementById('periodName').value,
                start_date: document.getElementById('periodStartDate').value,
                end_date: document.getElementById('periodEndDate').value,
            };

            try {
                const response = await fetchWithAuth('/api/admin/pay_periods', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const result = await response.json();
                if (!response.ok) {
                    throw new Error(result.detail || 'Failed to create pay period.');
                }
                createForm.reset();
                loadPayPeriods(); // Refresh table
            } catch (error) {
                createErrorDiv.textContent = error.message;
                createErrorDiv.style.display = 'block';
            } finally {
                createBtn.disabled = false;
            }
        });

        // Handle Edit Form Submission (from modal)
        saveChangesBtn.addEventListener('click', async function() {
            editErrorDiv.style.display = 'none';
            saveChangesBtn.disabled = true;

            const periodId = document.getElementById('editPeriodId').value;
            const payload = {
                name: document.getElementById('editPeriodName').value,
                start_date: document.getElementById('editPeriodStartDate').value,
                end_date: document.getElementById('editPeriodEndDate').value,
                status: document.getElementById('editPeriodStatus').value,
            };

            try {
                const response = await fetchWithAuth(`/api/admin/pay_periods/${periodId}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const result = await response.json();
                if (!response.ok) {
                    throw new Error(result.detail || 'Failed to update pay period.');
                }
                editModal.hide();
                loadPayPeriods(); // Refresh table
            } catch (error) {
                editErrorDiv.textContent = error.message;
                editErrorDiv.style.display = 'block';
            } finally {
                saveChangesBtn.disabled = false;
            }
        });

        // Initial load
        loadPayPeriods();
    }
});