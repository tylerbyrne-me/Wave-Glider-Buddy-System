"""
Shared Tips Router

Handles HTTP endpoints for shared tips and tricks functionality.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from fastapi.responses import HTMLResponse
from typing import List, Optional
from datetime import datetime, timezone
import sqlalchemy as sa

from sqlmodel import select, or_, func
from ..core import models
from ..core.models.database import Announcement
from ..core.db import get_db_session, SQLModelSession
from ..core.auth import get_current_active_user, get_optional_current_user
from ..core.templates import templates
from ..core.template_context import get_template_context
import logging

router = APIRouter(tags=["Shared Tips"])
logger = logging.getLogger(__name__)


@router.get("/shared_tips.html", response_class=HTMLResponse)
async def shared_tips_page(
    request: Request,
    current_user: Optional[models.User] = Depends(get_optional_current_user)
):
    """Shared tips main page."""
    return templates.TemplateResponse(
        "shared_tips.html",
        get_template_context(request=request, current_user=current_user)
    )


@router.get("/api/shared-tips", response_model=List[models.SharedTipRead])
async def get_shared_tips(
    category: Optional[str] = Query(None),
    query: Optional[str] = Query(None, description="Search query"),
    pinned_only: bool = Query(False, description="Show only pinned tips"),
    limit: int = Query(50, le=100),
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """Get all shared tips."""
    statement = select(models.SharedTip).where(models.SharedTip.is_archived == False)
    
    # Apply filters
    if category:
        statement = statement.where(models.SharedTip.category == category)
    if pinned_only:
        statement = statement.where(models.SharedTip.is_pinned == True)
    if query:
        search_filter = or_(
            models.SharedTip.title.ilike(f"%{query}%"),
            models.SharedTip.content.ilike(f"%{query}%"),
            models.SharedTip.tags.ilike(f"%{query}%")
        )
        statement = statement.where(search_filter)
    
    # Order by pinned first, then helpful count, then updated date
    statement = statement.order_by(
        models.SharedTip.is_pinned.desc(),
        models.SharedTip.helpful_count.desc(),
        models.SharedTip.updated_at_utc.desc()
    ).limit(limit)
    
    tips = session.exec(statement).all()
    
    # Don't increment view count when just listing tips
    # Views only count when a tip is specifically viewed via GET /api/shared-tips/{tip_id}
    
    # Add comment/question counts
    tip_ids = [tip.id for tip in tips]
    counts_dict = {}
    if tip_ids:
        # Get all comments for these tips
        all_comments = session.exec(
            select(models.TipComment).where(models.TipComment.tip_id.in_(tip_ids))
        ).all()
        
        # Count by tip_id
        for comment in all_comments:
            if comment.tip_id not in counts_dict:
                counts_dict[comment.tip_id] = {
                    'comment_count': 0,
                    'question_count': 0,
                    'unresolved_question_count': 0
                }
            counts_dict[comment.tip_id]['comment_count'] += 1
            if comment.is_question:
                counts_dict[comment.tip_id]['question_count'] += 1
                if not comment.is_resolved:
                    counts_dict[comment.tip_id]['unresolved_question_count'] += 1
    
    # Convert to Pydantic models with counts
    result = []
    for tip in tips:
        counts = counts_dict.get(tip.id, {'comment_count': 0, 'question_count': 0, 'unresolved_question_count': 0})
        tip_dict = {
            'id': tip.id,
            'title': tip.title,
            'content': tip.content,
            'category': tip.category,
            'tags': tip.tags,
            'created_by_username': tip.created_by_username,
            'created_at_utc': tip.created_at_utc,
            'updated_at_utc': tip.updated_at_utc,
            'last_edited_by_username': tip.last_edited_by_username,
            'helpful_count': tip.helpful_count,
            'view_count': tip.view_count,
            'is_pinned': tip.is_pinned,
            'is_archived': tip.is_archived,
            'comment_count': counts['comment_count'],
            'question_count': counts['question_count'],
            'unresolved_question_count': counts['unresolved_question_count']
        }
        result.append(models.SharedTipRead(**tip_dict))
    
    return result


@router.get("/api/shared-tips/categories", response_model=models.CategoriesResponse)
async def get_shared_tip_categories(
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """Get list of categories for shared tips."""
    try:
        statement = select(models.SharedTip).where(models.SharedTip.is_archived == False)
        tips = session.exec(statement).all()
        
        # Count tips by category
        category_counts = {}
        for tip in tips:
            category = tip.category or "Uncategorized"
            category_counts[category] = category_counts.get(category, 0) + 1
        
        categories = [
            models.CategoryInfo(name=cat, count=count)
            for cat, count in sorted(category_counts.items())
        ]
        
        response = models.CategoriesResponse(categories=categories)
        logger.debug(f"Categories response: {response.model_dump()}")
        return response
    except Exception as e:
        logger.error(f"Error getting shared tip categories: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get categories: {str(e)}")


@router.get("/api/shared-tips/{tip_id}", response_model=models.SharedTipRead)
async def get_shared_tip(
    tip_id: int,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """Get a specific shared tip."""
    tip = session.get(models.SharedTip, tip_id)
    if not tip:
        raise HTTPException(status_code=404, detail="Tip not found")
    
    if tip.is_archived:
        raise HTTPException(status_code=404, detail="Tip not found")
    
    # Get comment/question counts
    comments = session.exec(
        select(models.TipComment).where(models.TipComment.tip_id == tip_id)
    ).all()
    
    comment_count = len(comments)
    question_count = sum(1 for c in comments if c.is_question)
    unresolved_question_count = sum(1 for c in comments if c.is_question and not c.is_resolved)
    
    # Increment view count
    tip.view_count += 1
    session.add(tip)
    session.commit()
    session.refresh(tip)
    
    # Convert to Pydantic model with counts
    tip_dict = {
        'id': tip.id,
        'title': tip.title,
        'content': tip.content,
        'category': tip.category,
        'tags': tip.tags,
        'created_by_username': tip.created_by_username,
        'created_at_utc': tip.created_at_utc,
        'updated_at_utc': tip.updated_at_utc,
        'last_edited_by_username': tip.last_edited_by_username,
        'helpful_count': tip.helpful_count,
        'view_count': tip.view_count,
        'is_pinned': tip.is_pinned,
        'is_archived': tip.is_archived,
        'comment_count': comment_count,
        'question_count': question_count,
        'unresolved_question_count': unresolved_question_count
    }
    
    return models.SharedTipRead(**tip_dict)


@router.post("/api/shared-tips", response_model=models.SharedTipRead, status_code=status.HTTP_201_CREATED)
async def create_shared_tip(
    tip_data: models.SharedTipCreate,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """Create a new shared tip."""
    tip = models.SharedTip(
        title=tip_data.title,
        content=tip_data.content,
        category=tip_data.category,
        tags=tip_data.tags,
        is_pinned=tip_data.is_pinned,
        created_by_username=current_user.username
    )
    
    session.add(tip)
    session.commit()
    session.refresh(tip)
    
    # Auto-vectorize tip for semantic search
    try:
        from ..services.chatbot_service import chatbot_service
        if chatbot_service.vector_service and chatbot_service.vector_service.enabled:
            chatbot_service.vector_service.add_tip(
                tip_id=tip.id,
                title=tip.title,
                content=tip.content,
                category=tip.category,
                tags=tip.tags
            )
            logger.info(f"Tip {tip.id} vectorized for semantic search")
    except Exception as e:
        logger.warning(f"Failed to vectorize tip {tip.id}: {e}")
    
    logger.info(f"User '{current_user.username}' created shared tip: {tip.title}")
    return tip


@router.put("/api/shared-tips/{tip_id}", response_model=models.SharedTipRead)
async def update_shared_tip(
    tip_id: int,
    tip_data: models.SharedTipUpdate,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """Update a shared tip. Any user can edit any tip."""
    tip = session.get(models.SharedTip, tip_id)
    if not tip:
        raise HTTPException(status_code=404, detail="Tip not found")
    
    if tip.is_archived:
        raise HTTPException(status_code=404, detail="Tip not found")
    
    # Update fields
    update_dict = tip_data.model_dump(exclude_unset=True)
    for field, value in update_dict.items():
        setattr(tip, field, value)
    
    tip.last_edited_by_username = current_user.username
    tip.updated_at_utc = datetime.now(timezone.utc)
    
    # Record contribution
    contribution = models.TipContribution(
        tip_id=tip.id,
        contributed_by_username=current_user.username,
        contribution_type="edit",
        content=f"Edited: {tip.title}"
    )
    session.add(contribution)
    
    session.add(tip)
    session.commit()
    session.refresh(tip)
    
    # Update tip in vector store
    try:
        from ..services.chatbot_service import chatbot_service
        if chatbot_service.vector_service and chatbot_service.vector_service.enabled:
            chatbot_service.vector_service.add_tip(
                tip_id=tip.id,
                title=tip.title,
                content=tip.content,
                category=tip.category,
                tags=tip.tags
            )
            logger.info(f"Tip {tip.id} updated in vector store")
    except Exception as e:
        logger.warning(f"Failed to update tip {tip.id} in vector store: {e}")
    
    logger.info(f"User '{current_user.username}' updated shared tip {tip_id}")
    return tip


@router.post("/api/shared-tips/{tip_id}/helpful", response_model=models.SharedTipRead)
async def mark_tip_helpful(
    tip_id: int,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """Mark a tip as helpful (increment helpful count)."""
    tip = session.get(models.SharedTip, tip_id)
    if not tip:
        raise HTTPException(status_code=404, detail="Tip not found")
    
    if tip.is_archived:
        raise HTTPException(status_code=404, detail="Tip not found")
    
    tip.helpful_count += 1
    session.add(tip)
    session.commit()
    session.refresh(tip)
    
    logger.info(f"User '{current_user.username}' marked tip {tip_id} as helpful")
    return tip


@router.delete("/api/shared-tips/{tip_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_shared_tip(
    tip_id: int,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """Delete (archive) a shared tip. Any user can archive tips."""
    tip = session.get(models.SharedTip, tip_id)
    if not tip:
        raise HTTPException(status_code=404, detail="Tip not found")
    
    # Soft delete - mark as archived
    tip.is_archived = True
    tip.updated_at_utc = datetime.now(timezone.utc)
    
    # Remove from vector store (archived tips shouldn't be searchable)
    try:
        from ..services.chatbot_service import chatbot_service
        if chatbot_service.vector_service and chatbot_service.vector_service.enabled:
            chatbot_service.vector_service.delete_tip(tip_id)
            logger.info(f"Tip {tip_id} removed from vector store")
    except Exception as e:
        logger.warning(f"Failed to delete tip {tip_id} from vector store: {e}")

    session.add(tip)
    session.commit()
    
    logger.info(f"User '{current_user.username}' archived tip {tip_id}")
    return None


# ============================================================================
# Tip Comments Endpoints
# ============================================================================

@router.get("/api/shared-tips/{tip_id}/comments", response_model=List[models.TipCommentRead])
async def get_tip_comments(
    tip_id: int,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """Get all comments for a specific tip."""
    # Verify tip exists and is not archived
    tip = session.get(models.SharedTip, tip_id)
    if not tip or tip.is_archived:
        raise HTTPException(status_code=404, detail="Tip not found")
    
    statement = select(models.TipComment).where(
        models.TipComment.tip_id == tip_id
    ).order_by(
        models.TipComment.is_question.desc(),  # Questions first
        models.TipComment.is_resolved.asc(),   # Unresolved questions first
        models.TipComment.created_at_utc.asc()  # Oldest first
    )
    
    comments = session.exec(statement).all()
    return comments


@router.post("/api/shared-tips/{tip_id}/comments", response_model=models.TipCommentRead, status_code=status.HTTP_201_CREATED)
async def create_tip_comment(
    tip_id: int,
    comment_data: models.TipCommentCreate,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """Create a comment on a tip."""
    # Verify tip exists and is not archived
    tip = session.get(models.SharedTip, tip_id)
    if not tip or tip.is_archived:
        raise HTTPException(status_code=404, detail="Tip not found")
    
    comment = models.TipComment(
        tip_id=tip_id,
        commented_by_username=current_user.username,
        content=comment_data.content,
        is_question=comment_data.is_question
    )
    
    session.add(comment)
    session.flush()  # Flush to ensure comment is in the session
    
    # If this is a question, create an announcement for admins
    if comment_data.is_question:
        try:
            # Use a more descriptive announcement with better formatting
            announcement_content = (
                f"**New Question on Shared Tip**\n\n"
                f"A new question has been posted on the tip **\"{tip.title}\"** by {current_user.username}.\n\n"
                f"Click [here](/shared_tips.html?tip_id={tip_id}) to view and answer the question."
            )
            
            announcement = Announcement(
                content=announcement_content,
                created_by_username="system",
                is_active=True,
                announcement_type="question"
            )
            session.add(announcement)
            session.flush()  # Flush to get the ID
            logger.info(f"Created announcement ID {announcement.id} for new question on tip {tip_id} by {current_user.username}")
        except Exception as e:
            logger.error(f"Failed to create announcement for question on tip {tip_id}: {e}", exc_info=True)
            # Don't fail the comment creation if announcement fails
    
    # Commit both comment and announcement together
    session.commit()
    session.refresh(comment)
    
    logger.info(f"User '{current_user.username}' created comment on tip {tip_id}")
    return comment


@router.put("/api/shared-tips/{tip_id}/comments/{comment_id}", response_model=models.TipCommentRead)
async def update_tip_comment(
    tip_id: int,
    comment_id: int,
    comment_data: models.TipCommentUpdate,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """Update a tip comment. Users can update their own comments."""
    comment = session.get(models.TipComment, comment_id)
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    
    if comment.tip_id != tip_id:
        raise HTTPException(status_code=400, detail="Comment does not belong to this tip")
    
    # Users can only update their own comments (unless admin)
    if comment.commented_by_username != current_user.username and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Access denied")
    
    was_resolved = comment.is_resolved
    was_question = comment.is_question
    
    # Update fields
    update_dict = comment_data.model_dump(exclude_unset=True)
    for field, value in update_dict.items():
        setattr(comment, field, value)
    
    comment.updated_at_utc = datetime.now(timezone.utc)
    
    session.add(comment)
    session.commit()
    session.refresh(comment)
    
    # If a question was just resolved, check if all questions are resolved and deactivate announcements
    if was_question and not was_resolved and comment.is_resolved:
        try:
            tip = session.get(models.SharedTip, tip_id)
            if tip:
                # Check if there are any other unresolved questions on this tip
                unresolved_questions = session.exec(
                    select(models.TipComment).where(
                        models.TipComment.tip_id == tip_id,
                        models.TipComment.is_question == True,
                        models.TipComment.is_resolved == False
                    )
                ).all()
                
                # Only deactivate announcements if all questions are resolved
                if len(unresolved_questions) == 0:
                    # Find and deactivate announcements about this tip
                    # Look for announcements that:
                    # 1. Are of type "question" (our question announcements)
                    # 2. Contain the tip_id in the URL (tip_id={tip_id})
                    announcements = session.exec(
                        select(Announcement).where(
                            Announcement.is_active == True,
                            Announcement.announcement_type == "question",
                            Announcement.content.like(f"%tip_id={tip_id}%")
                        )
                    ).all()
                    for ann in announcements:
                        ann.is_active = False
                        session.add(ann)
                    session.commit()
                    logger.info(f"Deactivated {len(announcements)} announcement(s) - all questions resolved on tip {tip_id}")
                else:
                    logger.info(f"Tip {tip_id} still has {len(unresolved_questions)} unresolved question(s), keeping announcement active")
        except Exception as e:
            logger.error(f"Failed to deactivate announcements: {e}")
    
    logger.info(f"User '{current_user.username}' updated comment {comment_id}")
    return comment


@router.delete("/api/shared-tips/{tip_id}/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tip_comment(
    tip_id: int,
    comment_id: int,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """Delete a tip comment. Users can delete their own comments."""
    comment = session.get(models.TipComment, comment_id)
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    
    if comment.tip_id != tip_id:
        raise HTTPException(status_code=400, detail="Comment does not belong to this tip")
    
    # Users can only delete their own comments (unless admin)
    if comment.commented_by_username != current_user.username and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Access denied")
    
    session.delete(comment)
    session.commit()
    
    logger.info(f"User '{current_user.username}' deleted comment {comment_id}")
    return None

