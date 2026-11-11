"""WA-277 step C: a refused call gets ONE instruction, and the same checks accept a call that follows it.

Production, 2 to 11 Nov 2026: 64 of 587 turns had a call refused by a check in the code. The ones that cost the
person their update were refusals whose instruction the next check refused, or the same refusal given again and again
(each round is a whole model call):

- 5 Nov, "10 bag baby metal aanu vannathu": the corrected line sent with its new summary as a change was refused
  ("cannot change confirm_line"), then "pass material_said", then "cannot change material_said": seven calls, the
  list dropped and prepared again with the new material on it twice.
- 11 Nov, New India: "pass material_said" answered by "cannot change material_said" (fixed in 4c6ccec), then
  "there is no waiting entry 3" for the line the model itself had just replaced.
- 7 Nov, "alla, 6 mason aanu": "no tool named change_ready_entry", and the person was asked for the whole line again.
- 5 Nov: "material_said is not in English" three times in a row; the reply told the person "the system says the
  word must be in English".
- Aprodac, 7 Nov: saved at Main block in the afternoon; "6 masons came today" at 01:56 was asked "which site?"
  again, because the remembered site followed the calendar day and entries follow the working day.

The class: (1) what a refusal asks for is accepted when it comes back; (2) a list tool with nothing in the list says
what is true, never "no tool"; (3) the same line is not refused round after round: the second time for the same
reason (or the third for any) the model is told to stop and ask the person one plain question; (4) the site of the
working day is one day, the same one entries are dated by.

Guards: a line refused once and sent right goes through with no stop note; three different lines refused once each
are not stopped; a change of only the summary line is still refused (the card must show what is saved).
"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

from tests.agent_api.test_api_new_material_210b import (
    ACTOR,
    LITRE,
    PAINT,
    TOOLS,
    Store,
    _receipt,
    _turn,
)

from agent_api import whatsapp as wa
from agent_api.agent import (
    CHANGE_READY,
    CORRECT_SAVED,
    DROP_READY,
    REFUSALS_PER_LINE,
    SAVE_READY,
    ApiAgent,
    Places,
    refusal_kind,
    refusal_line,
)
from agent_api.client import ApiClient
from agent_api.tools import ALLOWED, MATERIAL_SAID, build_tools
from mesiri_ai.models import ChatMessage, ToolCallRecord, ToolRunResult

STEEL = str(uuid.uuid4())
SAID = [ChatMessage(role="user", text="30 litre paint vannu"), ChatMessage(role="model", text="Ready.")]


def _store() -> Store:
    store = Store()
    store.catalog.append({"id": STEEL, "name": "Steel", "aliases": [], "default_unit_id": LITRE})
    return store


def _change(changes: list[tuple[str, object]], line: str = "", number: int = 1) -> tuple[str, dict]:
    return (CHANGE_READY, {"number": number, "changes": [{"field": f, "value": v} for f, v in changes],
                           "confirm_line": line})


async def _on_paint(store: Store):  # noqa: ANN202
    turn = await _turn(store, [[_receipt(PAINT, "paint", LITRE, 30, "30 litres paint, Green Villa")], "Ready."],
                       "30 litre paint vannu")
    assert [e.body["material_id"] for e in turn.pending] == [PAINT]
    return turn.pending


def _errors(turn) -> list[str]:  # noqa: ANN001
    return [str((c["result"] or {}).get("error") or "") for c in turn.calls]


# 1. What a refusal asks for is accepted when it comes back ---------------------------------------------------------

async def test_the_reported_summary_line_sent_as_a_change_is_taken_as_the_line() -> None:
    store = _store()
    ready = await _on_paint(store)
    turn = await _turn(store, [[_change([("quantity", 40), ("confirm_line", "40 litres paint, Green Villa")])],
                               "Changed."], "alla, 40 litre aanu", ready=ready, history=SAID)
    assert _errors(turn) == [""], _errors(turn)
    assert [(e.body["quantity"], e.summary) for e in turn.pending] == [(40, "40 litres paint, Green Villa")]


async def test_the_material_refusal_of_a_change_says_how_and_that_call_is_accepted() -> None:
    store = _store()
    ready = await _on_paint(store)
    first = await _turn(store, [[_change([("material_id", STEEL)], "30 litres steel")], "x"],
                        "athu maattu", ready=ready, history=SAID)
    asked = _errors(first)[0]
    assert "material_said" in asked and "`changes`" in asked  # where it goes in THIS tool
    # The call the refusal asked for: the same change with their word as one more item.
    again = await _turn(store, [[_change([("material_id", STEEL), (MATERIAL_SAID, "steel")], "30 litres steel")],
                                "Changed."], "athu steel aakku", ready=ready, history=SAID)
    assert _errors(again) == [""], _errors(again)
    assert [e.body["material_id"] for e in again.pending] == [STEEL]


async def test_sibling_the_material_refusal_of_a_new_line_is_accepted_when_followed() -> None:
    store = _store()
    name, args = _receipt(STEEL, "", LITRE, 5, "5 litres, Green Villa")
    first = await _turn(store, [[(name, {k: v for k, v in args.items() if k != MATERIAL_SAID})], "x"], "athu 5 vannu")
    assert "pass material_said" in _errors(first)[0] and not first.pending
    again = await _turn(store, [[_receipt(STEEL, "steel", LITRE, 5, "5 litres steel, Green Villa")], "Ready."],
                        "athu 5 vannu")
    assert _errors(again) == [""] and [e.body["material_id"] for e in again.pending] == [STEEL]


async def test_guard_a_change_of_only_the_line_is_refused_with_what_to_send() -> None:
    store = _store()
    ready = await _on_paint(store)
    turn = await _turn(store, [[_change([("confirm_line", "30 litres steel, Green Villa")])], "x"],
                       "athu steel aakku", ready=ready, history=SAID)
    assert "the line alone changes nothing" in _errors(turn)[0] and MATERIAL_SAID in _errors(turn)[0]
    assert [e.summary for e in turn.pending] == ["30 litres paint, Green Villa"]  # the card still shows what is held


# 2. A list tool with nothing in the list ---------------------------------------------------------------------------

class _CallsAnyTool:
    """A model that calls a tool it was not offered (the real one did, 7 Nov: it had used it earlier in the chat)."""

    provider = "fake"

    def __init__(self, name: str) -> None:
        self.name = name

    async def run_tools(self, system_prompt, messages, tools, handler, **_):  # noqa: ANN001, ANN201, ANN003
        arguments = {"number": 1, "changes": [], "confirm_line": "x"}
        outcome = await handler(self.name, arguments)
        return ToolRunResult(text="x", calls=[ToolCallRecord(name=self.name, arguments=arguments, outcome=outcome)],
                             steps=1, stop_reason="answered", model="fake")


async def test_the_reported_change_with_nothing_waiting_is_never_no_tool() -> None:
    app = _store().api()
    tools = build_tools(app.openapi(), tuple(a for a in ALLOWED if a.name in TOOLS))
    for tool in (CHANGE_READY, SAVE_READY, DROP_READY, CORRECT_SAVED):
        client = ApiClient(ACTOR, app=app)
        try:
            turn = await ApiAgent(_CallsAnyTool(tool), tools).run(client, "alla, 6 mason aanu")
        finally:
            await client.close()
        error = _errors(turn)[0]
        assert "no tool named" not in error and "Nothing is waiting" in error and "new line" in error, (tool, error)


async def test_a_number_that_is_not_waiting_says_which_are() -> None:
    store = _store()
    ready = await _on_paint(store)
    turn = await _turn(store, [[_change([("quantity", 40)], "40 litres paint", number=3)], "x"],
                       "alla, 40 litre", ready=ready, history=SAID)
    assert "there is no waiting entry 3" in _errors(turn)[0] and "Waiting now: 1." in _errors(turn)[0]


# 3. The same line is not refused round after round -----------------------------------------------------------------

async def test_the_reported_same_refusal_twice_tells_the_model_to_stop_and_ask() -> None:
    store = _store()
    name, args = _receipt(STEEL, "", LITRE, 5, "5 litres, Green Villa")
    bare = (name, {k: v for k, v in args.items() if k != MATERIAL_SAID})
    turn = await _turn(store, [[bare], [bare], "Ethu material aanu vannathu?"], "athu 5 vannu")
    first, second = _errors(turn)[:2]
    assert "STOP" not in first
    assert "STOP" in second and "ONE short question" in second and "pass material_said" in second
    assert not turn.pending


async def test_sibling_a_third_refusal_for_any_reason_stops_too() -> None:
    assert REFUSALS_PER_LINE == 3
    store = _store()
    ready = await _on_paint(store)
    steps = [[_change([("colour", "red")], "x")], [_change([("confirm_line", "y")], "")],
             [_change([("shade", "dark")], "x")], "x"]
    turn = await _turn(store, steps, "athu maattu", ready=ready, history=SAID)
    errors = _errors(turn)
    assert ["STOP" in e for e in errors] == [False, False, True], errors


async def test_guard_a_line_refused_once_and_sent_right_goes_through_untouched() -> None:
    store = _store()
    name, args = _receipt(STEEL, "", LITRE, 5, "5 litres, Green Villa")
    bare = (name, {k: v for k, v in args.items() if k != MATERIAL_SAID})
    turn = await _turn(store, [[bare], [_receipt(STEEL, "steel", LITRE, 5, "5 litres steel, Green Villa")], "Ready."],
                       "athu 5 vannu")
    assert "STOP" not in " ".join(_errors(turn)) and len(turn.pending) == 1


async def test_guard_three_different_lines_refused_once_each_are_not_stopped() -> None:
    store = _store()

    def bare(line: str) -> tuple[str, dict]:
        name, args = _receipt(STEEL, "", LITRE, 5, line)
        return (name, {k: v for k, v in args.items() if k != MATERIAL_SAID})

    turn = await _turn(store, [[bare("5 a"), bare("5 b"), bare("5 c")], "x"], "athu 5 vannu")
    assert "STOP" not in " ".join(_errors(turn)[:3])  # each line's first refusal is its own instruction
    # ([248]'s one retry for lines not on the card then runs the same script: the second refusal of each stops it.)
    assert all("STOP" in e for e in _errors(turn)[3:])


def test_a_refusal_is_the_same_kind_whatever_it_names() -> None:
    a = refusal_kind("'Metal' is not in the company's material list (nearest: Cement, Sand). Never record it")
    b = refusal_kind("'TMT Steel Bars' is not in the company's material list (nearest: Steel). Never record it")
    assert a[:40] == b[:40]
    assert refusal_kind("Already saved at 12:27: x") == refusal_kind("Already saved at 13:25: x")
    assert refusal_line("record_receipt", {MATERIAL_SAID: " TMT  Steel "}) == refusal_line(
        "record_receipt", {MATERIAL_SAID: "tmt steel"})
    assert refusal_line("record_receipt", {MATERIAL_SAID: "cement"}) != refusal_line(
        "record_receipt", {MATERIAL_SAID: "sand"})


# 4. The site of the working day -----------------------------------------------------------------------------------

SITE_ID, PROJECT_ID = str(uuid.uuid4()), str(uuid.uuid4())
SITES_CTX = SimpleNamespace(
    timezone="Asia/Kolkata", projects=[SimpleNamespace(id=PROJECT_ID, name="Green Villa")],
    sites=[SimpleNamespace(id=SITE_ID, name="Main block", project_id=PROJECT_ID),
           SimpleNamespace(id=str(uuid.uuid4()), name="Annex", project_id=PROJECT_ID)])


def _at(monkeypatch, hour: int, minute: int = 0) -> None:  # noqa: ANN001
    class Clock(dt.datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: ANN001, ANN206
            return dt.datetime(2026, 11, 8, hour, minute, tzinfo=tz)

    monkeypatch.setattr(wa, "dt", SimpleNamespace(datetime=Clock))


def test_the_reported_site_holds_after_midnight_of_the_working_day(monkeypatch) -> None:  # noqa: ANN001
    saved_at = {"site_id": SITE_ID, "project_id": PROJECT_ID, "date": "2026-11-07", "recent": [SITE_ID]}
    _at(monkeypatch, 1, 56)  # 01:56 on the 8th: the working day (it starts at 04:00) is still the 7th
    assert wa._today(SITES_CTX, "04:00") == "2026-11-07"
    places = wa._places(SITES_CTX, saved_at, "04:00")
    assert isinstance(places, Places) and places.working is not None and places.working.name == "Main block"


def test_guard_the_next_working_day_asks_again(monkeypatch) -> None:  # noqa: ANN001
    saved_at = {"site_id": SITE_ID, "project_id": PROJECT_ID, "date": "2026-11-07", "recent": [SITE_ID]}
    _at(monkeypatch, 9)
    assert wa._today(SITES_CTX, "04:00") == "2026-11-08"
    assert wa._places(SITES_CTX, saved_at, "04:00").working is None  # [215]: yesterday's site is not a default
    assert wa._places(SITES_CTX, saved_at, "04:00").recent == (SITE_ID,)  # its button still comes first
