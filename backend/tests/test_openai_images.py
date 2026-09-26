"""OpenAIImageClient: exact-size requests and error messages, against a fake OpenAI client (no network)."""

import base64
from dataclasses import dataclass, field
from types import SimpleNamespace

import httpx
import openai
import pytest

from app.channels import get_channel_specs
from app.cloudflare_images import ImageGenerationError
from app.openai_images import OpenAIImageClient

IMAGE_BYTES = b"\xff\xd8 fake jpeg"
REQUEST = httpx.Request("POST", "https://api.openai.com/v1/images/generations")
SPECS = get_channel_specs()
# GPT Image size rules: sides are multiples of 16, ratio 1:3 to 3:1, and 655,360 to 8,294,400 pixels.
SIDE_MULTIPLE = 16
MIN_PIXELS = 655_360
MAX_PIXELS = 8_294_400
MAX_RATIO = 3


@dataclass
class FakeImages:
    outcome: object = None
    calls: list[dict] = field(default_factory=list)

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        if self.outcome is not None:
            return self.outcome
        return SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(IMAGE_BYTES).decode())])


def make_client(fake: FakeImages) -> OpenAIImageClient:
    return OpenAIImageClient(
        api_key="unused", model="image-model", quality="medium", timeout_seconds=1, client=SimpleNamespace(images=fake)
    )


@pytest.mark.parametrize("channel", list(SPECS))
def test_every_channel_size_is_one_gpt_image_accepts(channel):
    """Rule 1: each channel's exact size is requested directly, so it must be a size the model can produce."""
    width, height = SPECS[channel].image.width, SPECS[channel].image.height

    assert width % SIDE_MULTIPLE == 0 and height % SIDE_MULTIPLE == 0
    assert MIN_PIXELS <= width * height <= MAX_PIXELS
    assert max(width, height) / min(width, height) <= MAX_RATIO


def test_requests_the_exact_size_as_jpeg_and_returns_the_bytes():
    fake = FakeImages()

    image = make_client(fake).generate("a square scene", 1024, 1024)

    assert image == IMAGE_BYTES
    assert fake.calls == [
        {"model": "image-model", "prompt": "a square scene", "size": "1024x1024", "quality": "medium",
         "output_format": "jpeg", "n": 1}
    ]


def test_a_blocked_prompt_is_reported_with_openais_reason():
    body = {"message": "Your request was rejected by the safety system.", "code": "moderation_blocked"}
    blocked = openai.APIStatusError("blocked", response=httpx.Response(400, request=REQUEST), body=body)

    with pytest.raises(ImageGenerationError, match="HTTP 400.*rejected by the safety system"):
        make_client(FakeImages(outcome=blocked)).generate("scene", 1024, 1024)


def test_no_api_credit_says_how_to_fix_it():
    body = {"message": "You exceeded your current quota", "code": "insufficient_quota"}
    no_credit = openai.APIStatusError("quota", response=httpx.Response(429, request=REQUEST), body=body)

    with pytest.raises(ImageGenerationError, match="no API credit"):
        make_client(FakeImages(outcome=no_credit)).generate("scene", 1024, 1024)


def test_a_timeout_names_the_limit():
    with pytest.raises(ImageGenerationError, match="timed out after 1s"):
        make_client(FakeImages(outcome=openai.APITimeoutError(request=REQUEST))).generate("scene", 1024, 1024)


def test_an_empty_response_is_an_error():
    with pytest.raises(ImageGenerationError, match="no image"):
        make_client(FakeImages(outcome=SimpleNamespace(data=[]))).generate("scene", 1024, 1024)
