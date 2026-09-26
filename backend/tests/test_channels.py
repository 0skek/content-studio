import itertools
import json

import pytest

from app.channels import BYTES_PER_MEGABYTE, ChannelConfigError, load_channel_specs
from app.config import settings

EXPECTED_CHANNELS = {"instagram", "facebook", "x"}


@pytest.fixture(scope="module")
def specs():
    return load_channel_specs(settings.channels_config_path)


def test_real_config_defines_exactly_the_three_channels(specs):
    assert set(specs) == EXPECTED_CHANNELS


def test_each_channel_has_a_distinct_image_size(specs):
    sizes = {(spec.image.width, spec.image.height) for spec in specs.values()}

    assert len(sizes) == len(specs)


def test_each_size_is_within_tolerance_of_its_declared_ratio(specs):
    for spec in specs.values():
        assert spec.image.matches_aspect_ratio(spec.image.width, spec.image.height)


@pytest.mark.parametrize(("channel", "other_channel"), list(itertools.permutations(sorted(EXPECTED_CHANNELS), 2)))
def test_each_channel_rejects_the_other_channels_sizes(specs, channel, other_channel):
    other_image = specs[other_channel].image

    assert not specs[channel].image.matches_aspect_ratio(other_image.width, other_image.height)


def test_max_file_size_is_exposed_in_bytes(specs):
    instagram_image = specs["instagram"].image

    assert instagram_image.max_file_size_bytes == instagram_image.max_file_size_mb * BYTES_PER_MEGABYTE


def write_modified_config(tmp_path, modify):
    config = json.loads(settings.channels_config_path.read_text(encoding="utf-8"))
    modify(config)
    config_path = tmp_path / "channels.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return config_path


def remove_x_caption_limit(config):
    del config["x"]["caption"]["max_chars"]


def zero_instagram_caption_limit(config):
    config["instagram"]["caption"]["max_chars"] = 0


def stretch_facebook_width(config):
    config["facebook"]["image"]["width"] = 1600


def garble_x_aspect_ratio(config):
    config["x"]["image"]["aspect_ratio"] = "16x9"


def add_unknown_field(config):
    config["instagram"]["caption"]["max_emojis"] = 3


def remove_facebook_style(config):
    del config["facebook"]["style"]


def unknown_x_length_counting(config):
    config["x"]["caption"]["length_counting"] = "graphemes"


@pytest.mark.parametrize(
    ("modify", "expected_fragments"),
    [
        (remove_x_caption_limit, ["x.caption.max_chars", "Field required"]),
        (zero_instagram_caption_limit, ["instagram.caption.max_chars", "greater than 0"]),
        (stretch_facebook_width, ["facebook.image", "1600x1024", "aspect_ratio 1:1"]),
        (garble_x_aspect_ratio, ["x.image.aspect_ratio", "'16x9'"]),
        (add_unknown_field, ["instagram.caption.max_emojis", "Extra inputs are not permitted"]),
        (remove_facebook_style, ["facebook.style", "Field required"]),
        (unknown_x_length_counting, ["x.caption.length_counting", "'characters' or 'x_weighted'"]),
    ],
)
def test_malformed_config_is_rejected_with_channel_and_field(tmp_path, modify, expected_fragments):
    config_path = write_modified_config(tmp_path, modify)

    with pytest.raises(ChannelConfigError) as raised:
        load_channel_specs(config_path)

    for fragment in expected_fragments:
        assert fragment in str(raised.value)


def test_missing_config_file_is_rejected(tmp_path):
    with pytest.raises(ChannelConfigError, match="not found"):
        load_channel_specs(tmp_path / "missing.json")


def test_invalid_json_is_rejected(tmp_path):
    config_path = tmp_path / "channels.json"
    config_path.write_text("{ not json", encoding="utf-8")

    with pytest.raises(ChannelConfigError, match="not valid JSON"):
        load_channel_specs(config_path)
