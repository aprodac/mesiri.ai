"""WA-176: no setup question (letterhead, report time, more sites) while entries wait for Save.

Live 4 Nov: "10 bag cement vannu" got its Save card, then the letterhead question
right under it, burying the Save. The check now sees every assistant's open entries:
v3's ready list, classic's open card and classic's open draft.
"""

from __future__ import annotations

import time
import uuid

import pytest

from agent_api.whatsapp import PENDING_MAX_AGE_S, has_ready_entries, state_key
from mesiri.infrastructure.redis.client import FakeRedis
from runtime import setup_questions as sq
from runtime.agent import draft_store
from runtime.agent.cards import OPEN, SAVED, Card, CardItem, CardStore

ORG = uuid.uuid4()
USER = uuid.uuid4()


class _Runtime:
    def __init__(self, *, confirmation=None, waiting=None):
        self._confirmation = confirmation
        self._waiting = waiting

    async def get_awaiting_confirmation(self, user_id):
        return self._confirmation

    async def get_awaiting_input(self, user_id):
        return self._waiting


@pytest.fixture
def rig(monkeypatch):
    redis = FakeRedis()
    drafts = {"open": None}

    class _Drafts:
        def __init__(self, db):
            pass

        async def open_for(self, organization_id, user_id):
            return drafts["open"]

    monkeypatch.setattr(draft_store, "PostgresDraftStore", _Drafts)

    def make(runtime=None):
        return sq.SetupQuestions(
            db=None,
            redis=redis,
            storage=None,
            notifier=None,
            workflow_runtime=runtime or _Runtime(),
            start_site_followup=lambda **_: None,
        )

    return redis, drafts, make


def _card(state: str) -> Card:
    item = CardItem(
        tool="save_material_receipt", args={}, fact_type="material_receipt",
        fact_id=str(uuid.uuid4()), summary="Cement in: 10 bags",
    )  # fmt: skip
    return Card(id="c1", state=state, items=[item], created=time.time())


def test_a_ready_list_counts_until_it_is_dropped():
    assert has_ready_entries({"pending": [{"summary": "Cement in: 10 bags"}], "pending_at": time.time()})
    assert has_ready_entries({"pending": [{"summary": "x"}]})  # no time kept: still waiting
    assert not has_ready_entries({"pending": [], "pending_at": time.time()})
    assert not has_ready_entries({"pending": [{"summary": "x"}], "pending_at": time.time() - PENDING_MAX_AGE_S - 1})
    assert not has_ready_entries(None)


async def test_nothing_waiting_is_not_busy(rig):
    _, _, make = rig
    assert await make()._busy(str(USER), ORG) is False


async def test_a_v3_ready_list_holds_the_question(rig):
    redis, _, make = rig
    await redis.set_json(state_key(ORG, USER), {"pending": [{"summary": "Cement in: 10 bags"}], "pending_at": time.time()})
    assert await make()._busy(str(USER), ORG) is True
    assert await make().is_open(str(USER), ORG) is True


async def test_a_classic_open_card_holds_the_question_but_a_saved_one_does_not(rig):
    redis, _, make = rig
    actor = type("A", (), {"organization_id": ORG, "user_id": USER})()
    await CardStore(redis).put(actor, _card(OPEN))
    assert await make()._busy(str(USER), ORG) is True
    await CardStore(redis).put(actor, _card(SAVED))
    assert await make()._busy(str(USER), ORG) is False


async def test_a_classic_open_draft_holds_the_question(rig):
    _, drafts, make = rig
    drafts["open"] = object()
    assert await make()._busy(str(USER), ORG) is True


async def test_without_a_company_only_the_old_checks_run(rig):
    redis, drafts, make = rig
    drafts["open"] = object()
    assert await make()._busy(str(USER), None) is False
    assert await make(_Runtime(confirmation={"x": 1}))._busy(str(USER), None) is True


async def test_an_unreadable_store_means_do_not_interrupt(rig, monkeypatch):
    _, _, make = rig

    async def broken(self, organization_id, user_id):
        raise RuntimeError("db down")

    monkeypatch.setattr(draft_store.PostgresDraftStore, "open_for", broken)
    assert await make()._busy(str(USER), ORG) is True
