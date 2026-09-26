"""GeminiImageClient: aspect-ratio choice, model fallback and error messages, against a fake google-genai client."""

from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest
from google.genai import errors

from app.channels import get_channel_specs
from app.cloudflare_images import ImageGenerationError
from app.gemini_images import GeminiImageClient, closest_aspect_ratio

PRIMARY_MODEL = "image-primary"
FALLBACK_MODEL = "image-fallback"
IMAGE_BYTES = b"\xff\xd8 fake jpeg"
SPECS = get_channel_specs()


def api_error(code: int, status: str) -> errors.APIError:
    error_class = errors.ServerError if code >= 500 else errors.ClientError
    return error_class(code, {"error": {"code": code, "message": status.lower(), "status": status}})


def image_response(data: bytes = IMAGE_BYTES):
    part = SimpleNamespace(inline_data=SimpleNamespace(data=data, mime_type="image/png"))
    return SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]), finish_reason="STOP")])


@dataclass
class FakeModels:
    # model name -> exception to raise, or a response to return instead of the image.
    outcomes: dict[str, object] = field(default_factory=dict)
    calls: list[tuple[str, str, str]] = field(default_factory=list)

    def generate_content(self, model, contents, config):
        self.calls.append((model, config.image_config.aspect_ratio, config.image_config.image_size))
        outcome = self.outcomes.get(model)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome or image_response()


def make_client(fake_models: FakeModels) -> GeminiImageClient:
    return GeminiImageClient(
        api_key="unused",
        models=[PRIMARY_MODEL, FALLBACK_MODEL],
        image_size="1K",
        timeout_seconds=1,
        client=SimpleNamespace(models=fake_models),
    )


@pytest.mark.parametrize(("channel", "ratio"), [("instagram", "4:5"), ("facebook", "1:1"), ("x", "16:9")])
def test_each_channel_asks_for_its_own_native_ratio(channel, ratio):
    """Rule 1: every channel's size maps to its own ratio, so each image is generated for its channel."""
    image = SPECS[channel].image

    assert closest_aspect_ratio(image.width, image.height) == ratio


def test_the_three_channels_ask_for_three_different_ratios():
    ratios = {closest_aspect_ratio(spec.image.width, spec.image.height) for spec in SPECS.values()}

    assert len(ratios) == len(SPECS)


def test_returns_the_image_bytes_at_the_requested_ratio_and_tier():
    fake_models = FakeModels()

    image = make_client(fake_models).generate("a square scene", 1024, 1024)

    assert image == IMAGE_BYTES
    assert fake_models.calls == [(PRIMARY_MODEL, "1:1", "1K")]


@pytest.mark.parametrize(("code", "status"), [(503, "UNAVAILABLE"), (429, "RESOURCE_EXHAUSTED"), (404, "NOT_FOUND")])
def test_an_unavailable_model_falls_back_to_the_next(code, status):
    fake_models = FakeModels(outcomes={PRIMARY_MODEL: api_error(code, status)})

    assert make_client(fake_models).generate("scene", 1024, 1024) == IMAGE_BYTES
    assert [model for model, _, _ in fake_models.calls] == [PRIMARY_MODEL, FALLBACK_MODEL]


def test_a_bad_request_fails_at_once_with_the_reason():
    fake_models = FakeModels(outcomes={PRIMARY_MODEL: api_error(400, "INVALID_ARGUMENT")})

    with pytest.raises(ImageGenerationError, match="HTTP 400"):
        make_client(fake_models).generate("scene", 1024, 1024)
    assert len(fake_models.calls) == 1


def test_all_models_rate_limited_explains_that_billing_is_needed():
    quota = api_error(429, "RESOURCE_EXHAUSTED")
    fake_models = FakeModels(outcomes={PRIMARY_MODEL: quota, FALLBACK_MODEL: quota})

    with pytest.raises(ImageGenerationError, match="billing must be enabled"):
        make_client(fake_models).generate("scene", 1024, 1024)


def test_a_response_without_an_image_names_the_finish_reason():
    blocked = SimpleNamespace(candidates=[SimpleNamespace(content=None, finish_reason="IMAGE_SAFETY")])
    fake_models = FakeModels(outcomes={PRIMARY_MODEL: blocked})

    with pytest.raises(ImageGenerationError, match="IMAGE_SAFETY"):
        make_client(fake_models).generate("scene", 1024, 1024)
