"""FastAPI dependencies for generation. Tests override them with fakes, a test database and a temporary media folder."""

from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.db import SessionLocal
from app.generation_clients import GenerationClients, build_generation_clients


def get_generation_clients() -> GenerationClients:
    return build_generation_clients(settings)


def get_session_factory() -> sessionmaker[Session]:
    return SessionLocal


def get_media_dir() -> Path:
    return settings.media_dir
