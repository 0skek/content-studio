"""Deleting briefs and reports, and taking published posts down, so a flow can be rerun from any step.

A brief goes with all its posts (retry chains included), their metrics and image files. Any report citing one of
those posts is deleted too, with its insights, so no stored report ever cites a post that no longer exists
(rule 5). A brief still generating is refused: its background job would write to rows that are gone.
"""

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.generation_service import BRIEFS_MEDIA_SUBDIR, BriefNotFound
from app.models import Brief, GenerationStatus, Insight, Metric, Post, PostStatus, Report
from app.post_service import PostNotFound
from app.post_status import transition

logger = logging.getLogger(__name__)

IN_PROGRESS = (GenerationStatus.PENDING, GenerationStatus.GENERATING)


class BriefStillGenerating(Exception):
    def __init__(self, brief_id: int, post_ids: list[int]) -> None:
        super().__init__(
            f"Brief {brief_id} is still generating posts {', '.join(f'#{post_id}' for post_id in post_ids)}; "
            "wait for them to finish (ready or failed) before deleting it."
        )


class ReportNotFound(Exception):
    def __init__(self, report_id: int) -> None:
        super().__init__(f"Report {report_id} does not exist.")


@dataclass(frozen=True)
class DeletedBrief:
    brief_id: int
    post_ids: list[int]
    report_ids: list[int]


def _delete_reports(session: Session, report_ids: list[int]) -> None:
    if report_ids:
        session.execute(delete(Insight).where(Insight.report_id.in_(report_ids)))
        session.execute(delete(Report).where(Report.id.in_(report_ids)))


def delete_brief(session: Session, brief_id: int, media_dir: Path) -> DeletedBrief:
    brief = session.get(Brief, brief_id)
    if brief is None:
        raise BriefNotFound(brief_id)
    busy = [post.id for post in brief.posts if post.generation_status in IN_PROGRESS]
    if busy:
        raise BriefStillGenerating(brief_id, busy)

    post_ids = sorted(post.id for post in brief.posts)
    doomed = set(post_ids)
    citing_reports = _reports_citing(session, doomed)
    _delete_reports(session, citing_reports)
    session.execute(delete(Metric).where(Metric.post_id.in_(post_ids)))
    # One statement for the whole brief: SQLite checks the retry chain's self-reference when it ends.
    session.execute(delete(Post).where(Post.brief_id == brief_id))
    session.execute(delete(Brief).where(Brief.id == brief_id))
    session.commit()

    brief_media = media_dir / BRIEFS_MEDIA_SUBDIR / str(brief_id)
    try:
        shutil.rmtree(brief_media)
    except FileNotFoundError:
        pass  # Nothing was generated for this brief.
    except OSError as error:
        # The rows are gone either way; leftover files are only disk space.
        logger.warning("Brief %s deleted but its images could not be removed from %s: %s", brief_id, brief_media, error)
    return DeletedBrief(brief_id=brief_id, post_ids=post_ids, report_ids=sorted(citing_reports))


def _reports_citing(session: Session, post_ids: set[int]) -> list[int]:
    return sorted(report.id for report in session.scalars(select(Report)).all() if post_ids & set(report.cited_post_ids))


@dataclass(frozen=True)
class TakenDown:
    post: Post
    report_ids: list[int]


def take_down_post(session: Session, post_id: int) -> TakenDown:
    """Remove a published post from its channel: back to approved, publish time and metrics cleared.

    Reports citing it are deleted: their numbers no longer exist. Only published posts can be taken down
    (transition() refuses anything else).
    """
    post = session.get(Post, post_id)
    if post is None:
        raise PostNotFound(post_id)
    transition(post, PostStatus.APPROVED)
    post.published_at = None
    post.scheduled_at = None
    citing = _reports_citing(session, {post_id})
    _delete_reports(session, citing)
    session.execute(delete(Metric).where(Metric.post_id == post_id))
    session.commit()
    return TakenDown(post=post, report_ids=citing)


def delete_report(session: Session, report_id: int) -> None:
    if session.get(Report, report_id) is None:
        raise ReportNotFound(report_id)
    _delete_reports(session, [report_id])
    session.commit()
