"""Synthetic metrics are repeatable, platform-shaped, only grow, and carry the documented patterns."""

import json
from datetime import timedelta
from statistics import mean

import pytest

from app.channels import ChannelConfigError, get_channel_specs
from app.models import Language
from app.synthetic_metrics import (
    SYNTHETIC_METRICS_PATH,
    PostFacts,
    get_synthetic_metrics_config,
    load_synthetic_metrics_config,
    synthetic_metrics,
)
from tests.conftest import TEST_NOW

SPECS = get_channel_specs()
CONFIG = get_synthetic_metrics_config()
A_WEEK = timedelta(days=7)
SAMPLE_POSTS = range(1, 301)
PATTERN_TOLERANCE = 0.1  # counts of a few dozen clicks round by up to ~5%; the effects are 30-60%


def facts(post_id=1, channel="instagram", language=Language.ENGLISH, caption="Eid together", hashtags=("Eid",)):
    return PostFacts(
        post_id=post_id,
        channel=channel,
        language=language,
        caption=caption,
        hashtags=tuple(hashtags),
        published_at=TEST_NOW,
    )


def metrics_after(post_facts, elapsed):
    return synthetic_metrics(post_facts, TEST_NOW + elapsed, CONFIG, SPECS[post_facts.channel])


def engagement_rate(values):
    return values.engagements / values.impressions


def click_rate(values):
    return values.clicks / values.impressions


def test_the_config_covers_exactly_the_channels():
    assert set(CONFIG.channels) == set(SPECS)


def test_a_config_missing_a_channel_is_refused(tmp_path):
    raw = json.loads(SYNTHETIC_METRICS_PATH.read_text(encoding="utf-8"))
    del raw["channels"]["x"]
    broken = tmp_path / "synthetic_metrics.json"
    broken.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ChannelConfigError, match="exactly the channels"):
        load_synthetic_metrics_config(broken, SPECS)


def test_the_same_post_always_gets_the_same_numbers():
    assert metrics_after(facts(post_id=7), A_WEEK) == metrics_after(facts(post_id=7), A_WEEK)
    assert metrics_after(facts(post_id=7), A_WEEK) != metrics_after(facts(post_id=8), A_WEEK)


@pytest.mark.parametrize("channel", list(SPECS))
def test_totals_start_at_zero_and_only_grow(channel):
    post = facts(channel=channel)
    moments = [timedelta(hours=hours) for hours in (0, 1, 3, 12, 24, 72, 168)]

    series = [metrics_after(post, moment) for moment in moments]

    assert series[0].impressions == 0
    for earlier, later in zip(series, series[1:]):
        for field in ("impressions", "likes", "comments", "shares", "clicks"):
            assert getattr(later, field) >= getattr(earlier, field) >= 0
    assert series[-1].engagements <= series[-1].impressions


def test_nothing_before_publishing():
    assert metrics_after(facts(), -timedelta(hours=1)).impressions == 0


def test_platforms_have_their_own_shape():
    """Over many posts: Facebook clicks most, X engages least, Instagram reaches furthest and engages most."""
    averages = {}
    for channel in SPECS:
        week = [metrics_after(facts(post_id=post_id, channel=channel), A_WEEK) for post_id in SAMPLE_POSTS]
        averages[channel] = {
            "reach": mean(values.impressions for values in week),
            "engagement": mean(engagement_rate(values) for values in week),
            "clicks": mean(click_rate(values) for values in week),
        }

    assert averages["x"]["engagement"] < averages["facebook"]["engagement"] < averages["instagram"]["engagement"]
    assert max(averages, key=lambda channel: averages[channel]["clicks"]) == "facebook"
    assert max(averages, key=lambda channel: averages[channel]["reach"]) == "instagram"


def test_x_reaches_its_audience_within_hours_facebook_over_a_day():
    x, facebook = facts(channel="x"), facts(channel="facebook")

    x_share = metrics_after(x, timedelta(hours=12)).impressions / metrics_after(x, A_WEEK).impressions
    facebook_share = metrics_after(facebook, timedelta(hours=12)).impressions / metrics_after(facebook, A_WEEK).impressions

    assert x_share > 0.9 > 0.5 > facebook_share


def pattern(channel):
    return next(pattern for pattern in CONFIG.patterns if pattern.channel == channel)


def test_pattern_bengali_does_better_on_instagram():
    bengali = metrics_after(facts(channel="instagram", language=Language.BENGALI), A_WEEK)
    english = metrics_after(facts(channel="instagram", language=Language.ENGLISH), A_WEEK)

    ratio = engagement_rate(bengali) / engagement_rate(english)

    assert ratio == pytest.approx(pattern("instagram").engagement_factor, rel=PATTERN_TOLERANCE)


def test_pattern_facebook_posts_with_many_hashtags_do_worse():
    few = metrics_after(facts(channel="facebook", hashtags=("Eid", "Kolkata", "Family")), A_WEEK)
    many = metrics_after(facts(channel="facebook", hashtags=("Eid", "Kolkata", "Family", "Fashion")), A_WEEK)

    ratio = engagement_rate(many) / engagement_rate(few)

    assert ratio == pytest.approx(pattern("facebook").engagement_factor, rel=PATTERN_TOLERANCE)


def test_pattern_short_x_posts_get_more_clicks():
    short = metrics_after(facts(channel="x", caption="Eid looks, in store now."), A_WEEK)
    long = metrics_after(facts(channel="x", caption="Eid looks for the whole family " * 6), A_WEEK)

    ratio = click_rate(short) / click_rate(long)

    assert ratio == pytest.approx(pattern("x").click_factor, rel=PATTERN_TOLERANCE)
