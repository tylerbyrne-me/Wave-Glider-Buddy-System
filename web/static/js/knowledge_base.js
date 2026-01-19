/**
 * @file knowledge_base.js
 * @description Knowledge Base frontend functionality
 */

import { checkAuth, getUserProfile } from '/static/js/auth.js';
import { apiRequest, showToast, fetchWithAuth } from '/static/js/api.js';

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
    const fileTypeFilter = document.getElementById('fileTypeFilter');
    const categoryList = document.getElementById('categoryList');
    const documentsGrid = document.getElementById('documentsGrid');
    const loadingIndicator = document.getElementById('loadingIndicator');
    const noResults = document.getElementById('noResults');
    const loadMoreContainer = document.getElementById('loadMoreContainer');
    const loadMoreBtn = document.getElementById('loadMoreBtn');
    const totalDocumentsSpan = document.getElementById('totalDocuments');
    const showingCountSpan = document.getElementById('showingCount');
    
    // State
    let currentDocuments = [];
    let allCategories = [];
    let currentLimit = 50;
    let isLoading = false;
    const isAdmin = user.role === 'admin';
    
    // Debounce search
    let searchTimeout;
    
    // Initialize
    loadCategories();
    loadDocuments();
    
    // Event listeners
    searchInput.addEventListener('input', function() {
        clearSearchBtn.style.display = this.value ? 'block' : 'none';
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
            currentLimit = 50; // Reset limit when searching
            loadDocuments();
        }, 300);
    });
    
    clearSearchBtn.addEventListener('click', function() {
        searchInput.value = '';
        this.style.display = 'none';
        currentLimit = 50; // Reset limit when clearing search
        loadDocuments();
    });
    
    categoryFilter.addEventListener('change', function() {
        currentLimit = 50; // Reset limit when filtering
        loadDocuments();
    });
    fileTypeFilter.addEventListener('change', function() {
        currentLimit = 50; // Reset limit when filtering
        loadDocuments();
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
        currentLimit = 50; // Reset limit when filtering
        loadDocuments();
    });
    
    loadMoreBtn.addEventListener('click', function() {
        currentLimit += 50;
        loadDocuments(true);
    });
    
    // Upload form (admin only)
    const uploadForm = document.getElementById('uploadForm');
    const submitUploadBtn = document.getElementById('submitUploadBtn');
    const uploadModal = document.getElementById('uploadModal');
    
    if (uploadForm && submitUploadBtn) {
        submitUploadBtn.addEventListener('click', handleUpload);
        
        // Reset form when modal is closed
        if (uploadModal) {
            uploadModal.addEventListener('hidden.bs.modal', function() {
                uploadForm.reset();
                document.getElementById('uploadStatus').innerHTML = '';
            });
        }
    }
    
    // Functions
    async function loadCategories() {
        try {
            const response = await apiRequest('/api/knowledge/documents/categories', 'GET');
            allCategories = response.categories;
            
            // Clear and populate category filter dropdown
            categoryFilter.innerHTML = '<option value="">All Categories</option>';
            allCategories.forEach(cat => {
                const option = document.createElement('option');
                option.value = cat.name;
                option.textContent = `${cat.name} (${cat.count})`;
                categoryFilter.appendChild(option);
            });
            
            // Clear and populate sidebar category list (keep "All Documents" link)
            const allDocumentsLink = categoryList.querySelector('a[data-category=""]');
            categoryList.innerHTML = '';
            if (allDocumentsLink) {
                categoryList.appendChild(allDocumentsLink);
            } else {
                // Create "All Documents" link if it doesn't exist
                const allLink = document.createElement('a');
                allLink.href = '#';
                allLink.className = 'list-group-item list-group-item-action active';
                allLink.dataset.category = '';
                allLink.innerHTML = '<i class="fas fa-th"></i> All Documents';
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
        }
    }
    
    async function loadDocuments(append = false) {
        if (isLoading) return;
        isLoading = true;
        
        loadingIndicator.style.display = append ? 'none' : 'block';
        noResults.style.display = 'none';
        
        if (!append) {
            // Clear the grid completely before loading new documents
            documentsGrid.innerHTML = '';
            currentDocuments = [];
        }
        
        try {
            const params = new URLSearchParams();
            if (searchInput.value.trim()) {
                params.append('query', searchInput.value.trim());
            }
            if (categoryFilter.value) {
                params.append('category', categoryFilter.value);
            }
            if (fileTypeFilter.value) {
                params.append('file_type', fileTypeFilter.value);
            }
            params.append('limit', currentLimit.toString());
            
            const documents = await apiRequest(`/api/knowledge/documents?${params.toString()}`, 'GET');
            
            if (!append) {
                currentDocuments = documents;
            } else {
                currentDocuments = [...currentDocuments, ...documents];
            }
            
            displayDocuments(documents, append);
            updateStats();
            
            // Show/hide load more button
            if (documents.length >= currentLimit) {
                loadMoreContainer.style.display = 'block';
            } else {
                loadMoreContainer.style.display = 'none';
            }
            
        } catch (error) {
            console.error('Error loading documents:', error);
            showToast('Error loading documents: ' + error.message, 'danger');
        } finally {
            isLoading = false;
            loadingIndicator.style.display = 'none';
        }
    }
    
    function displayDocuments(documents, append = false) {
        if (!append) {
            documentsGrid.innerHTML = '';
        }
        
        if (documents.length === 0 && !append) {
            noResults.style.display = 'block';
            return;
        }
        
        // Get existing document IDs to prevent duplicates
        const existingDocIds = new Set();
        if (append) {
            documentsGrid.querySelectorAll('.document-card[data-doc-id]').forEach(card => {
                const docId = card.dataset.docId;
                if (docId) existingDocIds.add(parseInt(docId));
            });
        }
        
        documents.forEach(doc => {
            // Skip if document already exists in the grid
            if (existingDocIds.has(doc.id)) {
                return;
            }
            existingDocIds.add(doc.id);
            const card = createDocumentCard(doc);
            documentsGrid.appendChild(card);
        });
    }
    
    function createDocumentCard(doc) {
        const col = document.createElement('div');
        col.className = 'col-md-6 col-lg-4';
        
        // File type icon
        const fileIcons = {
            'pdf': 'fa-file-pdf text-danger',
            'docx': 'fa-file-word text-primary',
            'doc': 'fa-file-word text-primary',
            'pptx': 'fa-file-powerpoint text-warning',
            'ppt': 'fa-file-powerpoint text-warning'
        };
        const fileIcon = fileIcons[doc.file_type] || 'fa-file text-secondary';
        
        // Format file size
        const fileSize = formatFileSize(doc.file_size);
        
        // Format date
        const uploadDate = new Date(doc.uploaded_at_utc).toLocaleDateString();
        
        // Tags
        const tagsHtml = doc.tags ? doc.tags.split(',').map(tag => 
            `<span class="badge bg-light text-dark me-1">${tag.trim()}</span>`
        ).join('') : '';
        
        col.innerHTML = `
            <div class="card h-100 document-card" data-doc-id="${doc.id}">
                <div class="card-body d-flex flex-column">
                    <div class="d-flex align-items-start mb-2">
                        <i class="fas ${fileIcon} fa-2x me-2"></i>
                        <div class="flex-grow-1">
                            <h5 class="card-title mb-1">${escapeHtml(doc.title)}</h5>
                            <small class="text-muted">${doc.file_type.toUpperCase()} • ${fileSize}</small>
                        </div>
                    </div>
                    
                    ${doc.description ? `<p class="card-text text-muted small flex-grow-1">${escapeHtml(doc.description)}</p>` : ''}
                    
                    ${doc.category ? `<div class="mb-2"><span class="badge bg-info">${escapeHtml(doc.category)}</span></div>` : ''}
                    
                    ${tagsHtml ? `<div class="mb-2">${tagsHtml}</div>` : ''}
                    
                    <div class="mt-auto">
                        <small class="text-muted d-block mb-2">
                            <i class="fas fa-user"></i> ${escapeHtml(doc.uploaded_by_username)}<br>
                            <i class="fas fa-calendar"></i> ${uploadDate}
                        </small>
                        <div class="btn-group w-100" role="group">
                            <button class="btn btn-sm btn-outline-primary view-doc-btn" data-doc-id="${doc.id}">
                                <i class="fas fa-eye"></i> View
                            </button>
                            <a href="/api/knowledge/documents/${doc.id}/download" class="btn btn-sm btn-outline-success" target="_blank">
                                <i class="fas fa-download"></i> Download
                            </a>
                            ${isAdmin ? `
                            <button class="btn btn-sm btn-outline-warning edit-doc-btn" data-doc-id="${doc.id}">
                                <i class="fas fa-edit"></i> Edit
                            </button>
                            <button class="btn btn-sm btn-outline-danger delete-doc-btn" data-doc-id="${doc.id}">
                                <i class="fas fa-trash"></i> Delete
                            </button>
                            ` : ''}
                        </div>
                    </div>
                </div>
            </div>
        `;
        
        // Add click handlers
        const viewBtn = col.querySelector('.view-doc-btn');
        viewBtn.addEventListener('click', () => showDocumentModal(doc.id));
        
        if (isAdmin) {
            const editBtn = col.querySelector('.edit-doc-btn');
            const deleteBtn = col.querySelector('.delete-doc-btn');
            if (editBtn) {
                editBtn.addEventListener('click', () => showEditModal(doc));
            }
            if (deleteBtn) {
                deleteBtn.addEventListener('click', () => confirmDelete(doc));
            }
        }
        
        return col;
    }
    
    async function showDocumentModal(docId) {
        try {
            const doc = await apiRequest(`/api/knowledge/documents/${docId}`, 'GET');
            
            const modal = document.getElementById('documentModal');
            const modalTitle = document.getElementById('documentModalTitle');
            const modalBody = document.getElementById('documentModalBody');
            const downloadBtn = document.getElementById('documentDownloadBtn');
            
            modalTitle.textContent = doc.title;
            downloadBtn.href = `/api/knowledge/documents/${doc.id}/download`;
            
            const fileSize = formatFileSize(doc.file_size);
            const uploadDate = new Date(doc.uploaded_at_utc).toLocaleDateString();
            const tagsHtml = doc.tags ? doc.tags.split(',').map(tag => 
                `<span class="badge bg-light text-dark me-1">${tag.trim()}</span>`
            ).join('') : '';
            
            modalBody.innerHTML = `
                <div class="mb-3">
                    <strong>Description:</strong>
                    <p class="text-muted">${doc.description || 'No description provided.'}</p>
                </div>
                
                <div class="row mb-3">
                    <div class="col-md-6">
                        <strong>File Type:</strong> ${doc.file_type.toUpperCase()}<br>
                        <strong>File Size:</strong> ${fileSize}<br>
                        <strong>Category:</strong> ${doc.category || 'Uncategorized'}
                    </div>
                    <div class="col-md-6">
                        <strong>Uploaded By:</strong> ${escapeHtml(doc.uploaded_by_username)}<br>
                        <strong>Upload Date:</strong> ${uploadDate}<br>
                        <strong>Access Level:</strong> ${doc.access_level}
                    </div>
                </div>
                
                ${tagsHtml ? `<div class="mb-3"><strong>Tags:</strong><br>${tagsHtml}</div>` : ''}
                
                <div class="alert alert-info">
                    <i class="fas fa-info-circle"></i> Click "Download" to view the full document.
                </div>
            `;
            
            const bsModal = new bootstrap.Modal(modal);
            bsModal.show();
        } catch (error) {
            console.error('Error loading document:', error);
            showToast('Error loading document: ' + error.message, 'danger');
        }
    }
    
    async function handleUpload() {
        const form = document.getElementById('uploadForm');
        const submitBtn = document.getElementById('submitUploadBtn');
        const statusDiv = document.getElementById('uploadStatus');
        const fileInput = document.getElementById('uploadFile');
        
        if (!form.checkValidity()) {
            form.reportValidity();
            return;
        }
        
        const file = fileInput.files[0];
        if (!file) {
            showToast('Please select a file', 'danger');
            return;
        }
        
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Uploading...';
        statusDiv.innerHTML = '<div class="alert alert-info">Uploading document...</div>';
        
        try {
            const formData = new FormData();
            formData.append('file', file);
            
            const params = new URLSearchParams({
                title: document.getElementById('uploadTitle').value,
                description: document.getElementById('uploadDescription').value || '',
                category: document.getElementById('uploadCategory').value || '',
                tags: document.getElementById('uploadTags').value || '',
                access_level: document.getElementById('uploadAccessLevel').value
            });
            
            const response = await fetchWithAuth(`/api/knowledge/documents/upload?${params.toString()}`, {
                method: 'POST',
                body: formData
            });
            
            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Upload failed');
            }
            
            const result = await response.json();
            
            statusDiv.innerHTML = '<div class="alert alert-success">Document uploaded successfully!</div>';
            showToast('Document uploaded successfully!', 'success');
            
            // Reload documents and categories
            setTimeout(() => {
                const modal = bootstrap.Modal.getInstance(document.getElementById('uploadModal'));
                modal.hide();
                loadCategories();
                loadDocuments();
            }, 1500);
            
        } catch (error) {
            console.error('Upload error:', error);
            statusDiv.innerHTML = `<div class="alert alert-danger">Error: ${error.message}</div>`;
            showToast('Upload failed: ' + error.message, 'danger');
        } finally {
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<i class="fas fa-upload"></i> Upload Document';
        }
    }
    
    function updateStats() {
        totalDocumentsSpan.textContent = currentDocuments.length;
        showingCountSpan.textContent = currentDocuments.length;
    }
    
    function formatFileSize(bytes) {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
    }
    
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
    
    // Edit functionality
    function showEditModal(doc) {
        const modal = document.getElementById('editModal');
        if (!modal) return;
        
        document.getElementById('editDocId').value = doc.id;
        document.getElementById('editTitle').value = doc.title;
        document.getElementById('editDescription').value = doc.description || '';
        document.getElementById('editCategory').value = doc.category || '';
        document.getElementById('editTags').value = doc.tags || '';
        document.getElementById('editAccessLevel').value = doc.access_level;
        document.getElementById('editStatus').innerHTML = '';
        
        const bsModal = new bootstrap.Modal(modal);
        bsModal.show();
    }
    
    // Handle edit form submission
    const editForm = document.getElementById('editForm');
    const submitEditBtn = document.getElementById('submitEditBtn');
    const editModal = document.getElementById('editModal');
    
    if (editForm && submitEditBtn) {
        submitEditBtn.addEventListener('click', handleEdit);
        
        if (editModal) {
            editModal.addEventListener('hidden.bs.modal', function() {
                editForm.reset();
                document.getElementById('editStatus').innerHTML = '';
            });
        }
    }
    
    async function handleEdit() {
        const form = document.getElementById('editForm');
        const submitBtn = document.getElementById('submitEditBtn');
        const statusDiv = document.getElementById('editStatus');
        
        if (!form.checkValidity()) {
            form.reportValidity();
            return;
        }
        
        const docId = document.getElementById('editDocId').value;
        const updateData = {
            title: document.getElementById('editTitle').value,
            description: document.getElementById('editDescription').value || null,
            category: document.getElementById('editCategory').value || null,
            tags: document.getElementById('editTags').value || null,
            access_level: document.getElementById('editAccessLevel').value
        };
        
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Saving...';
        statusDiv.innerHTML = '<div class="alert alert-info">Saving changes...</div>';
        
        try {
            const updatedDoc = await apiRequest(`/api/knowledge/documents/${docId}`, 'PUT', updateData);
            
            statusDiv.innerHTML = '<div class="alert alert-success">Document updated successfully!</div>';
            showToast('Document updated successfully!', 'success');
            
            // Reload documents and categories
            setTimeout(() => {
                const modal = bootstrap.Modal.getInstance(document.getElementById('editModal'));
                modal.hide();
                loadCategories();
                loadDocuments();
            }, 1500);
            
        } catch (error) {
            console.error('Edit error:', error);
            statusDiv.innerHTML = `<div class="alert alert-danger">Error: ${error.message}</div>`;
            showToast('Update failed: ' + error.message, 'danger');
        } finally {
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<i class="fas fa-save"></i> Save Changes';
        }
    }
    
    // Delete functionality
    let documentToDelete = null;
    
    function confirmDelete(doc) {
        documentToDelete = doc;
        const modal = document.getElementById('deleteModal');
        if (!modal) return;
        
        document.getElementById('deleteDocTitle').textContent = doc.title;
        
        const bsModal = new bootstrap.Modal(modal);
        bsModal.show();
    }
    
    const confirmDeleteBtn = document.getElementById('confirmDeleteBtn');
    if (confirmDeleteBtn) {
        confirmDeleteBtn.addEventListener('click', handleDelete);
    }
    
    async function handleDelete() {
        if (!documentToDelete) return;
        
        const submitBtn = document.getElementById('confirmDeleteBtn');
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Deleting...';
        
        try {
            await apiRequest(`/api/knowledge/documents/${documentToDelete.id}`, 'DELETE');
            
            showToast('Document deleted successfully!', 'success');
            
            // Close modal and reload
            const modal = bootstrap.Modal.getInstance(document.getElementById('deleteModal'));
            modal.hide();
            
            loadCategories();
            loadDocuments();
            
            documentToDelete = null;
            
        } catch (error) {
            console.error('Delete error:', error);
            showToast('Delete failed: ' + error.message, 'danger');
        } finally {
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<i class="fas fa-trash"></i> Delete Document';
        }
    }
}

