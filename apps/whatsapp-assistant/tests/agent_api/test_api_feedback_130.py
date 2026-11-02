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
from agent_api.feedback import TELL_THE_TEAM
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


async def test_the_command_is_answered_by_the_code_without_a_model_turn() -> None:
    """2 Nov: the command is the whole message, so the code answers it: one entry, no model call."""
    model = FakeToolCallingProvider([
        [(TELL_THE_TEAM, {"kind": "bad_ux", "about": "the list printed twice"})], "Sorry, passed on."])
    service, trace = _service(model)
    await service.handle(_message("mesiri bad ux the list printed twice"), CTX)
    calls = trace.log_stage.await_args.kwargs["stage_payload"]["calls"]
    assert [c.get("by") for c in calls if c["tool"] == TELL_THE_TEAM] == ["code"]
    assert model.calls == 0


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


# 2 Nov (Ilan, Paraclette): "mesiri fix it" / "mesiri bad ux" reached the team group 8 minutes late. The class:
# every way the explicit command can arrive must be passed on by the code, whatever happens to the model.


def _photo(caption: str) -> NormalizedMessage:
    from mesiri_contracts.assistant.normalized_message import MediaReference

    return NormalizedMessage(message_id=f"wamid.{uuid.uuid4().hex[:6]}", sender=SenderInfo(wa_id="919800000000"),
                             timestamp=dt.datetime(2026, 11, 2, 6, tzinfo=dt.UTC), modality=InputModality.IMAGE,
                             text=caption, media=MediaReference(object_key="in/shot.jpg", mime_type="image/jpeg"))


def _photo_service(model, seen: str | None) -> tuple[wa.ApiWhatsApp, AsyncMock]:  # noqa: ANN001
    trace = AsyncMock()
    service = wa.ApiWhatsApp(provider=model, database=None, redis=FakeRedis(), send=AsyncMock(), transcribe=None,
                             message_logger=AsyncMock(), trace_logger=trace, app=stand_in_api([]),
                             describe=AsyncMock(return_value=seen))
    return service, trace


def _passed(trace: AsyncMock) -> list[dict]:
    calls = trace.log_stage.await_args.kwargs["stage_payload"].get("calls") or []
    return [c for c in calls if c["tool"] == TELL_THE_TEAM]


async def test_a_screenshot_captioned_with_the_command_reaches_the_team() -> None:
    service, trace = _photo_service(FakeToolCallingProvider(["Sorry, I'll pass it on."]), "A WhatsApp chat screenshot")
    await service.handle(_photo("mesiri bad ux the save button failed"), CTX)
    passed = _passed(trace)
    assert len(passed) == 1 and passed[0]["by"] == "code"
    assert passed[0]["args"]["kind"] == "bad_ux" and passed[0]["args"]["why"] == "the save button failed"
    assert "screenshot" in passed[0]["args"]["about"]


async def test_a_screenshot_that_cannot_be_read_still_reaches_the_team() -> None:
    service, trace = _photo_service(FakeToolCallingProvider([]), None)
    await service.handle(_photo("Mesiri fix it"), CTX)
    assert [p["args"]["kind"] for p in _passed(trace)] == ["wrong_reply"]


async def test_the_command_reaches_the_team_when_the_model_is_down() -> None:
    service, trace = _service(FakeToolCallingProvider([], error=KeyError("tool bug")))
    await service.handle(_message("mesiri fix it"), CTX)  # no model turn, so nothing to fail
    assert [p["args"]["kind"] for p in _passed(trace)] == ["wrong_reply"]


async def test_guard_a_captioned_photo_without_the_command_passes_nothing_on() -> None:
    service, trace = _photo_service(FakeToolCallingProvider(["Got it: 20 bags cement."]), "Cement bags at the gate")
    await service.handle(_photo("cement vannu"), CTX)
    assert _passed(trace) == []


# 2 Nov (Ilan, Paraclette): after "mesiri fix it" / "bad ux" Mesiri repeated the same "Ready to save" list, with the
# same TMT line twice, and never asked what he wanted instead.


async def _with_list(service, *entries: str) -> None:  # noqa: ANN001
    from agent_api.agent import PendingWrite

    state = {"pending": [PendingWrite(tool="record_usage", method="POST", path="/materials/outflows", params={},
                                      body={"n": i}, summary=e, idempotency_key=f"k{i}").to_json()
                         for i, e in enumerate(entries)], "batch": "b1", "language": "english"}
    await service._save_state(CTX, state)


async def test_the_command_keeps_the_waiting_list_and_asks_how_it_should_be() -> None:
    sent = AsyncMock()
    service = wa.ApiWhatsApp(provider=FakeToolCallingProvider([]), database=None, redis=FakeRedis(), send=sent,
                             transcribe=None, message_logger=AsyncMock(), trace_logger=AsyncMock(), app=stand_in_api([]))
    await _with_list(service, "10 TMT steel bars used at Tower A")
    await service.handle(_message("mesiri fix it"), CTX)
    reply = sent.await_args.args[0]
    assert "Ready to save" not in reply.text and not reply.buttons
    assert "How should it be instead?" in reply.text and "#" in reply.text
    state = await service._state(CTX)
    assert state["batch"] == "b1" and len(state["pending"]) == 1  # the list and its buttons still work
    assert state["awaiting_why"]["kind"] == "wrong_reply"


async def test_the_next_message_is_their_preferred_experience_for_the_same_request() -> None:
    trace = AsyncMock()
    sent = AsyncMock()
    service = wa.ApiWhatsApp(provider=FakeToolCallingProvider(["Got it."]), database=None, redis=FakeRedis(),
                             send=sent, transcribe=None, message_logger=AsyncMock(), trace_logger=trace,
                             app=stand_in_api([]))
    await _with_list(service, "10 TMT steel bars used at Tower A")
    await service.handle(_message("mesiri bad ux"), CTX)
    await service.handle(_message("ask me the unit with buttons, kg or pieces"), CTX)
    passed = _passed(trace)
    assert passed[0]["args"]["why"] == "ask me the unit with buttons, kg or pieces"
    assert "their answer to 'how should it be instead?'" in passed[0]["args"]["about"]
    assert "Added to your request" in sent.await_args.args[0].text
    assert "awaiting_why" not in await service._state(CTX)


async def test_guard_an_ordinary_entry_after_the_question_is_not_taken_as_feedback() -> None:
    trace = AsyncMock()
    service = wa.ApiWhatsApp(provider=FakeToolCallingProvider([]), database=None, redis=FakeRedis(),
                             send=AsyncMock(), transcribe=None, message_logger=AsyncMock(), trace_logger=trace,
                             app=stand_in_api([]))
    await service.handle(_message("mesiri bad ux"), CTX)
    service._agent._provider = FakeToolCallingProvider([[("list_projects", {})], "Green Villa."])
    await service.handle(_message("which projects do I have?"), CTX)
    assert _passed(trace) == []  # it looked something up: an ordinary message, not the reason


def test_the_same_entry_prepared_twice_is_listed_once() -> None:
    from agent_api.agent import PendingWrite

    one = PendingWrite(tool="record_usage", method="POST", path="/materials/outflows", params={},
                       body={"material": "TMT", "quantity": 10}, summary="10 TMT steel bars used at Tower A",
                       idempotency_key="a")
    again = PendingWrite(**{**one.to_json(), "idempotency_key": "b"})
    other = PendingWrite(**{**one.to_json(), "body": {"material": "TMT", "quantity": 12}, "idempotency_key": "c"})
    assert [e.idempotency_key for e in wa._distinct([one, again, other])] == ["a", "c"]
