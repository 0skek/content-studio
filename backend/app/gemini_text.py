"""Gemini text generation (copy and image scenes) with timeouts, retries, model fallback and clear errors.

Each model is retried with backoff on transient errors. If a model stays overloaded (503) or runs out of
free-tier quota (429), the next model in the list is tried; any other error fails at once.
"""

import logging
from collections.abc import Sequence
from typing import Any, TypeVar

import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError

MAX_ATTEMPTS_PER_MODEL = 4
RETRY_INITIAL_DELAY_SECONDS = 2.0
RETRY_MAX_DELAY_SECONDS = 16.0
RETRYABLE_STATUS_CODES = [429, 500, 502, 503, 504]
# Worth moving on to the next model rather than failing the post.
FALLBACK_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
HTTP_TOO_MANY_REQUESTS = 429
MILLISECONDS_PER_SECOND = 1000

SchemaT = TypeVar("SchemaT", bound=BaseModel)

logger = logging.getLogger(__name__)


class TextGenerationError(Exception):
    """Gemini could not produce usable text; the message is safe to show in the UI."""


class _ModelUnavailable(Exception):
    """This model is overloaded, out of quota or unreachable; the next model may still work."""


class GeminiTextClient:
    def __init__(
        self, api_key: str, models: Sequence[str], timeout_seconds: float, client: Any | None = None
    ) -> None:
        if not models:
            raise ValueError("At least one Gemini model is required")
        self._models = list(models)
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

    def generate(self, prompt: str, schema: type[SchemaT]) -> SchemaT:
        """Ask for JSON matching `schema` and return it validated, falling back through the model list."""
        failures: list[str] = []
        for model in self._models:
            try:
                return self._generate_with(model, prompt, schema)
            except _ModelUnavailable as unavailable:
                logger.warning("Gemini model %s unavailable (%s); trying the next model", model, unavailable)
                failures.append(f"{model}: {unavailable}")
        quota_hint = (
            " The free-tier daily quota resets at midnight Pacific time."
            if any(f"HTTP {HTTP_TOO_MANY_REQUESTS}" in failure for failure in failures)
            else ""
        )
        raise TextGenerationError(f"Every Gemini model failed. {' | '.join(failures)}.{quota_hint}")

    def _generate_with(self, model: str, prompt: str, schema: type[SchemaT]) -> SchemaT:
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        try:
            response = self._client.models.generate_content(model=model, contents=prompt, config=config)
        except errors.APIError as error:
            if error.code in FALLBACK_STATUS_CODES:
                raise _ModelUnavailable(f"HTTP {error.code} {error.message}") from error
            raise TextGenerationError(f"Gemini request failed (HTTP {error.code}): {error.message}") from error
        except httpx.TimeoutException as error:
            raise _ModelUnavailable("timed out") from error
        except httpx.HTTPError as error:
            raise _ModelUnavailable(f"network error: {error}") from error

        if isinstance(response.parsed, schema):
            return response.parsed
        if not response.text:
            finish_reason = response.candidates[0].finish_reason if response.candidates else "no candidates"
            raise TextGenerationError(f"Gemini ({model}) returned no text (finish reason: {finish_reason}).")
        try:
            return schema.model_validate_json(response.text)
        except ValidationError as error:
            raise TextGenerationError(
                f"Gemini ({model}) returned JSON that does not match {schema.__name__}: {error}"
            ) from error
