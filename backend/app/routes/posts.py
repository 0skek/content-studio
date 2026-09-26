"""HTTP routes for posts: the approval actions and scheduling. Every rule is enforced in post_service/transition()."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, status
from pydantic import BaseModel
from sqlalchemy.orm import Session, sessionmaker

from app.db import get_session
from app.deletion import take_down_post
from app.dependencies import get_generation_clients, get_media_dir, get_session_factory
from app.generation_clients import GenerationClients
from app.generation_service import run_brief_generation
from app.post_service import approve_post, discard_post, retry_post, schedule_post
from app.schemas import PostOut, ScheduleRequest

router = APIRouter(prefix="/posts", tags=["posts"])

SessionDep = Annotated[Session, Depends(get_session)]


@router.post("/{post_id}/approve", response_model=PostOut)
def approve(post_id: int, session: SessionDep) -> PostOut:
    """Approve a draft whose generation is ready. Anything else is refused with 409."""
    return PostOut.model_validate(approve_post(session, post_id))


@router.post("/{post_id}/discard", response_model=PostOut)
def discard(post_id: int, session: SessionDep) -> PostOut:
    return PostOut.model_validate(discard_post(session, post_id))


@router.post("/{post_id}/retry", status_code=status.HTTP_202_ACCEPTED, response_model=PostOut)
def retry(
    post_id: int,
    background_tasks: BackgroundTasks,
    session: SessionDep,
    clients: Annotated[GenerationClients, Depends(get_generation_clients)],
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
    media_dir: Annotated[Path, Depends(get_media_dir)],
) -> PostOut:
    """Create a new draft for a discarded (or failed) post and generate it in the background."""
    new_draft = retry_post(session, post_id)
    response = PostOut.model_validate(new_draft)
    background_tasks.add_task(run_brief_generation, new_draft.brief_id, clients, session_factory, media_dir)
    return response


class TakenDownOut(BaseModel):
    post: PostOut
    # Reports that cited the post; deleted because the numbers they cite are gone.
    deleted_report_ids: list[int]


@router.post("/{post_id}/take-down", response_model=TakenDownOut)
def take_down(post_id: int, session: SessionDep) -> TakenDownOut:
    """Remove a published post from its channel feed. It returns to approved with no metrics, ready to be
    scheduled again. Anything not published is refused with 409."""
    taken_down = take_down_post(session, post_id)
    return TakenDownOut(post=PostOut.model_validate(taken_down.post), deleted_report_ids=taken_down.report_ids)


@router.post("/{post_id}/schedule", response_model=PostOut)
def schedule(post_id: int, request: ScheduleRequest, session: SessionDep) -> PostOut:
    """Queue an approved post for publishing. Any other status is refused with 409."""
    return PostOut.model_validate(schedule_post(session, post_id, request.scheduled_at))
