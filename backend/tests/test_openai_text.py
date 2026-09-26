"""OpenAITextClient: model fallback and error messages, against a fake OpenAI client (no network)."""

from dataclasses import dataclass, field
from types import SimpleNamespace

import httpx
import openai
import pytest

from app.gemini_text import TextGenerationError
from app.openai_text import OpenAITextClient
from app.prompts import ChannelScene, SceneSet

PRIMARY_MODEL = "text-primary"
FALLBACK_MODEL = "text-fallback"
EXPECTED = SceneSet(scenes=[ChannelScene(channel="x", text_zone="right", scene="A wide festive scene")])
REQUEST = httpx.Request("POST", "https://api.openai.com/v1/responses")


def status_error(code: int, message: str, error_code: str | None = None) -> openai.APIStatusError:
    body = {"message": message, "type": "error", "code": error_code}
    return openai.APIStatusError(message, response=httpx.Response(code, request=REQUEST), body=body)


def parsed(value):
    return SimpleNamespace(output_parsed=value, output=[], status="completed", incomplete_details=None)


@dataclass
class FakeResponses:
    # model name -> exception to raise, or a response to return instead of EXPECTED.
    outcomes: dict[str, object] = field(default_factory=dict)
    called_models: list[str] = field(default_factory=list)

    def parse(self, model, input, text_format):
        self.called_models.append(model)
        outcome = self.outcomes.get(model)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome or parsed(EXPECTED)


def make_client(fake: FakeResponses) -> OpenAITextClient:
    return OpenAITextClient(
        api_key="unused", models=[PRIMARY_MODEL, FALLBACK_MODEL], timeout_seconds=1, client=SimpleNamespace(responses=fake)
    )


def test_primary_model_is_used_when_it_works():
    fake = FakeResponses()

    assert make_client(fake).generate("prompt", SceneSet) == EXPECTED
    assert fake.called_models == [PRIMARY_MODEL]


@pytest.mark.parametrize(
    "failure",
    [status_error(503, "overloaded"), status_error(429, "rate limited"), status_error(404, "no such model"),
     openai.APITimeoutError(request=REQUEST)],
    ids=["overloaded", "rate-limited", "gone", "timeout"],
)
def test_an_unavailable_model_falls_back_to_the_next(failure):
    fake = FakeResponses(outcomes={PRIMARY_MODEL: failure})

    assert make_client(fake).generate("prompt", SceneSet) == EXPECTED
    assert fake.called_models == [PRIMARY_MODEL, FALLBACK_MODEL]


def test_a_rejected_request_fails_at_once_with_the_reason():
    fake = FakeResponses(outcomes={PRIMARY_MODEL: status_error(401, "Incorrect API key provided")})

    with pytest.raises(TextGenerationError, match="HTTP 401 Incorrect API key provided"):
        make_client(fake).generate("prompt", SceneSet)
    assert fake.called_models == [PRIMARY_MODEL]


def test_no_api_credit_says_how_to_fix_it():
    no_credit = status_error(429, "You exceeded your current quota", error_code="insufficient_quota")
    fake = FakeResponses(outcomes={PRIMARY_MODEL: no_credit, FALLBACK_MODEL: no_credit})

    with pytest.raises(TextGenerationError, match="no API credit"):
        make_client(fake).generate("prompt", SceneSet)


def test_a_refusal_is_reported():
    refusal = SimpleNamespace(type="refusal", refusal="I can't help with that.")
    response = SimpleNamespace(
        output_parsed=None, output=[SimpleNamespace(content=[refusal])], status="completed", incomplete_details=None
    )
    fake = FakeResponses(outcomes={PRIMARY_MODEL: response})

    with pytest.raises(TextGenerationError, match="refused: I can't help with that"):
        make_client(fake).generate("prompt", SceneSet)


def test_a_cut_off_answer_names_the_reason():
    response = SimpleNamespace(
        output_parsed=None, output=[], status="incomplete", incomplete_details=SimpleNamespace(reason="max_output_tokens")
    )
    fake = FakeResponses(outcomes={PRIMARY_MODEL: response})

    with pytest.raises(TextGenerationError, match="max_output_tokens"):
        make_client(fake).generate("prompt", SceneSet)
