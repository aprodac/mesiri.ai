"""UX-71: the moments the "a day passes" scene shows, picked from what the cast played (sandbox_player.pick_highlights)."""

from __future__ import annotations

from mesiri.application.learn import sample_plan as sp
from mesiri.application.learn import sandbox_player as pl


def test_a_day_shows_its_first_work_and_the_notable_kinds_only() -> None:
    day = [e for e in sp.plan().entries if e.day == 3]
    picked = pl.pick_highlights(day)
    assert picked, "day 3 has orders"
    assert all(h["kind"] in pl.NOTABLE or h["kind"] == "work" for h in picked)
    assert sum(h["kind"] == "work" for h in picked) <= 1
    assert len(picked) <= pl.HIGHLIGHTS_A_DAY
    assert {h["who"] for h in picked} <= set(sp.WHO.values())


def test_a_week_is_capped_in_order_and_names_who() -> None:
    week = [e for e in sp.plan().entries if 1 <= e.day <= 7]
    picked = pl.pick_highlights(week)
    assert 0 < len(picked) <= pl.HIGHLIGHTS_MAX
    assert [h["day"] for h in picked] == sorted(h["day"] for h in picked)
    for d in {h["day"] for h in picked}:
        assert sum(h["day"] == d for h in picked) <= pl.HIGHLIGHTS_A_DAY


def test_routine_entries_never_show() -> None:
    routine = [e for e in sp.plan().entries if e.kind in ("attendance", "use", "conditions")][:50]
    assert pl.pick_highlights(routine) == []


def test_nothing_played_nothing_shown() -> None:
    assert pl.pick_highlights([]) == []
