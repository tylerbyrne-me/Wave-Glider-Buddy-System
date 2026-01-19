"""
Chatbot Service

Handles keyword-based FAQ matching and query processing.
Enhanced with vector search for semantic matching.
"""

import logging
from typing import List, Tuple, Optional, Dict
from pathlib import Path
from sqlmodel import select, or_, func
from ..core.models.database import FAQEntry, KnowledgeDocument, SharedTip
from ..core.models.schemas import FAQEntryRead, RelatedResource
from ..config import settings

logger = logging.getLogger(__name__)

# Try to import vector search service
try:
    from .vector_search_service import VectorSearchService
    VECTOR_SEARCH_AVAILABLE = True
except ImportError:
    VECTOR_SEARCH_AVAILABLE = False
    logger.warning("Vector search not available - dependencies may not be installed")


class ChatbotService:
    """Service for chatbot operations with vector search support."""
    
    def __init__(self):
        """Initialize the chatbot service."""
        self.vector_service = None
        
        # Initialize vector search if enabled and available
        if settings.vector_search_enabled and VECTOR_SEARCH_AVAILABLE:
            try:
                storage_path = Path("data_store/chroma_db")
                self.vector_service = VectorSearchService(storage_path=storage_path)
                if self.vector_service.enabled:
                    logger.info("Vector search service initialized successfully")
                else:
                    logger.warning("Vector search service disabled - dependencies not available")
            except Exception as e:
                logger.error(f"Failed to initialize vector search: {e}")
                self.vector_service = None
    
    def match_faqs(
        self,
        query: str,
        faq_entries: List[FAQEntry],
        limit: int = 5,
        use_vector_search: bool = True
    ) -> List[Tuple[FAQEntry, float]]:
        """
        Match FAQ entries to a query using vector search (if available) or keyword matching.
        
        Args:
            query: User's query text
            faq_entries: List of FAQ entries to search
            limit: Maximum number of results to return
            use_vector_search: Whether to use vector search (falls back to keyword if unavailable)
            
        Returns:
            List of tuples (FAQEntry, confidence_score) sorted by confidence
        """
        if not query or not query.strip():
            return []
        
        # Try vector search first if available
        if use_vector_search and self.vector_service and self.vector_service.enabled:
            try:
                vector_matches = self.vector_service.search_faqs(
                    query=query,
                    limit=limit,
                    similarity_threshold=settings.vector_similarity_threshold
                )
                
                if vector_matches:
                    # Convert vector search results to FAQEntry objects
                    faq_dict = {faq.id: faq for faq in faq_entries}
                    results = []
                    
                    for metadata, similarity in vector_matches:
                        faq_id = int(metadata.get('faq_id', 0))
                        if faq_id in faq_dict:
                            # Convert similarity (0-1) to confidence score (0-100)
                            confidence = similarity * 100.0
                            results.append((faq_dict[faq_id], confidence))
                    
                    if results:
                        logger.debug(f"Vector search found {len(results)} FAQ matches")
                        return results
            except Exception as e:
                logger.warning(f"Vector search failed, falling back to keyword matching: {e}")
        
        # Fallback to keyword matching
        return self._match_faqs_keyword(query, faq_entries, limit)
    
    def _match_faqs_keyword(
        self,
        query: str,
        faq_entries: List[FAQEntry],
        limit: int = 5
    ) -> List[Tuple[FAQEntry, float]]:
        """Keyword-based FAQ matching (fallback method)."""
        if not query or not query.strip():
            return []
        
        query_lower = query.lower().strip()
        query_words = set(query_lower.split())
        
        matches = []
        
        for faq in faq_entries:
            if not faq.is_active:
                continue
            
            score = 0.0
            
            # Check question match
            question_lower = faq.question.lower()
            if query_lower in question_lower:
                score += 50.0  # Exact phrase match in question
            else:
                # Count matching words in question
                question_words = set(question_lower.split())
                matching_words = query_words.intersection(question_words)
                if matching_words:
                    score += len(matching_words) * 10.0
            
            # Check answer match
            if faq.answer:
                answer_lower = faq.answer.lower()
                if query_lower in answer_lower:
                    score += 20.0  # Exact phrase match in answer
                else:
                    answer_words = set(answer_lower.split())
                    matching_words = query_words.intersection(answer_words)
                    if matching_words:
                        score += len(matching_words) * 5.0
            
            # Check keywords match
            if faq.keywords:
                keywords_lower = [k.strip().lower() for k in faq.keywords.split(',')]
                for keyword in keywords_lower:
                    if keyword in query_lower:
                        score += 30.0  # Keyword match
                    # Also check if query contains keyword
                    if keyword in query_words:
                        score += 15.0
            
            # Check tags match
            if faq.tags:
                tags_lower = [t.strip().lower() for t in faq.tags.split(',')]
                for tag in tags_lower:
                    if tag in query_lower:
                        score += 10.0
            
            # Boost score for shorter queries that match well
            if len(query_words) <= 3 and score > 20:
                score *= 1.2
            
            if score > 0:
                matches.append((faq, score))
        
        # Sort by score descending
        matches.sort(key=lambda x: x[1], reverse=True)
        
        # Return top matches
        return matches[:limit]
    
    def search_documents(
        self,
        query: str,
        category_filter: Optional[str] = None,
        tag_filter: Optional[str] = None,
        limit: int = 5
    ) -> List[Tuple[Dict, float, str]]:
        """
        Search documents using vector search with optional category/tag filtering.
        Perfect for troubleshooting queries!
        
        Args:
            query: Search query
            category_filter: Filter by category (e.g., "troubleshooting")
            tag_filter: Filter by tag
            limit: Maximum results
            
        Returns:
            List of (metadata_dict, similarity_score, content) tuples
        """
        if self.vector_service and self.vector_service.enabled:
            try:
                return self.vector_service.search_documents(
                    query=query,
                    category_filter=category_filter,
                    tag_filter=tag_filter,
                    limit=limit,
                    similarity_threshold=settings.vector_similarity_threshold
                )
            except Exception as e:
                logger.error(f"Error in vector document search: {e}")
        
        return []
    
    def search_tips(
        self,
        query: str,
        category_filter: Optional[str] = None,
        tag_filter: Optional[str] = None,
        limit: int = 5
    ) -> List[Tuple[Dict, float, str]]:
        """
        Search shared tips using vector search with optional category/tag filtering.
        
        Args:
            query: Search query
            category_filter: Filter by category (e.g., "troubleshooting")
            tag_filter: Filter by tag
            limit: Maximum results
            
        Returns:
            List of (metadata_dict, similarity_score, content) tuples
        """
        if self.vector_service and self.vector_service.enabled:
            try:
                return self.vector_service.search_tips(
                    query=query,
                    category_filter=category_filter,
                    tag_filter=tag_filter,
                    limit=limit,
                    similarity_threshold=settings.vector_similarity_threshold
                )
            except Exception as e:
                logger.error(f"Error in vector tip search: {e}")
        
        return []
    
    def detect_query_intent(self, query: str) -> Dict[str, bool]:
        """
        Detect the intent of a query to determine search strategy.
        
        Returns:
            Dict with intent flags: troubleshooting, procedure, general
        """
        query_lower = query.lower()
        
        # Troubleshooting indicators
        troubleshooting_keywords = [
            'error', 'fix', 'problem', 'issue', 'troubleshoot', 'broken',
            'not working', 'failed', 'failure', 'debug', 'resolve', 'repair'
        ]
        
        # Procedure indicators
        procedure_keywords = [
            'how to', 'how do i', 'procedure', 'steps', 'guide', 'tutorial',
            'setup', 'install', 'configure', 'calibrate', 'initialize'
        ]
        
        is_troubleshooting = any(kw in query_lower for kw in troubleshooting_keywords)
        is_procedure = any(kw in query_lower for kw in procedure_keywords)
        
        return {
            'troubleshooting': is_troubleshooting,
            'procedure': is_procedure,
            'general': not (is_troubleshooting or is_procedure)
        }
    
    def find_related_resources(
        self,
        faq: FAQEntry,
        documents: List[KnowledgeDocument],
        tips: List[SharedTip]
    ) -> Tuple[List[RelatedResource], List[RelatedResource]]:
        """
        Find related documents and tips for an FAQ entry.
        
        Args:
            faq: FAQ entry
            documents: List of knowledge documents
            tips: List of shared tips
            
        Returns:
            Tuple of (related_documents, related_tips)
        """
        related_docs = []
        related_tips = []
        
        # Get related document IDs
        if faq.related_document_ids:
            doc_ids = [int(id.strip()) for id in faq.related_document_ids.split(',') if id.strip().isdigit()]
            for doc in documents:
                if doc.id in doc_ids:
                    related_docs.append(RelatedResource(
                        type="document",
                        id=doc.id,
                        title=doc.title,
                        url=f"/knowledge_base.html#document-{doc.id}"
                    ))
        
        # Get related tip IDs
        if faq.related_tip_ids:
            tip_ids = [int(id.strip()) for id in faq.related_tip_ids.split(',') if id.strip().isdigit()]
            for tip in tips:
                if tip.id in tip_ids:
                    related_tips.append(RelatedResource(
                        type="tip",
                        id=tip.id,
                        title=tip.title,
                        url=f"/shared_tips.html?tip_id={tip.id}"
                    ))
        
        return related_docs, related_tips


# Create a singleton instance for use across the application
chatbot_service = ChatbotService()
