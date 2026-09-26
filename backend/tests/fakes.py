"""Fake Gemini and Cloudflare clients: no network, and every call is recorded for assertions."""

import io
import threading
from dataclasses import dataclass, field

from PIL import Image

from app.models import Language
from app.prompts import BENGALI_COPY_OPENING, ChannelCopy, ChannelScene, CopySet, SceneSet

FAKE_IMAGE_COLOR = (40, 90, 160)
FAKE_TEXT_ZONE = "top"


def fake_scene(channel: str) -> str:
    return f"A distinct {channel} scene"


def make_jpeg(width: int, height: int, color: tuple[int, int, int] = FAKE_IMAGE_COLOR) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (width, height), color).save(output, format="JPEG")
    return output.getvalue()


def copy_language_of(prompt: str) -> Language:
    return Language.BENGALI if BENGALI_COPY_OPENING in prompt else Language.ENGLISH


def default_copy(language: Language, channel: str) -> ChannelCopy:
    if language == Language.BENGALI:
        return ChannelCopy(
            channel=channel,
            headline="নতুন বছরের নতুন সাজ",
            caption=f"বৈশাখের রঙে সাজুন, আমাদের নতুন সংগ্রহ দেখে যান ({channel})",
            hashtags=["পহেলাবৈশাখ"],
        )
    return ChannelCopy(
        channel=channel,
        headline="New year, new colours",
        caption=f"Celebrate Boishakh in colour and visit our new collection ({channel})",
        hashtags=["PohelaBoishakh"],
    )


@dataclass(frozen=True)
class TextCall:
    prompt: str
    schema: type


@dataclass
class FakeTextClient:
    channels: list[str]
    # (language, channel) -> the copy to return on attempt 1, 2, ... (the last one repeats).
    copy_versions: dict[tuple[Language, str], list[ChannelCopy]] = field(default_factory=dict)
    scene_error: Exception | None = None
    # channel -> the headline zone the scene writer picks (FAKE_TEXT_ZONE if not listed).
    scene_zones: dict[str, str] = field(default_factory=dict)
    copy_errors: dict[Language, Exception] = field(default_factory=dict)
    calls: list[TextCall] = field(default_factory=list)
    _copy_attempts: dict[Language, int] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def generate(self, prompt, schema):
        with self._lock:
            self.calls.append(TextCall(prompt, schema))
        if schema is SceneSet:
            if self.scene_error:
                raise self.scene_error
            return SceneSet(
                scenes=[
                    ChannelScene(channel=c, text_zone=self.scene_zones.get(c, FAKE_TEXT_ZONE), scene=fake_scene(c))
                    for c in self.channels
                ]
            )

        language = copy_language_of(prompt)
        if language in self.copy_errors:
            raise self.copy_errors[language]
        with self._lock:
            attempt = self._copy_attempts.get(language, 0)
            self._copy_attempts[language] = attempt + 1
        posts = []
        for channel in self.channels:
            versions = self.copy_versions.get((language, channel))
            posts.append(versions[min(attempt, len(versions) - 1)] if versions else default_copy(language, channel))
        return CopySet(posts=posts)

    def copy_calls(self, language: Language) -> list[TextCall]:
        return [call for call in self.calls if call.schema is CopySet and copy_language_of(call.prompt) == language]


@dataclass(frozen=True)
class ImageCall:
    prompt: str
    width: int
    height: int


@dataclass
class FakeImageClient:
    # requested (width, height) -> (width, height) actually returned, to simulate a misbehaving service.
    returned_sizes: dict[tuple[int, int], tuple[int, int]] = field(default_factory=dict)
    # requested (width, height) -> error to raise instead.
    errors: dict[tuple[int, int], Exception] = field(default_factory=dict)
    calls: list[ImageCall] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def generate(self, prompt: str, width: int, height: int) -> bytes:
        with self._lock:
            self.calls.append(ImageCall(prompt, width, height))
        if (width, height) in self.errors:
            raise self.errors[(width, height)]
        return make_jpeg(*self.returned_sizes.get((width, height), (width, height)))
