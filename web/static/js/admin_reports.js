/**
 * @file admin_reports.js
 * @description Admin reports generation and charting
 */

import { checkAuth, getUserProfile } from '/static/js/auth.js';
import { apiRequest, showToast } from '/static/js/api.js';

document.addEventListener('DOMContentLoaded', async function() {
    if (!await checkAuth()) return;

    // Verify user is an admin before proceeding
    getUserProfile().then(user => {
        if (!user || user.role !== 'admin') {
            document.body.innerHTML = '<div class="container mt-5"><div class="alert alert-danger">Access Denied. You must be an administrator to view this page.</div></div>';
            return;
        }
        initializePage();
    });

    function initializePage() {
        const reportForm = document.getElementById('monthlyTimesheetReportForm');
        const yearSelect = document.getElementById('reportYear');
        const monthSelect = document.getElementById('reportMonth');
        const statusDiv = document.getElementById('reportStatus');
        const downloadButton = reportForm.querySelector('button[type="submit"]');
        const chartContainer = document.getElementById('chartContainer');
        const chartCanvas = document.getElementById('pilotHoursChart');
        const chartSpinner = document.getElementById('chartSpinner');
        const noChartData = document.getElementById('noChartData');
        let pilotHoursChart = null;

        // Populate year dropdown
        const currentYear = new Date().getFullYear();
        for (let year = currentYear; year >= 2023; year--) {
            const option = document.createElement('option');
            option.value = year;
            option.textContent = year;
            yearSelect.appendChild(option);
        }

        // Set default month to last month
        const lastMonth = new Date();
        lastMonth.setMonth(lastMonth.getMonth() - 1);
        monthSelect.value = lastMonth.getMonth() + 1;
        if (lastMonth.getMonth() === 11) { // If last month was December, year is also last year
            yearSelect.value = lastMonth.getFullYear();
        }

        reportForm.addEventListener('submit', async function(event) {
            event.preventDefault();
            statusDiv.innerHTML = '<div class="alert alert-info">Generating report...</div>';
            downloadButton.disabled = true;
            downloadButton.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Generating...';

            // Hide previous chart results and show spinner
            chartContainer.style.display = 'none';
            noChartData.style.display = 'none';
            chartSpinner.style.display = 'block';
            if (pilotHoursChart) {
                pilotHoursChart.destroy();
            }

            const year = yearSelect.value;
            const month = monthSelect.value;

            // Use Promise.all to fire off both requests concurrently
            // CSV download needs fetch directly for blob response, chart uses apiRequest for JSON
            const token = localStorage.getItem('accessToken');
            const headers = {};
            if (token) {
                headers['Authorization'] = `Bearer ${token}`;
            }
            
            try {
                const [csvResponse, chartData] = await Promise.all([
                    fetch(`/api/admin/reports/monthly_timesheet_summary?year=${year}&month=${month}`, { headers }),
                    apiRequest(`/api/admin/reports/monthly_summary_chart?year=${year}&month=${month}`, 'GET')
                ]);

                // Handle CSV Download
                if (csvResponse && csvResponse.ok) {
                    const blob = await csvResponse.blob();
                    const contentDisposition = csvResponse.headers.get('Content-Disposition');
                    let filename = `approved_timesheets_${year}-${String(month).padStart(2, '0')}.csv`;
                    if (contentDisposition && contentDisposition.includes('filename=')) {
                        filename = contentDisposition.split('filename=')[1].replace(/"/g, '');
                    }
                    const url = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.style.display = 'none';
                    a.href = url;
                    a.download = filename;
                    document.body.appendChild(a);
                    a.click();
                    window.URL.revokeObjectURL(url);
                    a.remove();
                    showToast(`Report downloaded successfully as ${filename}`, 'success');
                    statusDiv.innerHTML = `<div class="alert alert-success">Report downloaded successfully as <strong>${filename}</strong>.</div>`;
                } else if (csvResponse) {
                    const errorData = await csvResponse.json().catch(() => ({ detail: 'An unknown error occurred during CSV download.' }));
                    showToast(`CSV Download Error: ${errorData.detail}`, 'danger');
                    statusDiv.innerHTML = `<div class="alert alert-danger">CSV Download Error: ${errorData.detail}</div>`;
                }

                // Handle Chart Data
                chartSpinner.style.display = 'none';
                if (chartData) {
                    if (chartData.length > 0) {
                        renderPilotHoursChart(chartData);
                        chartContainer.style.display = 'block';
                    } else {
                        noChartData.style.display = 'block';
                    }
                }
            }

            // Re-enable button
            downloadButton.disabled = false;
            downloadButton.innerHTML = '<i class="fas fa-download me-2"></i>Download Report';
        });

        function renderPilotHoursChart(data) {
            const labels = data.map(d => d.pilot_name);
            const hours = data.map(d => d.total_hours);

            const chartConfig = {
                type: 'bar',
                data: {
                    labels: labels,
                    datasets: [{
                        label: 'Total Approved Hours',
                        data: hours,
                        backgroundColor: 'rgba(54, 162, 235, 0.6)',
                        borderColor: 'rgba(54, 162, 235, 1)',
                        borderWidth: 1
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: {
                            beginAtZero: true,
                            title: {
                                display: true,
                                text: 'Hours'
                            }
                        },
                        x: {
                            title: {
                                display: true,
                                text: 'Pilot'
                            }
                        }
                    },
                    plugins: {
                        legend: {
                            display: false
                        },
                        title: {
                            display: true,
                            text: `Approved Hours for ${monthSelect.options[monthSelect.selectedIndex].text} ${yearSelect.value}`
                        }
                    }
                }
            };
            pilotHoursChart = new Chart(chartCanvas, chartConfig);
        }
    }
});