"""SET-08 / SET-11 / SET-09 / SET-10 / SET-07: setup answers that depend on the project."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from backend.ports import ActorIdentity, ProjectSummary
from context.live_identity import SIGNUP_URL, unregistered_message
from mesiri.infrastructure.redis.client import FakeRedis
from runtime import join_journey as jj
from runtime import setup_questions as sq
from runtime.agent.journey_gateway import JourneyGateway

ORG = uuid.uuid4()
P1 = ProjectSummary(id=str(uuid.uuid4()), name="Green Villa")
P2 = ProjectSummary(id=str(uuid.uuid4()), name="Lake View")


def _actor(projects) -> ActorIdentity:
    return ActorIdentity(
        user_id=str(uuid.uuid4()),
        full_name="Suresh",
        role="ADMIN",
        organization_id=ORG,
        org_name="Suresh Builders",
        org_active=True,
        projects=list(projects),
    )


def _tap(reply_id):
    return SimpleNamespace(metadata={"interactive_reply_id": reply_id})


class _Conn:
    def __init__(self, log):
        self.log = log

    async def execute(self, stmt):
        self.log.append(stmt)
        return SimpleNamespace(first=lambda: None)


class _Tx:
    def __init__(self, log):
        self.log = log

    async def __aenter__(self):
        return _Conn(self.log)

    async def __aexit__(self, *exc):
        return None


@pytest.fixture
def setup(monkeypatch):
    statements: list = []
    started: list = []

    async def follow_up(**kwargs):
        started.append(kwargs)
        return sq.ReplySpec(text="What's the site called?")

    q = sq.SetupQuestions(
        db=SimpleNamespace(transaction=lambda: _Tx(statements)),
        redis=FakeRedis(),
        storage=None,
        notifier=None,
        workflow_runtime=None,
        start_site_followup=follow_up,
    )

    async def current(conn, org_id):
        return "21:00"

    async def record(actor, question, state):
        return None

    monkeypatch.setattr(q, "_current_deadline", current)
    monkeypatch.setattr(q, "_record", record)
    return SimpleNamespace(q=q, statements=statements, started=started)


async def _ask(setup, actor, question):
    await setup.q._redis.set_json(
        setup.q._hint_key(actor.user_id), {"question": question}, ttl_seconds=60
    )


# -- SET-08 ------------------------------------------------------------------------


async def test_set08_add_a_site_asks_which_project_when_there_are_several(setup) -> None:
    actor = _actor([P1, P2])
    await _ask(setup, actor, "more_sites")
    spec = await setup.q.handle_tap(_tap(sq.ADD_SITE), actor)
    assert setup.started == []  # never the first project by default
    assert [b.title for b in spec.buttons] == ["Green Villa", "Lake View"]

    done = await setup.q.handle_tap(_tap(f"{sq.SITE_IN_PREFIX}{P2.id}"), actor)
    assert done.text == "What's the site called?"
    assert setup.started[0]["project_id"] == P2.id


async def test_set08_one_project_needs_no_question(setup) -> None:
    actor = _actor([P1])
    await _ask(setup, actor, "more_sites")
    await setup.q.handle_tap(_tap(sq.ADD_SITE), actor)
    assert setup.started[0]["project_id"] == P1.id


async def test_set08_a_stale_project_tap_is_expired(setup) -> None:
    actor = _actor([P1, P2])
    spec = await setup.q.handle_tap(_tap(f"{sq.SITE_IN_PREFIX}{P2.id}"), actor)
    assert spec.text == sq.EXPIRED


# -- SET-11 ------------------------------------------------------------------------


async def test_set11_report_time_asks_which_projects_when_there_are_several(setup) -> None:
    actor = _actor([P1, P2])
    await _ask(setup, actor, "report_time")
    spec = await setup.q.handle_tap(_tap(f"{sq.TIME_PREFIX}20:00"), actor)
    assert setup.statements == []  # nothing changed yet
    assert [b.title for b in spec.buttons] == ["All projects", "Green Villa", "Lake View"]

    done = await setup.q.handle_tap(_tap(f"{sq.TIME_FOR_PREFIX}{P1.id}"), actor)
    assert "Green Villa" in done.text and "8 pm" in done.text
    (stmt,) = setup.statements
    assert str(P1.id) in str(stmt.compile().params.values()) or "projects.id" in str(stmt)


async def test_set11_all_projects_updates_the_whole_company(setup) -> None:
    actor = _actor([P1, P2])
    await _ask(setup, actor, "report_time")
    await setup.q.handle_tap(_tap(f"{sq.TIME_PREFIX}19:00"), actor)
    done = await setup.q.handle_tap(_tap(f"{sq.TIME_FOR_PREFIX}{sq.ALL_PROJECTS}"), actor)
    assert done.text == sq.REPORT_TIME_SET.format(time="7 pm")
    (stmt,) = setup.statements
    assert "projects.id" not in str(stmt).split("WHERE")[1]


async def test_set11_keeping_the_time_or_one_project_asks_nothing(setup) -> None:
    actor = _actor([P1, P2])
    await _ask(setup, actor, "report_time")
    kept = await setup.q.handle_tap(_tap(f"{sq.TIME_PREFIX}21:00"), actor)
    assert kept.text == sq.REPORT_TIME_KEPT.format(time="9 pm")

    solo = _actor([P1])
    await _ask(setup, solo, "report_time")
    done = await setup.q.handle_tap(_tap(f"{sq.TIME_PREFIX}20:00"), solo)
    assert done.text == sq.REPORT_TIME_SET.format(time="8 pm")


# -- SET-09 / SET-10 ---------------------------------------------------------------


def test_set09_the_join_code_sentence_reads_properly() -> None:
    assert "to you to approve" not in jj.CODE_INTRO
    assert "asked for your approval" in jj.CODE_INTRO


def test_set10_not_registered_shows_the_number_and_the_real_ways_in() -> None:
    text = unregistered_message("919876543210")
    assert "+919876543210" in text
    assert "join code" in text and SIGNUP_URL in text
    assert "Mesiri app" not in text


# -- SET-07 ------------------------------------------------------------------------


async def test_set07_the_join_code_tool_sends_the_code_and_says_little() -> None:
    sent = []

    async def share():
        sent.append("code")
        return ""

    gateway = JourneyGateway(
        message=None, save_now=None, undo=None, followups=None, held_prompt=None, share_code=share
    )
    step = await gateway.share_join_code()
    assert sent == ["code"] and step.status == "info"
    assert "do not repeat the code" in step.text


async def test_set07_a_site_engineer_is_refused() -> None:
    async def share():
        return jj.NOT_ALLOWED_TO_SHARE

    gateway = JourneyGateway(
        message=None, save_now=None, undo=None, followups=None, held_prompt=None, share_code=share
    )
    assert (await gateway.share_join_code()).text == jj.NOT_ALLOWED_TO_SHARE


def test_set07_the_agent_has_a_join_code_tool() -> None:
    from runtime.agent.tools import GET_JOIN_CODE, tool_specs

    assert GET_JOIN_CODE in {s.name for s in tool_specs()}
