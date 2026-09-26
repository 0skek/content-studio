"""Local image generation for development (IMAGE_PROVIDER=local). Same interface as CloudflareImageClient.

It calls tools/local_image_server, which runs SDXL on the local GPU and returns JPEG bytes at the exact size.
"""

import logging
import time
from collections.abc import Callable

import httpx

from app.cloudflare_images import ImageGenerationError
from app.local_gpu import LOCAL_GPU_LOCK

MAX_ATTEMPTS = 2
RETRY_BACKOFF_SECONDS = 3.0
HTTP_OK = 200
FIRST_SERVER_ERROR_STATUS = 500
ERROR_BODY_PREVIEW_CHARS = 300
START_HINT = "start it with `cd tools/local_image_server && uv run uvicorn server:app --port 8100`"

logger = logging.getLogger(__name__)


class LocalImageClient:
    def __init__(
        self,
        base_url: str,
        timeout_seconds: float,
        http_client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._http = http_client or httpx.Client()
        self._sleep = sleep

    def generate(self, prompt: str, width: int, height: int) -> bytes:
        """Return JPEG bytes. A server that is down fails at once; timeouts and 5xx get one retry."""
        form = {"prompt": (None, prompt), "width": (None, str(width)), "height": (None, str(height))}
        last_problem = ""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            logger.info("Local image request %dx%d (attempt %d of %d)", width, height, attempt, MAX_ATTEMPTS)
            try:
                with LOCAL_GPU_LOCK:
                    response = self._http.post(
                        f"{self._base_url}/generate", files=form, timeout=self._timeout_seconds
                    )
            except httpx.ConnectError as error:
                raise ImageGenerationError(
                    f"The local image server is not running at {self._base_url}; {START_HINT}."
                ) from error
            except httpx.TimeoutException:
                last_problem = f"timed out after {self._timeout_seconds:.0f}s"
            except httpx.HTTPError as error:
                last_problem = f"network error: {error}"
            else:
                if response.status_code == HTTP_OK:
                    return response.content
                detail = _error_detail(response)
                if response.status_code < FIRST_SERVER_ERROR_STATUS:
                    raise ImageGenerationError(
                        f"The local image server refused the request (HTTP {response.status_code}): {detail}"
                    )
                last_problem = f"HTTP {response.status_code}: {detail}"
            logger.warning("Local image %dx%d attempt %d failed: %s", width, height, attempt, last_problem)
            if attempt < MAX_ATTEMPTS:
                self._sleep(RETRY_BACKOFF_SECONDS)
        raise ImageGenerationError(
            f"Local image generation failed after {MAX_ATTEMPTS} attempts; last error: {last_problem}"
        )


def _error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:ERROR_BODY_PREVIEW_CHARS]
    detail = payload.get("detail") if isinstance(payload, dict) else None
    return str(detail) if detail else response.text[:ERROR_BODY_PREVIEW_CHARS]
