"""FastAPI entry point. Run from backend/: `uv run uvicorn app.main:app --reload`."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app import models  # noqa: F401  (registers every table on Base.metadata before create_all)
from app.channels import get_channel_specs
from app.config import settings
from app.db import Base, engine
from app.post_service import PostNotFound
from app.post_status import InvalidTransition
from app.routes import posts


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    get_channel_specs()  # Fail fast at startup if channels.json is invalid.
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="AI Content Studio", lifespan=lifespan)
app.include_router(posts.router)


@app.exception_handler(InvalidTransition)
async def handle_invalid_transition(request: Request, error: InvalidTransition) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(error)})


@app.exception_handler(PostNotFound)
async def handle_post_not_found(request: Request, error: PostNotFound) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(error)})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
