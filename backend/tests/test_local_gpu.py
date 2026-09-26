"""The local text and image clients share one laptop GPU, so they never have two requests in flight at once.

Seen live: six retries clicked together sent six requests to Ollama, which queued them, and every one timed out
while still waiting.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

from app.local_images import LocalImageClient
from app.ollama_text import OllamaTextClient
from app.prompts import ChannelScene, SceneSet
from tests.fakes import make_jpeg

REQUESTS_PER_CLIENT = 3
SIMULATED_WORK_SECONDS = 0.05
SCENES = SceneSet(scenes=[ChannelScene(channel="x", text_zone="right", scene="A wide festive scene")])


def test_local_text_and_image_requests_never_overlap():
    counter_lock = threading.Lock()
    in_flight = peak = 0

    def gpu_server(request: httpx.Request) -> httpx.Response:
        nonlocal in_flight, peak
        with counter_lock:
            in_flight += 1
            peak = max(peak, in_flight)
        time.sleep(SIMULATED_WORK_SECONDS)
        with counter_lock:
            in_flight -= 1
        if request.url.path == "/api/chat":
            return httpx.Response(200, json={"message": {"content": SCENES.model_dump_json()}, "done": True})
        return httpx.Response(200, content=make_jpeg(64, 32))

    transport = httpx.MockTransport(gpu_server)
    text = OllamaTextClient(
        base_url="http://ollama.test", model="gemma3:4b", timeout_seconds=1, max_output_tokens=64,
        http_client=httpx.Client(transport=transport),
    )
    images = LocalImageClient(base_url="http://images.test", timeout_seconds=1, http_client=httpx.Client(transport=transport))

    with ThreadPoolExecutor(max_workers=2 * REQUESTS_PER_CLIENT) as pool:
        calls = [pool.submit(text.generate, "scenes", SceneSet) for _ in range(REQUESTS_PER_CLIENT)]
        calls += [pool.submit(images.generate, "a scene", 64, 32) for _ in range(REQUESTS_PER_CLIENT)]
        results = [call.result() for call in calls]

    assert results[:REQUESTS_PER_CLIENT] == [SCENES] * REQUESTS_PER_CLIENT
    assert peak == 1
