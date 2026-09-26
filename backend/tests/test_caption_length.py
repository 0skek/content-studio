import pytest

from app.caption_length import LengthCounting, caption_length, published_text
from app.channels import get_channel_specs

BENGALI = "শুভ নববর্ষ"


@pytest.mark.parametrize(
    ("text", "characters", "x_weighted"),
    [
        ("Hello", 5, 5),
        (BENGALI, len(BENGALI), len(BENGALI)),
        ("🎉", 1, 2),
        ("你好", 2, 4),
        ("“quoted”", 8, 8),
    ],
    ids=["latin", "bengali", "emoji", "cjk", "curly-quotes"],
)
def test_counting_modes(text, characters, x_weighted):
    assert caption_length(text, LengthCounting.CHARACTERS) == characters
    assert caption_length(text, LengthCounting.X_WEIGHTED) == x_weighted


def test_bengali_gets_the_full_280_on_x():
    assert caption_length("ক" * 280, LengthCounting.X_WEIGHTED) == 280


def test_text_is_nfc_normalized_before_counting():
    decomposed_e_acute = "é"

    assert caption_length(decomposed_e_acute, LengthCounting.CHARACTERS) == 1


def test_published_text_puts_hashtags_after_the_caption():
    assert published_text("Hi", ["a", "b"]) == "Hi\n\n#a #b"
    assert published_text("Hi", []) == "Hi"


def test_hashtags_count_towards_the_limit():
    assert caption_length(published_text("Hi", ["tag"]), LengthCounting.CHARACTERS) == len("Hi\n\n#tag")


def test_x_uses_weighted_counting_and_the_others_count_characters():
    specs = get_channel_specs()

    assert specs["x"].caption.length_counting == LengthCounting.X_WEIGHTED
    assert specs["instagram"].caption.length_counting == LengthCounting.CHARACTERS
    assert specs["facebook"].caption.length_counting == LengthCounting.CHARACTERS
