/**
 * Admin FAQ Management
 * Handles CRUD operations for FAQ entries
 */

import { apiRequest, showToast } from './api.js';

// State
let allFaqs = [];
let currentFaqId = null;

// DOM Elements
const faqListContainer = document.getElementById('faqListContainer');
const faqCountBadge = document.getElementById('faqCountBadge');
const filterCategory = document.getElementById('filterCategory');
const filterStatus = document.getElementById('filterStatus');
const searchInput = document.getElementById('searchInput');
const createFaqBtn = document.getElementById('createFaqBtn');
const refreshBtn = document.getElementById('refreshBtn');

// Modal elements
const faqModal = new bootstrap.Modal(document.getElementById('faqModal'));
const faqModalLabel = document.getElementById('faqModalLabel');
const faqForm = document.getElementById('faqForm');
const faqId = document.getElementById('faqId');
const faqQuestion = document.getElementById('faqQuestion');
const faqAnswer = document.getElementById('faqAnswer');
const faqCategory = document.getElementById('faqCategory');
const faqIsActive = document.getElementById('faqIsActive');
const faqKeywords = document.getElementById('faqKeywords');
const faqTags = document.getElementById('faqTags');
const faqRelatedDocs = document.getElementById('faqRelatedDocs');
const faqRelatedTips = document.getElementById('faqRelatedTips');
const faqFormStatus = document.getElementById('faqFormStatus');
const saveFaqBtn = document.getElementById('saveFaqBtn');

const deleteModal = new bootstrap.Modal(document.getElementById('deleteModal'));
const deleteQuestionPreview = document.getElementById('deleteQuestionPreview');
const confirmDeleteBtn = document.getElementById('confirmDeleteBtn');

/**
 * Initialize the page
 */
async function init() {
    await loadFaqs();
    setupEventListeners();
}

/**
 * Load all FAQs from the server
 */
async function loadFaqs() {
    try {
        faqListContainer.innerHTML = `
            <div class="d-flex justify-content-center py-4">
                <div class="spinner-border" role="status">
                    <span class="visually-hidden">Loading...</span>
                </div>
            </div>
        `;
        
        const response = await apiRequest('/api/admin/faqs', 'GET');
        allFaqs = response;
        
        updateFaqCount();
        renderFaqs();
        
    } catch (error) {
        console.error('Error loading FAQs:', error);
        faqListContainer.innerHTML = `
            <div class="alert alert-danger">
                <i class="fas fa-exclamation-circle me-2"></i>
                Error loading FAQs: ${error.message}
            </div>
        `;
    }
}

/**
 * Update the FAQ count badge
 */
function updateFaqCount() {
    const activeCount = allFaqs.filter(f => f.is_active).length;
    faqCountBadge.textContent = `${allFaqs.length} FAQs (${activeCount} active)`;
}

/**
 * Get filtered FAQs based on current filter selections
 */
function getFilteredFaqs() {
    let filtered = [...allFaqs];
    
    // Category filter
    const category = filterCategory.value;
    if (category) {
        filtered = filtered.filter(f => f.category === category);
    }
    
    // Status filter
    const status = filterStatus.value;
    if (status === 'true') {
        filtered = filtered.filter(f => f.is_active);
    } else if (status === 'false') {
        filtered = filtered.filter(f => !f.is_active);
    }
    
    // Search filter
    const searchTerm = searchInput.value.toLowerCase().trim();
    if (searchTerm) {
        filtered = filtered.filter(f => 
            f.question.toLowerCase().includes(searchTerm) ||
            f.answer.toLowerCase().includes(searchTerm) ||
            (f.keywords && f.keywords.toLowerCase().includes(searchTerm)) ||
            (f.tags && f.tags.toLowerCase().includes(searchTerm))
        );
    }
    
    return filtered;
}

/**
 * Render FAQs to the list
 */
function renderFaqs() {
    const filtered = getFilteredFaqs();
    
    if (filtered.length === 0) {
        faqListContainer.innerHTML = `
            <div class="text-center py-4 text-muted">
                <i class="fas fa-question-circle fa-3x mb-3"></i>
                <p>No FAQs found. ${allFaqs.length === 0 ? 'Create your first FAQ!' : 'Try adjusting your filters.'}</p>
            </div>
        `;
        return;
    }
    
    const html = filtered.map(faq => createFaqCard(faq)).join('');
    faqListContainer.innerHTML = html;
}

/**
 * Create HTML for a single FAQ card
 */
function createFaqCard(faq) {
    const categoryBadge = getCategoryBadge(faq.category);
    const statusBadge = faq.is_active 
        ? '<span class="badge bg-success">Active</span>'
        : '<span class="badge bg-secondary">Inactive</span>';
    
    const truncatedAnswer = faq.answer.length > 200 
        ? faq.answer.substring(0, 200) + '...' 
        : faq.answer;
    
    const stats = `
        <small class="text-muted">
            <i class="fas fa-eye me-1"></i>${faq.view_count || 0} views
            <i class="fas fa-thumbs-up ms-2 me-1"></i>${faq.helpful_count || 0} helpful
        </small>
    `;
    
    return `
        <div class="card mb-3 faq-card ${!faq.is_active ? 'border-secondary opacity-75' : ''}" data-faq-id="${faq.id}">
            <div class="card-body">
                <div class="d-flex justify-content-between align-items-start mb-2">
                    <div class="d-flex align-items-center gap-2">
                        ${categoryBadge}
                        ${statusBadge}
                    </div>
                    <div class="btn-group btn-group-sm">
                        <button class="btn btn-outline-primary edit-btn" data-faq-id="${faq.id}" title="Edit">
                            <i class="fas fa-edit"></i>
                        </button>
                        <button class="btn btn-outline-danger delete-btn" data-faq-id="${faq.id}" title="Delete">
                            <i class="fas fa-trash"></i>
                        </button>
                    </div>
                </div>
                <h6 class="card-title mb-2">
                    <i class="fas fa-question-circle text-primary me-2"></i>${escapeHtml(faq.question)}
                </h6>
                <p class="card-text text-muted small mb-2">${escapeHtml(truncatedAnswer)}</p>
                <div class="d-flex justify-content-between align-items-center">
                    ${stats}
                    ${faq.tags ? `<small class="text-muted"><i class="fas fa-tags me-1"></i>${escapeHtml(faq.tags)}</small>` : ''}
                </div>
            </div>
        </div>
    `;
}

/**
 * Get category badge HTML
 */
function getCategoryBadge(category) {
    const badges = {
        sensors: 'bg-info',
        troubleshooting: 'bg-warning text-dark',
        procedures: 'bg-primary',
        power_management: 'bg-danger',
        navigation: 'bg-success',
        data: 'bg-dark',
        general: 'bg-secondary'
    };
    
    const bgClass = badges[category] || 'bg-secondary';
    const displayName = category ? category.replace('_', ' ') : 'general';
    
    return `<span class="badge ${bgClass}">${displayName}</span>`;
}

/**
 * Setup event listeners
 */
function setupEventListeners() {
    // Filter changes
    filterCategory.addEventListener('change', renderFaqs);
    filterStatus.addEventListener('change', renderFaqs);
    searchInput.addEventListener('input', debounce(renderFaqs, 300));
    
    // Create button
    createFaqBtn.addEventListener('click', () => openModal());
    
    // Refresh button
    refreshBtn.addEventListener('click', loadFaqs);
    
    // Save button
    saveFaqBtn.addEventListener('click', saveFaq);
    
    // Delete confirmation
    confirmDeleteBtn.addEventListener('click', confirmDelete);
    
    // Event delegation for edit/delete buttons
    faqListContainer.addEventListener('click', (e) => {
        const editBtn = e.target.closest('.edit-btn');
        const deleteBtn = e.target.closest('.delete-btn');
        
        if (editBtn) {
            const faqId = parseInt(editBtn.dataset.faqId);
            const faq = allFaqs.find(f => f.id === faqId);
            if (faq) openModal(faq);
        }
        
        if (deleteBtn) {
            const faqId = parseInt(deleteBtn.dataset.faqId);
            const faq = allFaqs.find(f => f.id === faqId);
            if (faq) openDeleteModal(faq);
        }
    });
}

/**
 * Open the FAQ modal for create or edit
 */
function openModal(faq = null) {
    // Reset form
    faqForm.reset();
    faqFormStatus.innerHTML = '';
    
    if (faq) {
        // Edit mode
        faqModalLabel.textContent = 'Edit FAQ';
        faqId.value = faq.id;
        faqQuestion.value = faq.question;
        faqAnswer.value = faq.answer;
        faqCategory.value = faq.category || 'general';
        faqIsActive.value = faq.is_active ? 'true' : 'false';
        faqKeywords.value = faq.keywords || '';
        faqTags.value = faq.tags || '';
        faqRelatedDocs.value = faq.related_document_ids || '';
        faqRelatedTips.value = faq.related_tip_ids || '';
    } else {
        // Create mode
        faqModalLabel.textContent = 'Create FAQ';
        faqId.value = '';
    }
    
    faqModal.show();
}

/**
 * Save FAQ (create or update)
 */
async function saveFaq() {
    // Validate
    if (!faqQuestion.value.trim() || !faqAnswer.value.trim()) {
        faqFormStatus.innerHTML = `
            <div class="alert alert-warning">
                <i class="fas fa-exclamation-triangle me-2"></i>
                Question and Answer are required.
            </div>
        `;
        return;
    }
    
    const faqData = {
        question: faqQuestion.value.trim(),
        answer: faqAnswer.value.trim(),
        category: faqCategory.value,
        is_active: faqIsActive.value === 'true',
        keywords: faqKeywords.value.trim() || null,
        tags: faqTags.value.trim() || null,
        related_document_ids: faqRelatedDocs.value.trim() || null,
        related_tip_ids: faqRelatedTips.value.trim() || null
    };
    
    const isEdit = !!faqId.value;
    
    try {
        saveFaqBtn.disabled = true;
        saveFaqBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Saving...';
        
        if (isEdit) {
            await apiRequest(`/api/admin/faqs/${faqId.value}`, 'PUT', faqData);
            showToast('FAQ updated successfully', 'success');
        } else {
            await apiRequest('/api/admin/faqs', 'POST', faqData);
            showToast('FAQ created successfully', 'success');
        }
        
        faqModal.hide();
        await loadFaqs();
        
    } catch (error) {
        console.error('Error saving FAQ:', error);
        faqFormStatus.innerHTML = `
            <div class="alert alert-danger">
                <i class="fas fa-exclamation-circle me-2"></i>
                Error saving FAQ: ${error.message}
            </div>
        `;
    } finally {
        saveFaqBtn.disabled = false;
        saveFaqBtn.innerHTML = '<i class="fas fa-save me-1"></i>Save FAQ';
    }
}

/**
 * Open delete confirmation modal
 */
function openDeleteModal(faq) {
    currentFaqId = faq.id;
    deleteQuestionPreview.textContent = faq.question;
    deleteModal.show();
}

/**
 * Confirm and execute delete
 */
async function confirmDelete() {
    if (!currentFaqId) return;
    
    try {
        confirmDeleteBtn.disabled = true;
        confirmDeleteBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Deleting...';
        
        await apiRequest(`/api/admin/faqs/${currentFaqId}`, 'DELETE');
        
        showToast('FAQ deleted successfully', 'success');
        deleteModal.hide();
        await loadFaqs();
        
    } catch (error) {
        console.error('Error deleting FAQ:', error);
        showToast(`Error deleting FAQ: ${error.message}`, 'danger');
    } finally {
        confirmDeleteBtn.disabled = false;
        confirmDeleteBtn.innerHTML = '<i class="fas fa-trash me-1"></i>Delete';
        currentFaqId = null;
    }
}

/**
 * Escape HTML to prevent XSS
 */
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * Debounce function
 */
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', init);
