"""HTTP routes for the weekly report and the insights that feed the next brief."""

import json
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.channels import get_channel_specs
from app.clock import VirtualClock
from app.db import get_session
from app.deletion import delete_report
from app.dependencies import get_clock, get_generation_clients
from app.generation_clients import GenerationClients
from app.models import Insight, Language, Report
from app.reporting import ReportDraft, generate_weekly_report, latest_insights

router = APIRouter(tags=["reports"])

SessionDep = Annotated[Session, Depends(get_session)]


class InsightOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    report_id: int
    text: str
    created_at: datetime


class EvidencePostOut(BaseModel):
    post_id: int
    brief_id: int
    brief_title: str
    channel: str
    language: Language
    headline: str | None
    hashtags: int
    published_length: int
    impressions: int
    engagements: int
    clicks: int
    engagement_rate: float | None
    click_through_rate: float | None


class EvidenceGroupOut(BaseModel):
    kind: str
    channel: str
    language: Language | None
    bucket: str | None
    label: str
    post_ids: list[int]
    impressions: int
    engagements: int
    clicks: int
    engagement_rate: float | None
    click_through_rate: float | None


class EvidenceOut(BaseModel):
    window_start: datetime
    window_end: datetime
    posts: list[EvidencePostOut]
    groups: list[EvidenceGroupOut]


class ReportOut(BaseModel):
    id: int
    week_start: date
    content: ReportDraft
    # The numbers the report was written from, for charts. None for reports saved before evidence was stored.
    evidence: EvidenceOut | None
    cited_post_ids: list[int]
    insights: list[InsightOut]

    @classmethod
    def of(cls, report: Report) -> "ReportOut":
        body = json.loads(report.body)
        stored_with_evidence = "content" in body
        return cls(
            id=report.id,
            week_start=report.week_start,
            content=ReportDraft.model_validate(body["content"] if stored_with_evidence else body),
            evidence=EvidenceOut.model_validate(body["evidence"]) if stored_with_evidence else None,
            cited_post_ids=report.cited_post_ids,
            insights=[InsightOut.model_validate(insight) for insight in report.insights],
        )


def _channel_names() -> dict[str, str]:
    return {channel: spec.display_name for channel, spec in get_channel_specs().items()}


@router.post("/reports", status_code=status.HTTP_201_CREATED, response_model=ReportOut)
def create_report(
    session: SessionDep,
    clients: Annotated[GenerationClients, Depends(get_generation_clients)],
    clock: Annotated[VirtualClock, Depends(get_clock)],
) -> ReportOut:
    """Write this week's report (the 7 days up to the demo clock's now). Every claim cites validated post IDs."""
    report = generate_weekly_report(session, clients.text, clock.now(), dict(get_channel_specs()), _channel_names())
    return ReportOut.of(report)


@router.get("/reports", response_model=list[ReportOut])
def list_reports(session: SessionDep) -> list[ReportOut]:
    return [ReportOut.of(report) for report in session.scalars(select(Report).order_by(Report.id.desc())).all()]


@router.delete("/reports/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_report(report_id: int, session: SessionDep) -> None:
    """Delete the report and its insights. Briefs that already applied them keep their copy."""
    delete_report(session, report_id)


@router.get("/insights/latest", response_model=list[InsightOut])
def get_latest_insights(session: SessionDep) -> list[Insight]:
    """The newest report's insights: offered on the brief form and injected into the next brief's prompts."""
    return latest_insights(session)
