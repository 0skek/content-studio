"""HTTP routes for briefs: creating one starts background generation of its draft posts."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.db import SessionLocal, get_session
from app.generation_clients import GenerationClients, build_generation_clients
from app.generation_service import create_brief_with_drafts, load_brief, run_brief_generation
from app.models import Brief
from app.schemas import BriefCreate, BriefOut, BriefSummaryOut

router = APIRouter(prefix="/briefs", tags=["briefs"])


# Dependencies, overridden in tests with fakes, a test database and a temporary media folder.
def get_generation_clients() -> GenerationClients:
    return build_generation_clients(settings)


def get_session_factory() -> sessionmaker[Session]:
    return SessionLocal


def get_media_dir() -> Path:
    return settings.media_dir


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
