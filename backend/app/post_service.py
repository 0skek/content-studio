"""Post operations shared by the HTTP routes and, from milestone 4, the scheduler."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import GenerationStatus, Post, PostStatus
from app.post_status import transition


class PostNotFound(Exception):
    def __init__(self, post_id: int) -> None:
        super().__init__(f"Post {post_id} does not exist.")
        self.post_id = post_id


class NotRetryable(Exception):
    """The post cannot be retried; the message says why."""


def _load_post(session: Session, post_id: int) -> Post:
    post = session.get(Post, post_id)
    if post is None:
        raise PostNotFound(post_id)
    return post


def approve_post(session: Session, post_id: int) -> Post:
    """Human approval. Refused unless the post is a draft whose generation is ready."""
    post = _load_post(session, post_id)
    transition(post, PostStatus.APPROVED)
    session.commit()
    return post


def discard_post(session: Session, post_id: int) -> Post:
    post = _load_post(session, post_id)
    transition(post, PostStatus.DISCARDED)
    session.commit()
    return post


def retry_post(session: Session, post_id: int) -> Post:
    """Create a new pending draft for the same slot, with the old post as its parent.

    Allowed on a discarded post, or on a draft whose generation failed (discarded first). Each post is retried
    at most once. The caller queues generation for the returned draft.
    """
    post = _load_post(session, post_id)
    existing_retry_id = session.scalar(select(Post.id).where(Post.parent_post_id == post.id))
    if existing_retry_id is not None:
        raise NotRetryable(f"Post {post.id} was already retried as post #{existing_retry_id}.")

    if post.status == PostStatus.DRAFT:
        if post.generation_status in (GenerationStatus.PENDING, GenerationStatus.GENERATING):
            raise NotRetryable(f"Post {post.id} is still generating; wait for it to finish.")
        if post.generation_status == GenerationStatus.READY:
            raise NotRetryable(f"Post {post.id} is a ready draft; approve it, or discard it before retrying.")
        transition(post, PostStatus.DISCARDED)
    elif post.status != PostStatus.DISCARDED:
        raise NotRetryable(
            f"Post {post.id} is {post.status}; only discarded posts or drafts whose generation failed can be retried."
        )

    retry = Post(
        brief_id=post.brief_id,
        channel=post.channel,
        language=post.language,
        caption="",
        hashtags=[],
        parent_post_id=post.id,
    )
    session.add(retry)
    try:
        session.commit()
    except IntegrityError as error:  # A concurrent retry of the same post won the race.
        session.rollback()
        raise NotRetryable(f"Post {post_id} was already retried.") from error
    return retry


def schedule_post(session: Session, post_id: int, scheduled_at: datetime) -> Post:
    """Queue a post for publishing. Only approved posts pass; anything else raises InvalidTransition."""
    if scheduled_at.tzinfo is None:
        raise ValueError(f"scheduled_at {scheduled_at!r} must be timezone-aware")

    post = _load_post(session, post_id)
    transition(post, PostStatus.SCHEDULED)
    post.scheduled_at = scheduled_at.astimezone(timezone.utc)
    session.commit()
    return post
