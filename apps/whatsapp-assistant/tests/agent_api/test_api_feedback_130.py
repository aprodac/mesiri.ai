"""WA-130: "mesiri bad ux" / "mesiri fix this" always reaches the team bot; memory keeps no list format.

Production, Paraclette 2 Nov 10:52: "Mesiri bad ux" -> the model apologised and called no tool, so
nothing reached the team; and its reply printed the Ready-to-save list twice because the history
kept whole replies (list format included) and the model copied it.
"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from tests.agent_api.standin import ORG, PROJECT, SITE, STAND_IN_TOOLS, USER, stand_in_api

from agent_api import whatsapp as wa
from agent_v2.skills.general.tools import TELL_THE_TEAM
from mesiri.infrastructure.redis.client import FakeRedis
from mesiri_ai.fakes import FakeToolCallingProvider
from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.normalized_message import NormalizedMessage, SenderInfo

CTX = SimpleNamespace(user_id=USER, organization_id=ORG, role="SITE_SUPERVISOR", full_name="Ravi",
                      timezone="Asia/Kolkata", projects=[SimpleNamespace(id=PROJECT, name="Green Villa")],
                      sites=[SimpleNamespace(id=SITE, name="Main block", project_id=PROJECT)])


@pytest.fixture(autouse=True)
def _stand_in_tools(monkeypatch):
    from agent_api import tools as tools_mod

    real = tools_mod.build_tools
    monkeypatch.setattr(wa, "build_tools", lambda openapi: real(
        openapi, tuple(a for a in tools_mod.ALLOWED if a.name in STAND_IN_TOOLS)))


@pytest.mark.parametrize(("said", "expected"), [
    ("Mesiri bad ux", ("bad_ux", "")),
    ("mesiri, fix this: the list came twice", ("wrong_reply", "the list came twice")),
    ("MESIRI bad UI too many buttons", ("bad_ux", "too many buttons")),
    ("this is confusing", None),                 # softer feedback: the model's judgement
    ("mesiri 50 bag cement vannu", None),
    ("fix this tap please", None),
])
def test_the_explicit_command(said: str, expected: tuple[str, str] | None) -> None:
    assert wa.feedback_command(said) == expected


def _message(text: str) -> NormalizedMessage:
    return NormalizedMessage(message_id=f"wamid.{uuid.uuid4().hex[:6]}", sender=SenderInfo(wa_id="919800000000"),
                             timestamp=dt.datetime(2026, 11, 2, 6, tzinfo=dt.UTC), modality=InputModality.TEXT,
                             text=text)


def _service(model) -> tuple[wa.ApiWhatsApp, AsyncMock]:  # noqa: ANN001
    trace = AsyncMock()
    service = wa.ApiWhatsApp(provider=model, database=None, redis=FakeRedis(), send=AsyncMock(), transcribe=None,
                             message_logger=AsyncMock(), trace_logger=trace, app=stand_in_api([]))
    return service, trace


async def test_the_command_reaches_the_team_even_when_the_model_calls_nothing() -> None:
    service, trace = _service(FakeToolCallingProvider(["Sorry, I made a mistake."]))
    await service._memory.remember(CTX, "10 TMT used", "Which unit?\n\n*Ready to save:*\n1. 10 TMT used at Tower A")
    await service.handle(_message("Mesiri bad ux"), CTX)
    calls = trace.log_stage.await_args.kwargs["stage_payload"]["calls"]
    passed = [c for c in calls if c["tool"] == TELL_THE_TEAM]
    assert len(passed) == 1 and passed[0]["by"] == "code"
    assert passed[0]["args"]["kind"] == "bad_ux"
    assert passed[0]["args"]["about"] == "Mesiri's reply before this: Which unit?"


async def test_no_second_entry_when_the_model_passed_it_on_itself() -> None:
    service, trace = _service(FakeToolCallingProvider([
        [(TELL_THE_TEAM, {"kind": "bad_ux", "about": "the list printed twice"})], "Sorry, passed on."]))
    await service.handle(_message("mesiri bad ux the list printed twice"), CTX)
    calls = trace.log_stage.await_args.kwargs["stage_payload"]["calls"]
    assert [c.get("by") for c in calls if c["tool"] == TELL_THE_TEAM] == [None]


async def test_ordinary_messages_add_nothing() -> None:
    service, trace = _service(FakeToolCallingProvider(["Hello."]))
    await service.handle(_message("this is confusing"), CTX)
    assert trace.log_stage.await_args.kwargs["stage_payload"]["calls"] == []


def test_memory_keeps_the_words_and_the_list_as_a_note() -> None:
    sent = "Which unit for the TMT?\n\n*Ready to save:*\n1. 10 TMT used at Tower A\n2. 5 bags cement"
    assert wa.for_memory(sent) == (
        "Which unit for the TMT?\n(under this reply, waiting for the Save button: 10 TMT used at Tower A; 5 bags cement)")
    assert wa.for_memory("Hello Ravi.") == "Hello Ravi."


async def test_the_conversation_stores_the_note_not_the_list() -> None:
    service, _ = _service(FakeToolCallingProvider(["Hi."]))
    await service.handle(_message("hello"), CTX)
    service._agent._provider = FakeToolCallingProvider(["Hi again."])
    texts = [m.text for m in await service._memory.load(CTX)]
    assert all("*Ready to save:*" not in t for t in texts)
