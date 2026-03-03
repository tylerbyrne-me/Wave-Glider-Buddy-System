"""
Slocum Masterdata Service.

Parses masterdata markdown, provides structured lookup for the parser/editor,
and vectorizes content into ChromaDB for LLM context and semantic search.
"""

import re
import logging
from pathlib import Path
from typing import Any, Optional

from ..config import settings

logger = logging.getLogger(__name__)

# Chunk size for vectorization (~800 for parameter-focused chunks per plan)
MASTERDATA_CHUNK_SIZE = 800
MASTERDATA_CHUNK_OVERLAP = 100

# In-memory state (set when masterdata is loaded via KB upload)
_current_masterdata_doc_id: Optional[int] = None
_current_chunk_count: int = 0
_current_parameter_count: int = 0
_last_vectorized_utc: Optional[str] = None


def _chunk_markdown(content: str) -> list[tuple[str, str]]:
    """Split markdown into chunks by sections (headers), preserving context."""
    chunks: list[tuple[str, str]] = []
    lines = content.split("\n")
    current_section: list[str] = []
    current_heading = ""
    chunk_idx = 0

    for line in lines:
        if re.match(r"^#{1,6}\s", line):
            if current_section:
                text = "\n".join(current_section)
                if len(text) >= 50:
                    chunks.append((f"slocum_md_{chunk_idx}", text))
                    chunk_idx += 1
            current_heading = line.strip()
            current_section = [line]
        else:
            current_section.append(line)
            # Flush if over size
            text = "\n".join(current_section)
            if len(text) >= MASTERDATA_CHUNK_SIZE:
                chunks.append((f"slocum_md_{chunk_idx}", text))
                chunk_idx += 1
                current_section = []
    if current_section:
        text = "\n".join(current_section)
        if text.strip():
            chunks.append((f"slocum_md_{chunk_idx}", text))
    return chunks


def _parse_structured_lookup(content: str) -> dict[str, Any]:
    """
    Parse masterdata markdown into a simple structured lookup.
    Returns dict suitable for validate_parameters / get_required_parameters.
    """
    lookup: dict[str, Any] = {}
    lines = content.split("\n")
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith(";"):
            continue
        # Try param = value or param: value or * param - description
        m = re.match(r"^[\*\-\s]*([a-zA-Z_][a-zA-Z0-9_:\.\(\)\-]*)\s*[=:]\s*(.+)", stripped)
        if m:
            key = m.group(1).strip()
            val = m.group(2).strip()
            if key not in lookup:
                lookup[key] = {"description": val}
            continue
        m = re.match(r"^([a-zA-Z_][a-zA-Z0-9_:\.\(\)\-]+)\s+", stripped)
        if m:
            key = m.group(1).strip()
            if key not in lookup:
                lookup[key] = {"description": stripped[len(key):].strip() or ""}
    return lookup


def load_and_vectorize_masterdata(
    content: str,
    document_id: Optional[int] = None,
    vector_search_service: Optional[Any] = None,
) -> dict[str, Any]:
    """
    Parse masterdata content, vectorize into ChromaDB, and update global state.
    Called from KB upload handler when category is Masterdata.
    """
    global _current_masterdata_doc_id, _current_chunk_count, _current_parameter_count, _last_vectorized_utc
    from datetime import datetime, timezone
    chunks = _chunk_markdown(content)
    structured = _parse_structured_lookup(content)
    _current_parameter_count = len(structured)
    _current_chunk_count = len(chunks)
    _current_masterdata_doc_id = document_id
    _last_vectorized_utc = datetime.now(timezone.utc).isoformat()

    if vector_search_service and getattr(vector_search_service, "add_slocum_masterdata_chunks", None):
        vector_search_service.add_slocum_masterdata_chunks(chunks, replace_existing=True)
    else:
        try:
            from .vector_search_service import vector_search_service as vss
            if vss and getattr(vss, "add_slocum_masterdata_chunks", None):
                vss.add_slocum_masterdata_chunks(chunks, replace_existing=True)
        except Exception as e:
            logger.warning(f"Could not vectorize Slocum masterdata: {e}")

    return {
        "chunk_count": len(chunks),
        "parameter_count": _current_parameter_count,
        "last_vectorized_utc": _last_vectorized_utc,
    }


def get_structured_masterdata(content: Optional[str] = None) -> dict[str, Any]:
    """
    Return structured parameter lookup. If content is provided, parse it;
    otherwise return empty (caller should pass content from KB document when needed).
    """
    if content:
        return _parse_structured_lookup(content)
    return {}


def get_masterdata_status() -> dict[str, Any]:
    """Return current masterdata status for the status endpoint."""
    global _current_masterdata_doc_id, _current_chunk_count, _current_parameter_count, _last_vectorized_utc
    return {
        "has_masterdata": _current_chunk_count > 0,
        "document_id": _current_masterdata_doc_id,
        "chunk_count": _current_chunk_count,
        "parameter_count": _current_parameter_count,
        "last_vectorized_utc": _last_vectorized_utc,
    }


def search_masterdata(query: str, limit: int = 8) -> list[tuple[dict, float, str]]:
    """Search masterdata via vector search. Returns (metadata, similarity, content)."""
    try:
        from .vector_search_service import vector_search_service as vss
        if vss and getattr(vss, "search_slocum_masterdata", None):
            return vss.search_slocum_masterdata(query, limit=limit)
    except Exception as e:
        logger.warning(f"Slocum masterdata search failed: {e}")
    return []
