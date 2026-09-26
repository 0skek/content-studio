"""Request and response bodies for the HTTP API."""

from datetime import datetime
from typing import Annotated, Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, computed_field, field_validator

from app.caption_length import LengthCounting, caption_length, published_text
from app.channels import get_channel_specs
from app.config import MEDIA_URL_PATH
from app.models import GenerationStatus, Language, PostStatus

NonBlankText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
DEFAULT_BRIEF_LANGUAGES = (Language.BENGALI, Language.ENGLISH)


class ScheduleRequest(BaseModel):
    # AwareDatetime rejects times without a timezone (422) instead of guessing one.
    scheduled_at: AwareDatetime


class BriefCreate(BaseModel):
    title: NonBlankText
    goal: NonBlankText
    audience: NonBlankText
    tone: NonBlankText
    languages: list[Language] = Field(default_factory=lambda: list(DEFAULT_BRIEF_LANGUAGES), min_length=1)
    # Insights from a weekly report to apply to this brief; their text goes into the generation prompts.
    insight_ids: list[int] = Field(default_factory=list)

    @field_validator("languages")
    @classmethod
    def _languages_are_unique(cls, languages: list[Language]) -> list[Language]:
        if len(set(languages)) != len(languages):
            raise ValueError("languages must not repeat")
        return languages


class PostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    brief_id: int
    channel: str
    language: Language
    headline: str | None
    caption: str
    hashtags: list[str]
    image_prompt: str | None
    image_path: str | None
    width: int | None
    height: int | None
    file_size_bytes: int | None
    generation_status: GenerationStatus
    generation_error: str | None
    status: PostStatus
    rejection_reason: str | None
    parent_post_id: int | None
    scheduled_at: datetime | None
    published_at: datetime | None

    @computed_field
    @property
    def image_url(self) -> str | None:
        return f"{MEDIA_URL_PATH}/{self.image_path}" if self.image_path else None

    @computed_field
    @property
    def published_length(self) -> int:
        """Length of caption plus hashtags, counted the way this post's channel counts it."""
        counting = get_channel_specs()[self.channel].caption.length_counting
        return caption_length(published_text(self.caption, self.hashtags), counting)


class BriefSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    languages: list[Language]
    created_at: datetime


class BriefOut(BriefSummaryOut):
    goal: str
    audience: str
    tone: str
    insights_used: list[Any]
    posts: list[PostOut]


class ChannelOut(BaseModel):
    id: str
    display_name: str
    width: int
    height: int
    aspect_ratio: str
    max_file_size_mb: float
    caption_max_chars: int
    max_hashtags: int
    length_counting: LengthCounting
