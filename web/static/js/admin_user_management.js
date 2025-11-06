/**
 * @file admin_user_management.js
 * @description Admin user management interface
 */

import { checkAuth, logout } from '/static/js/auth.js';
import { apiRequest, showToast } from '/static/js/api.js';

document.addEventListener('DOMContentLoaded', async function () {
    if (!await checkAuth()) {
        return;
    }

    const usersTableBody = document.getElementById('usersTableBody');
    const userManagementSpinner = document.getElementById('userManagementSpinner');
    const userManagementTableContainer = document.getElementById('userManagementTableContainer');
    const noUsersMessage = document.getElementById('noUsersMessage');

    const editUserModal = new bootstrap.Modal(document.getElementById('editUserModal'));
    const editUserForm = document.getElementById('editUserForm');
    const editUsernameInput = document.getElementById('editUsername');
    const editFullNameInput = document.getElementById('editFullName');
    const editEmailInput = document.getElementById('editEmail');
    const editRoleSelect = document.getElementById('editRole');
    const editDisabledCheckbox = document.getElementById('editDisabled');
    const saveUserChangesBtn = document.getElementById('saveUserChangesBtn');
    const editUserErrorDiv = document.getElementById('editUserError');

    const changePasswordModal = new bootstrap.Modal(document.getElementById('changePasswordModal'));
    const changePasswordForm = document.getElementById('changePasswordForm');
    const passwordChangeUsernameSpan = document.getElementById('passwordChangeUsername');
    const changePasswordForUsernameInput = document.getElementById('changePasswordForUsername');
    const newPasswordInput = document.getElementById('newPassword');
    const confirmNewPasswordInput = document.getElementById('confirmNewPassword');
    const saveNewPasswordBtn = document.getElementById('saveNewPasswordBtn');
    const changePasswordErrorDiv = document.getElementById('changePasswordError');

    const addNewUserModal = new bootstrap.Modal(document.getElementById('addNewUserModal'));
    const addNewUserForm = document.getElementById('addNewUserForm');
    const newUsernameInput = document.getElementById('newUsername');
    const newFullNameInput = document.getElementById('newFullName');
    const newEmailInput = document.getElementById('newEmail');
    const newRoleSelect = document.getElementById('newRole');
    const newUserPasswordInput = document.getElementById('newUserPassword');
    const newUserConfirmPasswordInput = document.getElementById('newUserConfirmPassword');
    const saveNewUserBtn = document.getElementById('saveNewUserBtn');
    const addNewUserErrorDiv = document.getElementById('addNewUserError');
    const addNewUserBtn = document.getElementById('addNewUserBtn');
    
    const currentAdminUsername = document.body.dataset.username;
    const closeUserManagementPageBtn = document.getElementById('closeUserManagementPageBtn');


    /**
     * Fetch and display all users
     */
    async function fetchAndDisplayUsers() {
        userManagementSpinner.style.display = 'block';
        userManagementTableContainer.style.display = 'none';
        noUsersMessage.style.display = 'none';

        try {
            const users = await apiRequest('/api/admin/users', 'GET');

            usersTableBody.innerHTML = '';

            if (!users || users.length === 0) {
                noUsersMessage.style.display = 'block';
            } else {
                users.forEach(user => {
                    const row = usersTableBody.insertRow();
                    row.insertCell().textContent = user.username;
                    row.insertCell().textContent = user.full_name || 'N/A';
                    row.insertCell().textContent = user.email || 'N/A';
                    row.insertCell().textContent = user.role.charAt(0).toUpperCase() + user.role.slice(1);
                    
                    // Color cell with visual indicator
                    const colorCell = row.insertCell();
                    if (user.color) {
                        colorCell.innerHTML = `
                            <div class="d-flex align-items-center">
                                <div class="user-color-indicator me-2" 
                                     style="width: 20px; height: 20px; background-color: ${user.color}; border: 1px solid #ccc; border-radius: 3px;" 
                                     title="User color: ${user.color}"></div>
                                <small class="text-muted">${user.color}</small>
                            </div>
                        `;
                    } else {
                        colorCell.innerHTML = '<span class="text-muted">No color</span>';
                    }
                    
                    row.insertCell().innerHTML = user.disabled ? '<span class="badge bg-danger sm-badge">Disabled</span>' : '<span class="badge bg-success sm-badge">Active</span>';

                    const actionsCell = row.insertCell();
                    actionsCell.classList.add('action-buttons');

                    const editBtn = document.createElement('button');
                    editBtn.classList.add('btn', 'btn-sm', 'btn-outline-primary');
                    editBtn.textContent = 'Edit';
                    editBtn.onclick = () => openEditUserModal(user);
                    actionsCell.appendChild(editBtn);

                    const passwordBtn = document.createElement('button');
                    passwordBtn.classList.add('btn', 'btn-sm', 'btn-outline-warning');
                    passwordBtn.textContent = 'Password';
                    passwordBtn.onclick = () => openChangePasswordModal(user.username);
                    actionsCell.appendChild(passwordBtn);
                });
                userManagementTableContainer.style.display = 'block';
            }
        } catch (error) {
            usersTableBody.innerHTML = `<tr><td colspan="7" class="text-center text-danger">Error loading users: ${error.message}</td></tr>`;
            userManagementTableContainer.style.display = 'block';
            noUsersMessage.style.display = 'none';
        } finally {
            userManagementSpinner.style.display = 'none';
        }
    }

    function openEditUserModal(user) {
        editUserErrorDiv.style.display = 'none';
        editUserForm.reset();
        editUsernameInput.value = user.username;
        document.getElementById('editUserModalLabel').textContent = `Edit User: ${user.username}`;
        editFullNameInput.value = user.full_name || '';
        editEmailInput.value = user.email || '';
        editRoleSelect.value = user.role;
        editDisabledCheckbox.checked = user.disabled;

        // Disable role change and disable checkbox for the current admin if they are editing themselves
        // to prevent self-lockout from the last admin account.
        if (user.username === currentAdminUsername) {
             // Check if this is the only active admin
            const users = Array.from(usersTableBody.rows).map(row => ({
                username: row.cells[0].textContent,
                role: row.cells[3].textContent.toLowerCase(),
                disabled: row.cells[5].textContent === 'Disabled'
            }));
            const activeAdmins = users.filter(u => u.role === 'admin' && !u.disabled);
            if (activeAdmins.length <= 1) {
                editRoleSelect.disabled = true;
                editDisabledCheckbox.disabled = true;
                 editUserErrorDiv.textContent = "Cannot change role or disable the only active admin account.";
                 editUserErrorDiv.style.display = 'block';
            } else {
                editRoleSelect.disabled = false;
                editDisabledCheckbox.disabled = false;
            }
        } else {
            editRoleSelect.disabled = false;
            editDisabledCheckbox.disabled = false;
        }
        editUserModal.show();
    }

    saveUserChangesBtn.addEventListener('click', async () => {
        editUserErrorDiv.style.display = 'none';
        const username = editUsernameInput.value;
        const payload = {
            full_name: editFullNameInput.value || null,
            email: editEmailInput.value || null,
            role: editRoleSelect.value,
            disabled: editDisabledCheckbox.checked
        };

        try {
            await apiRequest(`/api/admin/users/${username}`, 'PUT', payload);
            showToast('User updated successfully', 'success');
            editUserModal.hide();
            fetchAndDisplayUsers(); // Refresh the list
        } catch (error) {
            showToast(`Error updating user: ${error.message}`, 'danger');
            editUserErrorDiv.textContent = error.message;
            editUserErrorDiv.style.display = 'block';
        }
    });

    function openChangePasswordModal(username) {
        changePasswordErrorDiv.style.display = 'none';
        changePasswordForm.reset();
        passwordChangeUsernameSpan.textContent = username;
        changePasswordForUsernameInput.value = username;
        changePasswordModal.show();
    }

    saveNewPasswordBtn.addEventListener('click', async () => {
        changePasswordErrorDiv.style.display = 'none';
        const username = changePasswordForUsernameInput.value;
        const newPassword = newPasswordInput.value;
        const confirmPassword = confirmNewPasswordInput.value;

        if (!newPassword || !confirmPassword) {
            changePasswordErrorDiv.textContent = 'Both password fields are required.';
            changePasswordErrorDiv.style.display = 'block';
            return;
        }
        if (newPassword !== confirmPassword) {
            changePasswordErrorDiv.textContent = 'Passwords do not match.';
            changePasswordErrorDiv.style.display = 'block';
            return;
        }
        if (newPassword.length < 6) { // Basic password policy
            changePasswordErrorDiv.textContent = 'Password must be at least 6 characters long.';
            changePasswordErrorDiv.style.display = 'block';
            return;
        }

        try {
            await apiRequest(`/api/admin/users/${username}/password`, 'PUT', { new_password: newPassword });
            showToast('Password changed successfully', 'success');
            changePasswordModal.hide();
            fetchAndDisplayUsers(); // Refresh the list
        } catch (error) {
            showToast(`Error changing password: ${error.message}`, 'danger');
            changePasswordErrorDiv.textContent = error.message;
            changePasswordErrorDiv.style.display = 'block';
        }
    });

    function openAddNewUserModal() {
        addNewUserErrorDiv.style.display = 'none';
        addNewUserForm.reset();
        addNewUserModal.show();
    }

    saveNewUserBtn.addEventListener('click', async () => {
        addNewUserErrorDiv.style.display = 'none';
        
        const username = newUsernameInput.value.trim();
        const fullName = newFullNameInput.value.trim();
        const email = newEmailInput.value.trim();
        const role = newRoleSelect.value;
        const password = newUserPasswordInput.value;
        const confirmPassword = newUserConfirmPasswordInput.value;

        // Validation
        if (!username) {
            addNewUserErrorDiv.textContent = 'Username is required.';
            addNewUserErrorDiv.style.display = 'block';
            return;
        }
        if (!password) {
            addNewUserErrorDiv.textContent = 'Password is required.';
            addNewUserErrorDiv.style.display = 'block';
            return;
        }
        if (password !== confirmPassword) {
            addNewUserErrorDiv.textContent = 'Passwords do not match.';
            addNewUserErrorDiv.style.display = 'block';
            return;
        }
        if (password.length < 6) {
            addNewUserErrorDiv.textContent = 'Password must be at least 6 characters long.';
            addNewUserErrorDiv.style.display = 'block';
            return;
        }

        const payload = {
            username: username,
            full_name: fullName || null,
            email: email || null,
            role: role,
            password: password
        };

        try {
            await apiRequest('/register', 'POST', payload);
            showToast('User created successfully', 'success');
            addNewUserModal.hide();
            fetchAndDisplayUsers(); // Refresh the list
        } catch (error) {
            showToast(`Error creating user: ${error.message}`, 'danger');
            addNewUserErrorDiv.textContent = error.message;
            addNewUserErrorDiv.style.display = 'block';
        }
    });

    // Event listener for the "Add New User" button
    if (addNewUserBtn) {
        addNewUserBtn.addEventListener('click', function() {
            openAddNewUserModal();
        });
    }

    // Event listener for the "Close Page" button
    if (closeUserManagementPageBtn) { // Keep close button as requested
        closeUserManagementPageBtn.addEventListener('click', function(event) {
            event.preventDefault(); // Prevent default anchor behavior if any
            window.close();
        });
    }

    // Initial load
    fetchAndDisplayUsers();
});
