"""FastAPI dependencies. Tests override them with fakes, a test database, a temporary media folder and their own clock."""

import functools
from datetime import timedelta
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from app.adapters import MockChannelAdapter, build_adapters
from app.channels import get_channel_specs
from app.clock import VirtualClock, app_clock
from app.config import settings
from app.synthetic_metrics import get_synthetic_metrics_config
from app.db import SessionLocal
from app.generation_clients import GenerationClients, build_generation_clients


def get_generation_clients() -> GenerationClients:
    return build_generation_clients(settings)


def get_session_factory() -> sessionmaker[Session]:
    return SessionLocal


def get_media_dir() -> Path:
    return settings.media_dir


def get_clock() -> VirtualClock:
    return app_clock


def get_snapshot_interval() -> timedelta:
    return timedelta(minutes=get_synthetic_metrics_config().snapshot_interval_minutes)


@functools.cache
def get_adapters() -> dict[str, MockChannelAdapter]:
    return build_adapters(get_channel_specs(), get_synthetic_metrics_config())
