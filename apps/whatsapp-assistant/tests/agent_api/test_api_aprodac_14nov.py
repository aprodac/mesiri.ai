"""Live, Aprodac, 14 Nov 2026 01:01-01:04 UTC (06:31-06:34 IST), four messages:

1. A voice note with cement, M Sand and TMT got a card and the size question "1 Cubic Meters M Sand-il ethra Bags
   undu?". The answer "1cum msand = 30 bag" SAVED the whole card: the model called save_ready_entries on an answer.
   Fix: a message that answers the code's own question (a size, or a held line's site / material / unit / person)
   saves the card only when it also says save ([232]: "oru load-il 200 bar undakum, save cheythoo" still saves).
2. "randu cement alla, randu plumber" after Save: the saved 2 bags of cement could not be taken back (undo_receipt was
   behind the closed "take_back" area, tools on demand). Fix: something saved in this chat keeps take-back reachable.
3. Asked again, the same plumber correction went on the card twice. Fix: one correction per saved report waits; the
   same one is not added again, a different one takes its place.
"""

from __future__ import annotations

from tests.agent_api.test_api_correct_saved_item3 import _saved
from tests.agent_api.test_api_size_direction_232 import TMT_LOAD, TmtStore, _say, _started
from tests.agent_api.test_api_stock_unit_165 import NOS, _tools  # noqa: F401 -- the autouse fixture
from tests.agent_api.test_api_tools_on_demand_277e import Recording, _run

from agent_api.agent import (
    CORRECT_SAVED,
    PendingWrite,
    correctable_saves,
    corrected_attendance,
    remember_saves,
)
from mesiri_ai.fakes import FakeToolCallingProvider

# --- 1. an answer is not a Save -----------------------------------------------------------------------------------

async def test_live_a_size_answer_never_saves_the_card() -> None:
    store = TmtStore()
    h = await _started(store)  # 30 TMT bars on the card, "1 Loads ... ethra Numbers?" asked
    await _say(h, "1 load = 200 bar", [[("save_ready_entries", {})], "Saved."])  # the model saves anyway
    state = await h.state()
    assert store.received == []  # nothing saved
    assert {p["tool"] for p in state["pending"]} == {"record_receipt", "set_unit_conversion"}  # all back on the card
    assert "Saved." not in h.sent[-1].text


async def test_guard_an_answer_that_says_save_still_saves() -> None:
    store = TmtStore()
    h = await _started(store)
    await _say(h, "oru load-il 200 bar undakum, save cheythoo", [[("save_ready_entries", {})], "Saved."])
    assert store.one_unit[(TMT_LOAD, NOS)] and store.received  # [232]: said save, saved


# --- 2. take-back is reachable once something is saved here -------------------------------------------------------

async def test_live_take_back_tools_are_offered_once_something_is_saved_in_the_chat() -> None:
    saved = [{"fp": "x", "summary": "2 bags Cement, Main block", "at": 1e12, "tool": "record_receipt", "id": "r-1"}]
    with_save, without = Recording(["Ok."]), Recording(["Ok."])
    await _run(with_save, "randu cement alla, randu plumber", on_demand=True, recent_saves=saved)
    await _run(without, "randu cement alla, randu plumber", on_demand=True)
    assert "undo_receipt" in with_save.offered[0] and "undo_usage" in with_save.offered[0]
    assert "undo_receipt" not in without.offered[0]  # guard: nothing saved here, the area stays closed


# --- 3. one correction per saved report -----------------------------------------------------------------------------

def _waiting_correction(lines: list[dict]) -> tuple[list[dict], PendingWrite]:
    recent = remember_saves([], [_saved()], 1000.0)
    body, line = corrected_attendance(correctable_saves(recent)[0], lines)
    return recent, PendingWrite(tool="record_attendance", method="POST", path="/labour/attendance", params={},
                                body=body, summary=line, idempotency_key="k-first")


async def test_live_the_same_correction_asked_again_is_on_the_card_once() -> None:
    plumbers = [{"trade": "Plumber", "headcount": 2}]
    recent, first = _waiting_correction(plumbers)
    model = FakeToolCallingProvider([[(CORRECT_SAVED, {"number": 1, "lines": plumbers})], "Ok."])
    turn = await _run(model, "njan randu plumbermarre mathre paranjitullu", ready=[first], recent_saves=recent)
    assert [e.idempotency_key for e in turn.pending] == ["k-first"]


async def test_sibling_a_different_correction_takes_the_waiting_ones_place() -> None:
    recent, first = _waiting_correction([{"trade": "Plumber", "headcount": 2}])
    model = FakeToolCallingProvider([[(CORRECT_SAVED, {"number": 1, "lines": [{"trade": "Plumber", "headcount": 3}]})],
                                     "Ok."])
    turn = await _run(model, "alla, moonu plumber", ready=[first], recent_saves=recent)
    assert len(turn.pending) == 1 and "Plumber 0 → 3" in turn.pending[0].summary
    assert turn.pending[0].idempotency_key == "k-first"  # the same line on the card, changed


# --- 4. a take-back names what it takes back ------------------------------------------------------------------------

async def test_live_a_take_back_line_names_the_record_it_takes_back() -> None:
    """Live, 13-14 Nov: "↩️ Take back: *Take back usage*" said nothing about which entry. Every take-back kind now
    names the saved record, as it was saved; a record it cannot find keeps the plain title (guard)."""
    from types import SimpleNamespace

    from fastapi import FastAPI
    from tests.agent_api.standin import ACTOR

    from agent_api.client import ApiClient
    from agent_api.receipts import caption_lines, preview_slip

    app = FastAPI()
    rows = {"/materials/inflows": [{"id": "11111111-1111-4111-8111-111111111111", "material_name": "Cement",
                                    "quantity": "2", "unit": "bags", "occurred_date": "2026-11-14"}],
            "/materials/outflows": [{"id": "22222222-2222-4222-8222-222222222222", "material_name": "Cement",
                                     "quantity": "5000", "unit": "bags", "occurred_date": "2026-11-13"}],
            "/materials/transfers": [{"id": "33333333-3333-4333-8333-333333333333", "material_name": "Cement",
                                      "quantity": "10", "unit": "bags", "occurred_date": "2026-11-14",
                                      "from_site_name": "Main block", "to_site_name": "Annex"}],
            "/expenses": [{"id": "44444444-4444-4444-8444-444444444444", "amount": "2500",
                           "category_name": "Fuel", "occurred_date": "2026-11-14"}]}
    for path, items in rows.items():
        app.add_api_route(path, lambda items=items: {"items": items, "total": len(items)}, methods=["GET"])

    def undo(tool: str, path: str) -> PendingWrite:
        return PendingWrite(tool=tool, method="POST", path=path, params={}, body={}, summary="take back",
                            idempotency_key=tool)

    entries = [undo("undo_receipt", "/materials/inflows/11111111-1111-4111-8111-111111111111/reverse"),
               undo("undo_usage", "/materials/outflows/22222222-2222-4222-8222-222222222222/reverse"),
               undo("undo_transfer", "/materials/transfers/33333333-3333-4333-8333-333333333333/reverse"),
               undo("undo_expense", "/expenses/44444444-4444-4444-8444-444444444444/reverse"),
               undo("undo_receipt", "/materials/inflows/99999999-9999-4999-8999-999999999999/reverse")]
    client = ApiClient(ACTOR, app=app)
    try:
        lines = caption_lines(await preview_slip(entries, SimpleNamespace(sites=[], projects=[]), client))
    finally:
        await client.close()
    assert "*2 bags Cement · 2026-11-14*" in lines[0]
    assert "*5,000 bags Cement · 2026-11-13*" in lines[1]
    assert "*10 bags Cement · Main block → Annex*" in lines[2]
    assert "₹2,500 · Fuel · 2026-11-14" in lines[3]
    assert "*Take back delivery*" in lines[4]  # not found: the plain title, never a wrong record
