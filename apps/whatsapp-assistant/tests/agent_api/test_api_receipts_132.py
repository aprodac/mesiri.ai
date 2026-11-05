"""WA-132: a v3 Save sends the green SAVED card, as classic and v2 do.

- the Save tap: the "Saved" line first, then the card (the reply never waits for the picture);
- "save it" in words (save_ready_entries): the same card;
- a refused entry, and an entry with no card (a site's conditions), are left out;
- every v3 record type builds the real card data (channel.receipt.data.build_receipt_data).
"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import Depends
from tests.agent_api.standin import (
    BAG,
    CEMENT,
    ORG,
    PROJECT,
    SITE,
    STAND_IN_TOOLS,
    TMT,
    USER,
    stand_in_api,
    two_receipts_model,
)

from agent_api import whatsapp as wa
from agent_api.agent import SAVE_READY, PendingWrite, WriteResult
from agent_api.receipts import CARD_TYPES, _pair
from channel.receipt.builder import RecordReceiptBuilder
from mesiri.domains.shared.auth import get_current_user
from mesiri.infrastructure.redis.client import FakeRedis
from mesiri_ai.fakes import FakeToolCallingProvider
from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.normalized_message import NormalizedMessage, SenderInfo

OTHER_SITE = str(uuid.uuid4())
CTX = SimpleNamespace(user_id=USER, organization_id=ORG, role="SITE_SUPERVISOR", full_name="Ravi",
                      timezone="Asia/Kolkata", projects=[SimpleNamespace(id=PROJECT, name="Green Villa")],
                      sites=[SimpleNamespace(id=SITE, name="Main block", project_id=PROJECT),
                             SimpleNamespace(id=OTHER_SITE, name="Tower B", project_id=PROJECT)])


@pytest.fixture(autouse=True)
def _stand_in_tools(monkeypatch):
    from agent_api import tools as tools_mod

    real = tools_mod.build_tools
    monkeypatch.setattr(wa, "build_tools", lambda openapi: real(
        openapi, tuple(a for a in tools_mod.ALLOWED if a.name in STAND_IN_TOOLS)))


class Cards:
    """Stands in for RecordReceiptBuilder: keeps what it was asked to draw. ``preview=False``: the TO SAVE
    preview (WA-210) can't be drawn, so the list goes out as text and the SAVED card follows the Save, as before."""

    def __init__(self, *, preview: bool = False) -> None:
        self.asked: list = []
        self.previews: list = []
        self._preview = preview

    async def build_combined(self, saved: list, actor: Any, *, kept: bool = False, localize: bool = True
                             ) -> bytes | None:
        if not kept:
            self.previews.append((saved, localize))
            return b"PREVIEW" if self._preview else None
        self.asked.append((saved, kept))
        return b"PNG"


def _app(seen: list | None = None):  # noqa: ANN202
    app = stand_in_api(seen if seen is not None else [], refuse_tmt=False)
    app.router.routes = [r for r in app.router.routes if getattr(r, "path", "") != "/materials"]

    @app.get("/materials")
    async def materials(limit: int = 50, search: str | None = None, jwt: dict = Depends(get_current_user)):
        rows = [{"id": CEMENT, "name": "Cement", "default_unit_id": BAG},
                {"id": TMT, "name": "TMT bar", "default_unit_id": BAG}]
        hit = [r for r in rows if not search or search.lower() in r["name"].lower()]
        return {"items": hit, "total": len(hit)}

    return app


def _message(text: str, tap: str | None = None) -> NormalizedMessage:
    return NormalizedMessage(message_id=f"wamid.{uuid.uuid4().hex[:6]}", sender=SenderInfo(wa_id="919800000000"),
                             timestamp=dt.datetime(2026, 11, 2, 6, tzinfo=dt.UTC),
                             modality=InputModality.INTERACTIVE if tap else InputModality.TEXT, text=text,
                             metadata={"interactive_reply_id": tap} if tap else {})


def _service(model, cards: Cards, order: list):  # noqa: ANN001, ANN202
    sent: list = []

    async def send(spec, wa_id):  # noqa: ANN001
        sent.append(spec)
        order.append("text")

    async def send_image(wa_id, image, **kw):  # noqa: ANN001, ANN003
        order.append(("image", image, kw.get("shows")))
        return True

    service = wa.ApiWhatsApp(provider=model, database=None, redis=FakeRedis(), send=send, transcribe=None,
                             message_logger=AsyncMock(), app=_app(), receipt_builder=cards, send_image=send_image)
    return service, sent


async def test_the_save_tap_sends_the_saved_card_after_the_saved_line() -> None:
    cards, order = Cards(), []
    service, sent = _service(two_receipts_model(), cards, order)
    await service.handle(_message("50 bag cement, 50 TMT vannu, Main block"), CTX)  # [213]: two sites, so named
    order.clear()
    await service.handle(_message("Save", tap=sent[-1].buttons[0].id), CTX)
    assert order[0] == "text" and order[1][0] == "image" and order[1][1] == b"PNG"
    (pairs, kept), = cards.asked
    assert kept is True and len(pairs) == 2
    draft = pairs[0][0].draft_action
    assert draft.action_type.value == "record_material_receipt"
    assert draft.fields["material_name"] == "Cement" and draft.fields["unit"] == "bag"
    assert draft.site_id == SITE and pairs[0][1].material_row_id


async def test_saying_save_it_sends_the_card_too() -> None:
    cards, order = Cards(), []
    service, _ = _service(two_receipts_model(), cards, order)
    await service.handle(_message("50 bag cement, 50 TMT vannu, Main block"), CTX)
    service._agent._provider = FakeToolCallingProvider([[(SAVE_READY, {})], "Saved both."])
    order.clear()
    await service.handle(_message("ok save cheyyu"), CTX)
    assert [o[0] if isinstance(o, tuple) else o for o in order] == ["text", "image"]


async def test_no_card_without_saves_or_builder() -> None:
    cards, order = Cards(), []
    service, _ = _service(FakeToolCallingProvider(["Hello."]), cards, order)
    await service.handle(_message("hello"), CTX)
    assert order == ["text"] and cards.asked == []


def _entry(tool: str, body: dict) -> WriteResult:
    pending = PendingWrite(tool=tool, method="POST", path="/x", params={}, body=body, summary=f"{tool} line",
                           idempotency_key=f"api-agent-{uuid.uuid4()}")
    return WriteResult(pending, 201, {"id": str(uuid.uuid4())})


BODIES = {
    "record_receipt": {"project_id": PROJECT, "site_id": SITE, "material_id": CEMENT, "unit_id": BAG,
                       "quantity": 50, "supplier": "Sri Traders"},
    "record_usage": {"project_id": PROJECT, "site_id": SITE, "material_id": CEMENT, "unit_id": BAG, "quantity": 20},
    "record_transfer": {"from_site_id": SITE, "to_site_id": OTHER_SITE, "material_id": CEMENT, "unit_id": BAG,
                        "quantity": 10},
    "record_expense": {"project_id": PROJECT, "site_id": SITE, "amount": 450, "category_text": "Food",
                       "description": "tea and snacks"},
    "record_attendance": {"project_id": PROJECT, "site_id": SITE,
                          "lines": [{"trade": "mason", "headcount": 6}, {"trade": "helper", "headcount": 4}]},
    "record_work": {"project_id": PROJECT, "site_id": SITE, "work_type": "plastering",
                    "quantities": [{"quantity": 180, "unit": "sqm"}], "narrative": "first floor east"},
    "report_issue": {"project_id": PROJECT, "site_id": SITE, "issue_type": "MATERIAL_SHORTAGE",
                     "severity": "HIGH", "narrative": "cement ran out"},
}


@pytest.mark.parametrize("tool", sorted(CARD_TYPES))
def test_every_v3_record_type_builds_the_real_card_data(tool: str) -> None:
    pair = _pair(_entry(tool, BODIES[tool]).pending, "row-1", CTX, ({CEMENT: "Cement"}, {BAG: "bag"}), "cor_x")
    assert pair is not None
    data = RecordReceiptBuilder._data(pair[0], pair[1], CTX, dt.datetime.now(dt.UTC), True)
    assert data is not None
    if tool == "record_transfer":
        assert pair[0].draft_action.fields["to_site_name"] == "Tower B"


def test_a_refused_entry_or_one_with_no_card_is_left_out() -> None:
    from agent_api.receipts import saved_card

    refused = WriteResult(_entry("record_receipt", BODIES["record_receipt"]).pending, 403, {"detail": "no"})
    conditions = _entry("set_site_conditions", {"weather": "rainy"})
    assert "set_site_conditions" not in CARD_TYPES
    cards = Cards()

    import asyncio

    out = asyncio.run(saved_card(cards, [refused, conditions], CTX, None, "cor_x"))  # type: ignore[arg-type]
    assert out is None and cards.asked == []
