"""Gemini image generation with timeouts, retries, model fallback and clear errors.

Gemini takes an aspect ratio from a fixed list and an output tier, never a pixel size, so the client asks for
the listed ratio closest to the channel's size. The generation service then checks that the image came back at
exactly that size and fails the post otherwise: nothing is resized or cropped (rule 1). channels.json holds the
sizes Gemini actually returns for each channel's ratio.

Like the text client, it walks a list of models: an overloaded model (5xx) gets one retry, and a model that is
rate-limited (429) or no longer offered (404) is skipped at once. Any other error fails without trying further.
"""

import logging
from collections.abc import Sequence
from typing import Any

import httpx
from google import genai
from google.genai import errors, types

from app.cloudflare_images import ImageGenerationError

# The ratios Gemini image models accept (ai.google.dev/gemini-api/docs/image-generation).
SUPPORTED_ASPECT_RATIOS = ("1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9")
MAX_ATTEMPTS_PER_MODEL = 2
RETRY_INITIAL_DELAY_SECONDS = 2.0
RETRY_MAX_DELAY_SECONDS = 8.0
RETRYABLE_STATUS_CODES = [500, 502, 503, 504]
FALLBACK_STATUS_CODES = frozenset({404, 429, 500, 502, 503, 504})
HTTP_TOO_MANY_REQUESTS = 429
MILLISECONDS_PER_SECOND = 1000
IMAGE_MODALITY = "IMAGE"

logger = logging.getLogger(__name__)


class _ModelUnavailable(Exception):
    """This model is overloaded, rate-limited or unreachable; the next model may still work."""


def _ratio_value(ratio: str) -> float:
    width, height = ratio.split(":")
    return int(width) / int(height)


def closest_aspect_ratio(width: int, height: int) -> str:
    """The supported ratio nearest to width:height."""
    wanted = width / height
    return min(SUPPORTED_ASPECT_RATIOS, key=lambda ratio: abs(_ratio_value(ratio) - wanted))


class GeminiImageClient:
    def __init__(
        self,
        api_key: str,
        models: Sequence[str],
        image_size: str,
        timeout_seconds: float,
        client: Any | None = None,
    ) -> None:
        if not models:
            raise ValueError("At least one Gemini image model is required")
        self._models = list(models)
        self._image_size = image_size
        self._client = client or genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=int(timeout_seconds * MILLISECONDS_PER_SECOND),
                retry_options=types.HttpRetryOptions(
                    attempts=MAX_ATTEMPTS_PER_MODEL,
                    initial_delay=RETRY_INITIAL_DELAY_SECONDS,
                    max_delay=RETRY_MAX_DELAY_SECONDS,
                    http_status_codes=RETRYABLE_STATUS_CODES,
                ),
            ),
        )

    def generate(self, prompt: str, width: int, height: int) -> bytes:
        """Return the image bytes for the ratio nearest width:height, falling back through the model list."""
        ratio = closest_aspect_ratio(width, height)
        failures: list[str] = []
        for model in self._models:
            logger.info("Gemini image request %s at %s for %dx%d", model, ratio, width, height)
            try:
                return self._generate_with(model, prompt, ratio)
            except _ModelUnavailable as unavailable:
                logger.warning("Gemini image model %s unavailable (%s); trying the next model", model, unavailable)
                failures.append(f"{model}: {unavailable}")
        billing_hint = (
            " Gemini image models have no free tier: billing must be enabled for this key's Google project."
            if any(f"HTTP {HTTP_TOO_MANY_REQUESTS}" in failure for failure in failures)
            else ""
        )
        raise ImageGenerationError(f"Every Gemini image model failed. {' | '.join(failures)}.{billing_hint}")

    def _generate_with(self, model: str, prompt: str, ratio: str) -> bytes:
        config = types.GenerateContentConfig(
            response_modalities=[IMAGE_MODALITY],
            image_config=types.ImageConfig(aspect_ratio=ratio, image_size=self._image_size),
        )
        try:
            response = self._client.models.generate_content(model=model, contents=prompt, config=config)
        except errors.APIError as error:
            if error.code in FALLBACK_STATUS_CODES:
                raise _ModelUnavailable(f"HTTP {error.code} {error.message}") from error
            raise ImageGenerationError(f"Gemini image request failed (HTTP {error.code}): {error.message}") from error
        except httpx.TimeoutException as error:
            raise _ModelUnavailable("timed out") from error
        except httpx.HTTPError as error:
            raise _ModelUnavailable(f"network error: {error}") from error

        for candidate in response.candidates or []:
            parts = candidate.content.parts if candidate.content and candidate.content.parts else []
            for part in parts:
                if part.inline_data and part.inline_data.data:
                    return part.inline_data.data
        finish_reason = response.candidates[0].finish_reason if response.candidates else "no candidates"
        raise ImageGenerationError(f"Gemini ({model}) returned no image (finish reason: {finish_reason}).")
