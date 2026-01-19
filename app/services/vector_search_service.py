"""
Vector Search Service

Handles semantic search using ChromaDB for FAQs, documents, and tips.
Supports category/tag filtering for targeted searches (e.g., troubleshooting).
"""

import logging
from typing import List, Dict, Optional, Tuple
from pathlib import Path
import json

logger = logging.getLogger(__name__)
from ..config import settings

try:
    import chromadb
    from sentence_transformers import SentenceTransformer
    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False
    logger.warning("ChromaDB or sentence-transformers not installed. Vector search disabled.")


class VectorSearchService:
    """Service for vector-based semantic search."""
    
    def __init__(self, storage_path: Optional[Path] = None):
        """Initialize vector search service."""
        if not CHROMADB_AVAILABLE:
            self.enabled = False
            logger.warning("Vector search disabled - dependencies not installed")
            return

        # Disable MKLDNN in-process to avoid CPU kernel crashes.
        try:
            import torch
            torch.backends.mkldnn.enabled = False
            torch.set_num_threads(1)
            torch.set_num_interop_threads(1)
        except Exception as e:
            logger.warning(f"Failed to set torch CPU knobs: {e}")
        
        self.enabled = True
        self.storage_path = storage_path or Path("data_store/chroma_db")
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
        # Initialize ChromaDB client
        self.client = chromadb.PersistentClient(path=str(self.storage_path))
        
        # Initialize embedding model
        try:
            self.embedding_model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
            logger.info("Embedding model loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load embedding model: {e}")
            self.enabled = False
            return
        
        # Create collections for different content types
        self.faq_collection = self.client.get_or_create_collection(
            name="faqs",
            metadata={"description": "FAQ entries with semantic search"}
        )
        
        self.documents_collection = self.client.get_or_create_collection(
            name="documents",
            metadata={"description": "Knowledge base documents"}
        )
        
        self.tips_collection = self.client.get_or_create_collection(
            name="tips",
            metadata={"description": "Shared tips and tricks"}
        )
        
        logger.info("Vector search service initialized")
    
    def add_faq(
        self,
        faq_id: int,
        question: str,
        answer: str,
        category: Optional[str] = None,
        tags: Optional[str] = None,
        keywords: Optional[str] = None
    ):
        """Add or update an FAQ in the vector store."""
        if not self.enabled:
            return
        
        try:
            # Combine question and answer for better semantic matching
            content = f"{question}\n\n{answer}"
            embedding = self.embedding_model.encode(content).tolist()
            
            # Prepare metadata
            metadata = {
                "faq_id": str(faq_id),
                "question": question,
                "category": category or "general",
                "tags": tags or "",
                "keywords": keywords or "",
                "type": "faq"
            }
            
            # Add to collection (will update if ID exists)
            self.faq_collection.upsert(
                ids=[f"faq_{faq_id}"],
                embeddings=[embedding],
                documents=[answer],  # Store answer as the document
                metadatas=[metadata]
            )
            
            logger.debug(f"Added FAQ {faq_id} to vector store")
        except Exception as e:
            logger.error(f"Error adding FAQ to vector store: {e}")
    
    def add_document(
        self,
        doc_id: int,
        title: str,
        content: str,
        category: Optional[str] = None,
        tags: Optional[str] = None,
        file_type: Optional[str] = None,
        use_chunking: bool = True
    ):
        """
        Add or update a document in the vector store.
        
        Always removes old chunks/entries before adding new ones to prevent
        orphaned data when documents are updated or replaced.
        
        Args:
            doc_id: Document ID
            title: Document title
            content: Full document content
            category: Document category
            tags: Document tags
            file_type: File type
            use_chunking: If True, split large documents into chunks
        """
        if not self.enabled:
            return
        
        try:
            # Always clean up old chunks/entries first to prevent orphaned data
            # This handles cases where a document changes from chunked to single entry
            # or vice versa, or when a file is replaced with a new version
            self._delete_document_chunks(doc_id)
            # Also delete single-entry version if it exists
            try:
                self.documents_collection.delete(ids=[f"doc_{doc_id}"])
            except Exception:
                pass  # May not exist if document was chunked
            
            # For large documents, use chunking for better precision
            should_chunk = use_chunking and settings.vector_chunking_enabled
            if should_chunk and len(content) > settings.vector_chunking_min_chars:
                self._add_document_chunked(doc_id, title, content, category, tags, file_type)
            else:
                # Small document - store as single entry
                embedding = self.embedding_model.encode(content).tolist()
                
                metadata = {
                    "doc_id": str(doc_id),
                    "title": title,
                    "category": category or "general",
                    "tags": tags or "",
                    "file_type": file_type or "",
                    "type": "document",
                    "chunk_index": "0",
                    "is_chunked": "false"
                }
                
                self.documents_collection.upsert(
                    ids=[f"doc_{doc_id}"],
                    embeddings=[embedding],
                    documents=[content],
                    metadatas=[metadata]
                )
                
                logger.debug(f"Added document {doc_id} to vector store (single entry)")
        except Exception as e:
            logger.error(f"Error adding document to vector store: {e}")
    
    def _add_document_chunked(
        self,
        doc_id: int,
        title: str,
        content: str,
        category: Optional[str] = None,
        tags: Optional[str] = None,
        file_type: Optional[str] = None
    ):
        """Add a document as multiple chunks for better search precision."""
        try:
            from .chunking_service import chunking_service
            
            # First, remove any existing chunks for this document
            self._delete_document_chunks(doc_id)
            
            # Use context-aware chunking for better hierarchy preservation
            # Falls back to basic chunking if structure isn't detected
            chunks = chunking_service.chunk_with_context(
                doc_id=doc_id,
                content=content,
                title=title,
                category=category or "general",
                tags=tags or ""
            )
            
            # Add each chunk to the vector store
            ids = []
            embeddings = []
            documents = []
            metadatas = []
            
            for chunk in chunks:
                # Create embedding for chunk
                chunk_embedding = self.embedding_model.encode(chunk.content).tolist()
                
                ids.append(chunk.chunk_id)
                embeddings.append(chunk_embedding)
                documents.append(chunk.content)
                metadatas.append({
                    "doc_id": str(doc_id),
                    "title": chunk.title,
                    "category": chunk.category or "general",
                    "tags": chunk.tags or "",
                    "file_type": file_type or "",
                    "type": "document",
                    "chunk_index": str(chunk.chunk_index),
                    "is_chunked": "true",
                    "start_char": str(chunk.start_char),
                    "end_char": str(chunk.end_char)
                })
            
            # Batch upsert all chunks
            if ids:
                self.documents_collection.upsert(
                    ids=ids,
                    embeddings=embeddings,
                    documents=documents,
                    metadatas=metadatas
                )
            
            logger.info(f"Added document {doc_id} ({title}) as {len(chunks)} chunks")
            
        except Exception as e:
            logger.error(f"Error chunking document {doc_id}: {e}")
            # Fallback to single entry
            embedding = self.embedding_model.encode(content[:5000]).tolist()  # Truncate for safety
            self.documents_collection.upsert(
                ids=[f"doc_{doc_id}"],
                embeddings=[embedding],
                documents=[content[:5000]],
                metadatas=[{
                    "doc_id": str(doc_id),
                    "title": title,
                    "category": category or "general",
                    "tags": tags or "",
                    "file_type": file_type or "",
                    "type": "document",
                    "chunk_index": "0",
                    "is_chunked": "false"
                }]
            )
    
    def _delete_document_chunks(self, doc_id: int):
        """Delete all chunks for a document."""
        try:
            # Get all chunk IDs for this document
            results = self.documents_collection.get(
                where={"doc_id": str(doc_id)},
                include=[]
            )
            
            if results['ids']:
                self.documents_collection.delete(ids=results['ids'])
                logger.debug(f"Deleted {len(results['ids'])} chunks for document {doc_id}")
        except Exception as e:
            logger.warning(f"Error deleting document chunks: {e}")
    
    def add_tip(
        self,
        tip_id: int,
        title: str,
        content: str,
        category: Optional[str] = None,
        tags: Optional[str] = None
    ):
        """Add or update a shared tip in the vector store."""
        if not self.enabled:
            return
        
        try:
            # Combine title and content
            full_content = f"{title}\n\n{content}"
            embedding = self.embedding_model.encode(full_content).tolist()
            
            metadata = {
                "tip_id": str(tip_id),
                "title": title,
                "category": category or "general",
                "tags": tags or "",
                "type": "tip"
            }
            
            self.tips_collection.upsert(
                ids=[f"tip_{tip_id}"],
                embeddings=[embedding],
                documents=[content],
                metadatas=[metadata]
            )
            
            logger.debug(f"Added tip {tip_id} to vector store")
        except Exception as e:
            logger.error(f"Error adding tip to vector store: {e}")
    
    def search_faqs(
        self,
        query: str,
        category_filter: Optional[str] = None,
        tag_filter: Optional[str] = None,
        limit: int = 5,
        similarity_threshold: float = 0.35
    ) -> List[Tuple[Dict, float]]:
        """
        Search FAQs using vector similarity.
        
        Args:
            query: Search query
            category_filter: Filter by category (e.g., "troubleshooting")
            tag_filter: Filter by tag
            limit: Maximum results
            similarity_threshold: Minimum similarity score (lower = more strict)
            
        Returns:
            List of (metadata_dict, similarity_score) tuples
        """
        if not self.enabled:
            return []
        
        try:
            query_embedding = self.embedding_model.encode(query).tolist()
            
            # Build where clause for filtering
            where_clause = {}
            if category_filter:
                where_clause["category"] = category_filter
            if tag_filter:
                where_clause["tags"] = {"$contains": tag_filter}
            
            # Search with filters
            results = self.faq_collection.query(
                query_embeddings=[query_embedding],
                n_results=limit * 2,  # Get more to filter
                where=where_clause if where_clause else None,
                include=['metadatas', 'distances']
            )
            
            # Filter by similarity threshold and return
            # Note: ChromaDB uses L2 (Euclidean) distance by default
            # Convert to similarity using: 1 / (1 + distance) which gives values in [0, 1]
            matches = []
            if results['metadatas'] and results['distances']:
                for metadata, distance in zip(results['metadatas'][0], results['distances'][0]):
                    similarity = 1 / (1 + distance)  # Convert L2 distance to similarity
                    if similarity >= similarity_threshold:
                        matches.append((metadata, similarity))
            
            # Sort by similarity and limit
            matches.sort(key=lambda x: x[1], reverse=True)
            return matches[:limit]
            
        except Exception as e:
            logger.error(f"Error searching FAQs: {e}", exc_info=True)
            return []
    
    def search_documents(
        self,
        query: str,
        category_filter: Optional[str] = None,
        tag_filter: Optional[str] = None,
        limit: int = 5,
        similarity_threshold: float = 0.35
    ) -> List[Tuple[Dict, float, str]]:
        """
        Search documents using vector similarity.
        Perfect for finding troubleshooting documents!
        
        Args:
            query: Search query (e.g., "how to fix sensor error")
            category_filter: Filter by category (e.g., "troubleshooting")
            tag_filter: Filter by tag
            limit: Maximum results
            similarity_threshold: Minimum similarity score
            
        Returns:
            List of (metadata_dict, similarity_score, content) tuples
        """
        if not self.enabled:
            return []
        
        try:
            query_embedding = self.embedding_model.encode(query).tolist()
            
            # Build where clause
            where_clause = {}
            if category_filter:
                where_clause["category"] = category_filter
            if tag_filter:
                where_clause["tags"] = {"$contains": tag_filter}
            
            results = self.documents_collection.query(
                query_embeddings=[query_embedding],
                n_results=limit * 2,
                where=where_clause if where_clause else None,
                include=['metadatas', 'distances', 'documents']
            )
            
            matches = []
            if results['metadatas'] and results['distances'] and results['documents']:
                for metadata, distance, content in zip(
                    results['metadatas'][0],
                    results['distances'][0],
                    results['documents'][0]
                ):
                    similarity = 1 / (1 + distance)  # Convert L2 distance to similarity
                    if similarity >= similarity_threshold:
                        matches.append((metadata, similarity, content))
            
            matches.sort(key=lambda x: x[1], reverse=True)
            return matches[:limit]
            
        except Exception as e:
            logger.error(f"Error searching documents: {e}", exc_info=True)
            return []
    
    def search_tips(
        self,
        query: str,
        category_filter: Optional[str] = None,
        tag_filter: Optional[str] = None,
        limit: int = 5,
        similarity_threshold: float = 0.35
    ) -> List[Tuple[Dict, float, str]]:
        """
        Search shared tips using vector similarity.
        
        Args:
            query: Search query
            category_filter: Filter by category
            tag_filter: Filter by tag
            limit: Maximum results
            similarity_threshold: Minimum similarity score
            
        Returns:
            List of (metadata_dict, similarity_score, content) tuples
        """
        if not self.enabled:
            return []
        
        try:
            query_embedding = self.embedding_model.encode(query).tolist()
            
            where_clause = {}
            if category_filter:
                where_clause["category"] = category_filter
            if tag_filter:
                where_clause["tags"] = {"$contains": tag_filter}
            
            results = self.tips_collection.query(
                query_embeddings=[query_embedding],
                n_results=limit * 2,
                where=where_clause if where_clause else None,
                include=['metadatas', 'distances', 'documents']
            )
            
            matches = []
            if results['metadatas'] and results['distances'] and results['documents']:
                for metadata, distance, content in zip(
                    results['metadatas'][0],
                    results['distances'][0],
                    results['documents'][0]
                ):
                    similarity = 1 / (1 + distance)  # Convert L2 distance to similarity
                    if similarity >= similarity_threshold:
                        matches.append((metadata, similarity, content))
            
            matches.sort(key=lambda x: x[1], reverse=True)
            return matches[:limit]
            
        except Exception as e:
            logger.error(f"Error searching tips: {e}", exc_info=True)
            return []
    
    def delete_faq(self, faq_id: int):
        """Remove an FAQ from the vector store."""
        if not self.enabled:
            return
        try:
            self.faq_collection.delete(ids=[f"faq_{faq_id}"])
        except Exception as e:
            logger.error(f"Error deleting FAQ from vector store: {e}")
    
    def delete_document(self, doc_id: int):
        """Remove a document (and all its chunks) from the vector store."""
        if not self.enabled:
            return
        try:
            # Delete all chunks for this document
            self._delete_document_chunks(doc_id)
            # Also try to delete the single-entry version if it exists
            try:
                self.documents_collection.delete(ids=[f"doc_{doc_id}"])
            except Exception:
                pass  # May not exist if document was chunked
        except Exception as e:
            logger.error(f"Error deleting document from vector store: {e}")
    
    def delete_tip(self, tip_id: int):
        """Remove a tip from the vector store."""
        if not self.enabled:
            return
        try:
            self.tips_collection.delete(ids=[f"tip_{tip_id}"])
        except Exception as e:
            logger.error(f"Error deleting tip from vector store: {e}")
