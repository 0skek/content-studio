"""Application settings, read from environment variables and the repo-root .env file."""

from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    database_path: Path = BACKEND_DIR / "data" / "content_studio.db"
    channels_config_path: Path = BACKEND_DIR / "config" / "channels.json"

    # SecretStr keeps keys out of reprs and logs. None of these is used before milestone 2.
    gemini_text_api_key: SecretStr | None = None
    cf_account_id: str | None = None
    cf_api_token: SecretStr | None = None

    cloudflare_image_model: str = "@cf/black-forest-labs/flux-2-klein-4b"
    # Warm calls take ~17s and cold starts ~60s.
    image_request_timeout_seconds: float = 90.0

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path}"


settings = Settings()
