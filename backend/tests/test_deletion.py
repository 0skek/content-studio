"""Deleting a brief removes everything built from it, including reports citing its posts; deleting a report
removes its insights; taking a published post down returns it to approved. Nothing left behind cites a post
whose numbers no longer exist (rule 5)."""

from datetime import timedelta

from app.models import Brief, GenerationStatus, Insight, Language, Metric, Post, PostStatus, Report
from app.post_status import transition
from app.reporting import ReportClaim, ReportDraft
from tests.conftest import TEST_NOW

OTHER_BRIEF = {"title": "Winter shawls", "goal": "Launch", "audience": "Kolkata", "tone": "calm"}


def publish_with_metrics(session, post):
    transition(post, PostStatus.PUBLISHED)
    post.published_at = TEST_NOW - timedelta(hours=5)
    session.add(Metric(post_id=post.id, fetched_at=TEST_NOW, impressions=1000, likes=40, comments=2, shares=1, clicks=9))
    session.commit()
    return post


def other_brief_post(session, make_publishable_post):
    """A published post on a second brief, to prove deletion stays inside the brief."""
    other = Brief(**OTHER_BRIEF, languages=["en"])
    session.add(other)
    session.commit()
    post = make_publishable_post(channel="facebook")
    post.brief_id = other.id
    session.commit()
    return publish_with_metrics(session, post)


def test_deleting_a_brief_removes_its_posts_metrics_images_and_retry_chain(client, session, brief, media_dir, make_publishable_post):
    published = publish_with_metrics(session, make_publishable_post())
    discarded = make_publishable_post(channel="instagram", scheduled_at=None)
    retry = Post(brief=brief, channel="instagram", language=Language.ENGLISH, caption="", parent_post_id=discarded.id)
    retry.generation_status = GenerationStatus.FAILED  # its job has finished
    session.add(retry)
    session.commit()
    image_folder = (media_dir / published.image_path).parent
    assert image_folder.exists()
    brief_id, post_ids = brief.id, sorted([published.id, discarded.id, retry.id])

    response = client.delete(f"/briefs/{brief_id}")

    assert response.status_code == 200
    assert response.json()["post_ids"] == post_ids
    session.expunge_all()
    assert session.get(Brief, brief_id) is None
    assert session.query(Post).count() == 0 and session.query(Metric).count() == 0
    assert not image_folder.exists()
    assert client.get(f"/briefs/{brief_id}").status_code == 404


def test_reports_citing_the_deleted_posts_go_too_but_others_stay(client, session, brief, fake_text, make_publishable_post):
    ours = publish_with_metrics(session, make_publishable_post())
    theirs = other_brief_post(session, make_publishable_post)

    def report_citing(post_id):
        claim = ReportClaim(text="Engagement held steady.", post_ids=[post_id])
        return ReportDraft(summary=claim, findings=[claim], insights=[claim])

    fake_text.report_versions = [report_citing(ours.id)]
    citing_ours = client.post("/reports").json()["id"]
    fake_text.report_versions = [report_citing(theirs.id)]
    citing_theirs = client.post("/reports").json()["id"]

    response = client.delete(f"/briefs/{brief.id}")

    assert response.json()["report_ids"] == [citing_ours]
    session.expire_all()
    assert [report.id for report in session.query(Report).all()] == [citing_theirs]
    assert {insight.report_id for insight in session.query(Insight).all()} == {citing_theirs}
    assert session.get(Post, theirs.id) is not None


def test_a_brief_still_generating_cannot_be_deleted(client, session, make_publishable_post):
    post = make_publishable_post(scheduled_at=None)
    generating = Post(brief_id=post.brief_id, channel="x", language=Language.BENGALI, caption="")
    generating.generation_status = GenerationStatus.GENERATING
    session.add(generating)
    session.commit()

    response = client.delete(f"/briefs/{post.brief_id}")

    assert response.status_code == 409
    assert f"#{generating.id}" in response.json()["detail"]
    session.expire_all()
    assert session.get(Post, post.id) is not None


def test_deleting_an_unknown_brief_is_404(client):
    assert client.delete("/briefs/999").status_code == 404


def test_deleting_a_report_removes_its_insights_and_the_previous_report_becomes_latest(client, session, make_publishable_post):
    publish_with_metrics(session, make_publishable_post())
    first = client.post("/reports").json()
    second = client.post("/reports").json()

    assert client.delete(f"/reports/{second['id']}").status_code == 204

    session.expire_all()
    assert session.get(Report, second["id"]) is None
    assert session.query(Insight).filter_by(report_id=second["id"]).count() == 0
    assert [insight["report_id"] for insight in client.get("/insights/latest").json()] == [first["id"]] * len(
        first["insights"]
    )


def test_briefs_keep_the_insights_they_applied_after_the_report_is_deleted(client, session, make_publishable_post):
    publish_with_metrics(session, make_publishable_post())
    report = client.post("/reports").json()
    chosen = report["insights"][0]
    created = client.post("/briefs", json={**OTHER_BRIEF, "insight_ids": [chosen["id"]]}).json()

    client.delete(f"/reports/{report['id']}")

    assert client.get(f"/briefs/{created['id']}").json()["insights_used"][0]["text"] == chosen["text"]


def test_deleting_an_unknown_report_is_404(client):
    assert client.delete("/reports/999").status_code == 404


# ---------------------------------------------------------------- taking a published post down


def test_taking_a_post_down_removes_it_from_the_feed_and_returns_it_to_approved(client, session, make_publishable_post):
    post = publish_with_metrics(session, make_publishable_post(channel="instagram"))

    response = client.post(f"/posts/{post.id}/take-down")

    body = response.json()
    assert response.status_code == 200
    assert body["post"]["status"] == PostStatus.APPROVED
    assert body["post"]["published_at"] is None and body["post"]["scheduled_at"] is None
    assert client.get("/feeds").json()["instagram"] == []
    session.expire_all()
    assert session.query(Metric).filter_by(post_id=post.id).count() == 0


def test_a_taken_down_post_can_be_published_again_with_fresh_metrics(client, session, make_publishable_post):
    post = publish_with_metrics(session, make_publishable_post())
    client.post(f"/posts/{post.id}/take-down")

    client.post(f"/posts/{post.id}/schedule", json={"scheduled_at": TEST_NOW.isoformat()})
    run = client.post("/clock/advance", json={"hours": 1}).json()

    assert run["published"] == [post.id] and run["metrics_ingested"] == [post.id]
    feed_post = client.get("/feeds").json()["x"][0]
    assert feed_post["post"]["id"] == post.id
    assert feed_post["performance"]["fetched_at"] is not None


def test_reports_citing_a_taken_down_post_are_deleted(client, session, make_publishable_post):
    post = publish_with_metrics(session, make_publishable_post())
    report = client.post("/reports").json()

    body = client.post(f"/posts/{post.id}/take-down").json()

    assert body["deleted_report_ids"] == [report["id"]]
    assert client.get("/reports").json() == []


def test_only_published_posts_can_be_taken_down(client, make_publishable_post):
    scheduled = make_publishable_post()

    response = client.post(f"/posts/{scheduled.id}/take-down")

    assert response.status_code == 409
    assert "cannot move from 'scheduled' to 'approved'" in response.json()["detail"]


def test_taking_down_an_unknown_post_is_404(client):
    assert client.post("/posts/999/take-down").status_code == 404
