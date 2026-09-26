"""HTTP routes for publishing: the demo clock, running due posts now, and the adapter test bench."""

import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.adapters import AdapterRejected, Measurements, MockChannelAdapter, Submission
from app.clock import VirtualClock
from app.db import get_session
from app.dependencies import get_adapters, get_clock, get_media_dir, get_snapshot_interval
from app.publisher import publish_and_ingest

router = APIRouter(tags=["publishing"])

SessionDep = Annotated[Session, Depends(get_session)]
ClockDep = Annotated[VirtualClock, Depends(get_clock)]
AdaptersDep = Annotated[dict[str, MockChannelAdapter], Depends(get_adapters)]
MediaDirDep = Annotated[Path, Depends(get_media_dir)]

MAX_FAST_FORWARD_HOURS = 24 * 30
SECONDS_PER_HOUR = 3600
# Uploads above this are refused before the adapter sees them; well above every channel's file-size limit.
MAX_TEST_UPLOAD_BYTES = 50 * 1024 * 1024
HASHTAG_SEPARATORS = re.compile(r"[\s,]+")


class ClockOut(BaseModel):
    now: datetime
    offset_hours: float


class AdvanceRequest(BaseModel):
    hours: float = Field(gt=0, le=MAX_FAST_FORWARD_HOURS)


class PublishRunOut(BaseModel):
    now: datetime
    published: list[int]
    rejected: list[int]
    metrics_ingested: list[int]


class MeasurementsOut(BaseModel):
    width: int | None
    height: int | None
    file_size_bytes: int
    published_length: int
    hashtag_count: int


class AdapterVerdictOut(BaseModel):
    channel: str
    accepted: bool
    reasons: list[str]
    measurements: MeasurementsOut


def _clock_out(clock: VirtualClock) -> ClockOut:
    return ClockOut(now=clock.now(), offset_hours=clock.offset.total_seconds() / SECONDS_PER_HOUR)


def _run_due(session: Session, adapters: AdaptersDep, media_dir: Path, clock: VirtualClock) -> PublishRunOut:
    now = clock.now()
    run = publish_and_ingest(session, adapters, media_dir, now, get_snapshot_interval())
    return PublishRunOut(
        now=now, published=run.published, rejected=run.rejected, metrics_ingested=run.metrics_ingested
    )


@router.get("/clock", response_model=ClockOut)
def get_clock_state(clock: ClockDep) -> ClockOut:
    return _clock_out(clock)


@router.post("/clock/advance", response_model=PublishRunOut)
def advance_clock(
    request: AdvanceRequest, session: SessionDep, clock: ClockDep, adapters: AdaptersDep, media_dir: MediaDirDep
) -> PublishRunOut:
    """Fast-forward the demo clock, then publish whatever became due."""
    clock.advance(timedelta(hours=request.hours))
    return _run_due(session, adapters, media_dir, clock)


@router.post("/clock/reset", response_model=ClockOut)
def reset_clock(clock: ClockDep) -> ClockOut:
    """Drop the fast-forward and return to real time. Scheduled posts then wait for their real time."""
    clock.reset()
    return _clock_out(clock)


@router.post("/publisher/run-due", response_model=PublishRunOut)
def run_due_now(session: SessionDep, clock: ClockDep, adapters: AdaptersDep, media_dir: MediaDirDep) -> PublishRunOut:
    """Publish every scheduled post that is already due, without waiting for the background loop."""
    return _run_due(session, adapters, media_dir, clock)


def _parse_hashtags(raw: str) -> tuple[str, ...]:
    return tuple(tag.lstrip("#") for tag in HASHTAG_SEPARATORS.split(raw) if tag.lstrip("#"))


def _measurements_out(measurements: Measurements) -> MeasurementsOut:
    return MeasurementsOut(**measurements.__dict__)


@router.post(
    "/adapters/{channel}/submit",
    response_model=AdapterVerdictOut,
    responses={status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "Rejected by the adapter, with the reasons"}},
)
async def submit_to_adapter(
    channel: str,
    adapters: AdaptersDep,
    image: Annotated[UploadFile, File()],
    caption: Annotated[str, Form()] = "",
    hashtags: Annotated[str, Form()] = "",
) -> AdapterVerdictOut:
    """Test bench: send any caption and image straight to a channel's adapter. Nothing is stored.

    Accepted posts return 200. Rejected ones return 422 with every reason, exactly as the publisher would see them.
    """
    if channel not in adapters:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown channel {channel!r}; known: {', '.join(adapters)}")
    image_bytes = await image.read(MAX_TEST_UPLOAD_BYTES + 1)
    if len(image_bytes) > MAX_TEST_UPLOAD_BYTES:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE, f"Uploads are limited to {MAX_TEST_UPLOAD_BYTES // (1024 * 1024)} MB"
        )
    submission = Submission(caption=caption, hashtags=_parse_hashtags(hashtags), image_bytes=image_bytes)
    try:
        measurements = adapters[channel].publish(submission)
    except AdapterRejected as rejection:
        verdict = AdapterVerdictOut(
            channel=channel,
            accepted=False,
            reasons=rejection.reasons,
            measurements=_measurements_out(rejection.measurements or adapters[channel].measure(submission)),
        )
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, verdict.model_dump()) from rejection
    return AdapterVerdictOut(channel=channel, accepted=True, reasons=[], measurements=_measurements_out(measurements))
