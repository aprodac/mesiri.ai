"""WA-265: the real-model eval's spend is capped per day and stops mid-run when the budget is used."""

from __future__ import annotations

import json
from pathlib import Path

from tests.agent_api import evalbudget
from tests.agent_api.replays.conftest import budget_left


def _log(path: Path, calls: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(c) for c in calls) + "\n", encoding="utf-8")
    return path


def test_a_call_is_priced_and_cached_input_is_never_dearer() -> None:
    plain = evalbudget.call_usd({"input_tokens": 1_000_000, "output_tokens": 0})
    cached = evalbudget.call_usd({"input_tokens": 1_000_000, "cached_input_tokens": 1_000_000, "output_tokens": 0})
    assert plain == evalbudget.USD_PER_M_INPUT
    assert cached == evalbudget.USD_PER_M_CACHED <= plain


def test_spend_of_a_log_and_of_no_log(tmp_path: Path) -> None:
    log = _log(tmp_path / "u.jsonl", [{"input_tokens": 18_000, "output_tokens": 120}] * 3)
    one = (18_000 * evalbudget.USD_PER_M_INPUT + 120 * evalbudget.USD_PER_M_OUTPUT) / 1_000_000
    assert abs(evalbudget.spent_usd(log) - 3 * one) < 1e-12
    assert evalbudget.spent_usd(tmp_path / "missing.jsonl") == 0.0


def test_ledger_adds_up_over_a_day_and_starts_again_the_next(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.json"
    log = _log(tmp_path / "u.jsonl", [{"input_tokens": 1_000_000, "output_tokens": 0}])
    assert evalbudget.main(["add", str(ledger_path), str(log)]) == 0
    assert evalbudget.main(["add", str(ledger_path), str(log)]) == 0
    today = evalbudget.read_ledger(ledger_path)
    assert abs(today["usd"] - 2 * evalbudget.USD_PER_M_INPUT) < 1e-9
    assert evalbudget.remaining_usd(today, cap_inr=880.0) == 10.0 - today["usd"]
    assert evalbudget.remaining_usd(today, cap_inr=10.0) == 0.0
    assert evalbudget.read_ledger(ledger_path, today="2999-01-01")["usd"] == 0.0


def test_an_unreadable_ledger_is_an_empty_one(tmp_path: Path) -> None:
    bad = tmp_path / "ledger.json"
    bad.write_text("not json", encoding="utf-8")
    assert evalbudget.read_ledger(bad)["usd"] == 0.0


def test_the_group_is_told_once_a_day(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.json"
    assert evalbudget.main(["told", str(ledger_path), "key_refused"]) == 0
    assert evalbudget.main(["told", str(ledger_path), "key_refused"]) == 1
    assert evalbudget.main(["told", str(ledger_path), "cap_reached"]) == 0


def test_a_run_stops_when_its_budget_is_used(tmp_path: Path) -> None:
    log = _log(tmp_path / "u.jsonl", [{"input_tokens": 1_000_000, "output_tokens": 0}])
    assert budget_left(str(evalbudget.USD_PER_M_INPUT + 0.01), str(log))
    assert not budget_left(str(evalbudget.USD_PER_M_INPUT), str(log))
    assert not budget_left("0", str(log))


def test_no_budget_means_a_local_run_is_never_stopped(tmp_path: Path) -> None:
    log = _log(tmp_path / "u.jsonl", [{"input_tokens": 9_000_000, "output_tokens": 0}])
    assert budget_left(None, str(log))
    assert budget_left("", str(log))
    assert budget_left("1", None)
