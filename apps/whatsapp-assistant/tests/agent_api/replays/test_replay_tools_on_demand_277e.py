"""WA-277 step E: does the real model open the right tool area, and leave the door shut for everyday talk?

Written cases, not production replays: nobody has used tools on demand yet, and production has never called a tool
that is now in an area. They are the first thing the money is spent on (round 1 of the plan, section 9.4): if the
model says "can't" instead of opening an area, tools on demand does not go on for anyone.

- payments: "who do we owe, and how much to Malabar?"
- machines: "the JCB worked 6 hours today"
- wages: "gave Ravi mason 500 advance"
- the guard: "50 bags cement came" and "how many masons came today?" are core: no area is opened for them.

Scripted (every push, free): each case's own calls go through the real tools with the setting off, so the case
itself is known to run. Live (``SOP eval`` workflow, set ``areas``, tools_on_demand on): the real model.
"""

from __future__ import annotations

import pytest
from tests.agent_api.replaykit import check, replay

from agent_api import tool_areas

PROJECT = "5086f821-478b-46f9-80d3-6eec99d6484e"
SITE = "1b2f8c4e-0000-4000-8000-000000000001"
CEMENT = "3f194e81-47cb-43ec-b0e9-d2aa0a3311c8"
BAGS = "03e5cbfa-43d6-4af5-b18a-61aa7f884af7"
FACTS = ("The person's projects and sites (use these ids):\n- project Villa Kakkanad (project_id "
         f"{PROJECT})\n  - site Main building (site_id {SITE})\n"
         "Only one site: Main building. Use it; never ask which site.\n\n"
         f"Units (unit_id): bags ({BAGS}), kg (f24c7ce0-af60-4600-86a4-b66be7268d7e)\n"
         f"Materials (material_id, default unit):\n- Cement ({CEMENT}, bags)")

PAYABLES = {"items": [{"vendor_id": "a1a1a1a1-0000-4000-8000-000000000001", "vendor_name": "Malabar Cements",
                       "outstanding": "50000.00", "overdue": "20000.00", "advance": "0", "oldest_due": "2026-11-01"},
                      {"vendor_id": "a1a1a1a1-0000-4000-8000-000000000002", "vendor_name": "Sree Bricks",
                       "outstanding": "12000.00", "overdue": "0", "advance": "0", "oldest_due": "2026-11-20"}],
            "total_outstanding": "62000.00"}
MACHINES = {"items": [{"id": "b2b2b2b2-0000-4000-8000-000000000001", "name": "JCB 3DX", "kind": "excavator",
                       "ownership": "HIRED", "site_id": SITE, "status": "ON_SITE"}], "total": 1}
WORKERS = {"items": [{"id": "c3c3c3c3-0000-4000-8000-000000000001", "full_name": "Ravi", "trade": "Mason",
                      "is_active": True}], "total": 1}

OWED = {"text": "Namukku aarkkokke paisa kodukkaanundu? Malabar-inu ethra?", "facts": FACTS,
        "calls": [{"tool": "supplier_payables", "args": {}, "result": PAYABLES}],
        "reply": "Malabar Cements-inu 50,000 (20,000 overdue), Sree Bricks-inu 12,000. Aake 62,000."}
JCB = {"text": "innu JCB 6 manikkoor pani cheythu", "facts": FACTS,
       "calls": [{"tool": "machines", "args": {}, "result": MACHINES}],
       "reply": "JCB 3DX, 6 hours, Main building."}
ADVANCE = {"text": "Ravi mason-u 500 rupa advance koduthu", "facts": FACTS,
           "calls": [{"tool": "list_workers", "args": {}, "result": WORKERS}],
           "reply": "Ravi-kku 500 advance."}
CEMENT_CAME = {"text": "50 chaakku cement vannu", "facts": FACTS, "calls": [], "reply": ""}
MASONS = {"text": "innu ethra mason vannu?", "facts": FACTS,
          "calls": [{"tool": "labour_attendance", "args": {}, "result": {"items": [], "total": 0}}],
          "reply": "Innu attendance onnum record cheythittilla."}

AREA_CASES = [
    (OWED, "payments", ["supplier_payables", "supplier_account"]),
    (JCB, "machines", ["machines", "log_machines", "machine_logs"]),
    (ADVANCE, "wages", ["give_labour_advance", "labour_advance_balances", "labour_teams"]),
]


def _areas_opened(turn) -> list[str]:  # noqa: ANN001
    return [str((c.get("arguments") or {}).get("area")) for c in turn.calls if c["tool"] == tool_areas.OPEN]


@pytest.mark.parametrize("case", [OWED, JCB, ADVANCE, MASONS], ids=["owed", "jcb", "advance", "masons"])
async def test_the_cases_run_through_the_real_tools(case: dict) -> None:
    turn, _api = await replay(case)
    assert [c["tool"] for c in turn.calls] == [c["tool"] for c in case["calls"]]
    assert turn.reply


@pytest.mark.nightly  # not in the everyday set: it has its own set, `areas`
@pytest.mark.areas
@pytest.mark.live
@pytest.mark.parametrize(("case", "area", "any_of"), AREA_CASES, ids=["payments", "machines", "wages"])
async def test_the_model_opens_the_area_the_message_needs_live(case: dict, area: str, any_of: list[str]) -> None:
    turn, _api = await replay(case, live=True)
    wrong = check(turn, {"must_call": [tool_areas.OPEN], "must_call_any": any_of})
    if area not in _areas_opened(turn):
        wrong.append(f"opened {_areas_opened(turn) or 'nothing'}, not {area}")
    assert wrong == []


@pytest.mark.nightly  # not in the everyday set: it has its own set, `areas`
@pytest.mark.areas
@pytest.mark.live
async def test_a_delivery_opens_nothing_live() -> None:
    turn, _api = await replay(CEMENT_CAME, live=True)
    assert check(turn, {"must_call": ["record_receipt"], "must_not_call": [tool_areas.OPEN],
                        "pending_has": ["50"]}) == []


@pytest.mark.nightly  # not in the everyday set: it has its own set, `areas`
@pytest.mark.areas
@pytest.mark.live
async def test_an_attendance_question_opens_nothing_live() -> None:
    turn, _api = await replay(MASONS, live=True)
    assert check(turn, {"must_call_any": ["labour_attendance", "day_summary", "site_day"],
                        "must_not_call": [tool_areas.OPEN], "pending": []}) == []
