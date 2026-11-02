"""TM-20: a CI run's live Gemini calls reach `@bot cost`."""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
from decimal import Decimal
from pathlib import Path

from mesiri.domains.usage import prices

_PATH = Path(__file__).resolve().parents[4] / "scripts" / "report_ci_gemini_usage.py"
_spec = importlib.util.spec_from_file_location("report_ci_gemini_usage", _PATH)
report = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(report)

AT = dt.datetime(2026, 11, 2, tzinfo=dt.UTC)


def _line(model: str, provider: str = "gemini") -> str:
    return json.dumps(
        {"provider": provider, "model": model, "input_tokens": 1_000_000, "output_tokens": 100_000}
    )


def test_calls_are_totalled_per_model_at_our_prices() -> None:
    bodies = report.totals([_line("gemini-2.5-flash"), "", _line("gemini-2.5-flash")], at=AT)
    assert len(bodies) == 1
    body = bodies[0]
    one = prices.ai_cost(
        provider="gemini", model="gemini-2.5-flash", at=AT,
        input_tokens=1_000_000, output_tokens=100_000,
    )
    assert body["kind"] == "ci_tests"
    assert body["calls"] == 2
    assert body["usage"] == {"promptTokenCount": 2_000_000, "candidatesTokenCount": 200_000}
    assert Decimal(str(body["usd"])) == one.amount * 2


def test_a_model_with_no_price_leaves_the_price_to_the_listener() -> None:
    body = report.totals([_line("gemini-9-unknown")], at=AT)[0]
    assert "usd" not in body
    assert body["usage"]["promptTokenCount"] == 1_000_000


def test_other_providers_are_not_gemini_spend() -> None:
    assert report.totals([_line("deepseek-flash", "deepseek")], at=AT) == []


def test_a_run_with_no_calls_or_no_token_never_fails(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("MESIRI_USAGE_LOG", str(tmp_path / "none.jsonl"))
    assert report.main() == 0
    log = tmp_path / "usage.jsonl"
    log.write_text(_line("gemini-2.5-flash"), encoding="utf-8")
    monkeypatch.setenv("MESIRI_USAGE_LOG", str(log))
    monkeypatch.delenv("TEAMMATE_TOKEN", raising=False)
    assert report.main() == 0
    assert "not reported" in capsys.readouterr().out


def test_a_refused_report_is_a_warning(tmp_path, monkeypatch, capsys) -> None:
    log = tmp_path / "usage.jsonl"
    log.write_text(_line("gemini-2.5-flash"), encoding="utf-8")
    monkeypatch.setenv("MESIRI_USAGE_LOG", str(log))
    monkeypatch.setenv("TEAMMATE_TOKEN", "t")

    def refuse(*_args, **_kwargs):
        raise report.urllib.error.URLError("refused")

    monkeypatch.setattr(report, "post", refuse)
    assert report.main() == 0
    assert "::warning::" in capsys.readouterr().out
