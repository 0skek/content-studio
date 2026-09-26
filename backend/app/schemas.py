"""Request and response bodies for the HTTP API."""

from datetime import datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict

from app.models import GenerationStatus, Language, PostStatus


class ScheduleRequest(BaseModel):
    # AwareDatetime rejects times without a timezone (422) instead of guessing one.
    scheduled_at: AwareDatetime


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
