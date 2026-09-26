"""Post operations shared by the HTTP routes and, from milestone 4, the scheduler."""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import Post, PostStatus
from app.post_status import transition


class PostNotFound(Exception):
    def __init__(self, post_id: int) -> None:
        super().__init__(f"Post {post_id} does not exist.")
        self.post_id = post_id


def schedule_post(session: Session, post_id: int, scheduled_at: datetime) -> Post:
    """Queue a post for publishing. Only approved posts pass; anything else raises InvalidTransition."""
    if scheduled_at.tzinfo is None:
        raise ValueError(f"scheduled_at {scheduled_at!r} must be timezone-aware")

    post = session.get(Post, post_id)
    if post is None:
        raise PostNotFound(post_id)

    transition(post, PostStatus.SCHEDULED)
    post.scheduled_at = scheduled_at.astimezone(timezone.utc)
    session.commit()
    return post
