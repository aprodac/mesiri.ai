"""NXT-08: "what is waiting for me?" is the `waiting` tool (GET /approvals/waiting), on WhatsApp as on the bell.

Written cases, not production replays (the tool is new). Three turns:
- the asked message, in Manglish: "enikku enthokke pending undu?";
- a sibling, in English: "anything waiting for me to approve?";
- the guard: "show my requests" is the person's own requests (material ones and Mesiri's team), never `waiting`.

Scripted: the same calls go through the real tools and the reply lists what came back. Live (-m live, the "SOP eval"
workflow): the real model reads SOP.md and must pick the right tool.
"""

from __future__ import annotations

import pytest
from tests.agent_api.replaykit import check, replay

FACTS = ("The person's projects and sites (use these ids):\n- project Villa Kakkanad (project_id "
         "5086f821-478b-46f9-80d3-6eec99d6484e)\n  - site Main building (site_id 1b2f8c4e-0000-4000-8000-000000000001)\n"
         "Only one site: Main building. Use it; never ask which site.")

WAITING = {
    "today": "2026-11-09", "total": 3, "urgent": 1,
    "counts": {"site_report": 1, "material_request": 1, "subcontract_bill": 0, "ra_bill": 1, "task": 0},
    "items": [
        {"kind": "material_request", "ref": "MR-12", "title": "Cement 200 bags", "detail": "from Ravi · needed by 2026-11-10",
         "project_name": "Villa Kakkanad", "site_name": "Main building", "since": "2026-11-08", "urgent": True},
        {"kind": "site_report", "ref": None, "title": "Main building: 4 to confirm", "detail": "Today's updates from site",
         "project_name": "Villa Kakkanad", "site_name": "Main building", "since": "2026-11-09", "urgent": False},
        {"kind": "ra_bill", "ref": "RA-02", "title": "RA-02 for Mr. Thomas", "detail": "Draft: check and submit to the client",
         "project_name": "Villa Kakkanad", "site_name": None, "since": "2026-11-07", "urgent": False},
    ],
    "unavailable": [],
}

ASKED = {"text": "enikku enthokke pending undu?", "facts": FACTS,
         "calls": [{"tool": "waiting", "args": {}, "result": WAITING}],
         "reply": "3 waiting for you:\n1. MR-12 Cement 200 bags (Main building, from Ravi, needed tomorrow) - urgent\n"
                  "2. Main building: 4 to confirm today\n3. RA-02 for Mr. Thomas: draft to submit"}
SIBLING = {**ASKED, "text": "anything waiting for me to approve?"}
GUARD = {"text": "show my requests", "facts": FACTS, "calls": [], "reply": ""}

EXPECT = {"must_call": ["waiting"], "must_not_call": ["my_requests", "tell_the_team"], "pending": []}
EXPECT_GUARD = {"must_not_call": ["waiting"], "pending": []}


async def test_waiting_scripted_lists_what_the_api_returned() -> None:
    turn, api = await replay(ASKED)
    assert [c["tool"] for c in turn.calls] == ["waiting"]
    assert ("GET", "/approvals/waiting") in api.seen
    assert turn.pending == []  # a read: nothing waits for Save
    assert "MR-12" in turn.reply and "RA-02" in turn.reply


@pytest.mark.live
@pytest.mark.parametrize("case", [ASKED, SIBLING], ids=["manglish", "english"])
async def test_waiting_live(case: dict) -> None:
    turn, _api = await replay(case, live=True)
    assert check(turn, EXPECT) == []


@pytest.mark.live
async def test_my_requests_is_not_waiting_live() -> None:
    turn, _api = await replay(GUARD, live=True)
    assert check(turn, EXPECT_GUARD) == []
