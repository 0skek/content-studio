"""Synthetic engagement metrics for the mock adapters (config/synthetic_metrics.json). Not real data.

Each published post's totals grow toward a final value: reach = median * a per-post reach factor, and it follows
1 - exp(-hours / hours_to_63_percent_reach). Likes, comments, shares and clicks are fixed per-post rates of the
impressions. Everything is seeded by post id and channel, so the same post always gives the same numbers, and
totals never go down as time passes. Documented patterns (e.g. Bengali does better on Instagram) scale the rates.
"""

import json
import math
import random
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.caption_length import caption_length, hashtag_count, published_text
from app.channels import ChannelConfigError, ChannelSpec, get_channel_specs
from app.config import BACKEND_DIR
from app.models import Language

SYNTHETIC_METRICS_PATH = BACKEND_DIR / "config" / "synthetic_metrics.json"
SECONDS_PER_HOUR = 3600


class Rates(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    like: float = Field(ge=0, le=1)
    comment: float = Field(ge=0, le=1)
    share: float = Field(ge=0, le=1)
    click: float = Field(ge=0, le=1)


class ChannelProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    median_final_impressions: int = Field(gt=0)
    hours_to_63_percent_reach: float = Field(gt=0)
    rates: Rates


class Pattern(BaseModel):
    """A deliberate effect. Every condition that is set must hold for the factors to apply."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    channel: str
    description: str
    language: Language | None = None
    min_hashtags: int | None = Field(default=None, ge=0)
    max_published_length: int | None = Field(default=None, gt=0)
    engagement_factor: float = Field(default=1.0, gt=0)
    click_factor: float = Field(default=1.0, gt=0)


class SyntheticMetricsConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    snapshot_interval_minutes: float = Field(gt=0)
    reach_spread: float = Field(ge=0, lt=1)  # sigma of the log-normal per-post reach factor
    rate_jitter: float = Field(ge=0, lt=1)  # each post's rates vary by up to ±this fraction
    channels: dict[str, ChannelProfile]
    patterns: list[Pattern] = []


def load_synthetic_metrics_config(path: Path, channel_specs: Mapping[str, ChannelSpec]) -> SyntheticMetricsConfig:
    """Read and validate the config; every channel in channels.json needs a profile, and nothing else."""
    try:
        config = SyntheticMetricsConfig.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        raise ChannelConfigError(f"Invalid synthetic metrics config {path}: {error}") from error
    if set(config.channels) != set(channel_specs):
        raise ChannelConfigError(
            f"{path} must have a profile for exactly the channels in channels.json ({', '.join(channel_specs)}); "
            f"it has {', '.join(config.channels)}"
        )
    unknown = [pattern.channel for pattern in config.patterns if pattern.channel not in channel_specs]
    if unknown:
        raise ChannelConfigError(f"{path} has patterns for unknown channels: {', '.join(unknown)}")
    return config


@lru_cache(maxsize=1)
def get_synthetic_metrics_config() -> SyntheticMetricsConfig:
    return load_synthetic_metrics_config(SYNTHETIC_METRICS_PATH, get_channel_specs())


@dataclass(frozen=True)
class PostFacts:
    """What the metrics depend on; taken from a published post."""

    post_id: int
    channel: str
    language: Language
    caption: str
    hashtags: tuple[str, ...]
    published_at: datetime


@dataclass(frozen=True)
class MetricValues:
    impressions: int
    likes: int
    comments: int
    shares: int
    clicks: int

    @property
    def engagements(self) -> int:
        return self.likes + self.comments + self.shares


def _pattern_applies(pattern: Pattern, facts: PostFacts, spec: ChannelSpec) -> bool:
    if pattern.channel != facts.channel:
        return False
    text = published_text(facts.caption, list(facts.hashtags))
    if pattern.language is not None and pattern.language != facts.language:
        return False
    if pattern.min_hashtags is not None and hashtag_count(text) < pattern.min_hashtags:
        return False
    length = caption_length(text, spec.caption.length_counting)
    return pattern.max_published_length is None or length <= pattern.max_published_length


def synthetic_metrics(
    facts: PostFacts, now: datetime, config: SyntheticMetricsConfig, spec: ChannelSpec
) -> MetricValues:
    """Cumulative totals for a post at `now`. Zero at publishing, growing toward the post's final values."""
    profile = config.channels[facts.channel]
    random_source = random.Random(f"synthetic-metrics:{facts.channel}:{facts.post_id}")
    reach_factor = random_source.lognormvariate(0, config.reach_spread)

    def jittered(rate: float) -> float:
        return rate * random_source.uniform(1 - config.rate_jitter, 1 + config.rate_jitter)

    rates = {name: jittered(value) for name, value in profile.rates.model_dump().items()}
    for pattern in config.patterns:
        if _pattern_applies(pattern, facts, spec):
            for engagement in ("like", "comment", "share"):
                rates[engagement] *= pattern.engagement_factor
            rates["click"] *= pattern.click_factor

    hours = max((now - facts.published_at).total_seconds() / SECONDS_PER_HOUR, 0.0)
    progress = 1 - math.exp(-hours / profile.hours_to_63_percent_reach)
    impressions = round(profile.median_final_impressions * reach_factor * progress)
    return MetricValues(
        impressions=impressions,
        likes=round(impressions * rates["like"]),
        comments=round(impressions * rates["comment"]),
        shares=round(impressions * rates["share"]),
        clicks=round(impressions * rates["click"]),
    )
