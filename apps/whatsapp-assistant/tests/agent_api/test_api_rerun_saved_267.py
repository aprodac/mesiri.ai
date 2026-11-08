"""[267] (Ilan, 6 Nov 13:10: "before I clicked save it got saved... before save it's just draft"): one Save tap,
during a deploy. The Save went through and "Saved" went out, the worker was restarted before the job ended, and the
job ran again: the same tap was answered "There is nothing waiting to save", which read as "it saved by itself".
The draft card before it went out as a text list: the first card after the restart paid the browser's start.

Fix: a message answered once is never answered again by a re-run of its job; a tap on a card already saved says
"✅ Already saved." with its links; the card browser starts at worker start.

Guards: preparing never writes; a re-run of a message that was never answered still runs; a tap on a card that was
replaced (never saved) still says nothing is waiting.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from tests.agent_api.standin import STAND_IN_TOOLS, two_receipts_model
from tests.agent_api.test_api_receipts_132 import CTX, Cards, _app, _message

from agent_api import whatsapp as wa
from channel.receipt.render import ReceiptRenderer
from mesiri.infrastructure.redis.client import FakeRedis
from runtime import ai_outage
from runtime.agent.wording import say

UPDATE = "50 bag cement, 50 TMT vannu, Main block"


@pytest.fixture(autouse=True)
def _stand_in_tools(monkeypatch):  # noqa: ANN001, ANN202 -- as test_api_whatsapp_119 does
    from agent_api import tools as tools_mod

    real = tools_mod.build_tools
    monkeypatch.setattr(wa, "build_tools", lambda openapi: real(
        openapi, tuple(a for a in tools_mod.ALLOWED if a.name in STAND_IN_TOOLS)))


def _service(seen: list) -> tuple[Any, list]:
    sent: list = []

    async def send(spec, wa_id):  # noqa: ANN001
        sent.append(spec)

    async def send_image(wa_id, image, **kw):  # noqa: ANN001, ANN003
        return True

    service = wa.ApiWhatsApp(provider=two_receipts_model(), database=None, redis=FakeRedis(), send=send,
                             transcribe=None, message_logger=AsyncMock(), app=_app(seen),
                             receipt_builder=Cards(preview=True), send_image=send_image)
    return service, sent


def _writes(seen: list) -> list:
    return [s for s in seen if s[0] in {"POST", "PUT", "PATCH", "DELETE"}]


async def _rerun(service: Any, message: Any) -> None:
    token = ai_outage.retry_attempt.set(2)  # the worker's second try of the same job
    try:
        await service.handle(message, CTX)
    finally:
        ai_outage.retry_attempt.reset(token)


async def test_a_draft_writes_nothing_until_save() -> None:
    seen: list = []
    service, sent = _service(seen)
    await service.handle(_message(UPDATE), CTX)
    assert _writes(seen) == []  # it is a draft: only the card
    assert sent[-1].header_image == b"PREVIEW" and sent[-1].buttons[0].id.startswith(wa.SAVE_PREFIX)
    await service.handle(_message("Save", tap=sent[-1].buttons[0].id), CTX)
    assert len(_writes(seen)) == 2  # the two lines, on Save


async def test_a_save_tap_run_again_after_a_restart_is_not_answered_twice() -> None:
    seen: list = []
    service, sent = _service(seen)
    await service.handle(_message(UPDATE), CTX)
    tap = _message("Save", tap=sent[-1].buttons[0].id)
    await service.handle(tap, CTX)
    replies, writes = len(sent), len(_writes(seen))
    await _rerun(service, tap)
    assert len(sent) == replies  # no "There is nothing waiting to save" after the "Saved"
    assert len(_writes(seen)) == writes


async def test_a_second_tap_on_a_saved_card_says_already_saved_with_its_links() -> None:
    seen: list = []
    service, sent = _service(seen)
    await service.handle(_message(UPDATE), CTX)
    save = sent[-1].buttons[0].id
    await service.handle(_message("Save", tap=save), CTX)
    writes = len(_writes(seen))
    await service.handle(_message("Save", tap=save), CTX)
    text = sent[-1].text
    assert text.startswith(say("api.already_saved", "manglish")) and wa.NOTHING_WAITING not in text
    assert "https://" in text  # the record links, to see or change it on the dashboard
    assert len(_writes(seen)) == writes


async def test_cancel_and_edit_on_a_saved_card_say_it_is_saved() -> None:
    seen: list = []
    service, sent = _service(seen)
    await service.handle(_message(UPDATE), CTX)
    batch = sent[-1].buttons[0].id.split(":", 2)[2]
    await service.handle(_message("Save", tap=sent[-1].buttons[0].id), CTX)
    await service.handle(_message("Cancel", tap=f"{wa.CANCEL_PREFIX}{batch}"), CTX)
    assert sent[-1].text.startswith(say("api.already_saved", "manglish"))
    await service.handle(_message("Edit", tap=f"{wa.EDIT_PREFIX}{batch}"), CTX)
    assert sent[-1].text.startswith(say("api.already_saved", "manglish"))


async def test_guard_a_rerun_of_an_unanswered_message_still_runs() -> None:
    seen: list = []
    service, sent = _service(seen)
    await _rerun(service, _message(UPDATE))  # the first run died before its reply: this one answers
    assert sent and sent[-1].buttons and _writes(seen) == []


async def test_guard_a_tap_on_a_card_never_saved_still_says_nothing_waiting() -> None:
    seen: list = []
    service, sent = _service(seen)
    await service.handle(_message(UPDATE), CTX)
    await service.handle(_message("Save", tap=f"{wa.SAVE_PREFIX}oldbatch"), CTX)
    assert sent[-1].text in wa.NOTHING_ON_CARD_WORDS
    assert _writes(seen) == []


async def test_the_card_browser_warms_up_once_and_never_raises(monkeypatch) -> None:  # noqa: ANN001
    renderer, calls = ReceiptRenderer(), []

    async def pool() -> None:
        calls.append(1)
        raise RuntimeError("no chromium here")

    monkeypatch.setattr(renderer, "_ensure_pool", pool)
    await renderer.warm()
    assert calls == [1]
