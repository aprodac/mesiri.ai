"""ST-04: the schedule's maths (domains/schedule/logic.py), pure."""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest

from mesiri.domains.schedule import logic

D = datetime.date


def act(i, start, end, **extra):
    return {"id": i, "name": i, "start": start, "end": end, "milestone": False, "done": False, "progress": None,
            "actual_start": None, "actual_end": None, **extra}


def link(p, s, lag=0):
    return {"predecessor": p, "successor": s, "lag": lag}


# -- the worked example in the module docstring -------------------------------------------------------------------

EXC = act("exc", D(2026, 11, 1), D(2026, 11, 5), progress=Decimal("0.6"), actual_start=D(2026, 11, 1))
FTG = act("ftg", D(2026, 11, 6), D(2026, 11, 12))
SLAB = act("slab", D(2026, 11, 13), D(2026, 11, 20))
LINKS = [link("exc", "ftg"), link("ftg", "slab")]
TODAY = D(2026, 11, 8)


def test_worked_example_late_and_forecast():
    a = logic.assess(EXC, TODAY)
    assert a["state"] == logic.LATE
    assert a["days_late"] == 3
    assert a["forecast_end"] == D(2026, 11, 12)
    assert a["slip_days"] == 7


def test_worked_example_knock_on_pushes_everything_after():
    k = logic.knock_on([EXC, FTG, SLAB], LINKS, TODAY)
    assert k["moves"] == {"exc": 7, "ftg": 7, "slab": 7}
    assert k["planned_finish"] == D(2026, 11, 20)
    assert k["forecast_finish"] == D(2026, 11, 27)
    assert k["slip_days"] == 7


# -- progress from measured lines ---------------------------------------------------------------------------------

def test_line_progress_weighted_by_value_when_every_line_has_one():
    lines = [
        {"planned_quantity": "100", "done_quantity": "100", "contract_value": "90000"},
        {"planned_quantity": "10", "done_quantity": "0", "contract_value": "10000"},
    ]
    assert logic.line_progress(lines) == Decimal("0.9")


def test_line_progress_equal_weights_when_a_value_is_missing_and_caps_at_full():
    lines = [{"planned_quantity": "10", "done_quantity": "30"}, {"planned_quantity": "10", "done_quantity": "0",
                                                                  "contract_value": "5"}]
    assert logic.line_progress(lines) == Decimal("0.5")


def test_line_progress_none_without_lines():
    assert logic.line_progress([]) is None
    assert logic.line_progress([{"planned_quantity": "0", "done_quantity": "5"}]) is None


# -- states -------------------------------------------------------------------------------------------------------

def test_not_started_before_its_start():
    assert logic.assess(act("a", D(2026, 11, 10), D(2026, 11, 12)), TODAY)["state"] == logic.NOT_STARTED


def test_should_have_started_but_did_not_is_behind_and_forecasts_from_today():
    a = act("a", D(2026, 11, 6), D(2026, 11, 10))
    r = logic.assess(a, TODAY)
    assert r["state"] == logic.BEHIND
    assert r["forecast_end"] == D(2026, 11, 12)  # starts today, 5 days


def test_on_track_when_progress_matches_the_calendar():
    a = act("a", D(2026, 11, 5), D(2026, 11, 14), progress=Decimal("0.3"), actual_start=D(2026, 11, 5))
    assert logic.assess(a, TODAY)["state"] == logic.ON_TRACK


def test_behind_when_progress_lags_the_calendar_by_more_than_the_margin():
    a = act("a", D(2026, 11, 1), D(2026, 11, 10), progress=Decimal("0.2"), actual_start=D(2026, 11, 1))
    r = logic.assess(a, TODAY)
    assert r["state"] == logic.BEHIND
    assert r["slip_days"] > 0


def test_done_by_flag_by_measure_or_by_actual_end():
    assert logic.assess(act("a", D(2026, 11, 1), D(2026, 11, 3), done=True), TODAY)["state"] == logic.DONE
    assert logic.assess(act("a", D(2026, 11, 1), D(2026, 11, 3), progress=Decimal(1)), TODAY)["state"] == logic.DONE
    late_finish = act("a", D(2026, 11, 1), D(2026, 11, 3), actual_end=D(2026, 11, 5))
    r = logic.assess(late_finish, TODAY)
    assert r["state"] == logic.DONE and r["days_late"] == 2


def test_unscheduled_without_dates():
    assert logic.assess(act("a", None, None), TODAY)["state"] == logic.UNSCHEDULED


def test_milestone_past_its_day_is_late():
    m = act("m", D(2026, 11, 5), D(2026, 11, 5), milestone=True)
    assert logic.assess(m, TODAY)["state"] == logic.LATE
    assert logic.duration(m) == 0


# -- push ---------------------------------------------------------------------------------------------------------

def test_push_moves_only_what_now_starts_too_early_and_keeps_lengths():
    acts = [act("a", D(2026, 11, 1), D(2026, 11, 5)), act("b", D(2026, 11, 6), D(2026, 11, 8)),
            act("c", D(2026, 11, 20), D(2026, 11, 22))]
    moved = logic.push(acts, [link("a", "b"), link("b", "c")], {"a": (D(2026, 11, 1), D(2026, 11, 10))})
    assert moved["b"] == (D(2026, 11, 11), D(2026, 11, 13))
    assert "c" not in moved  # had slack


def test_push_respects_lag_and_milestones():
    m = act("m", D(2026, 11, 5), D(2026, 11, 5), milestone=True)
    b = act("b", D(2026, 11, 5), D(2026, 11, 6))
    moved = logic.push([m, b], [link("m", "b", lag=2)], {"m": (D(2026, 11, 9), D(2026, 11, 9))})
    assert moved["b"] == (D(2026, 11, 11), D(2026, 11, 12))


def test_push_never_moves_done_or_earlier_work():
    acts = [act("a", D(2026, 11, 1), D(2026, 11, 5)), act("b", D(2026, 11, 6), D(2026, 11, 8), done=True)]
    assert "b" not in logic.push(acts, [link("a", "b")], {"a": (D(2026, 11, 1), D(2026, 11, 9))})


# -- cycles, critical path, conflicts ------------------------------------------------------------------------------

def test_makes_cycle():
    links = [link("a", "b"), link("b", "c")]
    assert logic.makes_cycle(links, "c", "a")
    assert logic.makes_cycle(links, "a", "a")
    assert not logic.makes_cycle(links, "a", "c")


def test_order_raises_on_a_cycle():
    with pytest.raises(logic.CycleError):
        logic.order(["a", "b"], [link("a", "b"), link("b", "a")])


def test_critical_path_is_the_chain_with_no_slack():
    acts = [act("a", D(2026, 11, 1), D(2026, 11, 5)), act("b", D(2026, 11, 6), D(2026, 11, 15)),
            act("c", D(2026, 11, 6), D(2026, 11, 8)), act("d", D(2026, 11, 16), D(2026, 11, 20))]
    links = [link("a", "b"), link("a", "c"), link("b", "d"), link("c", "d")]
    assert logic.critical(acts, links) == {"a", "b", "d"}


def test_conflicts_list_links_the_dates_break():
    acts = [act("a", D(2026, 11, 1), D(2026, 11, 5)), act("b", D(2026, 11, 4), D(2026, 11, 8))]
    assert logic.conflicts(acts, [link("a", "b")]) == [{"predecessor": "a", "successor": "b", "days": 2}]


def test_a_milestone_may_fall_on_the_day_its_predecessor_ends():
    acts = [act("work", D(2026, 11, 1), D(2026, 11, 10)), act("m", D(2026, 11, 10), D(2026, 11, 10), milestone=True)]
    assert logic.conflicts(acts, [link("work", "m")]) == []
    assert logic.push(acts, [link("work", "m")], {"work": (D(2026, 11, 1), D(2026, 11, 12))})["m"] == (
        D(2026, 11, 12), D(2026, 11, 12))
    assert logic.critical(acts, [link("work", "m")]) == {"work", "m"}


def test_import_headings_read_like_names():
    from mesiri.domains.progress.boq_import import heading_name

    assert heading_name("SITE PREPARATION & EARTHWORK") == "Site Preparation & Earthwork"
    assert heading_name("WORKS OF THE GROUND FLOOR") == "Works of the Ground Floor"
    assert heading_name("Ground floor RCC") == "Ground floor RCC"
