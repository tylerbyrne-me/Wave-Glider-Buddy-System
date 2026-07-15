/**
 * Slocum daily pilot checklist form: render schema, refresh autofill, submit/edit.
 */
import { apiRequest, showToast } from '/static/js/api.js';
import { checkAuth } from '/static/js/auth.js';

document.addEventListener('DOMContentLoaded', async () => {
    if (!(await checkAuth())) return;

    const datasetId = document.body.dataset.datasetId;
    const editFormId = document.body.dataset.editFormId
        ? Number(document.body.dataset.editFormId)
        : null;

    const formTitle = document.getElementById('formTitle');
    const formDescription = document.getElementById('formDescription');
    const formSpinner = document.getElementById('formSpinner');
    const checklistForm = document.getElementById('slocumChecklistForm');
    const formSectionsContainer = document.getElementById('formSectionsContainer');
    const submissionStatus = document.getElementById('submissionStatus');
    const editModeBanner = document.getElementById('editModeBanner');
    const submitBtn = document.getElementById('submitChecklistBtn');
    const backLink = document.getElementById('backToDashboardLink');

    let currentSchema = null;
    let unverifiedModal = null;
    const modalEl = document.getElementById('unverifiedConfirmModal');
    if (modalEl && window.bootstrap) {
        unverifiedModal = new bootstrap.Modal(modalEl);
    }

    if (!datasetId) {
        if (formSpinner) formSpinner.style.display = 'none';
        if (submissionStatus) {
            submissionStatus.innerHTML = '<div class="alert alert-danger">Missing dataset id.</div>';
        }
        return;
    }

    if (backLink) {
        const isHistorical = /_delayed$/.test(datasetId);
        backLink.href = isHistorical
            ? `/slocum/historical?dataset=${encodeURIComponent(datasetId)}`
            : `/slocum?dataset=${encodeURIComponent(datasetId)}`;
    }

    function escapeHtml(value) {
        if (value === null || value === undefined) return '';
        return String(value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function buildSavedItemsById(sectionsData) {
        const map = {};
        (sectionsData || []).forEach((section) => {
            (section.items || []).forEach((item) => {
                if (item && item.id) map[item.id] = item;
            });
        });
        return map;
    }

    function applySavedValuesToForm(savedItemsById, sectionsData) {
        Object.entries(savedItemsById).forEach(([id, item]) => {
            const el = document.getElementById(id);
            if (!el) return;
            const itemType = item.item_type || '';
            if (itemType === 'autofilled_value' || itemType === 'static_text') {
                // keep live/static display; restore verify + comment only
            } else if (el.tagName === 'SELECT' || el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
                if (item.value != null) el.value = item.value;
            }
            const commentEl = document.querySelector(`[name="${id}_comment"]`);
            if (commentEl && item.comment != null) commentEl.value = item.comment;
            const verifiedEl = document.getElementById(`${id}_verified`);
            if (verifiedEl && item.is_verified != null) verifiedEl.checked = !!item.is_verified;
            if (itemType === 'checkbox' && el.type === 'checkbox') {
                el.checked = !!item.is_checked;
            }
        });
        (sectionsData || []).forEach((section) => {
            if (!section?.id || section.section_comment == null) return;
            const sectionCommentEl = document.getElementById(`${section.id}_comment`);
            if (sectionCommentEl) sectionCommentEl.value = section.section_comment;
        });
    }

    function renderSchema(schema, savedSubmission = null) {
        currentSchema = schema;
        if (formTitle) formTitle.textContent = schema.title || 'Slocum Daily Checklist';
        if (formDescription) formDescription.textContent = schema.description || '';
        formSectionsContainer.innerHTML = '';

        (schema.sections || []).forEach((section) => {
            const sectionDiv = document.createElement('div');
            sectionDiv.className = 'form-section';
            sectionDiv.dataset.sectionId = section.id;
            sectionDiv.innerHTML = `<h3 class="h5 mb-3">${section.title || section.id}</h3>`;

            (section.items || []).forEach((item) => {
                const itemDiv = document.createElement('div');
                itemDiv.className = 'form-item mb-3';
                itemDiv.dataset.itemId = item.id;

                let inputHtml = '';
                let labelContent = `${escapeHtml(item.label || item.id)}${item.required ? '<span class="text-danger">*</span>' : ''}`;
                const value = item.value != null && item.value !== '' ? item.value : '';
                const valueEsc = escapeHtml(value);
                const placeholderEsc = escapeHtml(item.placeholder || '');

                switch (item.item_type) {
                    case 'autofilled_value':
                        inputHtml = `<div class="autofilled-value" id="${item.id}">${valueEsc || 'N/A'}</div>`;
                        break;
                    case 'static_text':
                        inputHtml = `<div class="static-text" id="${item.id}">${valueEsc || '—'}</div>`;
                        break;
                    case 'text_input':
                        inputHtml = `<input type="text" class="form-control" id="${item.id}" name="${item.id}" value="${valueEsc}" placeholder="${placeholderEsc}" ${item.required ? 'required' : ''}>`;
                        break;
                    case 'text_area':
                        inputHtml = `<textarea class="form-control" id="${item.id}" name="${item.id}" rows="3" placeholder="${placeholderEsc}" ${item.required ? 'required' : ''}>${valueEsc}</textarea>`;
                        break;
                    case 'dropdown': {
                        const options = (item.options || [])
                            .map((opt) => {
                                const optEsc = escapeHtml(opt);
                                return `<option value="${optEsc}" ${value === opt ? 'selected' : ''}>${optEsc}</option>`;
                            })
                            .join('');
                        inputHtml = `<select class="form-select" id="${item.id}" name="${item.id}" ${item.required ? 'required' : ''}>
                            <option value="" ${!value ? 'selected' : ''} disabled>Select…</option>
                            ${options}
                        </select>`;
                        break;
                    }
                    case 'checkbox':
                        inputHtml = `<div class="form-check">
                            <input class="form-check-input" type="checkbox" id="${item.id}" name="${item.id}" ${item.is_checked ? 'checked' : ''}>
                            <label class="form-check-label" for="${item.id}">Checked</label>
                        </div>`;
                        break;
                    default:
                        inputHtml = `<input type="text" class="form-control" id="${item.id}" name="${item.id}" value="${value}">`;
                }

                const showItemComment = item.item_type !== 'text_area';
                const showVerified = item.item_type === 'autofilled_value' || item.item_type === 'static_text';

                itemDiv.innerHTML = `
                    <div class="row align-items-center">
                        <div class="col-md-3">
                            <label for="${item.id}" class="form-label mb-0">${labelContent}</label>
                        </div>
                        <div class="col-md-4">${inputHtml}</div>
                        <div class="col-md-3">
                            ${showItemComment ? `<textarea class="form-control form-control-sm" name="${item.id}_comment" rows="1" placeholder="Comment..."></textarea>` : ''}
                        </div>
                        <div class="col-md-2">
                            ${showVerified ? `
                            <div class="form-check">
                                <input class="form-check-input" type="checkbox" id="${item.id}_verified" name="${item.id}_verified" value="true">
                                <label class="form-check-label" for="${item.id}_verified">Verified</label>
                            </div>` : ''}
                        </div>
                    </div>
                `;
                sectionDiv.appendChild(itemDiv);
            });

            if (section.section_comment != null) {
                const notes = document.createElement('div');
                notes.className = 'mt-3';
                notes.innerHTML = `
                    <label for="${section.id}_comment" class="form-label">Section Notes:</label>
                    <textarea class="form-control" id="${section.id}_comment" name="${section.id}_comment" rows="2" placeholder="Overall notes for this section...">${section.section_comment || ''}</textarea>
                `;
                sectionDiv.appendChild(notes);
            }

            formSectionsContainer.appendChild(sectionDiv);
        });

        checklistForm.style.display = 'block';
        if (formSpinner) formSpinner.style.display = 'none';

        if (savedSubmission) {
            applySavedValuesToForm(
                buildSavedItemsById(savedSubmission.sections_data),
                savedSubmission.sections_data,
            );
            if (editModeBanner) {
                editModeBanner.style.display = 'block';
                editModeBanner.textContent = `Editing submission #${savedSubmission.id} by ${savedSubmission.submitted_by_username || 'unknown'}. Save will update this record.`;
            }
            if (submitBtn) submitBtn.textContent = 'Save Changes';
        }
    }

    function buildSectionsDataFromForm() {
        if (!currentSchema) return [];
        return (currentSchema.sections || []).map((section) => {
            const sectionCommentEl = document.getElementById(`${section.id}_comment`);
            const items = (section.items || []).map((item) => {
                const el = document.getElementById(item.id);
                const verifiedEl = document.getElementById(`${item.id}_verified`);
                const commentEl = document.querySelector(`[name="${item.id}_comment"]`);
                let value = null;
                let isChecked = null;
                if (item.item_type === 'autofilled_value' || item.item_type === 'static_text') {
                    value = el ? el.textContent : item.value;
                } else if (item.item_type === 'checkbox') {
                    isChecked = el ? el.checked : false;
                    value = isChecked ? 'true' : 'false';
                } else if (el) {
                    value = el.value;
                }
                return {
                    id: item.id,
                    label: item.label,
                    item_type: item.item_type,
                    value,
                    is_checked: isChecked,
                    is_verified: verifiedEl ? verifiedEl.checked : null,
                    comment: commentEl ? commentEl.value : null,
                    required: !!item.required,
                    options: item.options || null,
                    placeholder: item.placeholder || null,
                };
            });
            return {
                id: section.id,
                title: section.title,
                items,
                section_comment: sectionCommentEl ? sectionCommentEl.value : section.section_comment,
            };
        });
    }

    function countUnverified(sectionsData) {
        let count = 0;
        (sectionsData || []).forEach((section) => {
            (section.items || []).forEach((item) => {
                if (
                    (item.item_type === 'autofilled_value' || item.item_type === 'static_text')
                    && item.is_verified === false
                ) {
                    count += 1;
                }
            });
        });
        return count;
    }

    async function performSubmission(sectionsData) {
        if (submissionStatus) submissionStatus.innerHTML = '';
        const payload = {
            mission_id: datasetId,
            form_type: currentSchema?.form_type || 'slocum_daily_checklist',
            form_title: currentSchema?.title || 'Slocum Daily Pilot Checklist',
            sections_data: sectionsData,
        };
        try {
            if (editFormId) {
                await apiRequest(`/api/slocum/checklists/id/${editFormId}`, 'PUT', payload);
                showToast('Checklist updated.', 'success');
            } else {
                await apiRequest(`/api/slocum/checklists/${encodeURIComponent(datasetId)}`, 'POST', payload);
                showToast('Checklist submitted.', 'success');
            }
            window.location.href = backLink?.href || `/slocum?dataset=${encodeURIComponent(datasetId)}`;
        } catch (error) {
            if (submissionStatus) {
                submissionStatus.innerHTML = `<div class="alert alert-danger">Failed to save: ${error.message}</div>`;
            }
            showToast(`Failed to save checklist: ${error.message}`, 'danger');
        }
    }

    async function fetchAndRender() {
        if (formSpinner) formSpinner.style.display = 'block';
        checklistForm.style.display = 'none';
        try {
            const schema = await apiRequest(
                `/api/slocum/checklists/${encodeURIComponent(datasetId)}/template`,
                'GET',
            );
            let saved = null;
            if (editFormId) {
                saved = await apiRequest(`/api/slocum/checklists/id/${editFormId}`, 'GET');
            }
            renderSchema(schema, saved);
        } catch (error) {
            if (formSpinner) formSpinner.style.display = 'none';
            if (submissionStatus) {
                submissionStatus.innerHTML = `<div class="alert alert-danger">Failed to load checklist: ${error.message}</div>`;
            }
        }
    }

    const refreshBtn = document.getElementById('refreshFormDataBtn');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', async () => {
            refreshBtn.disabled = true;
            const original = refreshBtn.textContent;
            refreshBtn.textContent = 'Refreshing…';
            try {
                const schema = await apiRequest(
                    `/api/slocum/checklists/${encodeURIComponent(datasetId)}/template`,
                    'GET',
                );
                currentSchema = schema;
                let updated = 0;
                for (const section of schema.sections || []) {
                    for (const item of section.items || []) {
                        if (!item.id) continue;
                        if (item.item_type === 'autofilled_value' || item.item_type === 'static_text') {
                            const el = document.getElementById(item.id);
                            if (el && (el.classList.contains('autofilled-value') || el.classList.contains('static-text'))) {
                                el.textContent = item.value != null && item.value !== '' ? item.value : 'N/A';
                                updated += 1;
                            }
                        }
                    }
                }
                showToast(`Refreshed ${updated} autofilled field(s).`, 'success');
            } catch (error) {
                showToast(`Refresh failed: ${error.message}`, 'danger');
            } finally {
                refreshBtn.disabled = false;
                refreshBtn.textContent = original;
            }
        });
    }

    checklistForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        const sectionsData = buildSectionsDataFromForm();
        const unverified = countUnverified(sectionsData);
        if (unverified > 0 && unverifiedModal) {
            const submitAnyway = document.getElementById('unverifiedSubmitBtn');
            const cancelBtn = document.getElementById('unverifiedCancelSubmissionBtn');
            const onSubmit = () => {
                unverifiedModal.hide();
                performSubmission(sectionsData);
                cleanup();
            };
            const onCancel = () => {
                unverifiedModal.hide();
                cleanup();
            };
            function cleanup() {
                submitAnyway?.removeEventListener('click', onSubmit);
                cancelBtn?.removeEventListener('click', onCancel);
            }
            submitAnyway?.addEventListener('click', onSubmit);
            cancelBtn?.addEventListener('click', onCancel);
            unverifiedModal.show();
            return;
        }
        await performSubmission(sectionsData);
    });

    await fetchAndRender();
});
