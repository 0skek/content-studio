"""Due scheduled posts go through their adapter: valid ones are published, violations are rejected with reasons."""

from datetime import timedelta

from app.adapters import build_adapters
from app.channels import get_channel_specs
from app.models import Post, PostStatus
from app.publisher import publish_due_posts
from app.synthetic_metrics import get_synthetic_metrics_config
from tests.conftest import TEST_NOW
from tests.fakes import make_jpeg

ADAPTERS = build_adapters(get_channel_specs(), get_synthetic_metrics_config())


def publish(session, media_dir):
    return publish_due_posts(session, ADAPTERS, media_dir, TEST_NOW)


def reloaded(session, post) -> Post:
    session.expire_all()
    return session.get(Post, post.id)


def test_a_due_post_within_limits_is_published(session, media_dir, make_publishable_post):
    post = make_publishable_post()

    run = publish(session, media_dir)

    published = reloaded(session, post)
    assert run.published == [post.id] and run.rejected == []
    assert published.status == PostStatus.PUBLISHED
    assert published.published_at == TEST_NOW
    assert published.rejection_reason is None


def test_a_post_not_yet_due_stays_scheduled(session, media_dir, make_publishable_post):
    post = make_publishable_post(scheduled_at=TEST_NOW + timedelta(hours=1))

    run = publish(session, media_dir)

    assert run.published == [] and reloaded(session, post).status == PostStatus.SCHEDULED


def test_approved_posts_that_were_never_scheduled_are_never_published(session, media_dir, make_publishable_post):
    post = make_publishable_post(scheduled_at=None)

    publish(session, media_dir)

    assert reloaded(session, post).status == PostStatus.APPROVED


def test_an_oversized_caption_reaching_the_publisher_is_rejected_with_the_reason(
    session, media_dir, make_publishable_post
):
    limit = get_channel_specs()["x"].caption.max_chars
    post = make_publishable_post(caption="a" * limit)

    run = publish(session, media_dir)

    rejected = reloaded(session, post)
    assert run.rejected == [post.id]
    assert rejected.status == PostStatus.REJECTED
    assert f"the limit is {limit}" in rejected.rejection_reason
    assert rejected.published_at is None


def test_a_wrong_ratio_image_is_rejected_and_left_exactly_as_it_was(session, media_dir, make_publishable_post):
    square = make_jpeg(1024, 1024)
    post = make_publishable_post(channel="instagram", image_bytes=square)

    publish(session, media_dir)

    rejected = reloaded(session, post)
    assert rejected.status == PostStatus.REJECTED
    assert rejected.rejection_reason.startswith("aspect ratio 1024x1024")
    assert (media_dir / rejected.image_path).read_bytes() == square


def test_a_missing_image_file_is_rejected(session, media_dir, make_publishable_post):
    post = make_publishable_post()
    (media_dir / post.image_path).unlink()

    publish(session, media_dir)

    rejected = reloaded(session, post)
    assert rejected.status == PostStatus.REJECTED
    assert "could not be read" in rejected.rejection_reason


def test_one_rejected_post_does_not_hold_up_the_others(session, media_dir, make_publishable_post):
    bad = make_publishable_post(channel="facebook", image_bytes=make_jpeg(1600, 900))  # wide, not square
    good = make_publishable_post(channel="facebook")

    run = publish(session, media_dir)

    assert run.rejected == [bad.id] and run.published == [good.id]


def test_running_again_does_not_republish(session, media_dir, make_publishable_post):
    make_publishable_post()
    publish(session, media_dir)

    second_run = publish(session, media_dir)

    assert second_run.published == [] and second_run.rejected == []
