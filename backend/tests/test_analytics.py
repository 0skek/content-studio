"""Metrics are ingested through the adapters, and brief comparisons rank channels by rates, not raw totals."""

from datetime import timedelta

from app.adapters import build_adapters
from app.analytics import ingest_metrics, latest_snapshots
from app.channels import get_channel_specs
from app.models import Language, Metric, PostStatus
from app.post_status import transition
from app.synthetic_metrics import get_synthetic_metrics_config
from tests.conftest import TEST_NOW

ADAPTERS = build_adapters(get_channel_specs(), get_synthetic_metrics_config())
INTERVAL = timedelta(minutes=30)


def published(session, make_publishable_post, **fields):
    post = make_publishable_post(**fields)
    transition(post, PostStatus.PUBLISHED)
    post.published_at = TEST_NOW
    session.commit()
    return post


def add_snapshot(session, post, impressions, engagements, clicks, at=TEST_NOW):
    session.add(
        Metric(post_id=post.id, fetched_at=at, impressions=impressions, likes=engagements, comments=0, shares=0, clicks=clicks)
    )
    session.commit()


def test_only_published_posts_get_metrics(session, make_publishable_post):
    live = published(session, make_publishable_post)
    waiting = make_publishable_post(scheduled_at=TEST_NOW + timedelta(hours=1))

    ingested = ingest_metrics(session, ADAPTERS, TEST_NOW + timedelta(hours=2), INTERVAL)

    assert ingested == [live.id]
    assert set(latest_snapshots(session, [live.id, waiting.id])) == {live.id}


def test_snapshots_are_taken_at_most_once_per_interval_and_grow(session, make_publishable_post):
    post = published(session, make_publishable_post, channel="facebook")
    first_time = TEST_NOW + timedelta(hours=2)

    assert ingest_metrics(session, ADAPTERS, first_time, INTERVAL) == [post.id]
    assert ingest_metrics(session, ADAPTERS, first_time + INTERVAL / 2, INTERVAL) == []
    assert ingest_metrics(session, ADAPTERS, first_time + INTERVAL, INTERVAL) == [post.id]

    snapshots = session.query(Metric).filter_by(post_id=post.id).order_by(Metric.fetched_at).all()
    assert len(snapshots) == 2
    assert snapshots[1].impressions > snapshots[0].impressions > 0


def test_fast_forward_ingests_metrics(client, make_publishable_post):
    post = make_publishable_post(scheduled_at=TEST_NOW + timedelta(hours=1))

    first = client.post("/clock/advance", json={"hours": 2}).json()
    second = client.post("/clock/advance", json={"hours": 24}).json()

    assert first["published"] == [post.id] and first["metrics_ingested"] == [post.id]
    assert second["metrics_ingested"] == [post.id]
    cell = client.get(f"/briefs/{post.brief_id}/comparison").json()["rows"][1]["cells"]["x"]
    assert cell["post_id"] == post.id and cell["impressions"] > 0


def test_comparison_ranks_by_rate_not_by_raw_totals(client, session, make_publishable_post):
    """Instagram has 10x the impressions and more engagements in total, but Facebook engages a larger share."""
    instagram = published(session, make_publishable_post, channel="instagram")
    facebook = published(session, make_publishable_post, channel="facebook")
    add_snapshot(session, instagram, impressions=10_000, engagements=200, clicks=20)  # 2% engagement, 0.2% clicks
    add_snapshot(session, facebook, impressions=1_000, engagements=50, clicks=15)  # 5% engagement, 1.5% clicks

    body = client.get(f"/briefs/{instagram.brief_id}/comparison").json()

    english = next(row for row in body["rows"] if row["language"] == Language.ENGLISH)
    assert english["best_engagement_channel"] == "facebook"
    assert english["best_click_channel"] == "facebook"
    assert english["cells"]["instagram"]["engagement_rate"] == 0.02
    assert english["cells"]["facebook"]["engagement_rate"] == 0.05
    assert english["cells"]["x"] is None
    assert body["definitions"]["engagement_rate"] == "(likes + comments + shares) / impressions"


def test_comparison_uses_each_posts_latest_snapshot(client, session, make_publishable_post):
    post = published(session, make_publishable_post)
    add_snapshot(session, post, impressions=100, engagements=1, clicks=0, at=TEST_NOW)
    add_snapshot(session, post, impressions=1_000, engagements=30, clicks=5, at=TEST_NOW + timedelta(hours=5))

    cell = client.get(f"/briefs/{post.brief_id}/comparison").json()["rows"][1]["cells"]["x"]

    assert cell["impressions"] == 1_000 and cell["engagement_rate"] == 0.03


def test_channel_summaries_pool_totals_across_languages(client, session, make_publishable_post):
    english = published(session, make_publishable_post, channel="x")
    bengali = published(session, make_publishable_post, channel="x")
    bengali.language = Language.BENGALI
    session.commit()
    add_snapshot(session, english, impressions=900, engagements=9, clicks=9)
    add_snapshot(session, bengali, impressions=100, engagements=11, clicks=1)

    summaries = client.get(f"/briefs/{english.brief_id}/comparison").json()["channel_summaries"]

    x = next(summary for summary in summaries if summary["channel"] == "x")
    assert x["post_ids"] == [bengali.id, english.id] or x["post_ids"] == [english.id, bengali.id]
    assert x["engagement_rate"] == 20 / 1000  # sums over sums, not the average of 1% and 11%


def test_a_published_post_without_metrics_yet_is_shown_but_not_ranked(client, session, make_publishable_post):
    post = published(session, make_publishable_post)

    english = client.get(f"/briefs/{post.brief_id}/comparison").json()["rows"][1]

    assert english["cells"]["x"]["impressions"] == 0 and english["cells"]["x"]["engagement_rate"] is None
    assert english["best_engagement_channel"] is None


def test_unpublished_posts_are_not_compared(client, make_publishable_post):
    post = make_publishable_post(scheduled_at=None)

    rows = client.get(f"/briefs/{post.brief_id}/comparison").json()["rows"]

    assert all(cell is None for row in rows for cell in row["cells"].values())


def test_feeds_show_published_posts_per_channel_newest_first(client, session, make_publishable_post):
    older = published(session, make_publishable_post, channel="instagram")
    newer = published(session, make_publishable_post, channel="instagram")
    newer.published_at = TEST_NOW + timedelta(hours=1)
    session.commit()
    make_publishable_post(channel="instagram", scheduled_at=None)  # approved only: not in the feed
    add_snapshot(session, newer, impressions=500, engagements=20, clicks=2)

    feeds = client.get("/feeds").json()

    assert set(feeds) == set(get_channel_specs())
    assert [item["post"]["id"] for item in feeds["instagram"]] == [newer.id, older.id]
    assert feeds["instagram"][0]["performance"]["likes"] == 20
    assert feeds["instagram"][0]["brief_title"]
    assert feeds["x"] == []


def test_comparison_of_an_unknown_brief_is_404(client):
    assert client.get("/briefs/999/comparison").status_code == 404
