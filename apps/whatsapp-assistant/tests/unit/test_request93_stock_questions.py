"""Request 93: every stock question runs the stock lookup (so the Stock card is
drawn every time), not an answer from the stock line in the prompt."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from channel.replies import ReplySpec
from mesiri_ai.models import ToolCallRecord, ToolRunResult
from runtime.agent.prompt import SYSTEM_PROMPT, AgentContext, render_context
from runtime.agent.runner import AgentResult
from runtime.agent.stock_question import is_stock_question
from runtime.agent.turn import AgentTurnDeps, run_agent_turn

MATCH = [
    "stock",
    "Stock?",
    "stock ethra",
    "site il ella materials um ethra balance und?",
    "How much stock do we have on site?",
    "cement ethra baaki?",
    "cement stock ethra?",
    "what is the balance of cement",
    "how much cement is left",
    "how much cement left?",
    "remaining materials?",
    "materials on site",
    "show inventory",
    "inventory",
    "current stock please",
    "steel baaki ethra und",
    "sand ethra und",
    "ethra cement undu",
    "material balance",
    "what's the stock",
    "stock check",
    "STOCK",
    "stock entha",
    "enthokke materials und, balance ethra?",
    "site stock status",
]
NOT = [
    "10 bag cement vannu",
    "5 bags cement used for columns",
    "cement venam",
    "stock vannu 50 bags",
    "10 bag cement balance und, kooduthal venam",
    "cement theernu",
    "ran out of steel",
    "account balance",
    "petty cash balance ethra",
    "how many workers today?",
    "used 20 bags yesterday",
    "cement received",
    "need more sand",
    "",
    "hello",
    "👍",
]


@pytest.mark.parametrize("text", MATCH)
def test_stock_questions_match(text):
    assert is_stock_question(text)


@pytest.mark.parametrize("text", NOT)
def test_reports_and_other_messages_do_not_match(text):
    assert not is_stock_question(text)


def test_prompt_sends_stock_questions_to_the_lookup():
    assert "must call query_materials" in SYSTEM_PROMPT
    ctx = AgentContext(
        user_name="A", role="S", company="C", now=__import__("datetime").datetime(2026, 10, 23, 9), stock_line="Stock now at X (from the records): Cement 5 bag."
    )
    assert "To answer a stock question, call query_materials" in render_context(ctx)


class _Box:
    def __init__(self, answer="Stock: Cement 5 bag"):
        self.saved, self.attempted_writes, self.parked = [], 0, None
        self.answers, self.notes = [], []
        self.calls = 0
        self._answer = answer

    async def look_up_stock(self):
        self.calls += 1
        self.answers.append(self._answer)
        return self._answer


def _deps(result):
    runner = SimpleNamespace(run=AsyncMock(return_value=result))
    sent = []

    async def send(spec, wa_id):
        sent.append(spec)

    deps = AgentTurnDeps(
        runner=runner,
        make_gateway=lambda m, lang: SimpleNamespace(handled=[], finish=AsyncMock()),
        send_spec=send,
        transcribe=None,
        message_logger=AsyncMock(),
    )
    return deps, sent


ACTOR = SimpleNamespace(
    organization_id="o", user_id="u", full_name="A", role="SUPERVISOR", org_name="Acme", projects=[], sites=[]
)


async def _turn(text, calls, box):
    from tests.unit.test_agent_routing import _message

    run = ToolRunResult(text="There are 5 bags of cement.", calls=calls)
    deps, sent = _deps(AgentResult("ok", ReplySpec(text=run.text), box, run=run))
    await run_agent_turn(_message(text), ACTOR, deps)
    return sent


async def test_text_only_answer_to_a_stock_question_is_replaced_by_the_lookup():
    box = _Box()
    sent = await _turn("How much stock do we have on site?", [], box)
    assert box.calls == 1
    assert [s.text for s in sent] == ["Stock: Cement 5 bag"]


async def test_a_model_that_called_query_materials_is_left_alone():
    box = _Box()
    call = ToolCallRecord(name="query_materials", arguments={})
    sent = await _turn("stock", [call], box)
    assert box.calls == 0 and sent[0].text == "There are 5 bags of cement."


async def test_a_save_turn_is_unchanged():
    box = _Box()
    sent = await _turn("10 bag cement vannu", [], box)
    assert box.calls == 0 and sent[0].text == "There are 5 bags of cement."


async def test_a_failed_lookup_keeps_the_models_answer():
    box = _Box(answer="")
    sent = await _turn("stock", [], box)
    assert box.calls == 1 and sent[0].text == "There are 5 bags of cement."
