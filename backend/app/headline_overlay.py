"""Draws a post's headline onto its generated image so it reads as part of the photo. Never resizes or crops.

Placement: the scene writer asked the image model to keep one zone of the frame quiet (top, bottom, and for wide
images also left or right). The headline goes there unless that zone came out clearly busier than another one,
and never over a detected face.

Legibility: no box. A soft gradient, tinted from the photo's own colour behind the text, fades in from the image
edge and is only as strong as the target contrast needs. Calm light areas get dark text, everything else warm white
with a soft shadow. A short accent line above the headline takes the photo's most vivid colour.

Bengali needs libraqm shaping: Pillow's BASIC layout breaks conjuncts (র্ষ, ক্ষ্য) and misplaces vowel signs.
Noto Sans Bengali has no Latin glyphs and Pillow has no font fallback, so each headline is split into script
runs: Bengali characters use the Bengali font, everything else (brand names, digits, punctuation) uses Noto Sans.
"""

import colorsys
import functools
import io
import itertools
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageStat, features

from app.bengali_script import is_bengali
from app.config import BACKEND_DIR

FONTS_DIR = BACKEND_DIR / "assets" / "fonts"
BENGALI_FONT_PATH = FONTS_DIR / "NotoSansBengali-Bold.ttf"
LATIN_FONT_PATH = FONTS_DIR / "NotoSans-Bold.ttf"

# Dandas and zero-width (non-)joiners are used inside Bengali text and must stay in the Bengali run.
CHARACTERS_SHAPED_WITH_BENGALI = frozenset({"।", "॥", "‌", "‍"})

# Type. Sizes are fractions of the image's shorter side, so all three channel sizes look consistent.
FONT_SIZE_TO_SHORT_SIDE = 0.075
MIN_FONT_SIZE_TO_SHORT_SIDE = 0.045
FONT_SIZE_STEP_PIXELS = 2
LINE_GAP_TO_FONT_SIZE = 0.12
EDGE_ZONE_MAX_LINES = 3
SIDE_ZONE_MAX_LINES = 4
# Balancing tries every set of line breaks; headlines are capped at a few words, so this bound is never hit.
MAX_WORDS_TO_BALANCE = 16

# Layout. The safe margin keeps text off the frame edge on every platform (6-8% is the usual safe area).
SAFE_MARGIN_TO_SHORT_SIDE = 0.07
SIDE_ZONE_WIDTH_FRACTION = 0.46
ACCENT_WIDTH_TO_FONT_SIZE = 1.8
ACCENT_HEIGHT_TO_FONT_SIZE = 0.13
ACCENT_GAP_TO_FONT_SIZE = 0.45

# Choosing where the headline goes. Busyness is the mean edge strength behind the text block (0-255 scale).
ANALYSIS_LONG_SIDE_PIXELS = 256
CALM_EDGE_STRENGTH = 10.0
BUSY_EDGE_STRENGTH = 28.0
PREFERRED_ZONE_TOLERANCE = 1.6

# Faces. OpenCV's Haar detectors return a tight box; hair, forehead and chin extend past it.
FRONTAL_FACE_CASCADE = "haarcascade_frontalface_default.xml"
PROFILE_FACE_CASCADE = "haarcascade_profileface.xml"
FACE_MIN_SIZE_TO_SHORT_SIDE = 0.05
FACE_SCALE_FACTOR = 1.1
FACE_MIN_NEIGHBOURS = 6
FACE_BOX_GROWTH = 0.3

# Legibility. Contrast ratios follow WCAG; 3:1 is its bar for large text, and the scrim tops that up.
TARGET_CONTRAST_RATIO = 3.2
MIN_SCRIM_OPACITY = 0.18
MAX_SCRIM_OPACITY = 0.8
BUSY_MIN_SCRIM_OPACITY = 0.62
SCRIM_OPACITY_STEP = 0.02
SCRIM_FADE_TO_FONT_SIZE = 5.0
SCRIM_PADDING_TO_FONT_SIZE = 0.9
BRIGHT_PERCENTILE = 0.9
DARK_PERCENTILE = 0.1
MAX_EDGE_STRENGTH_FOR_DARK_TEXT = 12.0
SHADE_FACTOR = 0.22  # dark scrim: the local colour at 22% brightness
INK_FACTOR = 0.16  # dark text: the local colour at 16% brightness
PALE_BLEND_TO_WHITE = 0.7  # light scrim: the local colour, 70% of the way to white
LIGHT_TEXT_COLOR = (252, 250, 245)
SHADOW_OPACITY = 0.6
SHADOW_BLUR_TO_FONT_SIZE = 0.10
SHADOW_OFFSET_TO_FONT_SIZE = 0.04

# Accent colour: the most vivid of a few palette colours, if it stands out from what is behind the text.
PALETTE_SAMPLE_SIDE_PIXELS = 96
PALETTE_COLOURS = 8
MIN_ACCENT_SATURATION = 0.35
MIN_ACCENT_BRIGHTNESS = 0.45
MIN_ACCENT_CONTRAST_RATIO = 1.5

JPEG_QUALITY = 90

RGB = tuple[int, int, int]
Box = tuple[int, int, int, int]  # left, top, right, bottom


class TextShapingUnavailable(RuntimeError):
    """Pillow was built without libraqm, so Bengali would render incorrectly."""


class FaceDetectionUnavailable(RuntimeError):
    """OpenCV's face detector files are missing."""


class TextZone(StrEnum):
    TOP = "top"
    BOTTOM = "bottom"
    LEFT = "left"
    RIGHT = "right"


DEFAULT_TEXT_ZONE = TextZone.BOTTOM
EDGE_ZONES = (TextZone.TOP, TextZone.BOTTOM)


def allowed_text_zones(width: int, height: int) -> tuple[TextZone, ...]:
    """Tall and square images have room above or below the subject; wide ones also beside it."""
    if width > height:
        return (TextZone.LEFT, TextZone.RIGHT, TextZone.TOP, TextZone.BOTTOM)
    return EDGE_ZONES


def ensure_text_shaping_available() -> None:
    if not features.check("raqm"):
        raise TextShapingUnavailable(
            "Pillow has no libraqm support, so Bengali headlines would render with broken conjuncts. "
            "Install libraqm (apt install libraqm0) and reinstall Pillow."
        )


# ---------------------------------------------------------------- fonts and wrapping


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
    return is_bengali(character) or character in CHARACTERS_SHAPED_WITH_BENGALI


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


def _greedy_lines(words: list[str], fonts: HeadlineFonts, max_width: float) -> list[str]:
    lines: list[str] = []
    current_line = ""
    for word in words:
        candidate = f"{current_line} {word}" if current_line else word
        if current_line and text_width(candidate, fonts) > max_width:
            lines.append(current_line)
            current_line = word
        else:
            current_line = candidate
    if current_line:
        lines.append(current_line)
    return lines


def wrap_headline(headline: str, fonts: HeadlineFonts, max_width: float) -> list[str]:
    """Wrap into as few lines as greedy filling needs, then balance them so no word is left alone at the end.

    Among every way to break the words into that many lines, pick the one whose widest line is narrowest.
    The greedy result is one of the candidates, so balancing never makes the headline fit worse.
    """
    words = headline.split()
    greedy = _greedy_lines(words, fonts, max_width)
    if len(greedy) <= 1 or len(words) > MAX_WORDS_TO_BALANCE:
        return greedy
    best_lines, best_width = greedy, max(text_width(line, fonts) for line in greedy)
    for breaks in itertools.combinations(range(1, len(words)), len(greedy) - 1):
        bounds = zip((0, *breaks), (*breaks, len(words)))
        lines = [" ".join(words[start:end]) for start, end in bounds]
        widest = max(text_width(line, fonts) for line in lines)
        if widest < best_width:
            best_lines, best_width = lines, widest
    return best_lines


def _fit_headline(
    headline: str, short_side: int, max_width: float, max_lines: int
) -> tuple[HeadlineFonts, list[str]]:
    """Largest font size (down to a minimum) at which the headline fits in max_lines lines."""
    size = round(short_side * FONT_SIZE_TO_SHORT_SIDE)
    min_size = round(short_side * MIN_FONT_SIZE_TO_SHORT_SIDE)
    while True:
        fonts = HeadlineFonts.at_size(size)
        lines = wrap_headline(headline, fonts, max_width)
        fits = len(lines) <= max_lines and all(text_width(line, fonts) <= max_width for line in lines)
        if fits or size <= min_size:
            return fonts, lines
        size -= FONT_SIZE_STEP_PIXELS


# ---------------------------------------------------------------- where the headline goes


@dataclass(frozen=True)
class HeadlineLayout:
    zone: TextZone
    fonts: HeadlineFonts
    lines: tuple[str, ...]
    block: Box  # the accent line plus the text, in image pixels
    centred: bool

    @property
    def line_height(self) -> int:
        return self.fonts.ascent() + self.fonts.descent()

    @property
    def line_gap(self) -> int:
        return round(self.fonts.size * LINE_GAP_TO_FONT_SIZE)

    @property
    def accent_height(self) -> int:
        return max(1, round(self.fonts.size * ACCENT_HEIGHT_TO_FONT_SIZE))

    @property
    def accent_gap(self) -> int:
        return round(self.fonts.size * ACCENT_GAP_TO_FONT_SIZE)


def candidate_layouts(headline: str, width: int, height: int) -> list[HeadlineLayout]:
    """Every place the headline may go: centred at the top or bottom; for wide images also in the left or right
    column, upper, middle or lower. Each is fitted to its own space."""
    short_side = min(width, height)
    margin = round(short_side * SAFE_MARGIN_TO_SHORT_SIDE)
    layouts = []
    for zone in allowed_text_zones(width, height):
        is_edge_zone = zone in EDGE_ZONES
        max_width = (width if is_edge_zone else round(width * SIDE_ZONE_WIDTH_FRACTION)) - 2 * margin
        max_lines = EDGE_ZONE_MAX_LINES if is_edge_zone else SIDE_ZONE_MAX_LINES
        fonts, lines = _fit_headline(headline, short_side, max_width, max_lines)
        block_width = round(max(text_width(line, fonts) for line in lines))
        line_height = fonts.ascent() + fonts.descent()
        block_height = (
            max(1, round(fonts.size * ACCENT_HEIGHT_TO_FONT_SIZE))
            + round(fonts.size * ACCENT_GAP_TO_FONT_SIZE)
            + len(lines) * line_height
            + (len(lines) - 1) * round(fonts.size * LINE_GAP_TO_FONT_SIZE)
        )
        middle, lower, upper = (height - block_height) // 2, height - margin - block_height, margin
        if zone == TextZone.TOP:
            origins = [((width - block_width) // 2, upper)]
        elif zone == TextZone.BOTTOM:
            origins = [((width - block_width) // 2, lower)]
        else:
            left = margin if zone == TextZone.LEFT else width - margin - block_width
            origins = [(left, top) for top in (middle, lower, upper)]
        layouts.extend(
            HeadlineLayout(
                zone=zone,
                fonts=fonts,
                lines=tuple(lines),
                block=(left, top, left + block_width, top + block_height),
                centred=is_edge_zone,
            )
            for left, top in origins
        )
    return layouts


class EdgeMap:
    """Edge strength of a small grey copy of the image, for judging how busy any part of it is."""

    def __init__(self, image: Image.Image) -> None:
        self.scale = ANALYSIS_LONG_SIDE_PIXELS / max(image.size)
        small_size = (max(1, round(image.width * self.scale)), max(1, round(image.height * self.scale)))
        self.edges = image.convert("L").resize(small_size).filter(ImageFilter.FIND_EDGES)

    def busyness(self, box: Box) -> float:
        left, top, right, bottom = (round(value * self.scale) for value in box)
        region = self.edges.crop((left, top, max(right, left + 1), max(bottom, top + 1)))
        return ImageStat.Stat(region).mean[0]


def _overlap_area(box: Box, others: Sequence[Box]) -> int:
    left, top, right, bottom = box
    return sum(
        max(0, min(right, other[2]) - max(left, other[0])) * max(0, min(bottom, other[3]) - max(top, other[1]))
        for other in others
    )


def choose_layout(
    image: Image.Image, headline: str, preferred_zone: TextZone | None, faces: Sequence[Box], edges: EdgeMap
) -> HeadlineLayout:
    """The preferred zone (the one the image was composed to keep quiet) wins if it is calm, or not much busier
    than the calmest option. A layout over a face is used only if every option covers a face, and then the one
    covering the least."""
    layouts = candidate_layouts(headline, *image.size)
    face_overlap = [_overlap_area(layout.block, faces) for layout in layouts]
    least_overlap = min(face_overlap)
    scored = [
        (edges.busyness(layout.block), layout)
        for layout, overlap in zip(layouts, face_overlap)
        if overlap == least_overlap
    ]
    calmest_busyness, calmest = min(scored, key=lambda item: item[0])

    preferred = preferred_zone if preferred_zone in allowed_text_zones(*image.size) else DEFAULT_TEXT_ZONE
    in_preferred_zone = [item for item in scored if item[1].zone == preferred]
    if in_preferred_zone:
        preferred_busyness, best_preferred = min(in_preferred_zone, key=lambda item: item[0])
        if preferred_busyness <= max(calmest_busyness * PREFERRED_ZONE_TOLERANCE, CALM_EDGE_STRENGTH):
            return best_preferred
    return calmest


# ---------------------------------------------------------------- faces


_face_detection_lock = threading.Lock()


@functools.cache
def _face_detector(filename: str) -> cv2.CascadeClassifier:
    path = Path(cv2.data.haarcascades) / filename
    detector = cv2.CascadeClassifier(str(path))
    if detector.empty():
        raise FaceDetectionUnavailable(f"OpenCV could not load its face detector {path}")
    return detector


def ensure_face_detection_available() -> None:
    _face_detector(FRONTAL_FACE_CASCADE)
    _face_detector(PROFILE_FACE_CASCADE)


def detect_faces(image: Image.Image) -> list[Box]:
    """Boxes around faces, grown to cover hair and chin. The profile detector finds faces turned one way only,
    so it also runs on the mirrored image."""
    grey = np.asarray(image.convert("L"))
    mirrored = np.ascontiguousarray(np.fliplr(grey))
    min_side = max(1, round(min(image.size) * FACE_MIN_SIZE_TO_SHORT_SIDE))
    detect_options = {
        "scaleFactor": FACE_SCALE_FACTOR,
        "minNeighbors": FACE_MIN_NEIGHBOURS,
        "minSize": (min_side, min_side),
    }
    found: list[tuple[int, int, int, int]] = []
    # Sharing one detector between the parallel channel jobs is not documented as thread-safe.
    with _face_detection_lock:
        frontal, profile = _face_detector(FRONTAL_FACE_CASCADE), _face_detector(PROFILE_FACE_CASCADE)
        found.extend(tuple(box) for box in frontal.detectMultiScale(grey, **detect_options))
        found.extend(tuple(box) for box in profile.detectMultiScale(grey, **detect_options))
        found.extend(
            (image.width - x - w, y, w, h) for x, y, w, h in profile.detectMultiScale(mirrored, **detect_options)
        )
    boxes = []
    for x, y, w, h in found:
        growth = round(max(w, h) * FACE_BOX_GROWTH)
        boxes.append((int(x) - growth, int(y) - growth, int(x + w) + growth, int(y + h) + growth))
    return boxes


# ---------------------------------------------------------------- colour and contrast


def _linear(channel: float) -> float:
    value = channel / 255
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def relative_luminance(colour: Sequence[float]) -> float:
    red, green, blue = (_linear(channel) for channel in colour[:3])
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(first: Sequence[float], second: Sequence[float]) -> float:
    lighter, darker = sorted((relative_luminance(first), relative_luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _blend(colour: Sequence[float], over: Sequence[float], opacity: float) -> RGB:
    red, green, blue = (round(base * (1 - opacity) + top * opacity) for base, top in zip(colour, over))
    return red, green, blue


def _percentile(histogram: list[int], fraction: float) -> int:
    target, running = sum(histogram) * fraction, 0
    for value, count in enumerate(histogram):
        running += count
        if running >= target:
            return value
    return len(histogram) - 1


def _opacity_for_contrast(worst_grey: int, scrim: RGB, text: RGB) -> float:
    """Smallest scrim opacity at which the text reaches the target contrast over the worst background tone."""
    worst = (worst_grey, worst_grey, worst_grey)
    steps = round(MAX_SCRIM_OPACITY / SCRIM_OPACITY_STEP)
    for step in range(steps + 1):
        opacity = step * SCRIM_OPACITY_STEP
        if contrast_ratio(text, _blend(worst, scrim, opacity)) >= TARGET_CONTRAST_RATIO:
            return opacity
    return MAX_SCRIM_OPACITY


def _accent_colour(image: Image.Image, background: RGB, fallback: RGB) -> RGB:
    sample = image.convert("RGB").resize((PALETTE_SAMPLE_SIDE_PIXELS, PALETTE_SAMPLE_SIDE_PIXELS))
    palette = sample.quantize(PALETTE_COLOURS).convert("RGB").getcolors(PALETTE_SAMPLE_SIDE_PIXELS**2) or []
    best, best_score = fallback, 0.0
    for count, colour in palette:
        _hue, saturation, brightness = colorsys.rgb_to_hsv(*(channel / 255 for channel in colour))
        vivid = saturation >= MIN_ACCENT_SATURATION and brightness >= MIN_ACCENT_BRIGHTNESS
        if not vivid or contrast_ratio(colour, background) < MIN_ACCENT_CONTRAST_RATIO:
            continue
        score = saturation * brightness * count**0.5
        if score > best_score:
            best, best_score = colour, score
    return best


@dataclass(frozen=True)
class HeadlineColours:
    text: RGB
    scrim: RGB
    scrim_opacity: float
    accent: RGB
    shadow: bool


def choose_colours(image: Image.Image, layout: HeadlineLayout, edges: EdgeMap) -> HeadlineColours:
    """Light or dark text, whichever needs less scrim; busy backgrounds always get a solid scrim."""
    behind = image.convert("RGB").crop(layout.block)
    local = tuple(round(channel) for channel in ImageStat.Stat(behind).mean)
    histogram = behind.convert("L").histogram()
    busyness = edges.busyness(layout.block)
    busy_share = min(max((busyness - CALM_EDGE_STRENGTH) / (BUSY_EDGE_STRENGTH - CALM_EDGE_STRENGTH), 0.0), 1.0)
    busy_floor = BUSY_MIN_SCRIM_OPACITY * busy_share

    shade = tuple(round(channel * SHADE_FACTOR) for channel in local)
    brightest = _percentile(histogram, BRIGHT_PERCENTILE)
    text, scrim = LIGHT_TEXT_COLOR, shade
    opacity = max(_opacity_for_contrast(brightest, shade, LIGHT_TEXT_COLOR), busy_floor)
    if busyness <= MAX_EDGE_STRENGTH_FOR_DARK_TEXT:
        ink = tuple(round(channel * INK_FACTOR) for channel in local)
        pale = _blend(local, (255, 255, 255), PALE_BLEND_TO_WHITE)
        darkest = _percentile(histogram, DARK_PERCENTILE)
        dark_opacity = max(_opacity_for_contrast(darkest, pale, ink), busy_floor)
        if dark_opacity < opacity:
            text, scrim, opacity = ink, pale, dark_opacity
    opacity = max(opacity, MIN_SCRIM_OPACITY)
    background = _blend(local, scrim, opacity)
    return HeadlineColours(
        text=text,
        scrim=scrim,
        scrim_opacity=opacity,
        accent=_accent_colour(image, background, fallback=text),
        shadow=text == LIGHT_TEXT_COLOR,
    )


# ---------------------------------------------------------------- drawing


def _smoothstep(value: float) -> float:
    clamped = min(max(value, 0.0), 1.0)
    return clamped * clamped * (3 - 2 * clamped)


def _profile(length: int, solid_start: int, solid_end: int, fade: float, peak: int) -> list[int]:
    """Peak between solid_start and solid_end, easing to zero over `fade` pixels on either side."""
    values = []
    for position in range(length):
        distance = max(solid_start - position, position - solid_end, 0)
        values.append(round(peak * (1 - _smoothstep(distance / fade))))
    return values


def _strip(values: list[int], horizontal: bool) -> Image.Image:
    strip = Image.new("L", (len(values), 1) if horizontal else (1, len(values)))
    strip.putdata(values)
    return strip


def _scrim_mask(size: tuple[int, int], layout: HeadlineLayout, opacity: float) -> Image.Image:
    """Full strength from the image edge through the text, then fading into the photo. A side column also fades
    above and below the text, so it reads as light falling off rather than a panel."""
    width, height = size
    padding = round(layout.fonts.size * SCRIM_PADDING_TO_FONT_SIZE)
    fade = layout.fonts.size * SCRIM_FADE_TO_FONT_SIZE
    peak = round(255 * opacity)
    left, top, right, bottom = layout.block
    if layout.zone == TextZone.TOP:
        return _strip(_profile(height, 0, bottom + padding, fade, peak), horizontal=False).resize(size)
    if layout.zone == TextZone.BOTTOM:
        return _strip(_profile(height, top - padding, height, fade, peak), horizontal=False).resize(size)
    across = _strip(_profile(height, top - padding, bottom + padding, fade, 255), horizontal=False).resize(size)
    if layout.zone == TextZone.LEFT:
        along = _profile(width, 0, right + padding, fade, peak)
    else:
        along = _profile(width, left - padding, width, fade, peak)
    return ImageChops.multiply(_strip(along, horizontal=True).resize(size), across)


def _draw_headline(base: Image.Image, layout: HeadlineLayout, colours: HeadlineColours) -> Image.Image:
    scrim = Image.new("RGBA", base.size, (*colours.scrim, 0))
    scrim.putalpha(_scrim_mask(base.size, layout, colours.scrim_opacity))
    composed = Image.alpha_composite(base, scrim)

    width = base.width
    left, top, _right, _bottom = layout.block
    text_layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    glyph_mask = Image.new("L", base.size, 0)
    draw, mask_draw = ImageDraw.Draw(text_layer), ImageDraw.Draw(glyph_mask)

    accent_width = round(layout.fonts.size * ACCENT_WIDTH_TO_FONT_SIZE)
    accent_left = (width - accent_width) // 2 if layout.centred else left
    draw.rectangle(
        (accent_left, top, accent_left + accent_width, top + layout.accent_height), fill=(*colours.accent, 255)
    )
    baseline = top + layout.accent_height + layout.accent_gap + layout.fonts.ascent()
    for line in layout.lines:
        x = (width - text_width(line, layout.fonts)) / 2 if layout.centred else left
        for is_bengali, run in script_runs(line):
            font = layout.fonts.font_for(is_bengali)
            draw.text((x, baseline), run, font=font, fill=(*colours.text, 255), anchor="ls")
            mask_draw.text((x, baseline), run, font=font, fill=255, anchor="ls")
            x += font.getlength(run)
        baseline += layout.line_height + layout.line_gap

    if colours.shadow:
        blurred = glyph_mask.filter(ImageFilter.GaussianBlur(layout.fonts.size * SHADOW_BLUR_TO_FONT_SIZE))
        shadow_alpha = Image.new("L", base.size, 0)
        offset = round(layout.fonts.size * SHADOW_OFFSET_TO_FONT_SIZE)
        shadow_alpha.paste(blurred.point(lambda alpha: round(alpha * SHADOW_OPACITY)), (0, offset))
        shadow = Image.new("RGBA", base.size, (0, 0, 0, 0))
        shadow.putalpha(shadow_alpha)
        composed = Image.alpha_composite(composed, shadow)
    return Image.alpha_composite(composed, text_layer)


@dataclass(frozen=True)
class HeadlinePlan:
    layout: HeadlineLayout
    colours: HeadlineColours


def plan_headline(
    image: Image.Image, headline: str, preferred_zone: TextZone | None = None, faces: Sequence[Box] = ()
) -> HeadlinePlan:
    edges = EdgeMap(image)
    layout = choose_layout(image, headline, preferred_zone, faces, edges)
    return HeadlinePlan(layout=layout, colours=choose_colours(image, layout, edges))


def overlay_headline(image_bytes: bytes, headline: str, preferred_zone: TextZone | None = None) -> bytes:
    """Return JPEG bytes of the same size with the headline set into the photo."""
    if not headline.strip():
        raise ValueError("Cannot overlay an empty headline")
    with Image.open(io.BytesIO(image_bytes)) as source:
        base = source.convert("RGBA")
    width, height = base.size

    plan = plan_headline(base, headline, preferred_zone, faces=detect_faces(base))
    composed = _draw_headline(base, plan.layout, plan.colours).convert("RGB")
    if composed.size != (width, height):
        raise RuntimeError(f"Headline overlay changed the image size from {width}x{height} to {composed.size}")
    output = io.BytesIO()
    composed.save(output, format="JPEG", quality=JPEG_QUALITY)
    return output.getvalue()
