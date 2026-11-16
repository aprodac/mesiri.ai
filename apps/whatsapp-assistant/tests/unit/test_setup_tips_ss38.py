"""SS-38: a week of WhatsApp tips for a new owner, sent by the daily setup questions' own path (``after_reply``): only
when no setup question is due that day, at most one a day, in the owner's language (SS-63), and not for an owner who
chose "I'll find my way" or said "no more tips" (start mode ``free``)."""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest

from backend.ports import ActorIdentity
from mesiri.domains.organizations import setup_questions as rules
from mesiri.infrastructure.redis.client import FakeRedis
from runtime import setup_questions as sq
from runtime.agent.wording import LINES

ORG = uuid.uuid4()
NOW = dt.datetime(2026, 11, 16, 6, tzinfo=dt.UTC)  # 11:30 in India
CREATED = dt.datetime(2026, 11, 14, 6, tzinfo=dt.UTC)  # signed up two days ago


class _Conn:
    async def execute(self, stmt):  # noqa: ANN001, ANN201
        return SimpleNamespace(first=lambda: SimpleNamespace(timezone="Asia/Kolkata", created_at=CREATED))


class _Tx:
    async def __aenter__(self):  # noqa: ANN204
        return _Conn()

    async def __aexit__(self, *exc):  # noqa: ANN002, ANN204
        return None


class _Repo:
    store: dict = {}

    def __init__(self, conn) -> None:  # noqa: ANN001
        pass

    async def get(self, org, key):  # noqa: ANN001, ANN201
        return _Repo.store.get(key)

    async def set(self, org, key, value, updated_by=None):  # noqa: ANN001, ANN201
        _Repo.store[key] = value


def _owner() -> ActorIdentity:
    return ActorIdentity(user_id=str(uuid.uuid4()), full_name="Suresh", role="ADMIN", organization_id=ORG,
                         org_name="Suresh Builders", org_active=True, projects=[])


@pytest.fixture
def tips(monkeypatch):  # noqa: ANN001, ANN201
    _Repo.store = {}
    monkeypatch.setattr(sq, "PostgresOrganizationSettingsRepository", _Repo)
    state = SimpleNamespace(mode="guided", language="english", sent=[])
    q = sq.SetupQuestions(db=SimpleNamespace(transaction=_Tx), redis=FakeRedis(), storage=None, notifier=None,
                          workflow_runtime=None, start_site_followup=None, now=lambda: NOW)

    async def busy(*a):  # noqa: ANN002, ANN202
        return False

    async def language(actor):  # noqa: ANN001, ANN202
        sq._LANG.set(state.language)

    async def no(conn, actor):  # noqa: ANN001, ANN202
        return False

    async def mode(conn, actor):  # noqa: ANN001, ANN202
        return state.mode

    monkeypatch.setattr(q, "_busy", busy)
    monkeypatch.setattr(q, "_use_language", language)
    monkeypatch.setattr(q, "_should_ask_start_mode", no)
    monkeypatch.setattr(q, "_start_mode", mode)

    async def send(spec):  # noqa: ANN001, ANN202
        state.sent.append(spec.text)

    state.q, state.send = q, send
    return state


def _all_questions_answered() -> None:
    _Repo.store["setup_progress"] = {q: {"state": rules.ANSWERED, "on": "2026-11-15"} for q in rules.QUESTIONS}


async def test_a_tip_goes_out_when_no_question_is_due_and_says_how_to_stop(tips) -> None:  # noqa: ANN001
    _all_questions_answered()
    await tips.q.after_reply(_owner(), tips.send)
    assert tips.sent == [f"{LINES['tip.voice']['english']}\n\n{LINES['tip.stop']['english']}"]
    assert _Repo.store["setup_progress"]["tips"] == {"sent": ["voice"], "last_on": "2026-11-16"}


async def test_never_two_in_a_day(tips) -> None:  # noqa: ANN001
    _all_questions_answered()
    owner = _owner()
    await tips.q.after_reply(owner, tips.send)
    await tips.q._redis.set_json(tips.q._idle_key(owner.user_id), None, ttl_seconds=1)  # even past the idle wait
    await tips.q.after_reply(owner, tips.send)
    assert len(tips.sent) == 1


async def test_a_setup_question_day_gets_the_question_not_a_tip(tips, monkeypatch) -> None:  # noqa: ANN001
    async def spec(conn, org, question):  # noqa: ANN001, ANN202
        return sq.ReplySpec(text=f"question:{question}")

    monkeypatch.setattr(tips.q, "_question_spec", spec)
    await tips.q.after_reply(_owner(), tips.send)  # nothing answered yet: the letterhead question is due
    assert tips.sent == ["question:branding"]
    assert "tips" not in _Repo.store["setup_progress"]


@pytest.mark.parametrize("mode", ["free", "switching"])
async def test_no_tips_for_find_my_own_way_or_no_more_tips(tips, mode) -> None:  # noqa: ANN001
    _all_questions_answered()
    tips.mode = mode
    await tips.q.after_reply(_owner(), tips.send)
    assert tips.sent == []


async def test_in_the_owners_language(tips) -> None:  # noqa: ANN001
    _all_questions_answered()
    tips.language = "manglish"
    await tips.q.after_reply(_owner(), tips.send)
    assert tips.sent[0].startswith(LINES["tip.voice"]["manglish"])
