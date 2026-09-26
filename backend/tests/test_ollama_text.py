"""OllamaTextClient against httpx.MockTransport (no Ollama needed)."""

import json
from collections.abc import Callable

import httpx
import pytest

from app.gemini_text import TextGenerationError
from app.ollama_text import KEEP_ALIVE_UNLOAD_IMMEDIATELY, MAX_ATTEMPTS_FOR_MALFORMED_OUTPUT, OllamaTextClient
from app.prompts import ChannelScene, SceneSet

OLLAMA_URL = "http://ollama.test:11434"
MODEL = "gemma3:4b"
MAX_OUTPUT_TOKENS = 1536
EXPECTED = SceneSet(scenes=[ChannelScene(channel="x", text_zone="right", scene="A wide festive scene")])


def make_client(handler: Callable[[httpx.Request], httpx.Response]) -> tuple[OllamaTextClient, list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def recording_handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    client = OllamaTextClient(
        base_url=OLLAMA_URL,
        model=MODEL,
        timeout_seconds=1,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        http_client=httpx.Client(transport=httpx.MockTransport(recording_handler)),
    )
    return client, requests


def chat_reply(content: str) -> httpx.Response:
    return httpx.Response(200, json={"model": MODEL, "message": {"role": "assistant", "content": content}, "done": True})


def test_success_sends_the_schema_and_parses_the_answer():
    client, requests = make_client(lambda request: chat_reply(EXPECTED.model_dump_json()))

    assert client.generate("write scenes", SceneSet) == EXPECTED

    sent = json.loads(requests[0].content)
    assert requests[0].url == f"{OLLAMA_URL}/api/chat"
    assert sent["model"] == MODEL
    assert sent["format"] == SceneSet.model_json_schema()
    assert sent["stream"] is False
    assert sent["keep_alive"] == KEEP_ALIVE_UNLOAD_IMMEDIATELY
    assert sent["options"] == {"num_predict": MAX_OUTPUT_TOKENS}
    assert sent["messages"] == [{"role": "user", "content": "write scenes"}]


def test_ollama_not_running_says_how_to_start_it():
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client, _ = make_client(refuse)

    with pytest.raises(TextGenerationError, match="not running.*ollama serve"):
        client.generate("prompt", SceneSet)


def test_missing_model_says_how_to_pull_it():
    client, _ = make_client(lambda request: httpx.Response(404, json={"error": f"model '{MODEL}' not found"}))

    with pytest.raises(TextGenerationError, match=f"ollama pull {MODEL}"):
        client.generate("prompt", SceneSet)


def test_timeout_is_a_clear_error():
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    client, _ = make_client(slow)

    with pytest.raises(TextGenerationError, match="timed out"):
        client.generate("prompt", SceneSet)


@pytest.mark.parametrize("content", ['{"scenes": "not a list"}', "not json at all"])
def test_output_that_does_not_match_the_schema_is_a_clear_error(content):
    client, requests = make_client(lambda request: chat_reply(content))

    with pytest.raises(TextGenerationError, match=f"does not match SceneSet after {MAX_ATTEMPTS_FOR_MALFORMED_OUTPUT}"):
        client.generate("prompt", SceneSet)
    assert len(requests) == MAX_ATTEMPTS_FOR_MALFORMED_OUTPUT


def test_a_derailed_answer_gets_one_fresh_attempt():
    """Seen live: gemma3:4b closed a string with a curly quote, then looped on non-breaking spaces."""
    replies = iter([chat_reply('{"scenes": [{"channel": "x", "text_zone": "right", "scene": "Sky\u201d \u00a0\u00a0'),
                    chat_reply(EXPECTED.model_dump_json())])
    client, requests = make_client(lambda request: next(replies))

    assert client.generate("prompt", SceneSet) == EXPECTED
    assert len(requests) == 2


def test_a_reply_without_a_message_is_a_clear_error():
    client, _ = make_client(lambda request: httpx.Response(200, json={"done": True}))

    with pytest.raises(TextGenerationError, match="without a message"):
        client.generate("prompt", SceneSet)
