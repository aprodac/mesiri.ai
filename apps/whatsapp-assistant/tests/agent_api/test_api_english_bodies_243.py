"""[243] (4 Nov, Ilan, Aprodac, 20:56, cor_bd6fd016803c42de953613cd600e15ab / cor_9270c3a624bf425e86aa637ad744f040): a
Malayalam voice note; the model took "സിമന്റ്" as a new material instead of the listed Cement, the attendance line was
in Malayalam, and "ഇനി മംഗ്ലീഷിൽ മറുപടി നൽകും" sat on the card as a line to save.

Mesiri's records are English (matching, search, the client's report). The code checks every held body: a free-text
field in another script is sent back to the model once in the same turn ("write body fields in English"), then asked
about; never held, never saved. The card line and the reply stay in their language. A material word is matched in
English to the listed record. A reply-language choice is set at once, never a card line.
Journey: their words -> card (their language) -> Save tap -> what the API got."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from fastapi import Depends, FastAPI, Header
from pydantic import BaseModel
from tests.agent_api.standin import ACTOR, PROJECT, SITE
from tests.agent_api.test_api_agent_124 import CTX, _message, _service
from tests.agent_api.test_api_refused_line_233 import BASE, _app

from agent_api import whatsapp as wa
from agent_api.agent import ApiAgent, confirm
from agent_api.client import ApiClient
from agent_api.fill import fill_body, not_english, other_script
from agent_api.tools import ALLOWED, CONFIRM_ARG, MATERIAL_SAID, build_tools
from mesiri.domains.shared.auth import get_current_user
from mesiri_ai.fakes import FakeToolCallingProvider

NAMES = {"record_attendance", "record_work", "list_projects", "list_sites", "report_issue"}
ML_LINE = "ഗ്രീൻ വില്ലയിൽ ഇന്ന് 6 മേസൺ, 10 ഇലക്ട്രീഷ്യൻ"


@pytest.fixture(autouse=True)
def _tools(monkeypatch):
    from agent_api import tools as tools_mod

    real = tools_mod.build_tools
    monkeypatch.setattr(wa, "build_tools", lambda o: real(o, tuple(a for a in ALLOWED if a.name in NAMES)))


def _labour(trade_1: str, trade_2: str) -> tuple[str, dict]:
    return ("record_attendance", {**BASE, "lines": [{"trade": trade_1, "headcount": 6}, {"trade": trade_2, "headcount": 10}],
                                  CONFIRM_ARG: "ഗ്രീൻ വില്ല: 6 മേസൺ, 10 ഇലക്ട്രീഷ്യൻ"})


def _work(narrative: str) -> tuple[str, dict]:
    return ("record_work", {**BASE, "work_type": "plastering", "narrative": narrative,
                            CONFIRM_ARG: "രണ്ടാം നിലയിൽ പ്ലാസ്റ്ററിംഗ് കഴിഞ്ഞു"})


def _issue(narrative: str) -> tuple[str, dict]:
    return ("report_issue", {**BASE, "issue_type": "OTHER", "severity": "HIGH", "narrative": narrative,
                             CONFIRM_ARG: "വാട്ടർ ടാങ്ക് ചോരുന്നു"})


async def _journey(script: list, words: str) -> tuple[list, list]:
    posted: list = []
    service, sent = _service(FakeToolCallingProvider(script), app=_app(posted))
    await service.handle(_message(words), CTX)
    card = sent[-1]
    if card.buttons:
        await service.handle(_message("Save", tap=card.buttons[0].id), CTX)
    return posted, sent


def _no_other_script(posted: list) -> None:
    for _, body in posted:
        text = [v for v in body.values() if isinstance(v, str)] + [
            v for ln in body.get("lines") or [] for v in ln.values() if isinstance(v, str)]
        assert not any(other_script(v) for v in text), body


async def test_whole_journey_malayalam_labour_saves_english_trades_and_the_card_stays_malayalam() -> None:
    script = [[_labour("മേസൺ", "ഇലക്ട്രീഷ്യൻ")], [_labour("mason", "electrician")], "ശരി."]
    posted, sent = await _journey(script, ML_LINE)
    card = sent[0]
    assert "മേസൺ" in card.text  # the card line in their language
    (kind, body), = posted
    assert kind == "attendance" and [ln["trade"] for ln in body["lines"]] == ["mason", "electrician"]
    assert [ln["headcount"] for ln in body["lines"]] == [6, 10]  # quantities untouched
    _no_other_script(posted)


async def test_whole_journey_malayalam_work_update_saves_an_english_narrative() -> None:
    script = [[_work("രണ്ടാം നിലയിൽ പ്ലാസ്റ്ററിംഗ് കഴിഞ്ഞു")], [_work("Plastering done on 2nd floor")], "ശരി."]
    posted, sent = await _journey(script, "രണ്ടാം നിലയിൽ പ്ലാസ്റ്ററിംഗ് കഴിഞ്ഞു")
    assert "പ്ലാസ്റ്ററിംഗ്" in sent[0].text
    assert dict(posted)["work"]["narrative"] == "Plastering done on 2nd floor"


async def test_sibling_malayalam_issue_saves_in_english() -> None:
    script = [[_issue("വാട്ടർ ടാങ്ക് ചോരുന്നു")], [_issue("Water tank is leaking")], "ശരി."]
    posted, _ = await _journey(script, "വാട്ടർ ടാങ്ക് ചോരുന്നു")
    assert dict(posted)["issue"]["narrative"] == "Water tank is leaking"


async def test_still_not_english_after_one_retry_is_held_never_asked_of_the_person() -> None:
    # [248] replaces [243]'s "ask the person what it is called in English": translating is never the person's job.
    # With no translation route (this stand-in model has none) and the model still in Malayalam, the line is held.
    w = _work("പ്ലാസ്റ്ററിംഗ് കഴിഞ്ഞു")
    posted, sent = await _journey([[w], [w], "റെഡി."], "പ്ലാസ്റ്ററിംഗ് കഴിഞ്ഞു")
    assert len(posted) == 1 and "English" not in sent[0].text


async def test_a_work_update_without_narrative_never_takes_a_malayalam_summary() -> None:
    assert fill_body("record_work", {}, "പ്ലാസ്റ്ററിംഗ് കഴിഞ്ഞു", ()) == {}


async def test_guard_english_and_real_names_go_through_unchanged() -> None:
    posted, _ = await _journey([[_work("Plastering done at Asus garden, Sree Durga Traders")], "Ready."],
                               "plastering kazhinju Asus garden")
    assert dict(posted)["work"]["narrative"] == "Plastering done at Asus garden, Sree Durga Traders"


def test_ids_enums_and_dates_are_not_free_text() -> None:
    params = {"properties": {"site_id": {"type": "string"}, "severity": {"type": "string", "enum": ["HIGH"]},
                             "day": {"type": "string", "format": "date"}, "notes": {"type": "string"},
                             "lines": {"type": "array", "items": {"properties": {"trade": {"type": "string"}}}}}}
    body = {"site_id": "സൈറ്റ്", "severity": "ഉയർന്ന", "day": "ഇന്ന്", "notes": "₹500 ok 👍",
            "lines": [{"trade": "mason"}, {"trade": "മേസൺ"}]}
    assert not_english(params, body) == ["lines[2].trade"]
    assert not_english(params, {"notes": "हिंदी"}) == ["notes"] and not_english(params, {"notes": "تست"}) == ["notes"]


# -- materials: matched in English to the listed record ---------------------------------------------------------

CEMENT, UNIT = str(uuid.uuid4()), str(uuid.uuid4())
CATALOG = [{"id": CEMENT, "name": "Cement", "aliases": []}]


class _Inflow(BaseModel):
    project_id: uuid.UUID
    site_id: uuid.UUID | None = None
    material_id: uuid.UUID
    unit_id: uuid.UUID
    quantity: float
    occurred_date: str


class _New(BaseModel):
    name: str
    default_unit_id: str | None = None


class _Language(BaseModel):
    reply_language: str


def _materials_api(saved: list) -> FastAPI:
    app = FastAPI()

    @app.get("/materials")
    async def materials(limit: int = 50, is_active: bool | None = None, jwt: dict = Depends(get_current_user)):
        return {"items": CATALOG, "total": 1}

    @app.get("/materials/units-of-measure")
    async def units(jwt: dict = Depends(get_current_user)):
        return {"items": [{"id": UNIT, "code": "bag", "display_name": "Bags", "is_active": True}]}

    @app.post("/materials/inflows", status_code=201)
    async def inflow(body: _Inflow, jwt: dict = Depends(get_current_user),
                     idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
        saved.append(("receipt", str(body.material_id), body.quantity))
        return {"id": str(uuid.uuid4())}

    @app.post("/materials", status_code=201)
    async def new(body: _New, jwt: dict = Depends(get_current_user)):
        saved.append(("material", body.name))
        return {"id": str(uuid.uuid4())}

    @app.put("/me/reply-language")
    async def language(body: _Language, jwt: dict = Depends(get_current_user)):
        saved.append(("language", body.reply_language))
        return {"reply_language": body.reply_language}

    return app


def _receipt(said: str, material: str = CEMENT) -> tuple[str, dict]:
    return ("record_receipt", {"project_id": PROJECT, "site_id": SITE, "material_id": material, "unit_id": UNIT,
                               "quantity": 20, "occurred_date": dt.date.today().isoformat(), MATERIAL_SAID: said,
                               CONFIRM_ARG: "20 ചാക്ക് സിമന്റ് വന്നു"})


async def _agent(script: list, text: str) -> tuple:
    saved: list = []
    app = _materials_api(saved)
    tools = build_tools(app.openapi(), tuple(a for a in ALLOWED if a.name in (
        "record_receipt", "add_material", "set_reply_language")))
    client = ApiClient(ACTOR, app=app)
    try:
        turn = await ApiAgent(FakeToolCallingProvider(script), tools).run(
            client, text, language="malayalam", channel="whatsapp_voice")
        results = await confirm(client, turn.pending) if turn.pending else []
        return turn, saved, results
    finally:
        await client.close()


async def test_whole_journey_malayalam_cement_saves_on_the_listed_cement_never_a_new_material() -> None:
    add = ("add_material", {"name": "സിമന്റ്", CONFIRM_ARG: "പുതിയ മെറ്റീരിയൽ: സിമന്റ്"})
    turn, saved, results = await _agent([[_receipt("സിമന്റ്", "new:സിമന്റ്"), add], [add],
                                         [_receipt("cement")], "റെഡി."], "20 ചാക്ക് സിമന്റ് വന്നു")
    assert [e.tool for e in turn.pending] == ["record_receipt"] and turn.pending[0].summary.startswith("20 ചാക്ക്")
    assert all(r.ok for r in results) and saved == [("receipt", CEMENT, 20.0)]
    assert not any("➕" in o for o in turn.options)


async def test_a_new_material_that_is_already_listed_is_not_added_again() -> None:
    add = ("add_material", {"name": "Cement", CONFIRM_ARG: "പുതിയ: Cement"})
    turn, saved, _ = await _agent([[add], "ശരി."], "സിമന്റ് ചേർക്കൂ")
    assert turn.pending == [] and saved == []
    assert "already in the company's list" in turn.calls[0]["result"]["error"]


# -- a reply-language choice is set at once, never a card line ----------------------------------------------------


async def test_a_reply_language_choice_is_set_at_once_and_never_on_the_card() -> None:
    choice = ("set_reply_language", {"reply_language": "manglish", CONFIRM_ARG: "ഇനി മംഗ്ലീഷിൽ മറുപടി നൽകും"})
    turn, saved, _ = await _agent([[choice, _receipt("cement")], "Sheri."], "ഇനി മംഗ്ലീഷിൽ മറുപടി, 20 ചാക്ക് സിമന്റ് വന്നു")
    assert saved[0] == ("language", "manglish") and turn.language_set == "manglish"
    assert [e.tool for e in turn.pending] == ["record_receipt"]  # only the record waits for Save
