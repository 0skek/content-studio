"""Ollama text generation for local development (TEXT_PROVIDER=ollama). Same interface as GeminiTextClient."""

from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.gemini_text import TextGenerationError
from app.local_gpu import LOCAL_GPU_LOCK

HTTP_OK = 200
HTTP_NOT_FOUND = 404
# Unload the model after every call: the local image model needs the laptop GPU's memory right afterwards.
KEEP_ALIVE_UNLOAD_IMMEDIATELY = 0
ERROR_BODY_PREVIEW_CHARS = 300
# Small local models sometimes derail mid-answer (gemma3:4b closes a string with a curly quote, then loops on
# spaces), so malformed output gets one fresh attempt. Connection and HTTP errors do not.
MAX_ATTEMPTS_FOR_MALFORMED_OUTPUT = 2

SchemaT = TypeVar("SchemaT", bound=BaseModel)


class OllamaTextClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_seconds: float,
        max_output_tokens: int,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._max_output_tokens = max_output_tokens
        self._http = http_client or httpx.Client()

    def generate(self, prompt: str, schema: type[SchemaT]) -> SchemaT:
        """Ask for JSON matching `schema`; Ollama constrains its output to the schema passed as `format`."""
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "format": schema.model_json_schema(),
            "stream": False,
            "keep_alive": KEEP_ALIVE_UNLOAD_IMMEDIATELY,
            # A derailed answer loops until this cap instead of until the context fills, then gets its retry.
            "options": {"num_predict": self._max_output_tokens},
        }
        last_error: ValidationError | None = None
        for _attempt in range(MAX_ATTEMPTS_FOR_MALFORMED_OUTPUT):
            try:
                return schema.model_validate_json(self._chat(payload))
            except ValidationError as error:
                last_error = error
        raise TextGenerationError(
            f"Ollama ({self._model}) returned output that does not match {schema.__name__} "
            f"after {MAX_ATTEMPTS_FOR_MALFORMED_OUTPUT} attempts: {last_error}"
        ) from last_error

    def _chat(self, payload: dict) -> str:
        try:
            with LOCAL_GPU_LOCK:
                response = self._http.post(f"{self._base_url}/api/chat", json=payload, timeout=self._timeout_seconds)
        except httpx.ConnectError as error:
            raise TextGenerationError(
                f"Ollama is not running at {self._base_url}; start it with `ollama serve`."
            ) from error
        except httpx.TimeoutException as error:
            raise TextGenerationError(f"Ollama ({self._model}) timed out after {self._timeout_seconds:.0f}s.") from error
        except httpx.HTTPError as error:
            raise TextGenerationError(f"Could not reach Ollama: {error}") from error

        if response.status_code == HTTP_NOT_FOUND:
            raise TextGenerationError(f"Ollama has no model {self._model}; run `ollama pull {self._model}`.")
        if response.status_code != HTTP_OK:
            raise TextGenerationError(
                f"Ollama failed (HTTP {response.status_code}): {response.text[:ERROR_BODY_PREVIEW_CHARS]}"
            )
        try:
            return str(response.json()["message"]["content"])
        except (ValueError, KeyError, TypeError) as error:
            raise TextGenerationError(
                f"Ollama ({self._model}) sent a reply without a message: {response.text[:ERROR_BODY_PREVIEW_CHARS]}"
            ) from error
