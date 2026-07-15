import { apiRequest, showToast } from '/static/js/api.js';

document.addEventListener('DOMContentLoaded', () => {
    const jobsTableBody = document.getElementById('jobsTableBody');
    const refreshBtn = document.getElementById('refreshJobsBtn');
    const platformFilter = document.getElementById('platformFilter');
    let allJobs = [];

    const deriveJobPlatform = (jobId) => (String(jobId || '').startsWith('slocum_') ? 'slocum' : 'wave_glider');

    const renderJobs = (jobs) => {
        if (jobs.length === 0) {
            jobsTableBody.innerHTML = '<tr><td colspan="8" class="text-center text-muted">No scheduled jobs found.</td></tr>';
            return;
        }

        jobsTableBody.innerHTML = jobs.map(job => {
            const statusClass = job.status === 'ok' ? 'bg-success' : 'bg-danger';
            const statusTitle = job.status === 'ok' ? 'Job is running as scheduled.' : 'Job is overdue. It may have failed to run at its last scheduled time.';
            const platform = deriveJobPlatform(job.id);
            const platformLabel = platform === 'slocum' ? 'Slocum' : 'Wave Glider';

            return `
                <tr>
                    <td>
                        <span class="badge ${statusClass}" title="${statusTitle}">${job.status.toUpperCase()}</span>
                    </td>
                    <td><span class="badge bg-secondary">${platformLabel}</span></td>
                    <td><code>${job.id}</code></td>
                    <td>${job.name}</td>
                    <td><code>${job.func_ref}</code></td>
                    <td><span class="badge bg-secondary">${job.trigger.type}</span></td>
                    <td>${job.trigger.details}</td>
                    <td>${job.next_run_time ? new Date(job.next_run_time).toLocaleString('en-CA', { timeZone: 'UTC' }).replace(',', '') + ' UTC' : 'N/A'}</td>
                </tr>
            `;
        }).join('');
    };

    const applyFilter = () => {
        const selected = platformFilter ? platformFilter.value : 'all';
        if (selected === 'all') {
            renderJobs(allJobs);
            return;
        }
        renderJobs(allJobs.filter(job => deriveJobPlatform(job.id) === selected));
    };

    const loadJobs = async () => {
        jobsTableBody.innerHTML = `
            <tr>
                <td colspan="8" class="text-center">
                    <div class="spinner-border" role="status"><span class="visually-hidden">Loading...</span></div>
                </td>
            </tr>`;

        try {
            allJobs = await apiRequest('/api/admin/scheduler/jobs', 'GET');
            applyFilter();
        } catch (error) {
            jobsTableBody.innerHTML = '<tr><td colspan="8" class="text-center text-danger">Failed to load job status. You may not have permission to view this page.</td></tr>';
        }
    };

    if (platformFilter) {
        platformFilter.addEventListener('change', applyFilter);
    }

    refreshBtn.addEventListener('click', () => {
        showToast('Refreshing job list...', 'info');
        loadJobs();
    });

    loadJobs();
});
