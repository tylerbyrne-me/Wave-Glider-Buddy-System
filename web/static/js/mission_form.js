document.addEventListener('DOMContentLoaded', function () {
    if (!checkAuth()) { // from auth.js
        return;
    }

    const missionId = document.body.dataset.missionId;
    const formType = document.body.dataset.formType;
    const username = document.body.dataset.username;

    const formTitleElement = document.getElementById('formTitle');
    const formDescriptionElement = document.getElementById('formDescription');
    const formSectionsContainer = document.getElementById('formSectionsContainer');
    const missionReportForm = document.getElementById('missionReportForm');
    const submissionStatusDiv = document.getElementById('submissionStatus');
    const formSpinner = document.getElementById('formSpinner');

    async function fetchAndRenderFormSchema() {
        formSpinner.style.display = 'block';
        missionReportForm.style.display = 'none';
        try {
            const response = await fetchWithAuth(`/api/forms/${missionId}/template/${formType}`);
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || `Failed to load form template (Status: ${response.status})`);
            }
            const schema = await response.json();

            formTitleElement.textContent = schema.title || 'Mission Form';
            if (schema.description) {
                formDescriptionElement.textContent = schema.description;
            }

            formSectionsContainer.innerHTML = ''; // Clear previous content

            schema.sections.forEach(section => {
                const sectionDiv = document.createElement('div');
                sectionDiv.classList.add('form-section');
                sectionDiv.innerHTML = `<h3>${section.title}</h3>`;

                section.items.forEach(item => {
                    const itemDiv = document.createElement('div');
                    itemDiv.classList.add('form-item', 'mb-3');
                    itemDiv.dataset.itemId = item.id; // Store item id

                    let itemHtml = `<label for="${item.id}" class="form-label">${item.label}${item.required ? '<span class="text-danger">*</span>' : ''}</label>`;

                    switch (item.item_type) {
                        case 'checkbox':
                            itemHtml += `<div class="form-check">
                                           <input class="form-check-input" type="checkbox" id="${item.id}" name="${item.id}" ${item.is_checked ? 'checked' : ''} ${item.required ? 'required' : ''}>
                                           <label class="form-check-label" for="${item.id}">Check if complete/verified</label>
                                         </div>`;
                            break;
                        case 'text_input':
                            itemHtml += `<input type="text" class="form-control" id="${item.id}" name="${item.id}" value="${item.value || ''}" placeholder="${item.placeholder || ''}" ${item.required ? 'required' : ''}>`;
                            break;
                        case 'text_area':
                            itemHtml += `<textarea class="form-control" id="${item.id}" name="${item.id}" rows="3" placeholder="${item.placeholder || ''}" ${item.required ? 'required' : ''}>${item.value || ''}</textarea>`;
                            break;
                        case 'autofilled_value':
                            itemHtml += `<div class="autofilled-value" id="${item.id}">${item.value || 'N/A'}</div>`;
                            break;
                        case 'static_text':
                            itemHtml += `<p class="static-text" id="${item.id}">${item.value || ''}</p>`;
                            break;
                    }
                    // Add comment field for all interactive types
                    if (item.item_type !== 'autofilled_value' && item.item_type !== 'static_text') {
                         itemHtml += `<textarea class="form-control form-control-sm mt-2" name="${item.id}_comment" rows="1" placeholder="Optional comment..."></textarea>`;
                    }

                    itemDiv.innerHTML = itemHtml;
                    sectionDiv.appendChild(itemDiv);
                });

                if (section.section_comment) {
                    sectionDiv.innerHTML += `<div class="mt-3">
                                                <label for="${section.id}_comment" class="form-label">Section Notes:</label>
                                                <textarea class="form-control" id="${section.id}_comment" name="${section.id}_comment" rows="2" placeholder="Overall notes for this section...">${section.section_comment || ''}</textarea>
                                             </div>`;
                }
                formSectionsContainer.appendChild(sectionDiv);
            });
            missionReportForm.style.display = 'block';
        } catch (error) {
            console.error('Error fetching or rendering form schema:', error);
            formTitleElement.textContent = 'Error Loading Form';
            formDescriptionElement.textContent = error.message;
            submissionStatusDiv.innerHTML = `<div class="alert alert-danger">${error.message}</div>`;
        } finally {
            formSpinner.style.display = 'none';
        }
    }

    missionReportForm.addEventListener('submit', async function (event) {
        event.preventDefault();
        submissionStatusDiv.innerHTML = '<div class="alert alert-info">Submitting form...</div>';

        const formData = new FormData(missionReportForm);
        const sectionsData = [];

        // Reconstruct sections and items from the form
        document.querySelectorAll('.form-section').forEach(sectionElem => {
            const sectionTitle = sectionElem.querySelector('h3').textContent;
            const sectionId = sectionElem.id || sectionTitle.toLowerCase().replace(/\s+/g, '_'); // Fallback id
            const sectionCommentElem = sectionElem.querySelector(`textarea[name="${sectionId}_comment"]`);
            const section = {
                id: sectionId,
                title: sectionTitle,
                items: [],
                section_comment: sectionCommentElem ? sectionCommentElem.value.trim() : null
            };

            sectionElem.querySelectorAll('.form-item').forEach(itemElem => {
                const itemId = itemElem.dataset.itemId;
                const label = itemElem.querySelector('label[for="' + itemId + '"]').textContent.replace('*','').trim();
                const inputElem = missionReportForm.elements[itemId];
                const commentElem = missionReportForm.elements[`${itemId}_comment`];

                const formItem = {
                    id: itemId,
                    label: label,
                    item_type: '', // Will be set by backend schema, not strictly needed for submission if backend re-validates
                    value: null,
                    is_checked: null,
                    comment: commentElem ? commentElem.value.trim() : null
                };

                if (inputElem) {
                    if (inputElem.type === 'checkbox') {
                        formItem.is_checked = inputElem.checked;
                        formItem.item_type = 'checkbox';
                    } else if (inputElem.type === 'textarea' || inputElem.type === 'text') {
                        formItem.value = inputElem.value.trim();
                        formItem.item_type = inputElem.type === 'textarea' ? 'text_area' : 'text_input';
                    }
                } else { // For autofilled or static, grab the displayed value if needed, or rely on schema
                    const displayElem = document.getElementById(itemId);
                    if (displayElem && (displayElem.classList.contains('autofilled-value') || displayElem.classList.contains('static-text'))) {
                        formItem.value = displayElem.textContent;
                        formItem.item_type = displayElem.classList.contains('autofilled-value') ? 'autofilled_value' : 'static_text';
                    }
                }
                section.items.push(formItem);
            });
            sectionsData.push(section);
        });

        const submissionPayload = {
            mission_id: missionId,
            form_type: formType,
            form_title: formTitleElement.textContent,
            sections_data: sectionsData
        };

        try {
            const response = await fetchWithAuth(`/api/forms/${missionId}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(submissionPayload)
            });
            const result = await response.json();
            if (response.ok) {
                submissionStatusDiv.innerHTML = `<div class="alert alert-success">Form submitted successfully at ${new Date(result.submission_timestamp).toLocaleString()} by ${result.submitted_by_username}!</div>`;
                missionReportForm.reset(); // Optionally reset the form
                setTimeout(() => { window.location.href = '/'; }, 2000); // Redirect after 2s
            } else {
                submissionStatusDiv.innerHTML = `<div class="alert alert-danger">Submission failed: ${result.detail || 'Unknown error'}</div>`;
            }
        } catch (error) {
            console.error('Error submitting form:', error);
            submissionStatusDiv.innerHTML = `<div class="alert alert-danger">Network error or unexpected issue during submission.</div>`;
        }
    });

    // Initial load
    fetchAndRenderFormSchema();
});