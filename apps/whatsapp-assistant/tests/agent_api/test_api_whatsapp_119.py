"""WA-119: the API agent on WhatsApp (``assistant_mode`` = "api").

- a text message: the model's words, the ready entries listed, Save / Cancel buttons;
- Save: sent to the API as the sender, a refused one stays waiting with its reason;
- Cancel, or a button of an older list: nothing is saved;
- a voice note is transcribed first; an empty one is said plainly;
- a photo is left to the journey;
- a model failure says so and keeps what was waiting;
- the journey: a company on "api" gets the API agent, any other mode does not.
"""

from __future__ import annotations

import datetime as dt
import functools
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from tests.agent_api.standin import ORG, STAND_IN_TOOLS, USER, stand_in_api, two_receipts_model

from agent_api import whatsapp as wa
from agent_api.agent import SAVE_READY
from channel.replies import ReplySpec
from mesiri.infrastructure.redis.client import FakeRedis
from mesiri_ai.fakes import FakeToolCallingProvider
from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.normalized_message import NormalizedMessage, SenderInfo
from runtime.ai_outage import FallBackToV2

CTX = SimpleNamespace(user_id=USER, organization_id=ORG, role="SITE_SUPERVISOR", full_name="Ravi",
                      timezone="Asia/Kolkata", org_active=True)


def _message(text: str | None = "50 bag cement, 50 TMT vannu", modality=InputModality.TEXT, tap: str | None = None):
    metadata = {"interactive_reply_id": tap, "interactive_reply_type": "button_reply"} if tap else {}
    return NormalizedMessage(
        message_id=f"wamid.{uuid.uuid4().hex[:6]}",
        sender=SenderInfo(wa_id="919876543210", profile_name="Ravi"),
        timestamp=dt.datetime(2026, 11, 1, 6, tzinfo=dt.UTC),
        modality=InputModality.INTERACTIVE if tap else modality,
        text=text,
        metadata=metadata,
    )


class Harness:
    def __init__(self, model: Any, *, refuse_tmt: bool = False, transcript: str = "") -> None:
        self.seen: list = []
        self.sent: list[ReplySpec] = []
        self.logger = AsyncMock()
        self.trace = AsyncMock()
        self.app = stand_in_api(self.seen, refuse_tmt=refuse_tmt)

        async def send(spec: ReplySpec, wa_id: str) -> None:
            self.sent.append(spec)

        async def transcribe(message: Any) -> tuple[str, str | None, str | None]:
            return transcript, None, "ml"

        self.redis = FakeRedis()
        self.service = wa.ApiWhatsApp(
            provider=model, database=None, redis=self.redis, send=send, transcribe=transcribe,
            message_logger=self.logger, trace_logger=self.trace, app=self.app,
        )

    def posts(self) -> int:
        return [m for m, *_ in self.seen].count("POST")

    def buttons(self) -> list[str]:
        return [b.id for b in self.sent[-1].buttons or ()]


@pytest.fixture(autouse=True)
def _stand_in_tools(monkeypatch):
    from agent_api import tools as tools_mod

    real = tools_mod.build_tools
    monkeypatch.setattr(wa, "build_tools", lambda openapi: real(
        openapi, tuple(a for a in tools_mod.ALLOWED if a.name in STAND_IN_TOOLS)))


async def test_a_message_gets_the_models_words_the_ready_list_and_save_cancel() -> None:
    h = Harness(two_receipts_model())
    assert await h.service.handle(_message(), CTX) is True
    reply = h.sent[-1]
    assert reply.text.startswith("Ready: 50 bags cement")
    assert "*Ready to save:*\n1. 50 bags cement, Green Villa\n2. 50 TMT bars, Green Villa" in reply.text
    assert [b.title for b in reply.buttons] == ["Save", "Cancel"]
    assert h.posts() == 0
    h.logger.log_reply.assert_awaited()
    h.logger.mark_completed.assert_awaited()
    traced = h.trace.log_stage.await_args.kwargs
    assert traced["stage"] == "agent_api_turn" and traced["event_source"] == "agent_api"
    assert traced["stage_payload"]["pending"] == ["50 bags cement, Green Villa", "50 TMT bars, Green Villa"]


async def test_save_sends_them_to_the_api_once() -> None:
    h = Harness(two_receipts_model())
    await h.service.handle(_message(), CTX)
    save, _cancel = h.buttons()
    assert await h.service.handle(_message("Save", tap=save), CTX)
    assert h.posts() == 2
    assert h.sent[-1].text.startswith("Saved.") and "✅ 50 TMT bars, Green Villa" in h.sent[-1].text
    # The same button again: nothing waits, nothing is sent.
    await h.service.handle(_message("Save", tap=save), CTX)
    assert h.posts() == 2 and h.sent[-1].text == wa.NOTHING_WAITING


async def test_a_refused_entry_stays_waiting_with_the_apis_reason() -> None:
    h = Harness(two_receipts_model(), refuse_tmt=True)
    await h.service.handle(_message(), CTX)
    await h.service.handle(_message("Save", tap=h.buttons()[0]), CTX)
    reply = h.sent[-1]
    assert reply.text.startswith("Not everything could be saved:")
    assert "✅ 50 bags cement" in reply.text and "❌ 50 TMT bars, Green Villa: Not authorized for this site" in reply.text
    assert [b.title for b in reply.buttons] == ["Save", "Cancel"]  # the refused one can be tried again
    state = await h.redis.get_json(f"agent_api:{ORG}:{USER}")
    assert [e["summary"] for e in state["pending"]] == ["50 TMT bars, Green Villa"]


async def test_cancel_and_an_older_lists_button_save_nothing() -> None:
    h = Harness(FakeToolCallingProvider([
        *two_receipts_model()._script,
        # second message: the model prepares one more entry; the list (and its buttons) is new
    ]))
    await h.service.handle(_message(), CTX)
    old_save, cancel = h.buttons()
    await h.service.handle(_message("Cancel", tap=cancel), CTX)
    assert h.sent[-1].text == wa.CANCELLED and h.posts() == 0
    await h.service.handle(_message("Save", tap=old_save), CTX)
    assert h.sent[-1].text == wa.NOTHING_WAITING and h.posts() == 0


async def test_saying_save_saves_through_the_model_and_says_what_the_api_answered() -> None:
    first = two_receipts_model()
    h = Harness(first)
    await h.service.handle(_message(), CTX)
    h.service._agent._provider = FakeToolCallingProvider([[(SAVE_READY, {})], ""])
    await h.service.handle(_message("ok save cheyyu"), CTX)
    assert h.posts() == 2
    assert h.sent[-1].text.startswith("Saved.") and not h.sent[-1].buttons


async def test_a_voice_note_is_transcribed_first() -> None:
    model = two_receipts_model()
    h = Harness(model, transcript="50 bag cement, 50 TMT vannu")
    assert await h.service.handle(_message(None, modality=InputModality.VOICE), CTX)
    assert model.last_messages[-1].text == "50 bag cement, 50 TMT vannu"
    assert [b.title for b in h.sent[-1].buttons] == ["Save", "Cancel"]


async def test_an_empty_voice_note_is_said_plainly() -> None:
    model = two_receipts_model()
    h = Harness(model, transcript="")
    assert await h.service.handle(_message(None, modality=InputModality.VOICE), CTX)
    assert h.sent[-1].text == wa.COULD_NOT_HEAR and model.calls == 0


async def test_a_photo_is_left_to_the_journey() -> None:
    h = Harness(two_receipts_model())
    assert await h.service.handle(_message("bill", modality=InputModality.IMAGE), CTX) is False
    assert h.sent == []


async def test_a_model_bug_falls_back_to_v2_and_keeps_what_was_waiting() -> None:
    h = Harness(two_receipts_model())
    await h.service.handle(_message(), CTX)
    h.service._agent._provider = FakeToolCallingProvider([], error=RuntimeError("model down"))
    with pytest.raises(FallBackToV2):  # WA-128: v2 answers it; never a bare "send it again"
        await h.service.handle(_message("and 10 bags sand"), CTX)
    state = await h.redis.get_json(f"agent_api:{ORG}:{USER}")
    assert len(state["pending"]) == 2


async def test_the_conversation_is_remembered_for_the_next_message() -> None:
    model = two_receipts_model()
    h = Harness(model)
    await h.service.handle(_message(), CTX)
    nxt = FakeToolCallingProvider(["Which one?"])
    h.service._agent._provider = nxt
    await h.service.handle(_message("what did I just send?"), CTX)
    texts = [m.text for m in nxt.last_messages]
    assert texts[0] == "50 bag cement, 50 TMT vannu" and "Ready to save" in texts[1]
    assert texts[-1] == "what did I just send?"


# -- the journey ---------------------------------------------------------------------------


def _journey(monkeypatch, mode: str, model: Any):  # noqa: ANN202
    from tests.unit.test_agent_routing import _build

    harness = Harness(model)
    real_init = wa.ApiWhatsApp.__init__

    def init(self, **kwargs):  # noqa: ANN001, ANN003
        kwargs["app"] = harness.app
        real_init(self, **kwargs)

    monkeypatch.setattr(wa.ApiWhatsApp, "__init__", init)
    import runtime.message_journey as mj

    real_build = mj.build_message_handlers

    @functools.wraps(real_build)
    def build(**deps):  # noqa: ANN003
        return real_build(**deps, material_db=object(), redis_client=FakeRedis())

    monkeypatch.setattr(mj, "build_message_handlers", build)
    on_normalized, deps, _ = _build(monkeypatch, mode=mode, provider=model)
    return on_normalized, deps, harness


async def test_a_company_on_api_mode_gets_the_api_agent(monkeypatch) -> None:
    on_normalized, deps, harness = _journey(monkeypatch, "api", two_receipts_model())
    await on_normalized(_message(), {})
    sent = deps["sender"].send_button.await_args.kwargs
    assert "*Ready to save:*" in sent["body"]
    assert [b.title for b in sent["buttons"]] == ["Save", "Cancel"]
    deps["memory_coordinator"].record_turn.assert_not_awaited()  # the classic turn never ran


@pytest.mark.parametrize("mode", ["classic", "v2", None])
async def test_any_other_mode_never_reaches_the_api_agent(monkeypatch, mode) -> None:
    from tests.unit.test_agent_routing import ASK

    model = FakeToolCallingProvider(list(ASK._script))
    on_normalized, deps, harness = _journey(monkeypatch, mode, model)
    await on_normalized(_message("50 bags cement"), {})
    sent = deps["sender"].send_button.await_args.kwargs
    assert "Ready to save" not in sent["body"] and harness.seen == []
