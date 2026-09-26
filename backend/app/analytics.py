"""Analytics store: metric snapshots ingested through the adapters, and the like-for-like cross-platform comparison.

Comparison is by normalized rates, never raw totals: channels differ hugely in reach, so a post with more
impressions is not "better". For each language, the same brief's post on each channel sits side by side.
- engagement rate = (likes + comments + shares) / impressions
- click-through rate = clicks / impressions
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.adapters import MockChannelAdapter
from app.models import Brief, Language, Metric, Post, PostStatus
from app.synthetic_metrics import MetricValues, PostFacts

ENGAGEMENT_RATE_DEFINITION = "(likes + comments + shares) / impressions"
CLICK_THROUGH_RATE_DEFINITION = "clicks / impressions"


def post_facts(post: Post) -> PostFacts:
    if post.published_at is None:
        raise ValueError(f"Post {post.id} has not been published, so it has no metrics")
    return PostFacts(
        post_id=post.id,
        channel=post.channel,
        language=Language(post.language),
        caption=post.caption,
        hashtags=tuple(post.hashtags),
        published_at=post.published_at,
    )


def latest_snapshots(session: Session, post_ids: Iterable[int]) -> dict[int, Metric]:
    """Each post's most recent metrics snapshot."""
    ids = list(post_ids)
    if not ids:
        return {}
    newest = (
        select(Metric.post_id, func.max(Metric.fetched_at).label("fetched_at"))
        .where(Metric.post_id.in_(ids))
        .group_by(Metric.post_id)
        .subquery()
    )
    rows = session.scalars(
        select(Metric).join(
            newest, (Metric.post_id == newest.c.post_id) & (Metric.fetched_at == newest.c.fetched_at)
        )
    ).all()
    return {row.post_id: row for row in rows}


def ingest_metrics(
    session: Session, adapters: Mapping[str, MockChannelAdapter], now: datetime, interval: timedelta
) -> list[int]:
    """Store a new snapshot for every published post whose last one is at least `interval` old. Returns post ids."""
    published = session.scalars(select(Post).where(Post.status == PostStatus.PUBLISHED)).all()
    latest = latest_snapshots(session, (post.id for post in published))
    ingested = []
    for post in published:
        previous = latest.get(post.id)
        if previous is not None and now - previous.fetched_at < interval:
            continue
        values = adapters[post.channel].fetch_metrics(post_facts(post), now)
        session.add(Metric(post_id=post.id, fetched_at=now, **values.__dict__))
        ingested.append(post.id)
    session.commit()
    return ingested


# ---------------------------------------------------------------- comparison


def _rate(numerator: int, impressions: int) -> float | None:
    return numerator / impressions if impressions > 0 else None


@dataclass(frozen=True)
class Performance:
    post_id: int
    channel: str
    language: Language
    published_at: datetime | None
    fetched_at: datetime | None
    values: MetricValues

    @property
    def engagement_rate(self) -> float | None:
        return _rate(self.values.engagements, self.values.impressions)

    @property
    def click_through_rate(self) -> float | None:
        return _rate(self.values.clicks, self.values.impressions)


NO_METRICS_YET = MetricValues(impressions=0, likes=0, comments=0, shares=0, clicks=0)


def performance_of(post: Post, snapshot: Metric | None) -> Performance:
    values = (
        MetricValues(
            impressions=snapshot.impressions,
            likes=snapshot.likes,
            comments=snapshot.comments,
            shares=snapshot.shares,
            clicks=snapshot.clicks,
        )
        if snapshot
        else NO_METRICS_YET
    )
    return Performance(
        post_id=post.id,
        channel=post.channel,
        language=Language(post.language),
        published_at=post.published_at,
        fetched_at=snapshot.fetched_at if snapshot else None,
        values=values,
    )


def best_channel(performances: Iterable[Performance], rate: str) -> str | None:
    """The channel with the highest rate; posts without impressions yet are not ranked."""
    ranked = [(getattr(performance, rate), performance.channel) for performance in performances]
    ranked = [(value, channel) for value, channel in ranked if value is not None]
    return max(ranked, key=lambda item: item[0])[1] if ranked else None


@dataclass(frozen=True)
class LanguageRow:
    language: Language
    cells: dict[str, Performance | None]  # channel -> this language's published post there

    def best(self, rate: str) -> str | None:
        return best_channel((cell for cell in self.cells.values() if cell is not None), rate)


@dataclass(frozen=True)
class ChannelSummary:
    """All of this brief's published posts on one channel, pooled: rates are sums over sums, not averages."""

    channel: str
    post_ids: list[int]
    values: MetricValues

    @property
    def engagement_rate(self) -> float | None:
        return _rate(self.values.engagements, self.values.impressions)

    @property
    def click_through_rate(self) -> float | None:
        return _rate(self.values.clicks, self.values.impressions)


@dataclass(frozen=True)
class Comparison:
    brief_id: int
    channels: list[str]
    rows: list[LanguageRow]
    summaries: list[ChannelSummary]


def _pooled(channel: str, performances: Sequence[Performance]) -> ChannelSummary:
    def total(field: str) -> int:
        return sum(getattr(performance.values, field) for performance in performances)

    return ChannelSummary(
        channel=channel,
        post_ids=[performance.post_id for performance in performances],
        values=MetricValues(
            impressions=total("impressions"),
            likes=total("likes"),
            comments=total("comments"),
            shares=total("shares"),
            clicks=total("clicks"),
        ),
    )


def brief_comparison(session: Session, brief: Brief, channels: Sequence[str]) -> Comparison:
    """The brief's published posts side by side: one row per language, one column per channel."""
    published = [post for post in brief.posts if post.status == PostStatus.PUBLISHED]
    snapshots = latest_snapshots(session, (post.id for post in published))
    # Retries mean a slot could in principle hold more than one published post; the newest one represents it.
    newest_in_slot: dict[tuple[str, Language], Post] = {}
    for post in sorted(published, key=lambda candidate: candidate.id):
        newest_in_slot[(post.channel, Language(post.language))] = post
    performances = {slot: performance_of(post, snapshots.get(post.id)) for slot, post in newest_in_slot.items()}

    rows = [
        LanguageRow(
            language=language,
            cells={channel: performances.get((channel, language)) for channel in channels},
        )
        for language in (Language(code) for code in brief.languages)
    ]
    summaries = [
        _pooled(channel, [performance for (slot_channel, _), performance in performances.items() if slot_channel == channel])
        for channel in channels
    ]
    return Comparison(brief_id=brief.id, channels=list(channels), rows=rows, summaries=summaries)


def published_feed(session: Session, channel: str, limit: int) -> list[tuple[Post, Performance]]:
    """A channel's published posts, newest first, each with its latest metrics."""
    posts = session.scalars(
        select(Post)
        .where(Post.channel == channel, Post.status == PostStatus.PUBLISHED)
        .order_by(Post.published_at.desc(), Post.id.desc())
        .limit(limit)
    ).all()
    snapshots = latest_snapshots(session, (post.id for post in posts))
    return [(post, performance_of(post, snapshots.get(post.id))) for post in posts]
