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
- Backend: FastAPI + SQLite (SQLAlchemy or sqlmodel). No Postgres, Redis, Celery, or auth.
- Frontend: React (Vite). Plain, functional UI.
- Scheduler: APScheduler or a simple due-posts loop, plus a "fast-forward time" demo control.
- Secrets: `.env` only. Never hardcode, print, or commit API keys.

## Single sources of truth
- `backend/config/channels.json` — channel specs (size, aspect ratio, max file MB, caption limit, hashtag limit).
  Used by BOTH generation and adapter validation. No limits hardcoded anywhere else.
- `ALLOWED_TRANSITIONS` + `transition(post, new_status)` — the ONLY way post status changes.
  States: draft → approved | discarded; approved → scheduled; scheduled → published | rejected.
  Retry = new draft with `parent_post_id` pointing to the discarded one.

## Data model
- briefs: id, title, goal, audience, languages, tone, insights_used (JSON), created_at
- posts: id, brief_id, channel, language, caption, hashtags, image_path, width, height, file_size_bytes, status, rejection_reason, parent_post_id, scheduled_at, published_at
- metrics: post_id, fetched_at, impressions, likes, comments, shares, clicks
- reports: id, week_start, body, cited_post_ids (JSON)
- insights: id, report_id, text, created_at

## Milestones (do ONE at a time; stop and report when each done-check passes)
1. Schema, channels.json, transition() + test: scheduling an unapproved post is refused.
2. Generation: per-channel image + caption, Bengali + English, for one brief. Test: 3 images have 3 different sizes, generated separately.
3. Approval UI: approve / discard / retry (retry keeps lineage).
4. Mock adapters + validation + scheduler. Test: an oversized caption and a wrong-ratio image are each rejected with a reason.
5. Synthetic metrics (seeded, platform-realistic) + side-by-side comparison per brief using normalized rates (engagement rate), not raw totals.
6. Weekly report with citation validation → insights table → insights visible on and injected into the brief form.
7. End-to-end demo run + cached fallback assets in case generation is slow live.

Feature freeze after milestone 7. Bug fixes only after that.

## How to work
- Small steps. Show the plan before large changes.
- Write a test for every rule in "Non-negotiable rules."
- Real error handling on every external API call (timeouts, retries, clear error messages). No bare `except:`.
- Descriptive names. No magic numbers.
- Don't cut a feature or change scope without asking me first.
- If something in the problem statement is ambiguous, ask. Don't guess silently.
