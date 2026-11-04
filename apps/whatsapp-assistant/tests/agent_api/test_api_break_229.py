"""[229] break tests: other wordings, Malayalam / Hindi / Manglish model prose, the Save tap after a question,
the same missing-date mistake in another tool, one guard."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from fastapi import Depends
from pydantic import BaseModel
from tests.agent_api.standin import BAG, CEMENT, SITE, stand_in_api
from tests.agent_api.test_api_agent_124 import CTX, _message, _service
from tests.agent_api.test_api_three_flow_229 import (
    BASE,
    CEMENT_CALL,
    LABOUR,
    TODAY,
    WORK,
    _Att,
    _Work,
)

from agent_api import whatsapp as wa
from agent_api.tools import ALLOWED, CONFIRM_ARG
from mesiri.domains.shared.auth import get_current_user
from mesiri_ai.fakes import FakeToolCallingProvider
from runtime.agent.wording import say

NAMES = {"record_receipt", "record_attendance", "record_work", "record_usage", "list_projects", "list_sites",
         "search_materials", "list_units"}


@pytest.fixture(autouse=True)
def _tools(monkeypatch):
    from agent_api import tools as tools_mod

    real = tools_mod.build_tools
    monkeypatch.setattr(wa, "build_tools", lambda o: real(o, tuple(a for a in ALLOWED if a.name in NAMES)))


class _Out(BaseModel):
    project_id: uuid.UUID
    site_id: uuid.UUID | None = None
    material_id: uuid.UUID
    unit_id: uuid.UUID
    quantity: float
    occurred_date: dt.date


def _app(posted: list):
    app = stand_in_api([])

    @app.post("/labour/attendance", status_code=201)
    async def att(body: _Att, jwt: dict = Depends(get_current_user)):
        posted.append(("attendance", body.model_dump()))
        return {"id": str(uuid.uuid4())}

    @app.post("/progress/activities", status_code=201)
    async def work(body: _Work, jwt: dict = Depends(get_current_user)):
        posted.append(("work", body.model_dump()))
        return {"id": str(uuid.uuid4())}

    @app.post("/materials/outflows", status_code=201)
    async def outflow(body: _Out, jwt: dict = Depends(get_current_user)):
        posted.append(("outflow", body.model_dump()))
        return {"id": str(uuid.uuid4())}

    return app


async def test_malayalam_script_prose_telling_to_press_save_is_cut_and_the_code_line_is_drawn_once() -> None:
    prose = "മൂന്നും തയ്യാറാണ്. ഇത് സേവ് ചെയ്യാൻ Save ബട്ടൺ അമർത്തുക"
    model = FakeToolCallingProvider([[CEMENT_CALL, LABOUR, WORK], prose])
    service, sent = _service(model, app=_app([]))
    await service.handle(_message("സിമന്റ് 20 ബാഗ് വന്നു, 20 മേസൺ പണി, സ്ലാബ് പണി കഴിഞ്ഞു"), CTX)
    reply = sent[-1]
    assert "\n3. " in reply.text and [b.title for b in reply.buttons] == ["Save", "Cancel"]
    assert "ഇത് സേവ് ചെയ്യാൻ" not in reply.text  # the model's sentence is cut
    assert reply.text.count(say("api.press_save", "malayalam")) == 1


async def test_hindi_prose_with_a_held_list_has_one_save_line_in_hindi() -> None:
    prose = "तीनों तैयार हैं। सेव करने के लिए Save बटन दबाइए।"
    model = FakeToolCallingProvider([[CEMENT_CALL, LABOUR, WORK], prose])
    service, sent = _service(model, app=_app([]))
    await service.handle(_message("20 बोरी सीमेंट आया, 20 मिस्त्री ने काम किया, स्लैब का काम हो गया"), CTX)
    reply = sent[-1]
    assert [b.title for b in reply.buttons] == ["Save", "Cancel"]
    assert "सेव करने के लिए Save बटन" not in reply.text
    assert reply.text.count(say("api.press_save", "hindi")) == 1


@pytest.mark.parametrize("prose,message,language", [
    ("ഇത് സേവ് ചെയ്യാൻ Save ബട്ടൺ അമർത്തുക", "സിമന്റ് 20 ബാഗ് വന്നു", "malayalam"),
    ("Sab ready hai, Save dabao.", "aaj 20 bag cement site par aaya hai, kal ka kaam ho gaya", "hinglish"),
    ("Ellaam ready aanu, Save button click cheyyu", "20 bag cement vannu", "manglish"),
    ("All set. Tap on the Save button below.", "20 bag cement came", "english"),
])
async def test_prose_claiming_save_with_nothing_held_says_nothing_is_ready_in_their_language(
        prose: str, message: str, language: str) -> None:
    model = FakeToolCallingProvider([prose, prose])
    service, sent = _service(model, app=_app([]))
    await service.handle(_message(message), CTX)
    reply = sent[-1]
    assert not reply.buttons
    assert reply.text == say("api.nothing_held", language)


async def test_the_save_tap_after_a_question_saves_the_held_lines_at_the_kept_site_with_today() -> None:
    posted: list = []
    ask = ("ask", {"question": "Which trade?", "options": ["Mason", "Helper"]})
    model = FakeToolCallingProvider([[CEMENT_CALL, WORK, ask], "Two lines are ready, press Save. Which trade?"])
    service, sent = _service(model, app=_app(posted))
    await service.handle(_message("cement vannu, slab kazhinju, 5 pani"), CTX)
    reply = sent[-1]
    assert reply.text.lower().count("press save") == 0
    save = next(b for b in reply.buttons if b.title == "Save")
    await service.handle(_message("Save", tap=save.id), CTX)
    assert "work" in dict(posted)
    work = dict(posted)["work"]
    assert str(work["site_id"]) == SITE and work["occurred_date"].isoformat() == TODAY


async def test_the_same_mistake_in_another_tool_usage_without_a_date_gets_today() -> None:
    posted: list = []
    usage = ("record_usage", {**BASE, "material_id": CEMENT, "unit_id": BAG, "quantity": 5,
                              CONFIRM_ARG: "5 bag Cement used at Tower A"})
    model = FakeToolCallingProvider([[usage], "Ready."])
    service, sent = _service(model, app=_app(posted))
    await service.handle(_message("5 bag cement upayogichu"), CTX)
    assert [b.title for b in sent[-1].buttons] == ["Save", "Cancel"]
    await service.handle(_message("Save", tap=sent[-1].buttons[0].id), CTX)
    assert posted and posted[0][1]["occurred_date"].isoformat() == TODAY


async def test_guard_one_ready_line_with_model_prose_that_says_save_keeps_a_single_tap_line() -> None:
    model = FakeToolCallingProvider([[CEMENT_CALL], "20 bag Cement is ready. Please tap Save to confirm."])
    service, sent = _service(model, app=_app([]))
    await service.handle(_message("20 bag cement came"), CTX)
    reply = sent[-1]
    assert [b.title for b in reply.buttons] == ["Save", "Cancel"]
    assert "Please tap Save" not in reply.text and reply.text.count(say("api.press_save", "english")) == 1


async def test_hinglish_prose_with_a_held_list_has_one_save_line() -> None:
    model = FakeToolCallingProvider([[CEMENT_CALL, WORK], "Dono ready hai. Save dabao."])
    service, sent = _service(model, app=_app([]))
    await service.handle(_message("20 bag cement aaya, slab ka kaam ho gaya"), CTX)
    reply = sent[-1]
    assert [b.title for b in reply.buttons] == ["Save", "Cancel"]
    assert "Save dabao." not in reply.text.replace(say("api.press_save", "hinglish"), "")
