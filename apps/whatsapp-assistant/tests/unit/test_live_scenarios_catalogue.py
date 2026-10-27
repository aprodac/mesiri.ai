"""WA-80: the live scenario catalogue (tests/live/scenarios_27oct.json) and its runner
(teammate/scenarios.py). The runner talks to the real assistant; here it talks to a fake
chat, so what it judges and how it taps is pinned without the network."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
_spec = importlib.util.spec_from_file_location("scenarios", ROOT / "teammate" / "scenarios.py")
scenarios = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scenarios)


def _msg(n: int, text: str, options: list[str] | None = None, kind: str = "text") -> dict:
    opts = [{"n": i, "title": t} for i, t in enumerate(options or [], 1)]
    menu = "\n".join(f"{o['n']}) {o['title']}" for o in opts)
    return {"n": n, "kind": kind, "text": "\n".join(p for p in (text, menu) if p), "options": opts or None}


class _Chat:
    """Answers each send / tap with the next scripted reply; records what was sent."""

    def __init__(self, replies: list[list[dict]]) -> None:
        self.replies = list(replies)
        self.sent: list = []

    def act(self, *, text=None, choose=None):  # noqa: ANN001, ANN202
        self.sent.append(text if text is not None else choose)
        return (self.replies.pop(0) if self.replies else []), 2.0


def test_the_catalogue_checks_every_mark_of_the_27_oct_rounds():
    cat = scenarios.load(scenarios.DEFAULT_FILE)
    assert scenarios.validate(cat) == []
    assert len(cat["marks"]) == 58


def test_a_mark_with_no_check_is_a_catalogue_problem():
    cat = {"marks": {"M01": {}, "M02": {}}, "scenarios": [{"id": "S1", "steps": [{"send": "x", "checks": [{"mark": "M01"}]}]}]}
    assert scenarios.validate(cat) == ["M02: no check covers it"]


CARD = _msg(7, "📝 To save · Green Villa, Kakkanad:\n• Steel used: 20 rod (❓ How many kg is 20 rod?)", ["❌ Cancel"])


@pytest.mark.parametrize(
    "check, ok",
    [
        ({"mark": "M", "has_re": ["steel used: 20"]}, True),
        ({"mark": "M", "buttons_has": ["✅ Save"]}, False),
        ({"mark": "M", "buttons_has": ["❌"]}, True),
        ({"mark": "M", "lacks_re": ["{SITE_Q}"]}, True),
        ({"mark": "M", "has_re": ["\\b{n}\\b"]}, None),  # nothing captured: not judged
        ({"mark": "M", "body_count_max": {"Steel used": 0}}, False),
        ({"mark": "M", "max_seconds": 1}, False),
    ],
)
def test_judge(check, ok):
    got, _why = scenarios.judge(check, [CARD], 2.0, {"SITE_Q": "which site"}, {})
    assert got is ok


def test_option_lines_are_not_body_lines_and_repeats_are_found():
    doubled = _msg(1, "📝 To save:\n• Steel used: 20 rod\n• Steel used: 20 rod", ["❌ Cancel"])
    ok, why = scenarios.judge({"mark": "M", "no_duplicate_lines": True}, [doubled], 1.0, {}, {})
    assert ok is False and "Steel used" in why
    assert "1) ❌ Cancel" not in scenarios._body_lines([doubled])


def test_a_run_taps_by_title_captures_and_blocks_after_a_missing_tap():
    cat = {
        "patterns": {},
        "marks": {"M1": {}, "M2": {}, "M3": {}},
        "reset": [{"send": "cancel"}],
        "scenarios": [],
    }
    sc = {
        "id": "S",
        "steps": [
            {"send": "8 mason", "checks": [{"mark": "M1", "buttons_has": ["✅ Save"]}]},
            {"tap_if": "Replace"},  # not offered: skipped quietly
            {"tap": "✅ Save", "capture": {"w": "(\\d+) workers"}},
            {"send": "innu ethra?", "checks": [{"mark": "M2", "has_re": ["\\b{w}\\b"]}]},
            {"tap": "✅ Save"},  # not offered: the rest is blocked
            {"send": "more", "checks": [{"mark": "M3", "has": ["x"]}]},
        ],
        "cleanup": [{"send": "undo"}],
    }
    chat = _Chat(
        [
            [_msg(1, "Okay")],
            [_msg(2, "📝 To save: 8 workers (8 mason)", ["✅ Save", "❌ Cancel"])],
            [_msg(3, "✅ Saved: 8 workers (8 mason)")],
            [_msg(4, "Innu 8 per")],
            [_msg(5, "Removed")],
        ]
    )
    log: list[str] = []
    results = scenarios.run_scenario(chat, cat, sc, log)
    assert chat.sent == ["cancel", "8 mason", {"message_n": 2, "option": 1}, "innu ethra?", "undo"]
    by_mark = {r["mark"]: r for r in results}
    assert by_mark["M1"]["ok"] is True
    assert by_mark["M2"]["ok"] is True
    assert by_mark["M3"]["ok"] is False and by_mark["M3"]["why"].startswith("blocked")
    table, failing = scenarios.summarise(cat, [results])
    assert failing == 1 and "| M3 |" in table
