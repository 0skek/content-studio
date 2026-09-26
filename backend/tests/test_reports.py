"""The weekly report cites only real post IDs (rule 5), and its insights reach brief creation (rule 4).

Rule 5 done-check: a report citing a post that does not exist is regenerated, and one that never gets its
citations right is not saved. Rule 4 done-check: the latest insights are offered for the brief form and the
chosen ones are injected into the generation prompts.
"""

from datetime import timedelta

import pytest

from app.models import Insight, Language, Metric, PostStatus, Report
from app.post_status import transition
from app.prompts import BENGALI_COPY_OPENING, CopySet, SceneSet
from app.reporting import MAX_REPORT_ATTEMPTS, ReportClaim, ReportDraft, citation_problems
from tests.conftest import TEST_NOW

UNKNOWN_POST_ID = 999_999


@pytest.fixture
def week_of_posts(session, make_publishable_post):
    """Three published posts with metrics: Instagram in both languages and one X post."""
    posts = []
    for channel, language, impressions, engagements in (
        ("instagram", Language.BENGALI, 3000, 180),
        ("instagram", Language.ENGLISH, 3200, 120),
        ("x", Language.ENGLISH, 2500, 30),
    ):
        post = make_publishable_post(channel=channel)
        post.language = language
        transition(post, PostStatus.PUBLISHED)
        post.published_at = TEST_NOW - timedelta(days=1)
        session.add(
            Metric(
                post_id=post.id, fetched_at=TEST_NOW, impressions=impressions, likes=engagements,
                comments=0, shares=0, clicks=engagements // 10,
            )
        )
        posts.append(post)
    session.commit()
    return posts


def claim(text, *post_ids):
    return ReportClaim(text=text, post_ids=list(post_ids))


def report_citing(*post_ids, finding_text="Instagram Bengali led on engagement rate."):
    return ReportDraft(
        summary=claim("A steady week.", *post_ids),
        findings=[claim(finding_text, *post_ids)],
        insights=[claim("Lead with Bengali on Instagram.", *post_ids)],
    )


# ---------------------------------------------------------------- citation validation


def test_citations_of_real_posts_pass():
    assert citation_problems(report_citing(1, 2), known_post_ids={1, 2, 3}) == []


def test_a_made_up_post_id_is_a_problem():
    problems = citation_problems(report_citing(1, UNKNOWN_POST_ID), known_post_ids={1})

    assert f"finding 1 cites #{UNKNOWN_POST_ID}, which is not a post in this week's data" in problems


def test_a_claim_without_citations_is_a_problem():
    draft = report_citing(1)
    draft.findings.append(claim("Engagement rose everywhere."))

    assert citation_problems(draft, known_post_ids={1}) == ['finding 2 cites no post IDs: "Engagement rose everywhere."']


def test_an_id_mentioned_only_in_the_text_is_checked_too():
    draft = report_citing(1, finding_text=f"Post #{UNKNOWN_POST_ID} did best.")

    assert citation_problems(draft, known_post_ids={1}) == [
        f"finding 1 cites #{UNKNOWN_POST_ID}, which is not a post in this week's data"
    ]


# ---------------------------------------------------------------- generating reports


def test_the_report_cites_only_this_weeks_posts_and_is_saved(client, fake_text, week_of_posts):
    response = client.post("/reports")

    body = response.json()
    published_ids = {post.id for post in week_of_posts}
    assert response.status_code == 201
    assert body["cited_post_ids"] and set(body["cited_post_ids"]) <= published_ids
    assert body["content"]["findings"] and body["content"]["summary"]["post_ids"]
    assert [insight["text"] for insight in body["insights"]] == [
        claim.text for claim in ReportDraft.model_validate(body["content"]).insights
    ]
    evidence = body["evidence"]
    assert {post["post_id"] for post in evidence["posts"]} == published_ids
    instagram_bengali = next(
        group for group in evidence["groups"] if group["kind"] == "channel_language" and group["channel"] == "instagram"
        and group["language"] == Language.BENGALI
    )
    assert instagram_bengali["engagement_rate"] == 0.06 and instagram_bengali["post_ids"] == [week_of_posts[0].id]
    assert {group["kind"] for group in evidence["groups"]} == {
        "channel", "channel_language", "channel_hashtags", "channel_length"
    }
    prompt = fake_text.report_calls()[0].prompt
    assert all(f"- post #{post_id}:" in prompt for post_id in published_ids)
    assert "Instagram Bengali: posts" in prompt and "engagement rate 6.00%" in prompt


def test_rule_5_a_made_up_citation_makes_the_model_rewrite_the_report(client, fake_text, week_of_posts):
    real = week_of_posts[0].id
    fake_text.report_versions = [report_citing(real, UNKNOWN_POST_ID), report_citing(real)]

    response = client.post("/reports")

    assert response.status_code == 201
    assert response.json()["cited_post_ids"] == [real]
    calls = fake_text.report_calls()
    assert len(calls) == 2
    assert f"cites #{UNKNOWN_POST_ID}, which is not a post in this week's data" in calls[1].prompt


def test_rule_5_a_report_that_never_cites_correctly_is_not_saved(client, session, fake_text, week_of_posts):
    fake_text.report_versions = [report_citing(UNKNOWN_POST_ID)]

    response = client.post("/reports")

    assert response.status_code == 502
    assert f"after {MAX_REPORT_ATTEMPTS} attempts" in response.json()["detail"]
    assert len(fake_text.report_calls()) == MAX_REPORT_ATTEMPTS
    assert session.query(Report).count() == 0 and session.query(Insight).count() == 0


def test_posts_older_than_a_week_are_not_in_the_report(client, session, fake_text, week_of_posts):
    old = week_of_posts[2]
    old.published_at = TEST_NOW - timedelta(days=8)
    session.commit()
    fake_text.report_versions = [report_citing(old.id)]

    response = client.post("/reports")

    assert response.status_code == 502
    assert f"- post #{old.id}:" not in fake_text.report_calls()[0].prompt


def test_posts_published_during_a_fast_forward_stay_in_the_report_after_a_reset(
    client, session, fake_text, week_of_posts
):
    later = week_of_posts[0]
    later.published_at = TEST_NOW + timedelta(hours=30)
    session.commit()

    client.post("/reports")

    assert f"- post #{later.id}:" in fake_text.report_calls()[0].prompt


def test_no_report_without_published_posts(client, fake_text):
    response = client.post("/reports")

    assert response.status_code == 409 and "publish some posts first" in response.json()["detail"]
    assert fake_text.report_calls() == []


def test_reports_are_listed_newest_first(client, week_of_posts):
    first = client.post("/reports").json()["id"]
    second = client.post("/reports").json()["id"]

    assert [report["id"] for report in client.get("/reports").json()] == [second, first]


# ---------------------------------------------------------------- insights into the next brief


BRIEF_WITH_INSIGHTS = {
    "title": "Eid family collection",
    "goal": "Bring families to the store",
    "audience": "Parents in Dhaka",
    "tone": "warm",
}


def test_rule_4_the_latest_insights_are_offered_for_the_brief_form(client, week_of_posts):
    report = client.post("/reports").json()

    offered = client.get("/insights/latest").json()

    assert [insight["id"] for insight in offered] == [insight["id"] for insight in report["insights"]]
    assert all(insight["report_id"] == report["id"] for insight in offered)


def test_no_insights_before_the_first_report(client):
    assert client.get("/insights/latest").json() == []


def test_rule_4_chosen_insights_are_injected_into_every_generation_prompt(client, fake_text, week_of_posts):
    insights = client.post("/reports").json()["insights"]
    chosen = insights[0]

    response = client.post("/briefs", json={**BRIEF_WITH_INSIGHTS, "insight_ids": [chosen["id"]]})

    assert response.status_code == 202
    assert response.json()["insights_used"] == [
        {"id": chosen["id"], "report_id": chosen["report_id"], "text": chosen["text"]}
    ]
    scene_prompt = next(call.prompt for call in fake_text.calls if call.schema is SceneSet)
    copy_prompts = [call.prompt for call in fake_text.calls if call.schema is CopySet]
    assert chosen["text"] in scene_prompt
    assert len(copy_prompts) == 2 and all(chosen["text"] in prompt for prompt in copy_prompts)
    assert any(BENGALI_COPY_OPENING in prompt for prompt in copy_prompts)
    assert insights[1]["text"] not in scene_prompt  # only the chosen ones


def test_an_unknown_insight_id_is_refused(client):
    response = client.post("/briefs", json={**BRIEF_WITH_INSIGHTS, "insight_ids": [UNKNOWN_POST_ID]})

    assert response.status_code == 422 and str(UNKNOWN_POST_ID) in response.json()["detail"]
