import io

import pytest
from PIL import Image

from app.channels import get_channel_specs
from app.headline_overlay import (
    HeadlineFonts,
    ensure_text_shaping_available,
    overlay_headline,
    script_runs,
    text_width,
    wrap_headline,
)
from tests.fakes import FAKE_IMAGE_COLOR, make_jpeg

SPECS = get_channel_specs()
HEADLINES = {
    "bengali": "শুভ নববর্ষ — লক্ষ্য পূরণের নতুন বছর",
    "english": "New year, new colours",
    "mixed": "Aarong-এ শুভ নববর্ষ ২০২৬!",
}
JPEG_NOISE_TOLERANCE = 12
MIN_BAND_DARKENING = 40


def test_libraqm_is_available_for_bengali_shaping():
    ensure_text_shaping_available()


@pytest.mark.parametrize("channel", list(SPECS))
@pytest.mark.parametrize("headline", list(HEADLINES.values()), ids=list(HEADLINES))
def test_overlay_keeps_the_exact_image_size(channel, headline):
    image = SPECS[channel].image

    result = overlay_headline(make_jpeg(image.width, image.height), headline)

    with Image.open(io.BytesIO(result)) as overlaid:
        assert overlaid.size == (image.width, image.height)
        assert overlaid.format == "JPEG"


def test_headline_is_drawn_on_a_band_at_the_bottom_only():
    image = SPECS["x"].image

    result = overlay_headline(make_jpeg(image.width, image.height), HEADLINES["english"])

    with Image.open(io.BytesIO(result)) as overlaid:
        top_pixel = overlaid.getpixel((0, 0))
        bottom_edge_pixel = overlaid.getpixel((0, image.height - 1))
    assert all(abs(got - original) <= JPEG_NOISE_TOLERANCE for got, original in zip(top_pixel, FAKE_IMAGE_COLOR))
    assert sum(FAKE_IMAGE_COLOR) - sum(bottom_edge_pixel) >= MIN_BAND_DARKENING


def test_script_runs_give_latin_and_bengali_their_own_fonts():
    assert script_runs(HEADLINES["mixed"]) == [(False, "Aarong-"), (True, "এ শুভ নববর্ষ ২০২৬"), (False, "!")]


def test_joiners_and_dandas_stay_in_the_bengali_run():
    text_with_zero_width_joiner_and_danda = "র‍্যাব। ঢাকা"

    assert script_runs(text_with_zero_width_joiner_and_danda) == [(True, text_with_zero_width_joiner_and_danda)]


def test_long_headlines_wrap_within_the_width():
    fonts = HeadlineFonts.at_size(60)
    max_width = 500

    lines = wrap_headline(HEADLINES["bengali"] + " " + HEADLINES["english"], fonts, max_width)

    assert len(lines) > 1
    assert all(text_width(line, fonts) <= max_width for line in lines)


def test_empty_headline_is_refused():
    with pytest.raises(ValueError, match="empty headline"):
        overlay_headline(make_jpeg(100, 100), "   ")
