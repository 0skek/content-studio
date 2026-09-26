"""One request at a time on the laptop GPU, shared by the local text and image clients (development only).

Ollama and the local image server each queue requests themselves, but a queued request's HTTP timeout keeps
running while it waits: six retries clicked at once all timed out in Ollama's queue. Holding this lock around each
request means a timeout measures only the work itself, and text and images never compete for video memory.
"""

import threading

LOCAL_GPU_LOCK = threading.Lock()
