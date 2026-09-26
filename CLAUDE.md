# AI Content Studio — Hackathon Build (Problem 3)

Full problem statement: `docs/PROBLEM.md`. Read it before planning anything.

Solo build, hard deadline 11pm today. Working end-to-end beats polished-but-partial.

## What we're building
One content brief in → per-channel generated image + native copy (Bengali AND English) for 3 channels →
human approval (with discard/retry) → scheduled → "published" via mock adapters → synthetic metrics ingested →
cross-platform comparison → weekly AI report citing post IDs → report insights feed into the next brief.

## Non-negotiable rules (these are auto-disqualifiers — never violate)
1. **Separate image generation per channel** at that channel's native size. NEVER generate one image and crop/resize it per channel.
2. **Approval gate enforced in the backend.** Only `approved` posts can be scheduled. The API must reject it, not just the UI.
3. **Adapters must REJECT constraint violations** (aspect ratio, file size, caption length, hashtag count) with an explicit reason. Never silently accept or auto-fix.
4. **Insights must flow into brief creation**: shown on the brief form AND injected into the generation prompt.
5. **Every claim in the weekly report cites real post IDs.** Validate citations in code; regenerate if any cited ID doesn't exist.
6. **Bengali is written natively**, never translated from English. Generate each language independently.

## Stack (keep it boring)
- Backend: FastAPI + SQLite via SQLAlchemy 2.0; uv project in `backend/`. No Postgres, Redis, Celery, or auth.
  Tables come from `create_all()`, with no migrations: after a schema change, delete `backend/data/content_studio.db`.
- Frontend: React (Vite) + TypeScript in `frontend/`, plain CSS. The Vite dev server proxies API and `/media` paths to the backend on :8000.
- Scheduler: APScheduler or a simple due-posts loop, plus a "fast-forward time" demo control.
- Text generation: Gemini via `google-genai` on the free-tier key. No billing: don't enable or rely on it without asking me.
  - Model chain (set in `app/config.py`): `gemini-3.8-flash` → `3.7-flash` → `3.6-flash` → `3.5-flash` → `3.5-flash-lite`.
    - An overloaded model (5xx) gets one retry. A model out of quota (429) or gone (404) is skipped at once. `gemini-2.5-flash` returns 404 for new keys.
  - **The free tier allows 20 requests per day per model** (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`). The quota resets at midnight Pacific.
    - Each brief costs 3 requests and each retry 2, so budget live testing.
    - To swap keys, edit `GEMINI_TEXT_API_KEY` in `.env` and restart the backend; `--reload` does not pick up `.env` changes.
  - 503 "high demand" from Gemini is common. Every copy prompt forbids invented facts (the model once made up a shop address).
  - Copy is checked to be in its post's own language, excluding hashtags. A violation gets one corrective retry, then the post fails with the reason.
    - English posts may be at most 25% Bengali letters; Bengali posts must be at least 60% Bengali letters.
    - This was added after a fallback model wrote an English post in Bengali because the brief was in Bengali.
  - Cloudflare occasionally times out several times in a row (seen 2026-09-26), then recovers. The post fails with the reason and can be retried.
- Image generation: Cloudflare Workers AI (details below).
- **Local development providers** (to save the free quota): set `TEXT_PROVIDER=ollama` and `IMAGE_PROVIDER=local` in `.env`, then restart the backend.
  - The defaults, `gemini` / `cloudflare`, are production, and the demo must use them.
  - While a dev provider is active, the UI header shows a yellow "DEV" chip.
  - Text: Ollama at `OLLAMA_URL` with `OLLAMA_MODEL` (default `gemma3:4b`). The model is unloaded after every call to free the 6 GB GPU.
    - gemma3:4b sometimes derails mid-JSON (a curly quote, then a loop of spaces), so malformed output gets one fresh attempt.
      Output is capped at `OLLAMA_MAX_OUTPUT_TOKENS` (default 1536, about 3x a real answer), so a loop stops in about 30 s.
  - One request at a time on the GPU: the local text and image clients share `LOCAL_GPU_LOCK` (`app/local_gpu.py`), so timeouts measure work, not queueing.
    - Seen live: six posts retried together sent six requests to Ollama, and all six timed out in its queue.
    - A brief whose posts all failed is cheaper to recreate than to retry post by post: each retry makes its own scene call (3 requests for a new brief vs 12 for six retries).
    - It often breaks hashtag limits and ignores the scene word count; the checks catch it, and Gemini follows these far better.
  - Images: `tools/local_image_server/`, a separate uv project running SDXL fp16 on the GPU.
    - It takes the same `prompt`/`width`/`height` form as Cloudflare and returns a JPEG at exactly that size, one image at a time.
    - Because SDXL reads only the first 77 prompt tokens, it always applies a fixed "no text" negative prompt.
  - The same rules apply to local output: exact size or fail, one image per channel, independent languages, and the language check.
- Secrets: `.env` only, read through `app/config.py`. Names are in `.env.example`: `GEMINI_TEXT_API_KEY`, `CF_ACCOUNT_ID`, `CF_API_TOKEN`.
  Never hardcode, print, or commit API keys.

## Image generation
- **API:** Cloudflare Workers AI, model `@cf/black-forest-labs/flux-2-klein-4b`.
  - Request: `POST https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/run/@cf/black-forest-labs/flux-2-klein-4b`
    with `Authorization: Bearer {CF_API_TOKEN}` and a multipart form (`prompt`, `width`, `height`).
  - Response: JSON with a base64 JPEG in `result.image`.
- **Timing:** ~17s warm, ~60s cold. HTTP timeout 90s.
- **Sizes:** request each channel's exact `width`/`height` from channels.json. The model returns exactly that size (verified for all 3 channels), so never resize or crop afterwards.
- **Jobs:** generate the 3 channels in parallel as background jobs; the UI shows a per-post "generating" state.
  - Each brief gets one image per channel (3 generations). That channel's bn and en posts share it, and each gets its own headline overlay.
  - A failed or timed-out job sets the post's `generation_status` to `failed` with the error message. It never leaves a post stuck in `generating`.
- **Scene first, then copy** (`app/prompts.py`). One scene call plans every channel's photo. Each language's copy call then gets those scene descriptions and writes the headline and caption for the photo.
  - Rule 6 still holds: neither language ever sees the other's copy, and both get the same English scene text, which they are told not to translate or state as product facts.
  - Cost is unchanged (3 Gemini calls per brief, 2 per retry). Copy waits for the scene call, and if the scenes fail no copy call is made.
  - The scene prompt's art direction is adapted from `docs/generation_prompts.md`, a 5-stage chain for an image model that renders its own text.
    - We keep our design: one scene call, text-free images, headlines set in code.
    - We took: a literal and culturally specific subject, the goal choosing the moment, avoiding stock clichés, one decisive light, a dominant/secondary/accent palette, an off-centre subject with a designed quiet zone, unbranded clothes and packaging, and no invented face for a named real person.
- **Headline zone:** the scene call also picks `text_zone` per channel: top or bottom, and for wide images also left or right. An invalid zone falls back to bottom.
  - The image prompt then states that zone is quiet, empty space with no people (`HEADLINE_ZONE_CLAUSES`), and the scene is told to start with its composition, since SDXL reads only 77 tokens.
- **No text in images:** image prompts must request NO text/letters/typography, and no brand names on clothes or packaging.
  - The model can still draw pseudo-text on signage in busy street/market scenes, so prefer compositions without signs.
  - The approval gate catches the rest.
- **Headline overlay** (`app/headline_overlay.py`): headlines are set in code, integrated into the photo rather than on a box.
  - Placement: candidate spots are centred at the top or bottom, and for wide images the left or right column (upper, middle or lower). All sit inside a 7% safe margin.
    - The headline never covers a detected face. OpenCV Haar detectors run frontal, profile, and mirrored profile (`opencv-python-headless` 4.x; OpenCV 5 dropped them).
    - Among face-free spots, the scene's zone wins unless it came out clearly busier than the calmest spot (edge strength).
  - Legibility: the soft gradient scrim is tinted from the photo's own colour behind the text and fades into the photo. It is only as strong as a 3.2:1 contrast needs, and busy areas always get a strong one.
  - Calm, light areas get dark text; everything else gets warm white with a soft shadow. A short accent line above the headline takes the photo's most vivid colour.
  - Bengali needs proper shaping: use Pillow with libraqm (`layout_engine=ImageFont.Layout.RAQM`), which is verified working on this machine. Pillow's BASIC layout breaks conjuncts (র্ষ, ক্ষ্য) and reorders vowel signs. HTML/Playwright is the fallback if raqm is unavailable.
  - Noto Sans Bengali has no Latin glyphs and Pillow has no font fallback, so each headline is split into script runs: Bengali characters use Noto Sans Bengali, everything else uses Noto Sans. Both fonts are bundled in `backend/assets/fonts/`.
- **Measurements:** `width`, `height`, and `file_size_bytes` are measured from the final (overlaid) file, because that's what the adapters validate.
- **Files:** `backend/media/briefs/{brief_id}/` holds the raw `{channel}-base-post{ids}.jpg` images (named after the posts built from them, so retries never overwrite one) and the final `{channel}-{language}-post{post_id}.jpg` posts. The app serves them at `/media`; the folder is gitignored.

## Single sources of truth
- `backend/config/channels.json`: channel specs (image width/height, aspect ratio + tolerance, max file MB, caption limit, hashtag limit).
  - Used by BOTH generation and adapter validation. No limits hardcoded anywhere else.
  - Sizes are multiples of 16 that the image model returns exactly: Instagram 1024×1280 (4:5), LinkedIn 1344×704 (1.91:1), X 1536×864 (16:9).
  - Aspect-ratio tolerance is ±2%.
- `ALLOWED_TRANSITIONS` + `transition(post, new_status)` in `app/post_status.py`: the ONLY way post status changes (a test enforces it).
  - States: draft → approved | discarded; approved → scheduled; scheduled → published | rejected.
  - Retry = new draft with `parent_post_id` pointing to the discarded one.
    - A draft whose generation failed can be retried directly; it is discarded first.
    - Each post can be retried once (`parent_post_id` is unique), so each channel/language slot's history is a chain.
    - A retry regenerates only that post: one image plus its copy.
  - Generation progress is a separate field (`generation_status`), not a post status. Only drafts whose generation is `ready` can be approved, and `transition()` enforces this itself.

## Data model
All timestamps are stored in UTC.
- briefs: id, title, goal, audience, languages, tone, insights_used (JSON), created_at
- posts: id, brief_id, channel, language, headline, caption, hashtags, image_prompt, image_path, width, height, file_size_bytes, generation_status (pending | generating | ready | failed), generation_error, status, rejection_reason, parent_post_id, scheduled_at, published_at
- metrics: id, post_id, fetched_at, impressions, likes, comments, shares, clicks
- reports: id, week_start, body, cited_post_ids (JSON)
- insights: id, report_id, text, created_at

## Milestones (do ONE at a time; stop and report when each done-check passes)
1. ✅ (2026-09-26) Schema, channels.json, transition() + test: scheduling an unapproved post is refused.
2. ✅ (2026-09-26) Generation: per-channel image (parallel background jobs, per-post "generating" state, headline overlay) + caption, Bengali + English, for one brief. Test: 3 images have 3 different sizes, generated separately.
3. ✅ (2026-09-26) Approval UI: approve / discard / retry (retry keeps lineage).
4. Mock adapters + validation + scheduler. Test: an oversized caption and a wrong-ratio image are each rejected with a reason.
5. Synthetic metrics (seeded, platform-realistic) + side-by-side comparison per brief using normalized rates (engagement rate), not raw totals.
6. Weekly report with citation validation → insights table → insights visible on and injected into the brief form.
7. End-to-end demo run + cached fallback assets in case generation is slow live.

Feature freeze after milestone 7. Bug fixes only after that.

## Commands
- Backend tests (from `backend/`): `uv run pytest -q`
- API (from `backend/`): `uv run uvicorn app.main:app --reload` (`GET /health`, docs at `/docs`)
- UI (from `frontend/`): `npm run dev`, then open http://localhost:5173. Type-check and build with `npm run build`, lint with `npm run lint`.
- Local image server, dev only (from `tools/local_image_server/`): `uv run uvicorn server:app --port 8100`. The first start downloads SDXL (about 7 GB).
- Local text model, dev only: `ollama pull gemma3:4b` once. Ollama itself runs as a system service.

## How to work
- Small steps. Show the plan before large changes.
- Write a test for every rule in "Non-negotiable rules."
- Real error handling on every external API call (timeouts, retries, clear error messages). No bare `except:`.
- Descriptive names. No magic numbers.
- Don't cut a feature or change scope without asking me first.
- If something in the problem statement is ambiguous, ask. Don't guess silently.
