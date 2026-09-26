"""Provider selection: production uses Gemini + Cloudflare; local development uses Ollama + the local image server."""

import pytest

from app.cloudflare_images import CloudflareImageClient
from app.config import ImageProvider, Settings, TextProvider, settings
from app.gemini_text import GeminiTextClient
from app.generation_clients import GenerationNotConfigured, build_generation_clients
from app.local_images import LocalImageClient
from app.ollama_text import OllamaTextClient


def make_settings(**overrides) -> Settings:
    """Settings that ignore the real .env, so tests do not depend on the developer's keys or providers."""
    defaults = {"gemini_text_api_key": None, "cf_account_id": None, "cf_api_token": None}
    return Settings(_env_file=None, **{**defaults, **overrides})


def test_production_is_the_default():
    defaults = make_settings()

    assert defaults.text_provider == TextProvider.GEMINI
    assert defaults.image_provider == ImageProvider.CLOUDFLARE


def test_local_providers_need_no_keys():
    clients = build_generation_clients(
        make_settings(text_provider=TextProvider.OLLAMA, image_provider=ImageProvider.LOCAL)
    )

    assert isinstance(clients.text, OllamaTextClient)
    assert isinstance(clients.images, LocalImageClient)
    assert clients.text_before_images  # both share the one local GPU


def test_production_providers_are_built_from_the_keys():
    clients = build_generation_clients(
        make_settings(gemini_text_api_key="test-key", cf_account_id="account", cf_api_token="token")
    )

    assert isinstance(clients.text, GeminiTextClient)
    assert isinstance(clients.images, CloudflareImageClient)
    assert not clients.text_before_images  # cloud services: images may overlap with text


@pytest.mark.parametrize(
    ("overrides", "missing_key"),
    [
        ({"cf_account_id": "account", "cf_api_token": "token"}, "GEMINI_TEXT_API_KEY"),
        ({"gemini_text_api_key": "test-key", "cf_api_token": "token"}, "CF_ACCOUNT_ID"),
        ({"text_provider": TextProvider.OLLAMA}, "CF_ACCOUNT_ID, CF_API_TOKEN"),
    ],
)
def test_missing_production_keys_are_named(overrides, missing_key):
    with pytest.raises(GenerationNotConfigured, match=missing_key):
        build_generation_clients(make_settings(**overrides))


def test_mixed_providers_only_need_the_keys_they_use():
    clients = build_generation_clients(
        make_settings(gemini_text_api_key="test-key", image_provider=ImageProvider.LOCAL)
    )

    assert isinstance(clients.text, GeminiTextClient)
    assert isinstance(clients.images, LocalImageClient)


@pytest.mark.parametrize(
    ("text_provider", "image_provider", "production"),
    [
        (TextProvider.GEMINI, ImageProvider.CLOUDFLARE, True),
        (TextProvider.OLLAMA, ImageProvider.LOCAL, False),
        (TextProvider.GEMINI, ImageProvider.LOCAL, False),
    ],
)
def test_health_reports_the_providers(client, monkeypatch, text_provider, image_provider, production):
    monkeypatch.setattr(settings, "text_provider", text_provider)
    monkeypatch.setattr(settings, "image_provider", image_provider)

    health = client.get("/health").json()

    assert health["text_provider"] == text_provider
    assert health["image_provider"] == image_provider
    assert health["production_providers"] is production
