"""CloudflareImageClient: retries, decoding and error messages, against httpx.MockTransport (no network)."""

import base64
from collections.abc import Callable

import httpx
import pytest

from app.cloudflare_images import MAX_ATTEMPTS, CloudflareImageClient, ImageGenerationError
from tests.fakes import make_jpeg

IMAGE_BYTES = make_jpeg(64, 32)
SUCCESS_BODY = {"result": {"image": base64.b64encode(IMAGE_BYTES).decode()}, "success": True, "errors": []}


def make_client(handler: Callable[[httpx.Request], httpx.Response]) -> tuple[CloudflareImageClient, list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def recording_handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    client = CloudflareImageClient(
        account_id="account",
        api_token="token",
        model="@cf/black-forest-labs/flux-2-klein-4b",
        timeout_seconds=1,
        http_client=httpx.Client(transport=httpx.MockTransport(recording_handler)),
        sleep=lambda seconds: None,
    )
    return client, requests


def test_success_returns_the_decoded_image_and_sends_a_multipart_form():
    client, requests = make_client(lambda request: httpx.Response(200, json=SUCCESS_BODY))

    assert client.generate("a festive scene", 1344, 704) == IMAGE_BYTES

    request = requests[0]
    assert request.url.path.endswith("/accounts/account/ai/run/@cf/black-forest-labs/flux-2-klein-4b")
    assert request.headers["Authorization"] == "Bearer token"
    assert request.headers["Content-Type"].startswith("multipart/form-data")
    body = request.content.decode(errors="replace")
    for field_name, value in (("prompt", "a festive scene"), ("width", "1344"), ("height", "704")):
        assert f'name="{field_name}"' in body and value in body


def test_a_server_error_is_retried():
    responses = iter([httpx.Response(503, json={"errors": [{"message": "busy"}]}), httpx.Response(200, json=SUCCESS_BODY)])
    client, requests = make_client(lambda request: next(responses))

    assert client.generate("scene", 64, 32) == IMAGE_BYTES
    assert len(requests) == 2


def test_timeouts_are_retried_then_reported():
    def always_time_out(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    client, requests = make_client(always_time_out)

    with pytest.raises(ImageGenerationError, match=f"after {MAX_ATTEMPTS} attempts; last error: timed out"):
        client.generate("scene", 64, 32)
    assert len(requests) == MAX_ATTEMPTS


def test_a_client_error_fails_at_once_with_cloudflares_message():
    client, requests = make_client(
        lambda request: httpx.Response(400, json={"success": False, "errors": [{"message": "width must be <= 2048"}]})
    )

    with pytest.raises(ImageGenerationError, match="HTTP 400.*width must be <= 2048"):
        client.generate("scene", 4096, 32)
    assert len(requests) == 1


def test_a_reported_failure_is_an_error():
    client, _ = make_client(
        lambda request: httpx.Response(200, json={"success": False, "errors": [{"message": "NSFW prompt"}]})
    )

    with pytest.raises(ImageGenerationError, match="NSFW prompt"):
        client.generate("scene", 64, 32)


def test_invalid_base64_is_an_error():
    client, _ = make_client(lambda request: httpx.Response(200, json={"success": True, "result": {"image": "***"}}))

    with pytest.raises(ImageGenerationError, match="not valid base64"):
        client.generate("scene", 64, 32)
