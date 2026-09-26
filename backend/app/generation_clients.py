"""The external clients generation needs. Built from settings for real runs; tests pass fakes with the same methods."""

from dataclasses import dataclass
from typing import Protocol, TypeVar

from pydantic import BaseModel

from app.cloudflare_images import CloudflareImageClient
from app.config import ImageProvider, Settings, TextProvider
from app.gemini_images import GeminiImageClient
from app.gemini_text import GeminiTextClient
from app.local_images import LocalImageClient
from app.ollama_text import OllamaTextClient
from app.openai_images import OpenAIImageClient
from app.openai_text import OpenAITextClient

SchemaT = TypeVar("SchemaT", bound=BaseModel)


class TextClient(Protocol):
    def generate(self, prompt: str, schema: type[SchemaT]) -> SchemaT: ...


class ImageClient(Protocol):
    def generate(self, prompt: str, width: int, height: int) -> bytes: ...


@dataclass(frozen=True)
class GenerationClients:
    text: TextClient
    images: ImageClient
    # True when text and images share one small local GPU: all text calls must finish (and Ollama unload)
    # before any image starts, or the two models together run out of video memory.
    text_before_images: bool = False


class GenerationNotConfigured(Exception):
    """A key needed for generation is missing from .env."""


def build_generation_clients(settings: Settings) -> GenerationClients:
    """Clients for the configured providers. Only the chosen providers' keys are required."""
    both_local = settings.text_provider == TextProvider.OLLAMA and settings.image_provider == ImageProvider.LOCAL
    return GenerationClients(
        text=_build_text_client(settings), images=_build_image_client(settings), text_before_images=both_local
    )


def _require_keys(provider: str, keys: dict[str, object]) -> None:
    missing = [name for name, value in keys.items() if not value]
    if missing:
        raise GenerationNotConfigured(f"Generation with {provider} is not configured: set {', '.join(missing)} in .env")


def _build_text_client(settings: Settings) -> TextClient:
    if settings.text_provider == TextProvider.OPENAI:
        _require_keys("OpenAI", {"OPENAI_API_KEY": settings.openai_api_key})
        return OpenAITextClient(
            api_key=settings.openai_api_key.get_secret_value(),
            models=[settings.openai_text_model, *settings.openai_text_fallback_models],
            timeout_seconds=settings.openai_text_timeout_seconds,
        )
    if settings.text_provider == TextProvider.OLLAMA:
        return OllamaTextClient(
            base_url=settings.ollama_url,
            model=settings.ollama_model,
            timeout_seconds=settings.ollama_timeout_seconds,
            max_output_tokens=settings.ollama_max_output_tokens,
        )
    _require_keys("Gemini", {"GEMINI_API_KEY": settings.gemini_api_key})
    return GeminiTextClient(
        api_key=settings.gemini_api_key.get_secret_value(),
        models=[settings.gemini_text_model, *settings.gemini_text_fallback_models],
        timeout_seconds=settings.text_request_timeout_seconds,
    )


def _build_image_client(settings: Settings) -> ImageClient:
    if settings.image_provider == ImageProvider.OPENAI:
        _require_keys("OpenAI", {"OPENAI_API_KEY": settings.openai_api_key})
        return OpenAIImageClient(
            api_key=settings.openai_api_key.get_secret_value(),
            model=settings.openai_image_model,
            quality=settings.openai_image_quality,
            timeout_seconds=settings.openai_image_timeout_seconds,
        )
    if settings.image_provider == ImageProvider.LOCAL:
        return LocalImageClient(base_url=settings.local_image_url, timeout_seconds=settings.local_image_timeout_seconds)
    if settings.image_provider == ImageProvider.GEMINI:
        _require_keys("Gemini", {"GEMINI_API_KEY": settings.gemini_api_key})
        return GeminiImageClient(
            api_key=settings.gemini_api_key.get_secret_value(),
            models=[settings.gemini_image_model, *settings.gemini_image_fallback_models],
            image_size=settings.gemini_image_size,
            timeout_seconds=settings.image_request_timeout_seconds,
        )
    _require_keys("Cloudflare", {"CF_ACCOUNT_ID": settings.cf_account_id, "CF_API_TOKEN": settings.cf_api_token})
    return CloudflareImageClient(
        account_id=settings.cf_account_id,
        api_token=settings.cf_api_token.get_secret_value(),
        model=settings.cloudflare_image_model,
        timeout_seconds=settings.image_request_timeout_seconds,
    )
