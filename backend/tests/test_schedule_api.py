"""Milestone 1 done-check: the API refuses to schedule any post that is not approved (rule 2)."""

from datetime import datetime, timedelta, timezone

import pytest

from app.models import Post, PostStatus

KOLKATA_TIME = timezone(timedelta(hours=5, minutes=30))
SCHEDULE_TIME = datetime(2026, 10, 1, 18, 0, tzinfo=KOLKATA_TIME)
NON_APPROVED_STATUSES = [status for status in PostStatus if status != PostStatus.APPROVED]


def schedule_request(client, post_id: int, scheduled_at: str = SCHEDULE_TIME.isoformat()):
    return client.post(f"/posts/{post_id}/schedule", json={"scheduled_at": scheduled_at})


@pytest.mark.parametrize("status", NON_APPROVED_STATUSES)
def test_scheduling_a_non_approved_post_is_refused(client, session_factory, make_post_in_status, status):
    post = make_post_in_status(status)
    scheduled_at_before = post.scheduled_at

    response = schedule_request(client, post.id)

    assert response.status_code == 409
    assert f"cannot move from '{status}' to 'scheduled'" in response.json()["detail"]
    with session_factory() as fresh_session:
        stored_post = fresh_session.get(Post, post.id)
        assert stored_post.status == status
        assert stored_post.scheduled_at == scheduled_at_before


def test_scheduling_an_approved_post_queues_it_in_utc(client, session_factory, make_post_in_status):
    post = make_post_in_status(PostStatus.APPROVED)

    response = schedule_request(client, post.id)

    assert response.status_code == 200
    assert response.json()["status"] == PostStatus.SCHEDULED
    with session_factory() as fresh_session:
        stored_post = fresh_session.get(Post, post.id)
        assert stored_post.status == PostStatus.SCHEDULED
        assert stored_post.scheduled_at == SCHEDULE_TIME
        assert stored_post.scheduled_at.utcoffset() == timedelta(0)


def test_scheduling_an_unknown_post_is_404(client):
    response = schedule_request(client, post_id=999_999)

    assert response.status_code == 404


def test_scheduling_with_a_naive_datetime_is_422_and_changes_nothing(client, session_factory, make_post_in_status):
    post = make_post_in_status(PostStatus.APPROVED)

    response = schedule_request(client, post.id, scheduled_at="2026-10-01T18:00:00")

    assert response.status_code == 422
    with session_factory() as fresh_session:
        assert fresh_session.get(Post, post.id).status == PostStatus.APPROVED
