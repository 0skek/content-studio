"""Draws a post's headline onto its generated image. The image is never resized or cropped.

Bengali needs libraqm shaping: Pillow's BASIC layout breaks conjuncts (র্ষ, ক্ষ্য) and misplaces vowel signs.
Noto Sans Bengali has no Latin glyphs and Pillow has no font fallback, so each headline is split into script
runs: Bengali characters use the Bengali font, everything else (brand names, digits, punctuation) uses Noto Sans.
"""

import io
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont, features

from app.config import BACKEND_DIR

FONTS_DIR = BACKEND_DIR / "assets" / "fonts"
BENGALI_FONT_PATH = FONTS_DIR / "NotoSansBengali-Bold.ttf"
LATIN_FONT_PATH = FONTS_DIR / "NotoSans-Bold.ttf"

BENGALI_BLOCK_FIRST = 0x0980
BENGALI_BLOCK_LAST = 0x09FF
# Dandas and zero-width (non-)joiners are used inside Bengali text and must stay in the Bengali run.
CHARACTERS_SHAPED_WITH_BENGALI = frozenset({"।", "॥", "‌", "‍"})

# Sizes are fractions of the image's shorter side, so all three channel sizes look consistent.
FONT_SIZE_TO_SHORT_SIDE = 0.075
MIN_FONT_SIZE_TO_SHORT_SIDE = 0.045
FONT_SIZE_STEP_PIXELS = 2
SIDE_MARGIN_TO_WIDTH = 0.06
LINE_GAP_TO_FONT_SIZE = 0.2
BAND_PADDING_TO_FONT_SIZE = 0.6
MAX_HEADLINE_LINES = 3
BAND_COLOR_RGBA = (0, 0, 0, 150)
TEXT_COLOR = (255, 255, 255)
JPEG_QUALITY = 90


class TextShapingUnavailable(RuntimeError):
    """Pillow was built without libraqm, so Bengali would render incorrectly."""


def ensure_text_shaping_available() -> None:
    if not features.check("raqm"):
        raise TextShapingUnavailable(
            "Pillow has no libraqm support, so Bengali headlines would render with broken conjuncts. "
            "Install libraqm (apt install libraqm0) and reinstall Pillow."
        )


@dataclass(frozen=True)
class HeadlineFonts:
    bengali: ImageFont.FreeTypeFont
    latin: ImageFont.FreeTypeFont

    @classmethod
    def at_size(cls, size: int) -> "HeadlineFonts":
        return cls(
            bengali=ImageFont.truetype(str(BENGALI_FONT_PATH), size, layout_engine=ImageFont.Layout.RAQM),
            latin=ImageFont.truetype(str(LATIN_FONT_PATH), size, layout_engine=ImageFont.Layout.RAQM),
        )

    @property
    def size(self) -> int:
        return self.bengali.size

    def font_for(self, is_bengali: bool) -> ImageFont.FreeTypeFont:
        return self.bengali if is_bengali else self.latin

    def ascent(self) -> int:
        return max(self.bengali.getmetrics()[0], self.latin.getmetrics()[0])

    def descent(self) -> int:
        return max(self.bengali.getmetrics()[1], self.latin.getmetrics()[1])


def _uses_bengali_font(character: str) -> bool:
    return BENGALI_BLOCK_FIRST <= ord(character) <= BENGALI_BLOCK_LAST or character in CHARACTERS_SHAPED_WITH_BENGALI


def script_runs(text: str) -> list[tuple[bool, str]]:
    """Split text into (is_bengali, run) pieces. Spaces join the run before them."""
    runs: list[tuple[bool, str]] = []
    for character in text:
        is_bengali = runs[-1][0] if (character.isspace() and runs) else _uses_bengali_font(character)
        if runs and runs[-1][0] == is_bengali:
            runs[-1] = (is_bengali, runs[-1][1] + character)
        else:
            runs.append((is_bengali, character))
    return runs


def text_width(text: str, fonts: HeadlineFonts) -> float:
    return sum(fonts.font_for(is_bengali).getlength(run) for is_bengali, run in script_runs(text))


def wrap_headline(headline: str, fonts: HeadlineFonts, max_width: float) -> list[str]:
    lines: list[str] = []
    current_line = ""
    for word in headline.split():
        candidate = f"{current_line} {word}" if current_line else word
        if current_line and text_width(candidate, fonts) > max_width:
            lines.append(current_line)
            current_line = word
        else:
            current_line = candidate
    if current_line:
        lines.append(current_line)
    return lines


def _fit_headline(headline: str, short_side: int, max_width: float) -> tuple[HeadlineFonts, list[str]]:
    """Largest font size (down to a minimum) at which the headline fits in MAX_HEADLINE_LINES lines."""
    size = round(short_side * FONT_SIZE_TO_SHORT_SIDE)
    min_size = round(short_side * MIN_FONT_SIZE_TO_SHORT_SIDE)
    while True:
        fonts = HeadlineFonts.at_size(size)
        lines = wrap_headline(headline, fonts, max_width)
        fits = len(lines) <= MAX_HEADLINE_LINES and all(text_width(line, fonts) <= max_width for line in lines)
        if fits or size <= min_size:
            return fonts, lines
        size -= FONT_SIZE_STEP_PIXELS


def overlay_headline(image_bytes: bytes, headline: str) -> bytes:
    """Return JPEG bytes of the same size with the headline centred on a translucent band at the bottom."""
    if not headline.strip():
        raise ValueError("Cannot overlay an empty headline")
    with Image.open(io.BytesIO(image_bytes)) as source:
        base = source.convert("RGBA")
    width, height = base.size

    max_text_width = width - 2 * round(width * SIDE_MARGIN_TO_WIDTH)
    fonts, lines = _fit_headline(headline, min(width, height), max_text_width)
    line_height = fonts.ascent() + fonts.descent()
    line_gap = round(fonts.size * LINE_GAP_TO_FONT_SIZE)
    padding = round(fonts.size * BAND_PADDING_TO_FONT_SIZE)
    block_height = len(lines) * line_height + (len(lines) - 1) * line_gap
    band_top = height - block_height - 2 * padding

    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    draw.rectangle((0, band_top, width, height), fill=BAND_COLOR_RGBA)
    baseline = band_top + padding + fonts.ascent()
    for line in lines:
        x = (width - text_width(line, fonts)) / 2
        for is_bengali, run in script_runs(line):
            font = fonts.font_for(is_bengali)
            draw.text((x, baseline), run, font=font, fill=TEXT_COLOR, anchor="ls")
            x += font.getlength(run)
        baseline += line_height + line_gap

    composed = Image.alpha_composite(base, layer).convert("RGB")
    if composed.size != (width, height):
        raise RuntimeError(f"Headline overlay changed the image size from {width}x{height} to {composed.size}")
    output = io.BytesIO()
    composed.save(output, format="JPEG", quality=JPEG_QUALITY)
    return output.getvalue()
