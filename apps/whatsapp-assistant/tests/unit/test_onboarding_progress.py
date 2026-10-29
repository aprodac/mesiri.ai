"""SS-17: when the setup-progress card goes out (no database, no browser)."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from channel.onboarding_cards import ProgressFacts
from mesiri.infrastructure.redis.client import FakeRedis
from runtime import onboarding_progress as op
from runtime.setup_questions import CARD_SENT_KEY

NOW = dt.datetime(2026, 10, 22, 6, tzinfo=dt.UTC)
CREATED = dt.datetime(2026, 10, 20, 6, tzinfo=dt.UTC)


def _actor(role="ADMIN"):
    return SimpleNamespace(
        user_id="u1",
        organization_id="11111111-1111-1111-1111-111111111111",
        org_active=True,
        role=role,
        timezone="Asia/Kolkata",
        org_name="Suresh Builders",
        sites=[SimpleNamespace(name="Green Villa, Kakkanad")],
        projects=[],
    )


class _SetupQuestions:
    def __init__(self):
        self.open = False
        self.asked: list[str] = []

    async def is_open(self, user_id):
        return self.open

    async def ask(self, actor, question, send):
        self.asked.append(question)


class _Lang:
    def __init__(self, language=None):
        self.language = language

    async def get_profile(self, *, user_id):
        return self.language, "native"


@pytest.fixture
def rig(monkeypatch):
    redis = FakeRedis()
    sq = _SetupQuestions()
    state = {"facts": ProgressFacts(), "created": CREATED, "source": "whatsapp", "now": NOW}
    sent: list = []
    cards: list = []

    async def fake_render(renderer, card):
        cards.append(card)
        return b"png"

    monkeypatch.setattr(op, "render_card_png", fake_render)
    service = op.OnboardingProgress(
        db=None,
        redis=redis,
        renderer=object(),
        setup_questions=sq,
        language_store=_Lang(),
        now=lambda: state["now"],
    )

    async def fake_read(org_id):
        return state["facts"], state["created"], state["source"]

    service._read = fake_read  # type: ignore[method-assign]

    async def send_image(wa_id, png, caption=None, shows=None):
        sent.append(png)
        return True

    async def send_spec(spec):
        sent.append(spec)

    async def after():
        return await service.after_reply(
            _actor(), wa_id="919", send_image=send_image, send_spec=send_spec
        )

    return SimpleNamespace(
        service=service, redis=redis, sq=sq, state=state, sent=sent, cards=cards,
        after=after, send_image=send_image, send_spec=send_spec,
    )  # fmt: skip


def test_status_words():
    for text in ("setup", "Setup status", " SET UP ", "setup status!"):
        assert op.is_status_request(text)
    for text in ("setup the site", "status", "", None, "6 mason setup"):
        assert not op.is_status_request(text)


def test_card_due_rule():
    none = ProgressFacts()
    first = ProgressFacts(first_update=True)
    assert not op.card_due(None, none, today="d1")
    assert op.card_due(None, first, today="d1")  # (a) first saved update
    assert not op.card_due({"on": "d1", "done": ["company_site", "first_update"]}, first, today="d2")
    more = ProgressFacts(first_update=True, logo=True)
    assert op.card_due({"on": "d1", "done": ["company_site", "first_update"]}, more, today="d2")  # (b)
    assert not op.card_due({"on": "d2", "done": ["company_site", "first_update"]}, more, today="d2")


async def test_no_card_before_the_first_update(rig):
    assert await rig.after() is False and rig.sent == []


async def test_first_saved_update_sends_the_card_once(rig):
    rig.state["facts"] = ProgressFacts(first_update=True, materials=True)
    assert await rig.after() is True
    assert rig.sent[0] == b"png"
    assert rig.cards[0].done == 3 and rig.cards[0].next_step == "logo"
    # Same day, another step done: still only one card a day.
    rig.state["facts"] = ProgressFacts(first_update=True, materials=True, logo=True)
    assert await rig.after() is False and len(rig.cards) == 1


async def test_a_new_step_sends_a_card_the_next_day(rig):
    rig.state["facts"] = ProgressFacts(first_update=True, materials=True)
    await rig.after()
    rig.state["facts"] = ProgressFacts(first_update=True, materials=True, logo=True)
    rig.state["now"] = NOW + dt.timedelta(days=1)
    assert await rig.after() is True
    assert rig.cards[-1].done == 4
    # Nothing new since: quiet.
    rig.state["now"] = NOW + dt.timedelta(days=2)
    assert await rig.after() is False


async def test_not_while_a_confirmation_or_question_is_open(rig):
    rig.state["facts"] = ProgressFacts(first_update=True)
    rig.sq.open = True
    assert await rig.after() is False and rig.sent == []
    rig.sq.open = False
    assert await rig.after() is True


async def test_only_the_owner_of_a_whatsapp_company_in_its_first_30_days(rig):
    rig.state["facts"] = ProgressFacts(first_update=True)
    assert await rig.service.after_reply(
        _actor("SITE_ENGINEER"), wa_id="919", send_image=rig.send_image, send_spec=rig.send_spec
    ) is False
    rig.state["source"] = "admin"
    assert await rig.after() is False
    rig.state["source"] = "whatsapp"
    rig.state["created"] = NOW - dt.timedelta(days=31)
    assert await rig.after() is False


async def test_the_card_day_silences_the_setup_question(rig):
    rig.state["facts"] = ProgressFacts(first_update=True)
    await rig.after()
    assert await rig.redis.get_json(CARD_SENT_KEY.format(user_id="u1")) == "2026-10-22"


async def test_report_time_next_step_is_followed_by_its_buttons(rig):
    rig.state["facts"] = ProgressFacts(first_update=True, materials=True, logo=True, site_engineer=True)
    await rig.after()
    assert rig.cards[0].next_step == "report_time"
    assert rig.sq.asked == ["report_time"]


async def test_other_next_steps_ask_nothing_separately(rig):
    rig.state["facts"] = ProgressFacts(first_update=True)
    await rig.after()
    assert rig.sq.asked == []


async def test_malayalam_owner_gets_the_malayalam_card(rig):
    rig.service._language_store = _Lang("Malayalam")
    rig.state["facts"] = ProgressFacts(first_update=True)
    await rig.after()
    assert rig.cards[0].lang == "ml"


async def test_typed_setup_always_answers_and_does_not_use_up_the_day(rig):
    texts: list[str] = []

    async def send_text(wa_id, body):
        texts.append(body)

    await rig.service.send_status(
        _actor(), wa_id="919", send_image=rig.send_image, send_spec=rig.send_spec, send_text=send_text
    )
    assert rig.cards[0].done == 1 and texts == []
    # Still allowed to send its unprompted card later the same day.
    rig.state["facts"] = ProgressFacts(first_update=True)
    assert await rig.after() is True


async def test_typed_setup_falls_back_to_text_when_the_card_cannot_be_made(rig, monkeypatch):
    async def no_card(renderer, card):
        return None

    monkeypatch.setattr(op, "render_card_png", no_card)
    texts: list[str] = []

    async def send_text(wa_id, body):
        texts.append(body)

    await rig.service.send_status(
        _actor(), wa_id="919", send_image=rig.send_image, send_spec=rig.send_spec, send_text=send_text
    )
    assert texts and texts[0].startswith("Setup: 1 / 6")
