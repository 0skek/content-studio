"""Channel specs from backend/config/channels.json, the single source of truth for per-channel limits.

Generation and adapter validation both read limits from here; no limit is hardcoded anywhere else.
"""

import json
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator, model_validator

from app.config import settings

BYTES_PER_MEGABYTE = 1024 * 1024


class ChannelConfigError(Exception):
    """channels.json is missing, unreadable, or breaks the spec schema."""


def parse_aspect_ratio(aspect_ratio: str) -> float:
    """Turn a "W:H" string such as "4:5" or "1.91:1" into width / height."""
    parts = aspect_ratio.split(":")
    if len(parts) != 2:
        raise ValueError(f"aspect_ratio {aspect_ratio!r} must look like 'W:H', e.g. '4:5'")
    try:
        ratio_width, ratio_height = (float(part) for part in parts)
    except ValueError as error:
        raise ValueError(f"aspect_ratio {aspect_ratio!r} must contain two numbers, e.g. '4:5'") from error
    if ratio_width <= 0 or ratio_height <= 0:
        raise ValueError(f"aspect_ratio {aspect_ratio!r} must have positive sides")
    return ratio_width / ratio_height


class ImageSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    width: int = Field(gt=0)
    height: int = Field(gt=0)
    aspect_ratio: str
    # Relative tolerance: 0.05 accepts ratios within ±5% of the nominal aspect_ratio.
    aspect_ratio_tolerance: float = Field(gt=0, lt=1)
    max_file_size_mb: float = Field(gt=0)

    @field_validator("aspect_ratio")
    @classmethod
    def _aspect_ratio_parses(cls, aspect_ratio: str) -> str:
        parse_aspect_ratio(aspect_ratio)
        return aspect_ratio

    @model_validator(mode="after")
    def _size_matches_declared_ratio(self) -> "ImageSpec":
        if not self.matches_aspect_ratio(self.width, self.height):
            raise ValueError(
                f"size {self.width}x{self.height} (ratio {self.width / self.height:.3f}) is not within "
                f"±{self.aspect_ratio_tolerance:.0%} of the declared aspect_ratio "
                f"{self.aspect_ratio} ({self.nominal_ratio:.3f})"
            )
        return self

    @property
    def nominal_ratio(self) -> float:
        return parse_aspect_ratio(self.aspect_ratio)

    @property
    def max_file_size_bytes(self) -> int:
        return int(self.max_file_size_mb * BYTES_PER_MEGABYTE)

    def matches_aspect_ratio(self, width: int, height: int) -> bool:
        relative_difference = abs(width / height - self.nominal_ratio) / self.nominal_ratio
        return relative_difference <= self.aspect_ratio_tolerance


class CaptionSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_chars: int = Field(gt=0)
    max_hashtags: int = Field(ge=0)


class ChannelSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    display_name: str = Field(min_length=1)
    image: ImageSpec
    caption: CaptionSpec


_CHANNEL_SPECS_ADAPTER = TypeAdapter(dict[str, ChannelSpec])


def load_channel_specs(path: Path) -> dict[str, ChannelSpec]:
    """Read and validate a channels.json file. Raises ChannelConfigError naming the bad channel and field."""
    try:
        raw_config = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ChannelConfigError(f"Channel config not found at {path}") from error
    except json.JSONDecodeError as error:
        raise ChannelConfigError(f"Channel config {path} is not valid JSON: {error}") from error

    if not isinstance(raw_config, dict) or not raw_config:
        raise ChannelConfigError(f"Channel config {path} must be a non-empty object keyed by channel name")

    try:
        return _CHANNEL_SPECS_ADAPTER.validate_python(raw_config)
    except ValidationError as error:
        raise ChannelConfigError(f"Invalid channel config {path}:\n{error}") from error


@lru_cache(maxsize=1)
def get_channel_specs() -> Mapping[str, ChannelSpec]:
    """The app-wide channel specs, loaded once. Read-only so no caller can change a limit at runtime."""
    return MappingProxyType(load_channel_specs(settings.channels_config_path))
