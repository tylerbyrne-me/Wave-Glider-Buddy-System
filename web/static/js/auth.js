document.addEventListener('DOMContentLoaded', async function () { // Made async for getUserProfile
    const loginForm = document.getElementById('loginForm'); // Keep this
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

    // --- Banner-specific interactions (Logout, Username, Role-based buttons) ---
    const logoutBtnBanner = document.getElementById('logoutBtnBanner');
    if (logoutBtnBanner) {
        logoutBtnBanner.addEventListener('click', function(event) {
            event.preventDefault(); // Good practice for anchor tags acting as buttons
            logout();
        });
    }

    const usernameDisplayBanner = document.getElementById('usernameDisplayBanner');
    const viewFormsBtnBanner = document.getElementById('viewFormsBtnBanner');
    const registerUserBtnBanner = document.getElementById('registerUserBtnBanner');
    const userManagementBtnBanner = document.getElementById('userManagementBtnBanner');
    const missionSelectorBannerAuth = document.getElementById('missionSelectorBanner'); 
    const picHandoffNavDropdown = document.getElementById('picHandoffNavDropdown'); // New dropdown
    const submitNewPicHandoffLink = document.getElementById('submitNewPicHandoffLink');

    // Fetch user profile to update banner elements
    // Also used to determine which missions to show for pilots vs admin in mission dropdown
    // getUserProfile() is already async and defined below
    const currentUserForBanner = await getUserProfile(); 

    if (currentUserForBanner) {
        if (usernameDisplayBanner && currentUserForBanner.username) {
            usernameDisplayBanner.textContent = currentUserForBanner.username;
        }

        if (viewFormsBtnBanner) {
            if (currentUserForBanner.role === 'admin' || currentUserForBanner.role === 'pilot') {
                viewFormsBtnBanner.style.display = 'block';
            } else {
                viewFormsBtnBanner.style.display = 'none';
            }
        }
        if (currentUserForBanner.role === 'admin') {
            if (registerUserBtnBanner) registerUserBtnBanner.style.display = 'block';
            if (userManagementBtnBanner) userManagementBtnBanner.style.display = 'block';
        } else {
            if (registerUserBtnBanner) registerUserBtnBanner.style.display = 'none';
            if (userManagementBtnBanner) userManagementBtnBanner.style.display = 'none';
        }
        // Show PIC Handoff dropdown for pilot or admin
        if (picHandoffNavDropdown && (currentUserForBanner.role === 'pilot' || currentUserForBanner.role === 'admin')) {
            picHandoffNavDropdown.style.display = 'block';
        }
    } else { // No user logged in, ensure role-specific buttons are hidden
        if (viewFormsBtnBanner) viewFormsBtnBanner.style.display = 'none';
        if (registerUserBtnBanner) registerUserBtnBanner.style.display = 'none';
        if (userManagementBtnBanner) userManagementBtnBanner.style.display = 'none';
    }

    // --- Populate Mission Selector in Banner (if present on the page) ---
    if (missionSelectorBannerAuth) {
        const pageMissionId = document.body.dataset.missionId; // Available on index.html, mission_form.html etc.

        try {
            const response = await fetchWithAuth('/api/available_missions');
            if (response.ok) {
                const missions = await response.json();
                missionSelectorBannerAuth.innerHTML = ''; // Clear existing options

                if (missions.length === 0) {
                    const option = document.createElement('option');
                    option.value = "";
                    option.textContent = "No missions";
                    missionSelectorBannerAuth.appendChild(option);
                    missionSelectorBannerAuth.disabled = true;
                } else {
                    missionSelectorBannerAuth.disabled = false;
                    let missionSelected = false;
                    missions.forEach(m_id => {
                        const option = document.createElement('option');
                        option.value = m_id;
                        option.textContent = m_id;
                        if (pageMissionId && m_id === pageMissionId) {
                            option.selected = true;
                            missionSelected = true;
                        }
                        missionSelectorBannerAuth.appendChild(option);
                    });
                    // If no specific mission was selected (e.g., on view_forms.html),
                    // and there are missions, select the first one by default.
                    if (!missionSelected && missions.length > 0 && missionSelectorBannerAuth.options.length > 0) {
                        missionSelectorBannerAuth.options[0].selected = true;
                    }
                }
            } else {
                console.error('Failed to fetch available missions for banner in auth.js. Status:', response.status);
                missionSelectorBannerAuth.innerHTML = '<option value="">Error</option>';
                missionSelectorBannerAuth.disabled = true;
            }
        } catch (error) {
            console.error('Error fetching missions for banner in auth.js:', error);
            missionSelectorBannerAuth.innerHTML = '<option value="">Error</option>';
            missionSelectorBannerAuth.disabled = true;
        }

        // Add event listener for mission change on non-index pages
        // On index.html, dashboard.js handles the full page reload.
        // For other pages, we might just update links or specific content.
        if (window.location.pathname !== '/') {
            missionSelectorBannerAuth.addEventListener('change', function() { // Ensure this listener is added only once
                const selectedMission = this.value;
                if (selectedMission && submitNewPicHandoffLink) {
                    const defaultFormType = "pic_handoff_checklist";
                    submitNewPicHandoffLink.href = `/mission/${selectedMission}/form/${defaultFormType}.html`;
                    submitNewPicHandoffLink.classList.remove('disabled');
                }
                // If the current page IS mission-specific (like mission_form.html), it should reload.
                if (document.body.dataset.missionId && window.location.pathname.includes('/mission/')) {
                     const currentUrl = new URL(window.location.href);
                     currentUrl.pathname = currentUrl.pathname.replace(document.body.dataset.missionId, selectedMission);
                     window.location.href = currentUrl.toString();
                } else if (!selectedMission && submitNewPicHandoffLink) {
                    submitNewPicHandoffLink.href = "#";
                    submitNewPicHandoffLink.classList.add('disabled');
                }
            });
        }
    }

    // Update "Submit New PIC Handoff" link initially on all pages
    if (submitNewPicHandoffLink) {
        const initialMissionForPicLink = missionSelectorBannerAuth?.value || document.body.dataset.missionId;
        if (initialMissionForPicLink) {
            const defaultFormType = "pic_handoff_checklist";
            submitNewPicHandoffLink.href = `/mission/${initialMissionForPicLink}/form/${defaultFormType}.html`;
            submitNewPicHandoffLink.classList.remove('disabled');
        } else {
            submitNewPicHandoffLink.href = "#"; // Default if no mission context at all
            submitNewPicHandoffLink.classList.add('disabled');
        }
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


async function fetchWithAuth(url, options = {}) {
    const token = getAuthToken();
    options.headers = { ...options.headers }; // Ensure headers object exists
    if (token) {
        options.headers['Authorization'] = `Bearer ${token}`;
    } else if (!options.allowAnonymous) { // allowAnonymous can be a custom flag for public endpoints
        console.warn(`fetchWithAuth: No token for ${url}, and not an anonymous request. Server will likely reject if auth is needed.`);
        // Consider throwing an error or redirecting if a token is strictly required for the call
        // For now, let it proceed; the server will handle unauthorized access.
    }
    return fetch(url, options);
}

async function getUserProfile() {
    const token = getAuthToken();
    if (!token) {
        // console.log("getUserProfile: No token found. User is not authenticated.");
        return null;
    }
    try {
        const response = await fetchWithAuth('/api/users/me'); // Standard endpoint for current user info
        if (!response.ok) {
            if (response.status === 401) { // Unauthorized or token expired
                console.warn('getUserProfile: Unauthorized. Token might be invalid or expired. Logging out.');
                logout(); // Force logout if token is bad
            } else {
                console.error('Error fetching user profile:', response.status, await response.text());
            }
            return null;
        }
        return await response.json();
    } catch (error) {
        console.error('Network or other error fetching user profile:', error);
        return null;
    }
}