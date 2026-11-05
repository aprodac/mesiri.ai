"""WA-168 (approved by Alan, 3 Nov 2026): a size nobody on site knows never blocks or loses a line.

- the size question carries a "Don't know" button in their language; a tap holds the line for the company's admin
  (``POST /materials/size-requests``), the rest of the list stays, and no model turn is spent;
- a site engineer's own size is proposed to the company as well (the admin confirms it with one tap);
- the admin's tap sets it for the company and saves the lines that waited;
- once a day, one message per admin lists the open sizes (``runtime/size_requests_ask.py``).
"""

from __future__ import annotations

import datetime
import uuid
from types import SimpleNamespace

import pytest
from tests.agent_api.test_api_stock_unit_165 import (
    BAG,
    CEMENT,
    LOAD,
    MSAND,
    Harness,
    Store,
    _receipt,
)
from tests.agent_api.test_api_whatsapp_119 import CTX, _message

from agent_api import whatsapp as wa
from agent_api.tools import ALLOWED, CONFIRM_ARG
from mesiri_ai.fakes import FakeToolCallingProvider
from runtime.size_requests_ask import ask_message, queue_size_asks

TOOLS = ("record_receipt", "set_unit_conversion", "add_material", "size_requests", "answer_size_request")
LINE = _receipt(MSAND, "msand", LOAD, 1, "1 load msand Tower A")
#: [252]: a Manglish speaker's card line is in Latin letters (a script line is sent back to the model).
CEMENT_LINE = _receipt(CEMENT, "cement", BAG, 4, "4 bags cement Tower A")
ENGINEER = SimpleNamespace(**{**vars(CTX), "role": "SITE_ENGINEER"})
ADMIN = SimpleNamespace(**{**vars(CTX), "role": "ADMIN"})


@pytest.fixture(autouse=True)
def _tools(monkeypatch: pytest.MonkeyPatch) -> None:
    from agent_api import tools as tools_mod

    real = tools_mod.build_tools
    monkeypatch.setattr(wa, "build_tools", lambda openapi: real(openapi, tuple(a for a in ALLOWED if a.name in TOOLS)))


async def _asked(h: Harness, language: str = "manglish") -> None:
    """The reported start: "4 bag cement, 1 load msand", nobody knows a load's size; the question is open."""
    await h.hold(language=language)
    h.service._agent._provider = FakeToolCallingProvider(
        [[CEMENT_LINE, LINE], [("ask", {"question": "1 load msand = ethra bag?"})], "Cement ready. 1 load = ethra bag?"])
    await h.service.handle(_message("4 bag cement um 1 load msand um vannu"), ENGINEER)


async def test_the_size_question_has_a_dont_know_button_in_their_language() -> None:
    h = Harness(Store(), FakeToolCallingProvider(["-"]))
    await _asked(h)
    reply = h.sent[-1]
    # WA-197: the line is on the list too, so Save stays under the question (it holds the line for the admin).
    assert [b.title for b in reply.buttons] == ["🤷 Ariyilla", "Save"]
    state = await h.state()
    assert [n["summary"] for n in state["size_needed"]] == ["1 load msand Tower A"]
    assert [p["summary"] for p in state["pending"]] == ["4 bags cement Tower A",
                                                       "1 load msand Tower A (1 Loads = how many Bags?)"]


async def test_dont_know_holds_the_line_for_the_admin_keeps_the_rest_and_runs_no_model() -> None:
    store = Store()
    h = Harness(store, FakeToolCallingProvider(["-"]))
    await _asked(h)
    h.service._agent._provider = FakeToolCallingProvider([])  # no model turn: any call would fail
    await h.service.handle(_message("🤷 Ariyilla", tap="apiag:opt:2"), ENGINEER)
    reply = h.sent[-1]
    assert reply.text.startswith("👍 Maatti vechu: 1 load msand Tower A.")
    assert [b.title for b in reply.buttons] == ["Save", "✏️ Edit", "Cancel"]  # the cement still saves with one tap
    held = store.size_requests[0]
    assert held["held_lines"][0]["body"]["unit_id"] == LOAD and held["held_lines"][0]["body"]["quantity"] == 1
    assert "size_needed" not in await h.state()


async def test_anything_else_lets_the_size_question_go() -> None:
    store = Store()
    h = Harness(store, FakeToolCallingProvider(["-"]))
    await _asked(h)
    h.service._agent._provider = FakeToolCallingProvider(["Ok."])
    await h.service.handle(_message("steel ethra undu?"), ENGINEER)
    assert "size_needed" not in await h.state() and store.size_requests == []


async def test_an_engineers_own_size_is_proposed_to_the_company_too() -> None:
    store = Store()
    h = Harness(store, FakeToolCallingProvider(["-"]))
    h.service._agent._provider = FakeToolCallingProvider([[
        ("set_unit_conversion", {"material_id": MSAND, "from_unit_id": LOAD, "one_unit_equals": 60, CONFIRM_ARG: "x"}),
        LINE], "Ready."])
    await h.service.handle(_message("oru load 60 bag"), ENGINEER)
    assert store.size_requests[0]["proposed_one_unit_equals"] == "60.0"
    assert (await h.state())["pending"][0]["body"]["unit_id"] == BAG  # their own line converted now


async def test_the_admins_tap_sets_the_size_and_saves_the_lines_that_waited() -> None:
    store = Store()
    h = Harness(store, FakeToolCallingProvider(["-"]))
    await _asked(h)
    await h.service.handle(_message("🤷 Ariyilla", tap="apiag:opt:2"), ENGINEER)
    store.size_requests[0]["proposed_one_unit_equals"] = "60"
    await h.service.handle(_message("✅ 1. 60 bags", tap=f"apiag:size:{store.size_requests[0]['id']}"), ADMIN)
    assert h.sent[-1].text.startswith("✅ 1 load = 60") and store.received == [("എംസാന്റ്", 60.0)]


async def test_guard_a_site_engineers_tap_cannot_set_the_companys_size() -> None:
    store = Store()
    store.size_requests.append({"id": "r1", "material_id": MSAND, "from_unit_id": LOAD, "status": "open",
                                "held_lines": [], "proposed_one_unit_equals": "60"})
    h = Harness(store, FakeToolCallingProvider(["-"]))
    await h.service.handle(_message("✅", tap="apiag:size:r1"), ENGINEER)
    assert (MSAND, LOAD) not in store.one_unit and store.size_requests[0]["status"] == "open"


@pytest.mark.parametrize("said", ["🤷 Don't know", "dont know", "Ariyilla", "അറിയില്ല", "पता नहीं", "pata nahi"])
def test_dont_know_in_every_language(said: str) -> None:
    assert wa.is_dont_know(said)


@pytest.mark.parametrize("said", ["60", "ariyilla 60 aanu", "I know it's 60"])
def test_guard_an_answer_is_never_taken_as_dont_know(said: str) -> None:
    assert not wa.is_dont_know(said)


# -- the daily ask --------------------------------------------------------------------------------------------------


REQUESTS = [
    {"id": uuid.uuid4(), "material": "M sand", "unit_name": "Loads", "stock_unit": "bags", "stock_unit_name": "Bags",
     "proposed_one_unit_equals": None, "proposed_by_name": None, "waiting": 2},
    {"id": uuid.uuid4(), "material": "Thinner", "unit_name": "Drums", "stock_unit": "litres",
     "stock_unit_name": "Litres", "proposed_one_unit_equals": "20", "proposed_by_name": "Ravi", "waiting": 0},
]


def test_the_daily_message_lists_each_size_and_a_proposal_gets_a_button() -> None:
    text, buttons = ask_message(REQUESTS)
    assert "1. 1 Loads M sand = how many Bags? · 2 lines waiting" in text
    assert "2. 1 Drums Thinner = 20 Litres? (Ravi says)" in text
    assert buttons == [{"id": f"apiag:size:{REQUESTS[1]['id']}", "title": "✅ 2. 20 litres"}]
    assert all(len(b["title"]) <= 20 for b in buttons)


async def test_each_admin_is_asked_once_a_day_and_the_requests_marked_asked() -> None:
    org, admins, claims, marked = uuid.uuid4(), [uuid.uuid4(), uuid.uuid4()], [], []

    async def open_requests(conn):  # noqa: ANN001, ANN202
        return {org: REQUESTS}

    async def answerers(conn, organization_id):  # noqa: ANN001, ANN202
        return admins

    async def claim(**kwargs):  # noqa: ANN003, ANN202
        claims.append(kwargs)
        return uuid.uuid4()

    async def mark(conn, ids):  # noqa: ANN001, ANN202
        marked.extend(ids)

    queued = await queue_size_asks(object(), today=datetime.date(2026, 11, 4), open_requests=open_requests,
                                   answerers=answerers, claim=claim, mark_asked=mark)
    assert queued == 2 and [c["recipient_user_id"] for c in claims] == admins
    assert {c["rule_key"] for c in claims} == {"size_requests_ask"} and claims[0]["payload"]["buttons"]
    assert marked == [r["id"] for r in REQUESTS]
