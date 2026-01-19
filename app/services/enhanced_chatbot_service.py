"""
Enhanced Chatbot Service with Vector Search and LLM

This demonstrates how the chatbot would work with troubleshooting documents and tips.
This is a reference implementation - the actual integration will enhance the existing chatbot_service.py
"""

import logging
from typing import List, Dict, Optional, Tuple
from ..core.models.database import FAQEntry, KnowledgeDocument, SharedTip
from .vector_search_service import VectorSearchService

logger = logging.getLogger(__name__)


class EnhancedChatbotService:
    """
    Enhanced chatbot service that uses vector search to find:
    - Troubleshooting documents (filtered by category/tags)
    - Troubleshooting tips (filtered by category/tags)
    - FAQs
    - General documents and tips
    
    Then uses LLM to synthesize answers from multiple sources.
    """
    
    def __init__(self, vector_service: Optional[VectorSearchService] = None):
        """Initialize enhanced chatbot service."""
        self.vector_service = vector_service
        # LLM service would be initialized here when Phase 2 is implemented
    
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
            'not working', 'failed', 'failure', 'debug', 'resolve'
        ]
        
        # Procedure indicators
        procedure_keywords = [
            'how to', 'how do i', 'procedure', 'steps', 'guide', 'tutorial',
            'setup', 'install', 'configure', 'calibrate'
        ]
        
        is_troubleshooting = any(kw in query_lower for kw in troubleshooting_keywords)
        is_procedure = any(kw in query_lower for kw in procedure_keywords)
        
        return {
            'troubleshooting': is_troubleshooting,
            'procedure': is_procedure,
            'general': not (is_troubleshooting or is_procedure)
        }
    
    def search_troubleshooting_sources(
        self,
        query: str,
        limit_per_source: int = 3
    ) -> Dict[str, List]:
        """
        Search troubleshooting-specific sources.
        
        This is the key method that answers your question:
        - Searches documents with category="troubleshooting" or tag="troubleshooting"
        - Searches tips with troubleshooting category/tags
        - Returns results from both sources
        """
        results = {
            'documents': [],
            'tips': [],
            'faqs': []
        }
        
        if not self.vector_service or not self.vector_service.enabled:
            return results
        
        # Search troubleshooting documents
        # This filters to ONLY documents tagged as troubleshooting
        doc_matches = self.vector_service.search_documents(
            query=query,
            category_filter="troubleshooting",  # KEY: Only troubleshooting docs
            # OR use tag_filter="troubleshooting" if using tags instead
            limit=limit_per_source,
            similarity_threshold=0.35
        )
        
        for metadata, similarity, content in doc_matches:
            results['documents'].append({
                'doc_id': int(metadata['doc_id']),
                'title': metadata['title'],
                'content': content,
                'similarity': similarity,
                'category': metadata.get('category'),
                'tags': metadata.get('tags', '').split(',') if metadata.get('tags') else []
            })
        
        # Search troubleshooting tips
        # This filters to ONLY tips with troubleshooting category
        tip_matches = self.vector_service.search_tips(
            query=query,
            category_filter="troubleshooting",  # KEY: Only troubleshooting tips
            # OR use tag_filter="troubleshooting"
            limit=limit_per_source,
            similarity_threshold=0.35
        )
        
        for metadata, similarity, content in tip_matches:
            results['tips'].append({
                'tip_id': int(metadata['tip_id']),
                'title': metadata['title'],
                'content': content,
                'similarity': similarity,
                'category': metadata.get('category'),
                'tags': metadata.get('tags', '').split(',') if metadata.get('tags') else []
            })
        
        # Also search FAQs (no category filter - search all)
        faq_matches = self.vector_service.search_faqs(
            query=query,
            limit=limit_per_source,
            similarity_threshold=0.35
        )
        
        for metadata, similarity in faq_matches:
            results['faqs'].append({
                'faq_id': int(metadata['faq_id']),
                'question': metadata['question'],
                'similarity': similarity,
                'category': metadata.get('category')
            })
        
        return results
    
    def search_all_sources(
        self,
        query: str,
        limit_per_source: int = 3
    ) -> Dict[str, List]:
        """
        Search all sources without category filtering.
        Used for general queries.
        """
        results = {
            'documents': [],
            'tips': [],
            'faqs': []
        }
        
        if not self.vector_service or not self.vector_service.enabled:
            return results
        
        # Search all documents (no category filter)
        doc_matches = self.vector_service.search_documents(
            query=query,
            limit=limit_per_source,
            similarity_threshold=0.35
        )
        
        for metadata, similarity, content in doc_matches:
            results['documents'].append({
                'doc_id': int(metadata['doc_id']),
                'title': metadata['title'],
                'content': content,
                'similarity': similarity
            })
        
        # Search all tips (no category filter)
        tip_matches = self.vector_service.search_tips(
            query=query,
            limit=limit_per_source,
            similarity_threshold=0.35
        )
        
        for metadata, similarity, content in tip_matches:
            results['tips'].append({
                'tip_id': int(metadata['tip_id']),
                'title': metadata['title'],
                'content': content,
                'similarity': similarity
            })
        
        # Search FAQs
        faq_matches = self.vector_service.search_faqs(
            query=query,
            limit=limit_per_source,
            similarity_threshold=0.35
        )
        
        for metadata, similarity in faq_matches:
            results['faqs'].append({
                'faq_id': int(metadata['faq_id']),
                'question': metadata['question'],
                'similarity': similarity
            })
        
        return results
    
    def process_query(
        self,
        query: str,
        use_llm: bool = False
    ) -> Dict:
        """
        Process a user query with intelligent source selection.
        
        This demonstrates how troubleshooting queries would work:
        1. Detect if it's a troubleshooting query
        2. Search ONLY troubleshooting sources (docs + tips)
        3. Synthesize answer from multiple sources
        4. Return with source links
        """
        # Detect intent
        intent = self.detect_query_intent(query)
        
        # Search based on intent
        if intent['troubleshooting']:
            # KEY FEATURE: Search only troubleshooting sources
            search_results = self.search_troubleshooting_sources(query)
            source_type = "troubleshooting"
        elif intent['procedure']:
            # Search procedure documents
            search_results = self.search_all_sources(query)  # Could add procedure filter
            source_type = "procedure"
        else:
            # General search across all sources
            search_results = self.search_all_sources(query)
            source_type = "general"
        
        # Build response
        response = {
            'query': query,
            'intent': intent,
            'source_type': source_type,
            'sources': search_results,
            'has_results': any(
                search_results['documents'] or 
                search_results['tips'] or 
                search_results['faqs']
            )
        }
        
        # If LLM is enabled, synthesize answer
        if use_llm and response['has_results']:
            # This would call LLMService to synthesize from sources
            # For now, just return the structured results
            response['synthesized_answer'] = None  # Would be LLM-generated
        
        return response


# Example usage:
"""
# User asks: "My sensor is showing error code 1234, how do I fix it?"

service = EnhancedChatbotService(vector_service)

# This automatically:
# 1. Detects it's a troubleshooting query
# 2. Searches ONLY documents with category="troubleshooting"
# 3. Searches ONLY tips with category="troubleshooting"
# 4. Returns relevant troubleshooting content

result = service.process_query(
    "My sensor is showing error code 1234, how do I fix it?",
    use_llm=True
)

# Result contains:
# - Documents from troubleshooting manuals
# - Tips from pilots who solved similar issues
# - FAQs related to sensor errors
# - LLM-synthesized answer combining all sources
"""
