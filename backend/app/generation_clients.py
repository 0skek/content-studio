"""The external clients generation needs. Built from settings for real runs; tests pass fakes with the same methods."""

from dataclasses import dataclass
from typing import Protocol, TypeVar

from pydantic import BaseModel

from app.cloudflare_images import CloudflareImageClient
from app.config import Settings
from app.gemini_text import GeminiTextClient

SchemaT = TypeVar("SchemaT", bound=BaseModel)


class TextClient(Protocol):
    def generate(self, prompt: str, schema: type[SchemaT]) -> SchemaT: ...


class ImageClient(Protocol):
    def generate(self, prompt: str, width: int, height: int) -> bytes: ...


@dataclass(frozen=True)
class GenerationClients:
    text: TextClient
    images: ImageClient


class GenerationNotConfigured(Exception):
    """A key needed for generation is missing from .env."""


def build_generation_clients(settings: Settings) -> GenerationClients:
    required = {
        "GEMINI_TEXT_API_KEY": settings.gemini_text_api_key,
        "CF_ACCOUNT_ID": settings.cf_account_id,
        "CF_API_TOKEN": settings.cf_api_token,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise GenerationNotConfigured(f"Generation is not configured: set {', '.join(missing)} in .env")
    return GenerationClients(
        text=GeminiTextClient(
            api_key=settings.gemini_text_api_key.get_secret_value(),
            models=[settings.gemini_text_model, *settings.gemini_text_fallback_models],
            timeout_seconds=settings.text_request_timeout_seconds,
        ),
        images=CloudflareImageClient(
            account_id=settings.cf_account_id,
            api_token=settings.cf_api_token.get_secret_value(),
            model=settings.cloudflare_image_model,
            timeout_seconds=settings.image_request_timeout_seconds,
        ),
    )
