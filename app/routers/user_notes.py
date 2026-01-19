"""
User Notes Router

Handles HTTP endpoints for user personal notes functionality.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from fastapi.responses import HTMLResponse
from typing import List, Optional
from datetime import datetime, timezone

from sqlmodel import select, or_, func
from ..core import models
from ..core.db import get_db_session, SQLModelSession
from ..core.auth import get_current_active_user, get_optional_current_user
from ..core.templates import templates
from ..core.template_context import get_template_context
import logging

router = APIRouter(tags=["User Notes"])
logger = logging.getLogger(__name__)


@router.get("/my_notes.html", response_class=HTMLResponse)
async def my_notes_page(
    request: Request,
    current_user: Optional[models.User] = Depends(get_optional_current_user)
):
    """User notes main page."""
    return templates.TemplateResponse(
        "my_notes.html",
        get_template_context(request=request, current_user=current_user)
    )


@router.get("/api/user-notes", response_model=List[models.UserNoteRead])
async def get_user_notes(
    category: Optional[str] = Query(None),
    query: Optional[str] = Query(None, description="Search query"),
    pinned_only: bool = Query(False, description="Show only pinned notes"),
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """Get all notes for the current user."""
    # Get user ID from database
    user_stmt = select(models.UserInDB).where(models.UserInDB.username == current_user.username)
    user_in_db = session.exec(user_stmt).first()
    if not user_in_db:
        raise HTTPException(status_code=404, detail="User not found")
    
    statement = select(models.UserNote).where(models.UserNote.user_id == user_in_db.id)
    
    # Apply filters
    if category:
        statement = statement.where(models.UserNote.category == category)
    if pinned_only:
        statement = statement.where(models.UserNote.is_pinned == True)
    if query:
        search_filter = or_(
            models.UserNote.title.ilike(f"%{query}%"),
            models.UserNote.content.ilike(f"%{query}%"),
            models.UserNote.tags.ilike(f"%{query}%")
        )
        statement = statement.where(search_filter)
    
    # Order by pinned first, then updated date
    statement = statement.order_by(
        models.UserNote.is_pinned.desc(),
        models.UserNote.updated_at_utc.desc()
    )
    
    notes = session.exec(statement).all()
    return notes


@router.get("/api/user-notes/categories", response_model=models.CategoriesResponse)
async def get_user_note_categories(
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """Get list of categories for user's notes."""
    # Get user ID from database
    user_stmt = select(models.UserInDB).where(models.UserInDB.username == current_user.username)
    user_in_db = session.exec(user_stmt).first()
    if not user_in_db:
        raise HTTPException(status_code=404, detail="User not found")
    
    statement = select(models.UserNote).where(models.UserNote.user_id == user_in_db.id)
    notes = session.exec(statement).all()
    
    # Count notes by category
    category_counts = {}
    for note in notes:
        category = note.category or "Uncategorized"
        category_counts[category] = category_counts.get(category, 0) + 1
    
    categories = [
        models.CategoryInfo(name=cat, count=count)
        for cat, count in sorted(category_counts.items())
    ]
    
    return models.CategoriesResponse(categories=categories)


@router.get("/api/user-notes/{note_id}", response_model=models.UserNoteRead)
async def get_user_note(
    note_id: int,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """Get a specific user note."""
    # Get user ID from database
    user_stmt = select(models.UserInDB).where(models.UserInDB.username == current_user.username)
    user_in_db = session.exec(user_stmt).first()
    if not user_in_db:
        raise HTTPException(status_code=404, detail="User not found")
    
    note = session.get(models.UserNote, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    
    # Verify ownership
    if note.user_id != user_in_db.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    return note


@router.post("/api/user-notes", response_model=models.UserNoteRead, status_code=status.HTTP_201_CREATED)
async def create_user_note(
    note_data: models.UserNoteCreate,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """Create a new user note."""
    # Get user ID from database
    user_stmt = select(models.UserInDB).where(models.UserInDB.username == current_user.username)
    user_in_db = session.exec(user_stmt).first()
    if not user_in_db:
        raise HTTPException(status_code=404, detail="User not found")
    
    note = models.UserNote(
        user_id=user_in_db.id,
        title=note_data.title,
        content=note_data.content,
        category=note_data.category,
        tags=note_data.tags,
        is_pinned=note_data.is_pinned
    )
    
    session.add(note)
    session.commit()
    session.refresh(note)
    
    logger.info(f"User '{current_user.username}' created note: {note.title}")
    return note


@router.put("/api/user-notes/{note_id}", response_model=models.UserNoteRead)
async def update_user_note(
    note_id: int,
    note_data: models.UserNoteUpdate,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """Update a user note."""
    # Get user ID from database
    user_stmt = select(models.UserInDB).where(models.UserInDB.username == current_user.username)
    user_in_db = session.exec(user_stmt).first()
    if not user_in_db:
        raise HTTPException(status_code=404, detail="User not found")
    
    note = session.get(models.UserNote, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    
    # Verify ownership
    if note.user_id != user_in_db.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Update fields
    update_dict = note_data.model_dump(exclude_unset=True)
    for field, value in update_dict.items():
        setattr(note, field, value)
    
    note.updated_at_utc = datetime.now(timezone.utc)
    
    session.add(note)
    session.commit()
    session.refresh(note)
    
    logger.info(f"User '{current_user.username}' updated note {note_id}")
    return note


@router.delete("/api/user-notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user_note(
    note_id: int,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """Delete a user note."""
    # Get user ID from database
    user_stmt = select(models.UserInDB).where(models.UserInDB.username == current_user.username)
    user_in_db = session.exec(user_stmt).first()
    if not user_in_db:
        raise HTTPException(status_code=404, detail="User not found")
    
    note = session.get(models.UserNote, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    
    # Verify ownership
    if note.user_id != user_in_db.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    session.delete(note)
    session.commit()
    
    logger.info(f"User '{current_user.username}' deleted note {note_id}")
    return None

