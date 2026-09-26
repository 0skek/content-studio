"""HTTP routes for briefs: creating one starts background generation of its draft posts; deleting one removes
everything built from it."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db import get_session
from app.deletion import delete_brief
from app.dependencies import get_generation_clients, get_media_dir, get_session_factory
from app.generation_clients import GenerationClients
from app.generation_service import create_brief_with_drafts, load_brief, run_brief_generation
from app.models import Brief
from app.schemas import BriefCreate, BriefOut, BriefSummaryOut

router = APIRouter(prefix="/briefs", tags=["briefs"])

SessionDep = Annotated[Session, Depends(get_session)]


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=BriefOut)
def create_brief(
    brief_in: BriefCreate,
    background_tasks: BackgroundTasks,
    session: SessionDep,
    clients: Annotated[GenerationClients, Depends(get_generation_clients)],
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
    media_dir: Annotated[Path, Depends(get_media_dir)],
) -> BriefOut:
    """Create the brief and its pending drafts, then generate them in the background."""
    brief = create_brief_with_drafts(session, brief_in)
    response = BriefOut.model_validate(brief)
    background_tasks.add_task(run_brief_generation, brief.id, clients, session_factory, media_dir)
    return response


@router.get("", response_model=list[BriefSummaryOut])
def list_briefs(session: SessionDep) -> list[Brief]:
    return list(session.scalars(select(Brief).order_by(Brief.created_at.desc(), Brief.id.desc())))


@router.get("/{brief_id}", response_model=BriefOut)
def get_brief(brief_id: int, session: SessionDep) -> BriefOut:
    return BriefOut.model_validate(load_brief(session, brief_id))


class DeletedBriefOut(BaseModel):
    brief_id: int
    post_ids: list[int]
    # Reports that cited any of those posts, deleted with them so no report cites a missing post.
    report_ids: list[int]


@router.delete("/{brief_id}", response_model=DeletedBriefOut)
def remove_brief(
    brief_id: int, session: SessionDep, media_dir: Annotated[Path, Depends(get_media_dir)]
) -> DeletedBriefOut:
    """Delete the brief, its posts (retries included), their metrics and images, and reports citing them.
    Refused with 409 while any of its posts is still generating."""
    deleted = delete_brief(session, brief_id, media_dir)
    return DeletedBriefOut(brief_id=deleted.brief_id, post_ids=deleted.post_ids, report_ids=deleted.report_ids)
