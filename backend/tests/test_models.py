from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, StatementError

from app.models import GenerationStatus, Insight, Language, Metric, Post, PostStatus, Report


def test_all_tables_round_trip(session, brief, make_post_in_status):
    post = make_post_in_status(PostStatus.PUBLISHED, channel="x", language=Language.BENGALI)
    session.add(Metric(post=post, impressions=1200, likes=85, comments=9, shares=4, clicks=30))
    report = Report(week_start=date(2026, 9, 21), body=f"Post {post.id} led on engagement.", cited_post_ids=[post.id])
    session.add(report)
    session.add(Insight(report=report, text="Short Bengali captions do well on X."))
    session.commit()
    session.expire_all()

    assert brief.languages == ["bn", "en"]
    assert brief.insights_used == []
    assert brief.created_at.utcoffset() == timedelta(0)
    assert post.language == Language.BENGALI
    assert post.hashtags == ["test"]
    assert post.generation_status == GenerationStatus.READY
    assert post.generation_error is None
    assert post.metrics[0].likes == 85
    assert report.cited_post_ids == [post.id]
    assert report.insights[0].text == "Short Bengali captions do well on X."


def test_post_for_a_missing_brief_is_refused(session):
    missing_brief_id = 999_999
    session.add(Post(brief_id=missing_brief_id, channel="x", language=Language.ENGLISH, caption="Orphan"))

    with pytest.raises(IntegrityError, match="FOREIGN KEY"):
        session.commit()


def test_unknown_status_value_fails_the_check_constraint(session, make_post_in_status):
    post = make_post_in_status(PostStatus.DRAFT)

    with pytest.raises(IntegrityError, match="CHECK"):
        session.execute(text("UPDATE posts SET status = 'bogus' WHERE id = :id"), {"id": post.id})


def test_new_posts_start_as_drafts_with_pending_generation(brief):
    post = Post(brief=brief, channel="x", language=Language.ENGLISH, caption="")

    assert post.status == PostStatus.DRAFT
    assert post.generation_status == GenerationStatus.PENDING


def test_generation_progress_is_independent_of_approval_status(session, make_post_in_status):
    post = make_post_in_status(PostStatus.DRAFT)
    post.generation_status = GenerationStatus.FAILED
    post.generation_error = "Cloudflare timed out after 90s"
    session.commit()
    session.expire_all()

    assert post.status == PostStatus.DRAFT
    assert post.generation_status == GenerationStatus.FAILED
    assert post.generation_error == "Cloudflare timed out after 90s"


def test_unknown_generation_status_fails_the_check_constraint(session, make_post_in_status):
    post = make_post_in_status(PostStatus.DRAFT)

    with pytest.raises(IntegrityError, match="CHECK"):
        session.execute(text("UPDATE posts SET generation_status = 'bogus' WHERE id = :id"), {"id": post.id})


def test_negative_metric_count_fails_the_check_constraint(session, make_post_in_status):
    post = make_post_in_status(PostStatus.PUBLISHED)
    session.add(Metric(post=post, impressions=100, likes=-1, comments=0, shares=0, clicks=0))

    with pytest.raises(IntegrityError, match="CHECK"):
        session.commit()


def test_unknown_channel_is_rejected(brief):
    with pytest.raises(ValueError, match="Unknown channel 'tiktok'"):
        Post(brief=brief, channel="tiktok", language=Language.ENGLISH, caption="Hi")


def test_new_post_cannot_start_outside_draft(brief):
    with pytest.raises(ValueError, match="must start as 'draft'"):
        Post(brief=brief, channel="x", language=Language.ENGLISH, caption="Hi", status=PostStatus.APPROVED)


def test_retry_keeps_lineage_to_the_discarded_post(session, brief, make_post_in_status):
    discarded = make_post_in_status(PostStatus.DISCARDED)
    retry = Post(brief=brief, channel=discarded.channel, language=discarded.language, caption="Take two", parent=discarded)
    session.add(retry)
    session.commit()

    assert retry.status == PostStatus.DRAFT
    assert retry.parent_post_id == discarded.id
    assert discarded.retries == [retry]


def test_a_post_can_have_only_one_retry(session, brief, make_post_in_status):
    discarded = make_post_in_status(PostStatus.DISCARDED)
    for caption in ("First retry", "Second retry"):
        session.add(Post(brief=brief, channel="x", language=Language.ENGLISH, caption=caption, parent=discarded))

    with pytest.raises(IntegrityError, match="UNIQUE"):
        session.commit()


def test_naive_datetime_is_refused(session, make_post_in_status):
    post = make_post_in_status(PostStatus.PUBLISHED)
    post.published_at = datetime(2026, 10, 1, 12, 0)

    with pytest.raises(StatementError, match="naive datetime"):
        session.commit()
