"""PRC-32 (7 Nov 22:51, WhatsApp check): "Green Villa-ku 100 bag cement Malabar Traders-il phone-il order cheythu" ->
card -> Save -> "Not everything could be saved: ... asus asked for 200 bags Cement (REQ-0002, waiting) ... send it
again". The line was dropped.

Root cause: the API's duplicate check (409 ``possible_duplicate``, and a delivery's ``more_than_ordered``) runs at Save,
after the person's tap and outside any model turn, so the tool descriptions' "prepare it again with confirm_duplicate
when they say it is extra" could never happen on WhatsApp; the Save path treated the question as an error.
Class: material requests and orders (confirm_duplicate), a delivery put on an order (confirm_extra).
Fix: whatsapp.py's refusal step keeps such a line, marked confirmed with a new key; the reply shows the API's reason and
"if it is extra, tap Save; if not, Cancel". Guards: a line refused although already confirmed is dropped as before;
any other 409 or 4xx is dropped as before.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from tests.agent_api.standin import BAG, CEMENT, PROJECT, SITE, stand_in_api
from tests.agent_api.test_api_agent_124 import CTX, _message, _service

from agent_api import whatsapp as wa
from agent_api.agent import PendingWrite, WriteResult
from agent_api.tools import ALLOWED, CONFIRM_ARG, MATERIAL_SAID
from mesiri.domains.shared.auth import get_current_user
from mesiri_ai.fakes import FakeToolCallingProvider
from runtime.agent.wording import say

REASON = "Ravi asked for 200 bags Cement for Main block (REQ-0002, waiting). Order it from the request so they are told."


@pytest.fixture(autouse=True)
def _tools(monkeypatch):  # noqa: ANN001, ANN202
    from agent_api import tools as tools_mod

    real = tools_mod.build_tools
    keep = {"ask_for_material", "search_materials", "list_projects", "list_sites"}
    monkeypatch.setattr(wa, "build_tools", lambda o: real(o, tuple(a for a in ALLOWED if a.name in keep)))


class Ask(BaseModel):
    project_id: uuid.UUID
    site_id: uuid.UUID
    material_id: uuid.UUID | None = None
    quantity: float | None = None
    unit_id: uuid.UUID | None = None
    source: str = "dashboard"
    confirm_duplicate: bool = False


def _app(posted: list, *, always_refuse: bool = False):  # noqa: ANN202
    app = stand_in_api([])

    @app.post("/procurement/requests", status_code=201)
    async def ask(body: Ask, jwt: dict = Depends(get_current_user)):
        if always_refuse or not body.confirm_duplicate:
            return JSONResponse(status_code=409, content={"detail": {"code": "possible_duplicate", "message": REASON}})
        posted.append(body.model_dump())
        return {"id": str(uuid.uuid4()), "ref": "REQ-0003"}

    return app


ASK = ("ask_for_material", {"project_id": PROJECT, "site_id": SITE, "material_id": CEMENT, "unit_id": BAG,
                            "quantity": 100, MATERIAL_SAID: "cement", CONFIRM_ARG: "100 bags cement at Main block"})


async def test_a_possible_duplicate_at_save_is_asked_and_save_then_records_it_as_extra() -> None:
    posted: list = []
    service, sent = _service(FakeToolCallingProvider([[ASK], "OK."]), app=_app(posted))
    await service.handle(_message("100 bag cement venam Main block"), CTX)
    await service.handle(_message("Save", tap=sent[-1].buttons[0].id), CTX)
    asked = sent[-1]
    assert posted == []
    assert "(REQ-0002, waiting)" in asked.text  # the API's reason, whole
    assert say("api.extra_ask", "manglish") in asked.text  # in their language ("venam")
    assert say("api.refused_dropped", "manglish") not in asked.text  # kept, not dropped
    assert [b.title for b in asked.buttons][0] == "Save" and "Cancel" in [b.title for b in asked.buttons]
    await service.handle(_message("Save", tap=asked.buttons[0].id), CTX)
    assert len(posted) == 1 and posted[0]["confirm_duplicate"] is True and posted[0]["quantity"] == 100
    assert "❌" not in sent[-1].text


async def test_guard_refused_again_once_confirmed_is_dropped() -> None:
    service, sent = _service(FakeToolCallingProvider([[ASK], "OK."]), app=_app([], always_refuse=True))
    await service.handle(_message("100 bag cement venam Main block"), CTX)
    await service.handle(_message("Save", tap=sent[-1].buttons[0].id), CTX)
    await service.handle(_message("Save", tap=sent[-1].buttons[0].id), CTX)
    assert say("api.refused_dropped", "manglish") in sent[-1].text and not sent[-1].buttons


def _result(status: int, body: object, sent_body: dict | None = None) -> WriteResult:
    entry = PendingWrite("delivery_order", "POST", "/x", {}, sent_body or {}, "157 bags on PO-0003", "k")
    return WriteResult(pending=entry, status=status, body=body)


def test_sibling_more_than_ordered_asks_with_confirm_extra_and_other_refusals_do_not() -> None:
    more = {"detail": {"code": "more_than_ordered", "message": "PO-0003 has 150 bags still to come; this is 157."}}
    assert wa.confirm_field(_result(409, more)) == "confirm_extra"
    assert wa.confirm_field(_result(409, more, {"confirm_extra": True})) == ""
    assert wa.confirm_field(_result(409, {"detail": "PO-0003 is closed; it takes no more deliveries."})) == ""
    assert wa.confirm_field(_result(422, {"detail": {"code": "possible_duplicate"}})) == ""
