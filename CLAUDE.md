# AI Content Studio — Hackathon Build (Problem 3)

Full problem statement: `docs/PROBLEM.md`. Read it before planning anything.

Solo build, hard deadline 11pm today. Working end-to-end beats polished-but-partial.

## What we're building
One content brief in → per-channel generated image + native copy (Bengali AND English) for 3 channels →
human approval (with discard/retry) → scheduled → "published" via mock adapters → synthetic metrics ingested →
cross-platform comparison → weekly AI report citing post IDs → report insights feed into the next brief.

## Market
- The brand and audience are in West Bengal, India (Kolkata). Bengali copy uses West Bengal usage, and prompts say so.
- No Bangladesh references anywhere: code, prompts, UI text, sample data, tests or docs (decided 2026-09-26).

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
  - UI is dark only, and must not look AI-generated: no purple/blue gradients, glows, sparkle icons or emoji as icons.
    - Tokens are at the top of `src/index.css`: one warm-gray family, one marigold accent used sparingly, and status colours reserved for post states.
    - Fonts are self-hosted with @fontsource (Archivo for the UI, Hind Siliguri for Bengali, IBM Plex Mono for IDs and numbers). Icons are Phosphor.
    - Confirmations use `useConfirm()` (`src/confirm.ts`), never `window.confirm`. The Studio's New brief composer lives in the main area, next to the brief rail.
- Scheduler: a simple due-posts loop plus a "fast-forward time" demo control (see Publishing below).
- Text generation: Gemini (production; decided 2026-09-26, "Gemini only", reversing that day's earlier switch to OpenAI) via `app/gemini_text.py`.
  - Default models (`app/config.py`): `gemini-3.8-flash` → `3.7-flash` → `3.6-flash` → `3.5-flash` → `3.5-flash-lite`. `.env` can pin one with `GEMINI_TEXT_MODEL` and `GEMINI_TEXT_FALLBACK_MODELS=[]`.
    - Its free tier allows 20 requests per day per model; 503 "high demand" is common. `gemini-2.5-flash` returns 404 for new keys.
  - To swap keys, edit `.env` and restart the backend; `--reload` does not pick up `.env` changes (a reload triggered by a `.py` edit does).
  - Every copy prompt forbids invented facts (a model once made up a shop address), and keeps the brief's spelling of names in headline, caption and hashtags.
    - A model once rebuilt the brief's গড়িয়াহাট as গড়েরহাট from "Gariahat" in the English scene text. There is no code check for this; the approval gate is the backstop.
  - Copy is checked to be in its post's own language, excluding hashtags. A violation gets one corrective retry, then the post fails with the reason.
    - English posts may be at most 25% Bengali letters; Bengali posts must be at least 60% Bengali letters.
    - This was added after a fallback model wrote an English post in Bengali because the brief was in Bengali.
  - OpenAI alternative (`TEXT_PROVIDER=openai`, `app/openai_text.py`): Responses API with structured outputs (`responses.parse(text_format=<Pydantic schema>)`), `gpt-6-sol` falling back to `gpt-6-luna`.
    - The SDK retries connection errors, 429 and 5xx once; still failing moves to the next model. Any other error (a bad request, a 401) fails at once; a 429 with `insufficient_quota` means no API credit.
    - `OPENAI_API_KEY` must come from platform.openai.com with prepaid API credit (a ChatGPT subscription is not API access). About 3 cents per brief at September 2026 prices.
- Image generation: Gemini (details below; needs billing). OpenAI GPT Image (`IMAGE_PROVIDER=openai`) and Cloudflare (`IMAGE_PROVIDER=cloudflare`) remain alternatives.
- **Local development providers** (free and offline): set `TEXT_PROVIDER=ollama` and `IMAGE_PROVIDER=local` in `.env`, then restart the backend.
  - The defaults, `gemini` / `gemini`, are production, and the demo must use them.
  - The UI shows no provider indicator (the header's DEV chip was removed for the demo); check `GET /health` to see which providers are active.
  - Text: Ollama at `OLLAMA_URL` with `OLLAMA_MODEL` (default `gemma3:4b`). The model is unloaded after every call to free the 6 GB GPU.
    - gemma3:4b sometimes derails mid-JSON (a curly quote, then a loop of spaces), so malformed output gets one fresh attempt.
      Output is capped at `OLLAMA_MAX_OUTPUT_TOKENS` (default 1536, about 3x a real answer), so a loop stops in about 30 s.
  - One request at a time on the GPU: the local text and image clients share `LOCAL_GPU_LOCK` (`app/local_gpu.py`), so timeouts measure work, not queueing.
    - Seen live: six posts retried together sent six requests to Ollama, and all six timed out in its queue.
    - A brief whose posts all failed is cheaper to recreate than to retry post by post: each retry makes its own scene call (3 requests for a new brief vs 12 for six retries).
    - It often gives too many hashtags (trimmed at generation, see Publishing) and ignores the scene word count; the checks catch the rest, and the cloud models follow these far better.
  - Images: `tools/local_image_server/`, a separate uv project running SDXL fp16 on the GPU.
    - It takes the same `prompt`/`width`/`height` form as the other image clients and returns a JPEG at exactly that size, one image at a time.
    - Because SDXL reads only the first 77 prompt tokens, it always applies a fixed "no text" negative prompt.
  - The same rules apply to local output: exact size or fail, one image per channel, independent languages, and the language check.
- Secrets: `.env` only, read through `app/config.py`. Names are in `.env.example`.
  - Each provider needs ONE key for both text and images (a test enforces it): `GEMINI_API_KEY` (old name `GEMINI_TEXT_API_KEY` still accepted) or `OPENAI_API_KEY`.
  - `CF_ACCOUNT_ID` and `CF_API_TOKEN` only for Cloudflare images. The local providers need no key.
  Never hardcode, print, or commit API keys.

## Image generation
- **API:** Gemini `gemini-3.1-flash-image` → `gemini-3.1-flash-lite-image` (`app/gemini_images.py`), same key as text. No free tier (429 on every call without billing).
  - It takes a ratio from a fixed list (1:1, 2:3, 3:2, 3:4, 4:3, 4:5, 5:4, 9:16, 16:9, 21:9), never a pixel size, so the client asks for the nearest listed ratio. channels.json holds its measured sizes; it returns JPEG, 3.5-5 s per image.
- **Sizes:** request each channel's exact `width`/`height` from channels.json. Generation fails any image that comes back at another size; never resize or crop (rule 1).
  - LinkedIn was dropped (2026-09-26) while Gemini images were planned: its 1.91:1 isn't a Gemini ratio, and the problem statement doesn't require it. Facebook (1:1) replaced it and stays.
- **OpenAI alternative:** `gpt-image-2.5-flare` (`app/openai_images.py`): `images.generate(model, prompt, size="WIDTHxHEIGHT", quality, output_format="jpeg", n=1)`, base64 in `data[0].b64_json`.
  - Any size with sides that are multiples of 16, a ratio from 1:3 to 3:1 and 655,360 to 8,294,400 pixels, so each channel's exact size is requested directly.
  - `OPENAI_IMAGE_QUALITY` (default `medium`; `low` / `high`) trades sharpness against time and cost ($30 per million output tokens); HTTP timeout 180s.
- **Cloudflare alternative:** `@cf/black-forest-labs/flux-2-klein-4b` via `POST .../accounts/{CF_ACCOUNT_ID}/ai/run/...` (multipart `prompt`, `width`, `height`; base64 JPEG in `result.image`).
  - It returns any multiple-of-16 size exactly, ~17s warm, ~60s cold. It occasionally times out several times in a row, then recovers.
- **Jobs:** generate the 3 channels in parallel as background jobs; the UI shows a per-post "generating" state.
  - Each brief gets one image per channel (3 generations). That channel's bn and en posts share it, and each gets its own headline overlay.
  - A failed or timed-out job sets the post's `generation_status` to `failed` with the error message. It never leaves a post stuck in `generating`.
- **Scene first, then copy** (`app/prompts.py`). One scene call plans every channel's photo. Each language's copy call then gets those scene descriptions and writes the headline and caption for the photo.
  - Rule 6 still holds: neither language ever sees the other's copy, and both get the same English scene text, which they are told not to translate or state as product facts.
  - Cost is unchanged (3 text calls per brief, 2 per retry). Copy waits for the scene call, and if the scenes fail no copy call is made.
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

## Publishing (milestone 4)
- **Adapters** (`app/adapters.py`): one mock adapter per channel, built from channels.json. It checks what would actually be sent, and rejects every violation with an explicit reason.
  - It checks: the final image file (readable, aspect ratio ±2%, file size), caption plus hashtags length (X weighted), and hashtag count (inline `#tags` included).
  - It never resizes, recompresses or trims (rule 3).
  - Generation uses the same `caption_violations()`, so a generated post is never rejected for its copy.
  - Before that check, generation fits hashtags to the limit (`_normalized()` in `app/generation_service.py`): hashtag-only lines at the end of a caption move into the hashtags, then the model's first tags are kept.
    - Hashtags inside sentences are never removed (that would rewrite copy), so too many of those still fails. This happens before human review; the adapters still reject and never trim.
- **Publisher** (`app/publisher.py`): due `scheduled` posts go through their adapter and move to `published` (with `published_at`) or `rejected` (with `rejection_reason`), only via `transition()`.
  - A background loop runs every `SCHEDULER_INTERVAL_SECONDS` (5).
  - A lock keeps the loop and the manual controls from publishing a post twice.
- **Clock** (`app/clock.py`): real UTC plus an in-memory fast-forward offset (a restart resets it). The UI header's clock has +1h, +1d, a reset-to-current-time icon button and "Publish due"; each run's summary shows as a toast.
  - Endpoints: `GET /clock`, `POST /clock/advance {hours}`, `POST /clock/reset`, `POST /publisher/run-due`.
  - After a reset, posts published during the fast-forward have later timestamps than "now". Their metrics pause until real time catches up, and the report window has no upper bound, so they stay in reports.
- **Adapter test bench**: an experiment corner for the hackathon, not part of the product flow. The tab is set apart (divider, flask icon, "Experiment" tag),
  and the page opens with the problem statement's toughest-test sentence and which control breaks each constraint (limits read from channels.json).
  - The UI tab ("Adapter bench") and `POST /adapters/{channel}/submit` (multipart: `caption`, `hashtags`, `image`) send anything straight to an adapter. Nothing is stored.
  - It returns 200 when accepted, or 422 with `detail.reasons` and the measurements. This is how the demo shows a violating post being rejected.
  - Sample text is Durga Puja themed for a Kolkata shop, in Bengali (West Bengal usage) and English; clicking the chosen sample again restores it.
  - Presets make an exact-size image, a wrong-ratio image (square, or 2:1 for square Facebook), a noise PNG sized past the channel's file limit,
    and a caption exactly 20 over the limit (hashtag line and NFC normalisation included, as the adapter counts).
- UI: approved posts get a Schedule control (now / in 1 hour / in 1 day, from the demo clock). Cards show the scheduled or published time, or the rejection reason.

## Analytics (milestone 5)
- **Synthetic metrics** (`config/synthetic_metrics.json`, `app/synthetic_metrics.py`) are not real data. Each mock adapter's `fetch_metrics()` reports them.
  - Channel profiles: Instagram has the widest reach and mostly likes; Facebook reaches a little less but draws the most comments, shares and clicks; X reaches fast with the lowest engagement rate.
  - Totals grow as 1 - exp(-hours / hours_to_63_percent_reach) (X in hours, Facebook over about a day), and are seeded by post id and channel, so they are repeatable.
  - **Deliberate, documented patterns** for the weekly report to find:
    - Bengali gets 1.35x engagement on Instagram.
    - Facebook posts with 4 or more hashtags get 0.7x engagement.
    - X posts of 140 weighted characters or fewer get 1.6x clicks.
- **Ingestion** (`app/analytics.py`): every publishing run (background loop, fast-forward, "Publish due now") snapshots each published post into `metrics`, at most once per `snapshot_interval_minutes` (30) of demo time.
- **Comparison** (`GET /briefs/{id}/comparison`): like-for-like, meaning the same brief and language, one column per channel, using each post's latest snapshot.
  - Posts are ranked by **rates, never raw totals**: engagement rate = (likes + comments + shares) / impressions, click-through rate = clicks / impressions.
  - Channel summaries pool totals (sums over sums). Posts without impressions show but aren't ranked.
  - The UI shows it as "Performance across channels" under the brief.
- **Channel feeds** (`GET /feeds`, "Channel feeds" tab): each mock channel's published posts, rendered in that platform's style (labelled "mock"), with live metrics. This is the demo's proof that a post was "posted".

## Weekly report and insights (milestone 6)
- **Report** (`app/reporting.py`, `POST /reports`, "Reports" tab): covers posts published in the last 7 days of the demo clock, with their latest metrics.
  - Code computes pooled rates per group (channel, channel x language, channel x hashtags 0-3 vs 4+, channel x length up to 140 vs longer), with the post IDs behind each.
  - One text-model call (the same client as generation: Gemini in production, Ollama in dev) returns a summary, findings and 1-4 insights, each with `post_ids`.
- **Citation validation (rule 5)**: every claim must cite at least one post ID, and every cited ID, including any `#123` written in the text, must be a post in that week's evidence.
- **Like-for-like**: the prompt lists each brief's posts per language side by side ("like-for-like sets") and forbids comparing channels across languages.
  - Code checks findings and insights: one citing several channels and several languages must cite every one of those channels in every one of those languages. The summary is exempt.
  - Added after a report ranked a Bengali Instagram post against English Facebook and X posts, and advised "Lead with Instagram".
- Either kind of problem regenerates the report with the problems as feedback, up to `MAX_REPORT_ATTEMPTS` (3). After that the API returns 502 and nothing is saved.
  - Numbers are not verified; only citations and like-for-like are.
  - No published posts gives 409, and no model call is made.
  - Stored as `reports.body` (JSON: summary, findings, insights with post_ids) plus `cited_post_ids`, and one `insights` row per insight.
- **Insights into the next brief (rule 4)**: `GET /insights/latest` feeds the brief form's "Insights from the latest report" checkboxes, ticked by default.
  - The chosen `insight_ids` go in `POST /briefs`. They're saved on the brief as `insights_used` ({id, report_id, text}), shown on the brief view, and injected into the scene prompt and both copy prompts ("What worked before").
- **Report page** ("Reports" tab, `#reports`):
  - The report also stores its evidence (per-post metrics and group rates) in `reports.body`, so the charts show exactly the numbers the model was given.
  - Layout: stat tiles, the summary as a callout, four grouped bar charts (engagement rate and click-through rate by channel x language; hashtag count vs engagement; post length vs clicks), numbered findings with a bold lead sentence, a "Do next" insight list, and a collapsible table of every post.
  - Charts follow the dataviz skill: the reference palette's dark steps for slots 1-4, validated as pairs (1-2, 3-4) against the #171614 card; every bar also carries its value label. Each chart has a legend, a hover/focus tooltip and a table-view toggle.
  - While a report is being written: a bordered panel with a progress bar, a spinner and an elapsed timer, the button reads "Writing…", the Reports tab shows a pulsing dot, and older reports dim. The view stays mounted when hidden, so switching tabs doesn't lose it. Older reports fold into one-line rows.
- With only a couple of published posts, a small model's analysis is thin (seen with gemma3:4b: a wrong number, an unsupported claim). The demo needs a week of published posts (M7).

## Deleting (`app/deletion.py`)
- `DELETE /briefs/{id}` ("Delete brief" on the brief view) removes the brief, all its posts (retry chains included), their metrics, and `media/briefs/{id}/`.
  - It also removes any report citing those posts, with its insights, so no stored report cites a missing post (rule 5).
  - It's refused with 409 while any of its posts is pending or generating.
- `DELETE /reports/{id}` ("Delete report") removes the report and its insights; the previous report's insights become the latest. Briefs keep the insight text they applied.
- `POST /posts/{id}/take-down` ("Take down" on feed posts and published post cards) moves a published post back to approved, clears `published_at`, `scheduled_at` and its metrics, and deletes reports citing it.
  - The post can then be scheduled and published again, with metrics from zero. This replays the demo without regenerating anything, so it costs no quota.
  - A re-published post starts at 0 because `published_at` is when the publishing run happened; the next fast-forward grows it.

## Single sources of truth
- `backend/config/channels.json`: channel specs (image width/height, aspect ratio + tolerance, max file MB, caption limit, hashtag limit).
  - Used by BOTH generation and adapter validation. No limits hardcoded anywhere else.
  - Sizes are what Gemini's 1K tier returns for each ratio (measured 2026-09-26 with gemini-3.1-flash-lite-image): Instagram 928×1152 (4:5, +0.7%),
    Facebook 1024×1024 (1:1), X 1376×768 (16:9, +0.8%). All are multiples of 16 that GPT Image, Cloudflare and local SDXL also produce exactly; a test checks GPT Image's rules.
  - Aspect-ratio tolerance is ±2%.
- `ALLOWED_TRANSITIONS` + `transition(post, new_status)` in `app/post_status.py`: the ONLY way post status changes (a test enforces it).
  - States: draft → approved | discarded; approved → scheduled; scheduled → published | rejected; published → approved (take-down, so it can be scheduled again).
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
4. ✅ (2026-09-26) Mock adapters + validation + scheduler. Test: an oversized caption and a wrong-ratio image are each rejected with a reason.
5. ✅ (2026-09-26) Synthetic metrics (seeded, platform-realistic) + side-by-side comparison per brief using normalized rates (engagement rate), not raw totals.
6. ✅ (2026-09-26) Weekly report with citation validation → insights table → insights visible on and injected into the brief form.
7. End-to-end demo run + cached fallback assets in case generation is slow live.

Feature freeze after milestone 7. Bug fixes only after that.

## Commands
- Backend tests (from `backend/`): `uv run pytest -q`
- API (from `backend/`): `uv run uvicorn app.main:app --reload` (`GET /health`, docs at `/docs`)
- UI (from `frontend/`): `npm run dev`, then open http://localhost:5173. Type-check and build with `npm run build`, lint with `npm run lint`.
  - Tabs are in the URL hash (`#studio`, `#feeds`, `#reports`, `#bench`). `BACKEND_URL=http://localhost:8001 npx vite --port 5174` points a second dev server at a test backend.
- Local image server, dev only (from `tools/local_image_server/`): `uv run uvicorn server:app --port 8100`. The first start downloads SDXL (about 7 GB).
- Local text model, dev only: `ollama pull gemma3:4b` once. Ollama itself runs as a system service.

## How to work
- Small steps. Show the plan before large changes.
- Write a test for every rule in "Non-negotiable rules."
- Real error handling on every external API call (timeouts, retries, clear error messages). No bare `except:`.
- Descriptive names. No magic numbers.
- Don't cut a feature or change scope without asking me first.
- If something in the problem statement is ambiguous, ask. Don't guess silently.
