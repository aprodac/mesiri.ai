"""[264] (5 Nov, an admin: "Send todays report" -> "OK." and a card; the Save tap then said "✅ Save aayi."): a report
send held for a tap is a send, not a record.

- the card line is drawn by the code and names the project ("📤 Today's report for *Green Villa*");
- no bare "OK." above a held list: the list and the code's Save / Send line speak; a previewed card's caption is
  the Send line;
- the button says Send when only a send waits, and the tap's reply says the report went out, with its link;
- guards: a list of records keeps Save, "Tap Save to record these" and the "Saved." result; a record and a send
  saved together keep "Saved." for the record and the sent line for the report.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import Depends
from tests.agent_api.standin import PROJECT, STAND_IN_TOOLS, two_receipts_model
from tests.agent_api.test_api_receipts_132 import CTX, Cards, _message
from tests.agent_api.test_api_receipts_132 import _app as receipts_app

from agent_api import whatsapp as wa
from agent_api.agent import PendingWrite, WriteResult, send_line
from mesiri.domains.shared.auth import get_current_user
from mesiri.infrastructure.redis.client import FakeRedis
from mesiri_ai.fakes import FakeToolCallingProvider
from runtime.agent.wording import say

TOOLS = STAND_IN_TOOLS | {"send_dpr"}


@pytest.fixture(autouse=True)
def _stand_in_tools(monkeypatch):  # noqa: ANN001, ANN202
    from agent_api import tools as tools_mod

    real = tools_mod.build_tools
    monkeypatch.setattr(wa, "build_tools", lambda openapi: real(
        openapi, tuple(a for a in tools_mod.ALLOWED if a.name in TOOLS)))


def _app(sends: list):  # noqa: ANN202
    app = receipts_app()

    @app.post("/dpr/projects/{project_id}/send")
    async def send(project_id: str, jwt: dict = Depends(get_current_user)):
        sends.append(project_id)
        return {"status": "queued", "report_date": "2026-11-02"}

    return app


def _send_model(words: str = "OK.") -> FakeToolCallingProvider:
    return FakeToolCallingProvider([
        [("send_dpr", {"project_id": PROJECT, "confirm_line": "Today's DPR report"})],
        words,
    ])


def _service(model: Any, *, preview: bool = False) -> tuple[Any, list, list]:
    sent: list = []
    sends: list = []

    async def send(spec, wa_id):  # noqa: ANN001, ANN202
        sent.append(spec)

    async def send_image(wa_id, image, **kw):  # noqa: ANN001, ANN003, ANN202
        return True

    service = wa.ApiWhatsApp(provider=model, database=None, redis=FakeRedis(), send=send, transcribe=None,
                             message_logger=AsyncMock(), app=_app(sends), receipt_builder=Cards(preview=preview),
                             send_image=send_image)
    return service, sent, sends


async def test_send_todays_report_holds_a_send_card_that_names_the_project_never_a_bare_ok() -> None:
    service, sent, sends = await _held()
    reply = sent[-1]
    assert not reply.text.startswith("OK")
    assert "Today's report for *Green Villa*" in reply.text
    assert "Today's DPR report" not in reply.text  # the model's line is replaced by the code's
    assert reply.buttons[0].title == wa.SEND_TITLE
    assert wa.READY_SEND_HEADING in reply.text and wa.READY_HEADING not in reply.text
    assert sends == []  # nothing goes out before the tap


async def _held(*, preview: bool = False) -> tuple[Any, list, list]:
    service, sent, sends = _service(_send_model(), preview=preview)
    await service.handle(_message("Send todays report"), CTX)
    return service, sent, sends


async def test_a_previewed_send_card_is_captioned_with_the_send_line() -> None:
    _s, sent, _ = await _held(preview=True)
    reply = sent[-1]
    assert reply.header_image == b"PREVIEW"
    # WA-259: the structured line as on the slip, then the Send line (the human line when the model said nothing else).
    structured, human = reply.text.strip().split("\n\n")
    assert structured.startswith("1. *Send today's report*") and "Green Villa" in structured
    assert human in (wa.PRESS_SEND, say("api.press_send", "manglish"))


async def test_the_send_tap_says_the_report_went_out_not_saved() -> None:
    service, sent, sends = await _held()
    await service.handle(_message("Send", tap=sent[-1].buttons[0].id), CTX)
    text = sent[-1].text
    assert sends == [PROJECT]
    assert "📤" in text and "Green Villa" in text
    assert "Saved" not in text and "Save aayi" not in text
    assert "/reports" in text  # the link to the reports page stays


async def test_a_previewed_send_tap_is_not_save_aayi() -> None:
    service, sent, sends = await _held(preview=True)
    await service.handle(_message("Send", tap=sent[-1].buttons[0].id), CTX)
    text = sent[-1].text
    assert sends == [PROJECT]
    assert "Save aayi" not in text and wa.SAVED_SHORT not in text and "📤" in text


# -- lines in their language --------------------------------------------------------------------------------------


def test_the_send_line_and_the_sent_line_in_manglish() -> None:
    from agent_api.agent import Places

    places = Places(projects=((PROJECT, "cl"),), sites=())
    line = send_line(f"/dpr/projects/{PROJECT}/send", places, "manglish")
    assert line == "📤 *cl* innathe report"
    result = WriteResult(pending=_pending(line), status=200, body={"status": "queued"})
    sent = wa.sent_line(result, "manglish")
    assert sent.startswith("📤 Report ayachu: *cl* innathe report.")
    assert wa.press_line([_pending(line)], "manglish") == say("api.press_send", "manglish")


def test_a_project_that_is_not_theirs_keeps_the_models_line() -> None:
    from agent_api.agent import Places

    assert send_line("/dpr/projects/other/send", Places(projects=((PROJECT, "cl"),), sites=()), "english") == ""


def _pending(summary: str, tool: str = "send_dpr") -> PendingWrite:
    path = f"/dpr/projects/{PROJECT}/send" if tool == "send_dpr" else "/materials/inflows"
    return PendingWrite(tool=tool, method="POST", path=path, params={}, body={"project_id": PROJECT},
                        summary=summary, idempotency_key="k-" + tool)


# -- guards -------------------------------------------------------------------------------------------------------


async def test_guard_a_list_of_records_keeps_save_and_its_line() -> None:
    sends: list = []
    sent: list = []

    async def send(spec, wa_id):  # noqa: ANN001, ANN202
        sent.append(spec)

    service = wa.ApiWhatsApp(provider=two_receipts_model(), database=None, redis=FakeRedis(), send=send,
                             transcribe=None, message_logger=AsyncMock(), app=_app(sends), receipt_builder=Cards())
    await service.handle(_message("50 bag cement, 50 TMT vannu, Main block"), CTX)
    reply = sent[-1]
    assert reply.buttons[0].title == "Save"
    assert wa.READY_HEADING in reply.text
    assert reply.text.endswith((wa.PRESS_SAVE, say("api.press_save", "manglish")))


def test_guard_a_record_and_a_send_saved_together() -> None:
    record = WriteResult(pending=_pending("50 bags cement", tool="record_receipt"), status=201, body={"id": "x"})
    report = WriteResult(pending=_pending("📤 Today's report for *Green Villa*"), status=200, body={})
    text = wa._saved_text([record, report], None, today="2026-11-02")
    assert text.startswith("Saved.") and "✅ 50 bags cement" in text
    assert "📤 Report sent: Today's report for *Green Villa*." in text
    short = wa._saved_short([record, report], None, today="2026-11-02")
    assert short.startswith(wa.SAVED_SHORT) and "📤 Report sent" in short
