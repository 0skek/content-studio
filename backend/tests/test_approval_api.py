"""Milestone 3: approve / discard / retry through the API, with every rule enforced in the backend."""

import pytest

from app.channels import get_channel_specs
from app.dependencies import get_generation_clients
from app.generation_clients import GenerationNotConfigured
from app.main import app
from app.models import GenerationStatus, Language, Post, PostStatus
from app.prompts import CopySet

SPECS = get_channel_specs()
BRIEF_BODY = {
    "title": "Pohela Boishakh collection",
    "goal": "Drive visits to the new-year collection",
    "audience": "Young professionals in Dhaka",
    "tone": "warm, festive",
}


def create_generated_brief(client) -> dict[tuple[str, str], dict]:
    """Create a brief (the fakes generate it before the call returns) and index its posts by slot."""
    brief_id = client.post("/briefs", json=BRIEF_BODY).json()["id"]
    return {(post["channel"], post["language"]): post for post in client.get(f"/briefs/{brief_id}").json()["posts"]}


def fetch_post(client, post: dict) -> dict:
    brief = client.get(f"/briefs/{post['brief_id']}").json()
    return next(candidate for candidate in brief["posts"] if candidate["id"] == post["id"])


# ---------------------------------------------------------------- approve


def test_approving_a_ready_draft(client):
    post = create_generated_brief(client)[("instagram", "bn")]

    response = client.post(f"/posts/{post['id']}/approve")

    assert response.status_code == 200
    assert response.json()["status"] == PostStatus.APPROVED
    assert fetch_post(client, post)["status"] == PostStatus.APPROVED


@pytest.mark.parametrize("generation", [GenerationStatus.PENDING, GenerationStatus.GENERATING, GenerationStatus.FAILED])
def test_approving_a_draft_that_is_not_ready_is_refused(client, session_factory, make_post_in_status, generation):
    draft = make_post_in_status(PostStatus.DRAFT, generation=generation)

    response = client.post(f"/posts/{draft.id}/approve")

    assert response.status_code == 409
    assert f"its generation is {generation}" in response.json()["detail"]
    with session_factory() as session:
        assert session.get(Post, draft.id).status == PostStatus.DRAFT


@pytest.mark.parametrize("status", [PostStatus.APPROVED, PostStatus.DISCARDED, PostStatus.SCHEDULED])
def test_approving_a_post_that_is_not_a_draft_is_refused(client, make_post_in_status, status):
    post = make_post_in_status(status)

    response = client.post(f"/posts/{post.id}/approve")

    assert response.status_code == 409
    assert f"cannot move from '{status}' to 'approved'" in response.json()["detail"]


# ---------------------------------------------------------------- discard


def test_discarding_a_draft(client):
    post = create_generated_brief(client)[("linkedin", "en")]

    response = client.post(f"/posts/{post['id']}/discard")

    assert response.status_code == 200
    assert response.json()["status"] == PostStatus.DISCARDED


def test_discarding_an_approved_post_is_refused(client, make_post_in_status):
    approved = make_post_in_status(PostStatus.APPROVED)

    response = client.post(f"/posts/{approved.id}/discard")

    assert response.status_code == 409


# ---------------------------------------------------------------- retry


def test_retrying_a_discarded_post_regenerates_only_that_post(client, fake_images, fake_text, media_dir):
    posts = create_generated_brief(client)
    target, sibling = posts[("x", "en")], posts[("x", "bn")]
    client.post(f"/posts/{target['id']}/discard")
    image_calls_before, text_calls_before = len(fake_images.calls), len(fake_text.calls)

    response = client.post(f"/posts/{target['id']}/retry")

    assert response.status_code == 202
    retry = response.json()
    assert retry["parent_post_id"] == target["id"]
    assert (retry["brief_id"], retry["channel"], retry["language"]) == (target["brief_id"], "x", "en")
    assert retry["status"] == PostStatus.DRAFT
    assert retry["generation_status"] == GenerationStatus.PENDING  # generation runs after the response

    x_image = SPECS["x"].image
    new_image_calls = fake_images.calls[image_calls_before:]
    assert [(call.width, call.height) for call in new_image_calls] == [(x_image.width, x_image.height)]
    new_copy_calls = [call for call in fake_text.calls[text_calls_before:] if call.schema is CopySet]
    assert len(new_copy_calls) == 1

    regenerated = fetch_post(client, retry)
    assert regenerated["generation_status"] == GenerationStatus.READY
    assert regenerated["image_url"] != target["image_url"]
    assert (media_dir / regenerated["image_path"]).exists()
    assert fetch_post(client, target)["status"] == PostStatus.DISCARDED
    assert fetch_post(client, target)["image_url"] == target["image_url"]
    assert fetch_post(client, sibling) == sibling


def test_retrying_a_failed_draft_discards_it_first(client, fake_images):
    linkedin = SPECS["linkedin"].image
    fake_images.errors[(linkedin.width, linkedin.height)] = RuntimeError("Cloudflare is down")
    failed = create_generated_brief(client)[("linkedin", "bn")]
    assert failed["generation_status"] == GenerationStatus.FAILED
    fake_images.errors.clear()

    response = client.post(f"/posts/{failed['id']}/retry")

    assert response.status_code == 202
    assert fetch_post(client, failed)["status"] == PostStatus.DISCARDED
    assert fetch_post(client, response.json())["generation_status"] == GenerationStatus.READY


def test_a_post_can_only_be_retried_once(client):
    post = create_generated_brief(client)[("instagram", "en")]
    client.post(f"/posts/{post['id']}/discard")
    first_retry = client.post(f"/posts/{post['id']}/retry").json()

    response = client.post(f"/posts/{post['id']}/retry")

    assert response.status_code == 409
    assert f"already retried as post #{first_retry['id']}" in response.json()["detail"]


def test_a_retry_can_itself_be_retried(client):
    post = create_generated_brief(client)[("instagram", "en")]
    client.post(f"/posts/{post['id']}/discard")
    first_retry = client.post(f"/posts/{post['id']}/retry").json()
    client.post(f"/posts/{first_retry['id']}/discard")

    second_retry = client.post(f"/posts/{first_retry['id']}/retry")

    assert second_retry.status_code == 202
    assert second_retry.json()["parent_post_id"] == first_retry["id"]


def test_retrying_a_ready_draft_is_refused(client):
    post = create_generated_brief(client)[("x", "bn")]

    response = client.post(f"/posts/{post['id']}/retry")

    assert response.status_code == 409
    assert "discard it before retrying" in response.json()["detail"]


@pytest.mark.parametrize("status", [PostStatus.APPROVED, PostStatus.SCHEDULED])
def test_retrying_an_approved_or_scheduled_post_is_refused(client, make_post_in_status, status):
    post = make_post_in_status(status)

    response = client.post(f"/posts/{post.id}/retry")

    assert response.status_code == 409
    assert f"is {status}" in response.json()["detail"]


def test_retry_without_generation_keys_is_503_and_changes_nothing(client, session_factory):
    post = create_generated_brief(client)[("x", "en")]
    client.post(f"/posts/{post['id']}/discard")

    def not_configured():
        raise GenerationNotConfigured("Generation is not configured: set CF_API_TOKEN in .env")

    app.dependency_overrides[get_generation_clients] = not_configured
    response = client.post(f"/posts/{post['id']}/retry")

    assert response.status_code == 503
    with session_factory() as session:
        assert session.query(Post).filter(Post.parent_post_id == post["id"]).count() == 0


@pytest.mark.parametrize("action", ["approve", "discard", "retry"])
def test_unknown_post_is_404(client, action):
    assert client.post(f"/posts/999999/{action}").status_code == 404


def test_languages_of_the_slot_are_kept(client):
    post = create_generated_brief(client)[("linkedin", "bn")]
    client.post(f"/posts/{post['id']}/discard")

    retry = client.post(f"/posts/{post['id']}/retry").json()

    assert retry["language"] == Language.BENGALI
