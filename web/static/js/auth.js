import { apiRequest, showToast } from '/static/js/api.js';

document.addEventListener('DOMContentLoaded', async function () { // Made async for getUserProfile
    // --- Theme Switcher Logic ---
    // This is placed at the top to run immediately and prevent a flash of unstyled content (FOUC).
    const themeSwitch = document.getElementById('themeSwitch');
    const htmlEl = document.documentElement;

    const getPreferredTheme = () => {
        if (localStorage.getItem('theme')) {
            return localStorage.getItem('theme');
        }
        // Default to dark theme if no preference is set
        return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
    };

    const setTheme = (theme) => {
        htmlEl.setAttribute('data-bs-theme', theme);
        if (themeSwitch) {
            themeSwitch.checked = (theme === 'dark');
        }
        localStorage.setItem('theme', theme);
    };

    // Set the initial theme when the page loads
    setTheme(getPreferredTheme());

    // Add a listener for the toggle switch
    if (themeSwitch) {
        themeSwitch.addEventListener('change', () => {
            setTheme(themeSwitch.checked ? 'dark' : 'light');
        });
    }

    // --- Global UTC Clock in Banner ---
    // This function is placed here in auth.js to run on every page.
    // It's moved to the top of the listener to ensure it runs immediately
    // without waiting for async operations like fetching user profiles.
    function updateUtcClockBanner() {
        const clockElement = document.getElementById('utcClockBanner');
        if (clockElement) {
            const now = new Date();
            const year = now.getUTCFullYear();
            const month = String(now.getUTCMonth() + 1).padStart(2, '0');
            const day = String(now.getUTCDate()).padStart(2, '0');
            const hours = String(now.getUTCHours()).padStart(2, '0');
            const minutes = String(now.getUTCMinutes()).padStart(2, '0');
            const seconds = String(now.getUTCSeconds()).padStart(2, '0');
            
            clockElement.textContent = `${year}-${month}-${day} ${hours}:${minutes}:${seconds} UTC`;
        }
    }
    // Initialize clock immediately and set interval
    updateUtcClockBanner();
    setInterval(updateUtcClockBanner, 1000);

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

            // Use URLSearchParams to send form data as required by OAuth2PasswordRequestForm
            const formData = new URLSearchParams();
            formData.append('username', username);
            formData.append('password', password);

            try {
                const response = await fetch('/token', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded',
                    },
                    body: formData,
                });

                if (response.ok) {
                    const data = await response.json();
                    localStorage.setItem('accessToken', data.access_token);
                    // Redirect to the new home page
                    window.location.href = '/home.html';
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
                const response = await apiRequest('/register', 'POST', {
                    method: 'POST',
                }); // Use fetchWithAuth

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
    const missionSelectorDropdownMenu = document.getElementById('missionSelectorDropdownMenu'); // New dropdown menu for missions
    const submitNewPicHandoffLink = document.getElementById('submitNewPicHandoffLink');

    // Fetch user profile to update banner elements
    // Also used to determine which missions to show for pilots vs admin in mission dropdown
    // getUserProfile() is already async and defined below
    const currentUserForBanner = await getUserProfile(); 

    if (currentUserForBanner) {
        if (usernameDisplayBanner && currentUserForBanner.username) {
            usernameDisplayBanner.textContent = currentUserForBanner.username;
        }

        // Admin Management Dropdown
        const adminManagementDropdown = document.getElementById('adminManagementDropdown');
        if (adminManagementDropdown) {
            adminManagementDropdown.style.display = (currentUserForBanner.role === 'admin') ? 'block' : 'none';
        }
        if (viewFormsBtnBanner) {
            // This is now part of Admin Management dropdown, so its individual display is handled by that.
        }
        if (currentUserForBanner.role === 'admin') {
            if (registerUserBtnBanner) registerUserBtnBanner.style.display = 'block';
            if (userManagementBtnBanner) userManagementBtnBanner.style.display = 'block';
        } else {
            if (registerUserBtnBanner) registerUserBtnBanner.style.display = 'none';
            if (userManagementBtnBanner) userManagementBtnBanner.style.display = 'none';
        }

        // PIC Management Dropdown
        const picManagementDropdown = document.getElementById('picManagementDropdown');
        if (picManagementDropdown) {
            picManagementDropdown.style.display = (currentUserForBanner.role === 'pilot' || currentUserForBanner.role === 'admin') ? 'block' : 'none';
        }

        // Payroll Dropdown
        const payrollDropdown = document.getElementById('payrollDropdown');
        if (payrollDropdown) {
            payrollDropdown.style.display = (currentUserForBanner.role === 'pilot' || currentUserForBanner.role === 'admin') ? 'block' : 'none';
        }
    } else { // No user logged in, ensure role-specific buttons are hidden
        if (viewFormsBtnBanner) viewFormsBtnBanner.style.display = 'none';
        if (registerUserBtnBanner) registerUserBtnBanner.style.display = 'none';
        if (userManagementBtnBanner) userManagementBtnBanner.style.display = 'none';
        if (document.getElementById('adminManagementDropdown')) document.getElementById('adminManagementDropdown').style.display = 'none';
        if (document.getElementById('picManagementDropdown')) document.getElementById('picManagementDropdown').style.display = 'none';
        if (document.getElementById('payrollDropdown')) document.getElementById('payrollDropdown').style.display = 'none';
    }

    // --- Populate Mission Selector in Banner (if present on the page) ---
    if (missionSelectorDropdownMenu) {
        const pageMissionId = document.body.dataset.missionId; // Available on index.html, mission_form.html etc.

        try {
            const missions = await apiRequest('/api/available_missions', 'GET');
            missionSelectorDropdownMenu.innerHTML = '';
            if (missions.length === 0) {
                const option = document.createElement('option');
                option.value = "";
                option.textContent = "No missions";
                missionSelectorDropdownMenu.appendChild(option);
                missionSelectorDropdownMenu.disabled = true;
                // Also disable the dropdown toggle if no missions
                document.getElementById('missionDashboardDropdown').classList.add('disabled');
            } else {
                missions.forEach(m_id => {
                    const listItem = document.createElement('li');
                    const link = document.createElement('a');
                    link.classList.add('dropdown-item');
                    link.href = `/?mission=${m_id}`; // Link to dashboard with selected mission
                    link.textContent = m_id;
                    if (pageMissionId && m_id === pageMissionId) {
                        link.classList.add('active'); // Highlight active mission
                    }
                    listItem.appendChild(link);
                    missionSelectorDropdownMenu.appendChild(listItem);
                });
            }
        } catch (error) {
            console.error('Error fetching missions for banner in auth.js:', error);
            missionSelectorDropdownMenu.innerHTML = '<option value="">Error</option>';
            missionSelectorDropdownMenu.disabled = true;
        }

        // Update "Submit New PIC Handoff" link when mission changes (for non-dashboard pages)
        // For dashboard, mission selection reloads the page, so this is for other pages.
        // This listener is on the dropdown menu itself, not the individual links.
        missionSelectorDropdownMenu.addEventListener('click', function(event) {
            const targetLink = event.target.closest('.dropdown-item');
            if (targetLink && targetLink.href.includes('/?mission=')) {
                const newMissionId = new URL(targetLink.href).searchParams.get('mission');
                updateSubmitNewPicHandoffLink(newMissionId);
            }
        });

        // Initial update of the "Submit New PIC Handoff" link
        updateSubmitNewPicHandoffLink(pageMissionId);
    }

    function updateSubmitNewPicHandoffLink(missionId) {
        if (submitNewPicHandoffLink) {
            const defaultFormType = "pic_handoff_checklist";
            if (missionId) {
                submitNewPicHandoffLink.href = `/mission/${missionId}/form/${defaultFormType}.html`;
                submitNewPicHandoffLink.target = "_blank"; // Open in new tab
                submitNewPicHandoffLink.classList.remove('disabled');
            } else {
                submitNewPicHandoffLink.href = "#";
                submitNewPicHandoffLink.target = "_self"; // Default to same tab
                submitNewPicHandoffLink.classList.add('disabled');
            }
        }
    }
});

// --- Global Auth Functions ---

function getAuthToken() {
    return localStorage.getItem('accessToken');
}

async function checkAuth() {
    try {
        // Try to fetch user profile (will use cookie if present)
        const user = await apiRequest('/api/users/me', 'GET');
        if (window.location.pathname === '/login.html') {
            window.location.href = '/home.html';
            return true;
        }
        return true;
    } catch (error) {
        // Not authenticated, redirect to login
        if (window.location.pathname !== '/login.html') {
            window.location.href = '/login.html';
        }
        return false;
    }
}

async function logout() {
    localStorage.removeItem('accessToken');
    try {
        // Call the server to clear the HttpOnly cookie
        await fetch('/logout', { method: 'POST' });
    } catch (error) {
        // Log the error but proceed with client-side logout anyway
        console.error("Failed to call server logout endpoint, but proceeding with client-side logout.", error);
    }
    // Redirect to login page
    window.location.href = '/login.html';
}


async function getUserProfile() {
    const token = getAuthToken();
    if (!token) {
        // console.log("getUserProfile: No token found. User is not authenticated.");
        return null;
    }
    try {
        const user = await apiRequest('/api/users/me', 'GET'); // apiRequest returns parsed JSON or throws
        return user;
    } catch (error) {
        // If error is due to 401, apiRequest already redirects and removes token
        console.error('Network or other error fetching user profile:', error);
        return null;
    }
}

export { checkAuth, logout, getUserProfile, getAuthToken };