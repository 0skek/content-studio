"""OpenAI text generation (copy, image scenes and reports) with timeouts, retries, model fallback and clear errors.

Answers come back through structured outputs, parsed into the caller's Pydantic schema. The SDK itself retries
connection errors, 429 and 5xx once. A model still overloaded, rate-limited or gone after that moves on to the
next model; any other error (a bad request, a rejected key) fails at once without trying further models.
"""

import logging
from collections.abc import Sequence
from typing import Any, TypeVar

import openai
from pydantic import BaseModel, ValidationError

from app.gemini_text import TextGenerationError

# The SDK's own retries per request, on top of the first attempt.
MAX_RETRIES_PER_MODEL = 1
# Worth moving on to the next model rather than failing the post.
FALLBACK_STATUS_CODES = frozenset({404, 429, 500, 502, 503, 504})
# A 429 with this code means the account has no API credit, which no retry or other model will fix.
NO_CREDIT_CODE = "insufficient_quota"
NO_CREDIT_HINT = " The OpenAI account has no API credit: add some at platform.openai.com (Settings > Billing)."

SchemaT = TypeVar("SchemaT", bound=BaseModel)

logger = logging.getLogger(__name__)


class _ModelUnavailable(Exception):
    """This model is overloaded, rate-limited or unreachable; the next model may still work."""


def error_detail(error: openai.APIStatusError) -> str:
    """OpenAI's own message for a failed request, without the SDK's 'Error code: ...' wrapping."""
    body = error.body
    if isinstance(body, dict) and body.get("message"):
        return str(body["message"])
    return str(error)


def is_out_of_credit(error: openai.APIStatusError) -> bool:
    return isinstance(error.body, dict) and error.body.get("code") == NO_CREDIT_CODE


class OpenAITextClient:
    def __init__(
        self, api_key: str, models: Sequence[str], timeout_seconds: float, client: Any | None = None
    ) -> None:
        if not models:
            raise ValueError("At least one OpenAI model is required")
        self._models = list(models)
        self._client = client or openai.OpenAI(
            api_key=api_key, timeout=timeout_seconds, max_retries=MAX_RETRIES_PER_MODEL
        )

    def generate(self, prompt: str, schema: type[SchemaT]) -> SchemaT:
        """Ask for an answer matching `schema` and return it validated, falling back through the model list."""
        failures: list[str] = []
        for model in self._models:
            try:
                return self._generate_with(model, prompt, schema)
            except _ModelUnavailable as unavailable:
                logger.warning("OpenAI model %s unavailable (%s); trying the next model", model, unavailable)
                failures.append(f"{model}: {unavailable}")
        hint = NO_CREDIT_HINT if any(NO_CREDIT_CODE in failure for failure in failures) else ""
        raise TextGenerationError(f"Every OpenAI model failed. {' | '.join(failures)}.{hint}")

    def _generate_with(self, model: str, prompt: str, schema: type[SchemaT]) -> SchemaT:
        try:
            response = self._client.responses.parse(model=model, input=prompt, text_format=schema)
        except openai.APITimeoutError as error:
            raise _ModelUnavailable("timed out") from error
        except openai.APIConnectionError as error:
            raise _ModelUnavailable(f"network error: {error}") from error
        except openai.APIStatusError as error:
            detail = f"HTTP {error.status_code} {error_detail(error)}"
            if is_out_of_credit(error):
                raise _ModelUnavailable(f"{detail} ({NO_CREDIT_CODE})") from error
            if error.status_code in FALLBACK_STATUS_CODES:
                raise _ModelUnavailable(detail) from error
            raise TextGenerationError(f"OpenAI request failed ({detail}).") from error
        except ValidationError as error:
            raise TextGenerationError(
                f"OpenAI ({model}) returned JSON that does not match {schema.__name__}: {error}"
            ) from error

        parsed = response.output_parsed
        if isinstance(parsed, schema):
            return parsed
        refusal = _refusal(response)
        if refusal:
            raise TextGenerationError(f"OpenAI ({model}) refused: {refusal}")
        reason = getattr(getattr(response, "incomplete_details", None), "reason", None) or response.status
        raise TextGenerationError(f"OpenAI ({model}) returned no usable answer (status: {reason}).")


def _refusal(response: Any) -> str | None:
    for item in getattr(response, "output", None) or []:
        for content in getattr(item, "content", None) or []:
            if getattr(content, "type", None) == "refusal":
                return getattr(content, "refusal", None) or "no reason given"
    return None
