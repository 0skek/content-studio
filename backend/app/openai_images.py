"""OpenAI image generation (gpt-image) with a timeout, bounded retries and clear errors.

GPT Image models take any WIDTHxHEIGHT whose sides are multiples of 16 (ratio 1:3 to 3:1, 655,360 to 8,294,400
pixels), so each channel's exact size from channels.json is requested directly. The generation service still
checks the size that comes back and fails the post otherwise: nothing is resized or cropped (rule 1).
"""

import base64
import binascii
import logging
import time
from typing import Any

import openai

from app.cloudflare_images import ImageGenerationError
from app.openai_text import NO_CREDIT_HINT, error_detail, is_out_of_credit

# The SDK's own retries (connection errors, 429, 5xx), on top of the first attempt.
MAX_RETRIES = 1
OUTPUT_FORMAT = "jpeg"

logger = logging.getLogger(__name__)


class OpenAIImageClient:
    def __init__(
        self, api_key: str, model: str, quality: str, timeout_seconds: float, client: Any | None = None
    ) -> None:
        self._model = model
        self._quality = quality
        self._timeout_seconds = timeout_seconds
        self._client = client or openai.OpenAI(api_key=api_key, timeout=timeout_seconds, max_retries=MAX_RETRIES)

    def generate(self, prompt: str, width: int, height: int) -> bytes:
        """Return JPEG bytes at exactly width x height (the caller verifies the size)."""
        logger.info("OpenAI image request %s %dx%d (%s quality)", self._model, width, height, self._quality)
        started = time.monotonic()
        try:
            result = self._client.images.generate(
                model=self._model,
                prompt=prompt,
                size=f"{width}x{height}",
                quality=self._quality,
                output_format=OUTPUT_FORMAT,
                n=1,
            )
        except openai.APITimeoutError as error:
            raise ImageGenerationError(
                f"OpenAI image generation timed out after {self._timeout_seconds:.0f}s."
            ) from error
        except openai.APIConnectionError as error:
            raise ImageGenerationError(f"Could not reach OpenAI: {error}") from error
        except openai.APIStatusError as error:
            hint = NO_CREDIT_HINT if is_out_of_credit(error) else ""
            raise ImageGenerationError(
                f"OpenAI rejected the image request (HTTP {error.status_code}): {error_detail(error)}.{hint}"
            ) from error

        encoded = result.data[0].b64_json if result.data else None
        if not encoded:
            raise ImageGenerationError("OpenAI returned no image.")
        try:
            image = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as error:
            raise ImageGenerationError("OpenAI returned an image that is not valid base64.") from error
        logger.info("OpenAI image %dx%d done in %.1fs", width, height, time.monotonic() - started)
        return image
