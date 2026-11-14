"""WEB-84: Live's demo deck (GET /dpr/live/deck, ``domains/dpr/deck.py``): the stories and their ready messages.

The guard that matters: a ready message is a real entry once sent, so only a company marked as a demo is given
any story; and a story's messages name only the sites this person can see."""

from __future__ import annotations

import uuid

import pytest

from mesiri.authorization.context import (
    AccessPolicy,
    AuthorizationContext,
    ProjectAccessScope,
    SiteAccessScope,
)
from mesiri.domains.dpr import board, deck
from mesiri.domains.dpr import router as dpr_router

ORG, P1, S1, S2 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def test_five_stories_in_the_plans_order_each_ending_on_an_owners_question():
    out = deck.stories(["Main block", "Annex"])
    assert [s["key"] for s in out] == ["delivery", "day", "wrong", "asks", "night"]
    assert [s["key"] for s in out if s["short"]] == ["delivery", "night"]
    questions = {q.key for q in board.QUESTIONS}
    for story in out:
        assert story["ends_on"] in questions and story["steps"]
        for step in story["steps"]:
            assert step["say"] and (step["send"] or step["do"])  # every step says something and does something
        assert any(step["send"] for step in story["steps"])  # and every story sends at least one message


def test_the_messages_name_the_demos_own_sites():
    out = {s["key"]: s for s in deck.stories(["Main block", "Annex"])}
    assert out["delivery"]["steps"][0]["send"] == "50 bags cement came at Main block today, rate 400 per bag"
    assert out["wrong"]["steps"][0]["send"] == "5000 bags cement used at Annex today"
    text = " ".join(str(v) for s in out.values() for step in s["steps"] for v in step.values() if v)
    assert "{" not in text and "}" not in text


def test_one_site_or_none_still_gives_whole_messages():
    one = {s["key"]: s for s in deck.stories(["Tower A"])}
    assert one["wrong"]["steps"][0]["send"] == "5000 bags cement used at Tower A today"
    none = deck.stories([])
    assert "the site" in none[0]["steps"][0]["send"]


class _Settings:
    value: object = True
    ready: object = None

    def __init__(self, conn):
        pass

    async def get(self, org, key):
        assert key in ("demo_company", "live_ready_messages")
        return _Settings.value if key == "demo_company" else _Settings.ready


class _Conn:
    asked = 0

    async def execute(self, *_a, **_k):
        _Conn.asked += 1

        class _Rows:
            def all(self):
                row = lambda site, name: type("R", (), {"id": site, "project_id": P1, "name": name})()  # noqa: E731
                return [row(S1, "Main block"), row(S2, "Annex")]

        return _Rows()


def _ctx(sites=None):
    scope = ProjectAccessScope(mode="custom_projects", project_ids={P1})
    site_scope = SiteAccessScope(mode="all_sites", site_ids=set()) if sites is None else SiteAccessScope(mode="custom_sites", site_ids=set(sites))
    return AuthorizationContext(user_id=uuid.uuid4(), organization_id=ORG, role="ADMIN", status="active",
                                access_policy=AccessPolicy(mode=scope.mode, projects=[]), project_scope=scope,
                                site_scopes={P1: site_scope})


@pytest.fixture
def route(monkeypatch):
    monkeypatch.setattr(
        "mesiri.infrastructure.postgres.repositories.organization_settings.PostgresOrganizationSettingsRepository", _Settings)
    _Settings.value, _Settings.ready, _Conn.asked = True, None, 0


async def test_a_demo_company_gets_the_stories(route):
    out = await dpr_router.live_demo_deck(auth_context=_ctx(), conn=_Conn())
    assert out["demo"] is True and out["reset"] is True and len(out["stories"]) == 6
    assert [s["key"] for s in out["stories"] if s["test"]] == ["test"]  # the test list comes last
    assert "Main block" in out["stories"][0]["steps"][0]["send"]


@pytest.mark.parametrize("stored", [False, None, "true", 1])
async def test_guard_any_other_company_gets_no_story_and_nothing_is_read(route, stored):
    _Settings.value = stored
    assert await dpr_router.live_demo_deck(auth_context=_ctx(), conn=_Conn()) == {
        "demo": False, "reset": False, "stories": []}
    assert _Conn.asked == 0


@pytest.mark.parametrize("ready", [False, None, "true", 1])
async def test_guard_the_test_switch_must_be_exactly_true(route, ready):
    _Settings.value, _Settings.ready = False, ready
    assert (await dpr_router.live_demo_deck(auth_context=_ctx(), conn=_Conn()))["stories"] == []
    assert _Conn.asked == 0


async def test_the_test_company_gets_the_ready_messages_without_being_a_demo(route):
    """Asked 14 Nov: Mesiri Test Builders (live_ready_messages, migration 0550) gets Stories and the test list,
    and is not offered the demo's one-tap reset."""
    _Settings.value, _Settings.ready = False, True
    out = await dpr_router.live_demo_deck(auth_context=_ctx(), conn=_Conn())
    assert out["demo"] is True and out["reset"] is False
    assert out["stories"][-1]["key"] == "test" and out["stories"][-1]["test"] is True


async def test_guard_the_messages_name_only_the_sites_this_person_sees(route):
    out = await dpr_router.live_demo_deck(auth_context=_ctx(sites=[S2]), conn=_Conn())
    text = " ".join(step["send"] or "" for s in out["stories"] for step in s["steps"])
    assert "Annex" in text and "Main block" not in text


def test_the_wrong_entry_story_says_what_the_assistant_really_does():
    """Run on the real assistant (13 Nov): an entry beyond the stock is saved and marked, not refused; and one
    message takes it back. The story must not promise that Mesiri stops it."""
    wrong = next(s for s in deck.stories(["Main block", "Annex"]) if s["key"] == "wrong")
    said = " ".join(step["say"] for step in wrong["steps"]).lower()
    assert "mesiri stops" not in said and "marks it" in said
    sends = [step["send"] for step in wrong["steps"] if step["send"]]
    assert sends == ["5000 bags cement used at Annex today",
                     "That 5000 bags cement used at Annex was a mistake, take it back",
                     "30 bags cement used at Main block today"]


def test_the_test_list_has_a_ready_message_for_every_kind_with_a_ripple_and_names_the_sites():
    """Asked 14 Nov: one ready message for every kind Live shows, so Live can be tested without a phone. Every kind
    that has a ripple (``live_feed.RECORD_KINDS``), and a question (WEB-87), has a message to send."""
    from mesiri.domains.dpr import live_feed

    test = deck.stories(["Main block", "Annex"], test=True)[-1]
    assert test["test"] is True and test["ends_on"] in {q.key for q in board.QUESTIONS}
    kinds = {step["kind"] for step in test["steps"]}
    assert kinds <= set(live_feed.KIND_LABELS)
    sent = {step["kind"] for step in test["steps"] if step["send"]}
    assert {live_feed.WRITE_KINDS[tool] for tool in live_feed.RECORD_KINDS} - {"expense"} <= sent
    assert {"question", "correction", "undo", "report", "transfer", "expense"} <= sent
    text = " ".join(step["send"] or "" for step in test["steps"])
    assert "Main block" in text and "Annex" in text and "{" not in text
    assert all(step["say"] for step in test["steps"])


def test_guard_the_stories_alone_leave_the_test_list_out():
    assert all(not s["test"] for s in deck.stories(["Main block"]))
