"""
LLM Service

Handles communication with local Ollama LLM for response synthesis.
Provides intelligent responses based on retrieved context from documents, tips, and FAQs.
Uses direct HTTP calls to Ollama for reliability.

Note: LLM calls are synchronous but can be run asynchronously via synthesize_response_async()
which wraps the blocking call in a thread pool to avoid blocking the FastAPI event loop.
"""

import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor
import requests
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ContextSource:
    """Represents a source of context for the LLM."""
    source_type: str  # "document", "tip", "faq"
    title: str
    content: str
    id: int
    category: Optional[str] = None
    similarity: float = 0.0


class LLMService:
    """Service for LLM-powered response generation using Ollama via HTTP."""
    
    def __init__(self):
        """Initialize the LLM service."""
        from ..config import settings
        
        self.enabled = False
        self.host = settings.llm_host
        self.model = settings.llm_model
        self.temperature = settings.llm_temperature
        self.max_tokens = settings.llm_max_tokens
        self.timeout = settings.llm_timeout
        self.max_context_chars = getattr(settings, 'llm_max_context_chars', 6000)
        
        if not settings.llm_enabled:
            logger.info("LLM is disabled in settings")
            return
        
        try:
            # Test connection by listing models via HTTP
            resp = requests.get(f"{self.host}/api/tags", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                models = data.get('models', [])
                available_models = [m.get('name', m.get('model', '')) for m in models]
                
                if not available_models:
                    logger.warning("No models installed in Ollama. Run: ollama pull mistral:7b")
                    return
                
                # Check if configured model is available
                model_found = any(self.model in m or m in self.model for m in available_models)
                if not model_found:
                    logger.warning(f"Model '{self.model}' not found. Available: {available_models}")
                    # Use first available model as fallback
                    self.model = available_models[0]
                    logger.info(f"Using fallback model: {self.model}")
                
                self.enabled = True
                logger.info(f"LLM service initialized with model: {self.model}")
            else:
                logger.error(f"Failed to connect to Ollama: HTTP {resp.status_code}")
                
        except requests.exceptions.ConnectionError:
            logger.warning(f"Cannot connect to Ollama at {self.host}. LLM features disabled.")
        except Exception as e:
            logger.error(f"Failed to initialize LLM service: {e}")
    
    def is_available(self) -> bool:
        """Check if LLM service is available."""
        if not self.enabled:
            return False
        
        try:
            resp = requests.get(f"{self.host}/api/tags", timeout=2)
            return resp.status_code == 200
        except Exception:
            return False
    
    def synthesize_response(
        self,
        query: str,
        context_sources: List[ContextSource],
        max_context_length: Optional[int] = None  # Uses config default if not specified
    ) -> Tuple[Optional[str], List[str]]:
        """
        Generate a response using the LLM based on query and context.
        
        Args:
            query: User's question
            context_sources: List of relevant documents, tips, FAQs
            max_context_length: Maximum context characters to include
            
        Returns:
            Tuple of (response_text, list_of_source_references)
        """
        if not self.enabled:
            return None, []
        
        # Use config default if not specified
        if max_context_length is None:
            max_context_length = self.max_context_chars
        
        try:
            # Build context from sources
            context, sources = self._build_context(context_sources, max_context_length)
            
            if not context:
                # No context available, use general knowledge
                prompt = self._build_general_prompt(query)
            else:
                prompt = self._build_rag_prompt(query, context)
            
            # Generate response via HTTP
            resp = requests.post(
                f"{self.host}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": self.temperature,
                        "num_predict": self.max_tokens,
                    }
                },
                timeout=self.timeout
            )
            
            if resp.status_code != 200:
                logger.error(f"LLM generation failed: HTTP {resp.status_code}")
                return None, sources
            
            response_text = resp.json().get('response', '').strip()
            
            if not response_text:
                return None, sources
            
            return response_text, sources
            
        except requests.exceptions.Timeout:
            logger.warning(f"LLM request timed out after {self.timeout}s")
            return None, []
        except Exception as e:
            logger.error(f"Error generating LLM response: {e}")
            return None, []
    
    async def synthesize_response_async(
        self,
        query: str,
        context_sources: List[ContextSource],
        max_context_length: Optional[int] = None
    ) -> Tuple[Optional[str], List[str]]:
        """
        Async wrapper for synthesize_response.
        
        Runs the blocking LLM call in a thread pool to avoid blocking
        the FastAPI event loop, allowing other requests to be processed
        while waiting for the LLM response.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,  # Uses default ThreadPoolExecutor
            lambda: self.synthesize_response(query, context_sources, max_context_length)
        )
    
    def _build_context(
        self,
        sources: List[ContextSource],
        max_length: int
    ) -> Tuple[str, List[str]]:
        """Build context string from sources, respecting max length."""
        context_parts = []
        source_refs = []
        current_length = 0
        
        # Sort by similarity (best matches first)
        sorted_sources = sorted(sources, key=lambda x: x.similarity, reverse=True)
        
        # Calculate per-source limit based on total budget (allow ~5-6 sources)
        per_source_limit = min(max_length // 4, 2000)
        
        for source in sorted_sources:
            # Format source content
            source_header = f"\n--- {source.source_type.upper()}: {source.title} ---\n"
            source_content = source.content[:per_source_limit]  # Dynamic limit based on budget
            
            part = source_header + source_content
            
            if current_length + len(part) > max_length:
                # Truncate if needed
                remaining = max_length - current_length
                if remaining > 200:  # Only add if meaningful content fits
                    part = part[:remaining] + "..."
                    context_parts.append(part)
                    source_refs.append(f"{source.source_type}: {source.title}")
                break
            
            context_parts.append(part)
            source_refs.append(f"{source.source_type}: {source.title}")
            current_length += len(part)
        
        return "\n".join(context_parts), source_refs
    
    def _build_rag_prompt(self, query: str, context: str) -> str:
        """Build a RAG (Retrieval-Augmented Generation) prompt."""
        return f"""You are a helpful assistant for Wave Glider operations. Answer the user's question based on the provided context. 

IMPORTANT INSTRUCTIONS:
- Use ONLY the information from the context below to answer
- If the context doesn't contain enough information, say so
- Be concise and direct
- If referencing specific procedures, quote them accurately
- Format your response with clear structure when appropriate

CONTEXT:
{context}

USER QUESTION: {query}

ANSWER:"""
    
    def _build_general_prompt(self, query: str) -> str:
        """Build a general prompt when no context is available."""
        return f"""You are a helpful assistant for Wave Glider operations. The user has asked a question, but no specific documentation was found.

Provide a helpful response, but make it clear that you're providing general guidance and recommend checking official documentation.

USER QUESTION: {query}

ANSWER:"""
    
    def classify_intent(self, query: str) -> Dict[str, bool]:
        """
        Classify the intent of a query using keywords.
        Returns dict with intent flags.
        """
        query_lower = query.lower()
        
        troubleshooting_keywords = [
            'error', 'fix', 'problem', 'issue', 'troubleshoot', 'broken',
            'not working', 'failed', 'failure', 'debug', 'resolve', 'repair',
            'wrong', 'stuck', 'crash', 'fault'
        ]
        
        procedure_keywords = [
            'how to', 'how do i', 'procedure', 'steps', 'guide', 'tutorial',
            'setup', 'install', 'configure', 'calibrate', 'initialize',
            'what are the steps', 'process for'
        ]
        
        status_keywords = [
            'status', 'check', 'current', 'state', 'is it', 'are they'
        ]
        
        is_troubleshooting = any(kw in query_lower for kw in troubleshooting_keywords)
        is_procedure = any(kw in query_lower for kw in procedure_keywords)
        is_status = any(kw in query_lower for kw in status_keywords)
        
        return {
            'troubleshooting': is_troubleshooting,
            'procedure': is_procedure,
            'information': not (is_troubleshooting or is_procedure or is_status),
            'status': is_status,
            'general': not (is_troubleshooting or is_procedure or is_status)
        }


# Create singleton instance
llm_service = LLMService()
