import io
import random

import pytest
from PIL import Image

from app.channels import get_channel_specs
from app.headline_overlay import (
    BUSY_MIN_SCRIM_OPACITY,
    MIN_SCRIM_OPACITY,
    SAFE_MARGIN_TO_SHORT_SIDE,
    TARGET_CONTRAST_RATIO,
    HeadlineFonts,
    TextZone,
    allowed_text_zones,
    candidate_layouts,
    contrast_ratio,
    detect_faces,
    ensure_face_detection_available,
    ensure_text_shaping_available,
    overlay_headline,
    plan_headline,
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
NOISE_BLOCK_PIXELS = 16
NOISE_SEED = 7
LIGHT_WALL = (236, 230, 218)
DARK_SKY = (28, 34, 58)


def plain_image(width: int, height: int, color=FAKE_IMAGE_COLOR) -> Image.Image:
    return Image.new("RGBA", (width, height), (*color, 255))


def with_busy_area(image: Image.Image, box: tuple[int, int, int, int]) -> Image.Image:
    """Paste random black-and-white blocks into box, like foliage or embroidery at a glance."""
    left, top, right, bottom = box
    rng = random.Random(NOISE_SEED)
    columns, rows = (right - left) // NOISE_BLOCK_PIXELS + 1, (bottom - top) // NOISE_BLOCK_PIXELS + 1
    blocks = Image.new("L", (columns, rows))
    blocks.putdata([rng.choice((0, 255)) for _ in range(columns * rows)])
    noise = blocks.resize((columns * NOISE_BLOCK_PIXELS, rows * NOISE_BLOCK_PIXELS), Image.Resampling.NEAREST)
    busy = image.copy()
    busy.paste(noise.crop((0, 0, right - left, bottom - top)).convert("RGBA"), (left, top))
    return busy


def portrait() -> tuple[int, int]:
    return SPECS["instagram"].image.width, SPECS["instagram"].image.height


def landscape() -> tuple[int, int]:
    return SPECS["x"].image.width, SPECS["x"].image.height


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


def test_face_detection_is_available_and_finds_nothing_in_a_plain_image():
    ensure_face_detection_available()

    assert detect_faces(plain_image(*portrait())) == []


def test_wide_images_can_put_the_headline_beside_the_subject_tall_ones_only_above_or_below():
    assert set(allowed_text_zones(*landscape())) == set(TextZone)
    assert allowed_text_zones(*portrait()) == (TextZone.TOP, TextZone.BOTTOM)


def test_without_a_preference_the_headline_sits_at_the_bottom_and_leaves_the_top_untouched():
    width, height = landscape()

    plan = plan_headline(plain_image(width, height), HEADLINES["english"])
    result = overlay_headline(make_jpeg(width, height), HEADLINES["english"])

    assert plan.layout.zone == TextZone.BOTTOM
    with Image.open(io.BytesIO(result)) as overlaid:
        top_pixel = overlaid.getpixel((0, 0))
    assert all(abs(got - original) <= JPEG_NOISE_TOLERANCE for got, original in zip(top_pixel, FAKE_IMAGE_COLOR))


@pytest.mark.parametrize("zone", list(TextZone))
def test_the_zone_the_image_was_composed_for_is_used_when_it_is_calm(zone):
    plan = plan_headline(plain_image(*landscape()), HEADLINES["bengali"], preferred_zone=zone)

    assert plan.layout.zone == zone


def test_a_preferred_zone_that_came_out_busy_is_not_used():
    width, height = portrait()
    busy_top = with_busy_area(plain_image(width, height), (0, 0, width, height // 2))

    plan = plan_headline(busy_top, HEADLINES["english"], preferred_zone=TextZone.TOP)

    assert plan.layout.zone == TextZone.BOTTOM


def test_without_a_preference_the_calm_part_of_the_image_wins():
    width, height = portrait()
    busy_bottom = with_busy_area(plain_image(width, height), (0, height // 2, width, height))

    plan = plan_headline(busy_bottom, HEADLINES["english"])

    assert plan.layout.zone == TextZone.TOP


def test_the_headline_never_covers_a_face():
    width, height = portrait()
    face = (width // 3, height // 20, 2 * width // 3, height // 3)

    plan = plan_headline(plain_image(width, height), HEADLINES["bengali"], preferred_zone=TextZone.TOP, faces=[face])

    left, top, right, bottom = plan.layout.block
    assert plan.layout.zone == TextZone.BOTTOM
    assert right <= face[0] or left >= face[2] or bottom <= face[1] or top >= face[3]


def test_a_side_column_moves_up_or_down_to_clear_a_face():
    width, height = landscape()
    face_in_the_middle_of_the_left_column = (width // 20, 2 * height // 5, width // 3, 3 * height // 5)

    plan = plan_headline(
        plain_image(width, height),
        HEADLINES["english"],
        preferred_zone=TextZone.LEFT,
        faces=[face_in_the_middle_of_the_left_column],
    )

    assert plan.layout.zone == TextZone.LEFT
    _left, top, _right, bottom = plan.layout.block
    assert bottom <= face_in_the_middle_of_the_left_column[1] or top >= face_in_the_middle_of_the_left_column[3]


@pytest.mark.parametrize("channel", list(SPECS))
@pytest.mark.parametrize("headline", list(HEADLINES.values()), ids=list(HEADLINES))
def test_every_placement_stays_inside_the_safe_margin(channel, headline):
    width, height = SPECS[channel].image.width, SPECS[channel].image.height
    margin = round(min(width, height) * SAFE_MARGIN_TO_SHORT_SIDE)

    for layout in candidate_layouts(headline, width, height):
        left, top, right, bottom = layout.block
        assert left >= margin and top >= margin
        assert right <= width - margin and bottom <= height - margin


def test_a_calm_light_background_gets_dark_text_and_barely_any_scrim():
    plan = plan_headline(plain_image(*landscape(), color=LIGHT_WALL), HEADLINES["english"])

    assert not plan.colours.shadow
    assert contrast_ratio(plan.colours.text, LIGHT_WALL) >= TARGET_CONTRAST_RATIO
    assert plan.colours.scrim_opacity == MIN_SCRIM_OPACITY


def test_a_calm_dark_background_gets_light_text_and_barely_any_scrim():
    plan = plan_headline(plain_image(*landscape(), color=DARK_SKY), HEADLINES["english"])

    assert plan.colours.shadow
    assert contrast_ratio(plan.colours.text, DARK_SKY) >= TARGET_CONTRAST_RATIO
    assert plan.colours.scrim_opacity == MIN_SCRIM_OPACITY


def test_a_busy_background_gets_light_text_on_a_strong_scrim():
    width, height = landscape()
    busy = with_busy_area(plain_image(width, height), (0, 0, width, height))

    plan = plan_headline(busy, HEADLINES["english"])

    assert plan.colours.shadow
    assert plan.colours.scrim_opacity >= BUSY_MIN_SCRIM_OPACITY


@pytest.mark.parametrize("grey", [0, 64, 128, 170, 200, 255])
def test_the_headline_reaches_the_target_contrast_on_any_calm_tone(grey):
    colour = (grey, grey, grey)

    plan = plan_headline(plain_image(*landscape(), color=colour), HEADLINES["english"])

    opacity = plan.colours.scrim_opacity
    behind = tuple(c * (1 - opacity) + s * opacity for c, s in zip(colour, plan.colours.scrim))
    assert contrast_ratio(plan.colours.text, behind) >= TARGET_CONTRAST_RATIO


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


def test_wrapped_lines_are_balanced_instead_of_leaving_one_word_alone():
    """The live LinkedIn headline wrapped as 'Celebrate Pohela Boishakh with Heritage' / 'Wear'."""
    fonts = HeadlineFonts.at_size(60)
    headline = "Celebrate Pohela Boishakh with Heritage Wear"
    max_width = text_width("Celebrate Pohela Boishakh with Heritage", fonts) + 1

    lines = wrap_headline(headline, fonts, max_width)

    assert len(lines) == 2
    assert all(len(line.split()) >= 2 for line in lines)
    assert " ".join(lines) == headline
    assert all(text_width(line, fonts) <= max_width for line in lines)


def test_a_headline_that_fits_stays_on_one_line():
    fonts = HeadlineFonts.at_size(60)

    assert wrap_headline("New colours", fonts, 10_000) == ["New colours"]


def test_empty_headline_is_refused():
    with pytest.raises(ValueError, match="empty headline"):
        overlay_headline(make_jpeg(100, 100), "   ")
