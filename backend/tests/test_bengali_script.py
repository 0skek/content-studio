import pytest

from app.bengali_script import bengali_letter_share, is_bengali


def test_bengali_block_is_recognised():
    assert is_bengali("ক")
    assert is_bengali("১")
    assert not is_bengali("k")


@pytest.mark.parametrize(
    ("text", "share"),
    [
        ("শুভ নববর্ষ", 1.0),
        ("New year", 0.0),
        ("ক k", 0.5),
        ("123 !?", None),
        ("", None),
    ],
)
def test_bengali_letter_share(text, share):
    assert bengali_letter_share(text) == share
