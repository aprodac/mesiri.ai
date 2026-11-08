"""[233] break tests: other wordings, the next step through Save, the same mistake reached another way, one guard."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from fastapi import Depends
from pydantic import BaseModel
from tests.agent_api.test_api_agent_124 import CTX, _message, _service
from tests.agent_api.test_api_refused_line_233 import BASE, LABOUR, WORDS, WORK, _app, _tools  # noqa: F401

from agent_api.agent import SAVE_READY, PendingWrite
from agent_api.fill import fill_body, missing_in_body
from agent_api.tools import CONFIRM_ARG
from mesiri.domains.shared.auth import get_current_user
from mesiri_ai.fakes import FakeToolCallingProvider


class Line(BaseModel):
    trade: str
    headcount: int


class Att(BaseModel):
    project_id: uuid.UUID
    site_id: uuid.UUID
    occurred_date: dt.date
    lines: list[Line]


def _work(line: str) -> tuple[str, dict]:
    return ("record_work", {**BASE, "work_type": "plastering", CONFIRM_ARG: line})


@pytest.mark.parametrize("line,expected", [
    # [243]: a card line in Malayalam script never becomes the narrative (test_api_english_bodies_243.py).
    ("2nd floor plastering kazhinju at Green Villa", "2nd floor plastering kazhinju"),
    ("Plastering done at Green Villa main block, 2nd floor", "Plastering done at Green Villa main block, 2nd floor"),
])
async def test_other_wordings_become_the_narrative_through_a_real_save(line, expected) -> None:
    posted: list = []
    service, sent = _service(FakeToolCallingProvider([[_work(line)], "OK."]), app=_app(posted))
    await service.handle(_message("update"), CTX)
    await service.handle(_message("Save", tap=sent[-1].buttons[0].id), CTX)
    assert dict(posted)["work"]["narrative"] == expected
    assert "❌" not in sent[-1].text


async def test_note_suffix_and_empty_words_never_make_an_empty_or_bare_site_narrative() -> None:
    out = fill_body("record_work", {}, "at Green Villa", ("Green Villa",))
    assert out.get("narrative", "x").strip()  # never "" (the API would refuse)
    assert fill_body("record_work", {}, "   ", ("Green Villa",)) == {}  # nothing to fill from: left for the API/gap check
    assert fill_body("record_work", {"narrative": "  "}, "Plastering at Green Villa", ("Green Villa",))["narrative"] == "Plastering"


async def test_next_step_after_a_dropped_line_save_again_is_not_a_resend_and_labour_still_saves() -> None:
    posted: list = []
    # the API refuses the work line for a reason the code cannot fix; labour goes through
    model = FakeToolCallingProvider([[WORK, LABOUR], "OK."])
    service, sent = _service(model, app=_app(posted, refuse_all_work="work type not allowed here"))
    await service.handle(_message(WORDS), CTX)
    card = sent[-1]
    await service.handle(_message("Save", tap=card.buttons[0].id), CTX)
    assert [k for k, _ in posted] == ["attendance"]
    assert "not saved yet" in sent[-1].text and not sent[-1].buttons
    n = len(sent)
    # the old Save button tapped again, and a typed "save": nothing is re-sent, nothing resurrected
    await service.handle(_message("Save", tap=card.buttons[0].id), CTX)
    model._script = ["Nothing to save."]
    await service.handle(_message("save"), CTX)
    assert [k for k, _ in posted] == ["attendance"]
    print([x.text for x in sent[n:]])
    assert len(sent) > n and not any("Plastering" in x.text for x in sent[n:])


async def test_save_ready_entries_tool_path_fills_a_line_held_before_the_fix() -> None:
    posted: list = []
    model = FakeToolCallingProvider([[WORK], "Ready."])
    service, sent = _service(model, app=_app(posted))
    await service.handle(_message("plastering done"), CTX)
    # simulate a line held before the fix: strip the narrative from what Redis holds
    key = service._key(CTX)
    state = await service._redis.get_json(key)
    for e in state["pending"]:
        e["body"].pop("narrative", None)
    await service._redis.set_json(key, state, ttl_seconds=600)
    model._script = [[(SAVE_READY, {})], "Done."]
    await service.handle(_message("yes please save it"), CTX)
    assert [k for k, _ in posted] == ["work"], sent[-1].text
    assert posted[0][1]["narrative"] == "Plastering done on 2nd floor"
    state = await service._redis.get_json(key) or {}
    assert not state.get("pending")


async def test_issue_with_missing_nested_field_is_not_held_and_complete_body_is_unchanged() -> None:
    posted: list = []
    app = _app(posted)
    app.router.routes = [r for r in app.router.routes if getattr(r, "path", "") != "/labour/attendance"]

    @app.post("/labour/attendance", status_code=201)
    async def att(body: Att, jwt: dict = Depends(get_current_user)):
        posted.append(("attendance", body.model_dump()))
        return {"id": str(uuid.uuid4())}

    app.openapi_schema = None
    bad = ("record_attendance", {**BASE, "lines": [{"headcount": 6}], CONFIRM_ARG: "6 workers at Green Villa"})
    service, sent = _service(FakeToolCallingProvider([[bad], "Which trade?"]), app=app)
    await service.handle(_message("6 workers today"), CTX)
    state = await service._redis.get_json(service._key(CTX)) or {}
    assert not state.get("pending")  # not held, so it cannot be refused and carried
    assert not any(s.buttons for s in sent)
    issue = ("report_issue", {**BASE, "issue_type": "OTHER", "severity": "HIGH", CONFIRM_ARG: "Water tank leak at Green Villa"})
    model = FakeToolCallingProvider([[issue], "OK."])
    service, sent = _service(model, app=_app(posted))
    await service.handle(_message("water tank leak"), CTX)
    await service.handle(_message("Save", tap=sent[-1].buttons[0].id), CTX)
    kinds = [k for k, _ in posted]
    assert kinds == ["issue"] and "narrative" not in {k for k, v in posted[0][1].items() if v and k == "narrative"}


async def test_guard_quantities_kept_labour_saves_as_before_and_missing_check_ignores_complete_rows() -> None:
    posted: list = []
    q = ("record_work", {**BASE, "quantities": [{"quantity": 200, "unit": "sqft"}], CONFIRM_ARG: "200 sqft plastering at Green Villa"})
    service, sent = _service(FakeToolCallingProvider([[q, LABOUR], "OK."]), app=_app(posted))
    await service.handle(_message("200 sqft plastering, 6 masons"), CTX)
    await service.handle(_message("Save", tap=sent[-1].buttons[0].id), CTX)
    by = dict(posted)
    assert not by["work"]["narrative"] and by["work"]["quantities"][0]["quantity"] == 200
    assert by["attendance"]["lines"][0]["headcount"] == 6
    assert missing_in_body({"properties": {"lines": {"type": "array", "items": {"required": ["trade"]}}}},
                           {"lines": [{"trade": "mason"}], "note": [1, 2]}) == []
    assert PendingWrite  # imported for symmetry
