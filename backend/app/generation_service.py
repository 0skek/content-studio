"""Turns a brief into draft posts: native copy per language and one separately generated image per channel.

- Rule 1: each channel's image is its own generation at that channel's exact size. A wrong size fails the
  channel; nothing is ever resized or cropped.
- Rule 6: each language's copy comes from its own call built from the brief alone; no language sees another's output.
- Every post the job starts ends `ready` or `failed` with a readable error, never stuck in `generating`.
"""

import io
import logging
from collections.abc import Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from PIL import Image, UnidentifiedImageError
from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker

from app.caption_length import HASHTAG_PREFIX, LengthCounting, caption_length, published_text
from app.channels import ChannelSpec, get_channel_specs
from app.cloudflare_images import ImageGenerationError
from app.gemini_text import TextGenerationError
from app.generation_clients import GenerationClients, ImageClient, TextClient
from app.headline_overlay import overlay_headline
from app.models import Brief, GenerationStatus, Language, Post
from app.prompts import (
    HEADLINE_MAX_WORDS,
    BriefContext,
    ChannelCopy,
    CopySet,
    SceneSet,
    copy_prompt,
    final_image_prompt,
    scene_prompt,
)
from app.schemas import BriefCreate

MAX_COPY_ATTEMPTS = 2
BRIEFS_MEDIA_SUBDIR = "briefs"
INTERRUPTED_MESSAGE = "Generation was interrupted by a server restart."

logger = logging.getLogger(__name__)

OutputT = TypeVar("OutputT")


class BriefNotFound(Exception):
    def __init__(self, brief_id: int) -> None:
        super().__init__(f"Brief {brief_id} does not exist.")
        self.brief_id = brief_id


class ImageSizeMismatch(Exception):
    """The image service returned a size other than the one requested (rule 1: never resize)."""


class UnusableChannelOutput(Exception):
    """A generation call returned nothing usable for one channel."""


@dataclass(frozen=True)
class CopyOutcome:
    accepted: dict[str, ChannelCopy]
    problems: dict[str, str]


# ---------------------------------------------------------------- brief creation and recovery


def create_brief_with_drafts(session: Session, brief_in: BriefCreate) -> Brief:
    """Create the brief and one pending draft per channel x language."""
    brief = Brief(
        title=brief_in.title,
        goal=brief_in.goal,
        audience=brief_in.audience,
        tone=brief_in.tone,
        languages=[str(language) for language in brief_in.languages],
        insights_used=[],
    )
    for channel in get_channel_specs():
        for language in brief_in.languages:
            brief.posts.append(Post(channel=channel, language=language, caption="", hashtags=[]))
    session.add(brief)
    session.commit()
    return brief


def load_brief(session: Session, brief_id: int) -> Brief:
    brief = session.get(Brief, brief_id)
    if brief is None:
        raise BriefNotFound(brief_id)
    return brief


def fail_interrupted_generation(session: Session) -> int:
    """At startup, no job is running, so any pending/generating post was cut off by a restart."""
    result = session.execute(
        update(Post)
        .where(Post.generation_status.in_([GenerationStatus.PENDING, GenerationStatus.GENERATING]))
        .values(generation_status=GenerationStatus.FAILED, generation_error=INTERRUPTED_MESSAGE)
    )
    session.commit()
    return result.rowcount


# ---------------------------------------------------------------- the background job


@dataclass(frozen=True)
class _ChannelJob:
    channel: str
    spec: ChannelSpec
    post_ids: dict[Language, int]
    scenes: Future[dict[str, str]]
    copies: dict[Language, Future[CopyOutcome]]
    images: ImageClient
    media_dir: Path
    brief_dir: Path
    session_factory: sessionmaker[Session]


def run_brief_generation(
    brief_id: int, clients: GenerationClients, session_factory: sessionmaker[Session], media_dir: Path
) -> None:
    """Generate every pending post of a brief. Runs as a background task."""
    started = _start_generation(brief_id, session_factory)
    if started is None:
        return
    context, languages, post_ids = started
    failure_reason = "Generation stopped unexpectedly."
    try:
        specs = get_channel_specs()
        brief_dir = media_dir / BRIEFS_MEDIA_SUBDIR / str(brief_id)
        brief_dir.mkdir(parents=True, exist_ok=True)
        with (
            ThreadPoolExecutor(max_workers=1 + len(languages), thread_name_prefix="text") as text_pool,
            ThreadPoolExecutor(max_workers=len(specs), thread_name_prefix="channel") as channel_pool,
        ):
            scenes = text_pool.submit(_generate_scenes, clients.text, context, specs)
            copies = {
                language: text_pool.submit(_generate_copy, clients.text, context, language, specs)
                for language in languages
            }
            channel_jobs = [
                channel_pool.submit(
                    _produce_channel,
                    _ChannelJob(
                        channel=channel,
                        spec=spec,
                        post_ids={language: post_ids[(channel, language)] for language in languages},
                        scenes=scenes,
                        copies=copies,
                        images=clients.images,
                        media_dir=media_dir,
                        brief_dir=brief_dir,
                        session_factory=session_factory,
                    ),
                )
                for channel, spec in specs.items()
            ]
            for channel_job in channel_jobs:
                channel_job.result()
    except Exception as error:  # Job boundary: record the failure on the posts rather than leave them stuck.
        logger.exception("Generation for brief %s crashed", brief_id)
        failure_reason = f"Generation stopped unexpectedly: {error}"
    finally:
        _fail_posts_still_generating(session_factory, list(post_ids.values()), failure_reason)


def _start_generation(
    brief_id: int, session_factory: sessionmaker[Session]
) -> tuple[BriefContext, list[Language], dict[tuple[str, Language], int]] | None:
    with session_factory() as session:
        brief = session.get(Brief, brief_id)
        if brief is None:
            logger.error("Generation requested for missing brief %s", brief_id)
            return None
        context = BriefContext(
            title=brief.title,
            goal=brief.goal,
            audience=brief.audience,
            tone=brief.tone,
            insights=tuple(str(insight) for insight in brief.insights_used),
        )
        languages = [Language(code) for code in brief.languages]
        post_ids: dict[tuple[str, Language], int] = {}
        for post in brief.posts:
            if post.generation_status == GenerationStatus.PENDING:
                post.generation_status = GenerationStatus.GENERATING
                post_ids[(post.channel, Language(post.language))] = post.id
        session.commit()
    return context, languages, post_ids


def _produce_channel(job: _ChannelJob) -> None:
    """One channel: its own image at its own size, then one headline overlay per language."""
    try:
        scene = _output_for_channel(job.channel, job.scenes.result(), "image scene")
        image_prompt = final_image_prompt(scene)
        image_bytes = job.images.generate(image_prompt, job.spec.image.width, job.spec.image.height)
        _require_native_size(job.channel, image_bytes, job.spec)
        (job.brief_dir / f"{job.channel}-base.jpg").write_bytes(image_bytes)
    except (TextGenerationError, ImageGenerationError, ImageSizeMismatch, UnusableChannelOutput, OSError) as error:
        logger.warning("Channel %s failed: %s", job.channel, error)
        _record_failure(job.session_factory, list(job.post_ids.values()), str(error))
        return

    for language, post_id in job.post_ids.items():
        try:
            outcome = job.copies[language].result()
            if job.channel in outcome.problems:
                raise UnusableChannelOutput(outcome.problems[job.channel])
            copy = _output_for_channel(job.channel, outcome.accepted, f"{language} copy")
            final_bytes = overlay_headline(image_bytes, copy.headline)
            final_path = job.brief_dir / f"{job.channel}-{language}-post{post_id}.jpg"
            final_path.write_bytes(final_bytes)
        except (TextGenerationError, UnusableChannelOutput, OSError) as error:
            logger.warning("Post %s (%s/%s) failed: %s", post_id, job.channel, language, error)
            _record_failure(job.session_factory, [post_id], str(error))
            continue
        _record_ready(
            job.session_factory,
            post_id,
            copy=copy,
            image_prompt=image_prompt,
            image_path=final_path.relative_to(job.media_dir).as_posix(),
            final_bytes=final_bytes,
        )


def _output_for_channel(channel: str, outputs: Mapping[str, OutputT], what: str) -> OutputT:
    if channel not in outputs:
        raise UnusableChannelOutput(f"Gemini returned no {what} for {channel}.")
    return outputs[channel]


def _require_native_size(channel: str, image_bytes: bytes, spec: ChannelSpec) -> None:
    width, height = _image_size(image_bytes, channel)
    expected = (spec.image.width, spec.image.height)
    if (width, height) != expected:
        raise ImageSizeMismatch(
            f"{channel} image came back {width}x{height} but {expected[0]}x{expected[1]} was requested; "
            "refusing to resize or crop it."
        )


def _image_size(image_bytes: bytes, channel: str) -> tuple[int, int]:
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            return image.size
    except (UnidentifiedImageError, OSError) as error:
        raise ImageGenerationError(f"The image service returned data for {channel} that is not an image.") from error


# ---------------------------------------------------------------- text generation


def _generate_scenes(text_client: TextClient, context: BriefContext, specs: dict[str, ChannelSpec]) -> dict[str, str]:
    scene_set = text_client.generate(scene_prompt(context, specs), SceneSet)
    scenes: dict[str, str] = {}
    for scene in scene_set.scenes:
        if scene.channel in specs and scene.channel not in scenes and scene.scene.strip():
            scenes[scene.channel] = scene.scene.strip()
    return scenes


def _generate_copy(
    text_client: TextClient, context: BriefContext, language: Language, specs: dict[str, ChannelSpec]
) -> CopyOutcome:
    """One call for all channels; channels that break a limit get one corrective retry with feedback."""
    accepted: dict[str, ChannelCopy] = {}
    problems: dict[str, list[str]] = {}
    for _attempt in range(MAX_COPY_ATTEMPTS):
        feedback = [problem for channel_problems in problems.values() for problem in channel_problems]
        copy_set = text_client.generate(copy_prompt(context, language, specs, feedback), CopySet)
        returned = {}
        for post in copy_set.posts:
            returned.setdefault(post.channel, post)
        problems = {}
        for channel, spec in specs.items():
            if channel in accepted:
                continue
            if channel not in returned:
                problems[channel] = [f"{channel}: no post was returned"]
                continue
            post = _normalized(returned[channel])
            channel_problems = limit_problems(channel, post, spec)
            if channel_problems:
                problems[channel] = channel_problems
            else:
                accepted[channel] = post
        if not problems:
            break
    return CopyOutcome(
        accepted=accepted,
        problems={
            channel: f"{language} copy for {channel} still breaks limits after {MAX_COPY_ATTEMPTS} attempts: "
            + "; ".join(channel_problems)
            for channel, channel_problems in problems.items()
        },
    )


def _normalized(post: ChannelCopy) -> ChannelCopy:
    hashtags: list[str] = []
    for tag in post.hashtags:
        cleaned = "".join(tag.strip().lstrip(HASHTAG_PREFIX).split())
        if cleaned and cleaned not in hashtags:
            hashtags.append(cleaned)
    return ChannelCopy(
        channel=post.channel, headline=post.headline.strip(), caption=post.caption.strip(), hashtags=hashtags
    )


def limit_problems(channel: str, post: ChannelCopy, spec: ChannelSpec) -> list[str]:
    problems = []
    headline_words = len(post.headline.split())
    if headline_words == 0:
        problems.append(f"{channel}: headline is empty")
    elif headline_words > HEADLINE_MAX_WORDS:
        problems.append(f"{channel}: headline has {headline_words} words; the limit is {HEADLINE_MAX_WORDS}")
    if not post.caption:
        problems.append(f"{channel}: caption is empty")
    if len(post.hashtags) > spec.caption.max_hashtags:
        problems.append(f"{channel}: {len(post.hashtags)} hashtags; the limit is {spec.caption.max_hashtags}")
    length = caption_length(published_text(post.caption, post.hashtags), spec.caption.length_counting)
    if length > spec.caption.max_chars:
        unit = "weighted characters" if spec.caption.length_counting == LengthCounting.X_WEIGHTED else "characters"
        problems.append(
            f"{channel}: caption plus hashtags is {length} {unit}; the limit is {spec.caption.max_chars}"
        )
    return problems


# ---------------------------------------------------------------- recording results


def _record_ready(
    session_factory: sessionmaker[Session],
    post_id: int,
    *,
    copy: ChannelCopy,
    image_prompt: str,
    image_path: str,
    final_bytes: bytes,
) -> None:
    width, height = _image_size(final_bytes, copy.channel)
    with session_factory() as session:
        post = session.get(Post, post_id)
        post.headline = copy.headline
        post.caption = copy.caption
        post.hashtags = copy.hashtags
        post.image_prompt = image_prompt
        post.image_path = image_path
        # Measured from the final overlaid file: that is what the adapters validate.
        post.width = width
        post.height = height
        post.file_size_bytes = len(final_bytes)
        post.generation_status = GenerationStatus.READY
        post.generation_error = None
        session.commit()


def _record_failure(session_factory: sessionmaker[Session], post_ids: list[int], message: str) -> None:
    with session_factory() as session:
        session.execute(
            update(Post)
            .where(Post.id.in_(post_ids))
            .values(generation_status=GenerationStatus.FAILED, generation_error=message)
        )
        session.commit()


def _fail_posts_still_generating(session_factory: sessionmaker[Session], post_ids: list[int], message: str) -> None:
    with session_factory() as session:
        session.execute(
            update(Post)
            .where(Post.id.in_(post_ids), Post.generation_status == GenerationStatus.GENERATING)
            .values(generation_status=GenerationStatus.FAILED, generation_error=message)
        )
        session.commit()
