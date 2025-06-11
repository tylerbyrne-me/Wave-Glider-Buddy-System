document.addEventListener('DOMContentLoaded', function () {
    const loginForm = document.getElementById('loginForm');
    const loginErrorDiv = document.getElementById('loginError');
    const registerForm = document.getElementById('registerForm');
    const registerMessageDiv = document.getElementById('registerMessage');

    if (loginForm) {
        loginForm.addEventListener('submit', async function (event) {
            event.preventDefault();
            if (loginErrorDiv) loginErrorDiv.style.display = 'none';

            const username = loginForm.username.value;
            const password = loginForm.password.value;

            const formData = new FormData();
            formData.append('username', username);
            formData.append('password', password);

            try {
                const response = await fetch('/token', {
                    method: 'POST',
                    body: formData,
                });

                if (response.ok) {
                    const data = await response.json();
                    localStorage.setItem('accessToken', data.access_token);
                    // Redirect to the main dashboard or the page they were trying to access
                    window.location.href = '/';
                } else {
                    const errorData = await response.json();
                    const detail = errorData.detail || `Login failed (Status: ${response.status})`;
                    if (loginErrorDiv) {
                        loginErrorDiv.textContent = detail;
                        loginErrorDiv.style.display = 'block';
                    } else {
                        alert(detail); // Fallback if error div is not present
                    }
                    console.error('Login failed:', detail);
                }
            } catch (error) {
                console.error('Network error during login:', error);
                if (loginErrorDiv) {
                    loginErrorDiv.textContent = 'Network error. Please try again.';
                    loginErrorDiv.style.display = 'block';
                } else {
                    alert('Network error. Please try again.');
                }
            }
        });
    }

    if (registerForm) {
        registerForm.addEventListener('submit', async function(event) {
            event.preventDefault();
            if (registerMessageDiv) {
                registerMessageDiv.style.display = 'none';
                registerMessageDiv.classList.remove('alert-success', 'alert-danger');
            }

            const username = registerForm.username.value;
            const email = registerForm.email.value;
            const fullName = registerForm.fullName.value;
            const password = registerForm.password.value;
            const confirmPassword = registerForm.confirmPassword.value;

            if (password !== confirmPassword) {
                if (registerMessageDiv) {
                    registerMessageDiv.textContent = 'Passwords do not match.';
                    registerMessageDiv.classList.add('alert-danger');
                    registerMessageDiv.style.display = 'block';
                } else {
                    alert('Passwords do not match.');
                }
                return;
            }

            const userData = {
                username: username,
                email: email,
                full_name: fullName || null, // Send null if empty
                password: password
                // Role defaults to 'pilot' on the backend via Pydantic model
            };

            try {
                const response = await fetchWithAuth('/register', { // Use fetchWithAuth
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        // fetchWithAuth will add the Authorization header
                    },
                    body: JSON.stringify(userData),
                });

                const responseData = await response.json();

                if (response.ok) {
                    if (registerMessageDiv) {
                        registerMessageDiv.textContent = 'Registration successful! Redirecting to login...';
                        registerMessageDiv.classList.add('alert-success');
                        registerMessageDiv.style.display = 'block';
                    }
                    setTimeout(() => { window.location.href = '/login.html'; }, 2000);
                } else {
                    const detail = responseData.detail || `Registration failed (Status: ${response.status})`;
                    if (registerMessageDiv) {
                        registerMessageDiv.textContent = detail;
                        registerMessageDiv.classList.add('alert-danger');
                        registerMessageDiv.style.display = 'block';
                    } else { alert(detail); }
                    console.error('Registration failed:', detail);
                }
            } catch (error) {
                console.error('Network error during registration:', error);
                if (registerMessageDiv) {
                    registerMessageDiv.textContent = 'Network error. Please try again.';
                    registerMessageDiv.classList.add('alert-danger');
                    registerMessageDiv.style.display = 'block';
                } else { alert('Network error. Please try again.');}
            }
        });
    }
});

// --- Global Auth Functions ---

function getAuthToken() {
    return localStorage.getItem('accessToken');
}

function checkAuth() {
    const token = getAuthToken();
    // If no token and not on login page, redirect to login
    if (!token && window.location.pathname !== '/login.html') {
        // Store the current path to redirect back after login, if desired
        // localStorage.setItem('redirectAfterLogin', window.location.pathname + window.location.search);
        window.location.href = '/login.html';
        return false;
    }
    // If on login page and token exists, redirect to dashboard
    if (token && window.location.pathname === '/login.html') {
        window.location.href = '/';
        return true; // Or false, as we are redirecting away
    }
    return !!token; // Returns true if token exists, false otherwise
}

function logout() {
    localStorage.removeItem('accessToken');
    // Also consider clearing other session-related data if any
    window.location.href = '/login.html';
}

// Helper function to add Authorization header to fetch requests
async function fetchWithAuth(url, options = {}) {
    const token = getAuthToken();
    options.headers = { ...options.headers, 'Authorization': `Bearer ${token}` };
    return fetch(url, options);
}