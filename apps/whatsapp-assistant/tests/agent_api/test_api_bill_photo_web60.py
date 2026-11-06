"""WEB-60 (Ilan, 5 Nov 2026: "make sure sent expense bill and all is there saved for an expense if image is there"):
the bill photo stays with its expense whichever order the messages come in (``agent_api/bill_photo.py``).

Reported class: the photo key reached only a write made in the photo's own turn.
- case 1, photo first, Mesiri asks, the answer makes the expense: the photo is on it;
- case 2, expense typed first and waiting on the card, then the photo: the photo is on that expense;
- case 3, expense saved, then its bill: the facts name it and `add_bill_photo` adds the photo to it;
Guards: a photo that raised no question is not carried into an unrelated later expense; two waiting expenses are not
guessed between; `add_bill_photo` with no photo is refused by the code.
"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import Depends
from pydantic import BaseModel
from tests.agent_api.standin import ORG, PROJECT, SITE, USER, stand_in_api

from agent_api import whatsapp as wa
from agent_api.agent import ASK
from agent_api.tools import CONFIRM_ARG
from channel.replies import ReplySpec
from mesiri.domains.shared.auth import get_current_user
from mesiri.infrastructure.redis.client import FakeRedis
from mesiri_ai.fakes import FakeToolCallingProvider
from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.normalized_message import (
    MediaReference,
    NormalizedMessage,
    SenderInfo,
)

CTX = SimpleNamespace(
    user_id=USER, organization_id=ORG, role="SITE_SUPERVISOR", full_name="Ravi", timezone="Asia/Kolkata",
    projects=[SimpleNamespace(id=PROJECT, name="Green Villa")],
    sites=[SimpleNamespace(id=SITE, name="Main block", project_id=PROJECT)],
)
TOOLS = {"list_projects", "list_sites", "record_expense", "add_bill_photo"}
KEY = "media/wamid.bill/m1"
SAVED_ID = str(uuid.uuid4())


class _Expense(BaseModel):
    project_id: uuid.UUID
    amount: float
    occurred_date: str | None = None
    vendor_text: str | None = None
    source: str = "web"
    media_object_key: str | None = None


class _Bill(BaseModel):
    data_base64: str | None = None
    content_type: str | None = None
    media_object_key: str | None = None


@pytest.fixture(autouse=True)
def _tools(monkeypatch):
    from agent_api import tools as tools_mod

    real = tools_mod.build_tools
    monkeypatch.setattr(wa, "build_tools", lambda openapi: real(
        openapi, tuple(a for a in tools_mod.ALLOWED if a.name in TOOLS)))


def _api(posted: list[tuple[str, dict]]):
    app = stand_in_api([])

    @app.post("/expenses", status_code=201)
    async def record(body: _Expense, jwt: dict = Depends(get_current_user)):
        posted.append(("/expenses", body.model_dump()))
        return {"id": SAVED_ID, "status": "succeeded"}

    @app.post("/expenses/{expense_id}/attachments", status_code=201)
    async def bill(expense_id: str, body: _Bill, jwt: dict = Depends(get_current_user)):
        posted.append((f"/expenses/{expense_id}/attachments", body.model_dump()))
        return [{"id": str(uuid.uuid4()), "expense_id": expense_id, "attachment_type": "receipt", "url": "https://x"}]

    return app


def _message(text: str | None, *, photo: bool = False, tap: str | None = None) -> NormalizedMessage:
    modality = InputModality.INTERACTIVE if tap else InputModality.IMAGE if photo else InputModality.TEXT
    return NormalizedMessage(
        message_id=f"wamid.{uuid.uuid4().hex[:6]}",
        sender=SenderInfo(wa_id="919876543210", profile_name="Ravi"),
        timestamp=dt.datetime(2026, 11, 5, 6, tzinfo=dt.UTC), modality=modality, text=text,
        metadata={"interactive_reply_id": tap} if tap else {},
        media=MediaReference(media_id="m1", mime_type="image/jpeg", object_key=KEY) if photo else None,
    )


async def _describe(message: Any, hint: str | None = None) -> str:
    return "A hardware bill: Sri Hardwares, ₹4,500, 5 Nov 2026"


def _service(posted: list):
    sent: list[ReplySpec] = []

    async def send(spec: ReplySpec, wa_id: str) -> None:
        sent.append(spec)

    service = wa.ApiWhatsApp(provider=FakeToolCallingProvider(["hi"]), database=None, redis=FakeRedis(), send=send,
                             transcribe=None, message_logger=AsyncMock(), app=_api(posted), describe=_describe)
    return service, sent


async def _say(service, script: list, message: NormalizedMessage) -> FakeToolCallingProvider:
    model = FakeToolCallingProvider(script)
    service._agent._provider = model
    assert await service.handle(message, CTX)
    return model


async def _save(service, sent) -> None:
    save = next(b for b in sent[-1].buttons if b.title == "Save")
    await _say(service, ["Saved."], _message("Save", tap=save.id))


def _expense(amount: float = 4500, **more: Any) -> tuple:
    return ("record_expense", {"project_id": PROJECT, "amount": amount, "vendor_text": "Sri Hardwares",
                               CONFIRM_ARG: f"₹{amount:,.0f} Sri Hardwares", **more})


async def test_case1_photo_then_the_answer_makes_the_expense_with_the_photo() -> None:
    posted: list = []
    service, sent = _service(posted)
    await _say(service, [[(ASK, {"question": "Which project was this for?", "options": ["Green Villa"]})],
                         "Which project was this for?"], _message(None, photo=True))
    await _say(service, [[_expense()], "₹4,500 Sri Hardwares is ready. Tap Save."], _message("Green Villa"))
    await _save(service, sent)
    assert posted == [("/expenses", {**posted[0][1], "media_object_key": KEY})]


async def test_case2_expense_waiting_on_the_card_gets_the_photo_that_follows() -> None:
    posted: list = []
    service, sent = _service(posted)
    await _say(service, [[_expense()], "₹4,500 Sri Hardwares is ready. Tap Save."], _message("paid 4500 sri hardwares"))
    await _say(service, ["That's the bill for the ₹4,500 above. Tap Save."], _message(None, photo=True))
    await _save(service, sent)
    assert len(posted) == 1 and posted[0][1]["media_object_key"] == KEY


async def test_case3_bill_after_the_save_is_added_to_that_expense() -> None:
    posted: list = []
    service, sent = _service(posted)
    await _say(service, [[_expense()], "₹4,500 Sri Hardwares is ready. Tap Save."], _message("paid 4500 sri hardwares"))
    await _save(service, sent)
    assert posted[0][1]["media_object_key"] is None
    model = await _say(service, [[("add_bill_photo", {"expense_id": SAVED_ID, CONFIRM_ARG: "Bill photo for ₹4,500"})],
                                 "Bill photo for ₹4,500 is ready. Tap Save."], _message(None, photo=True))
    assert f"expense_id {SAVED_ID}" in model.last_system_prompt + "".join(m.text or "" for m in model.last_messages)
    await _save(service, sent)
    assert posted[1] == (f"/expenses/{SAVED_ID}/attachments",
                         {"data_base64": None, "content_type": None, "media_object_key": KEY})
    # once the bill is on it, the next photo is not offered for it again
    model = await _say(service, ["ok"], _message(None, photo=True))
    assert SAVED_ID not in model.last_system_prompt


async def test_guard_a_photo_that_asked_nothing_is_not_carried_into_a_later_expense() -> None:
    posted: list = []
    service, sent = _service(posted)
    await _say(service, ["Nice progress on the slab."], _message(None, photo=True))
    await _say(service, [[_expense(800, vendor_text="Tea shop")], "₹800 is ready. Tap Save."], _message("tea 800"))
    await _save(service, sent)
    assert posted[0][1]["media_object_key"] is None


async def test_guard_two_waiting_expenses_are_not_guessed_between() -> None:
    posted: list = []
    service, sent = _service(posted)
    await _say(service, [[_expense(), _expense(800, vendor_text="Tea shop")], "Two expenses are ready. Tap Save."],
               _message("paid 4500 sri hardwares and 800 tea"))
    await _say(service, ["Which expense is this bill for?"], _message(None, photo=True))
    await _save(service, sent)
    assert [p[1]["media_object_key"] for p in posted] == [None, None]


async def test_guard_add_bill_photo_with_no_photo_is_refused_by_the_code() -> None:
    posted: list = []
    service, sent = _service(posted)
    seen: list = []

    def answer(records):  # what the tool said back
        seen.extend(r.outcome.content for r in records)
        return "Please send the bill photo."

    await _say(service, [[("add_bill_photo", {"expense_id": SAVED_ID, CONFIRM_ARG: "bill"})], answer],
               _message("add the bill to that expense"))
    assert "no photo in this message" in str(seen)
    assert not sent[-1].buttons and posted == []
