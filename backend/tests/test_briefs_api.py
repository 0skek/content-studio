import pytest

from app.caption_length import caption_length, published_text
from app.channels import get_channel_specs
from app.generation_clients import GenerationNotConfigured
from app.main import app
from app.dependencies import get_generation_clients

SPECS = get_channel_specs()
BRIEF_BODY = {
    "title": "Pohela Boishakh collection",
    "goal": "Drive visits to the new-year collection",
    "audience": "Young professionals in Dhaka",
    "tone": "warm, festive",
    "languages": ["bn", "en"],
}


def test_creating_a_brief_returns_pending_drafts_then_generates_them(client):
    response = client.post("/briefs", json=BRIEF_BODY)

    assert response.status_code == 202
    created = response.json()
    assert {(post["channel"], post["language"]) for post in created["posts"]} == {
        (channel, language) for channel in SPECS for language in ("bn", "en")
    }
    assert all(post["generation_status"] == "pending" for post in created["posts"])

    detail = client.get(f"/briefs/{created['id']}").json()
    assert all(post["generation_status"] == "ready" for post in detail["posts"])
    assert all(post["image_url"].startswith(f"/media/briefs/{created['id']}/") for post in detail["posts"])
    for post in detail["posts"]:
        counting = SPECS[post["channel"]].caption.length_counting
        assert post["published_length"] == caption_length(published_text(post["caption"], post["hashtags"]), counting)


def test_languages_default_to_bengali_and_english(client):
    body = {key: value for key, value in BRIEF_BODY.items() if key != "languages"}

    created = client.post("/briefs", json=body).json()

    assert {post["language"] for post in created["posts"]} == {"bn", "en"}


def test_a_single_language_brief_gets_one_post_per_channel(client):
    created = client.post("/briefs", json={**BRIEF_BODY, "languages": ["bn"]}).json()

    assert sorted(post["channel"] for post in created["posts"]) == sorted(SPECS)
    assert {post["language"] for post in created["posts"]} == {"bn"}


@pytest.mark.parametrize(
    "overrides",
    [{"title": "   "}, {"goal": ""}, {"languages": []}, {"languages": ["fr"]}, {"languages": ["bn", "bn"]}],
)
def test_invalid_briefs_are_rejected(client, overrides):
    response = client.post("/briefs", json={**BRIEF_BODY, **overrides})

    assert response.status_code == 422


def test_missing_keys_give_503_and_create_nothing(client):
    def not_configured():
        raise GenerationNotConfigured("Generation is not configured: set CF_API_TOKEN in .env")

    app.dependency_overrides[get_generation_clients] = not_configured

    response = client.post("/briefs", json=BRIEF_BODY)

    assert response.status_code == 503
    assert "CF_API_TOKEN" in response.json()["detail"]
    assert client.get("/briefs").json() == []


def test_unknown_brief_is_404(client):
    assert client.get("/briefs/999999").status_code == 404


def test_briefs_are_listed_newest_first(client):
    first = client.post("/briefs", json={**BRIEF_BODY, "title": "First"}).json()
    second = client.post("/briefs", json={**BRIEF_BODY, "title": "Second"}).json()

    listed = client.get("/briefs").json()

    assert [brief["id"] for brief in listed] == [second["id"], first["id"]]


def test_channels_endpoint_serves_the_specs(client):
    channels = {channel["id"]: channel for channel in client.get("/channels").json()}

    assert set(channels) == set(SPECS)
    for channel_id, spec in SPECS.items():
        assert (channels[channel_id]["width"], channels[channel_id]["height"]) == (spec.image.width, spec.image.height)
        assert channels[channel_id]["length_counting"] == spec.caption.length_counting
