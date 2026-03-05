/**
 * @file api.js
 * @description A shared module for API requests and UI utilities.
 * This module centralizes API communication, providing a consistent
 * way to handle authenticated requests and display user feedback.
 */

/** Redirects to login with session_expired and next params. Used by apiRequest and fetchWithAuth. */
const redirectToLoginOn401 = () => {
    localStorage.removeItem('accessToken');
    const nextParam = encodeURIComponent(window.location.pathname + window.location.search);
    window.location.href = `/login.html?session_expired=true&next=${nextParam}`;
};

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
 * Current platform for Knowledge Base (wave_glider or slocum). Set by base template as window.APP_PLATFORM.
 * @returns {string}
 */
export const getPlatform = () => (typeof window !== 'undefined' && window.APP_PLATFORM) ? window.APP_PLATFORM : 'wave_glider';

/**
 * Appends platform query parameter to a URL for KB API calls.
 * @param {string} url - Base URL (may already have query params).
 * @returns {string}
 */
export const appendPlatformParam = (url) => {
    const sep = url.includes('?') ? '&' : '?';
    return `${url}${sep}platform=${encodeURIComponent(getPlatform())}`;
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

    const options = { method, headers, credentials: 'include' };
    if (body) {
        options.body = JSON.stringify(body);
    }

    const response = await fetch(url, options);

    if (response.status === 401) {
        redirectToLoginOn401();
        throw new Error('Session expired. Redirecting to login.');
    }

    if (!response.ok) {
        let errorMessage = `HTTP error! Status: ${response.status}`;
        try {
            const errorData = await response.json();
            console.error('API Error Response:', errorData);
            // Handle different error response formats
            if (typeof errorData === 'string') {
                errorMessage = errorData;
            } else if (errorData && typeof errorData === 'object') {
                // FastAPI validation errors have a specific structure
                if (Array.isArray(errorData.detail)) {
                    // Validation errors
                    const validationErrors = errorData.detail.map(err => 
                        `${err.loc?.join('.')}: ${err.msg}`
                    ).join('; ');
                    errorMessage = `Validation error: ${validationErrors}`;
                } else {
                    errorMessage = errorData.detail || errorData.message || errorData.error || JSON.stringify(errorData);
                }
            }
        } catch (e) {
            // If JSON parsing fails, try to get text
            try {
                const text = await response.text();
                errorMessage = text || errorMessage;
            } catch (textError) {
                // Use default error message
            }
        }
        throw new Error(errorMessage);
    }

    return response.status === 204 ? null : await response.json();
};

/**
 * Returns headers object with Bearer token if present. Use for one-off fetch calls that need auth.
 * Prefer apiRequest() or fetchWithAuth() so 401 handling and credentials are consistent.
 */
export const getAuthHeaders = () => {
    const token = localStorage.getItem('accessToken');
    const headers = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;
    return headers;
};

/**
 * Makes a fetch request with auth (Bearer + credentials) and consistent 401 handling.
 * Use for FormData, blob, or other non-JSON requests. On 401, redirects to login with next= and throws.
 * @param {string} url - The API endpoint URL.
 * @param {Object} [options={}] - Fetch options (method, headers, body, etc.). Headers are merged with auth.
 * @returns {Promise<Response>} The fetch response promise (caller should check response.ok and handle 401 only if not redirected).
 */
export const fetchWithAuth = async (url, options = {}) => {
    const token = localStorage.getItem('accessToken');
    const headers = new Headers(options.headers || {});
    if (token && !headers.has('Authorization')) {
        headers.set('Authorization', `Bearer ${token}`);
    }
    const response = await fetch(url, { ...options, headers, credentials: 'include' });
    if (response.status === 401) {
        redirectToLoginOn401();
        throw new Error('Session expired. Redirecting to login.');
    }
    return response;
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