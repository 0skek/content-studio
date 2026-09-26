"""Mock channel adapters reject every constraint violation with a reason and never fix anything (rule 3).

Includes the milestone 4 done-check: an oversized caption and a wrong-ratio image are each rejected with a reason.
"""

import pytest

from app.adapters import AdapterRejected, Submission, build_adapters, hashtag_count
from app.channels import get_channel_specs
from app.synthetic_metrics import get_synthetic_metrics_config
from tests.fakes import make_jpeg

SPECS = get_channel_specs()
ADAPTERS = build_adapters(SPECS, get_synthetic_metrics_config())
CAPTION_WITHIN_LIMITS = "Eid outfits for the whole family"


def native_image(channel: str) -> bytes:
    return make_jpeg(SPECS[channel].image.width, SPECS[channel].image.height)


def submission(channel: str, **changes) -> Submission:
    fields = {"caption": CAPTION_WITHIN_LIMITS, "hashtags": ("Eid",), "image_bytes": native_image(channel)}
    return Submission(**{**fields, **changes})


def rejection_reasons(channel: str, post: Submission) -> list[str]:
    with pytest.raises(AdapterRejected) as rejection:
        ADAPTERS[channel].publish(post)
    assert rejection.value.channel == channel
    return rejection.value.reasons


@pytest.mark.parametrize("channel", list(SPECS))
def test_a_post_within_every_limit_is_accepted(channel):
    measurements = ADAPTERS[channel].publish(submission(channel))

    assert (measurements.width, measurements.height) == (SPECS[channel].image.width, SPECS[channel].image.height)
    assert measurements.hashtag_count == 1


def test_milestone_4_an_oversized_caption_is_rejected_with_a_reason():
    limit = SPECS["x"].caption.max_chars

    reasons = rejection_reasons("x", submission("x", caption="a" * limit))

    assert len(reasons) == 1
    assert "caption plus hashtags is" in reasons[0] and f"the limit is {limit}" in reasons[0]


def test_milestone_4_a_wrong_ratio_image_is_rejected_with_a_reason():
    square = make_jpeg(1024, 1024)

    reasons = rejection_reasons("instagram", submission("instagram", image_bytes=square))

    assert reasons == ["aspect ratio 1024x1024 (1.000:1) is not 4:5 (0.800:1) within ±2%"]


@pytest.mark.parametrize("channel", list(SPECS))
def test_every_channel_rejects_another_channels_image(channel):
    other = next(other for other in SPECS if SPECS[other].image.aspect_ratio != SPECS[channel].image.aspect_ratio)

    reasons = rejection_reasons(channel, submission(channel, image_bytes=native_image(other)))

    assert any(reason.startswith("aspect ratio") for reason in reasons)


def test_a_ratio_inside_the_tolerance_is_accepted():
    slightly_off_16_by_9 = make_jpeg(1536, 870)  # 1.766:1, within 1% of 16:9

    ADAPTERS["x"].publish(submission("x", image_bytes=slightly_off_16_by_9))


def test_a_file_over_the_size_limit_is_rejected_not_recompressed():
    spec = SPECS["linkedin"].image
    padded = native_image("linkedin") + b"\0" * spec.max_file_size_bytes  # still a valid JPEG, just too big
    post = submission("linkedin", image_bytes=padded)

    reasons = rejection_reasons("linkedin", post)

    assert len(reasons) == 1 and f"the limit is {spec.max_file_size_mb:g} MB" in reasons[0]
    assert post.image_bytes == padded


def test_hashtags_are_counted_where_the_platform_sees_them_including_inline():
    limit = SPECS["x"].caption.max_hashtags
    post = submission("x", caption="Eid is here #EidMubarak #Dhaka", hashtags=("Eid",))

    reasons = rejection_reasons("x", post)

    assert reasons == [f"3 hashtags; the limit is {limit}"]


def test_hashtag_count_ignores_a_lone_hash_sign():
    assert hashtag_count("Price # 5 #Eid") == 1


def test_x_counts_emoji_double_but_bengali_single():
    limit = SPECS["x"].caption.max_chars
    bengali_at_the_limit = "ক" * limit
    emoji_over_the_limit = "\U0001f389" * (limit // 2 + 1)

    ADAPTERS["x"].publish(submission("x", caption=bengali_at_the_limit, hashtags=()))
    reasons = rejection_reasons("x", submission("x", caption=emoji_over_the_limit, hashtags=()))

    assert reasons == [f"caption plus hashtags is {limit + 2} weighted characters; the limit is {limit}"]


def test_an_unreadable_image_is_rejected():
    reasons = rejection_reasons("instagram", submission("instagram", image_bytes=b"not an image"))

    assert reasons == ["the image is not a readable image file"]


def test_every_violation_is_listed_at_once():
    post = submission("x", caption="a" * 300 + " #one #two", image_bytes=make_jpeg(1024, 1024))

    reasons = rejection_reasons("x", post)

    assert len(reasons) == 3
    assert [reason.split()[0] for reason in reasons] == ["aspect", "3", "caption"]
