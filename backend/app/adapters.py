"""Mock channel adapters: the last gate before a post goes out (rule 3).

Each adapter checks what would actually be sent, the final image file and the caption plus hashtags, against its
channel's limits in channels.json, and rejects any violation with an explicit reason. It never fixes anything:
no resizing, recompressing, trimming or dropping hashtags. A post that passes is "published" (nothing leaves the
machine). Adapters also report each published post's engagement, from the synthetic metrics model.
"""

import io
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from PIL import Image, UnidentifiedImageError

from app.caption_length import LengthCounting, caption_length, hashtag_count, published_text
from app.channels import BYTES_PER_MEGABYTE, CaptionSpec, ChannelSpec
from app.synthetic_metrics import MetricValues, PostFacts, SyntheticMetricsConfig, synthetic_metrics

logger = logging.getLogger(__name__)


def caption_violations(caption: str, hashtags: Sequence[str], spec: CaptionSpec) -> list[str]:
    """Caption limit problems, shared by generation (which retries) and the adapters (which reject)."""
    text = published_text(caption, list(hashtags))
    problems = []
    tags = hashtag_count(text)
    if tags > spec.max_hashtags:
        problems.append(f"{tags} hashtags; the limit is {spec.max_hashtags}")
    length = caption_length(text, spec.length_counting)
    if length > spec.max_chars:
        unit = "weighted characters" if spec.length_counting == LengthCounting.X_WEIGHTED else "characters"
        problems.append(f"caption plus hashtags is {length} {unit}; the limit is {spec.max_chars}")
    return problems


@dataclass(frozen=True)
class Submission:
    """Exactly what a channel receives."""

    caption: str
    hashtags: tuple[str, ...]
    image_bytes: bytes


@dataclass(frozen=True)
class Measurements:
    width: int | None
    height: int | None
    file_size_bytes: int
    published_length: int
    hashtag_count: int


class AdapterRejected(Exception):
    def __init__(self, channel: str, reasons: Sequence[str], measurements: Measurements | None = None) -> None:
        super().__init__(f"{channel} rejected the post: " + "; ".join(reasons))
        self.channel = channel
        self.reasons = list(reasons)
        self.measurements = measurements


class MockChannelAdapter:
    def __init__(self, channel: str, spec: ChannelSpec, metrics_config: SyntheticMetricsConfig) -> None:
        self.channel = channel
        self.spec = spec
        self._metrics_config = metrics_config

    def measure(self, submission: Submission) -> Measurements:
        width = height = None
        try:
            with Image.open(io.BytesIO(submission.image_bytes)) as image:
                width, height = image.size
        except (UnidentifiedImageError, OSError):
            pass  # Reported as a violation by violations(); measure() only describes what arrived.
        text = published_text(submission.caption, list(submission.hashtags))
        return Measurements(
            width=width,
            height=height,
            file_size_bytes=len(submission.image_bytes),
            published_length=caption_length(text, self.spec.caption.length_counting),
            hashtag_count=hashtag_count(text),
        )

    def violations(self, submission: Submission) -> list[str]:
        image_spec = self.spec.image
        measured = self.measure(submission)
        reasons = []
        if measured.width is None or measured.height is None:
            reasons.append("the image is not a readable image file")
        elif not image_spec.matches_aspect_ratio(measured.width, measured.height):
            reasons.append(
                f"aspect ratio {measured.width}x{measured.height} ({measured.width / measured.height:.3f}:1) "
                f"is not {image_spec.aspect_ratio} ({image_spec.nominal_ratio:.3f}:1) "
                f"within ±{image_spec.aspect_ratio_tolerance:.0%}"
            )
        if measured.file_size_bytes > image_spec.max_file_size_bytes:
            reasons.append(
                f"image file is {measured.file_size_bytes / BYTES_PER_MEGABYTE:.2f} MB; "
                f"the limit is {image_spec.max_file_size_mb:g} MB"
            )
        reasons.extend(caption_violations(submission.caption, submission.hashtags, self.spec.caption))
        return reasons

    def publish(self, submission: Submission) -> Measurements:
        """Accept the post, or raise AdapterRejected listing every violation. The submission is never altered."""
        reasons = self.violations(submission)
        measurements = self.measure(submission)
        if reasons:
            logger.info("%s adapter rejected a post: %s", self.channel, "; ".join(reasons))
            raise AdapterRejected(self.channel, reasons, measurements)
        logger.info("%s adapter published a post (mock)", self.channel)
        return measurements


    def fetch_metrics(self, facts: PostFacts, now: datetime) -> MetricValues:
        """The post's engagement so far, as the platform's insights API would report it (synthetic)."""
        return synthetic_metrics(facts, now, self._metrics_config, self.spec)


def build_adapters(
    specs: Mapping[str, ChannelSpec], metrics_config: SyntheticMetricsConfig
) -> dict[str, MockChannelAdapter]:
    return {channel: MockChannelAdapter(channel, spec, metrics_config) for channel, spec in specs.items()}
