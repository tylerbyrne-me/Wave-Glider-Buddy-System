"""
Document Chunking Service

Splits large documents into smaller, semantically meaningful chunks
for better vector search precision.

Optimized for structured documents following the RAG document template:
- Preserves section headers with their content
- Keeps tables intact when possible
- Maintains numbered procedure steps together
- Adds context from parent sections to isolated chunks
"""

import re
import logging
from typing import List, Tuple, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class DocumentChunk:
    """Represents a chunk of a document."""
    doc_id: int
    chunk_index: int
    content: str
    title: str
    category: str
    tags: str
    start_char: int
    end_char: int
    
    @property
    def chunk_id(self) -> str:
        """Unique ID for this chunk."""
        return f"doc_{self.doc_id}_chunk_{self.chunk_index}"


class ChunkingService:
    """Service for splitting documents into chunks with structure preservation."""
    
    def __init__(
        self,
        chunk_size: int = 1200,  # Target chunk size in characters (increased for Mistral)
        chunk_overlap: int = 150,  # Overlap between chunks
        min_chunk_size: int = 200,  # Minimum chunk size (increased to ensure meaningful content)
        include_headers: bool = True  # Include parent section headers in each chunk
    ):
        """
        Initialize chunking service.
        
        Args:
            chunk_size: Target size for each chunk in characters
            chunk_overlap: Number of characters to overlap between chunks
            min_chunk_size: Minimum size for a chunk (smaller chunks are merged)
            include_headers: Whether to prepend section context to each chunk
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.min_chunk_size = min_chunk_size
        self.include_headers = include_headers
    
    def chunk_document(
        self,
        doc_id: int,
        content: str,
        title: str,
        category: str = "",
        tags: str = ""
    ) -> List[DocumentChunk]:
        """
        Split a document into chunks.
        
        Args:
            doc_id: Document ID
            content: Full document content
            title: Document title
            category: Document category
            tags: Document tags
            
        Returns:
            List of DocumentChunk objects
        """
        if not content or len(content) < self.min_chunk_size:
            # Document too small to chunk
            return [DocumentChunk(
                doc_id=doc_id,
                chunk_index=0,
                content=content or "",
                title=title,
                category=category,
                tags=tags,
                start_char=0,
                end_char=len(content) if content else 0
            )]
        
        # Split into semantic chunks (by paragraphs, sections, etc.)
        chunks = self._semantic_chunk(content)
        
        # Create DocumentChunk objects
        result = []
        current_pos = 0
        
        for i, chunk_content in enumerate(chunks):
            if not chunk_content.strip():
                continue
            
            result.append(DocumentChunk(
                doc_id=doc_id,
                chunk_index=i,
                content=chunk_content.strip(),
                title=f"{title} (Part {i + 1})" if len(chunks) > 1 else title,
                category=category,
                tags=tags,
                start_char=current_pos,
                end_char=current_pos + len(chunk_content)
            ))
            
            current_pos += len(chunk_content)
        
        logger.debug(f"Document {doc_id} ({title}) split into {len(result)} chunks")
        return result
    
    def _semantic_chunk(self, content: str) -> List[str]:
        """
        Split content into semantically meaningful chunks.
        
        Strategy:
        1. Split by major section breaks (headers, HR lines)
        2. If sections too large, split by paragraphs
        3. If paragraphs too large, split by sentences
        4. Merge small chunks with neighbors
        """
        # First, try to split by section markers
        sections = self._split_by_sections(content)
        
        # Process each section
        chunks = []
        for section in sections:
            if len(section) <= self.chunk_size:
                chunks.append(section)
            else:
                # Split large sections by paragraphs
                para_chunks = self._split_by_paragraphs(section)
                chunks.extend(para_chunks)
        
        # Merge small chunks
        chunks = self._merge_small_chunks(chunks)
        
        # Add overlap
        chunks = self._add_overlap(chunks, content)
        
        return chunks
    
    def _split_by_sections(self, content: str) -> List[str]:
        """Split by section headers or horizontal rules."""
        # Common section patterns
        section_patterns = [
            r'\n#{1,6}\s+',  # Markdown headers
            r'\n-{3,}\n',     # Horizontal rules
            r'\n={3,}\n',     # Horizontal rules
            r'\n\*{3,}\n',    # Horizontal rules
            r'\n(?=[A-Z][A-Z\s]{10,}:?\n)',  # ALL CAPS HEADERS
        ]
        
        combined_pattern = '|'.join(section_patterns)
        
        # Split and keep the delimiter with the following section
        parts = re.split(f'({combined_pattern})', content)
        
        # Combine delimiters with following content
        sections = []
        current = ""
        
        for part in parts:
            if re.match(combined_pattern, part):
                if current:
                    sections.append(current)
                current = part
            else:
                current += part
        
        if current:
            sections.append(current)
        
        return sections if sections else [content]
    
    def _split_by_paragraphs(self, content: str) -> List[str]:
        """Split content by paragraphs."""
        # Split by double newlines (paragraph breaks)
        paragraphs = re.split(r'\n\s*\n', content)
        
        result = []
        current_chunk = ""
        
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            
            if len(current_chunk) + len(para) <= self.chunk_size:
                current_chunk += "\n\n" + para if current_chunk else para
            else:
                if current_chunk:
                    result.append(current_chunk)
                
                # If single paragraph is too large, split by sentences
                if len(para) > self.chunk_size:
                    sentence_chunks = self._split_by_sentences(para)
                    result.extend(sentence_chunks)
                    current_chunk = ""
                else:
                    current_chunk = para
        
        if current_chunk:
            result.append(current_chunk)
        
        return result
    
    def _split_by_sentences(self, content: str) -> List[str]:
        """Split content by sentences for very long paragraphs."""
        # Simple sentence splitting (handles common cases)
        sentences = re.split(r'(?<=[.!?])\s+', content)
        
        result = []
        current_chunk = ""
        
        for sentence in sentences:
            if len(current_chunk) + len(sentence) <= self.chunk_size:
                current_chunk += " " + sentence if current_chunk else sentence
            else:
                if current_chunk:
                    result.append(current_chunk)
                current_chunk = sentence
        
        if current_chunk:
            result.append(current_chunk)
        
        return result
    
    def _merge_small_chunks(self, chunks: List[str]) -> List[str]:
        """Merge chunks that are too small."""
        if len(chunks) <= 1:
            return chunks
        
        result = []
        current = ""
        
        for chunk in chunks:
            if len(current) + len(chunk) <= self.chunk_size:
                current += "\n\n" + chunk if current else chunk
            else:
                if current and len(current) >= self.min_chunk_size:
                    result.append(current)
                elif current:
                    # Current is too small, try to merge with next
                    current += "\n\n" + chunk
                    continue
                current = chunk
        
        if current:
            result.append(current)
        
        return result
    
    def _add_overlap(self, chunks: List[str], original: str) -> List[str]:
        """Add overlap between chunks for better context."""
        if len(chunks) <= 1 or self.chunk_overlap <= 0:
            return chunks
        
        result = []
        for i, chunk in enumerate(chunks):
            if i > 0:
                # Add end of previous chunk as prefix
                prev_chunk = chunks[i - 1]
                overlap_text = prev_chunk[-self.chunk_overlap:] if len(prev_chunk) > self.chunk_overlap else prev_chunk
                # Find a good break point (word boundary)
                space_idx = overlap_text.find(' ')
                if space_idx > 0:
                    overlap_text = overlap_text[space_idx + 1:]
                chunk = f"...{overlap_text}\n\n{chunk}"
            
            result.append(chunk)
        
        return result
    
    def _extract_section_hierarchy(self, content: str, position: int) -> str:
        """
        Extract the section hierarchy (headers) leading up to a position in the document.
        This provides context for isolated chunks.
        
        Returns a string like:
        "# Document Title > ## Section Name > ### Subsection Name"
        """
        # Find all headers before this position
        header_pattern = r'^(#{1,6})\s+(.+?)$'
        headers_before = []
        
        content_before = content[:position]
        for match in re.finditer(header_pattern, content_before, re.MULTILINE):
            level = len(match.group(1))
            title = match.group(2).strip()
            headers_before.append((level, title, match.start()))
        
        if not headers_before:
            return ""
        
        # Build hierarchy - keep only the most recent header at each level
        hierarchy = {}
        for level, title, pos in headers_before:
            hierarchy[level] = title
            # Clear any sub-levels when we see a new header
            for sub_level in list(hierarchy.keys()):
                if sub_level > level:
                    del hierarchy[sub_level]
        
        # Format as breadcrumb
        if hierarchy:
            sorted_levels = sorted(hierarchy.keys())
            breadcrumb = " > ".join([hierarchy[lvl] for lvl in sorted_levels])
            return f"[Context: {breadcrumb}]\n\n"
        
        return ""
    
    def _is_table_content(self, text: str) -> bool:
        """Check if text contains a markdown table that shouldn't be split."""
        lines = text.strip().split('\n')
        table_lines = sum(1 for line in lines if '|' in line and line.strip().startswith('|'))
        return table_lines >= 2
    
    def _is_numbered_list(self, text: str) -> bool:
        """Check if text is a numbered procedure list that should stay together."""
        numbered_pattern = r'^\d+\.\s+'
        lines = text.strip().split('\n')
        numbered_lines = sum(1 for line in lines if re.match(numbered_pattern, line.strip()))
        return numbered_lines >= 3
    
    def chunk_with_context(
        self,
        doc_id: int,
        content: str,
        title: str,
        category: str = "",
        tags: str = ""
    ) -> List[DocumentChunk]:
        """
        Enhanced chunking that preserves document structure and adds context.
        
        This method:
        1. Identifies section boundaries
        2. Keeps tables and numbered lists intact when possible
        3. Adds section hierarchy context to each chunk
        
        Args:
            doc_id: Document ID
            content: Full document content
            title: Document title
            category: Document category
            tags: Document tags
            
        Returns:
            List of DocumentChunk objects with contextual information
        """
        if not content or len(content) < self.min_chunk_size:
            return [DocumentChunk(
                doc_id=doc_id,
                chunk_index=0,
                content=content or "",
                title=title,
                category=category,
                tags=tags,
                start_char=0,
                end_char=len(content) if content else 0
            )]
        
        # Extract document metadata header if present (first few lines with **Key:** format)
        metadata_match = re.match(r'^((?:\*\*\w+:\*\*.*\n)+)', content)
        doc_metadata = ""
        if metadata_match:
            doc_metadata = metadata_match.group(1).strip() + "\n\n"
        
        # Split by section headers while keeping headers with content
        section_pattern = r'(^#{1,6}\s+.+$)'
        parts = re.split(section_pattern, content, flags=re.MULTILINE)
        
        # Reconstruct sections with their headers
        sections = []
        current_section = ""
        current_start = 0
        
        for part in parts:
            if re.match(r'^#{1,6}\s+', part):
                # This is a header - save current section and start new one
                if current_section.strip():
                    sections.append((current_section, current_start))
                current_section = part + "\n"
                current_start = content.find(part, current_start)
            else:
                current_section += part
        
        if current_section.strip():
            sections.append((current_section, current_start))
        
        # Process sections into chunks
        chunks = []
        chunk_index = 0
        
        for section_content, section_start in sections:
            section_content = section_content.strip()
            if not section_content:
                continue
            
            # Check if section contains a table or numbered list that should stay together
            is_structured = self._is_table_content(section_content) or self._is_numbered_list(section_content)
            
            # If section is small enough or is structured content, keep it as one chunk
            if len(section_content) <= self.chunk_size * 1.2 or (is_structured and len(section_content) <= self.chunk_size * 2):
                # Add context header if enabled
                if self.include_headers:
                    context = self._extract_section_hierarchy(content, section_start)
                    if context and not section_content.startswith('#'):
                        section_content = context + section_content
                
                chunks.append(DocumentChunk(
                    doc_id=doc_id,
                    chunk_index=chunk_index,
                    content=section_content,
                    title=f"{title} (Part {chunk_index + 1})" if len(sections) > 1 else title,
                    category=category,
                    tags=tags,
                    start_char=section_start,
                    end_char=section_start + len(section_content)
                ))
                chunk_index += 1
            else:
                # Section is too large - split by paragraphs
                para_chunks = self._split_by_paragraphs(section_content)
                
                for para_chunk in para_chunks:
                    if not para_chunk.strip():
                        continue
                    
                    # Add context header
                    if self.include_headers:
                        context = self._extract_section_hierarchy(content, section_start)
                        if context and not para_chunk.startswith('#'):
                            para_chunk = context + para_chunk
                    
                    chunks.append(DocumentChunk(
                        doc_id=doc_id,
                        chunk_index=chunk_index,
                        content=para_chunk.strip(),
                        title=f"{title} (Part {chunk_index + 1})",
                        category=category,
                        tags=tags,
                        start_char=section_start,
                        end_char=section_start + len(para_chunk)
                    ))
                    chunk_index += 1
        
        # If no chunks were created, fall back to basic chunking
        if not chunks:
            return self.chunk_document(doc_id, content, title, category, tags)
        
        logger.info(f"Document {doc_id} ({title}) split into {len(chunks)} context-aware chunks")
        return chunks


# Singleton instance with optimized settings for Mistral 7B
chunking_service = ChunkingService(
    chunk_size=1200,      # Larger chunks for more context
    chunk_overlap=150,    # Reasonable overlap
    min_chunk_size=200,   # Ensure meaningful chunks
    include_headers=True  # Add section context to chunks
)
