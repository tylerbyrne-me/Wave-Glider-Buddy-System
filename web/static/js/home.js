document.addEventListener('DOMContentLoaded', async function() {
    // --- Authentication Check ---
    if (!checkAuth()) { // checkAuth is from auth.js
        return; // Stop further execution if not authenticated
    }

    // Initialize all panels
    initializeUpcomingShiftsPanel();
    initializeAnnouncementsPanelWithRefresh();
    initializeTimesheetStatusPanel();
});

function initializeAnnouncementsPanelWithRefresh() {
    const announcementsPanel = document.getElementById('announcementsPanel');
    if (!announcementsPanel) {
        console.warn("home.js: 'announcementsPanel' div not found.");
        return;
    }
    const markdownConverter = new showdown.Converter();

    // --- Function to fetch and render announcements ---
    const fetchAndRenderAnnouncements = async () => {
        try {
            const response = await fetchWithAuth('/api/announcements/active');
            if (!response.ok) {
                throw new Error(`Failed to fetch announcements: ${response.status}`);
            }
            const announcements = await response.json();

            // Filter out announcements that the user has already acknowledged.
            const unacknowledgedAnnouncements = announcements.filter(ann => !ann.is_acknowledged_by_user);

            if (unacknowledgedAnnouncements.length === 0) {
                announcementsPanel.innerHTML = ''; // Clear the panel if no announcements
                return;
            }

            let announcementsHtml = '';
            unacknowledgedAnnouncements.forEach(ann => {
                const contentHtml = markdownConverter.makeHtml(ann.content);
                // Since we only show unacknowledged items, this will always be a button.
                const ackButtonHtml = `<button class="btn btn-sm btn-outline-success ack-btn" data-id="${ann.id}">Acknowledge &amp; Clear</button>`;

                announcementsHtml += `
                    <div class="alert alert-info" role="alert" id="announcement-${ann.id}">
                        <div class="d-flex justify-content-between align-items-start">
                            <div>
                                <h5 class="alert-heading">Announcement</h5>
                                <div class="announcement-content">${contentHtml}</div>
                                <p class="mb-0 small text-muted">Posted by ${ann.created_by_username} on ${new Date(ann.created_at_utc).toLocaleDateString()}</p>
                            </div>
                            <div class="ack-container ms-3">
                                ${ackButtonHtml}
                            </div>
                        </div>
                    </div>
                `;
            });
            announcementsPanel.innerHTML = announcementsHtml;

        } catch (error) {
            console.error("Error refreshing announcements:", error);
            // Avoid overwriting content with an error if it's just a background refresh fail
            if (!announcementsPanel.hasChildNodes() || announcementsPanel.querySelector('.spinner-border')) {
                 announcementsPanel.innerHTML = `<div class="alert alert-warning">Could not load announcements.</div>`;
            }
        }
    };

    // --- Event listener for Acknowledge buttons (Event Delegation) ---
    announcementsPanel.addEventListener('click', async function(e) {
        if (e.target.classList.contains('ack-btn')) {
            const button = e.target;
            const annId = button.dataset.id;
            button.disabled = true; // Prevent double-clicks
            button.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Acknowledging...';

            try {
                const response = await fetchWithAuth(`/api/announcements/${annId}/ack`, { method: 'POST' });
                if (!response.ok) throw new Error('Failed to acknowledge.');
                
                // On success, fade out and remove the announcement from the view.
                const announcementCard = document.getElementById(`announcement-${annId}`);
                if (announcementCard) {
                    announcementCard.style.transition = 'opacity 0.5s ease';
                    announcementCard.style.opacity = '0';
                    setTimeout(() => {
                        announcementCard.remove();
                        // If this was the last announcement, the panel will be empty.
                        if (announcementsPanel.childElementCount === 0) {
                            announcementsPanel.innerHTML = '';
                        }
                    }, 500);
                }
            } catch (error) {
                alert(`Error: ${error.message}`);
                button.disabled = false; // Re-enable button on failure
                button.innerHTML = 'Acknowledge & Clear';
            }
        }
    });

    // --- Initial Load and Auto-Refresh Timer ---
    fetchAndRenderAnnouncements(); // Initial call to load data
    const refreshInterval = 5 * 60 * 1000; // 5 minutes in milliseconds
    setInterval(fetchAndRenderAnnouncements, refreshInterval);
}

async function initializeTimesheetStatusPanel() {
    const statusDiv = document.getElementById('timesheetStatusContent');
    if (!statusDiv) return;

    try {
        const response = await fetchWithAuth('/api/timesheets/my_status');
        if (!response.ok) throw new Error('Failed to fetch timesheet statuses.');

        const statuses = await response.json();

        if (statuses.length === 0) {
            statusDiv.innerHTML = '<p class="text-muted small text-center">No recent timesheet submissions.</p>';
            return;
        }

        let html = '<ul class="list-group list-group-flush">';
        statuses.forEach(ts => {
            let statusBadge;
            let notesHtml = '';
            switch (ts.status) {
                case 'submitted':
                    statusBadge = '<span class="badge bg-primary">Submitted</span>';
                    break;
                case 'approved':
                    statusBadge = '<span class="badge bg-success">Approved</span>';
                    break;
                case 'rejected':
                    statusBadge = '<span class="badge bg-danger">Rejected</span>';
                    if (ts.reviewer_notes) {
                        notesHtml = `<div class="small text-muted mt-1 fst-italic"><strong>Reason:</strong> ${ts.reviewer_notes}</div>`;
                    }
                    break;
            }
            html += `
                <li class="list-group-item p-2">
                    <div class="d-flex justify-content-between align-items-start">
                        <div class="fw-bold">${ts.pay_period_name}</div>
                        ${statusBadge}
                    </div>
                    ${notesHtml}
                </li>
            `;
        });
        html += '</ul>';
        statusDiv.innerHTML = html;

    } catch (error) {
        console.error("Error fetching timesheet statuses:", error);
        statusDiv.innerHTML = `<p class='text-danger small'>Error loading statuses.</p>`;
    }
}

async function initializeUpcomingShiftsPanel() {
    const upcomingShiftsDiv = document.getElementById('upcomingShiftsContent');
    if (!upcomingShiftsDiv) {
        console.warn("home.js: 'upcomingShiftsContent' div not found. Skipping panel initialization.");
        return;
    }

    try {
        const currentUser = await getUserProfile(); // from auth.js
        if (!currentUser || !currentUser.username) {
            upcomingShiftsDiv.innerHTML = "<p class='text-muted small'>Please log in to view your shifts.</p>";
            return;
        }

        const today = new Date();
        const futureDate = new Date(today.getTime() + 30 * 24 * 60 * 60 * 1000); // Next 30 days

        const apiUrl = `/api/schedule/events?start=${today.toISOString()}&end=${futureDate.toISOString()}`;
        
        const response = await fetchWithAuth(apiUrl); // from auth.js
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ detail: "Unknown error fetching shifts." }));
            throw new Error(`Failed to fetch shifts: ${response.status} - ${errorData.detail}`);
        }

        const events = await response.json();
        const upcomingShifts = events
            .filter(event => event.type === 'shift' && event.text === currentUser.username)
            .sort((a, b) => new Date(a.start) - new Date(b.start));

        if (upcomingShifts.length > 0) {
            let shiftsHtml = '<ul class="list-group list-group-flush">';
            upcomingShifts.forEach(shift => {
                const startDate = new Date(shift.start);
                const endDate = new Date(shift.end);
                const dateString = startDate.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
                const timeString = `${startDate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} - ${endDate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
                shiftsHtml += `<li class="list-group-item d-flex justify-content-between align-items-center p-2"><div><div class="fw-bold">${dateString}</div><div class="small text-muted">${timeString}</div></div></li>`;
            });
            shiftsHtml += '</ul>';
            upcomingShiftsDiv.innerHTML = shiftsHtml;
        } else {
            upcomingShiftsDiv.innerHTML = "<p class='text-muted small text-center'>No upcoming shifts in the next 30 days.</p>";
        }
    } catch (error) {
        console.error("Error fetching upcoming shifts:", error);
        upcomingShiftsDiv.innerHTML = `<p class='text-danger small'>Error loading shifts: ${error.message}</p>`;
    }
}