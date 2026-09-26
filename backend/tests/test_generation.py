"""Generation of a brief's drafts, including the milestone 2 done-check (rule 1) and native languages (rule 6)."""

import pytest
from PIL import Image
from sqlalchemy import select

from app.channels import get_channel_specs
from app.cloudflare_images import ImageGenerationError
from app.gemini_text import TextGenerationError
from app.generation_service import (
    BRIEFS_MEDIA_SUBDIR,
    INTERRUPTED_MESSAGE,
    MAX_COPY_ATTEMPTS,
    create_brief_with_drafts,
    fail_interrupted_generation,
    limit_problems,
    run_brief_generation,
)
from app.models import GenerationStatus, Language, Post
from app.prompts import BENGALI_COPY_OPENING, HEADLINE_MAX_WORDS, NO_TEXT_CLAUSE, ChannelCopy
from app.schemas import BriefCreate
from tests.fakes import default_copy

BRIEF_INPUT = BriefCreate(
    title="Pohela Boishakh collection",
    goal="Drive visits to the new-year collection",
    audience="Young professionals in Dhaka",
    tone="warm, festive",
)
SPECS = get_channel_specs()


@pytest.fixture
def brief(session):
    return create_brief_with_drafts(session, BRIEF_INPUT)


@pytest.fixture
def generate(brief, generation_clients, session_factory, media_dir):
    def run() -> dict[tuple[str, Language], Post]:
        run_brief_generation(brief.id, generation_clients, session_factory, media_dir)
        with session_factory() as fresh_session:
            posts = fresh_session.scalars(select(Post).where(Post.brief_id == brief.id)).all()
            return {(post.channel, Language(post.language)): post for post in posts}

    return run


def brief_dir(media_dir, brief):
    return media_dir / BRIEFS_MEDIA_SUBDIR / str(brief.id)


def test_each_channel_image_is_generated_separately_at_its_native_size(generate, fake_images, media_dir, brief):
    """Milestone 2 done-check: 3 images, 3 different sizes, 3 separate generations."""
    posts = generate()

    channel_sizes = {(spec.image.width, spec.image.height) for spec in SPECS.values()}
    requested_sizes = [(call.width, call.height) for call in fake_images.calls]
    assert len(SPECS) == 3
    assert len(channel_sizes) == 3
    assert sorted(requested_sizes) == sorted(channel_sizes)
    assert len({call.prompt for call in fake_images.calls}) == 3

    for channel, spec in SPECS.items():
        with Image.open(brief_dir(media_dir, brief) / f"{channel}-base.jpg") as base_image:
            assert base_image.size == (spec.image.width, spec.image.height)

    assert len(posts) == 6
    for (channel, _language), post in posts.items():
        spec = SPECS[channel]
        final_path = media_dir / post.image_path
        assert post.generation_status == GenerationStatus.READY
        with Image.open(final_path) as final_image:
            assert final_image.size == (spec.image.width, spec.image.height) == (post.width, post.height)
        assert post.file_size_bytes == final_path.stat().st_size


def test_both_languages_share_the_channel_image_but_get_their_own_file(generate):
    posts = generate()

    for channel in SPECS:
        bengali, english = posts[(channel, Language.BENGALI)], posts[(channel, Language.ENGLISH)]
        assert bengali.image_prompt == english.image_prompt
        assert bengali.image_path != english.image_path
        assert bengali.image_path.endswith(f"{channel}-bn-post{bengali.id}.jpg")


def test_wrong_size_from_the_image_service_fails_instead_of_resizing(generate, fake_images, media_dir, brief):
    instagram = SPECS["instagram"].image
    fake_images.returned_sizes[(instagram.width, instagram.height)] = (1024, 1024)

    posts = generate()

    for language in Language:
        post = posts[("instagram", language)]
        assert post.generation_status == GenerationStatus.FAILED
        assert f"came back 1024x1024 but {instagram.width}x{instagram.height} was requested" in post.generation_error
        assert post.image_path is None
    assert not (brief_dir(media_dir, brief) / "instagram-base.jpg").exists()
    assert all(post.generation_status == GenerationStatus.READY for (c, _), post in posts.items() if c != "instagram")


def test_each_language_is_written_by_its_own_call_from_the_brief_alone(generate, fake_text):
    """Rule 6: Bengali is generated natively, never from the English output (and vice versa)."""
    posts = generate()

    bengali_calls = fake_text.copy_calls(Language.BENGALI)
    english_calls = fake_text.copy_calls(Language.ENGLISH)
    assert len(bengali_calls) == len(english_calls) == 1
    assert BENGALI_COPY_OPENING in bengali_calls[0].prompt
    assert BENGALI_COPY_OPENING not in english_calls[0].prompt
    for channel in SPECS:
        english_copy = default_copy(Language.ENGLISH, channel)
        bengali_copy = default_copy(Language.BENGALI, channel)
        assert english_copy.caption not in bengali_calls[0].prompt
        assert english_copy.headline not in bengali_calls[0].prompt
        assert bengali_copy.caption not in english_calls[0].prompt
        assert posts[(channel, Language.BENGALI)].caption == bengali_copy.caption


def test_every_image_prompt_forbids_text(generate, fake_images):
    generate()

    assert fake_images.calls
    assert all(NO_TEXT_CLAUSE in call.prompt for call in fake_images.calls)


def over_limit_x_copy(language: Language) -> ChannelCopy:
    x_limit = SPECS["x"].caption.max_chars
    return ChannelCopy(channel="x", headline="Too long", caption="a" * (x_limit + 20), hashtags=["tag"])


def test_over_limit_copy_gets_one_corrective_retry(generate, fake_text):
    fake_text.copy_versions[(Language.ENGLISH, "x")] = [
        over_limit_x_copy(Language.ENGLISH),
        default_copy(Language.ENGLISH, "x"),
    ]

    posts = generate()

    english_calls = fake_text.copy_calls(Language.ENGLISH)
    assert len(english_calls) == 2
    assert f"the limit is {SPECS['x'].caption.max_chars}" in english_calls[1].prompt
    assert len(fake_text.copy_calls(Language.BENGALI)) == 1
    assert posts[("x", Language.ENGLISH)].generation_status == GenerationStatus.READY


def test_copy_still_over_limit_after_the_retry_fails_only_that_post(generate, fake_text):
    fake_text.copy_versions[(Language.ENGLISH, "x")] = [over_limit_x_copy(Language.ENGLISH)]

    posts = generate()

    failed = posts[("x", Language.ENGLISH)]
    assert failed.generation_status == GenerationStatus.FAILED
    assert f"after {MAX_COPY_ATTEMPTS} attempts" in failed.generation_error
    assert f"the limit is {SPECS['x'].caption.max_chars}" in failed.generation_error
    others = [post for key, post in posts.items() if key != ("x", Language.ENGLISH)]
    assert all(post.generation_status == GenerationStatus.READY for post in others)


def test_image_failure_fails_only_that_channels_posts(generate, fake_images):
    linkedin = SPECS["linkedin"].image
    fake_images.errors[(linkedin.width, linkedin.height)] = ImageGenerationError("Cloudflare timed out after 90s")

    posts = generate()

    for (channel, _language), post in posts.items():
        if channel == "linkedin":
            assert post.generation_status == GenerationStatus.FAILED
            assert post.generation_error == "Cloudflare timed out after 90s"
        else:
            assert post.generation_status == GenerationStatus.READY


def test_scene_failure_fails_every_post_with_the_reason(generate, fake_text, fake_images):
    fake_text.scene_error = TextGenerationError("Gemini quota exhausted")

    posts = generate()

    assert not fake_images.calls
    assert all(post.generation_status == GenerationStatus.FAILED for post in posts.values())
    assert all(post.generation_error == "Gemini quota exhausted" for post in posts.values())


def test_copy_failure_fails_only_that_language(generate, fake_text):
    fake_text.copy_errors[Language.BENGALI] = TextGenerationError("Gemini request failed (HTTP 500)")

    posts = generate()

    for (_channel, language), post in posts.items():
        expected = GenerationStatus.FAILED if language == Language.BENGALI else GenerationStatus.READY
        assert post.generation_status == expected


def test_an_unexpected_crash_never_leaves_posts_generating(generate, fake_images):
    for spec in SPECS.values():
        fake_images.errors[(spec.image.width, spec.image.height)] = RuntimeError("boom")

    posts = generate()

    assert all(post.generation_status == GenerationStatus.FAILED for post in posts.values())
    assert all("unexpectedly" in post.generation_error for post in posts.values())


def test_hashtags_are_cleaned_up(generate, fake_text):
    fake_text.copy_versions[(Language.ENGLISH, "instagram")] = [
        ChannelCopy(channel="instagram", headline="Hi", caption="Hello", hashtags=["#Pohela Boishakh", "Dhaka", "", "#Dhaka"])
    ]

    posts = generate()

    assert posts[("instagram", Language.ENGLISH)].hashtags == ["PohelaBoishakh", "Dhaka"]


def test_interrupted_generation_is_marked_failed_on_startup(session, brief):
    brief.posts[0].generation_status = GenerationStatus.GENERATING
    session.commit()

    marked = fail_interrupted_generation(session)

    session.expire_all()
    assert marked == len(brief.posts)
    assert all(post.generation_status == GenerationStatus.FAILED for post in brief.posts)
    assert all(post.generation_error == INTERRUPTED_MESSAGE for post in brief.posts)


@pytest.mark.parametrize(
    ("copy", "expected_problem"),
    [
        (ChannelCopy(channel="x", headline="", caption="Hi", hashtags=[]), "headline is empty"),
        (
            ChannelCopy(channel="x", headline=" ".join(["word"] * (HEADLINE_MAX_WORDS + 1)), caption="Hi", hashtags=[]),
            f"the limit is {HEADLINE_MAX_WORDS}",
        ),
        (ChannelCopy(channel="x", headline="Hi", caption="", hashtags=[]), "caption is empty"),
        (ChannelCopy(channel="x", headline="Hi", caption="Hi", hashtags=["a", "b", "c"]), "3 hashtags"),
        (ChannelCopy(channel="x", headline="Hi", caption="🎉" * 141, hashtags=[]), "282 weighted characters"),
    ],
)
def test_limit_problems_are_named(copy, expected_problem):
    problems = limit_problems("x", copy, SPECS["x"])

    assert any(expected_problem in problem for problem in problems)


def test_copy_within_limits_has_no_problems():
    assert limit_problems("x", default_copy(Language.BENGALI, "x"), SPECS["x"]) == []
