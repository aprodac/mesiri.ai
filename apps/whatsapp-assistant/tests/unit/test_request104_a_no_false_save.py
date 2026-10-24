"""Request 104, A: never claim a save that did not happen.

Live 24 Oct: "JCB worked 6 hours today" and "2 mixers and 1 vibrator on site
today" answered "✅ Saved ... Reply UNDO", then "UNDO" said "Nothing to undo".
"""

from __future__ import annotations

import datetime as dt

import pytest

from mesiri_ai.fakes import FakeToolCallingProvider
from runtime.agent import runner as r
from runtime.agent.equipment import EQUIPMENT_LINE, is_equipment_only
from runtime.agent.gateway import StepResult
from runtime.agent.prompt import AgentContext
from runtime.agent.tools import ScopeLookup

CTX = AgentContext(
    user_name="Adarsh", role="SUPERVISOR", company="Acme", now=dt.datetime(2026, 10, 24, 5, 30),
    projects=(("Hospital Project", None),), sites=(("Tower A", "Hospital Project"),),
)


class Gateway:
    def __init__(self) -> None:
        self.runs: list = []

    async def run(self, candidate, *, text):  # noqa: ANN001, ANN202
        self.runs.append(candidate)
        return StepResult("saved", text="ok", summary="Work: JCB 6 hours")


@pytest.mark.parametrize(
    "text", ["JCB worked 6 hours today", "2 mixers and 1 vibrator on site today", "excavator 4 hrs"]
)
def test_equipment_only_messages(text):
    assert is_equipment_only(text)


@pytest.mark.parametrize(
    "text",
    [
        "concreted 20 cum slab with the mixer",
        "crane breakdown, work stopped",
        "5 masons and 8 helpers today",
        "JCB 6 hours and 5 mason came",
    ],
)
def test_other_messages_are_not(text):
    assert not is_equipment_only(text)


@pytest.mark.parametrize("tool", ["save_work_done", "save_labour"])
@pytest.mark.parametrize("text", ["JCB worked 6 hours today", "2 mixers and 1 vibrator on site today"])
async def test_equipment_gets_the_plain_line_and_no_card(tool, text):
    args = {"narrative": text} if tool == "save_work_done" else {"workers": [{"trade": "mixer", "headcount": 2}]}
    provider = FakeToolCallingProvider([[(tool, args)], "✅ Saved: JCB worked 6 hours. Wrong? Reply UNDO."])
    gateway = Gateway()
    result = await r.AgentRunner(provider).run(ctx=CTX, user_text=text, gateway=gateway, scope=ScopeLookup())
    assert gateway.runs == []  # nothing written
    assert result.reply.text == EQUIPMENT_LINE
    assert not result.reply.buttons and not result.reply.list_rows
    assert "undo" not in result.reply.text.casefold() and "saved" not in result.reply.text.casefold()
    assert result.saved_count == 0
