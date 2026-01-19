/**
 * @file shared_tips.js
 * @description Shared Tips frontend functionality
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
    // Make user available globally for comment functions
    window.currentUser = user;
    
    // DOM elements
    const searchInput = document.getElementById('searchInput');
    const clearSearchBtn = document.getElementById('clearSearchBtn');
    const categoryFilter = document.getElementById('categoryFilter');
    const pinnedOnlyFilter = document.getElementById('pinnedOnlyFilter');
    const categoryList = document.getElementById('categoryList');
    const tipsList = document.getElementById('tipsList');
    const loadingIndicator = document.getElementById('loadingIndicator');
    const noResults = document.getElementById('noResults');
    
    // State
    let currentTips = [];
    let allCategories = [];
    let tipToDelete = null;
    let currentTipId = null;
    
    // Debounce search
    let searchTimeout;
    
    // Initialize
    loadCategories();
    loadTips();
    
    // Check if we should open a specific tip from URL parameter
    const urlParams = new URLSearchParams(window.location.search);
    const tipIdParam = urlParams.get('tip_id');
    if (tipIdParam) {
        const tipId = parseInt(tipIdParam);
        if (!isNaN(tipId)) {
            // Wait for tips to load, then open the comments modal directly
            // This will show the tip and allow viewing/answering the question
            setTimeout(async () => {
                try {
                    // Set tip ID for comment form
                    const commentTipIdInput = document.getElementById('commentTipId');
                    const commentIdInput = document.getElementById('commentId');
                    const commentForm = document.getElementById('commentForm');
                    const cancelCommentBtn = document.getElementById('cancelCommentBtn');
                    
                    if (commentTipIdInput) commentTipIdInput.value = tipId;
                    if (commentIdInput) commentIdInput.value = '';
                    if (commentForm) commentForm.reset();
                    if (cancelCommentBtn) cancelCommentBtn.style.display = 'none';
                    
                    // Load comments
                    await loadComments(tipId);
                    
                    // Show comments modal
                    const commentsModal = new bootstrap.Modal(document.getElementById('tipCommentsModal'));
                    commentsModal.show();
                    
                    // Clean up URL parameter
                    window.history.replaceState({}, document.title, window.location.pathname);
                } catch (error) {
                    console.error('Error opening tip from URL:', error);
                    showToast('Error loading tip: ' + (error.message || 'Unknown error'), 'danger');
                }
            }, 1000);
        }
    }
    
    // Event listeners
    searchInput.addEventListener('input', function() {
        clearSearchBtn.style.display = this.value ? 'block' : 'none';
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
            loadTips();
        }, 300);
    });
    
    clearSearchBtn.addEventListener('click', function() {
        searchInput.value = '';
        this.style.display = 'none';
        loadTips();
    });
    
    categoryFilter.addEventListener('change', function() {
        loadTips();
    });
    pinnedOnlyFilter.addEventListener('change', function() {
        loadTips();
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
        loadTips();
    });
    
    // Create/Edit tip form
    const tipForm = document.getElementById('tipForm');
    const saveTipBtn = document.getElementById('saveTipBtn');
    const createModal = document.getElementById('createTipModal');
    let isEditing = false;
    
    if (saveTipBtn) {
        saveTipBtn.addEventListener('click', handleSaveTip);
    }
    
    if (createModal) {
        createModal.addEventListener('show.bs.modal', function(e) {
            // Only reset if we're creating a new tip (not editing)
            if (!isEditing) {
                tipForm.reset();
                document.getElementById('tipId').value = '';
                document.getElementById('createTipModalLabel').innerHTML = '<i class="fas fa-plus"></i> Share a Tip';
                document.getElementById('tipStatus').innerHTML = '';
            }
            isEditing = false; // Reset flag after modal opens
        });
        
        createModal.addEventListener('hidden.bs.modal', function() {
            // Reset form when modal is closed
            tipForm.reset();
            document.getElementById('tipId').value = '';
            document.getElementById('createTipModalLabel').innerHTML = '<i class="fas fa-plus"></i> Share a Tip';
            document.getElementById('tipStatus').innerHTML = '';
            isEditing = false;
        });
    }
    
    // Delete confirmation
    const confirmDeleteBtn = document.getElementById('confirmDeleteTipBtn');
    if (confirmDeleteBtn) {
        confirmDeleteBtn.addEventListener('click', handleDeleteTip);
    }
    
    const deleteTipModal = document.getElementById('deleteTipModal');
    if (deleteTipModal) {
        deleteTipModal.addEventListener('hidden.bs.modal', function() {
            tipToDelete = null;
        });
    }
    
    // Mark helpful
    const markHelpfulBtn = document.getElementById('markHelpfulBtn');
    if (markHelpfulBtn) {
        markHelpfulBtn.addEventListener('click', handleMarkHelpful);
    }
    
    // Comments
    const commentForm = document.getElementById('commentForm');
    const cancelCommentBtn = document.getElementById('cancelCommentBtn');
    if (commentForm) {
        commentForm.addEventListener('submit', handleSubmitComment);
    }
    if (cancelCommentBtn) {
        cancelCommentBtn.addEventListener('click', resetCommentForm);
    }
    
    // Functions
    async function loadCategories() {
        try {
            const response = await apiRequest('/api/shared-tips/categories', 'GET');
            console.log('Categories response:', response);
            allCategories = response && response.categories ? response.categories : [];
            
            // Clear and populate category filter dropdown
            categoryFilter.innerHTML = '<option value="">All Categories</option>';
            allCategories.forEach(cat => {
                const option = document.createElement('option');
                option.value = cat.name;
                option.textContent = `${cat.name} (${cat.count})`;
                categoryFilter.appendChild(option);
            });
            
            // Clear and populate sidebar category list (keep "All Tips" link)
            const allTipsLink = categoryList.querySelector('a[data-category=""]');
            categoryList.innerHTML = '';
            if (allTipsLink) {
                categoryList.appendChild(allTipsLink);
            } else {
                const allLink = document.createElement('a');
                allLink.href = '#';
                allLink.className = 'list-group-item list-group-item-action active';
                allLink.dataset.category = '';
                allLink.innerHTML = '<i class="fas fa-th"></i> All Tips';
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
    
    async function loadTips() {
        loadingIndicator.style.display = 'block';
        noResults.style.display = 'none';
        // Clear the list before loading new tips
        tipsList.innerHTML = '';
        currentTips = [];
        
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
            
            const url = `/api/shared-tips?${params.toString()}`;
            console.log('Loading tips from:', url);
            const tips = await apiRequest(url, 'GET');
            console.log('Tips response:', tips);
            currentTips = Array.isArray(tips) ? tips : [];
            
            if (currentTips.length === 0) {
                noResults.style.display = 'block';
            } else {
                displayTips(currentTips);
            }
        } catch (error) {
            console.error('Error loading tips:', error);
            const errorMsg = error instanceof Error ? error.message : (typeof error === 'string' ? error : JSON.stringify(error));
            showToast('Error loading tips: ' + errorMsg, 'danger');
        } finally {
            loadingIndicator.style.display = 'none';
        }
    }
    
    function displayTips(tips) {
        // Get existing tip IDs to prevent duplicates
        const existingTipIds = new Set();
        tipsList.querySelectorAll('.tip-card[data-tip-id]').forEach(card => {
            const tipId = card.dataset.tipId;
            if (tipId) existingTipIds.add(parseInt(tipId));
        });
        
        tips.forEach(tip => {
            // Skip if tip already exists in the list
            if (existingTipIds.has(tip.id)) {
                return;
            }
            existingTipIds.add(tip.id);
            const card = createTipCard(tip);
            tipsList.appendChild(card);
        });
    }
    
    function createTipCard(tip) {
        const card = document.createElement('div');
        card.className = `card mb-3 tip-card ${tip.is_pinned ? 'border-primary' : ''}`;
        card.dataset.tipId = tip.id;
        
        const pinnedIcon = tip.is_pinned ? '<i class="fas fa-thumbtack text-warning"></i> ' : '';
        const tagsHtml = tip.tags ? tip.tags.split(',').map(tag => 
            `<span class="badge bg-light text-dark me-1">${tag.trim()}</span>`
        ).join('') : '';
        const createdDate = new Date(tip.created_at_utc).toLocaleDateString();
        const updatedDate = new Date(tip.updated_at_utc).toLocaleDateString();
        const isEdited = tip.last_edited_by_username && tip.last_edited_by_username !== tip.created_by_username;
        
        card.innerHTML = `
            <div class="card-body">
                <div class="d-flex justify-content-between align-items-start mb-2">
                    <div class="flex-grow-1">
                        <h5 class="card-title mb-1">
                            ${pinnedIcon}${escapeHtml(tip.title)}
                        </h5>
                        <small class="text-muted">
                            <i class="fas fa-user"></i> ${escapeHtml(tip.created_by_username)}
                            ${isEdited ? ` • Edited by ${escapeHtml(tip.last_edited_by_username)}` : ''}
                            <br>
                            <i class="fas fa-calendar"></i> Created ${createdDate}
                            ${isEdited ? ` • Updated ${updatedDate}` : ''}
                        </small>
                    </div>
                    <div class="btn-group btn-group-sm">
                        <button class="btn btn-outline-primary view-tip-btn" data-tip-id="${tip.id}" title="View">
                            <i class="fas fa-eye"></i>
                        </button>
                        <button class="btn btn-outline-warning edit-tip-btn" data-tip-id="${tip.id}" title="Edit">
                            <i class="fas fa-edit"></i>
                        </button>
                        <button class="btn btn-outline-danger delete-tip-btn" data-tip-id="${tip.id}" title="Delete">
                            <i class="fas fa-trash"></i>
                        </button>
                    </div>
                </div>
                
                <p class="card-text" style="max-height: 150px; overflow: hidden;">
                    ${escapeHtml(tip.content ? tip.content.substring(0, 300) : '')}${tip.content && tip.content.length > 300 ? '...' : ''}
                </p>
                
                ${tip.category ? `<div class="mb-2"><span class="badge bg-info">${escapeHtml(tip.category)}</span></div>` : ''}
                ${tagsHtml ? `<div class="mb-2">${tagsHtml}</div>` : ''}
                
                <div class="d-flex justify-content-between align-items-center mt-2">
                    <button class="btn btn-sm btn-outline-success helpful-btn" data-tip-id="${tip.id}">
                        <i class="fas fa-thumbs-up"></i> Helpful (${tip.helpful_count})
                    </button>
                    <div class="d-flex gap-2 align-items-center">
                        ${tip.comment_count > 0 ? `
                            <span class="badge bg-info" title="${tip.comment_count} comment${tip.comment_count !== 1 ? 's' : ''}">
                                <i class="fas fa-comments"></i> ${tip.comment_count}
                            </span>
                        ` : ''}
                        ${tip.question_count > 0 ? `
                            <span class="badge ${tip.unresolved_question_count > 0 ? 'bg-warning' : 'bg-success'}" 
                                  title="${tip.question_count} question${tip.question_count !== 1 ? 's' : ''}${tip.unresolved_question_count > 0 ? ` (${tip.unresolved_question_count} unresolved)` : ' (all resolved)'}">
                                <i class="fas fa-question-circle"></i> ${tip.question_count}
                                ${tip.unresolved_question_count > 0 ? `<span class="badge bg-danger ms-1">${tip.unresolved_question_count}</span>` : ''}
                            </span>
                        ` : ''}
                        <small class="text-muted">
                            <i class="fas fa-eye"></i> ${tip.view_count} views
                        </small>
                    </div>
                </div>
            </div>
        `;
        
        // Add event listeners
        const viewBtn = card.querySelector('.view-tip-btn');
        const editBtn = card.querySelector('.edit-tip-btn');
        const deleteBtn = card.querySelector('.delete-tip-btn');
        const helpfulBtn = card.querySelector('.helpful-btn');
        
        viewBtn.addEventListener('click', () => showTipDetail(tip.id));
        editBtn.addEventListener('click', () => showEditModal(tip));
        deleteBtn.addEventListener('click', () => confirmDelete(tip));
        helpfulBtn.addEventListener('click', () => markHelpful(tip.id));
        
        return card;
    }
    
    async function showTipDetail(tipId) {
        try {
            // This endpoint increments view count when a tip is specifically viewed
            const tip = await apiRequest(`/api/shared-tips/${tipId}`, 'GET');
            currentTipId = tipId;
            
            const modal = document.getElementById('tipDetailModal');
            const modalTitle = document.getElementById('tipDetailTitle');
            const modalBody = document.getElementById('tipDetailBody');
            const helpfulBtn = document.getElementById('markHelpfulBtn');
            const helpfulCount = document.getElementById('helpfulCount');
            
            modalTitle.textContent = tip.title;
            helpfulCount.textContent = tip.helpful_count;
            
            const tagsHtml = tip.tags ? tip.tags.split(',').map(tag => 
                `<span class="badge bg-light text-dark me-1">${tag.trim()}</span>`
            ).join('') : '';
            const createdDate = new Date(tip.created_at_utc).toLocaleDateString();
            const updatedDate = new Date(tip.updated_at_utc).toLocaleDateString();
            
            modalBody.innerHTML = `
                <div class="mb-3">
                    <p style="white-space: pre-wrap;">${escapeHtml(tip.content)}</p>
                </div>
                
                <div class="row mb-3">
                    <div class="col-md-6">
                        <strong>Category:</strong> ${tip.category || 'Uncategorized'}<br>
                        <strong>Created By:</strong> ${escapeHtml(tip.created_by_username)}<br>
                        <strong>Created:</strong> ${createdDate}
                    </div>
                    <div class="col-md-6">
                        ${tip.last_edited_by_username ? `<strong>Last Edited By:</strong> ${escapeHtml(tip.last_edited_by_username)}<br>` : ''}
                        <strong>Updated:</strong> ${updatedDate}<br>
                        <strong>Views:</strong> ${tip.view_count}
                    </div>
                </div>
                
                ${tagsHtml ? `<div class="mb-3"><strong>Tags:</strong><br>${tagsHtml}</div>` : ''}
                
                <div class="mt-4">
                    <button class="btn btn-outline-primary" onclick="showComments(${tip.id})">
                        <i class="fas fa-comments"></i> View Comments & Questions
                    </button>
                </div>
            `;
            
            // Update view count in the card if it's visible
            const tipCard = document.querySelector(`.tip-card[data-tip-id="${tipId}"]`);
            if (tipCard) {
                const viewCountElement = tipCard.querySelector('.text-muted');
                if (viewCountElement) {
                    viewCountElement.innerHTML = `<i class="fas fa-eye"></i> ${tip.view_count} views`;
                }
            }
            
            const bsModal = new bootstrap.Modal(modal);
            bsModal.show();
        } catch (error) {
            console.error('Error loading tip:', error);
            showToast('Error loading tip: ' + error.message, 'danger');
        }
    }
    
    // Make showComments available globally
    window.showComments = async function(tipId) {
        // Close tip detail modal if open
        const tipDetailModal = bootstrap.Modal.getInstance(document.getElementById('tipDetailModal'));
        if (tipDetailModal) {
            tipDetailModal.hide();
        }
        
        // Set tip ID for comment form
        document.getElementById('commentTipId').value = tipId;
        resetCommentForm();
        
        // Load comments
        await loadComments(tipId);
        
        // Show comments modal
        const commentsModal = new bootstrap.Modal(document.getElementById('tipCommentsModal'));
        commentsModal.show();
    };
    
    async function loadComments(tipId) {
        const commentsList = document.getElementById('commentsList');
        commentsList.innerHTML = '<div class="text-center py-3"><div class="spinner-border text-primary" role="status"><span class="visually-hidden">Loading comments...</span></div></div>';
        
        try {
            const comments = await apiRequest(`/api/shared-tips/${tipId}/comments`, 'GET');
            
            if (comments.length === 0) {
                commentsList.innerHTML = '<div class="alert alert-info"><i class="fas fa-info-circle"></i> No comments yet. Be the first to comment!</div>';
                return;
            }
            
            commentsList.innerHTML = '';
            comments.forEach(comment => {
                const commentCard = createCommentCard(comment, tipId);
                commentsList.appendChild(commentCard);
            });
        } catch (error) {
            console.error('Error loading comments:', error);
            commentsList.innerHTML = `<div class="alert alert-danger">Error loading comments: ${error.message}</div>`;
        }
    }
    
    function createCommentCard(comment, tipId) {
        const card = document.createElement('div');
        card.className = `card mb-3 ${comment.is_question ? 'border-primary' : ''}`;
        card.dataset.commentId = comment.id;
        
        const questionBadge = comment.is_question ? 
            `<span class="badge ${comment.is_resolved ? 'bg-success' : 'bg-primary'} me-2">
                <i class="fas fa-question-circle"></i> ${comment.is_resolved ? 'Resolved' : 'Question'}
            </span>` : '';
        const date = new Date(comment.created_at_utc).toLocaleString();
        const isOwnComment = comment.commented_by_username === window.currentUser.username;
        
        card.innerHTML = `
            <div class="card-body">
                <div class="d-flex justify-content-between align-items-start mb-2">
                    <div>
                        ${questionBadge}
                        <strong>${escapeHtml(comment.commented_by_username)}</strong>
                        <small class="text-muted ms-2">
                            <i class="fas fa-clock"></i> ${date}
                        </small>
                    </div>
                    ${isOwnComment ? `
                        <div class="btn-group btn-group-sm">
                            <button class="btn btn-outline-primary edit-comment-btn" data-comment-id="${comment.id}" title="Edit">
                                <i class="fas fa-edit"></i>
                            </button>
                            <button class="btn btn-outline-danger delete-comment-btn" data-comment-id="${comment.id}" title="Delete">
                                <i class="fas fa-trash"></i>
                            </button>
                        </div>
                    ` : ''}
                </div>
                <p class="card-text mb-0" style="white-space: pre-wrap;">${escapeHtml(comment.content)}</p>
                ${comment.is_question && !comment.is_resolved ? `
                    <div class="mt-2">
                        <button class="btn btn-sm btn-outline-success resolve-question-btn" data-comment-id="${comment.id}">
                            <i class="fas fa-check"></i> Mark as Resolved
                        </button>
                    </div>
                ` : ''}
            </div>
        `;
        
        // Add event listeners
        if (isOwnComment) {
            const editBtn = card.querySelector('.edit-comment-btn');
            const deleteBtn = card.querySelector('.delete-comment-btn');
            if (editBtn) {
                editBtn.addEventListener('click', () => editComment(comment, tipId));
            }
            if (deleteBtn) {
                deleteBtn.addEventListener('click', () => deleteComment(comment.id, tipId));
            }
        }
        
        const resolveBtn = card.querySelector('.resolve-question-btn');
        if (resolveBtn) {
            resolveBtn.addEventListener('click', () => resolveQuestion(comment.id, tipId));
        }
        
        return card;
    }
    
    async function handleSubmitComment(e) {
        e.preventDefault();
        
        const tipId = document.getElementById('commentTipId').value;
        const commentId = document.getElementById('commentId').value;
        const content = document.getElementById('commentContent').value.trim();
        const isQuestion = document.getElementById('commentIsQuestion').checked;
        
        if (!content) {
            showToast('Please enter a comment', 'warning');
            return;
        }
        
        const submitBtn = e.target.querySelector('button[type="submit"]');
        const originalText = submitBtn.innerHTML;
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Posting...';
        
        try {
            if (commentId) {
                // Update existing comment
                await apiRequest(`/api/shared-tips/${tipId}/comments/${commentId}`, 'PUT', {
                    content: content
                });
                showToast('Comment updated successfully!', 'success');
            } else {
                // Create new comment
                await apiRequest(`/api/shared-tips/${tipId}/comments`, 'POST', {
                    content: content,
                    is_question: isQuestion
                });
                showToast('Comment posted successfully!', 'success');
            }
            
            resetCommentForm();
            await loadComments(tipId);
            
            // Refresh tips list to update comment/question counts
            await loadTips();
        } catch (error) {
            console.error('Error posting comment:', error);
            showToast('Error posting comment: ' + error.message, 'danger');
        } finally {
            submitBtn.disabled = false;
            submitBtn.innerHTML = originalText;
        }
    }
    
    function resetCommentForm() {
        document.getElementById('commentForm').reset();
        document.getElementById('commentId').value = '';
        document.getElementById('cancelCommentBtn').style.display = 'none';
    }
    
    function editComment(comment, tipId) {
        document.getElementById('commentId').value = comment.id;
        document.getElementById('commentContent').value = comment.content;
        document.getElementById('commentIsQuestion').checked = comment.is_question;
        document.getElementById('cancelCommentBtn').style.display = 'block';
        
        // Scroll to form
        document.getElementById('commentForm').scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    
    async function deleteComment(commentId, tipId) {
        if (!confirm('Are you sure you want to delete this comment?')) {
            return;
        }
        
        try {
            await apiRequest(`/api/shared-tips/${tipId}/comments/${commentId}`, 'DELETE');
            showToast('Comment deleted successfully!', 'success');
            await loadComments(tipId);
            
            // Refresh tips list to update comment/question counts
            await loadTips();
        } catch (error) {
            console.error('Error deleting comment:', error);
            showToast('Error deleting comment: ' + error.message, 'danger');
        }
    }
    
    async function resolveQuestion(commentId, tipId) {
        try {
            await apiRequest(`/api/shared-tips/${tipId}/comments/${commentId}`, 'PUT', {
                is_resolved: true
            });
            showToast('Question marked as resolved!', 'success');
            await loadComments(tipId);
            
            // Refresh tips list to update question counts
            await loadTips();
        } catch (error) {
            console.error('Error resolving question:', error);
            showToast('Error: ' + error.message, 'danger');
        }
    }
    
    async function showEditModal(tip) {
        // Set flag to prevent form reset
        isEditing = true;
        
        // If we only have basic tip data, fetch full details
        let fullTip = tip;
        // Check if we need to fetch full details (if content is truncated)
        if (!tip.content || (tip.content.length <= 300 && tip.content.includes('...'))) {
            try {
                fullTip = await apiRequest(`/api/shared-tips/${tip.id}`, 'GET');
            } catch (error) {
                console.error('Error fetching tip details:', error);
                showToast('Error loading tip details', 'danger');
                isEditing = false;
                return;
            }
        }
        
        // Populate form with tip data BEFORE opening modal
        document.getElementById('tipId').value = fullTip.id;
        document.getElementById('tipTitle').value = fullTip.title || '';
        document.getElementById('tipContent').value = fullTip.content || '';
        document.getElementById('tipCategory').value = fullTip.category || '';
        document.getElementById('tipTags').value = fullTip.tags || '';
        document.getElementById('tipIsPinned').checked = fullTip.is_pinned || false;
        document.getElementById('createTipModalLabel').innerHTML = '<i class="fas fa-edit"></i> Edit Tip';
        document.getElementById('tipStatus').innerHTML = '';
        
        // Now open the modal
        const modal = new bootstrap.Modal(document.getElementById('createTipModal'));
        modal.show();
    }
    
    async function handleSaveTip() {
        const form = document.getElementById('tipForm');
        if (!form.checkValidity()) {
            form.reportValidity();
            return;
        }
        
        const tipId = document.getElementById('tipId').value;
        const tipData = {
            title: document.getElementById('tipTitle').value,
            content: document.getElementById('tipContent').value,
            category: document.getElementById('tipCategory').value || null,
            tags: document.getElementById('tipTags').value || null,
            is_pinned: document.getElementById('tipIsPinned').checked
        };
        
        const submitBtn = document.getElementById('saveTipBtn');
        const statusDiv = document.getElementById('tipStatus');
        
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Saving...';
        statusDiv.innerHTML = '<div class="alert alert-info">Saving tip...</div>';
        
        try {
            let tip;
            if (tipId) {
                tip = await apiRequest(`/api/shared-tips/${tipId}`, 'PUT', tipData);
                showToast('Tip updated successfully!', 'success');
            } else {
                tip = await apiRequest('/api/shared-tips', 'POST', tipData);
                showToast('Tip shared successfully!', 'success');
            }
            
            statusDiv.innerHTML = '<div class="alert alert-success">Tip saved successfully!</div>';
            
            // Close modal and refresh
            const modal = bootstrap.Modal.getInstance(document.getElementById('createTipModal'));
            modal.hide();
            
            // Refresh tips and categories
            await loadCategories();
            await loadTips();
            
        } catch (error) {
            console.error('Error saving tip:', error);
            statusDiv.innerHTML = `<div class="alert alert-danger">Error: ${error.message}</div>`;
            showToast('Error saving tip: ' + error.message, 'danger');
        } finally {
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<i class="fas fa-save"></i> Share Tip';
        }
    }
    
    async function markHelpful(tipId) {
        try {
            const tip = await apiRequest(`/api/shared-tips/${tipId}/helpful`, 'POST');
            showToast('Thank you for the feedback!', 'success');
            
            // Update the button text
            const helpfulBtn = document.querySelector(`.helpful-btn[data-tip-id="${tipId}"]`);
            if (helpfulBtn) {
                helpfulBtn.innerHTML = `<i class="fas fa-thumbs-up"></i> Helpful (${tip.helpful_count})`;
            }
            
            // Update in detail modal if open
            if (currentTipId === tipId) {
                document.getElementById('helpfulCount').textContent = tip.helpful_count;
            }
        } catch (error) {
            console.error('Error marking helpful:', error);
            showToast('Error: ' + error.message, 'danger');
        }
    }
    
    async function handleMarkHelpful() {
        if (currentTipId) {
            await markHelpful(currentTipId);
        }
    }
    
    function confirmDelete(tip) {
        tipToDelete = tip;
        document.getElementById('deleteTipTitle').textContent = tip.title;
        const modal = new bootstrap.Modal(document.getElementById('deleteTipModal'));
        modal.show();
    }
    
    async function handleDeleteTip() {
        if (!tipToDelete) return;
        
        const submitBtn = document.getElementById('confirmDeleteTipBtn');
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Deleting...';
        
        try {
            await apiRequest(`/api/shared-tips/${tipToDelete.id}`, 'DELETE');
            showToast('Tip deleted successfully!', 'success');
            
            const modal = bootstrap.Modal.getInstance(document.getElementById('deleteTipModal'));
            modal.hide();
            
            loadCategories();
            loadTips();
            
            tipToDelete = null;
        } catch (error) {
            console.error('Error deleting tip:', error);
            showToast('Error deleting tip: ' + error.message, 'danger');
        } finally {
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<i class="fas fa-trash"></i> Delete Tip';
        }
    }
    
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

