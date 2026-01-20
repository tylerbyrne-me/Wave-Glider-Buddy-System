/**
 * User Settings Page JavaScript
 * Handles user information updates and password changes
 */

import { getAuthToken } from './auth.js';
import { apiRequest, showToast } from './api.js';

class UserSettings {
    constructor() {
        this.initializeEventListeners();
        this.loadUserData();
    }

    initializeEventListeners() {
        // User information form
        const userInfoForm = document.getElementById('userInfoForm');
        if (userInfoForm) {
            userInfoForm.addEventListener('submit', (e) => this.handleUserInfoUpdate(e));
        }

        // Password change form
        const passwordForm = document.getElementById('passwordChangeForm');
        if (passwordForm) {
            passwordForm.addEventListener('submit', (e) => this.handlePasswordChange(e));
        }

        // Refresh button
        const refreshBtn = document.getElementById('refreshUserDataBtn');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => this.loadUserData());
        }

        // Real-time password confirmation validation
        const newPasswordInput = document.getElementById('newPassword');
        const confirmPasswordInput = document.getElementById('confirmPassword');
        
        if (newPasswordInput && confirmPasswordInput) {
            confirmPasswordInput.addEventListener('input', () => this.validatePasswordMatch());
            newPasswordInput.addEventListener('input', () => this.validatePasswordMatch());
        }
    }

    async loadUserData() {
        try {
            const userData = await apiRequest('/api/users/me', 'GET');
            this.populateUserData(userData);
        } catch (error) {
            showToast(`Failed to load user data: ${error.message}`, 'danger');
        }
    }

    populateUserData(userData) {
        // Update form fields with current user data
        const fullNameInput = document.getElementById('fullName');
        const emailInput = document.getElementById('email');
        
        if (fullNameInput) {
            fullNameInput.value = userData.full_name || '';
        }
        if (emailInput) {
            emailInput.value = userData.email || '';
        }

        // Update account status display
        this.updateAccountStatusDisplay(userData);
    }

    updateAccountStatusDisplay(userData) {
        const statusBadge = document.querySelector('.badge');
        if (statusBadge) {
            if (userData.disabled) {
                statusBadge.className = 'badge bg-danger';
                statusBadge.textContent = 'Disabled';
            } else {
                statusBadge.className = 'badge bg-success';
                statusBadge.textContent = 'Active';
            }
        }
    }

    async handleUserInfoUpdate(event) {
        event.preventDefault();
        
        const updateBtn = document.getElementById('updateInfoBtn');
        const originalText = updateBtn.innerHTML;
        
        try {
            // Disable button and show loading state
            updateBtn.disabled = true;
            updateBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Updating...';

            const formData = {
                full_name: document.getElementById('fullName').value.trim() || null,
                email: document.getElementById('email').value.trim() || null
            };

            const tokenInput = document.getElementById('sensorTrackerToken');
            const clearTokenCheckbox = document.getElementById('clearSensorTrackerToken');
            if (tokenInput && clearTokenCheckbox) {
                if (clearTokenCheckbox.checked) {
                    formData.sensor_tracker_token = null;
                } else {
                    const tokenValue = tokenInput.value.trim();
                    if (tokenValue) {
                        formData.sensor_tracker_token = tokenValue;
                    }
                }
            }

            const updatedUser = await apiRequest('/api/users/me', 'PUT', formData);
            this.populateUserData(updatedUser);
            if (tokenInput) tokenInput.value = '';
            if (clearTokenCheckbox) clearTokenCheckbox.checked = false;
            showToast('User information updated successfully!', 'success');

        } catch (error) {
            showToast(`Failed to update information: ${error.message}`, 'danger');
        } finally {
            // Re-enable button
            updateBtn.disabled = false;
            updateBtn.innerHTML = originalText;
        }
    }

    async handlePasswordChange(event) {
        event.preventDefault();
        
        const changeBtn = document.getElementById('changePasswordBtn');
        const originalText = changeBtn.innerHTML;
        
        try {
            // Validate password match
            if (!this.validatePasswordMatch()) {
                return;
            }

            // Disable button and show loading state
            changeBtn.disabled = true;
            changeBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Changing...';

            const formData = {
                current_password: document.getElementById('currentPassword').value,
                new_password: document.getElementById('newPassword').value
            };

            await apiRequest('/api/users/me/password', 'PUT', formData);

            // Clear password fields
            document.getElementById('currentPassword').value = '';
            document.getElementById('newPassword').value = '';
            document.getElementById('confirmPassword').value = '';
            
            showToast('Password changed successfully!', 'success');

        } catch (error) {
            showToast(`Failed to change password: ${error.message}`, 'danger');
        } finally {
            // Re-enable button
            changeBtn.disabled = false;
            changeBtn.innerHTML = originalText;
        }
    }

    validatePasswordMatch() {
        const newPassword = document.getElementById('newPassword').value;
        const confirmPassword = document.getElementById('confirmPassword').value;
        const confirmInput = document.getElementById('confirmPassword');
        
        if (confirmPassword && newPassword !== confirmPassword) {
            confirmInput.setCustomValidity('Passwords do not match');
            confirmInput.classList.add('is-invalid');
            return false;
        } else {
            confirmInput.setCustomValidity('');
            confirmInput.classList.remove('is-invalid');
            return true;
        }
    }
}

// Initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    new UserSettings();
});
