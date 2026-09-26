"""Cloudflare Workers AI image generation (flux-2-klein-4b) with a timeout, bounded retries and clear errors."""

import base64
import binascii
import logging
import time
from collections.abc import Callable

import httpx

CLOUDFLARE_API_BASE = "https://api.cloudflare.com/client/v4"
MAX_ATTEMPTS = 2
RETRY_BACKOFF_SECONDS = 3.0
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
HTTP_OK = 200
ERROR_BODY_PREVIEW_CHARS = 300

logger = logging.getLogger(__name__)


class ImageGenerationError(Exception):
    """Cloudflare could not produce an image; the message is safe to show in the UI."""


class CloudflareImageClient:
    def __init__(
        self,
        account_id: str,
        api_token: str,
        model: str,
        timeout_seconds: float,
        http_client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._url = f"{CLOUDFLARE_API_BASE}/accounts/{account_id}/ai/run/{model}"
        self._headers = {"Authorization": f"Bearer {api_token}"}
        self._timeout_seconds = timeout_seconds
        self._http = http_client or httpx.Client()
        self._sleep = sleep

    def generate(self, prompt: str, width: int, height: int) -> bytes:
        """Return JPEG bytes. Retries timeouts, 429 and 5xx; other failures raise at once."""
        form = {"prompt": (None, prompt), "width": (None, str(width)), "height": (None, str(height))}
        last_problem = ""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            logger.info("Cloudflare image request %dx%d (attempt %d of %d)", width, height, attempt, MAX_ATTEMPTS)
            started = time.monotonic()
            try:
                response = self._http.post(self._url, headers=self._headers, files=form, timeout=self._timeout_seconds)
            except httpx.TimeoutException:
                last_problem = f"timed out after {self._timeout_seconds:.0f}s"
            except httpx.HTTPError as error:
                last_problem = f"network error: {error}"
            else:
                if response.status_code == HTTP_OK:
                    logger.info("Cloudflare image %dx%d done in %.1fs", width, height, time.monotonic() - started)
                    return _decode_image(response)
                if response.status_code not in RETRYABLE_STATUS_CODES:
                    raise ImageGenerationError(
                        f"Cloudflare rejected the image request (HTTP {response.status_code}): "
                        f"{_error_detail(response)}"
                    )
                last_problem = f"HTTP {response.status_code}: {_error_detail(response)}"
            logger.warning("Cloudflare image %dx%d attempt %d failed: %s", width, height, attempt, last_problem)
            if attempt < MAX_ATTEMPTS:
                self._sleep(RETRY_BACKOFF_SECONDS)
        raise ImageGenerationError(
            f"Cloudflare image generation failed after {MAX_ATTEMPTS} attempts; last error: {last_problem}"
        )


def _decode_image(response: httpx.Response) -> bytes:
    try:
        payload = response.json()
    except ValueError as error:
        raise ImageGenerationError(
            f"Cloudflare returned non-JSON: {response.text[:ERROR_BODY_PREVIEW_CHARS]}"
        ) from error
    if not isinstance(payload, dict) or not payload.get("success", False):
        raise ImageGenerationError(f"Cloudflare reported failure: {_error_detail(response)}")
    try:
        encoded_image = payload["result"]["image"]
    except (KeyError, TypeError) as error:
        raise ImageGenerationError("Cloudflare response had no result.image field.") from error
    try:
        return base64.b64decode(encoded_image, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ImageGenerationError("Cloudflare returned an image that is not valid base64.") from error


def _error_detail(response: httpx.Response) -> str:
    """Cloudflare's own error messages when the body has them, else the start of the raw body."""
    try:
        payload = response.json()
    except ValueError:
        return response.text[:ERROR_BODY_PREVIEW_CHARS]
    errors = payload.get("errors") if isinstance(payload, dict) else None
    messages = [str(error.get("message", error)) for error in errors or [] if isinstance(error, dict)]
    return "; ".join(messages) if messages else response.text[:ERROR_BODY_PREVIEW_CHARS]
