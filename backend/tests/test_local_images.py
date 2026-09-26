"""LocalImageClient against httpx.MockTransport (no GPU or image server needed)."""

from collections.abc import Callable

import httpx
import pytest

from app.cloudflare_images import ImageGenerationError
from app.local_images import MAX_ATTEMPTS, LocalImageClient
from tests.fakes import make_jpeg

SERVER_URL = "http://images.test:8100"
IMAGE_BYTES = make_jpeg(64, 32)


def make_client(handler: Callable[[httpx.Request], httpx.Response]) -> tuple[LocalImageClient, list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def recording_handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    client = LocalImageClient(
        base_url=SERVER_URL,
        timeout_seconds=1,
        http_client=httpx.Client(transport=httpx.MockTransport(recording_handler)),
        sleep=lambda seconds: None,
    )
    return client, requests


def test_success_returns_the_image_and_sends_the_same_form_as_cloudflare():
    client, requests = make_client(lambda request: httpx.Response(200, content=IMAGE_BYTES))

    assert client.generate("a festive scene", 1344, 704) == IMAGE_BYTES

    request = requests[0]
    assert request.url == f"{SERVER_URL}/generate"
    body = request.content.decode(errors="replace")
    for field_name, value in (("prompt", "a festive scene"), ("width", "1344"), ("height", "704")):
        assert f'name="{field_name}"' in body and value in body


def test_server_not_running_fails_at_once_with_how_to_start_it():
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client, requests = make_client(refuse)

    with pytest.raises(ImageGenerationError, match="not running.*uv run uvicorn server:app"):
        client.generate("scene", 64, 32)
    assert len(requests) == 1


def test_a_server_error_is_retried_once():
    responses = iter([httpx.Response(503, json={"detail": "GPU out of memory"}), httpx.Response(200, content=IMAGE_BYTES)])
    client, requests = make_client(lambda request: next(responses))

    assert client.generate("scene", 64, 32) == IMAGE_BYTES
    assert len(requests) == 2


def test_timeouts_are_retried_then_reported():
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    client, requests = make_client(slow)

    with pytest.raises(ImageGenerationError, match=f"after {MAX_ATTEMPTS} attempts; last error: timed out"):
        client.generate("scene", 64, 32)
    assert len(requests) == MAX_ATTEMPTS


def test_a_refused_request_fails_at_once_with_the_servers_reason():
    client, requests = make_client(
        lambda request: httpx.Response(422, json={"detail": "width must be a positive multiple of 8"})
    )

    with pytest.raises(ImageGenerationError, match="HTTP 422.*multiple of 8"):
        client.generate("scene", 65, 32)
    assert len(requests) == 1
