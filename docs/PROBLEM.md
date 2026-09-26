# Problem 3 — AI Content Studio & Multi-Platform Command Center

*Track: Content Ops / Generative AI*

Four integrated modules — Generative Studio, Publisher, Analytics Store, Cross-Platform Insights — that turn a single content brief into on-brand generated assets, platform-tailored captions, scheduled posts, unified engagement metrics, and a weekly report that feeds insights back into the next brief.

## Must get right

| Area | Requirement |
| --- | --- |
| **Generation** | Visual and copy must differ meaningfully per channel (tone, length, hashtag convention, CTA) — Bengali and English are both natively generated, not translated |
| **Approval gate** | Nothing enters the publishing queue without explicit human approval; a discard-and-retry loop exists before that point |
| **Comparison** | Cross-platform insights compare like-for-like content side by side, not just separate per-platform totals |

## MVP scope

Brief in → generated image/video + tailored copy for 3 channels → approved → scheduled → "published" via mock channel adapter → metrics ingested → one cross-platform comparison + one weekly AI-written report, every claim citing post IDs.

## Toughest test

A Bengali brief is checked for genuinely native-sounding output, not machine translation. A post that violates a platform constraint (aspect ratio, file size, character limit) is submitted to the adapter layer and must be rejected, not silently accepted.

## Auto-disqualifiers

- One generated image cropped/relabeled per platform and called "tailored"
- Generation with no approval gate before scheduling
- Insights that live on a dashboard but never reach brief creation

---

## Our interpretation (not part of the official statement)

These are our working assumptions. If anything here conflicts with the official text above, the official text wins.

- Publishing uses **mock** channel adapters; no real social media APIs.
- Metrics are **synthetic** (seeded, platform-realistic), ingested through each adapter.
- Image generation alone satisfies "image/video"; video is optional and the first thing cut if time runs short.
- Channels: Instagram, Facebook, X. (LinkedIn was dropped while Gemini images were planned, since its 1.91:1 ratio isn't one Gemini produces; the statement doesn't require it.)
- "Like-for-like" means the same brief's posts compared across channels using normalized rates (e.g. engagement rate), not raw totals.
- "Reach brief creation" means insights are both visible on the brief form and injected into the generation prompt.
