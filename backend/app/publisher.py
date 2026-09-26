"""Publishing: due scheduled posts go through their channel's mock adapter and end published or rejected.

A background loop runs this every few seconds; the fast-forward and "publish due now" controls run it at once.
Status changes only through transition(): scheduled -> published, or scheduled -> rejected with the reasons.
Each run also ingests metrics for published posts through their adapters (see app/analytics.py).
"""

import asyncio
import logging
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.adapters import AdapterRejected, MockChannelAdapter, Submission
from app.analytics import ingest_metrics
from app.clock import VirtualClock
from app.models import Post, PostStatus
from app.post_status import transition

logger = logging.getLogger(__name__)

# The background loop and the manual controls must not publish (or snapshot) the same post twice.
_publishing_lock = threading.RLock()


@dataclass
class PublishRun:
    published: list[int] = field(default_factory=list)
    rejected: list[int] = field(default_factory=list)
    metrics_ingested: list[int] = field(default_factory=list)


def _submission_for(post: Post, media_dir: Path) -> Submission:
    """What the channel receives. A post whose final image is missing has nothing to send, so it is rejected."""
    if not post.image_path:
        raise AdapterRejected(post.channel, ["the post has no image to send"])
    image_file = media_dir / post.image_path
    try:
        image_bytes = image_file.read_bytes()
    except OSError as error:
        raise AdapterRejected(post.channel, [f"the image file {post.image_path} could not be read: {error}"]) from error
    return Submission(caption=post.caption, hashtags=tuple(post.hashtags), image_bytes=image_bytes)


def publish_due_posts(
    session: Session, adapters: Mapping[str, MockChannelAdapter], media_dir: Path, now: datetime
) -> PublishRun:
    """Send every scheduled post whose time has come, oldest first."""
    run = PublishRun()
    with _publishing_lock:
        due = session.scalars(
            select(Post)
            .where(Post.status == PostStatus.SCHEDULED, Post.scheduled_at <= now)
            .order_by(Post.scheduled_at, Post.id)
        ).all()
        for post in due:
            try:
                adapters[post.channel].publish(_submission_for(post, media_dir))
            except AdapterRejected as rejection:
                transition(post, PostStatus.REJECTED, rejection_reason="; ".join(rejection.reasons))
                run.rejected.append(post.id)
            else:
                transition(post, PostStatus.PUBLISHED)
                post.published_at = now
                run.published.append(post.id)
        session.commit()
    if run.published or run.rejected:
        logger.info("Publishing run: published %s, rejected %s", run.published, run.rejected)
    return run


def publish_and_ingest(
    session: Session,
    adapters: Mapping[str, MockChannelAdapter],
    media_dir: Path,
    now: datetime,
    snapshot_interval: timedelta,
) -> PublishRun:
    with _publishing_lock:
        run = publish_due_posts(session, adapters, media_dir, now)
        run.metrics_ingested = ingest_metrics(session, adapters, now, snapshot_interval)
    return run


async def run_scheduler(
    session_factory: sessionmaker[Session],
    adapters: Mapping[str, MockChannelAdapter],
    media_dir: Path,
    clock: VirtualClock,
    interval_seconds: float,
    snapshot_interval: timedelta,
) -> None:
    """Publish due posts and ingest metrics every interval until cancelled at shutdown."""
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await asyncio.to_thread(_run_once, session_factory, adapters, media_dir, clock, snapshot_interval)
        except Exception:  # Loop boundary: one failed run must not stop publishing for the rest of the demo.
            logger.exception("Scheduled publishing run failed")


def _run_once(
    session_factory: sessionmaker[Session],
    adapters: Mapping[str, MockChannelAdapter],
    media_dir: Path,
    clock: VirtualClock,
    snapshot_interval: timedelta,
) -> PublishRun:
    with session_factory() as session:
        return publish_and_ingest(session, adapters, media_dir, clock.now(), snapshot_interval)
