"""[243] SOP eval case (WA-148): a Manglish message is saved in English. Manglish is in Latin letters, so the code's
script check cannot catch it; the SOP rule ("Every tool body is English") does, and this live case guards it.

Built by hand on the facts of cor_8b1d1e93e5a649fc9b337a9ef62f0959 (the replays of cor_bd6fd016803c42de953613cd600e15ab
and cor_9270c3a624bf425e86aa637ad744f040 could not be fetched on the bot server: no control-plane token).
"""

from __future__ import annotations

import pytest
from tests.agent_api.replaykit import check, replay
from tests.agent_api.replays.test_replay_plan_233 import RECORDED as GREEN_VILLA

from agent_api.fill import other_script

SITE = "727d30ee-c40d-4587-90ed-cdf519121dfb"
PROJECT = "fee7ee7c-e5d6-436c-88be-7a5ea29cc1ee"
RECORDED = {
    **GREEN_VILLA,
    "text": "Green Villa-il innu 6 mason, 10 electrician pani eduthu. 2nd floor plastering kazhinju",
    "calls": [
        {"tool": "record_attendance", "arguments": {
            "project_id": PROJECT, "site_id": SITE, "occurred_date": "2026-11-04",
            "lines": [{"trade": "mason", "headcount": 6}, {"trade": "electrician", "headcount": 10}],
            "confirm_line": "Green Villa: 6 mason, 10 electrician pani eduthu"}},
        {"tool": "record_work", "arguments": {
            "project_id": PROJECT, "site_id": SITE, "activity_date": "2026-11-04", "work_type": "plastering",
            "narrative": "Plastering done on 2nd floor", "confirm_line": "2nd floor plastering kazhinju"}},
    ],
    "reply": "Sheri.",
}
EXPECT = {"must_call": ["record_attendance", "record_work"], "must_not_call": []}
MANGLISH = ("kazhinju", "pani", "eduthu", "innu")


def _english(turn) -> list[str]:  # noqa: ANN001
    wrong = []
    for e in turn.pending:
        texts = [str(v) for k, v in e.body.items() if isinstance(v, str) and not k.endswith("_id")]
        texts += [str(ln.get("trade") or "") for ln in e.body.get("lines") or []]
        wrong += [t for t in texts if other_script(t) or any(w in t.lower().split() for w in MANGLISH)]
    return wrong


async def test_replay_plan_243() -> None:
    turn, _api = await replay(RECORDED)
    assert [c["tool"] for c in turn.calls] == ["record_attendance", "record_work"]
    assert _english(turn) == []
    assert turn.pending[0].summary.endswith("pani eduthu")  # the card line stays in their words


@pytest.mark.live
async def test_replay_plan_243_live() -> None:
    turn, _api = await replay(RECORDED, live=True)
    assert check(turn, EXPECT) == []
    assert _english(turn) == []
