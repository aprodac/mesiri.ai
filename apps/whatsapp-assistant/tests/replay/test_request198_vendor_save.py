"""Request 198: "Yes, add new vendor" on an expense card saves the expense.

Live 1 Nov (Ilan, ADMIN): a bill photo -> Expense 140 card -> Save -> "Which account?" ->
"Office Cash" -> "I don't have 'Irani Cafe NIBM' as a vendor yet. Add it?" ->
"Yes, add new vendor" -> "Nothing was saved. Couldn't save Expense 140 ... Couldn't read".
Driven with the real expense workflow; only the lookups and the backend are stand-ins.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from tests.replay.test_agent_replay import _make_world, _MemoryRedis
from tests.replay.test_request159_a_save_question import _tap

from context import seed
from mesiri_ai.fakes import FakeToolCallingProvider
from runtime.agent import draft as dr
from runtime.agent.cards import CardStore
from runtime.agent.draft_store import MemoryDraftStore
from workflows.entities import Missing

EXPENSE = ("save_expense", {"amount": 140, "description": "tea", "vendor": "Irani Cafe NIBM", "category": "Food & Beverages"})
ACCOUNTS = ("Office Cash", "Site Cash")


class _Accounts:
    async def list_accounts(self, *, organization_id, created_by):  # noqa: ANN001
        return [SimpleNamespace(id=f"00000000-0000-4000-8000-00000000000{n}", name=a) for n, a in enumerate(ACCOUNTS, 1)]


class _Vendors:
    async def resolve(self, *, organization_id, vendor_name):  # noqa: ANN001
        return Missing(name_hint=vendor_name)


@pytest.fixture
async def world():
    world = await _make_world(site_keys=(seed.SITE_A1,))
    world.draft_v2 = True
    world.drafts = MemoryDraftStore()
    world.cards = CardStore(_MemoryRedis())
    world.site = {"money_account_query": _Accounts(), "vendor_query": _Vendors()}
    make = world.gateway

    def gateway(text, *a, **kw):
        # As runtime/message_journey.py wires it: the open question is closed or answered through the handler.
        gw = make(text, *a, **kw)
        uid = world.actor.user_id
        gw.abandon_question = lambda: world.handler._close_question(uid)
        gw.answer_question = lambda answer: world.handler.answer_open_question(uid, answer)
        gw.confirm_now = lambda: world.handler.confirm_now(uid, actor=world.actor)
        return gw

    world.gateway = gateway
    return world


async def test_yes_add_new_vendor_saves_the_expense(world):
    result = await world.say(FakeToolCallingProvider([[EXPENSE], "Check it."]), "paid 140 for tea")
    card = await _tap(world, result.reply, "✅ Save")
    print("1:", card.text)
    card = await _tap(world, card, "Office Cash")
    print("2:", card.text)
    saved = await _tap(world, card, "Yes, add new vendor")
    print("3:", saved.text)
    assert saved.text.startswith("✅ *Saved*"), saved.text
    assert len(world.dispatcher.dispatched) == 1


async def test_a_system_failure_keeps_the_line_and_the_next_save_tries_again(world):
    from mesiri_contracts.application.results.execution_result import (
        ExecutionResult,
        ExecutionStatus,
    )

    real = world.dispatcher.dispatch
    calls = {"n": 0}

    async def flaky(confirmed):  # noqa: ANN001
        calls["n"] += 1
        if calls["n"] == 1:
            return ExecutionResult(status=ExecutionStatus.FAILED, idempotency_key="idem_x")
        return await real(confirmed)

    world.dispatcher.dispatch = flaky
    result = await world.say(FakeToolCallingProvider([[EXPENSE], "Check it."]), "paid 140 for tea")
    card = await _tap(world, result.reply, "✅ Save")
    card = await _tap(world, card, "Office Cash")
    failed = await _tap(world, card, "Yes, add new vendor")
    assert failed.text.startswith("Nothing was saved.") and "Expense ₹140" in failed.text
    assert dr.CANT_READ not in failed.text and "send it again" not in failed.text.lower()
    assert "Tap Save to try again" in failed.text
    assert any(r.title.startswith("✅ Save") for r in [*(failed.buttons or ()), *(failed.list_rows or ())])
    saved = await _tap(world, failed, "✅ Save")
    assert saved.text.startswith("✅ *Saved*"), saved.text
