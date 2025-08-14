import { apiRequest, showToast } from '/static/js/api.js';

document.addEventListener('DOMContentLoaded', () => {
    const jobsTableBody = document.getElementById('jobsTableBody');
    const refreshBtn = document.getElementById('refreshJobsBtn');

    const loadJobs = async () => {
        jobsTableBody.innerHTML = `
            <tr>
                <td colspan="7" class="text-center">
                    <div class="spinner-border" role="status"><span class="visually-hidden">Loading...</span></div>
                </td>
            </tr>`;

        try {
            const jobs = await apiRequest('/api/admin/scheduler/jobs', 'GET');
            if (jobs.length === 0) {
                jobsTableBody.innerHTML = '<tr><td colspan="7" class="text-center text-muted">No scheduled jobs found.</td></tr>';
                return;
            }

            jobsTableBody.innerHTML = jobs.map(job => {
                const statusClass = job.status === 'ok' ? 'bg-success' : 'bg-danger';
                const statusTitle = job.status === 'ok' ? 'Job is running as scheduled.' : 'Job is overdue. It may have failed to run at its last scheduled time.';
                
                return `
                    <tr>
                        <td>
                            <span class="badge ${statusClass}" title="${statusTitle}">${job.status.toUpperCase()}</span>
                        </td>
                        <td><code>${job.id}</code></td>
                        <td>${job.name}</td>
                        <td><code>${job.func_ref}</code></td>
                        <td><span class="badge bg-secondary">${job.trigger.type}</span></td>
                        <td>${job.trigger.details}</td>
                        <td>${job.next_run_time ? new Date(job.next_run_time).toLocaleString('en-CA', { timeZone: 'UTC' }).replace(',', '') + ' UTC' : 'N/A'}</td>
                    </tr>
                `;
            }).join('');

        } catch (error) {
            jobsTableBody.innerHTML = '<tr><td colspan="7" class="text-center text-danger">Failed to load job status. You may not have permission to view this page.</td></tr>';
        }
    };

    refreshBtn.addEventListener('click', () => {
        showToast('Refreshing job list...', 'info');
        loadJobs();
    });

    loadJobs();
});