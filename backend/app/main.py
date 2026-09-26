"""FastAPI entry point. Run from backend/: `uv run uvicorn app.main:app --reload`."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import models  # noqa: F401  (registers every table on Base.metadata before create_all)
from app.channels import get_channel_specs
from app.config import MEDIA_URL_PATH, settings
from app.db import Base, SessionLocal, engine
from app.generation_clients import GenerationNotConfigured
from app.generation_service import BriefNotFound, fail_interrupted_generation
from app.headline_overlay import ensure_text_shaping_available
from app.post_service import PostNotFound
from app.post_status import InvalidTransition
from app.routes import briefs, channels, posts

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    get_channel_specs()  # Fail fast at startup if channels.json is invalid.
    ensure_text_shaping_available()  # Fail fast if Bengali headlines would render broken.
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        interrupted = fail_interrupted_generation(session)
    if interrupted:
        logger.warning("Marked %d posts failed: their generation was interrupted by a restart", interrupted)
    yield


app = FastAPI(title="AI Content Studio", lifespan=lifespan)
app.include_router(posts.router)
app.include_router(briefs.router)
app.include_router(channels.router)
# check_dir=False: the lifespan creates the folder, which runs after this line.
app.mount(MEDIA_URL_PATH, StaticFiles(directory=settings.media_dir, check_dir=False), name="media")


@app.exception_handler(InvalidTransition)
async def handle_invalid_transition(request: Request, error: InvalidTransition) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(error)})


@app.exception_handler(PostNotFound)
async def handle_post_not_found(request: Request, error: PostNotFound) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(error)})


@app.exception_handler(BriefNotFound)
async def handle_brief_not_found(request: Request, error: BriefNotFound) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(error)})


@app.exception_handler(GenerationNotConfigured)
async def handle_generation_not_configured(request: Request, error: GenerationNotConfigured) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"detail": str(error)})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
