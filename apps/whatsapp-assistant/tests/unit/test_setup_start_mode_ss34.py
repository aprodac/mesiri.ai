"""SS-34 (guided onboarding): "How would you like to start?" on WhatsApp, as the first daily setup question for a
new owner who has not answered it on the dashboard; the answer lands on the owner's own users row."""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest

from backend.ports import ActorIdentity
from mesiri.domains.identity.preferences_router import START_MODES
from mesiri.domains.organizations import setup_questions as rules
from mesiri.infrastructure.redis.client import FakeRedis
from runtime import setup_questions as sq

ORG = uuid.uuid4()
NOW = dt.datetime(2026, 11, 15, 9, tzinfo=dt.UTC)


def _actor() -> ActorIdentity:
    return ActorIdentity(
        user_id=str(uuid.uuid4()), full_name="Suresh", role="ADMIN", organization_id=ORG,
        org_name="Suresh Builders", org_active=True, projects=[],
    )


class _Conn:
    def __init__(self, log, row):
        self.log, self.row = log, row

    async def execute(self, stmt):
        self.log.append(stmt)
        return SimpleNamespace(first=lambda: self.row)


class _Tx:
    def __init__(self, log, row):
        self.log, self.row = log, row

    async def __aenter__(self):
        return _Conn(self.log, self.row)

    async def __aexit__(self, *exc):
        return None


def _questions(monkeypatch, row=None):
    log: list = []
    recorded: list = []
    q = sq.SetupQuestions(
        db=SimpleNamespace(transaction=lambda: _Tx(log, row)), redis=FakeRedis(), storage=None, notifier=None,
        workflow_runtime=None, start_site_followup=None, now=lambda: NOW,
    )

    async def record(actor, question, state):
        recorded.append((question, state))

    async def english(actor):  # noqa: ANN001, ANN202 -- SS-63: language has its own tests below
        return None

    monkeypatch.setattr(q, "_record", record)
    monkeypatch.setattr(q, "_use_language", english)
    return SimpleNamespace(q=q, log=log, recorded=recorded)


def _tap(reply_id):
    return SimpleNamespace(metadata={"interactive_reply_id": reply_id})


def test_the_four_answers_match_the_dashboards() -> None:
    assert [r.id.removeprefix(sq.MODE_PREFIX) for r in sq.START_MODE_ROWS] == list(START_MODES)
    assert set(sq.START_MODE_REPLY) == set(START_MODES)
    assert all(len(r.title) <= 24 and len(r.description) <= 72 for r in sq.START_MODE_ROWS)  # WhatsApp's limits


async def test_the_question_is_a_list_of_the_four_answers(monkeypatch) -> None:
    s = _questions(monkeypatch)
    spec = await s.q._question_spec(None, ORG, rules.START_MODE)
    assert spec.list_rows == sq.START_MODE_ROWS and "How would you like to start?" in spec.text


@pytest.mark.parametrize(("stored", "age_days", "ask"), [
    (None, 0, True),          # a new owner, not answered: asked
    ("free", 0, False),       # answered on the dashboard: not asked again
    (None, 30, False),        # was using Mesiri before this existed: never asked (D-GO5)
])
async def test_asked_only_of_a_new_owner_who_has_not_answered(monkeypatch, stored, age_days, ask) -> None:
    row = SimpleNamespace(start_mode=stored, created_at=NOW - dt.timedelta(days=age_days))
    s = _questions(monkeypatch, row)
    assert await s.q._should_ask_start_mode(_Conn(s.log, row), _actor()) is ask


async def test_no_user_row_is_never_asked(monkeypatch) -> None:
    s = _questions(monkeypatch)
    assert await s.q._should_ask_start_mode(_Conn(s.log, None), _actor()) is False


@pytest.mark.parametrize("mode", START_MODES)
async def test_a_tap_saves_the_owners_own_answer_and_gives_its_tip(monkeypatch, mode) -> None:
    s = _questions(monkeypatch)
    actor = _actor()
    await s.q._redis.set_json(s.q._hint_key(actor.user_id), {"question": rules.START_MODE}, ttl_seconds=60)
    spec = await s.q.handle_tap(_tap(f"{sq.MODE_PREFIX}{mode}"), actor)
    assert spec.text == sq.START_MODE_REPLY[mode]
    (stmt,) = s.log
    params = stmt.compile().params
    assert params["start_mode"] == mode
    assert {v for k, v in params.items() if k.startswith(("id", "organization_id"))} == {uuid.UUID(actor.user_id), ORG}
    assert s.recorded == [(rules.START_MODE, rules.ANSWERED)]
    assert not await s.q._redis.get_json(s.q._hint_key(actor.user_id))  # the question is closed


async def test_an_unknown_answer_changes_nothing(monkeypatch) -> None:
    s = _questions(monkeypatch)
    spec = await s.q.handle_tap(_tap(f"{sq.MODE_PREFIX}expert"), _actor())
    assert spec.text == sq.EXPIRED and s.log == [] and s.recorded == []


async def test_the_other_questions_taps_are_unchanged(monkeypatch) -> None:
    # Guard: a branding skip still needs its own question open.
    s = _questions(monkeypatch)
    spec = await s.q.handle_tap(_tap(sq.SKIP_BRANDING), _actor())
    assert spec.text == sq.EXPIRED


# -- SS-63: the setup questions and tips in the owner's own language ------------------------------------------------

from runtime.agent.wording import LANGUAGES, LINES  # noqa: E402

_SETUP_KEYS = [k for k in LINES if k.startswith(("setup.", "start.", "tip."))]


def test_every_setup_line_has_every_language() -> None:
    assert len(_SETUP_KEYS) > 40
    for key in _SETUP_KEYS:
        assert set(LINES[key]) == set(LANGUAGES), key
        assert all(LINES[key][lang].strip() for lang in LANGUAGES), key


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_answers_fit_whatsapp_in_every_language(language) -> None:  # noqa: ANN001
    rows = sq.start_mode_rows(language)
    assert [r.id.removeprefix(sq.MODE_PREFIX) for r in rows] == list(START_MODES)
    assert all(len(r.title) <= 24 and len(r.description) <= 72 for r in rows), [(r.title, len(r.title)) for r in rows]
    # Reply buttons (Skip, Add a site, No, Keep 9 pm, All projects) and the list button: WhatsApp's 20 characters.
    for key in ("setup.skip", "setup.add_site", "setup.no", "setup.all_projects", "setup.choose"):
        assert len(LINES[key][language]) <= 20, (key, LINES[key][language])
    assert len(LINES["setup.keep_time"][language].format(time="9 pm")) <= 20


@pytest.mark.parametrize(("stored", "expected"), [
    ("malayalam", "malayalam"), ("hindi", "hindi"), ("english", "english"),
    (None, "manglish"),   # none chosen: Manglish (WA-207)
    ("auto", "manglish"),  # "follow each message": this is no reply to one
])
async def test_the_language_is_the_owners_reply_language(monkeypatch, stored, expected) -> None:  # noqa: ANN001
    row = SimpleNamespace(reply_language=stored)
    q = sq.SetupQuestions(db=SimpleNamespace(transaction=lambda: _Tx([], row)), redis=FakeRedis(), storage=None,
                          notifier=None, workflow_runtime=None, start_site_followup=None, now=lambda: NOW)
    await q._use_language(_actor())
    assert sq._LANG.get() == expected
    spec = await q._question_spec(None, ORG, rules.START_MODE)
    assert spec.text == LINES["start.ask"][expected]
    assert [r.title for r in spec.list_rows] == [LINES[f"start.{m}.title"][expected] for m in START_MODES]


async def test_no_user_row_is_english() -> None:
    q = sq.SetupQuestions(db=SimpleNamespace(transaction=lambda: _Tx([], None)), redis=FakeRedis(), storage=None,
                          notifier=None, workflow_runtime=None, start_site_followup=None, now=lambda: NOW)
    await q._use_language(_actor())
    assert sq._LANG.get() == "english"


def test_the_bring_my_data_reply_no_longer_promises_a_whatsapp_import() -> None:
    # Importing an Excel sent on WhatsApp is not built (BOQ-05, blocked): the reply points at Bring your data only.
    for language in LANGUAGES:
        assert "Bring your data" in LINES["start.bring_data.reply"][language]
    assert "send me the file" not in LINES["start.bring_data.reply"]["english"].lower()
