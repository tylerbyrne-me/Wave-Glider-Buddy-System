/**
 * User Settings Page JavaScript
 * Handles user information updates and password changes
 */

import { getAuthToken } from './auth.js';
import { showToast } from './api.js';

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
            const response = await fetch('/api/users/me', {
                method: 'GET',
                headers: {
                    'Authorization': `Bearer ${getAuthToken()}`,
                    'Content-Type': 'application/json'
                }
            });

            if (!response.ok) {
                throw new Error(`Failed to load user data: ${response.statusText}`);
            }

            const userData = await response.json();
            this.populateUserData(userData);
            
        } catch (error) {
            console.error('Error loading user data:', error);
            showToast('Failed to load user data. Please refresh the page.', 'danger');
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

            const response = await fetch('/api/users/me', {
                method: 'PUT',
                headers: {
                    'Authorization': `Bearer ${getAuthToken()}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(formData)
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || `Update failed: ${response.statusText}`);
            }

            const updatedUser = await response.json();
            this.populateUserData(updatedUser);
            showToast('User information updated successfully!', 'success');

        } catch (error) {
            console.error('Error updating user info:', error);
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

            const response = await fetch('/api/users/me/password', {
                method: 'PUT',
                headers: {
                    'Authorization': `Bearer ${getAuthToken()}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(formData)
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || `Password change failed: ${response.statusText}`);
            }

            // Clear password fields
            document.getElementById('currentPassword').value = '';
            document.getElementById('newPassword').value = '';
            document.getElementById('confirmPassword').value = '';
            
            showToast('Password changed successfully!', 'success');

        } catch (error) {
            console.error('Error changing password:', error);
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
