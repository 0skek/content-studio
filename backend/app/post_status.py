"""The post state machine. transition() is the only code allowed to change a post's status."""

from app.models import GenerationStatus, Post, PostStatus

ALLOWED_TRANSITIONS: dict[PostStatus, frozenset[PostStatus]] = {
    PostStatus.DRAFT: frozenset({PostStatus.APPROVED, PostStatus.DISCARDED}),
    PostStatus.APPROVED: frozenset({PostStatus.SCHEDULED}),
    PostStatus.SCHEDULED: frozenset({PostStatus.PUBLISHED, PostStatus.REJECTED}),
    PostStatus.DISCARDED: frozenset(),
    # Taking a post down from its channel returns it to the approved queue, so it can be scheduled again.
    PostStatus.PUBLISHED: frozenset({PostStatus.APPROVED}),
    PostStatus.REJECTED: frozenset(),
}


class InvalidTransition(Exception):
    """The requested status change is not allowed."""

    def __init__(
        self, post_id: int | None, from_status: PostStatus, to_status: PostStatus, message: str | None = None
    ) -> None:
        allowed_targets = ALLOWED_TRANSITIONS[from_status]
        allowed_text = ", ".join(sorted(allowed_targets)) if allowed_targets else "nothing (final state)"
        super().__init__(
            message
            or f"Post {post_id} cannot move from '{from_status}' to '{to_status}'. "
            f"Allowed from '{from_status}': {allowed_text}."
        )
        self.post_id = post_id
        self.from_status = from_status
        self.to_status = to_status


class GenerationNotReady(InvalidTransition):
    """Only drafts whose image and copy finished generating can be approved."""

    def __init__(self, post_id: int | None, generation_status: GenerationStatus) -> None:
        super().__init__(
            post_id,
            PostStatus.DRAFT,
            PostStatus.APPROVED,
            message=f"Post {post_id} can't be approved: its generation is {generation_status}. "
            f"Only posts whose generation is {GenerationStatus.READY} can be approved.",
        )
        self.generation_status = generation_status


def transition(post: Post, new_status: PostStatus, *, rejection_reason: str | None = None) -> None:
    """Move a post to new_status, or raise without touching it.

    Approving requires finished generation. Moving to 'rejected' requires a non-blank rejection_reason.
    Does not commit; the caller owns the transaction.
    """
    current_status = PostStatus(post.status)
    new_status = PostStatus(new_status)

    if new_status not in ALLOWED_TRANSITIONS[current_status]:
        raise InvalidTransition(post.id, current_status, new_status)

    if new_status == PostStatus.APPROVED and post.generation_status != GenerationStatus.READY:
        raise GenerationNotReady(post.id, GenerationStatus(post.generation_status))

    if new_status == PostStatus.REJECTED:
        if rejection_reason is None or not rejection_reason.strip():
            raise ValueError(f"Rejecting post {post.id} requires a non-blank rejection_reason")
    elif rejection_reason is not None:
        raise ValueError(
            f"rejection_reason is only accepted when rejecting; post {post.id} is moving to '{new_status}'"
        )

    post.status = new_status
    if new_status == PostStatus.REJECTED:
        post.rejection_reason = rejection_reason.strip()
