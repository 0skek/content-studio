"""GeminiTextClient: model fallback and error messages, against a fake google-genai client (no network)."""

from dataclasses import dataclass, field
from types import SimpleNamespace

import httpx
import pytest
from google.genai import errors

from app.gemini_text import GeminiTextClient, TextGenerationError
from app.prompts import ChannelScene, SceneSet

PRIMARY_MODEL = "gemini-primary"
FALLBACK_MODEL = "gemini-fallback"
EXPECTED = SceneSet(scenes=[ChannelScene(channel="x", scene="A wide festive scene")])


def overloaded() -> errors.APIError:
    return errors.ServerError(503, {"error": {"code": 503, "message": "high demand", "status": "UNAVAILABLE"}})


def out_of_quota() -> errors.APIError:
    return errors.ClientError(429, {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}})


def bad_request() -> errors.APIError:
    return errors.ClientError(400, {"error": {"code": 400, "message": "Invalid schema", "status": "INVALID_ARGUMENT"}})


@dataclass
class FakeModels:
    # model name -> exception to raise; any other model returns EXPECTED.
    failures: dict[str, Exception] = field(default_factory=dict)
    called_models: list[str] = field(default_factory=list)

    def generate_content(self, model, contents, config):
        self.called_models.append(model)
        if model in self.failures:
            raise self.failures[model]
        return SimpleNamespace(parsed=EXPECTED, text=EXPECTED.model_dump_json(), candidates=[])


def make_client(fake_models: FakeModels) -> GeminiTextClient:
    return GeminiTextClient(
        api_key="unused",
        models=[PRIMARY_MODEL, FALLBACK_MODEL],
        timeout_seconds=1,
        client=SimpleNamespace(models=fake_models),
    )


def test_primary_model_is_used_when_it_works():
    fake_models = FakeModels()

    assert make_client(fake_models).generate("prompt", SceneSet) == EXPECTED
    assert fake_models.called_models == [PRIMARY_MODEL]


@pytest.mark.parametrize("failure", [overloaded(), out_of_quota(), httpx.ReadTimeout("slow")], ids=["503", "429", "timeout"])
def test_falls_back_to_the_next_model_when_the_primary_is_unavailable(failure):
    fake_models = FakeModels(failures={PRIMARY_MODEL: failure})

    assert make_client(fake_models).generate("prompt", SceneSet) == EXPECTED
    assert fake_models.called_models == [PRIMARY_MODEL, FALLBACK_MODEL]


def test_a_bad_request_fails_at_once_without_fallback():
    fake_models = FakeModels(failures={PRIMARY_MODEL: bad_request()})

    with pytest.raises(TextGenerationError, match="HTTP 400"):
        make_client(fake_models).generate("prompt", SceneSet)
    assert fake_models.called_models == [PRIMARY_MODEL]


def test_when_every_model_fails_the_error_names_each_one():
    fake_models = FakeModels(failures={PRIMARY_MODEL: overloaded(), FALLBACK_MODEL: out_of_quota()})

    with pytest.raises(TextGenerationError) as raised:
        make_client(fake_models).generate("prompt", SceneSet)

    message = str(raised.value)
    assert f"{PRIMARY_MODEL}: HTTP 503" in message
    assert f"{FALLBACK_MODEL}: HTTP 429" in message
    assert "resets at midnight Pacific" in message


def test_malformed_json_is_a_clear_error():
    fake_models = FakeModels()
    fake_models.generate_content = lambda model, contents, config: SimpleNamespace(
        parsed=None, text='{"scenes": "not a list"}', candidates=[]
    )

    with pytest.raises(TextGenerationError, match="does not match SceneSet"):
        make_client(fake_models).generate("prompt", SceneSet)
