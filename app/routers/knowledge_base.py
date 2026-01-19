"""
Knowledge Base Router

Handles HTTP endpoints for knowledge base functionality.
"""

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Query
from fastapi.responses import FileResponse, HTMLResponse
from typing import List, Optional
from pathlib import Path
from datetime import datetime, timezone

from sqlmodel import select, or_, and_, func
from ..core import models
from ..core.db import get_db_session, SQLModelSession
from ..core.auth import get_current_active_user, get_current_admin_user, get_optional_current_user
from ..services.knowledge_base_service import KnowledgeBaseService
from ..core.templates import templates
from ..core.template_context import get_template_context
from ..config import settings
from fastapi import Request
import logging
import shutil

router = APIRouter(tags=["Knowledge Base"])
logger = logging.getLogger(__name__)

# Initialize service
kb_service = KnowledgeBaseService()

# File storage directory
KB_DOCUMENTS_DIR = Path(__file__).resolve().parent.parent.parent / "web" / "static" / "knowledge_base" / "documents"
KB_DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)


def _normalize_file_url(file_path: str) -> str:
    """
    Normalize file path to URL for static file serving.
    Removes 'web/' prefix since static files are mounted at /static.
    """
    normalized_path = file_path.replace(chr(92), '/')  # Replace backslashes with forward slashes
    if normalized_path.startswith('web/static/'):
        normalized_path = normalized_path.replace('web/static/', 'static/', 1)
    elif normalized_path.startswith('web\\static\\'):
        normalized_path = normalized_path.replace('web\\static\\', 'static/', 1)
    return f"/{normalized_path}"


# --- HTML Page Endpoint ---
@router.get("/knowledge_base.html", response_class=HTMLResponse)
async def knowledge_base_page(
    request: Request,
    current_user: Optional[models.User] = Depends(get_optional_current_user)
):
    """Knowledge base main page."""
    return templates.TemplateResponse(
        "knowledge_base.html",
        get_template_context(request=request, current_user=current_user)
    )


@router.post("/api/knowledge/documents/upload", response_model=models.KnowledgeDocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    title: str = Query(..., description="Document title"),
    description: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    tags: Optional[str] = Query(None),
    access_level: str = Query("pilot", description="Access level: public, pilot, admin"),
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """
    Upload a knowledge base document.
    Requires active user authentication.
    """
    logger.info(f"User '{current_user.username}' uploading document: {file.filename}")
    
    # Validate file type
    allowed_types = {
        "application/pdf": "pdf",
        "application/msword": "doc",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    }
    
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed: PDF, DOC, DOCX, PPTX. Got: {file.content_type}"
        )
    
    file_type = allowed_types[file.content_type]
    
    # Validate file size (configurable limit)
    MAX_FILE_SIZE = settings.knowledge_base_max_upload_size_mb * 1024 * 1024
    
    # Read file content
    content = await file.read()
    file_size = len(content)
    
    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size is {settings.knowledge_base_max_upload_size_mb}MB. Got: {file_size / 1024 / 1024:.2f}MB"
        )
    
    # Get next document ID
    max_id_stmt = select(func.max(models.KnowledgeDocument.id))
    max_id_result = session.exec(max_id_stmt).first()
    doc_id = (max_id_result or 0) + 1
    
    # Create document directory structure
    doc_dir = KB_DOCUMENTS_DIR / str(doc_id) / "v1"
    doc_dir.mkdir(parents=True, exist_ok=True)
    
    # Save file
    file_extension = Path(file.filename).suffix
    safe_filename = f"{doc_id}_v1{file_extension}"
    file_path = doc_dir / safe_filename
    
    try:
        with file_path.open("wb") as f:
            f.write(content)
        
        logger.info(f"File saved to {file_path}")
        
        # Extract text for search (async, non-blocking)
        searchable_content = await kb_service.extract_text_from_document(file_path, file_type)
        logger.info(f"Extracted {len(searchable_content)} characters from document")
        
        # Create database record
        # Calculate relative path from project root
        project_root = Path(__file__).resolve().parent.parent.parent
        relative_path = file_path.relative_to(project_root)
        
        document = models.KnowledgeDocument(
            title=title,
            description=description,
            file_path=str(relative_path).replace("\\", "/"),  # Use forward slashes
            file_name=file.filename,
            file_type=file_type,
            file_size=file_size,
            category=category,
            tags=tags,
            access_level=access_level,
            searchable_content=searchable_content,
            uploaded_by_username=current_user.username,
        )
        
        session.add(document)
        session.commit()
        session.refresh(document)
        
        # Auto-vectorize document for semantic search
        try:
            from ..services.chatbot_service import chatbot_service
            if chatbot_service.vector_service and chatbot_service.vector_service.enabled:
                chatbot_service.vector_service.add_document(
                    doc_id=document.id,
                    title=document.title,
                    content=searchable_content or "",
                    category=category,
                    tags=tags,
                    file_type=file_type
                )
                logger.info(f"Document {document.id} vectorized for semantic search")
        except Exception as e:
            logger.warning(f"Failed to vectorize document {document.id}: {e}")
        
        # Build file URL
        file_url = f"/static/knowledge_base/documents/{doc_id}/v1/{safe_filename}"
        
        logger.info(f"Document '{title}' uploaded successfully with ID {document.id}")
        
        return models.KnowledgeDocumentUploadResponse(
            id=document.id,
            title=document.title,
            file_url=file_url,
            message="Document uploaded successfully"
        )
        
    except Exception as e:
        logger.error(f"Error uploading document: {e}", exc_info=True)
        # Clean up file if it exists
        if file_path.exists():
            file_path.unlink()
        raise HTTPException(status_code=500, detail=f"Failed to upload document: {str(e)}")


@router.get("/api/knowledge/documents", response_model=List[models.KnowledgeDocumentRead])
async def list_documents(
    query: Optional[str] = Query(None, description="Search query"),
    category: Optional[str] = Query(None),
    file_type: Optional[str] = Query(None),
    limit: int = Query(50, le=100),
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """List/search knowledge base documents."""
    # Build query statement
    statement = select(models.KnowledgeDocument).where(
        models.KnowledgeDocument.is_active == True
    )
    
    # Determine access level filter based on user role
    if current_user.role == models.UserRoleEnum.pilot:
        # Pilots can see 'pilot' and 'public' documents
        statement = statement.where(
            or_(
                models.KnowledgeDocument.access_level == "pilot",
                models.KnowledgeDocument.access_level == "public"
            )
        )
    # Admins see everything (no additional filter)
    
    # Apply filters
    if category:
        statement = statement.where(models.KnowledgeDocument.category == category)
    if file_type:
        statement = statement.where(models.KnowledgeDocument.file_type == file_type)
    
    # Apply search query
    if query:
        search_filter = or_(
            models.KnowledgeDocument.title.ilike(f"%{query}%"),
            models.KnowledgeDocument.description.ilike(f"%{query}%"),
            models.KnowledgeDocument.searchable_content.ilike(f"%{query}%"),
            models.KnowledgeDocument.tags.ilike(f"%{query}%")
        )
        statement = statement.where(search_filter)
    
    statement = statement.order_by(
        models.KnowledgeDocument.uploaded_at_utc.desc()
    ).limit(limit)
    
    documents = session.exec(statement).all()
    
    # Convert to response models with file URLs
    results = []
    for doc in documents:
        # Parse file path to build URL
        file_url = _normalize_file_url(doc.file_path)
        
        results.append(models.KnowledgeDocumentRead(
            id=doc.id,
            title=doc.title,
            description=doc.description,
            file_name=doc.file_name,
            file_type=doc.file_type,
            file_size=doc.file_size,
            category=doc.category,
            tags=doc.tags,
            access_level=doc.access_level,
            file_url=file_url,
            uploaded_by_username=doc.uploaded_by_username,
            uploaded_at_utc=doc.uploaded_at_utc,
            updated_at_utc=doc.updated_at_utc,
            version=doc.version
        ))
    
    return results


@router.get("/api/knowledge/documents/categories", response_model=models.CategoriesResponse)
async def get_categories(
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """Get list of all categories with document counts."""
    # Build query with access level filter
    statement = select(models.KnowledgeDocument).where(
        models.KnowledgeDocument.is_active == True
    )
    
    if current_user.role == models.UserRoleEnum.pilot:
        statement = statement.where(
            or_(
                models.KnowledgeDocument.access_level == "pilot",
                models.KnowledgeDocument.access_level == "public"
            )
        )
    
    documents = session.exec(statement).all()
    
    # Count documents by category
    category_counts = {}
    for doc in documents:
        category = doc.category or "Uncategorized"
        category_counts[category] = category_counts.get(category, 0) + 1
    
    categories = [
        models.CategoryInfo(name=cat, count=count)
        for cat, count in sorted(category_counts.items())
    ]
    
    return models.CategoriesResponse(categories=categories)


@router.get("/api/knowledge/documents/{doc_id}/download")
async def download_document(
    doc_id: int,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """Download a knowledge base document."""
    document = session.get(models.KnowledgeDocument, doc_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    
    if not document.is_active:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Check access
    if document.access_level == "admin" and current_user.role != models.UserRoleEnum.admin:
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Build full file path
    project_root = Path(__file__).resolve().parent.parent.parent
    file_path = project_root / document.file_path.replace("/", "\\" if "\\" in str(project_root) else "/")
    
    if not file_path.exists():
        logger.error(f"File not found at path: {file_path}")
        raise HTTPException(status_code=404, detail="File not found on server")
    
    return FileResponse(
        path=str(file_path),
        filename=document.file_name,
        media_type="application/octet-stream"
    )


@router.get("/api/knowledge/documents/{doc_id}", response_model=models.KnowledgeDocumentRead)
async def get_document(
    doc_id: int,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """Get a single knowledge base document."""
    document = session.get(models.KnowledgeDocument, doc_id)
    if not document or not document.is_active:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Check access
    if document.access_level == "admin" and current_user.role != models.UserRoleEnum.admin:
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Build file URL
    file_url = _normalize_file_url(document.file_path)
    
    return models.KnowledgeDocumentRead(
        id=document.id,
        title=document.title,
        description=document.description,
        file_name=document.file_name,
        file_type=document.file_type,
        file_size=document.file_size,
        category=document.category,
        tags=document.tags,
        access_level=document.access_level,
        file_url=file_url,
        uploaded_by_username=document.uploaded_by_username,
        uploaded_at_utc=document.uploaded_at_utc,
        updated_at_utc=document.updated_at_utc,
        version=document.version
    )


@router.get("/api/knowledge/documents/{doc_id}/extracted-text")
async def get_extracted_text(
    doc_id: int,
    preview: bool = Query(True, description="Return preview (first 500 chars) or full text"),
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """Get extracted text content from a document (for debugging/verification)."""
    document = session.get(models.KnowledgeDocument, doc_id)
    if not document or not document.is_active:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Check access
    if document.access_level == "admin" and current_user.role != models.UserRoleEnum.admin:
        raise HTTPException(status_code=403, detail="Access denied")
    
    if not document.searchable_content:
        return {
            "doc_id": doc_id,
            "title": document.title,
            "has_extracted_text": False,
            "message": "No text was extracted from this document. This could mean the extraction failed or the document has no text content."
        }
    
    text = document.searchable_content
    if preview and len(text) > 500:
        text = text[:500] + "..."
    
    return {
        "doc_id": doc_id,
        "title": document.title,
        "has_extracted_text": True,
        "text_length": len(document.searchable_content),
        "text": text
    }


@router.put("/api/knowledge/documents/{doc_id}", response_model=models.KnowledgeDocumentRead)
async def update_document(
    doc_id: int,
    update_data: models.KnowledgeDocumentUpdate,
    current_user: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """Update a knowledge base document. Admin only."""
    document = session.get(models.KnowledgeDocument, doc_id)
    if not document or not document.is_active:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Update fields
    update_dict = update_data.model_dump(exclude_unset=True)
    for field, value in update_dict.items():
        setattr(document, field, value)
    
    document.updated_at_utc = datetime.now(timezone.utc)
    
    session.add(document)
    session.commit()
    session.refresh(document)
    
    # Update document in vector store
    try:
        from ..services.chatbot_service import chatbot_service
        if chatbot_service.vector_service and chatbot_service.vector_service.enabled:
            chatbot_service.vector_service.add_document(
                doc_id=document.id,
                title=document.title,
                content=document.searchable_content or "",
                category=document.category,
                tags=document.tags,
                file_type=document.file_type
            )
            logger.info(f"Document {document.id} updated in vector store")
    except Exception as e:
        logger.warning(f"Failed to update document {document.id} in vector store: {e}")
    
    logger.info(f"Admin '{current_user.username}' updated document {doc_id}")
    
    # Build file URL
    file_url = _normalize_file_url(document.file_path)
    
    return models.KnowledgeDocumentRead(
        id=document.id,
        title=document.title,
        description=document.description,
        file_name=document.file_name,
        file_type=document.file_type,
        file_size=document.file_size,
        category=document.category,
        tags=document.tags,
        access_level=document.access_level,
        file_url=file_url,
        uploaded_by_username=document.uploaded_by_username,
        uploaded_at_utc=document.uploaded_at_utc,
        updated_at_utc=document.updated_at_utc,
        version=document.version
    )


@router.delete("/api/knowledge/documents/{doc_id}")
async def delete_document(
    doc_id: int,
    current_user: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """Delete (soft delete) a knowledge base document. Admin only."""
    document = session.get(models.KnowledgeDocument, doc_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    # Remove stored files from disk (if present)
    try:
        project_root = Path(__file__).resolve().parent.parent.parent
        file_path = project_root / document.file_path.replace("/", "\\" if "\\" in str(project_root) else "/")
        resolved_file_path = file_path.resolve()
        resolved_docs_root = KB_DOCUMENTS_DIR.resolve()

        try:
            resolved_file_path.relative_to(resolved_docs_root)
        except ValueError:
            logger.warning(
                "Skipping file deletion for document %s: path outside docs root (%s)",
                doc_id,
                resolved_file_path
            )
        else:
            if resolved_file_path.exists():
                try:
                    resolved_file_path.unlink()
                    logger.info("Deleted knowledge document file: %s", resolved_file_path)
                except Exception as e:
                    logger.warning("Failed to delete knowledge document file %s: %s", resolved_file_path, e)
            else:
                logger.info("Knowledge document file already missing: %s", resolved_file_path)

            # Remove version folder and document folder if empty
            doc_folder = resolved_file_path.parent.parent if resolved_file_path.parent.name.startswith("v") else resolved_file_path.parent
            for path in [resolved_file_path.parent, doc_folder]:
                try:
                    if path.exists() and path.is_dir():
                        path.rmdir()
                except Exception:
                    # Folder may not be empty; ignore
                    pass
    except Exception as e:
        logger.warning("Failed to remove document files for %s: %s", doc_id, e)
    
    # Remove from vector store (inactive documents shouldn't be searchable)
    try:
        from ..services.chatbot_service import chatbot_service
        if chatbot_service.vector_service and chatbot_service.vector_service.enabled:
            chatbot_service.vector_service.delete_document(doc_id)
            logger.info(f"Document {doc_id} removed from vector store")
    except Exception as e:
        logger.warning(f"Failed to delete document {doc_id} from vector store: {e}")
    
    # Soft delete - mark as inactive
    document.is_active = False
    document.updated_at_utc = datetime.now(timezone.utc)
    
    session.add(document)
    session.commit()
    
    logger.info(f"Admin '{current_user.username}' deleted (soft) document {doc_id}: {document.title}")
    
    return {
        "message": "Document deleted successfully",
        "id": doc_id
    }
