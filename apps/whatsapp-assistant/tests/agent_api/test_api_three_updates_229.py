"""[229] (4 Nov, Ilan, Paraclette): one voice note with three updates (cement, masons, slab) got "tap Save" and no Save
button: the model asked a date for the labour, prepared nothing, and the reply still told him to press Save.

ACCEPTANCE (TM-63): the person's whole journey, through Save, asserting what was saved:
- voice note -> three lines held in the first turn (labour date filled by the code), Save sent with them;
- Save -> cement 20 bags, 5 masons dated today, slab work done, all at Tower A, all in one Save;
- each number stays with its own item (20 bags cement + 5 masons, never 20 masons);
- a date that was said ("innale") is used as said;
- "tap Save" is never said with nothing held, and the model's own copy of that line is cut.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi import Depends, FastAPI
from pydantic import BaseModel
from tests.agent_api.standin import BAG, CEMENT, PROJECT, SITE, stand_in_api
from tests.agent_api.test_api_whatsapp_119 import CTX, Harness, _message

from agent_api import whatsapp as wa
from agent_api.agent import ApiAgent, number_clash
from agent_api.client import ApiClient
from agent_api.tools import ALLOWED, CONFIRM_ARG, build_tools
from mesiri.domains.shared.auth import get_current_user
from mesiri_ai.fakes import FakeToolCallingProvider
from runtime.agent.wording import LANGUAGES, say

TOOLS = {"list_projects", "list_sites", "search_materials", "list_units", "record_receipt",
         "record_attendance", "record_work"}
TODAY = __import__("mesiri.domains.organizations.settings", fromlist=["working_day"]).working_day(
    dt.datetime.now(ZoneInfo("Asia/Kolkata"))).isoformat()  # fix 2: the working day
VOICE = "20 bag cement Tower A-il vannu, 5 mason pani eduthu, slab pani kazhinju"


class Line(BaseModel):
    trade: str | None = None
    headcount: int | None = None


class Attendance(BaseModel):
    project_id: uuid.UUID
    site_id: uuid.UUID
    occurred_date: dt.date
    lines: list[Line]


class Inflow(BaseModel):
    project_id: uuid.UUID
    site_id: uuid.UUID | None = None
    material_id: uuid.UUID
    unit_id: uuid.UUID
    quantity: float
    occurred_date: dt.date


class Work(BaseModel):
    project_id: uuid.UUID
    site_id: uuid.UUID
    activity_date: dt.date
    work_type: str | None = None
    narrative: str | None = None


def _api(posted: list[tuple[str, dict]]) -> FastAPI:
    app = stand_in_api([])
    original = [r for r in app.router.routes if getattr(r, "path", "") == "/materials/inflows" and "POST" in getattr(r, "methods", ())]
    for r in original:
        app.router.routes.remove(r)

    @app.post("/materials/inflows", status_code=201)
    async def inflow(body: Inflow, jwt: dict = Depends(get_current_user)):
        posted.append(("receipt", body.model_dump(mode="json")))
        return {"id": str(uuid.uuid4())}

    @app.post("/labour/attendance", status_code=201)
    async def attendance(body: Attendance, jwt: dict = Depends(get_current_user)):
        posted.append(("labour", body.model_dump(mode="json")))
        return {"id": str(uuid.uuid4())}

    @app.post("/progress/activities", status_code=201)
    async def work(body: Work, jwt: dict = Depends(get_current_user)):
        posted.append(("work", body.model_dump(mode="json")))
        return {"id": str(uuid.uuid4())}

    return app


@pytest.fixture
def posted(monkeypatch) -> list:
    """What reached the API on Save (the stand-in API records the bodies)."""
    from tests.agent_api import test_api_whatsapp_119 as base

    out: list = []
    monkeypatch.setattr(base, "stand_in_api", lambda seen, **kw: _api(out))
    return out


@pytest.fixture(autouse=True)
def _tools(monkeypatch):
    from agent_api import tools as tools_mod

    real = tools_mod.build_tools
    monkeypatch.setattr(wa, "build_tools", lambda openapi: real(openapi, tuple(a for a in tools_mod.ALLOWED if a.name in TOOLS)))


def _receipt(qty: int = 20) -> tuple[str, dict]:
    return ("record_receipt", {"project_id": PROJECT, "site_id": SITE, "material_id": CEMENT, "unit_id": BAG,
                               "quantity": qty, "occurred_date": TODAY, CONFIRM_ARG: f"{qty} bags cement, Tower A"})


def _labour(count: int, **extra: Any) -> tuple[str, dict]:
    return ("record_attendance", {"project_id": PROJECT, "site_id": SITE, "lines": [{"trade": "mason", "headcount": count}],
                                  CONFIRM_ARG: f"{count} masons, Tower A", **extra})


def _slab(**extra: Any) -> tuple[str, dict]:
    return ("record_work", {"project_id": PROJECT, "site_id": SITE, "work_type": "slab", "narrative": "Slab work done",
                            CONFIRM_ARG: "Slab work done, Tower A", **extra})


def _harness(model: Any, posted: list) -> Harness:
    return Harness(model, transcript=VOICE)


def _model(*rounds: Any) -> FakeToolCallingProvider:
    prelude = [[("list_projects", {}), ("search_materials", {"search": "cement"}), ("list_units", {})]]
    return FakeToolCallingProvider([*prelude, *rounds])


async def test_the_whole_journey_three_updates_one_save(posted: list) -> None:
    # The model leaves the dates out (it asked for one in production) and writes its own "press Save" line.
    h = _harness(_model([_receipt(20), _labour(5), _slab()],
                        "20 bag cement ready. 5 mason ready. Slab ready.\n\nIthu save cheyyanayi \"Save\" button amarthuka."), posted)
    voice = _message(None, modality=wa.InputModality.VOICE)
    assert await h.service.handle(voice, CTX)
    reply = h.sent[-1]
    assert [b.title for b in reply.buttons] == ["Save", "✏️ Edit", "Cancel"]  # the Save button is sent with the list
    assert all(f"{i}. " in reply.text for i in (1, 2, 3))
    assert "Ithu save cheyyanayi" not in reply.text  # the model's own copy is cut
    assert reply.text.count(say("api.press_save", "manglish")) == 1  # the code's line, once (their language)
    assert posted == []  # nothing saved before Save
    save, _edit, _cancel = h.buttons()
    assert await h.service.handle(_message("Save", tap=save), CTX)
    by_kind = {k: b for k, b in posted}
    assert len(posted) == 3
    assert by_kind["receipt"]["quantity"] == 20 and by_kind["receipt"]["site_id"] == SITE
    assert by_kind["labour"]["lines"][0]["headcount"] == 5  # not the cement's 20
    assert by_kind["labour"]["occurred_date"] == TODAY and by_kind["labour"]["site_id"] == SITE
    assert by_kind["work"]["activity_date"] == TODAY and by_kind["work"]["site_id"] == SITE


async def test_a_question_for_one_line_keeps_the_others_with_save(posted: list) -> None:
    h = _harness(_model([_receipt(20), _labour(5)], [("ask", {"question": "Which work was done on the slab?"})],
                        "Two are ready. Which work was done on the slab?"), posted)
    assert await h.service.handle(_message("20 bag cement, 5 mason, slab"), CTX)
    reply = h.sent[-1]
    assert "1. 20 bags cement" in reply.text and "2. 5 masons" in reply.text
    # A question with no buttons of its own leaves Save / Cancel under the list.
    assert [b.title for b in reply.buttons] == ["Save", "✏️ Edit", "Cancel"]


async def test_a_said_date_is_used_as_said(posted: list) -> None:
    h = _harness(_model([_labour(5, occurred_date="2026-11-03")], "Ready."), posted)
    await h.service.handle(_message("innale 5 mason undayirunnu"), CTX)
    save, _edit, _ = h.buttons()
    await h.service.handle(_message("Save", tap=save), CTX)
    assert posted[0][1]["occurred_date"] == "2026-11-03"


async def test_each_number_stays_with_its_item(posted: list) -> None:
    # "aaru" = 6; the model first reuses the cement's 20, the code refuses, the model corrects itself.
    h = _harness(_model([_receipt(20), _labour(20)], [_labour(6)], "Ready."), posted)
    await h.service.handle(_message("20 bag cement, aaru mason pani eduthu"), CTX)
    save, _edit, _ = h.buttons()
    await h.service.handle(_message("Save", tap=save), CTX)
    assert {k: b for k, b in posted}["labour"]["lines"][0]["headcount"] == 6


def test_number_clash_rules() -> None:
    cement = {"quantity": 20}
    masons = {"lines": [{"headcount": 20}]}
    assert number_clash("20 bag cement, aaru mason", masons, [cement])
    assert not number_clash("20 bag cement, 20 mason", masons, [cement])  # said twice: fine
    assert not number_clash("20 bag cement, 5 mason", {"lines": [{"headcount": 5}]}, [cement])
    assert not number_clash("20 bag cement", cement, [])  # first use


async def test_tap_save_is_never_said_with_nothing_held(posted: list) -> None:
    line = "Your cement is ready. Tap Save to record it."
    h = _harness(FakeToolCallingProvider([line, line]), posted)
    await h.service.handle(_message("20 bags of cement came today"), CTX)
    reply = h.sent[-1]
    assert reply.text == wa.NOTHING_HELD and not reply.buttons


def test_the_two_lines_exist_in_every_language() -> None:
    for lang in LANGUAGES:
        assert say("api.press_save", lang) and say("api.nothing_held", lang)


def test_tools_still_build() -> None:
    assert build_tools is not None and ALLOWED and ApiAgent and ApiClient
