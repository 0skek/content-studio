import itertools

import pytest

from app.models import GenerationStatus, PostStatus
from app.post_status import ALLOWED_TRANSITIONS, GenerationNotReady, InvalidTransition, transition

ALLOWED_PAIRS = [(source, target) for source, targets in ALLOWED_TRANSITIONS.items() for target in targets]
DISALLOWED_PAIRS = [pair for pair in itertools.product(PostStatus, repeat=2) if pair not in ALLOWED_PAIRS]
FINAL_STATUSES = [PostStatus.DISCARDED, PostStatus.PUBLISHED, PostStatus.REJECTED]
REJECTION_REASON = "Image aspect ratio 1.00 does not match 4:5"


def reason_for(target: PostStatus) -> str | None:
    return REJECTION_REASON if target == PostStatus.REJECTED else None


def test_every_status_has_a_transition_entry():
    assert set(ALLOWED_TRANSITIONS) == set(PostStatus)


@pytest.mark.parametrize(("from_status", "to_status"), ALLOWED_PAIRS)
def test_allowed_transition_succeeds(make_post_in_status, from_status, to_status):
    post = make_post_in_status(from_status)

    transition(post, to_status, rejection_reason=reason_for(to_status))

    assert post.status == to_status


@pytest.mark.parametrize(("from_status", "to_status"), DISALLOWED_PAIRS)
def test_disallowed_transition_raises_and_leaves_post_untouched(make_post_in_status, from_status, to_status):
    post = make_post_in_status(from_status)
    rejection_reason_before = post.rejection_reason

    with pytest.raises(InvalidTransition) as raised:
        transition(post, to_status, rejection_reason=reason_for(to_status))

    assert (raised.value.from_status, raised.value.to_status) == (from_status, to_status)
    assert post.status == from_status
    assert post.rejection_reason == rejection_reason_before


@pytest.mark.parametrize("final_status", FINAL_STATUSES)
def test_final_statuses_have_no_way_out(final_status):
    assert ALLOWED_TRANSITIONS[final_status] == frozenset()


def test_refusal_message_names_the_allowed_targets(make_post_in_status):
    draft = make_post_in_status(PostStatus.DRAFT)

    with pytest.raises(InvalidTransition) as raised:
        transition(draft, PostStatus.SCHEDULED)

    assert str(raised.value) == (
        f"Post {draft.id} cannot move from 'draft' to 'scheduled'. Allowed from 'draft': approved, discarded."
    )


@pytest.mark.parametrize("blank_reason", [None, "", "   "])
def test_rejecting_requires_a_reason(make_post_in_status, blank_reason):
    post = make_post_in_status(PostStatus.SCHEDULED)

    with pytest.raises(ValueError, match="requires a non-blank rejection_reason"):
        transition(post, PostStatus.REJECTED, rejection_reason=blank_reason)

    assert post.status == PostStatus.SCHEDULED
    assert post.rejection_reason is None


def test_rejection_reason_is_stored(make_post_in_status):
    post = make_post_in_status(PostStatus.SCHEDULED)

    transition(post, PostStatus.REJECTED, rejection_reason=REJECTION_REASON)

    assert post.status == PostStatus.REJECTED
    assert post.rejection_reason == REJECTION_REASON


@pytest.mark.parametrize(
    "generation", [GenerationStatus.PENDING, GenerationStatus.GENERATING, GenerationStatus.FAILED]
)
def test_approving_requires_finished_generation(make_post_in_status, generation):
    draft = make_post_in_status(PostStatus.DRAFT, generation=generation)

    with pytest.raises(GenerationNotReady) as raised:
        transition(draft, PostStatus.APPROVED)

    assert str(raised.value).startswith(f"Post {draft.id} can't be approved: its generation is {generation}")
    assert draft.status == PostStatus.DRAFT


def test_a_draft_that_is_not_ready_can_still_be_discarded(make_post_in_status):
    draft = make_post_in_status(PostStatus.DRAFT, generation=GenerationStatus.FAILED)

    transition(draft, PostStatus.DISCARDED)

    assert draft.status == PostStatus.DISCARDED


def test_reason_on_a_non_reject_transition_is_refused(make_post_in_status):
    post = make_post_in_status(PostStatus.DRAFT)

    with pytest.raises(ValueError, match="only accepted when rejecting"):
        transition(post, PostStatus.APPROVED, rejection_reason="not a rejection")

    assert post.status == PostStatus.DRAFT
