/**
 * @file payroll_submit.js
 * @description Timesheet submission interface
 */

import { checkAuth } from '/static/js/auth.js';
import { apiRequest, showToast } from '/static/js/api.js';

document.addEventListener('DOMContentLoaded', async function() {
    if (!await checkAuth()) return;

    const urlParams = new URLSearchParams(window.location.search);
    const resubmitPeriodId = urlParams.get('resubmit_for_period');

    const payPeriodSelect = document.getElementById('payPeriodSelect');
    const payPeriodSpinner = document.getElementById('payPeriodSpinner');
    const calculationSection = document.getElementById('calculationSection');
    const hoursSpinner = document.getElementById('hoursSpinner');
    const calculatedHoursSpan = document.getElementById('calculatedHours');
    const submitBtn = document.getElementById('submitTimesheetBtn');
    const submitForm = document.getElementById('timesheetSubmitForm');
    const submissionStatusDiv = document.getElementById('submissionStatus');
    const pilotNotesTextarea = document.getElementById('pilotNotes');

    let currentCalculatedHours = 0;

    /**
     * Fetch open pay periods
     */
    async function fetchOpenPayPeriods() {
        try {
            const periods = await apiRequest('/api/pay_periods/open', 'GET');

            payPeriodSelect.innerHTML = '<option value="" selected disabled>-- Select a Period --</option>';
            if (periods.length > 0) {
                periods.forEach(period => {
                    const option = document.createElement('option');
                    option.value = period.id;
                    option.textContent = `${period.name} (${period.start_date} to ${period.end_date})`;
                    payPeriodSelect.appendChild(option);
                });
                payPeriodSelect.disabled = false;

                // If resubmitting, pre-select the period and trigger the change event
                if (resubmitPeriodId && payPeriodSelect.querySelector(`option[value="${resubmitPeriodId}"]`)) {
                    payPeriodSelect.value = resubmitPeriodId;
                    payPeriodSelect.dispatchEvent(new Event('change'));
                }
            } else {
                payPeriodSelect.innerHTML = '<option selected>No open pay periods available.</option>';
            }
        } catch (error) {
            showToast(`Error loading pay periods: ${error.message}`, 'danger');
            payPeriodSelect.innerHTML = `<option selected>Error: ${error.message}</option>`;
        } finally {
            payPeriodSpinner.style.display = 'none';
        }
    }

    payPeriodSelect.addEventListener('change', async function() {
        const periodId = this.value;
        if (!periodId) {
            calculationSection.style.display = 'none';
            return;
        }

        calculationSection.style.display = 'block';
        hoursSpinner.style.display = 'block';
        calculatedHoursSpan.textContent = '--';
        submitBtn.disabled = true;
        submissionStatusDiv.innerHTML = '';

        try {
            const data = await apiRequest(`/api/timesheets/calculate?pay_period_id=${periodId}`, 'GET');
            currentCalculatedHours = data.calculated_hours;
            calculatedHoursSpan.textContent = currentCalculatedHours;
            submitBtn.disabled = false;
        } catch (error) {
            showToast(`Error calculating hours: ${error.message}`, 'danger');
            calculatedHoursSpan.textContent = `Error`;
            submissionStatusDiv.innerHTML = `<div class="alert alert-danger">${error.message}</div>`;
        } finally {
            hoursSpinner.style.display = 'none';
        }
    });

    submitForm.addEventListener('submit', async function(event) {
        event.preventDefault();
        submitBtn.disabled = true;
        submissionStatusDiv.innerHTML = '<div class="alert alert-info">Submitting...</div>';

        const payload = {
            pay_period_id: parseInt(payPeriodSelect.value),
            calculated_hours: currentCalculatedHours,
            notes: pilotNotesTextarea.value.trim()
        };

        try {
            await apiRequest('/api/timesheets', 'POST', payload);
            showToast('Timesheet submitted successfully!', 'success');
            submissionStatusDiv.innerHTML = `<div class="alert alert-success">Timesheet submitted successfully!</div>`;
            // Reset form state
            payPeriodSelect.value = "";
            calculationSection.style.display = 'none';
            pilotNotesTextarea.value = "";

        } catch (error) {
            showToast(`Error submitting timesheet: ${error.message}`, 'danger');
            submissionStatusDiv.innerHTML = `<div class="alert alert-danger">${error.message}</div>`;
            submitBtn.disabled = false; // Re-enable on error
        }
    });

    // Initial load
    fetchOpenPayPeriods();
});