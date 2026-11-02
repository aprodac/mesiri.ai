"""TM-25: a production v3 turn becomes a scripted test (tests/agent_api/replaykit.py,
scripts/replay_to_test.py). Guards: the replay runs the real tools with the recorded API answers and sends
nothing (writes wait for Save); long digit runs (phone numbers) are masked in a generated test."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from tests.agent_api.replaykit import replay

SITE = "11111111-1111-1111-1111-111111111111"
RECORDED = {
    "correlation_id": "cor_0123456789abcdef0123456789abcdef",
    "text": "50 bag cement vannu, stock ethra? call 9876543210",
    "calls": [
        {"tool": "stock_check", "arguments": {"site_id": SITE, "material_id": "33333333-3333-3333-3333-333333333333"},
         "result": {"items": [{"material_name": "Cement", "current_stock": 176}]}},
        {"tool": "record_receipt", "arguments": {
            "project_id": "22222222-2222-2222-2222-222222222222", "site_id": SITE,
            "material_id": "33333333-3333-3333-3333-333333333333", "quantity": 50,
            "unit_id": "44444444-4444-4444-4444-444444444444", "occurred_date": "2026-11-02",
            "confirm_line": "50 bags cement"}},
    ],
    "reply": "Stock 176 bags. 50 bags cement ready; tap Save.",
    "pending": ["50 bags cement"],
}


async def test_the_turn_runs_again_with_the_recorded_answers() -> None:
    turn, api = await replay(RECORDED)
    assert [c["tool"] for c in turn.calls] == ["stock_check", "record_receipt"]
    assert [e.summary for e in turn.pending] == ["50 bags cement"]
    assert ("GET", "/materials/stock-check") in api.seen
    assert not [m for m, _ in api.seen if m != "GET"]  # nothing written: writes wait for Save
    stock = next(c for c in turn.calls if c["tool"] == "stock_check")
    assert "176" in str(stock["result"])  # the model was shown what production showed it


def _script():
    path = Path(__file__).resolve().parents[4] / "scripts" / "replay_to_test.py"
    spec = importlib.util.spec_from_file_location("replay_to_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def test_the_generated_test_records_what_happened_and_masks_numbers() -> None:
    text = _script().render(RECORDED, "cement and stock")
    assert "async def test_replay_cement_and_stock" in text
    assert "['stock_check', 'record_receipt']" in text and "['50 bags cement']" in text
    assert "9876543210" not in text and "xxxxxxxxxx" in text
    compile(text, "generated.py", "exec")
