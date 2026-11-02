"""WA-135: an attendance-sheet photo in v3 (the gap left by WA-124: "read as words only").

Root cause: the vision step already transcribes every row of a sheet (``workers`` JSON), but the
SOP told v3 only about bill photos, and every entry v3 prepared was recorded as typed text
(``recorded_via`` / ``source`` fixed to ``whatsapp_text``), so a sheet or a voice note showed in
the dashboard as typed.

Class: every tool with a fixed channel value (attendance ``recorded_via``, work ``source``), every
way in (typed, voice, photo, document). Guard: a fixed value that is not a channel (the expense's
``source: whatsapp``) is untouched, and a typed message is still ``whatsapp_text``.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi import Depends, FastAPI
from pydantic import BaseModel
from tests.agent_api.standin import ACTOR, PROJECT, SITE, stand_in_api
from tests.agent_api.test_api_agent_124 import CTX, _message, _service, _stand_in_tools  # noqa: F401 (autouse)

from agent_api import whatsapp as wa
from agent_api.agent import SOP, ApiAgent, confirm
from agent_api.client import ApiClient
from agent_api.tools import ALLOWED, CONFIRM_ARG, Allowed, build_tools
from mesiri.domains.shared.auth import get_current_user
from mesiri_ai.fakes import FakeToolCallingProvider
from mesiri_contracts.assistant.enums import InputModality


class _Line(BaseModel):
    worker_name: str | None = None
    trade: str | None = None
    headcount: int = 1


class _Attendance(BaseModel):
    project_id: uuid.UUID
    site_id: uuid.UUID
    occurred_date: str
    lines: list[_Line]
    recorded_via: str = "dashboard"


class _Expense(BaseModel):
    project_id: uuid.UUID
    amount: float
    occurred_date: str
    source: str = "web"


def _api(posted: list[tuple[str, dict]]) -> FastAPI:
    app = stand_in_api([])

    @app.post("/labour/attendance")
    async def attendance(body: _Attendance, jwt: dict = Depends(get_current_user)):
        posted.append(("attendance", body.model_dump()))
        return {"id": str(uuid.uuid4())}

    @app.post("/expenses")
    async def expense(body: _Expense, jwt: dict = Depends(get_current_user)):
        posted.append(("expense", body.model_dump()))
        return {"id": str(uuid.uuid4())}

    return app


def _tools(app: FastAPI) -> dict:
    real = next(a for a in ALLOWED if a.name == "record_attendance")
    expense = Allowed("record_expense", "POST", "/expenses", "Prepare an expense.",
                      hide=("source",), fixed=(("source", "whatsapp"),))
    return build_tools(app.openapi(), (real, expense))


SHEET = {"project_id": PROJECT, "site_id": SITE, "occurred_date": "2026-11-02", CONFIRM_ARG: "Attendance, 3 lines",
         "lines": [{"worker_name": "Ravi", "trade": "mason", "headcount": 1},
                   {"worker_name": "Suresh", "trade": "helper", "headcount": 1},
                   {"trade": "helper", "headcount": 1}]}


async def _prepared_and_saved(channel: str | None, calls: list) -> list[tuple[str, dict]]:
    posted: list[tuple[str, dict]] = []
    app = _api(posted)
    model = FakeToolCallingProvider([calls, "Ready. Tap Save."])
    client = ApiClient(ACTOR, app=app)
    try:
        kwargs = {"channel": channel} if channel else {}
        turn = await ApiAgent(model, _tools(app)).run(client, "(sent a photo)\nWhat the photo shows: sheet", **kwargs)
        assert posted == []  # nothing before Save
        await confirm(client, turn.pending)
    finally:
        await client.close()
    return posted


async def test_a_sheet_photo_is_one_attendance_report_recorded_as_a_photo() -> None:
    posted = await _prepared_and_saved("whatsapp_image", [("record_attendance", SHEET)])
    ((kind, body),) = posted
    assert kind == "attendance" and body["recorded_via"] == "whatsapp_image"
    assert [line["worker_name"] for line in body["lines"]] == ["Ravi", "Suresh", None]


@pytest.mark.parametrize(("channel", "expected"), [
    ("whatsapp_voice", "whatsapp_voice"),
    (None, "whatsapp_text"),             # guard: typed stays typed
    ("something_else", "whatsapp_text"),  # an unknown channel never reaches the API
])
async def test_every_way_in_is_recorded_as_itself(channel, expected) -> None:
    posted = await _prepared_and_saved(channel, [("record_attendance", SHEET)])
    assert posted[0][1]["recorded_via"] == expected


async def test_guard_a_fixed_value_that_is_not_a_channel_is_untouched() -> None:
    posted = await _prepared_and_saved("whatsapp_image", [("record_expense", {
        "project_id": PROJECT, "amount": 500, "occurred_date": "2026-11-02", CONFIRM_ARG: "₹500"})])
    assert posted[0][1]["source"] == "whatsapp"


@pytest.mark.parametrize(("modality", "expected"), [
    (InputModality.IMAGE, "whatsapp_image"), (InputModality.DOCUMENT, "whatsapp_image"),
    (InputModality.VOICE, "whatsapp_voice"), (InputModality.TEXT, "whatsapp_text"),
])
def test_the_channel_comes_from_how_the_message_came(modality, expected) -> None:
    assert wa._channel(_message("x", modality=modality)) == expected


async def test_the_whatsapp_side_passes_the_photo_channel_to_the_agent(monkeypatch) -> None:
    seen: dict[str, Any] = {}
    real_run = ApiAgent.run

    async def spy(self, client, text, **kwargs):  # noqa: ANN001, ANN003, ANN202
        seen.update(kwargs)
        return await real_run(self, client, text, **kwargs)

    monkeypatch.setattr(ApiAgent, "run", spy)

    async def describe(message: Any, hint: str | None = None) -> str:
        return 'Attendance sheet (workers: [{"name": "Ravi", "trade": "mason", "headcount": 1}])'

    service, _ = _service(FakeToolCallingProvider(["1 line ready."]), describe=describe)
    assert await service.handle(_message(None, modality=InputModality.IMAGE, key="media/w/2"), CTX)
    assert seen["channel"] == "whatsapp_image"


def test_the_sop_says_how_to_read_a_sheet() -> None:
    assert "attendance sheet" in SOP and "record_attendance" in SOP
    assert 'never a person named "?"' in SOP
