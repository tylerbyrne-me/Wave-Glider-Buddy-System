"""
Chatbot Router

Handles HTTP endpoints for chatbot/FAQ functionality.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from fastapi.responses import HTMLResponse
from typing import List, Optional
from datetime import datetime, timezone

from sqlmodel import select
from ..core import models
from ..core.db import get_db_session, SQLModelSession
from ..core.auth import get_current_active_user, get_current_admin_user, get_optional_current_user
from ..services.chatbot_service import chatbot_service
from ..services.llm_service import llm_service, ContextSource
from ..core.templates import templates
from ..core.template_context import get_template_context
from ..config import settings
import logging

router = APIRouter(tags=["Chatbot"])
logger = logging.getLogger(__name__)


@router.get("/chatbot.html", response_class=HTMLResponse)
async def chatbot_page(
    request: Request,
    current_user: Optional[models.User] = Depends(get_optional_current_user)
):
    """Chatbot main page."""
    return templates.TemplateResponse(
        "chatbot.html",
        get_template_context(request=request, current_user=current_user)
    )


@router.get("/admin_faqs.html", response_class=HTMLResponse)
async def admin_faqs_page(
    request: Request,
    current_user: models.User = Depends(get_current_admin_user)
):
    """FAQ management page (admin only)."""
    return templates.TemplateResponse(
        "admin_faqs.html",
        get_template_context(request=request, current_user=current_user)
    )


@router.get("/api/chatbot/status")
async def get_chatbot_status(
    current_user: models.User = Depends(get_current_active_user)
):
    """Get chatbot service status including LLM availability."""
    vector_enabled = False
    vector_doc_count = 0
    vector_tip_count = 0
    vector_faq_count = 0
    
    if chatbot_service.vector_service and chatbot_service.vector_service.enabled:
        vector_enabled = True
        try:
            vector_doc_count = chatbot_service.vector_service.documents_collection.count()
            vector_tip_count = chatbot_service.vector_service.tips_collection.count()
            vector_faq_count = chatbot_service.vector_service.faq_collection.count()
        except Exception:
            pass
    
    return {
        "vector_search": {
            "enabled": vector_enabled,
            "documents_indexed": vector_doc_count,
            "tips_indexed": vector_tip_count,
            "faqs_indexed": vector_faq_count
        },
        "llm": {
            "enabled": settings.llm_enabled,
            "available": llm_service.is_available(),
            "model": settings.llm_model if settings.llm_enabled else None
        },
        "settings": {
            "similarity_threshold": settings.vector_similarity_threshold,
            "llm_temperature": settings.llm_temperature if settings.llm_enabled else None
        }
    }


@router.post("/api/chatbot/query", response_model=models.ChatbotResponse)
async def query_chatbot(
    query_request: models.ChatbotQueryRequest,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """Process a chatbot query and return matching FAQs and related resources."""
    try:
        # Get user ID from database
        from ..core import auth
        user_in_db = auth.get_user_from_db(session, current_user.username)
        user_id = user_in_db.id if user_in_db else None
        
        # Detect query intent for targeted searching
        intent = chatbot_service.detect_query_intent(query_request.query)
        
        # Get all active FAQs
        faq_stmt = select(models.FAQEntry).where(models.FAQEntry.is_active == True)
        faq_entries = session.exec(faq_stmt).all()
        
        # Match FAQs to query (uses vector search if available)
        matched_faqs_with_scores = chatbot_service.match_faqs(
            query_request.query,
            faq_entries,
            limit=5
        )
        
        matched_faqs = [faq for faq, score in matched_faqs_with_scores]
        matched_faq_ids = [faq.id for faq in matched_faqs]
        
        # Get related documents and tips from FAQs (manual links)
        all_related_doc_ids = set()
        all_related_tip_ids = set()
        
        for faq in matched_faqs:
            if faq.related_document_ids:
                doc_ids = [int(id.strip()) for id in faq.related_document_ids.split(',') if id.strip().isdigit()]
                all_related_doc_ids.update(doc_ids)
            if faq.related_tip_ids:
                tip_ids = [int(id.strip()) for id in faq.related_tip_ids.split(',') if id.strip().isdigit()]
                all_related_tip_ids.update(tip_ids)
        
        def _build_snippet(text: str, max_len: int = 240) -> str:
            snippet = " ".join((text or "").split())
            if len(snippet) <= max_len:
                return snippet
            return snippet[:max_len].rstrip() + "..."

        # Vector search for documents
        # If troubleshooting query, prioritize troubleshooting documents
        category_filter = "troubleshooting" if intent['troubleshooting'] else None
        tag_filter = "troubleshooting" if intent['troubleshooting'] else None
        
        logger.debug(f"Query intent: {intent}, category_filter: {category_filter}")
        
        vector_doc_results = chatbot_service.search_documents(
            query=query_request.query,
            category_filter=category_filter,
            tag_filter=tag_filter,
            limit=5
        )
        
        logger.debug(f"Vector doc results: {len(vector_doc_results)} matches")
        
        doc_snippets = {}
        # Add vector search document results
        for metadata, similarity, content in vector_doc_results:
            doc_id = int(metadata.get('doc_id', 0))
            logger.debug(f"  Doc match: id={doc_id}, sim={similarity:.3f}, title={metadata.get('title', 'N/A')[:30]}")
            if doc_id and doc_id not in all_related_doc_ids:
                all_related_doc_ids.add(doc_id)
            if doc_id and doc_id not in doc_snippets:
                doc_snippets[doc_id] = {
                    "snippet": _build_snippet(content),
                    "similarity": similarity,
                    "chunk_index": int(metadata.get("chunk_index", 0)) if metadata.get("chunk_index") is not None else None,
                }
        
        # Vector search for tips
        vector_tip_results = chatbot_service.search_tips(
            query=query_request.query,
            category_filter=category_filter,
            tag_filter=tag_filter,
            limit=5
        )
        
        logger.debug(f"Vector tip results: {len(vector_tip_results)} matches")
        
        tip_snippets = {}
        # Add vector search tip results
        for metadata, similarity, content in vector_tip_results:
            tip_id = int(metadata.get('tip_id', 0))
            logger.debug(f"  Tip match: id={tip_id}, sim={similarity:.3f}, title={metadata.get('title', 'N/A')[:30]}")
            if tip_id and tip_id not in all_related_tip_ids:
                all_related_tip_ids.add(tip_id)
            if tip_id and tip_id not in tip_snippets:
                tip_snippets[tip_id] = {
                    "snippet": _build_snippet(content),
                    "similarity": similarity,
                    "chunk_index": None,
                }
        
        # Fetch related documents from database
        related_documents = []
        docs_for_context = []
        if all_related_doc_ids:
            doc_stmt = select(models.KnowledgeDocument).where(
                models.KnowledgeDocument.id.in_(list(all_related_doc_ids)),
                models.KnowledgeDocument.is_active == True
            )
            docs = session.exec(doc_stmt).all()
            for doc in docs:
                snippet_meta = doc_snippets.get(doc.id, {})
                related_documents.append(models.RelatedResource(
                    type="document",
                    id=doc.id,
                    title=doc.title,
                    url=f"/knowledge_base.html#document-{doc.id}",
                    snippet=snippet_meta.get("snippet"),
                    similarity=snippet_meta.get("similarity"),
                    chunk_index=snippet_meta.get("chunk_index"),
                ))
                # Prepare context for LLM
                docs_for_context.append(doc)
        
        # Fetch related tips from database
        related_tips = []
        tips_for_context = []
        if all_related_tip_ids:
            tip_stmt = select(models.SharedTip).where(
                models.SharedTip.id.in_(list(all_related_tip_ids)),
                models.SharedTip.is_archived == False
            )
            tips = session.exec(tip_stmt).all()
            for tip in tips:
                snippet_meta = tip_snippets.get(tip.id, {})
                related_tips.append(models.RelatedResource(
                    type="tip",
                    id=tip.id,
                    title=tip.title,
                    url=f"/shared_tips.html?tip_id={tip.id}",
                    snippet=snippet_meta.get("snippet"),
                    similarity=snippet_meta.get("similarity"),
                    chunk_index=snippet_meta.get("chunk_index"),
                ))
                # Prepare context for LLM
                tips_for_context.append(tip)
        
        # Build context sources for LLM
        context_sources = []
        
        # Add FAQs to context
        for faq, score in matched_faqs_with_scores:
            context_sources.append(ContextSource(
                source_type="faq",
                title=faq.question,
                content=faq.answer,
                id=faq.id,
                category=faq.category,
                similarity=score / 100.0  # Normalize to 0-1
            ))
        
        # Add documents to context (use vector search results for similarity)
        for metadata, similarity, content in vector_doc_results:
            doc_id = int(metadata.get('doc_id', 0))
            doc_title = metadata.get('title', 'Document')
            # Find full content from database
            for doc in docs_for_context:
                if doc.id == doc_id:
                    context_sources.append(ContextSource(
                        source_type="document",
                        title=doc_title,
                        content=doc.searchable_content or content,
                        id=doc_id,
                        category=doc.category,
                        similarity=similarity
                    ))
                    break
        
        # Add tips to context
        for metadata, similarity, content in vector_tip_results:
            tip_id = int(metadata.get('tip_id', 0))
            tip_title = metadata.get('title', 'Tip')
            for tip in tips_for_context:
                if tip.id == tip_id:
                    context_sources.append(ContextSource(
                        source_type="tip",
                        title=tip_title,
                        content=tip.content,
                        id=tip_id,
                        category=tip.category,
                        similarity=similarity
                    ))
                    break
        
        # Try to synthesize response with LLM
        synthesized_response = None
        sources_used = []
        llm_used = False
        llm_model = None
        
        if context_sources and llm_service.is_available():
            logger.debug(f"Attempting LLM synthesis with {len(context_sources)} context sources")
            # Use async version to avoid blocking the event loop
            synthesized_response, sources_used = await llm_service.synthesize_response_async(
                query=query_request.query,
                context_sources=context_sources
            )
            if synthesized_response:
                llm_used = True
                llm_model = settings.llm_model  # Include the model name
                logger.info(f"LLM ({llm_model}) synthesized response from {len(sources_used)} sources")
        
        # Log interaction
        interaction = models.ChatbotInteraction(
            user_id=user_id,
            query=query_request.query,
            matched_faq_ids=','.join(map(str, matched_faq_ids)) if matched_faq_ids else None
        )
        session.add(interaction)
        session.commit()
        session.refresh(interaction)
        
        # Increment view count for matched FAQs
        for faq in matched_faqs:
            faq.view_count += 1
            session.add(faq)
        session.commit()
        
        # Convert FAQs to response models
        faq_reads = [models.FAQEntryRead.model_validate(faq) for faq in matched_faqs]
        
        return models.ChatbotResponse(
            matched_faqs=faq_reads,
            related_documents=related_documents,
            related_tips=related_tips,
            interaction_id=interaction.id,
            synthesized_response=synthesized_response,
            sources_used=sources_used,
            llm_used=llm_used,
            llm_model=llm_model
        )
        
    except Exception as e:
        logger.error(f"Error processing chatbot query: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error processing query: {str(e)}")


@router.post("/api/chatbot/feedback", status_code=status.HTTP_204_NO_CONTENT)
async def submit_chatbot_feedback(
    feedback: models.ChatbotFeedbackRequest,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """Submit feedback on a chatbot response."""
    try:
        interaction = session.get(models.ChatbotInteraction, feedback.interaction_id)
        if not interaction:
            raise HTTPException(status_code=404, detail="Interaction not found")
        
        interaction.was_helpful = feedback.was_helpful
        if feedback.selected_faq_id:
            interaction.selected_faq_id = feedback.selected_faq_id
            # Increment helpful count for selected FAQ
            faq = session.get(models.FAQEntry, feedback.selected_faq_id)
            if faq:
                if feedback.was_helpful:
                    faq.helpful_count += 1
                session.add(faq)
        
        session.add(interaction)
        session.commit()
        
        logger.info(f"User '{current_user.username}' submitted chatbot feedback: helpful={feedback.was_helpful}")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error submitting chatbot feedback: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error submitting feedback: {str(e)}")


# Admin endpoints for FAQ management
@router.get("/api/admin/faqs", response_model=List[models.FAQEntryRead])
async def list_faqs(
    category: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    current_admin: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """List all FAQs (admin only)."""
    statement = select(models.FAQEntry)
    
    if category:
        statement = statement.where(models.FAQEntry.category == category)
    if is_active is not None:
        statement = statement.where(models.FAQEntry.is_active == is_active)
    
    statement = statement.order_by(models.FAQEntry.created_at_utc.desc())
    
    faqs = session.exec(statement).all()
    return [models.FAQEntryRead.model_validate(faq) for faq in faqs]


@router.post("/api/admin/faqs", response_model=models.FAQEntryRead, status_code=status.HTTP_201_CREATED)
async def create_faq(
    faq_data: models.FAQEntryCreate,
    current_admin: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """Create a new FAQ entry (admin only)."""
    faq = models.FAQEntry(
        question=faq_data.question,
        answer=faq_data.answer,
        keywords=faq_data.keywords,
        category=faq_data.category,
        tags=faq_data.tags,
        related_document_ids=faq_data.related_document_ids,
        related_tip_ids=faq_data.related_tip_ids,
        created_by_username=current_admin.username
    )
    
    session.add(faq)
    session.commit()
    session.refresh(faq)
    
    # Auto-vectorize FAQ for semantic search
    try:
        if chatbot_service.vector_service and chatbot_service.vector_service.enabled:
            chatbot_service.vector_service.add_faq(
                faq_id=faq.id,
                question=faq.question,
                answer=faq.answer,
                category=faq.category,
                tags=faq.tags,
                keywords=faq.keywords
            )
            logger.info(f"FAQ {faq.id} vectorized for semantic search")
    except Exception as e:
        logger.warning(f"Failed to vectorize FAQ {faq.id}: {e}")
    
    logger.info(f"Admin '{current_admin.username}' created FAQ: {faq.question}")
    return models.FAQEntryRead.model_validate(faq)


@router.put("/api/admin/faqs/{faq_id}", response_model=models.FAQEntryRead)
async def update_faq(
    faq_id: int,
    faq_data: models.FAQEntryUpdate,
    current_admin: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """Update an FAQ entry (admin only)."""
    faq = session.get(models.FAQEntry, faq_id)
    if not faq:
        raise HTTPException(status_code=404, detail="FAQ not found")
    
    update_dict = faq_data.model_dump(exclude_unset=True)
    for field, value in update_dict.items():
        setattr(faq, field, value)
    
    faq.updated_at_utc = datetime.now(timezone.utc)
    
    session.add(faq)
    session.commit()
    session.refresh(faq)
    
    # Update FAQ in vector store
    try:
        if chatbot_service.vector_service and chatbot_service.vector_service.enabled:
            chatbot_service.vector_service.add_faq(
                faq_id=faq.id,
                question=faq.question,
                answer=faq.answer,
                category=faq.category,
                tags=faq.tags,
                keywords=faq.keywords
            )
            logger.info(f"FAQ {faq.id} updated in vector store")
    except Exception as e:
        logger.warning(f"Failed to update FAQ {faq.id} in vector store: {e}")
    
    logger.info(f"Admin '{current_admin.username}' updated FAQ {faq_id}")
    return models.FAQEntryRead.model_validate(faq)


@router.delete("/api/admin/faqs/{faq_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_faq(
    faq_id: int,
    current_admin: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """Delete an FAQ entry (admin only)."""
    faq = session.get(models.FAQEntry, faq_id)
    if not faq:
        raise HTTPException(status_code=404, detail="FAQ not found")
    
    # Remove from vector store
    try:
        if chatbot_service.vector_service and chatbot_service.vector_service.enabled:
            chatbot_service.vector_service.delete_faq(faq_id)
    except Exception as e:
        logger.warning(f"Failed to delete FAQ {faq_id} from vector store: {e}")
    
    session.delete(faq)
    session.commit()
    
    logger.info(f"Admin '{current_admin.username}' deleted FAQ {faq_id}")
    return None
