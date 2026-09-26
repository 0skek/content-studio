"""Application settings, read from environment variables and the repo-root .env file."""

from enum import StrEnum
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
MEDIA_URL_PATH = "/media"


class TextProvider(StrEnum):
    GEMINI = "gemini"  # production
    OLLAMA = "ollama"  # local development


class ImageProvider(StrEnum):
    CLOUDFLARE = "cloudflare"  # production
    LOCAL = "local"  # local development: tools/local_image_server


PRODUCTION_TEXT_PROVIDER = TextProvider.GEMINI
PRODUCTION_IMAGE_PROVIDER = ImageProvider.CLOUDFLARE


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    database_path: Path = BACKEND_DIR / "data" / "content_studio.db"
    channels_config_path: Path = BACKEND_DIR / "config" / "channels.json"
    # Generated images; one folder per brief so they are easy to review.
    media_dir: Path = BACKEND_DIR / "media"

    # Which services generate content. The defaults are production; set both to the local ones for development.
    text_provider: TextProvider = PRODUCTION_TEXT_PROVIDER
    image_provider: ImageProvider = PRODUCTION_IMAGE_PROVIDER

    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "gemma3:4b"
    # Per call, including loading the model (it is unloaded after every call), not counting the wait for the GPU.
    ollama_timeout_seconds: float = 180.0
    # A copy answer for three channels is about 500 tokens (measured). A derailed answer that loops is cut off
    # here (about 30 s on the laptop GPU) and gets one retry, instead of running into the timeout.
    ollama_max_output_tokens: int = 1536

    local_image_url: str = "http://127.0.0.1:8100"
    # Per image, not counting the wait for the GPU (see app/local_gpu.py).
    local_image_timeout_seconds: float = 300.0

    # SecretStr keeps keys out of reprs and logs.
    gemini_text_api_key: SecretStr | None = None
    cf_account_id: str | None = None
    cf_api_token: SecretStr | None = None

    gemini_text_model: str = "gemini-3.8-flash"
    # Tried in order when the model before is overloaded (5xx), out of free-tier quota (429) or gone (404).
    # Free-tier quotas are per model, so each fallback adds capacity. gemini-2.5-flash is gone for new keys (404).
    gemini_text_fallback_models: list[str] = [
        "gemini-3.7-flash",
        "gemini-3.6-flash",
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
    ]
    # One structured call for 3 channels took ~9s when measured.
    text_request_timeout_seconds: float = 60.0

    cloudflare_image_model: str = "@cf/black-forest-labs/flux-2-klein-4b"
    # Warm calls take ~17s and cold starts ~60s.
    image_request_timeout_seconds: float = 90.0

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path}"


settings = Settings()
