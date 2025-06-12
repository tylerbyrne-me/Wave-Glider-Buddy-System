document.addEventListener('DOMContentLoaded', function () {
    if (!checkAuth()) { // from auth.js
        // If checkAuth redirects, this script might not fully execute, which is fine.
        return;
    }

    const formsTableBody = document.getElementById('formsTableBody');
    const formsSpinner = document.getElementById('formsSpinner');
    const formsTableContainer = document.getElementById('formsTableContainer');
    const noFormsMessage = document.getElementById('noFormsMessage');
    const formDetailsModal = new bootstrap.Modal(document.getElementById('formDetailsModal'));
    const formDetailsContentElement = document.getElementById('formDetailsContent'); // Updated ID
    const backToDashboardBtn = document.getElementById('backToDashboardBtn');

    async function fetchAndDisplayForms() {
        formsSpinner.style.display = 'block';
        formsTableContainer.style.display = 'none';
        noFormsMessage.style.display = 'none';

        try {
            const response = await fetchWithAuth('/api/forms/all'); // Assumes fetchWithAuth is globally available from auth.js
            if (!response.ok) {
                if (response.status === 401 || response.status === 403) {
                    // Should be handled by checkAuth, but as a fallback:
                    logout(); // Redirect to login if not authorized
                    return;
                }
                const errorData = await response.json();
                throw new Error(errorData.detail || `Failed to load forms (Status: ${response.status})`);
            }
            const forms = await response.json();

            formsTableBody.innerHTML = ''; // Clear existing rows

            if (forms.length === 0) {
                noFormsMessage.style.display = 'block';
            } else {
                forms.forEach(form => {
                    const row = formsTableBody.insertRow();
                    row.insertCell().textContent = form.mission_id;
                    row.insertCell().textContent = form.form_type;
                    row.insertCell().textContent = form.form_title;
                    row.insertCell().textContent = form.submitted_by_username;
                    row.insertCell().textContent = new Date(form.submission_timestamp).toLocaleString();
                    
                    const actionsCell = row.insertCell();
                    const viewButton = document.createElement('button');
                    viewButton.classList.add('btn', 'btn-sm', 'btn-outline-info');
                    viewButton.textContent = 'View Details';
                    viewButton.onclick = () => {
                        document.getElementById('formDetailsModalLabel').textContent = `Details for: ${form.form_title} (${form.form_type})`;
                        formDetailsContentElement.innerHTML = ''; // Clear previous content

                        if (form.sections_data && form.sections_data.length > 0) {
                            form.sections_data.forEach(section => {
                                const sectionDiv = document.createElement('div');
                                sectionDiv.classList.add('mb-4'); // Spacing between sections

                                const sectionTitle = document.createElement('h5');
                                sectionTitle.textContent = section.title;
                                sectionDiv.appendChild(sectionTitle);

                                if (section.section_comment) {
                                    const sectionCommentP = document.createElement('p');
                                    sectionCommentP.classList.add('text-muted', 'fst-italic', 'ms-2');
                                    sectionCommentP.textContent = `Section Notes: ${section.section_comment}`;
                                    sectionDiv.appendChild(sectionCommentP);
                                }

                                const itemList = document.createElement('ul');
                                itemList.classList.add('list-group', 'list-group-flush');

                                section.items.forEach(item => {
                                    const listItem = document.createElement('li');
                                    listItem.classList.add('list-group-item', 'bg-transparent'); // bg-transparent for dark mode
                                    
                                    let itemValueDisplay = '';
                                    if (item.item_type === 'checkbox') {
                                        itemValueDisplay = item.is_checked ? 'Checked' : 'Unchecked';
                                    } else if (item.item_type === 'autofilled_value' || item.item_type === 'static_text') {
                                        itemValueDisplay = item.value || 'N/A';
                                    } else { // text_input, text_area
                                        itemValueDisplay = item.value || '(empty)';
                                    }

                                    listItem.innerHTML = `<strong>${item.label}:</strong> ${itemValueDisplay}`;
                                    if (item.comment) {
                                        listItem.innerHTML += `<br><small class="text-info ms-3"><em>Comment: ${item.comment}</em></small>`;
                                    }
                                    itemList.appendChild(listItem);
                                });
                                sectionDiv.appendChild(itemList);
                                formDetailsContentElement.appendChild(sectionDiv);
                            });
                        } else {
                            formDetailsContentElement.textContent = 'No detailed section data available for this form.';
                        }
                        formDetailsModal.show();
                    };
                    actionsCell.appendChild(viewButton);
                });
                formsTableContainer.style.display = 'block';
            }
        } catch (error) {
            console.error('Error fetching or displaying forms:', error);
            formsTableBody.innerHTML = `<tr><td colspan="6" class="text-center text-danger">Error loading forms: ${error.message}</td></tr>`;
            formsTableContainer.style.display = 'block'; // Show table container to display error
            noFormsMessage.style.display = 'none';
        } finally {
            formsSpinner.style.display = 'none';
        }
    }

    // Initial load
    fetchAndDisplayForms();

    // Event listener for the "Close Page" button
    if (backToDashboardBtn) {
        backToDashboardBtn.addEventListener('click', function(event) {
            event.preventDefault(); // Prevent default anchor behavior
            window.close();
        });
    }
});