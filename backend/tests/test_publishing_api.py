"""The demo clock, the publish-now control and the adapter test bench, through the HTTP API."""

import pytest

from app.channels import get_channel_specs
from app.models import PostStatus
from tests.conftest import TEST_NOW
from tests.fakes import make_jpeg

SPECS = get_channel_specs()


def post_status(client, brief_id: int, post_id: int) -> dict:
    return next(post for post in client.get(f"/briefs/{brief_id}").json()["posts"] if post["id"] == post_id)


def test_the_clock_starts_at_real_time(client):
    body = client.get("/clock").json()

    assert body["now"].startswith(TEST_NOW.isoformat()[:19]) and body["offset_hours"] == 0


def test_fast_forward_publishes_what_became_due(client, make_publishable_post):
    post = make_publishable_post(scheduled_at=None)
    in_two_hours = "2026-09-26T14:00:00+00:00"
    assert client.post(f"/posts/{post.id}/schedule", json={"scheduled_at": in_two_hours}).status_code == 200
    assert client.post("/publisher/run-due").json()["published"] == []

    response = client.post("/clock/advance", json={"hours": 3})

    assert response.status_code == 200
    assert response.json()["published"] == [post.id]
    assert client.get("/clock").json()["offset_hours"] == 3
    published = post_status(client, post.brief_id, post.id)
    assert published["status"] == PostStatus.PUBLISHED and published["published_at"]


def test_reset_returns_to_real_time(client):
    client.post("/clock/advance", json={"hours": 30})

    body = client.post("/clock/reset").json()

    assert body["offset_hours"] == 0 and body["now"].startswith(TEST_NOW.isoformat()[:19])
    assert client.get("/clock").json()["offset_hours"] == 0


@pytest.mark.parametrize("hours", [0, -1])
def test_the_clock_only_moves_forward(client, hours):
    assert client.post("/clock/advance", json={"hours": hours}).status_code == 422


def test_run_due_reports_rejections_with_the_reason_stored(client, make_publishable_post):
    post = make_publishable_post(channel="instagram", image_bytes=make_jpeg(1024, 1024))

    body = client.post("/publisher/run-due").json()

    assert body["rejected"] == [post.id]
    rejected = post_status(client, post.brief_id, post.id)
    assert rejected["status"] == PostStatus.REJECTED
    assert rejected["rejection_reason"].startswith("aspect ratio 1024x1024")


def submit(client, channel: str, caption: str, image: bytes, hashtags: str = "Eid"):
    return client.post(
        f"/adapters/{channel}/submit",
        data={"caption": caption, "hashtags": hashtags},
        files={"image": ("post.jpg", image, "image/jpeg")},
    )


def test_bench_accepts_a_post_within_limits(client):
    spec = SPECS["linkedin"].image

    response = submit(client, "linkedin", "Eid outfits for the whole family", make_jpeg(spec.width, spec.height))

    body = response.json()
    assert response.status_code == 200
    assert body["accepted"] is True and body["reasons"] == []
    assert (body["measurements"]["width"], body["measurements"]["height"]) == (spec.width, spec.height)


def test_milestone_4_bench_rejects_an_oversized_caption_with_the_reason(client):
    spec = SPECS["x"]

    response = submit(client, "x", "a" * spec.caption.max_chars, make_jpeg(spec.image.width, spec.image.height))

    assert response.status_code == 422
    verdict = response.json()["detail"]
    assert verdict["accepted"] is False
    assert len(verdict["reasons"]) == 1 and f"the limit is {spec.caption.max_chars}" in verdict["reasons"][0]
    assert verdict["measurements"]["published_length"] > spec.caption.max_chars


def test_milestone_4_bench_rejects_a_wrong_ratio_image_with_the_reason(client):
    response = submit(client, "instagram", "Eid outfits", make_jpeg(1024, 1024))

    assert response.status_code == 422
    assert response.json()["detail"]["reasons"] == ["aspect ratio 1024x1024 (1.000:1) is not 4:5 (0.800:1) within ±2%"]


def test_bench_reads_hashtags_with_or_without_hash_signs(client):
    spec = SPECS["x"].image

    response = submit(client, "x", "Eid", make_jpeg(spec.width, spec.height), hashtags="#one, two #three")

    assert response.status_code == 422
    assert response.json()["detail"]["reasons"] == ["3 hashtags; the limit is 2"]


def test_bench_refuses_an_unknown_channel(client):
    assert submit(client, "tiktok", "Eid", make_jpeg(64, 64)).status_code == 404
