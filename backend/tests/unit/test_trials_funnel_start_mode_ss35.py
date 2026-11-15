"""SS-35 (guided onboarding): the trials funnel split by how each owner chose to start, so the team sees which
kind of customer reaches a first update, a first DPR and conversion."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from mesiri.application.organizations.trials_funnel import START_MODE_LABELS, build_funnel

T0 = dt.datetime(2026, 11, 10, 4, tzinfo=dt.UTC)


def _company(i, *, update=False, dpr=False):
    return SimpleNamespace(
        id=i, name=f"T{i}", signup_source="whatsapp", effective_status="trial", trial_started_at=T0,
        trial_ends_at=None, converted_at=None,
        setup=SimpleNamespace(first_update_at=T0 if update else None, first_dpr_sent_at=T0 if dpr else None),
    )


def test_each_answer_gets_its_own_steps_most_trials_first() -> None:
    trials = [_company(1, update=True), _company(2), _company(3, update=True, dpr=True), _company(4)]
    funnel = build_funnel(trials, {}, {1: "guided", 2: "guided", 3: "bring_data", 4: "expert"})
    by_mode = {row["start_mode"]: row for row in funnel["by_start_mode"]}
    assert [row["start_mode"] for row in funnel["by_start_mode"]][0] == "guided"
    guided = {s["key"]: (s["count"], s["percent"]) for s in by_mode["guided"]["steps"]}
    assert guided["started"] == (2, 100) and guided["first_update"] == (1, 50)
    assert {s["key"]: s["count"] for s in by_mode["bring_data"]["steps"]}["first_dpr"] == 1
    assert by_mode[None]["label"] == START_MODE_LABELS[None]  # an unknown stored value counts as not answered
    assert [t["start_mode"] for t in funnel["trials"]] == ["guided", "guided", "bring_data", None]


def test_guard_the_overall_funnel_is_unchanged() -> None:
    trials = [_company(1, update=True), _company(2)]
    assert build_funnel(trials, {})["steps"] == build_funnel(trials, {}, {1: "free"})["steps"]
    assert build_funnel([], {})["by_start_mode"] == []
