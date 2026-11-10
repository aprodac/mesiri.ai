"""TM-25: a production v3 turn becomes a scripted test (tests/agent_api/replaykit.py,
scripts/replay_to_test.py). Guards: the replay runs the real tools with the recorded API answers and sends
nothing (writes wait for Save); long digit runs (phone numbers) are masked in a generated test."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from tests.agent_api.replaykit import check, replay

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
    assert "33333333-3333-3333-3333-333333333333" in text  # ids are never masked
    assert "@pytest.mark.live" in text and "async def test_replay_cement_and_stock_live" in text
    assert "EXPECT = {" in text and "'record_receipt'" in text
    compile(text, "generated.py", "exec")


async def test_check_says_what_the_turn_got_wrong() -> None:
    """WA-148: the live test's verdict on a turn against EXPECT."""
    turn, _ = await replay(RECORDED)
    assert check(turn, {"must_call": ["record_receipt"], "pending": ["cement"]}) == []
    wrong = check(turn, {"must_call": ["record_usage"], "must_not_call": ["stock_check"], "pending": ["steel", "cement"]})
    assert "did not call record_usage" in wrong and "called stock_check" in wrong
    assert any("1 entries waiting, expected 2" in w for w in wrong) and "no waiting entry mentions 'steel'" in wrong


async def test_guard_the_live_replay_skips_without_a_key(monkeypatch) -> None:
    import pytest

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(pytest.skip.Exception):
        await replay(RECORDED, live=True)


async def test_a_wrong_turn_says_what_the_model_did_271() -> None:
    """WA-271: a failed expectation carries what the model called, what waits and what it said."""
    turn, _api = await replay({"text": "hi", "calls": [], "reply": "Namaskaram."})
    wrong = check(turn, {"must_call": ["record_receipt"], "pending": ["cement"]})
    assert wrong[0] == "did not call record_receipt" and wrong[-1].startswith("(it called nothing; waiting: nothing; said: ")
    assert "Namaskaram." in wrong[-1]


async def test_the_messages_before_reach_the_model_271() -> None:
    """WA-271: a recorded turn's earlier messages are the model's history in the replay."""
    from unittest.mock import patch

    from agent_api.agent import ApiAgent

    seen: dict = {}
    real = ApiAgent.run

    async def run(self, client, text, **kwargs):  # noqa: ANN001, ANN003, ANN202
        seen["history"] = [(m.role, m.text) for m in kwargs.get("history") or []]
        return await real(self, client, text, **kwargs)

    with patch.object(ApiAgent, "run", run):
        await replay({"text": "Ink kanan pattule?", "calls": [], "reply": "Sheri.",
                      "before": [{"role": "user", "text": "ente complaints evide?"}, {"role": "model", "text": "Nokkam."}]})
    assert seen["history"] == [("user", "ente complaints evide?"), ("model", "Nokkam.")]


def test_the_trace_keeps_the_last_few_messages_cut_short_271() -> None:
    from types import SimpleNamespace

    from agent_api.whatsapp import BEFORE_CHARS, BEFORE_IN_TRACE, before_in_trace

    history = [SimpleNamespace(role="user", text=f"{i} " + "x" * 1000) for i in range(20)]
    kept = before_in_trace(history)
    assert len(kept) == BEFORE_IN_TRACE and kept[-1]["text"].startswith("19 ") and len(kept[0]["text"]) == BEFORE_CHARS
    assert before_in_trace(None) == []
