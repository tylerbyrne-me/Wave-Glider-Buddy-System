/**
 * @file api.js
 * @description A shared module for API requests and UI utilities.
 * This module centralizes API communication, providing a consistent
 * way to handle authenticated requests and display user feedback.
 */

/**
 * Shows a Bootstrap toast notification.
 * @param {string} message - The message to display in the toast.
 * @param {string} [type='success'] - The type of toast ('success' or 'danger').
 */
export const showToast = (message, type = 'success') => {
    const toastContainer = document.getElementById('toast-container');
    if (!toastContainer) {
        console.error('Toast container not found. Please add `<div id="toast-container" class="toast-container position-fixed top-0 end-0 p-3"></div>` to your base HTML.');
        return;
    }
    const toastId = `toast-${Date.now()}`;
    const toastHTML = `
        <div id="${toastId}" class="toast align-items-center text-white bg-${type === 'success' ? 'success' : 'danger'} border-0" role="alert" aria-live="assertive" aria-atomic="true">
            <div class="d-flex">
                <div class="toast-body">${message}</div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
            </div>
        </div>
    `;
    toastContainer.insertAdjacentHTML('beforeend', toastHTML);
    const toastEl = document.getElementById(toastId);
    const toast = new bootstrap.Toast(toastEl, { delay: 5000 });
    toast.show();
    toastEl.addEventListener('hidden.bs.toast', () => toastEl.remove());
};

/**
 * Makes an authenticated API request.
 * Handles token retrieval, headers, and standardized error handling.
 * @param {string} url - The API endpoint URL.
 * @param {string} method - The HTTP method (e.g., 'GET', 'POST', 'PUT', 'DELETE').
 * @param {Object|null} [body=null] - The request body for POST/PUT requests.
 * @returns {Promise<any>} A promise that resolves with the JSON response body.
 * @throws {Error} Throws an error if the request fails, with the message from the server.
 */
export const apiRequest = async (url, method, body = null) => {
    const token = localStorage.getItem('accessToken');
    const headers = {
        'Content-Type': 'application/json',
    };
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }

    const options = { method, headers };
    if (body) {
        options.body = JSON.stringify(body);
    }

    const response = await fetch(url, options);

    if (response.status === 401) {
        localStorage.removeItem('accessToken');
        window.location.href = '/login.html?session_expired=true';
        throw new Error('Session expired. Redirecting to login.');
    }

    if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: 'An unknown error occurred.' }));
        throw new Error(errorData.detail || `HTTP error! Status: ${response.status}`);
    }

    return response.status === 204 ? null : await response.json();
};

/**
 * Makes a fetch request with credentials included (for cookie-based auth).
 * @param {string} url - The API endpoint URL.
 * @param {Object} [options={}] - Fetch options (method, headers, etc.).
 * @returns {Promise<Response>} The fetch response promise.
 */
export const fetchWithAuth = (url, options = {}) => {
    return fetch(url, { ...options, credentials: 'include' });
};

/**
 * Escapes HTML to prevent XSS attacks.
 * @param {string} str - The string to escape.
 * @returns {string} The escaped string.
 */
export const escapeHTML = (str) => {
    if (str === null || str === undefined) return '';
    return str.toString().replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#039;');
};