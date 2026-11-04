"""[233] (4 Nov, asus, test company): "Green Villa: plastering done on 2nd floor, 6 masons worked today" -> Save ->
"activity must have a narrative or at least one quantity"; the refused line then came back on every card.
Journey: the words -> card -> Save tap -> what the API got -> the next message and card.
Class: a write tool body with an either/or field the code can fill; a line the API refuses must not ride on."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from tests.agent_api.standin import PROJECT, SITE, stand_in_api
from tests.agent_api.test_api_agent_124 import CTX, _message, _service

from agent_api import whatsapp as wa
from agent_api.fill import fill_body, missing_in_body
from agent_api.tools import ALLOWED, CONFIRM_ARG
from mesiri.domains.shared.auth import get_current_user
from mesiri_ai.fakes import FakeToolCallingProvider

NAMES = {"record_attendance", "record_work", "list_projects", "list_sites", "report_issue"}


class _Q(BaseModel):
    quantity: float
    unit: str


class _Work(BaseModel):
    project_id: uuid.UUID
    site_id: uuid.UUID
    activity_date: dt.date
    work_type: str | None = None
    narrative: str | None = None
    quantities: list[_Q] = []
    source: str = "dashboard"


class _Issue(BaseModel):
    project_id: uuid.UUID
    site_id: uuid.UUID
    issue_type: str
    severity: str
    narrative: str | None = None


class _Att(BaseModel):
    project_id: uuid.UUID
    site_id: uuid.UUID
    occurred_date: dt.date
    lines: list[dict]
    recorded_via: str = "dashboard"


@pytest.fixture(autouse=True)
def _tools(monkeypatch):
    from agent_api import tools as tools_mod

    real = tools_mod.build_tools
    monkeypatch.setattr(wa, "build_tools", lambda o: real(o, tuple(a for a in ALLOWED if a.name in NAMES)))


def _app(posted: list, refuse_all_work: str | None = None) -> FastAPI:
    app = stand_in_api([])

    @app.post("/progress/activities", status_code=201)
    async def work(body: _Work, jwt: dict = Depends(get_current_user)):
        if refuse_all_work:
            raise HTTPException(422, refuse_all_work)
        if not (body.narrative or "").strip() and not body.quantities:  # backend validation.py, unchanged
            raise HTTPException(422, "activity must have a narrative or at least one quantity")
        posted.append(("work", body.model_dump()))
        return {"id": str(uuid.uuid4())}

    @app.post("/progress/issues", status_code=201)
    async def issue(body: _Issue, jwt: dict = Depends(get_current_user)):
        posted.append(("issue", body.model_dump()))
        return {"id": str(uuid.uuid4())}

    @app.post("/labour/attendance", status_code=201)
    async def att(body: _Att, jwt: dict = Depends(get_current_user)):
        posted.append(("attendance", body.model_dump()))
        return {"id": str(uuid.uuid4())}

    return app


BASE = {"project_id": PROJECT, "site_id": SITE}
WORK = ("record_work", {**BASE, "work_type": "plastering", CONFIRM_ARG: "Plastering done on 2nd floor at Green Villa"})
LABOUR = ("record_attendance", {**BASE, "lines": [{"trade": "mason", "headcount": 6}],
                                CONFIRM_ARG: "6 masons worked today at Green Villa"})
WORDS = "Green Villa: plastering done on 2nd floor, 6 masons worked today"


async def test_whole_journey_work_update_without_narrative_saves_with_their_words_and_the_labour_line() -> None:
    posted: list = []
    service, sent = _service(FakeToolCallingProvider([[WORK, LABOUR], "OK."]), app=_app(posted))
    await service.handle(_message(WORDS), CTX)
    card = sent[-1]
    assert "\n1. " in card.text and "\n2. " in card.text
    assert "Tap *Save*" in card.text and "amarthuka" not in card.text  # English conversation, English Save line
    await service.handle(_message("Save", tap=card.buttons[0].id), CTX)
    by = dict(posted)
    assert by["work"]["narrative"] == "Plastering done on 2nd floor"  # their words, without the site
    assert by["work"]["activity_date"] == dt.datetime.now(dt.UTC).astimezone(
        __import__("zoneinfo").ZoneInfo("Asia/Kolkata")).date()
    assert by["attendance"]["lines"][0]["headcount"] == 6
    assert "❌" not in sent[-1].text and not sent[-1].buttons


async def test_a_line_held_before_the_fix_is_filled_and_retried_in_the_same_save() -> None:
    from agent_api.agent import PendingWrite, confirm
    from agent_api.client import ApiClient

    posted: list = []
    entry = PendingWrite("record_work", "POST", "/progress/activities", {}, {
        **{k: v for k, v in BASE.items()}, "activity_date": "2026-11-04", "work_type": "plastering",
        "source": "whatsapp_text"}, "Plastering done on 2nd floor at Green Villa", "k1")
    client = ApiClient(__import__("agent_api.whatsapp", fromlist=["_actor"])._actor(CTX), app=_app(posted))
    try:
        (result,) = await confirm(client, [entry], ("Green Villa",))
    finally:
        await client.close()
    assert result.ok and posted[0][1]["narrative"] == "Plastering done on 2nd floor"


async def test_guard_quantities_are_kept_and_no_narrative_is_invented() -> None:
    body = {"quantities": [{"quantity": 200, "unit": "sqft"}], "work_type": "plastering"}
    assert fill_body("record_work", body, "200 sqft plastering at Green Villa", ("Green Villa",)) is body
    assert fill_body("record_attendance", {"lines": []}, "6 masons", ()) == {"lines": []}
    having = {"narrative": "Their narrative"}
    assert fill_body("record_work", having, "x", ()) is having


def test_site_is_cut_only_when_it_is_a_known_place() -> None:
    out = fill_body("record_work", {}, "Plastering at the back at Green Villa · 📍 *X* (not Y)", ("Green Villa, Kakkanad",))
    assert out["narrative"] == "Plastering at the back"
    out = fill_body("record_work", {}, "Plastering done at 2nd floor", ("Green Villa",))
    assert out["narrative"] == "Plastering done at 2nd floor"


def test_nested_required_fields_are_read_from_the_tools_own_schema() -> None:
    params = {"properties": {"lines": {"type": "array", "items": {"type": "object", "required": ["trade"]}}}}
    assert missing_in_body(params, {"lines": [{"trade": "mason"}, {"headcount": 2}]}) == ["lines[2].trade"]
    assert missing_in_body(params, {"lines": [{"trade": "mason"}]}) == []


async def test_a_refused_line_is_dropped_with_a_plain_sentence_and_never_on_the_next_card() -> None:
    posted: list = []
    leak = ("report_issue", {**BASE, "issue_type": "OTHER", "severity": "HIGH", CONFIRM_ARG: "Water tank leak at Green Villa"})
    model = FakeToolCallingProvider([[WORK], "OK."])
    service, sent = _service(model, app=_app(posted, refuse_all_work="stock is too low for this"))
    await service.handle(_message("plastering done on 2nd floor"), CTX)
    await service.handle(_message("Save", tap=sent[-1].buttons[0].id), CTX)
    refused = sent[-1]
    assert "❌" in refused.text and "Send them again" in refused.text and not refused.buttons
    model._script = [[leak], "OK."]  # the model's next turn
    await service.handle(_message("water tank leak at Green Villa"), CTX)
    card = sent[-1]
    assert "Plastering" not in card.text  # the refused line is not on the next card
    assert "Water tank leak" in card.text


async def test_a_transient_failure_keeps_the_line_once_then_drops_it() -> None:
    from agent_api.agent import PendingWrite, WriteResult

    e = PendingWrite("record_work", "POST", "/p", {}, {}, "x", "key-1")
    state: dict = {}
    kept, dropped = wa._refused_to_keep([WriteResult(e, 503, {"detail": "down"})], state)
    assert kept == [e] and not dropped
    kept, dropped = wa._refused_to_keep([WriteResult(e, 503, {"detail": "down"})], state)
    assert kept == [] and dropped


async def test_guard_in_a_chosen_language_the_save_line_stays_in_it() -> None:
    service, sent = _service(FakeToolCallingProvider([[LABOUR], "OK."]), app=_app([]))
    await service.handle(_message("6 mason pani eduthu"), CTX)
    assert "amarthuka" in sent[-1].text
