"""HTTP routes exposing the channel specs from channels.json to the UI."""

from fastapi import APIRouter

from app.channels import get_channel_specs
from app.schemas import ChannelOut

router = APIRouter(prefix="/channels", tags=["channels"])


@router.get("", response_model=list[ChannelOut])
def list_channels() -> list[ChannelOut]:
    return [
        ChannelOut(
            id=channel,
            display_name=spec.display_name,
            width=spec.image.width,
            height=spec.image.height,
            aspect_ratio=spec.image.aspect_ratio,
            max_file_size_mb=spec.image.max_file_size_mb,
            caption_max_chars=spec.caption.max_chars,
            max_hashtags=spec.caption.max_hashtags,
            length_counting=spec.caption.length_counting,
        )
        for channel, spec in get_channel_specs().items()
    ]
