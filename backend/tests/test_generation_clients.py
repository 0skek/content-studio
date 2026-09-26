"""Provider selection: production uses Gemini for text and images; local development uses Ollama + the local image
server; OpenAI (text and images) and Cloudflare (images) remain alternatives."""

import pytest

from app.cloudflare_images import CloudflareImageClient
from app.config import ImageProvider, Settings, TextProvider, settings
from app.gemini_images import GeminiImageClient
from app.gemini_text import GeminiTextClient
from app.generation_clients import GenerationNotConfigured, build_generation_clients
from app.local_images import LocalImageClient
from app.ollama_text import OllamaTextClient
from app.openai_images import OpenAIImageClient
from app.openai_text import OpenAITextClient


def make_settings(**overrides) -> Settings:
    """Settings that ignore the real .env, so tests do not depend on the developer's keys or providers."""
    defaults = {"openai_api_key": None, "gemini_api_key": None, "cf_account_id": None, "cf_api_token": None}
    return Settings(_env_file=None, **{**defaults, **overrides})


def test_production_is_the_default():
    defaults = make_settings()

    assert defaults.text_provider == TextProvider.GEMINI
    assert defaults.image_provider == ImageProvider.GEMINI


def test_local_providers_need_no_keys():
    clients = build_generation_clients(
        make_settings(text_provider=TextProvider.OLLAMA, image_provider=ImageProvider.LOCAL)
    )

    assert isinstance(clients.text, OllamaTextClient)
    assert isinstance(clients.images, LocalImageClient)
    assert clients.text_before_images  # both share the one local GPU


def test_production_providers_are_built_from_the_gemini_key():
    clients = build_generation_clients(make_settings(gemini_api_key="test-key"))

    assert isinstance(clients.text, GeminiTextClient)
    assert isinstance(clients.images, GeminiImageClient)
    assert not clients.text_before_images  # cloud services: images may overlap with text


@pytest.mark.parametrize(
    ("provider_settings", "key_setting", "text_client", "image_client"),
    [
        ({"text_provider": TextProvider.OPENAI, "image_provider": ImageProvider.OPENAI}, "openai_api_key",
         OpenAITextClient, OpenAIImageClient),
        ({"text_provider": TextProvider.GEMINI, "image_provider": ImageProvider.GEMINI}, "gemini_api_key",
         GeminiTextClient, GeminiImageClient),
    ],
    ids=["openai", "gemini"],
)
def test_one_key_runs_both_text_and_images(provider_settings, key_setting, text_client, image_client):
    """Every other key is unset: a single provider key must be enough for the whole pipeline."""
    clients = build_generation_clients(make_settings(**provider_settings, **{key_setting: "the-only-key"}))

    assert isinstance(clients.text, text_client)
    assert isinstance(clients.images, image_client)


@pytest.mark.parametrize("env_name", ["GEMINI_API_KEY", "GEMINI_TEXT_API_KEY"])
def test_the_gemini_key_is_read_under_its_new_or_old_name(monkeypatch, env_name):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_TEXT_API_KEY", raising=False)
    monkeypatch.setenv(env_name, "from-the-environment")

    assert Settings(_env_file=None).gemini_api_key.get_secret_value() == "from-the-environment"


def test_cloudflare_images_are_built_from_their_keys():
    clients = build_generation_clients(
        make_settings(
            gemini_api_key="test-key",
            image_provider=ImageProvider.CLOUDFLARE,
            cf_account_id="account",
            cf_api_token="token",
        )
    )

    assert isinstance(clients.images, CloudflareImageClient)


@pytest.mark.parametrize(
    ("overrides", "missing_key"),
    [
        ({}, "GEMINI_API_KEY"),
        ({"text_provider": TextProvider.OLLAMA}, "GEMINI_API_KEY"),  # Gemini images need it too
        ({"text_provider": TextProvider.OPENAI, "gemini_api_key": "k"}, "OPENAI_API_KEY"),
        (
            {"gemini_api_key": "test-key", "image_provider": ImageProvider.CLOUDFLARE, "cf_api_token": "token"},
            "CF_ACCOUNT_ID",
        ),
    ],
)
def test_missing_production_keys_are_named(overrides, missing_key):
    with pytest.raises(GenerationNotConfigured, match=missing_key):
        build_generation_clients(make_settings(**overrides))


def test_mixed_providers_only_need_the_keys_they_use():
    clients = build_generation_clients(make_settings(gemini_api_key="test-key", image_provider=ImageProvider.LOCAL))

    assert isinstance(clients.text, GeminiTextClient)
    assert isinstance(clients.images, LocalImageClient)


@pytest.mark.parametrize(
    ("text_provider", "image_provider", "production"),
    [
        (TextProvider.GEMINI, ImageProvider.GEMINI, True),
        (TextProvider.OPENAI, ImageProvider.OPENAI, False),
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
