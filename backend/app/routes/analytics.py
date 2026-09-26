"""HTTP routes for analytics: the per-brief cross-platform comparison and the mock channel feeds."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.analytics import (
    CLICK_THROUGH_RATE_DEFINITION,
    ENGAGEMENT_RATE_DEFINITION,
    ChannelSummary,
    Performance,
    brief_comparison,
    published_feed,
)
from app.channels import get_channel_specs
from app.db import get_session
from app.generation_service import load_brief
from app.models import Language
from app.schemas import PostOut

router = APIRouter(tags=["analytics"])

SessionDep = Annotated[Session, Depends(get_session)]
DEFAULT_FEED_LENGTH = 30
MAX_FEED_LENGTH = 200


class PerformanceOut(BaseModel):
    post_id: int
    channel: str
    language: Language
    published_at: datetime | None
    fetched_at: datetime | None
    impressions: int
    likes: int
    comments: int
    shares: int
    clicks: int
    engagements: int
    engagement_rate: float | None
    click_through_rate: float | None

    @classmethod
    def of(cls, performance: Performance) -> "PerformanceOut":
        values = performance.values
        return cls(
            post_id=performance.post_id,
            channel=performance.channel,
            language=performance.language,
            published_at=performance.published_at,
            fetched_at=performance.fetched_at,
            impressions=values.impressions,
            likes=values.likes,
            comments=values.comments,
            shares=values.shares,
            clicks=values.clicks,
            engagements=values.engagements,
            engagement_rate=performance.engagement_rate,
            click_through_rate=performance.click_through_rate,
        )


class LanguageRowOut(BaseModel):
    language: Language
    cells: dict[str, PerformanceOut | None]
    best_engagement_channel: str | None
    best_click_channel: str | None


class ChannelSummaryOut(BaseModel):
    channel: str
    post_ids: list[int]
    impressions: int
    engagements: int
    clicks: int
    engagement_rate: float | None
    click_through_rate: float | None

    @classmethod
    def of(cls, summary: ChannelSummary) -> "ChannelSummaryOut":
        return cls(
            channel=summary.channel,
            post_ids=summary.post_ids,
            impressions=summary.values.impressions,
            engagements=summary.values.engagements,
            clicks=summary.values.clicks,
            engagement_rate=summary.engagement_rate,
            click_through_rate=summary.click_through_rate,
        )


class ComparisonOut(BaseModel):
    brief_id: int
    channels: list[str]
    rows: list[LanguageRowOut]
    channel_summaries: list[ChannelSummaryOut]
    definitions: dict[str, str]


class FeedPostOut(BaseModel):
    post: PostOut
    brief_title: str
    performance: PerformanceOut


@router.get("/briefs/{brief_id}/comparison", response_model=ComparisonOut)
def get_comparison(brief_id: int, session: SessionDep) -> ComparisonOut:
    """Like-for-like: for each language, this brief's published post on each channel, compared by rates."""
    comparison = brief_comparison(session, load_brief(session, brief_id), list(get_channel_specs()))
    return ComparisonOut(
        brief_id=comparison.brief_id,
        channels=comparison.channels,
        rows=[
            LanguageRowOut(
                language=row.language,
                cells={
                    channel: PerformanceOut.of(cell) if cell is not None else None for channel, cell in row.cells.items()
                },
                best_engagement_channel=row.best("engagement_rate"),
                best_click_channel=row.best("click_through_rate"),
            )
            for row in comparison.rows
        ],
        channel_summaries=[ChannelSummaryOut.of(summary) for summary in comparison.summaries],
        definitions={"engagement_rate": ENGAGEMENT_RATE_DEFINITION, "click_through_rate": CLICK_THROUGH_RATE_DEFINITION},
    )


@router.get("/feeds", response_model=dict[str, list[FeedPostOut]])
def get_feeds(
    session: SessionDep, limit: Annotated[int, Query(gt=0, le=MAX_FEED_LENGTH)] = DEFAULT_FEED_LENGTH
) -> dict[str, list[FeedPostOut]]:
    """What each mock channel has published, newest first, with each post's latest metrics."""
    return {
        channel: [
            FeedPostOut(post=PostOut.model_validate(post), brief_title=post.brief.title, performance=PerformanceOut.of(performance))
            for post, performance in published_feed(session, channel, limit)
        ]
        for channel in get_channel_specs()
    }
