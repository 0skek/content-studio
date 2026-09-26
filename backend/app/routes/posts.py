"""HTTP routes for posts."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.post_service import schedule_post
from app.schemas import PostOut, ScheduleRequest

router = APIRouter(prefix="/posts", tags=["posts"])


@router.post("/{post_id}/schedule", response_model=PostOut)
def schedule(
    post_id: int, request: ScheduleRequest, session: Annotated[Session, Depends(get_session)]
) -> PostOut:
    """Queue an approved post for publishing. Any other status is refused with 409."""
    post = schedule_post(session, post_id, request.scheduled_at)
    return PostOut.model_validate(post)
