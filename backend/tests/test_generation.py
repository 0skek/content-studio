"""Generation of a brief's drafts, including the milestone 2 done-check (rule 1) and native languages (rule 6)."""

import io

import pytest
from PIL import Image
from sqlalchemy import select

from app.channels import get_channel_specs
from app.cloudflare_images import ImageGenerationError
from app.gemini_text import TextGenerationError
from app.generation_clients import GenerationClients
from app.generation_service import (
    BRIEFS_MEDIA_SUBDIR,
    INTERRUPTED_MESSAGE,
    MAX_COPY_ATTEMPTS,
    base_image_filename,
    create_brief_with_drafts,
    fail_interrupted_generation,
    limit_problems,
    run_brief_generation,
)
from app.models import GenerationStatus, Language, Post, PostStatus
from app.post_status import transition
from app import generation_service
from app.headline_overlay import DEFAULT_TEXT_ZONE, TextZone
from app.prompts import (
    BENGALI_COPY_OPENING,
    BENGALI_NAME_SPELLING_RULE,
    ENGLISH_NAME_SPELLING_RULE,
    HEADLINE_MAX_WORDS,
    HEADLINE_ZONE_CLAUSES,
    NO_TEXT_CLAUSE,
    BriefContext,
    ChannelCopy,
    CopySet,
    SceneSet,
    copy_prompt,
)
from app.schemas import BriefCreate
from tests.fakes import FAKE_TEXT_ZONE, default_copy, fake_scene

BRIEF_INPUT = BriefCreate(
    title="Poila Baishakh collection",
    goal="Drive visits to the new-year collection",
    audience="Young professionals in Kolkata",
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
        channel_post_ids = [posts[(channel, language)].id for language in Language]
        with Image.open(brief_dir(media_dir, brief) / base_image_filename(channel, channel_post_ids)) as base_image:
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
    assert not list(brief_dir(media_dir, brief).glob("instagram-*.jpg"))
    assert all(post.generation_status == GenerationStatus.READY for (c, _), post in posts.items() if c != "instagram")


def test_a_later_run_regenerates_only_the_pending_post(
    generate, brief, session_factory, fake_images, fake_text, media_dir
):
    first_run = generate()
    replaced = first_run[("x", Language.ENGLISH)]
    with session_factory() as session:
        transition(session.get(Post, replaced.id), PostStatus.DISCARDED)
        retry = Post(brief_id=brief.id, channel="x", language=Language.ENGLISH, caption="", parent_post_id=replaced.id)
        session.add(retry)
        session.commit()
        retry_id = retry.id
    image_calls_before, text_calls_before = len(fake_images.calls), len(fake_text.calls)

    generate()

    x_image = SPECS["x"].image
    assert [(call.width, call.height) for call in fake_images.calls[image_calls_before:]] == [(x_image.width, x_image.height)]
    assert len(fake_text.calls) - text_calls_before == 2  # one scene call, one English copy call
    assert len(fake_text.copy_calls(Language.ENGLISH)) == 2 and len(fake_text.copy_calls(Language.BENGALI)) == 1
    retry_copy_prompt = fake_text.copy_calls(Language.ENGLISH)[-1].prompt
    assert "- x:" in retry_copy_prompt and "- instagram:" not in retry_copy_prompt

    with session_factory() as session:
        regenerated = session.get(Post, retry_id)
        assert regenerated.generation_status == GenerationStatus.READY
        for earlier in first_run.values():
            unchanged = session.get(Post, earlier.id)
            assert unchanged.image_path == earlier.image_path
            assert unchanged.generation_status == GenerationStatus.READY
    x_bengali_id = first_run[("x", Language.BENGALI)].id
    assert (brief_dir(media_dir, brief) / base_image_filename("x", [x_bengali_id, replaced.id])).exists()
    assert (brief_dir(media_dir, brief) / base_image_filename("x", [retry_id])).exists()


def test_on_a_shared_local_gpu_every_text_call_finishes_before_any_image(
    brief, fake_text, fake_images, session_factory, media_dir
):
    text_calls_done_at_each_image = []
    original_generate = fake_images.generate

    def recording_generate(prompt, width, height):
        text_calls_done_at_each_image.append(len(fake_text.calls))
        return original_generate(prompt, width, height)

    fake_images.generate = recording_generate
    clients = GenerationClients(text=fake_text, images=fake_images, text_before_images=True)

    run_brief_generation(brief.id, clients, session_factory, media_dir)

    all_text_calls = 1 + len(Language)  # one scene call plus one copy call per language
    assert text_calls_done_at_each_image == [all_text_calls] * len(SPECS)


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


def test_copy_is_written_for_each_channels_photo(generate, fake_text):
    """The scene is planned first; both languages then write for the same photo, never from each other's copy."""
    generate()

    assert fake_text.calls[0].schema is SceneSet
    copy_calls = [call for call in fake_text.calls if call.schema is CopySet]
    assert len(copy_calls) == len(Language)
    for call in copy_calls:
        for channel in SPECS:
            assert f"- {channel}: {fake_scene(channel)}" in call.prompt


def test_the_headline_zone_the_scene_chose_reaches_the_image_prompt_and_the_overlay(
    generate, fake_text, fake_images, monkeypatch
):
    # Only wide images take a zone beside the subject: square facebook and tall instagram fall back.
    fake_text.scene_zones = {"x": "Right ", "facebook": "left", "instagram": "left"}
    overlaid_zones = {}
    real_overlay = generation_service.overlay_headline

    def recording_overlay(image_bytes, headline, preferred_zone):
        with Image.open(io.BytesIO(image_bytes)) as image:
            overlaid_zones[image.size] = preferred_zone
        return real_overlay(image_bytes, headline, preferred_zone)

    monkeypatch.setattr(generation_service, "overlay_headline", recording_overlay)

    generate()

    expected = {"x": TextZone.RIGHT, "facebook": DEFAULT_TEXT_ZONE, "instagram": DEFAULT_TEXT_ZONE}
    prompts = {(call.width, call.height): call.prompt for call in fake_images.calls}
    for channel, zone in expected.items():
        size = (SPECS[channel].image.width, SPECS[channel].image.height)
        assert HEADLINE_ZONE_CLAUSES[zone] in prompts[size]
        assert overlaid_zones[size] == zone


def test_a_valid_zone_from_the_scene_writer_is_kept(generate, fake_images):
    generate()

    assert all(HEADLINE_ZONE_CLAUSES[TextZone(FAKE_TEXT_ZONE)] in call.prompt for call in fake_images.calls)


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
    facebook = SPECS["facebook"].image
    fake_images.errors[(facebook.width, facebook.height)] = ImageGenerationError("Cloudflare timed out after 90s")

    posts = generate()

    for (channel, _language), post in posts.items():
        if channel == "facebook":
            assert post.generation_status == GenerationStatus.FAILED
            assert post.generation_error == "Cloudflare timed out after 90s"
        else:
            assert post.generation_status == GenerationStatus.READY


def test_scene_failure_fails_every_post_with_the_reason(generate, fake_text, fake_images):
    fake_text.scene_error = TextGenerationError("Gemini quota exhausted")

    posts = generate()

    assert not fake_images.calls
    assert not [call for call in fake_text.calls if call.schema is CopySet]  # no quota spent on copy
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
        ChannelCopy(channel="instagram", headline="Hi", caption="Hello", hashtags=["#Poila Baishakh", "Kolkata", "", "#Kolkata"])
    ]

    posts = generate()

    assert posts[("instagram", Language.ENGLISH)].hashtags == ["PoilaBaishakh", "Kolkata"]


def test_extra_hashtags_are_trimmed_to_the_channel_limit_without_a_retry(generate, fake_text):
    limit = SPECS["x"].caption.max_hashtags
    tags = [f"tag{number}" for number in range(limit + 2)]
    fake_text.copy_versions[(Language.ENGLISH, "x")] = [
        ChannelCopy(channel="x", headline="Hi", caption="Visit us this week", hashtags=tags)
    ]

    posts = generate()

    post = posts[("x", Language.ENGLISH)]
    assert post.generation_status == GenerationStatus.READY
    assert post.hashtags == tags[:limit]  # the model's first tags are kept
    assert len(fake_text.copy_calls(Language.ENGLISH)) == 1  # no quota spent on a retry


def test_hashtag_lines_at_the_end_of_the_caption_move_into_the_hashtags(generate, fake_text):
    fake_text.copy_versions[(Language.ENGLISH, "facebook")] = [
        ChannelCopy(
            channel="facebook", headline="Hi", caption="Visit us this week.\n\n#Eid #Kolkata\n", hashtags=["eid", "Craft"]
        )
    ]

    posts = generate()

    post = posts[("facebook", Language.ENGLISH)]
    assert post.caption == "Visit us this week."
    assert post.hashtags == ["eid", "Craft", "Kolkata"]  # counted once, ignoring case


def test_hashtags_inside_sentences_are_never_removed(generate, fake_text):
    limit = SPECS["x"].caption.max_hashtags
    caption = "Celebrate " + " and ".join(f"#word{number}" for number in range(limit + 1)) + " with us"
    fake_text.copy_versions[(Language.ENGLISH, "x")] = [
        ChannelCopy(channel="x", headline="Hi", caption=caption, hashtags=["extra"])
    ]

    posts = generate()

    post = posts[("x", Language.ENGLISH)]
    assert post.generation_status == GenerationStatus.FAILED
    assert f"{limit + 1} hashtags; the limit is {limit}" in post.generation_error


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
    problems = limit_problems("x", copy, SPECS["x"], Language.ENGLISH)

    assert any(expected_problem in problem for problem in problems)


@pytest.mark.parametrize("language", list(Language))
def test_copy_within_limits_has_no_problems(language):
    assert limit_problems("x", default_copy(language, "x"), SPECS["x"], language) == []


BENGALI_X_COPY = ChannelCopy(
    channel="x",
    headline="পয়লা বৈশাখ কালেকশন",
    caption="নতুন বছরের দেশি পোশাকের সংগ্রহ দেখতে আজই আমাদের বুটিকে চলে আসুন।",
    hashtags=["PoilaBaishakh"],
)


def test_english_post_written_in_bengali_is_a_problem():
    """The real failure seen live: a fallback model wrote the English X post in Bengali."""
    problems = limit_problems("x", BENGALI_X_COPY, SPECS["x"], Language.ENGLISH)

    assert any("headline must be written in English, but 100% of its letters are Bengali" in p for p in problems)
    assert any("caption must be written in English" in p for p in problems)


def test_bengali_post_written_in_english_is_a_problem():
    problems = limit_problems("x", default_copy(Language.ENGLISH, "x"), SPECS["x"], Language.BENGALI)

    assert any("headline must be written in Bengali, but only 0% of its letters are Bengali" in p for p in problems)


@pytest.mark.parametrize(
    ("copy", "language"),
    [
        (
            ChannelCopy(channel="x", headline="Biba-তে নতুন বৈশাখী সাজ", caption="Biba-তে আসুন, নতুন সাজে সাজুন", hashtags=[]),
            Language.BENGALI,
        ),
        (
            ChannelCopy(channel="x", headline="Shubho Noboborsho", caption="Happy new year to all of Kolkata! শুভ", hashtags=[]),
            Language.ENGLISH,
        ),
        (ChannelCopy(channel="x", headline="New colours", caption="Visit us", hashtags=["পয়লাবৈশাখ"]), Language.ENGLISH),
    ],
    ids=["bengali-with-latin-brand", "english-with-bengali-greeting", "hashtags-are-exempt"],
)
def test_a_little_of_the_other_script_is_fine(copy, language):
    assert limit_problems("x", copy, SPECS["x"], language) == []


def test_wrong_language_copy_gets_a_corrective_retry(generate, fake_text):
    fake_text.copy_versions[(Language.ENGLISH, "x")] = [BENGALI_X_COPY, default_copy(Language.ENGLISH, "x")]

    posts = generate()

    english_calls = fake_text.copy_calls(Language.ENGLISH)
    assert len(english_calls) == 2
    assert "must be written in English" in english_calls[1].prompt
    assert posts[("x", Language.ENGLISH)].headline == default_copy(Language.ENGLISH, "x").headline


def test_wrong_language_copy_after_the_retry_fails_the_post(generate, fake_text):
    fake_text.copy_versions[(Language.ENGLISH, "x")] = [BENGALI_X_COPY]

    posts = generate()

    failed = posts[("x", Language.ENGLISH)]
    assert failed.generation_status == GenerationStatus.FAILED
    assert "must be written in English" in failed.generation_error


@pytest.mark.parametrize("language", list(Language))
def test_copy_prompts_insist_on_their_own_language(language):
    context = BriefContext(title="t", goal="g", audience="a", tone="warm")

    prompt = copy_prompt(context, language, SPECS, scenes={})

    expected = "in English, even if the brief" if language == Language.ENGLISH else "ব্রিফ ইংরেজিতে লেখা থাকলেও"
    assert expected in prompt


@pytest.mark.parametrize("language", list(Language))
def test_copy_prompts_keep_the_briefs_spelling_of_names(language):
    context = BriefContext(title="t", goal="গড়িয়াহাটের দোকানে ভিড় আনা", audience="a", tone="warm")

    prompt = copy_prompt(context, language, SPECS, scenes={"x": "Inside our Gariahat shop"})

    rule = ENGLISH_NAME_SPELLING_RULE if language == Language.ENGLISH else BENGALI_NAME_SPELLING_RULE
    assert rule in prompt
