"""FastAPI entry point. Run from backend/: `uv run uvicorn app.main:app --reload`."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import models  # noqa: F401  (registers every table on Base.metadata before create_all)
from app.channels import get_channel_specs
from app.config import MEDIA_URL_PATH, PRODUCTION_IMAGE_PROVIDER, PRODUCTION_TEXT_PROVIDER, settings
from app.db import Base, SessionLocal, engine
from app.generation_clients import GenerationNotConfigured
from app.deletion import BriefStillGenerating, ReportNotFound
from app.gemini_text import TextGenerationError
from app.generation_service import BriefNotFound, UnknownInsights, fail_interrupted_generation
from app.headline_overlay import ensure_face_detection_available, ensure_text_shaping_available
from app.post_service import NotRetryable, PostNotFound
from app.post_status import InvalidTransition
from app.dependencies import get_adapters, get_clock, get_snapshot_interval
from app.synthetic_metrics import get_synthetic_metrics_config
from app.publisher import run_scheduler
from app.reporting import NothingToReport, ReportGenerationFailed
from app.routes import analytics, briefs, channels, posts, publishing, reports

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    get_channel_specs()  # Fail fast at startup if channels.json is invalid.
    get_synthetic_metrics_config()  # ...or if synthetic_metrics.json is.
    ensure_text_shaping_available()  # Fail fast if Bengali headlines would render broken.
    ensure_face_detection_available()  # Headlines are kept off faces.
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        interrupted = fail_interrupted_generation(session)
    if interrupted:
        logger.warning("Marked %d posts failed: their generation was interrupted by a restart", interrupted)
    scheduler = asyncio.create_task(
        run_scheduler(
            SessionLocal,
            get_adapters(),
            settings.media_dir,
            get_clock(),
            settings.scheduler_interval_seconds,
            get_snapshot_interval(),
        )
    )
    yield
    scheduler.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await scheduler


app = FastAPI(title="AI Content Studio", lifespan=lifespan)
app.include_router(posts.router)
app.include_router(briefs.router)
app.include_router(channels.router)
app.include_router(publishing.router)
app.include_router(analytics.router)
app.include_router(reports.router)
# check_dir=False: the lifespan creates the folder, which runs after this line.
app.mount(MEDIA_URL_PATH, StaticFiles(directory=settings.media_dir, check_dir=False), name="media")


@app.exception_handler(InvalidTransition)
async def handle_invalid_transition(request: Request, error: InvalidTransition) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(error)})


@app.exception_handler(NotRetryable)
async def handle_not_retryable(request: Request, error: NotRetryable) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(error)})


@app.exception_handler(PostNotFound)
async def handle_post_not_found(request: Request, error: PostNotFound) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(error)})


@app.exception_handler(BriefNotFound)
async def handle_brief_not_found(request: Request, error: BriefNotFound) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(error)})


@app.exception_handler(BriefStillGenerating)
async def handle_brief_still_generating(request: Request, error: BriefStillGenerating) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(error)})


@app.exception_handler(ReportNotFound)
async def handle_report_not_found(request: Request, error: ReportNotFound) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(error)})


@app.exception_handler(UnknownInsights)
async def handle_unknown_insights(request: Request, error: UnknownInsights) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content={"detail": str(error)})


@app.exception_handler(NothingToReport)
async def handle_nothing_to_report(request: Request, error: NothingToReport) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(error)})


# The text model answered, but not usably (report citations) or not at all: an upstream failure.
@app.exception_handler(ReportGenerationFailed)
async def handle_report_failed(request: Request, error: ReportGenerationFailed) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_502_BAD_GATEWAY, content={"detail": str(error)})


@app.exception_handler(TextGenerationError)
async def handle_text_generation_error(request: Request, error: TextGenerationError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_502_BAD_GATEWAY, content={"detail": str(error)})


@app.exception_handler(GenerationNotConfigured)
async def handle_generation_not_configured(request: Request, error: GenerationNotConfigured) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"detail": str(error)})


@app.get("/health")
def health() -> dict[str, str | bool]:
    """Includes the active generation providers, so the UI can warn when dev providers are on."""
    return {
        "status": "ok",
        "text_provider": settings.text_provider,
        "image_provider": settings.image_provider,
        "production_providers": settings.text_provider == PRODUCTION_TEXT_PROVIDER
        and settings.image_provider == PRODUCTION_IMAGE_PROVIDER,
    }
