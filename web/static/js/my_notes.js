/**
 * @file my_notes.js
 * @description User Notes frontend functionality
 */

import { checkAuth, getUserProfile } from '/static/js/auth.js';
import { apiRequest, showToast } from '/static/js/api.js';

document.addEventListener('DOMContentLoaded', async function() {
    if (!await checkAuth()) return;
    
    const user = await getUserProfile();
    if (!user) {
        window.location.href = '/login.html';
        return;
    }
    
    initializePage(user);
});

function initializePage(user) {
    // DOM elements
    const searchInput = document.getElementById('searchInput');
    const clearSearchBtn = document.getElementById('clearSearchBtn');
    const categoryFilter = document.getElementById('categoryFilter');
    const pinnedOnlyFilter = document.getElementById('pinnedOnlyFilter');
    const categoryList = document.getElementById('categoryList');
    const notesGrid = document.getElementById('notesGrid');
    const loadingIndicator = document.getElementById('loadingIndicator');
    const noResults = document.getElementById('noResults');
    
    // State
    let currentNotes = [];
    let allCategories = [];
    let noteToDelete = null;
    
    // Debounce search
    let searchTimeout;
    
    // Initialize
    loadCategories();
    loadNotes();
    
    // Event listeners
    searchInput.addEventListener('input', function() {
        clearSearchBtn.style.display = this.value ? 'block' : 'none';
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
            loadNotes();
        }, 300);
    });
    
    clearSearchBtn.addEventListener('click', function() {
        searchInput.value = '';
        this.style.display = 'none';
        loadNotes();
    });
    
    categoryFilter.addEventListener('change', function() {
        loadNotes();
    });
    pinnedOnlyFilter.addEventListener('change', function() {
        loadNotes();
    });
    
    categoryList.addEventListener('click', function(e) {
        e.preventDefault();
        const link = e.target.closest('a');
        if (!link) return;
        
        // Update active state
        categoryList.querySelectorAll('a').forEach(a => a.classList.remove('active'));
        link.classList.add('active');
        
        // Update filter
        const category = link.dataset.category || '';
        categoryFilter.value = category;
        loadNotes();
    });
    
    // Create/Edit note form
    const noteForm = document.getElementById('noteForm');
    const saveNoteBtn = document.getElementById('saveNoteBtn');
    const createModal = document.getElementById('createNoteModal');
    let isEditing = false;
    
    if (saveNoteBtn) {
        saveNoteBtn.addEventListener('click', handleSaveNote);
    }
    
    if (createModal) {
        createModal.addEventListener('show.bs.modal', function(e) {
            // Only reset if we're creating a new note (not editing)
            if (!isEditing) {
                noteForm.reset();
                document.getElementById('noteId').value = '';
                document.getElementById('createNoteModalLabel').innerHTML = '<i class="fas fa-plus"></i> New Note';
                document.getElementById('noteStatus').innerHTML = '';
            }
            isEditing = false; // Reset flag after modal opens
        });
        
        createModal.addEventListener('hidden.bs.modal', function() {
            // Reset form when modal is closed
            noteForm.reset();
            document.getElementById('noteId').value = '';
            document.getElementById('createNoteModalLabel').innerHTML = '<i class="fas fa-plus"></i> New Note';
            document.getElementById('noteStatus').innerHTML = '';
            isEditing = false;
        });
    }
    
    // Delete confirmation
    const confirmDeleteBtn = document.getElementById('confirmDeleteNoteBtn');
    if (confirmDeleteBtn) {
        confirmDeleteBtn.addEventListener('click', handleDeleteNote);
    }
    
    // Functions
    async function loadCategories() {
        try {
            const response = await apiRequest('/api/user-notes/categories', 'GET');
            allCategories = response.categories || [];
            
            // Clear and populate category filter dropdown
            categoryFilter.innerHTML = '<option value="">All Categories</option>';
            allCategories.forEach(cat => {
                const option = document.createElement('option');
                option.value = cat.name;
                option.textContent = `${cat.name} (${cat.count})`;
                categoryFilter.appendChild(option);
            });
            
            // Clear and populate sidebar category list (keep "All Notes" link)
            const allNotesLink = categoryList.querySelector('a[data-category=""]');
            categoryList.innerHTML = '';
            if (allNotesLink) {
                categoryList.appendChild(allNotesLink);
            } else {
                const allLink = document.createElement('a');
                allLink.href = '#';
                allLink.className = 'list-group-item list-group-item-action active';
                allLink.dataset.category = '';
                allLink.innerHTML = '<i class="fas fa-th"></i> All Notes';
                categoryList.appendChild(allLink);
            }
            
            // Add category links
            allCategories.forEach(cat => {
                const link = document.createElement('a');
                link.href = '#';
                link.className = 'list-group-item list-group-item-action';
                link.dataset.category = cat.name;
                link.innerHTML = `<i class="fas fa-folder"></i> ${cat.name} <span class="badge bg-secondary float-end">${cat.count}</span>`;
                categoryList.appendChild(link);
            });
        } catch (error) {
            console.error('Error loading categories:', error);
            const errorMsg = error instanceof Error ? error.message : (typeof error === 'string' ? error : JSON.stringify(error));
            showToast('Error loading categories: ' + errorMsg, 'danger');
        }
    }
    
    async function loadNotes() {
        loadingIndicator.style.display = 'block';
        noResults.style.display = 'none';
        // Clear the grid before loading new notes
        notesGrid.innerHTML = '';
        currentNotes = [];
        
        try {
            const params = new URLSearchParams();
            if (searchInput.value.trim()) {
                params.append('query', searchInput.value.trim());
            }
            if (categoryFilter.value) {
                params.append('category', categoryFilter.value);
            }
            if (pinnedOnlyFilter.checked) {
                params.append('pinned_only', 'true');
            }
            
            const notes = await apiRequest(`/api/user-notes?${params.toString()}`, 'GET');
            currentNotes = notes || [];
            
            if (currentNotes.length === 0) {
                noResults.style.display = 'block';
            } else {
                displayNotes(currentNotes);
            }
        } catch (error) {
            console.error('Error loading notes:', error);
            const errorMsg = error instanceof Error ? error.message : (typeof error === 'string' ? error : JSON.stringify(error));
            showToast('Error loading notes: ' + errorMsg, 'danger');
        } finally {
            loadingIndicator.style.display = 'none';
        }
    }
    
    function displayNotes(notes) {
        // Get existing note IDs to prevent duplicates
        const existingNoteIds = new Set();
        notesGrid.querySelectorAll('.note-card[data-note-id]').forEach(card => {
            const noteId = card.dataset.noteId;
            if (noteId) existingNoteIds.add(parseInt(noteId));
        });
        
        notes.forEach(note => {
            // Skip if note already exists in the grid
            if (existingNoteIds.has(note.id)) {
                return;
            }
            existingNoteIds.add(note.id);
            const card = createNoteCard(note);
            notesGrid.appendChild(card);
        });
    }
    
    function createNoteCard(note) {
        const col = document.createElement('div');
        col.className = 'col-md-6 col-lg-4';
        
        const pinnedIcon = note.is_pinned ? '<i class="fas fa-thumbtack text-warning"></i> ' : '';
        const tagsHtml = note.tags ? note.tags.split(',').map(tag => 
            `<span class="badge bg-light text-dark me-1">${tag.trim()}</span>`
        ).join('') : '';
        const updatedDate = new Date(note.updated_at_utc).toLocaleDateString();
        
        col.innerHTML = `
            <div class="card h-100 note-card ${note.is_pinned ? 'border-warning' : ''}" data-note-id="${note.id}" style="cursor: pointer;">
                <div class="card-body d-flex flex-column">
                    <div class="d-flex justify-content-between align-items-start mb-2">
                        <h5 class="card-title mb-0">${pinnedIcon}${escapeHtml(note.title)}</h5>
                        <div class="btn-group btn-group-sm" onclick="event.stopPropagation();">
                            <button class="btn btn-outline-primary edit-note-btn" data-note-id="${note.id}" title="Edit">
                                <i class="fas fa-edit"></i>
                            </button>
                            <button class="btn btn-outline-danger delete-note-btn" data-note-id="${note.id}" title="Delete">
                                <i class="fas fa-trash"></i>
                            </button>
                        </div>
                    </div>
                    
                    <p class="card-text text-muted small flex-grow-1" style="max-height: 150px; overflow: hidden; text-overflow: ellipsis;">
                        ${escapeHtml(note.content ? note.content.substring(0, 200) : '')}${note.content && note.content.length > 200 ? '...' : ''}
                    </p>
                    
                    ${note.category ? `<div class="mb-2"><span class="badge bg-info">${escapeHtml(note.category)}</span></div>` : ''}
                    ${tagsHtml ? `<div class="mb-2">${tagsHtml}</div>` : ''}
                    
                    <small class="text-muted">
                        <i class="fas fa-calendar"></i> Updated ${updatedDate}
                    </small>
                </div>
            </div>
        `;
        
        // Add event listeners
        const card = col.querySelector('.note-card');
        const editBtn = col.querySelector('.edit-note-btn');
        const deleteBtn = col.querySelector('.delete-note-btn');
        
        // Make entire card clickable to edit
        card.addEventListener('click', (e) => {
            // Don't trigger if clicking on buttons
            if (!e.target.closest('.btn-group')) {
                showEditModal(note);
            }
        });
        
        editBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            showEditModal(note);
        });
        deleteBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            confirmDelete(note);
        });
        
        return col;
    }
    
    async function showEditModal(note) {
        // Set flag to prevent form reset
        isEditing = true;
        
        // If we only have basic note data, fetch full details
        let fullNote = note;
        // Check if we need to fetch full details (if content is truncated)
        if (!note.content || (note.content.length <= 200 && note.content.includes('...'))) {
            try {
                fullNote = await apiRequest(`/api/user-notes/${note.id}`, 'GET');
            } catch (error) {
                console.error('Error fetching note details:', error);
                showToast('Error loading note details', 'danger');
                isEditing = false;
                return;
            }
        }
        
        // Populate form with note data BEFORE opening modal
        document.getElementById('noteId').value = fullNote.id;
        document.getElementById('noteTitle').value = fullNote.title || '';
        document.getElementById('noteContent').value = fullNote.content || '';
        document.getElementById('noteCategory').value = fullNote.category || '';
        document.getElementById('noteTags').value = fullNote.tags || '';
        document.getElementById('noteIsPinned').checked = fullNote.is_pinned || false;
        document.getElementById('createNoteModalLabel').innerHTML = '<i class="fas fa-edit"></i> Edit Note';
        document.getElementById('noteStatus').innerHTML = '';
        
        // Now open the modal
        const modal = new bootstrap.Modal(document.getElementById('createNoteModal'));
        modal.show();
    }
    
    async function handleSaveNote() {
        const form = document.getElementById('noteForm');
        if (!form.checkValidity()) {
            form.reportValidity();
            return;
        }
        
        const noteId = document.getElementById('noteId').value;
        const noteData = {
            title: document.getElementById('noteTitle').value,
            content: document.getElementById('noteContent').value,
            category: document.getElementById('noteCategory').value || null,
            tags: document.getElementById('noteTags').value || null,
            is_pinned: document.getElementById('noteIsPinned').checked
        };
        
        const submitBtn = document.getElementById('saveNoteBtn');
        const statusDiv = document.getElementById('noteStatus');
        
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Saving...';
        statusDiv.innerHTML = '<div class="alert alert-info">Saving note...</div>';
        
        try {
            let note;
            if (noteId) {
                // Update existing
                note = await apiRequest(`/api/user-notes/${noteId}`, 'PUT', noteData);
                showToast('Note updated successfully!', 'success');
            } else {
                // Create new
                note = await apiRequest('/api/user-notes', 'POST', noteData);
                showToast('Note created successfully!', 'success');
            }
            
            statusDiv.innerHTML = '<div class="alert alert-success">Note saved successfully!</div>';
            
            // Close modal and refresh
            const modal = bootstrap.Modal.getInstance(document.getElementById('createNoteModal'));
            modal.hide();
            
            // Refresh notes and categories
            await loadCategories();
            await loadNotes();
            
            // If it was a new note, show a message that they can click to edit
            if (!noteId) {
                showToast('Note created! Click on any note card to edit it.', 'success');
            }
            
        } catch (error) {
            console.error('Error saving note:', error);
            statusDiv.innerHTML = `<div class="alert alert-danger">Error: ${error.message}</div>`;
            showToast('Error saving note: ' + error.message, 'danger');
        } finally {
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<i class="fas fa-save"></i> Save Note';
        }
    }
    
    function confirmDelete(note) {
        noteToDelete = note;
        document.getElementById('deleteNoteTitle').textContent = note.title;
        const modal = new bootstrap.Modal(document.getElementById('deleteNoteModal'));
        modal.show();
    }
    
    async function handleDeleteNote() {
        if (!noteToDelete) return;
        
        const submitBtn = document.getElementById('confirmDeleteNoteBtn');
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Deleting...';
        
        try {
            await apiRequest(`/api/user-notes/${noteToDelete.id}`, 'DELETE');
            showToast('Note deleted successfully!', 'success');
            
            const modal = bootstrap.Modal.getInstance(document.getElementById('deleteNoteModal'));
            modal.hide();
            
            loadCategories();
            loadNotes();
            
            noteToDelete = null;
        } catch (error) {
            console.error('Error deleting note:', error);
            showToast('Error deleting note: ' + error.message, 'danger');
        } finally {
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<i class="fas fa-trash"></i> Delete Note';
        }
    }
    
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

