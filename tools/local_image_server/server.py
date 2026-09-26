"""Dev-only local image server: SDXL on the local GPU, taking the same form fields as Cloudflare Workers AI.

The backend uses it when IMAGE_PROVIDER=local. It lives in its own process so backend reloads never reload the
model, and PyTorch stays out of the backend's dependencies.

Run from this folder:  uv run uvicorn server:app --port 8100
The first start downloads about 7 GB of model weights into the Hugging Face cache.
"""

import io
import logging
import os
import threading
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

# Must be set before torch loads; reduces fragmentation on the 6 GB GPU.
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

import torch  # noqa: E402
from diffusers import AutoencoderKL, StableDiffusionXLPipeline  # noqa: E402
from fastapi import FastAPI, Form, HTTPException, status  # noqa: E402
from fastapi.responses import Response  # noqa: E402

MODEL_ID = os.environ.get("LOCAL_IMAGE_MODEL", "stabilityai/stable-diffusion-xl-base-1.0")
# The stock SDXL VAE overflows in fp16 and can return black images; this one is fixed for fp16.
VAE_ID = os.environ.get("LOCAL_IMAGE_VAE", "madebyollin/sdxl-vae-fp16-fix")
INFERENCE_STEPS = int(os.environ.get("LOCAL_IMAGE_STEPS", "25"))
GUIDANCE_SCALE = float(os.environ.get("LOCAL_IMAGE_GUIDANCE", "6.0"))
# SDXL reads only the first 77 tokens of a prompt, so the "no text" clause at the end of our prompts is often cut
# off. The negative prompt keeps text out regardless.
# The defect terms are the people-related ones from docs/generation_prompts.md.
NEGATIVE_PROMPT = (
    "text, letters, words, numbers, typography, caption, watermark, logo, brand name, signage, signboard, "
    "low quality, blurry, flat lighting, malformed hands, extra fingers, fused fingers, asymmetric eyes, "
    "waxy skin, duplicated faces"
)
SIZE_MULTIPLE = 8
MAX_SIDE_PIXELS = 2048
JPEG_QUALITY = 92

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("local_image_server")

pipeline_holder: dict[str, StableDiffusionXLPipeline] = {}
# 6 GB of video memory fits one image at a time; parallel requests queue here.
generation_lock = threading.Lock()


def load_pipeline() -> StableDiffusionXLPipeline:
    if not torch.cuda.is_available():
        raise RuntimeError("PyTorch sees no CUDA GPU; this server needs one.")
    vae = AutoencoderKL.from_pretrained(VAE_ID, torch_dtype=torch.float16)
    pipeline = StableDiffusionXLPipeline.from_pretrained(
        MODEL_ID, vae=vae, torch_dtype=torch.float16, variant="fp16", use_safetensors=True
    )
    # The UNet is 5.1 GB in fp16, more than a 6 GB laptop GPU has free next to the desktop. Stored as fp8 it is
    # ~2.6 GB; each layer is cast back to fp16 only while it computes.
    pipeline.unet.enable_layerwise_casting(storage_dtype=torch.float8_e4m3fn, compute_dtype=torch.float16)
    # Only the component in use sits on the GPU, and decoding runs in tiles: that is what fits 6 GB.
    pipeline.enable_model_cpu_offload()
    pipeline.vae.enable_tiling()
    return pipeline


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    started = time.monotonic()
    logger.info("Loading %s (first run downloads it)...", MODEL_ID)
    pipeline_holder["pipeline"] = load_pipeline()
    logger.info("Model ready in %.0fs on %s", time.monotonic() - started, torch.cuda.get_device_name(0))
    yield


app = FastAPI(title="Local image server (dev only)", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str | int | bool]:
    return {"status": "ok", "model": MODEL_ID, "loaded": "pipeline" in pipeline_holder, "steps": INFERENCE_STEPS}


@app.post("/generate")
def generate(prompt: str = Form(...), width: int = Form(...), height: int = Form(...)) -> Response:
    """Return a JPEG at exactly width x height; never resized, like the Cloudflare model."""
    for name, value in (("width", width), ("height", height)):
        if value <= 0 or value > MAX_SIDE_PIXELS or value % SIZE_MULTIPLE:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"{name} must be a positive multiple of {SIZE_MULTIPLE} up to {MAX_SIDE_PIXELS}, got {value}",
            )
    with generation_lock:
        started = time.monotonic()
        try:
            image = pipeline_holder["pipeline"](
                prompt=prompt,
                negative_prompt=NEGATIVE_PROMPT,
                width=width,
                height=height,
                num_inference_steps=INFERENCE_STEPS,
                guidance_scale=GUIDANCE_SCALE,
            ).images[0]
        except torch.cuda.OutOfMemoryError as error:
            torch.cuda.empty_cache()
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, f"GPU out of memory at {width}x{height}: {error}"
            ) from error
    if image.size != (width, height):
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, f"Pipeline returned {image.size}, expected {(width, height)}"
        )
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=JPEG_QUALITY)
    logger.info("Generated %dx%d in %.1fs", width, height, time.monotonic() - started)
    return Response(content=output.getvalue(), media_type="image/jpeg")
