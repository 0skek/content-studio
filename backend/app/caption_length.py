"""Caption length rules, shared by generation (milestone 2) and the channel adapters (milestone 4)."""

import unicodedata
from enum import StrEnum


class LengthCounting(StrEnum):
    CHARACTERS = "characters"
    X_WEIGHTED = "x_weighted"


# X's official weighting, from twitter-text config v3:
# https://github.com/twitter/twitter-text/blob/master/config/v3.json
# Code points in these ranges weigh 1. U+0000-U+10FF covers Latin *and* Bengali (U+0980-U+09FF).
# Everything else (emoji, CJK, ...) weighs 2. We count per code point, so multi-code-point emoji
# (e.g. with a variation selector) count slightly more than on X: conservative, never under-counts.
X_LIGHT_CODE_POINT_RANGES = (
    (0x0000, 0x10FF),
    (0x2000, 0x200D),
    (0x2010, 0x201F),
    (0x2032, 0x2037),
)
X_LIGHT_WEIGHT = 1
X_HEAVY_WEIGHT = 2

HASHTAG_PREFIX = "#"
HASHTAG_SEPARATOR = " "
CAPTION_HASHTAG_SEPARATOR = "\n\n"


def _x_weight(character: str) -> int:
    code_point = ord(character)
    if any(start <= code_point <= end for start, end in X_LIGHT_CODE_POINT_RANGES):
        return X_LIGHT_WEIGHT
    return X_HEAVY_WEIGHT


def caption_length(text: str, counting: LengthCounting) -> int:
    normalized = unicodedata.normalize("NFC", text)
    if counting == LengthCounting.X_WEIGHTED:
        return sum(_x_weight(character) for character in normalized)
    return len(normalized)


def hashtag_count(text: str) -> int:
    """Hashtags as the platform sees them: every word starting with '#', inline in the caption or appended."""
    return sum(1 for word in text.split() if word.startswith(HASHTAG_PREFIX) and len(word) > len(HASHTAG_PREFIX))


def published_text(caption: str, hashtags: list[str]) -> str:
    """The text a channel actually receives: the caption, then the hashtags. Limits apply to this."""
    if not hashtags:
        return caption
    hashtag_line = HASHTAG_SEPARATOR.join(f"{HASHTAG_PREFIX}{tag}" for tag in hashtags)
    return f"{caption}{CAPTION_HASHTAG_SEPARATOR}{hashtag_line}"
