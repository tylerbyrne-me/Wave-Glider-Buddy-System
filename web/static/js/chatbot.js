/**
 * @file chatbot.js
 * @description Chatbot frontend functionality
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
    
    initializeChatbot();
});

function initializeChatbot() {
    const chatMessages = document.getElementById('chatMessages');
    const chatInput = document.getElementById('chatInput');
    const sendButton = document.getElementById('sendButton');
    const quickQuestions = document.getElementById('quickQuestions');
    
    let currentInteractionId = null;
    
    // Load quick questions (sample questions)
    const sampleQuestions = [
        "How do I upload a document?",
        "What are shared tips?",
        "How do I create a note?",
        "Where can I find mission information?"
    ];
    
    sampleQuestions.forEach(question => {
        const btn = document.createElement('button');
        btn.className = 'btn btn-outline-primary btn-sm';
        btn.textContent = question;
        btn.addEventListener('click', () => {
            chatInput.value = question;
            handleSendMessage();
        });
        quickQuestions.appendChild(btn);
    });
    
    // Send message on Enter key
    chatInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSendMessage();
        }
    });
    
    // Send message on button click
    sendButton.addEventListener('click', handleSendMessage);
    
    async function handleSendMessage() {
        const query = chatInput.value.trim();
        if (!query) return;
        
        // Add user message to chat
        addMessage('user', query);
        chatInput.value = '';
        sendButton.disabled = true;
        sendButton.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
        
        try {
            const response = await apiRequest('/api/chatbot/query', 'POST', { query });
            currentInteractionId = response.interaction_id;
            
            // Display bot response
            const hasSynthesized = response.synthesized_response && response.synthesized_response.length > 0;
            const hasFaqs = response.matched_faqs && response.matched_faqs.length > 0;
            const hasDocs = response.related_documents && response.related_documents.length > 0;
            const hasTips = response.related_tips && response.related_tips.length > 0;
            
            if (hasSynthesized) {
                // LLM synthesized a response - show it as the main answer
                console.log('LLM Response received:', {
                    hasSynthesized: hasSynthesized,
                    llm_model: response.llm_model,
                    llm_used: response.llm_used
                });
                addSynthesizedMessage(response.synthesized_response, response.sources_used || [], response.llm_model);
                
                // Show related resources for reference
                if (hasDocs || hasTips) {
                    addRelatedResources(response.related_documents, response.related_tips);
                }
            } else if (hasFaqs) {
                // Show FAQ answers (fallback when LLM not available)
                response.matched_faqs.forEach((faq, index) => {
                    addMessage('bot', faq.answer, {
                        question: faq.question,
                        faqId: faq.id,
                        isFirst: index === 0
                    });
                });
                
                // Show related resources if available
                if (hasDocs || hasTips) {
                    addRelatedResources(response.related_documents, response.related_tips);
                }
            } else if (hasDocs || hasTips) {
                // No FAQs but found documents/tips - show them as primary results
                addMessage('bot', "I found some relevant resources that might help:");
                addRelatedResources(response.related_documents, response.related_tips, true);
            } else {
                addMessage('bot', "I couldn't find a specific answer to your question. Try rephrasing or check the Knowledge Base and Shared Tips sections for more information.");
            }
        } catch (error) {
            addMessage('bot', `Sorry, I encountered an error: ${error.message || 'Unknown error'}. Please try again.`, { isError: true });
        } finally {
            sendButton.disabled = false;
            sendButton.innerHTML = '<i class="fas fa-paper-plane"></i> Send';
        }
    }
    
    function addMessage(sender, content, metadata = {}) {
        // Clear initial placeholder if this is the first message
        if (chatMessages.querySelector('.text-center.text-muted')) {
            chatMessages.innerHTML = '';
        }
        
        const messageDiv = document.createElement('div');
        messageDiv.className = `mb-3 ${sender === 'user' ? 'text-end' : 'text-start'}`;
        
        const messageBubble = document.createElement('div');
        messageBubble.className = `d-inline-block p-3 rounded ${sender === 'user' ? 'bg-primary text-white' : 'bg-white border'} ${metadata.isError ? 'border-danger' : ''}`;
        messageBubble.style.maxWidth = '75%';
        
        if (sender === 'bot' && metadata.question) {
            messageBubble.innerHTML = `
                <div class="fw-bold mb-2">
                    <i class="fas fa-question-circle"></i> ${escapeHtml(metadata.question)}
                </div>
                <div>${escapeHtml(content)}</div>
                ${metadata.isFirst ? `
                    <div class="mt-3 d-flex gap-2">
                        <button class="btn btn-sm btn-success helpful-btn" data-faq-id="${metadata.faqId}">
                            <i class="fas fa-thumbs-up"></i> Helpful
                        </button>
                        <button class="btn btn-sm btn-outline-secondary not-helpful-btn" data-faq-id="${metadata.faqId}">
                            <i class="fas fa-thumbs-down"></i> Not Helpful
                        </button>
                    </div>
                ` : ''}
            `;
        } else {
            messageBubble.textContent = content;
        }
        
        messageDiv.appendChild(messageBubble);
        chatMessages.appendChild(messageDiv);
        
        // Scroll to bottom
        chatMessages.scrollTop = chatMessages.scrollHeight;
        
        // Add event listeners for feedback buttons
        if (metadata.isFirst) {
            const helpfulBtn = messageDiv.querySelector('.helpful-btn');
            const notHelpfulBtn = messageDiv.querySelector('.not-helpful-btn');
            
            if (helpfulBtn) {
                helpfulBtn.addEventListener('click', () => submitFeedback(true, metadata.faqId));
            }
            if (notHelpfulBtn) {
                notHelpfulBtn.addEventListener('click', () => submitFeedback(false, metadata.faqId));
            }
        }
    }
    
    function addSynthesizedMessage(content, sources, llmModel) {
        // Debug logging
        console.log('addSynthesizedMessage called with:', { llmModel, hasContent: !!content, sourcesCount: sources?.length || 0 });
        
        // Clear initial placeholder if this is the first message
        if (chatMessages.querySelector('.text-center.text-muted')) {
            chatMessages.innerHTML = '';
        }
        
        const messageDiv = document.createElement('div');
        messageDiv.className = 'mb-3 text-start';
        
        const messageBubble = document.createElement('div');
        messageBubble.className = 'd-inline-block p-3 rounded bg-white border border-success';
        messageBubble.style.maxWidth = '85%';
        
        // Format the synthesized response with markdown-like formatting
        let formattedContent = escapeHtml(content)
            .replace(/\n\n/g, '</p><p>')
            .replace(/\n/g, '<br>')
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
            .replace(/\*(.*?)\*/g, '<em>$1</em>');
        
        let sourcesHtml = '';
        if (sources && sources.length > 0) {
            sourcesHtml = `
                <div class="mt-3 pt-2 border-top">
                    <small class="text-muted">
                        <i class="fas fa-book-open"></i> Sources: ${sources.map(s => escapeHtml(s)).join(', ')}
                    </small>
                </div>
            `;
        }
        
        // Build the LLM header with model name highlighted
        let llmHeader = '';
        if (llmModel) {
            // Model name is highlighted with a badge-style appearance
            llmHeader = `
                <div class="d-flex align-items-center mb-2">
                    <i class="fas fa-robot text-success me-2"></i>
                    <small class="text-success fw-bold">
                        LLM (<span class="badge bg-success text-white px-2 py-1 rounded" style="font-size: 0.75em;">${escapeHtml(llmModel)}</span>) Generated Response
                    </small>
                </div>
            `;
        } else {
            // Fallback if model name not provided
            llmHeader = `
                <div class="d-flex align-items-center mb-2">
                    <i class="fas fa-robot text-success me-2"></i>
                    <small class="text-success fw-bold">LLM Generated Response</small>
                </div>
            `;
        }
        
        messageBubble.innerHTML = `
            ${llmHeader}
            <div class="mb-2"><p>${formattedContent}</p></div>
            ${sourcesHtml}
            <div class="mt-3 d-flex gap-2">
                <button class="btn btn-sm btn-success helpful-btn">
                    <i class="fas fa-thumbs-up"></i> Helpful
                </button>
                <button class="btn btn-sm btn-outline-secondary not-helpful-btn">
                    <i class="fas fa-thumbs-down"></i> Not Helpful
                </button>
            </div>
        `;
        
        messageDiv.appendChild(messageBubble);
        chatMessages.appendChild(messageDiv);
        chatMessages.scrollTop = chatMessages.scrollHeight;
        
        // Add event listeners for feedback buttons
        const helpfulBtn = messageDiv.querySelector('.helpful-btn');
        const notHelpfulBtn = messageDiv.querySelector('.not-helpful-btn');
        
        if (helpfulBtn) {
            helpfulBtn.addEventListener('click', () => submitFeedback(true, null));
        }
        if (notHelpfulBtn) {
            notHelpfulBtn.addEventListener('click', () => submitFeedback(false, null));
        }
    }
    
    function addRelatedResources(documents, tips, isPrimaryResult = false) {
        const resourcesDiv = document.createElement('div');
        resourcesDiv.className = 'mb-3 text-start';
        
        const headerText = isPrimaryResult ? 'Matching Resources:' : 'Related Resources:';
        const bgClass = isPrimaryResult ? 'bg-white border-primary' : 'bg-light';
        
        let resourcesHtml = `<div class="${bgClass} p-3 rounded border"><strong><i class="fas fa-link"></i> ${headerText}</strong><ul class="mb-0 mt-2">`;
        
        documents.forEach(doc => {
            resourcesHtml += `<li><a href="${doc.url}" target="_blank">📄 ${escapeHtml(doc.title)}</a></li>`;
        });
        
        tips.forEach(tip => {
            resourcesHtml += `<li><a href="${tip.url}" target="_blank">💡 ${escapeHtml(tip.title)}</a></li>`;
        });
        
        resourcesHtml += '</ul></div>';
        resourcesDiv.innerHTML = resourcesHtml;
        chatMessages.appendChild(resourcesDiv);
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }
    
    async function submitFeedback(wasHelpful, faqId) {
        if (!currentInteractionId) return;
        
        try {
            await apiRequest('/api/chatbot/feedback', 'POST', {
                interaction_id: currentInteractionId,
                was_helpful: wasHelpful,
                selected_faq_id: faqId
            });
            
            // Disable feedback buttons
            document.querySelectorAll('.helpful-btn, .not-helpful-btn').forEach(btn => {
                btn.disabled = true;
                btn.classList.add('opacity-50');
            });
            
            showToast(wasHelpful ? 'Thank you for your feedback!' : 'Thanks for letting us know. We\'ll improve our answers.', 'success');
        } catch (error) {
            console.error('Error submitting feedback:', error);
        }
    }
    
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}
