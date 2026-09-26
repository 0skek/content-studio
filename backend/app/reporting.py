"""The weekly report (rule 5): an AI-written analysis in which every claim cites real post IDs, checked in code.

1. Evidence is computed in code: every post published in the last 7 days of the demo clock, with its latest
   metrics, plus pooled rates for groups of posts (channel, channel x language, hashtag count, caption length).
2. One text-model call writes a summary, findings and actionable insights, each citing post IDs. The report
   stores this evidence too, so its charts show exactly the numbers the model was given.
3. Citations are validated: every claim must cite at least one ID, and every cited ID (including any "#123"
   written in the text) must be a post in that evidence. Otherwise the report is regenerated with the problems
   as feedback, up to MAX_REPORT_ATTEMPTS; after that it fails and nothing is saved.
4. The insights are stored, shown on the brief form and injected into the next brief's prompts (rule 4).
"""

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics import Performance, latest_snapshots, performance_of
from app.caption_length import caption_length, hashtag_count, published_text
from app.channels import ChannelSpec
from app.generation_clients import TextClient
from app.models import Insight, Language, Post, PostStatus, Report
from app.synthetic_metrics import MetricValues

REPORT_WINDOW = timedelta(days=7)
MAX_REPORT_ATTEMPTS = 3
MIN_INSIGHTS = 1
MAX_INSIGHTS = 4
# Common rules of thumb, used only to group posts for the analysis: LinkedIn advises about 3 hashtags, and 140
# characters is the classic short-post length.
FEW_HASHTAGS_MAX = 3
SHORT_POST_MAX_LENGTH = 140
PERCENT = 100
POST_REFERENCE_IN_TEXT = re.compile(r"#(\d+)\b")
LANGUAGE_NAMES = {Language.BENGALI: "Bengali", Language.ENGLISH: "English"}


class NothingToReport(Exception):
    """No post was published in the report window."""


class ReportGenerationFailed(Exception):
    """The model kept citing posts that are not in the data, or making uncited claims."""


class ReportClaim(BaseModel):
    text: str
    post_ids: list[int] = Field(description="IDs of the posts whose numbers support this claim.")


class ReportDraft(BaseModel):
    summary: ReportClaim
    findings: list[ReportClaim]
    insights: list[ReportClaim] = Field(description="Actionable recommendations for the next brief.")


# ---------------------------------------------------------------- evidence


@dataclass(frozen=True)
class PostEvidence:
    post: Post
    performance: Performance
    hashtags: int
    published_length: int


class GroupKind:
    CHANNEL = "channel"
    CHANNEL_LANGUAGE = "channel_language"
    CHANNEL_HASHTAGS = "channel_hashtags"
    CHANNEL_LENGTH = "channel_length"


FEW_HASHTAGS = "few_hashtags"
MANY_HASHTAGS = "many_hashtags"
SHORT_POSTS = "short"
LONG_POSTS = "long"


@dataclass(frozen=True)
class GroupEvidence:
    kind: str
    channel: str
    label: str
    post_ids: list[int]
    values: MetricValues
    language: Language | None = None
    bucket: str | None = None  # FEW_HASHTAGS / MANY_HASHTAGS or SHORT_POSTS / LONG_POSTS

    def rate(self, numerator: int) -> float | None:
        return numerator / self.values.impressions if self.values.impressions else None


@dataclass(frozen=True)
class Evidence:
    window_start: datetime
    window_end: datetime
    posts: list[PostEvidence]
    groups: list[GroupEvidence]

    @property
    def post_ids(self) -> set[int]:
        return {item.post.id for item in self.posts}


def _totals(items: Sequence[PostEvidence]) -> MetricValues:
    def total(field: str) -> int:
        return sum(getattr(item.performance.values, field) for item in items)

    return MetricValues(
        impressions=total("impressions"),
        likes=total("likes"),
        comments=total("comments"),
        shares=total("shares"),
        clicks=total("clicks"),
    )


def _hashtag_bucket(item: PostEvidence) -> str:
    return FEW_HASHTAGS if item.hashtags <= FEW_HASHTAGS_MAX else MANY_HASHTAGS


def _length_bucket(item: PostEvidence) -> str:
    return SHORT_POSTS if item.published_length <= SHORT_POST_MAX_LENGTH else LONG_POSTS


BUCKET_LABELS = {
    FEW_HASHTAGS: f"0-{FEW_HASHTAGS_MAX} hashtags",
    MANY_HASHTAGS: f"{FEW_HASHTAGS_MAX + 1}+ hashtags",
    SHORT_POSTS: f"short posts (<= {SHORT_POST_MAX_LENGTH} chars)",
    LONG_POSTS: f"long posts (> {SHORT_POST_MAX_LENGTH} chars)",
}


def _groups(posts: Sequence[PostEvidence], channel_names: dict[str, str]) -> list[GroupEvidence]:
    """Pooled groups, total over total: per channel, and per channel split by language, hashtags and length."""
    keyed: dict[tuple[str, str, Language | None, str | None], list[PostEvidence]] = {}
    for item in posts:
        channel, language = item.post.channel, Language(item.post.language)
        for key in (
            (GroupKind.CHANNEL, channel, None, None),
            (GroupKind.CHANNEL_LANGUAGE, channel, language, None),
            (GroupKind.CHANNEL_HASHTAGS, channel, None, _hashtag_bucket(item)),
            (GroupKind.CHANNEL_LENGTH, channel, None, _length_bucket(item)),
        ):
            keyed.setdefault(key, []).append(item)
    groups = []
    for (kind, channel, language, bucket), items in keyed.items():
        label = channel_names[channel]
        if language is not None:
            label += f" {LANGUAGE_NAMES[language]}"
        if bucket is not None:
            label += f" {BUCKET_LABELS[bucket]}"
        groups.append(
            GroupEvidence(
                kind=kind,
                channel=channel,
                label=label,
                post_ids=[item.post.id for item in items],
                values=_totals(items),
                language=language,
                bucket=bucket,
            )
        )
    kind_order = [GroupKind.CHANNEL, GroupKind.CHANNEL_LANGUAGE, GroupKind.CHANNEL_HASHTAGS, GroupKind.CHANNEL_LENGTH]
    return sorted(groups, key=lambda group: (kind_order.index(group.kind), group.label))


def gather_evidence(
    session: Session, now: datetime, specs: dict[str, ChannelSpec], channel_names: dict[str, str]
) -> Evidence:
    window_start = now - REPORT_WINDOW
    posts = session.scalars(
        select(Post)
        # No upper bound: after a clock reset, posts published during the fast-forward are "later" than now.
        .where(Post.status == PostStatus.PUBLISHED, Post.published_at >= window_start)
        .order_by(Post.id)
    ).all()
    snapshots = latest_snapshots(session, (post.id for post in posts))
    items = []
    for post in posts:
        text = published_text(post.caption, post.hashtags)
        items.append(
            PostEvidence(
                post=post,
                performance=performance_of(post, snapshots.get(post.id)),
                hashtags=hashtag_count(text),
                published_length=caption_length(text, specs[post.channel].caption.length_counting),
            )
        )
    return Evidence(window_start=window_start, window_end=now, posts=items, groups=_groups(items, channel_names))


# ---------------------------------------------------------------- prompt


def _percent(rate: float | None) -> str:
    return "n/a" if rate is None else f"{rate * PERCENT:.2f}%"


def report_prompt(evidence: Evidence, channel_names: dict[str, str], feedback: Sequence[str] = ()) -> str:
    post_lines = [
        f"- post #{item.post.id}: {channel_names[item.post.channel]}, {LANGUAGE_NAMES[Language(item.post.language)]}, "
        f"brief \"{item.post.brief.title}\", {item.hashtags} hashtags, {item.published_length} chars; "
        f"{item.performance.values.impressions} impressions, engagement rate {_percent(item.performance.engagement_rate)}, "
        f"click-through rate {_percent(item.performance.click_through_rate)}; headline \"{item.post.headline}\""
        for item in evidence.posts
    ]
    group_lines = [
        f"- {group.label}: posts {', '.join(f'#{post_id}' for post_id in group.post_ids)} "
        f"({len(group.post_ids)} posts, {group.values.impressions} impressions), "
        f"engagement rate {_percent(group.rate(group.values.engagements))}, "
        f"click-through rate {_percent(group.rate(group.values.clicks))}"
        for group in evidence.groups
    ]
    sections = [
        "You are the social media analyst for a Bangladeshi brand. Write this week's cross-platform performance "
        "report from the data below.",
        f"Week: {evidence.window_start:%Y-%m-%d %H:%M} to {evidence.window_end:%Y-%m-%d %H:%M} UTC. "
        "Engagement rate = (likes + comments + shares) / impressions. Click-through rate = clicks / impressions.",
        "Published posts\n" + "\n".join(post_lines),
        "Pooled groups (rates are total over total)\n" + "\n".join(group_lines),
        "Write\n"
        "- summary: two or three sentences on the week.\n"
        "- findings: three to six specific findings. Compare rates, never raw totals, and name the channels or "
        "languages being compared. Say when a group has only one or two posts.\n"
        f"- insights: {MIN_INSIGHTS + 1} to {MAX_INSIGHTS} short, actionable recommendations for the next content "
        "brief, each following from the findings (for example which language to lead with on a channel, how "
        "many hashtags to use, or how long to keep posts).",
        "Rules\n"
        "- Every summary, finding and insight lists in post_ids the IDs of the posts its numbers come from. "
        "Use only post IDs that appear in the data above; never make up an ID.\n"
        "- Use only numbers that appear in the data above. Do not invent figures, trends or causes.\n"
        "- Write in English.",
    ]
    if feedback:
        sections.append(
            "Your previous answer broke the citation rules. Fix every one of these:\n"
            + "\n".join(f"- {problem}" for problem in feedback)
        )
    return "\n\n".join(sections)


# ---------------------------------------------------------------- validation


def _claims(draft: ReportDraft) -> list[tuple[str, ReportClaim]]:
    return (
        [("the summary", draft.summary)]
        + [(f"finding {index}", claim) for index, claim in enumerate(draft.findings, start=1)]
        + [(f"insight {index}", claim) for index, claim in enumerate(draft.insights, start=1)]
    )


def citation_problems(draft: ReportDraft, known_post_ids: set[int]) -> list[str]:
    """Everything that stops the report being saved. Empty means every claim cites real posts from the data."""
    problems = []
    if not draft.findings:
        problems.append("the report has no findings")
    if not MIN_INSIGHTS <= len(draft.insights) <= MAX_INSIGHTS:
        problems.append(f"the report has {len(draft.insights)} insights; write {MIN_INSIGHTS} to {MAX_INSIGHTS}")
    for name, claim in _claims(draft):
        if not claim.text.strip():
            problems.append(f"{name} is empty")
        if not claim.post_ids:
            problems.append(f"{name} cites no post IDs: \"{claim.text.strip()}\"")
        mentioned = [int(match) for match in POST_REFERENCE_IN_TEXT.findall(claim.text)]
        unknown = sorted({post_id for post_id in [*claim.post_ids, *mentioned] if post_id not in known_post_ids})
        if unknown:
            listed = ", ".join(f"#{post_id}" for post_id in unknown)
            problems.append(f"{name} cites {listed}, which is not a post in this week's data")
    return problems


def cited_post_ids(draft: ReportDraft) -> list[int]:
    return sorted({post_id for _name, claim in _claims(draft) for post_id in claim.post_ids})


def evidence_payload(evidence: Evidence) -> dict:
    """The numbers the report was written from, saved with it so the UI charts exactly what the model saw."""
    return {
        "window_start": evidence.window_start.isoformat(),
        "window_end": evidence.window_end.isoformat(),
        "posts": [
            {
                "post_id": item.post.id,
                "brief_id": item.post.brief_id,
                "brief_title": item.post.brief.title,
                "channel": item.post.channel,
                "language": str(item.post.language),
                "headline": item.post.headline,
                "hashtags": item.hashtags,
                "published_length": item.published_length,
                "impressions": item.performance.values.impressions,
                "engagements": item.performance.values.engagements,
                "clicks": item.performance.values.clicks,
                "engagement_rate": item.performance.engagement_rate,
                "click_through_rate": item.performance.click_through_rate,
            }
            for item in evidence.posts
        ],
        "groups": [
            {
                "kind": group.kind,
                "channel": group.channel,
                "language": str(group.language) if group.language else None,
                "bucket": group.bucket,
                "label": group.label,
                "post_ids": group.post_ids,
                "impressions": group.values.impressions,
                "engagements": group.values.engagements,
                "clicks": group.values.clicks,
                "engagement_rate": group.rate(group.values.engagements),
                "click_through_rate": group.rate(group.values.clicks),
            }
            for group in evidence.groups
        ],
    }


# ---------------------------------------------------------------- the whole report


def generate_weekly_report(
    session: Session,
    text_client: TextClient,
    now: datetime,
    specs: dict[str, ChannelSpec],
    channel_names: dict[str, str],
) -> Report:
    """Write, validate (regenerating on bad citations) and save the report and its insights."""
    evidence = gather_evidence(session, now, specs, channel_names)
    if not evidence.posts:
        raise NothingToReport(
            f"Nothing was published between {evidence.window_start:%Y-%m-%d %H:%M} and {now:%Y-%m-%d %H:%M} UTC; "
            "publish some posts first."
        )
    problems: list[str] = []
    for _attempt in range(MAX_REPORT_ATTEMPTS):
        draft = text_client.generate(report_prompt(evidence, channel_names, problems), ReportDraft)
        problems = citation_problems(draft, evidence.post_ids)
        if not problems:
            break
    else:
        raise ReportGenerationFailed(
            f"The report still broke the citation rules after {MAX_REPORT_ATTEMPTS} attempts: " + "; ".join(problems)
        )

    report = Report(
        week_start=evidence.window_start.date(),
        body=json.dumps({"content": draft.model_dump(), "evidence": evidence_payload(evidence)}, ensure_ascii=False),
        cited_post_ids=cited_post_ids(draft),
    )
    report.insights = [Insight(text=claim.text.strip()) for claim in draft.insights]
    session.add(report)
    session.commit()
    return report


def latest_insights(session: Session) -> list[Insight]:
    latest = session.scalars(select(Report).order_by(Report.id.desc()).limit(1)).first()
    return list(latest.insights) if latest else []
