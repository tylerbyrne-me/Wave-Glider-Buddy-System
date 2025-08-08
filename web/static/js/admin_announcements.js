import { checkAuth } from '/static/js/auth.js';
import { fetchWithAuth } from '/static/js/api.js';

document.addEventListener('DOMContentLoaded', function() {
    if (!checkAuth()) return;

    // --- Element References ---
    const createForm = document.getElementById('createAnnouncementForm');
    const contentInput = document.getElementById('announcementContent');
    const createStatusDiv = document.getElementById('createStatus');
    const listContainer = document.getElementById('announcementsListContainer');
    
    // Modals
    const acknowledgedByModal = new bootstrap.Modal(document.getElementById('acknowledgedByModal'));
    const acknowledgedByList = document.getElementById('acknowledgedByList');
    const editAnnouncementModal = new bootstrap.Modal(document.getElementById('editAnnouncementModal'));
    const editAnnouncementIdInput = document.getElementById('editAnnouncementId');
    const editAnnouncementContentInput = document.getElementById('editAnnouncementContent');
    const saveChangesBtn = document.getElementById('saveAnnouncementChangesBtn');
    const editStatusDiv = document.getElementById('editStatus');

    const markdownConverter = new showdown.Converter();

    let announcementsMap = {}; // To store full announcement objects by ID

    async function loadAnnouncements() {
        try {
            const response = await fetchWithAuth('/api/admin/announcements/all');
            if (!response.ok) throw new Error('Failed to fetch announcements.');
            
            const announcements = await response.json();
            // Store announcements in a map for easy access by the edit function
            announcementsMap = {};
            announcements.forEach(ann => { announcementsMap[ann.id] = ann; });
            renderAnnouncements(announcements);
        } catch (error) {
            listContainer.innerHTML = `<div class="alert alert-danger">${error.message}</div>`;
        }
    }

    function renderAnnouncements(announcements) {
        if (announcements.length === 0) {
            listContainer.innerHTML = '<p class="text-muted">No announcements have been posted.</p>';
            return;
        }

        let html = '<div class="list-group">';
        announcements.forEach(ann => {
            const contentHtml = markdownConverter.makeHtml(ann.content);
            const ackCount = ann.acknowledged_by.length;
            const statusBadge = ann.is_active 
                ? '<span class="badge bg-success">Active</span>' 
                : '<span class="badge bg-secondary">Archived</span>';

            html += `
                <div class="list-group-item list-group-item-action flex-column align-items-start">
                    <div class="d-flex w-100 justify-content-between">
                        <div class="mb-1">${contentHtml}</div>
                        <div>${statusBadge}</div>
                    </div>
                    <p class="mb-1 small text-muted">
                        Posted by ${ann.created_by_username} on ${new Date(ann.created_at_utc).toLocaleDateString()}
                    </p>
                    <div class="d-flex justify-content-between align-items-center">
                        <button class="btn btn-sm btn-outline-info view-acks-btn" data-acks='${JSON.stringify(ann.acknowledged_by)}' title="View who has acknowledged this announcement">
                            ${ackCount} Acknowledgement(s)
                        </button>
                        <div>
                            ${ann.is_active ? `<button class="btn btn-sm btn-outline-secondary me-2 edit-btn" data-id="${ann.id}" title="Edit this announcement">Edit</button>` : ''}
                            ${ann.is_active ? `<button class="btn btn-sm btn-outline-warning archive-btn" data-id="${ann.id}" title="Archive this announcement">Archive</button>` : ''}
                        </div>
                    </div>
                </div>
            `;
        });
        html += '</div>';
        listContainer.innerHTML = html;
    }

    createForm.addEventListener('submit', async function(e) {
        e.preventDefault();
        createStatusDiv.innerHTML = '';
        const content = contentInput.value.trim();
        if (!content) return;

        try {
            const response = await fetchWithAuth('/api/admin/announcements', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content: content })
            });

            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.detail || 'Failed to post announcement.');
            }

            createStatusDiv.innerHTML = '<div class="alert alert-success">Announcement posted successfully.</div>';
            contentInput.value = '';
            loadAnnouncements(); // Refresh the list
        } catch (error) {
            createStatusDiv.innerHTML = `<div class="alert alert-danger">${error.message}</div>`;
        }
    });

    saveChangesBtn.addEventListener('click', async function() {
        const annId = editAnnouncementIdInput.value;
        const newContent = editAnnouncementContentInput.value.trim();
        editStatusDiv.innerHTML = '';

        if (!newContent) {
            editStatusDiv.innerHTML = '<div class="alert alert-danger">Content cannot be empty.</div>';
            return;
        }

        try {
            const response = await fetchWithAuth(`/api/admin/announcements/${annId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content: newContent })
            });

            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.detail || 'Failed to save changes.');
            }

            editAnnouncementModal.hide();
            loadAnnouncements(); // Refresh the list to show changes

        } catch (error) {
            editStatusDiv.innerHTML = `<div class="alert alert-danger">${error.message}</div>`;
        }
    });

    listContainer.addEventListener('click', async function(e) {
        if (e.target.classList.contains('archive-btn')) {
            const annId = e.target.dataset.id;
            if (confirm('Are you sure you want to archive this announcement? It will no longer be shown to users.')) {
                try {
                    const response = await fetchWithAuth(`/api/admin/announcements/${annId}`, { method: 'DELETE' });
                    if (!response.ok) throw new Error('Failed to archive.');
                    loadAnnouncements(); // Refresh list
                } catch (error) {
                    alert(error.message);
                }
            }
        }

        if (e.target.classList.contains('edit-btn')) {
            const annId = e.target.dataset.id;
            const announcement = announcementsMap[annId];
            if (announcement) {
                editStatusDiv.innerHTML = ''; // Clear previous status messages
                editAnnouncementIdInput.value = annId;
                editAnnouncementContentInput.value = announcement.content;
                editAnnouncementModal.show();
            }
        }

        if (e.target.classList.contains('view-acks-btn')) {
            const acks = JSON.parse(e.target.dataset.acks);
            acknowledgedByList.innerHTML = '';
            if (acks.length > 0) {
                acks.forEach(ack => {
                    const li = document.createElement('li');
                    li.className = 'list-group-item';
                    li.textContent = `${ack.username} (at ${new Date(ack.acknowledged_at_utc).toLocaleString()})`;
                    acknowledgedByList.appendChild(li);
                });
            } else {
                acknowledgedByList.innerHTML = '<li class="list-group-item">No one has acknowledged this yet.</li>';
            }
            acknowledgedByModal.show();
        }
    });

    loadAnnouncements();
});