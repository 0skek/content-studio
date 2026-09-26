"""ORM models for the five tables: briefs, posts, metrics, reports, insights."""

from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, CheckConstraint, Date, Enum, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.channels import get_channel_specs
from app.db import Base, UTCDateTime, utc_now


class PostStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    DISCARDED = "discarded"
    SCHEDULED = "scheduled"
    PUBLISHED = "published"
    REJECTED = "rejected"


class Language(StrEnum):
    BENGALI = "bn"
    ENGLISH = "en"


class GenerationStatus(StrEnum):
    """Progress of a post's background generation job. Separate from PostStatus (the approval flow)."""

    PENDING = "pending"
    GENERATING = "generating"
    READY = "ready"
    FAILED = "failed"


def _string_enum_column(enum_class: type[StrEnum], constraint_name: str) -> Enum:
    """Store enum values ("draft"), not member names ("DRAFT"), guarded by a CHECK constraint."""
    return Enum(
        enum_class,
        name=constraint_name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda members: [member.value for member in members],
    )


METRIC_COUNT_COLUMNS = ("impressions", "likes", "comments", "shares", "clicks")


class Brief(Base):
    __tablename__ = "briefs"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String)
    goal: Mapped[str] = mapped_column(Text)
    audience: Mapped[str] = mapped_column(Text)
    languages: Mapped[list[str]] = mapped_column(JSON)
    tone: Mapped[str] = mapped_column(String)
    insights_used: Mapped[list[Any]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)

    posts: Mapped[list["Post"]] = relationship(back_populates="brief", order_by="Post.id")


class Post(Base):
    __tablename__ = "posts"
    # Supports the scheduler's query for scheduled posts that are due.
    __table_args__ = (Index("ix_posts_status_scheduled_at", "status", "scheduled_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    brief_id: Mapped[int] = mapped_column(ForeignKey("briefs.id"), index=True)
    channel: Mapped[str] = mapped_column(String)
    language: Mapped[Language] = mapped_column(_string_enum_column(Language, "language"))
    # Overlaid on the image in code; image prompts never ask the model for text.
    headline: Mapped[str | None] = mapped_column(Text)
    caption: Mapped[str] = mapped_column(Text)
    hashtags: Mapped[list[str]] = mapped_column(JSON, default=list)
    image_prompt: Mapped[str | None] = mapped_column(Text)
    image_path: Mapped[str | None] = mapped_column(String)
    # Measured from the final overlaid file, which is what the adapters validate.
    width: Mapped[int | None]
    height: Mapped[int | None]
    file_size_bytes: Mapped[int | None]
    generation_status: Mapped[GenerationStatus] = mapped_column(
        _string_enum_column(GenerationStatus, "generation_status"), default=GenerationStatus.PENDING
    )
    generation_error: Mapped[str | None] = mapped_column(Text)
    status: Mapped[PostStatus] = mapped_column(
        _string_enum_column(PostStatus, "post_status"), default=PostStatus.DRAFT
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    # A retry is a new draft whose parent is the discarded post it replaces. Unique: a post is retried at most
    # once, so each channel/language slot's history is a simple chain.
    parent_post_id: Mapped[int | None] = mapped_column(ForeignKey("posts.id"), unique=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    brief: Mapped[Brief] = relationship(back_populates="posts")
    parent: Mapped["Post | None"] = relationship(remote_side=[id], back_populates="retries")
    retries: Mapped[list["Post"]] = relationship(back_populates="parent")
    metrics: Mapped[list["Metric"]] = relationship(back_populates="post")

    def __init__(self, **fields: Any) -> None:
        # Every post starts as a draft; after that, only transition() may change its status.
        initial_status = fields.setdefault("status", PostStatus.DRAFT)
        if initial_status != PostStatus.DRAFT:
            raise ValueError(
                f"New posts must start as '{PostStatus.DRAFT}', not {initial_status!r}; "
                "change status only through transition()"
            )
        fields.setdefault("generation_status", GenerationStatus.PENDING)
        super().__init__(**fields)

    @validates("channel")
    def _validate_channel(self, key: str, channel: str) -> str:
        known_channels = get_channel_specs().keys()
        if channel not in known_channels:
            raise ValueError(
                f"Unknown channel {channel!r}; channels.json defines: {', '.join(sorted(known_channels))}"
            )
        return channel


class Metric(Base):
    __tablename__ = "metrics"
    __table_args__ = tuple(
        CheckConstraint(f"{column} >= 0", name=f"ck_metrics_{column}_non_negative")
        for column in METRIC_COUNT_COLUMNS
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"), index=True)
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    impressions: Mapped[int]
    likes: Mapped[int]
    comments: Mapped[int]
    shares: Mapped[int]
    clicks: Mapped[int]

    post: Mapped[Post] = relationship(back_populates="metrics")


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    week_start: Mapped[date] = mapped_column(Date)
    body: Mapped[str] = mapped_column(Text)
    cited_post_ids: Mapped[list[int]] = mapped_column(JSON, default=list)

    insights: Mapped[list["Insight"]] = relationship(back_populates="report")


class Insight(Base):
    __tablename__ = "insights"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id"), index=True)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)

    report: Mapped[Report] = relationship(back_populates="insights")
