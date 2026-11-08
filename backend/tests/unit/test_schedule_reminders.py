"""ST-04: the WhatsApp notes about the schedule (domains/schedule/reminders.py), pure."""

from __future__ import annotations

import datetime

from mesiri.domains.schedule.reminders import delay_message, week_message

MON = datetime.date(2026, 11, 9)


def _a(i, name, start, end, state, **extra):
    return {"id": i, "name": name, "start": start, "end": end, "state": state, "milestone": False, "progress": None,
            "actual_start": None, "days_late": 0, "slip_days": 0, "forecast_end": None, "pushed_days": 0, "after": [], **extra}


def _sched(acts, **summary):
    return {"activities": acts, "summary": {"forecast_finish": None, "slip_days": 0, "contract_finish": None,
                                            "planned_finish": None, **summary}}


def test_delay_note_names_the_late_work_what_it_pushes_and_the_finish():
    acts = [
        _a("e", "Excavation", MON - datetime.timedelta(9), MON - datetime.timedelta(3), "late", progress=60,
           days_late=3, slip_days=4, forecast_end=MON + datetime.timedelta(1)),
        _a("f", "Footings", MON, MON + datetime.timedelta(6), "not_started", pushed_days=4, after=[{"id": "e", "lag": 0}]),
    ]
    note = delay_message("Villa", _sched(acts, forecast_finish=datetime.date(2027, 3, 24), slip_days=4,
                                          contract_finish=datetime.date(2027, 3, 20)))
    assert "*Excavation* is 3 days late, 60% done: at this pace it finishes Tue 10 Nov and pushes Footings." in note
    assert "Forecast finish Wed 24 Mar, 4 days after the contract date (Sat 20 Mar)." in note


def test_no_delay_note_when_all_is_on_time():
    assert delay_message("Villa", _sched([_a("a", "A", MON, MON, "on_track")])) is None


def test_week_note_lists_starts_finishes_and_late_in_order():
    acts = [
        _a("a", "Brickwork", MON - datetime.timedelta(5), MON + datetime.timedelta(2), "on_track", progress=70),
        _a("w", "Waterproofing", MON - datetime.timedelta(2), MON + datetime.timedelta(20), "behind"),
        _a("b", "Plastering", MON + datetime.timedelta(3), MON + datetime.timedelta(20), "not_started"),
        _a("c", "Slab cast", MON + datetime.timedelta(4), MON + datetime.timedelta(4), "not_started", milestone=True),
        _a("d", "Excavation", MON - datetime.timedelta(9), MON - datetime.timedelta(3), "late", days_late=3),
        _a("e", "Painting", MON + datetime.timedelta(30), MON + datetime.timedelta(40), "not_started"),
    ]
    note = week_message("Villa", _sched(acts), MON)
    assert note.startswith("📅 *This week at Villa* (Mon 9 Nov - Sun 15 Nov)")
    assert "Starts: Plastering (Thu 12 Nov), Slab cast (milestone Fri 13 Nov)" in note
    assert "Should finish: Brickwork (Wed 11 Nov, 70% now)" in note
    assert "⚠️ Late: Excavation (3 days)" in note
    assert "⚠️ Should have started: Waterproofing (Sat 7 Nov)" in note and "Continues" not in note
    assert "Painting" not in note


def test_no_week_note_for_an_empty_week():
    assert week_message("Villa", _sched([]), MON) is None


def test_delay_note_says_not_started_instead_of_zero_percent_behind():
    a = _a("s", "Superstructure", MON - datetime.timedelta(17), MON + datetime.timedelta(20), "behind", progress=0)
    note = delay_message("Villa", _sched([a]))
    assert "*Superstructure* has not started (planned Fri 23 Oct)." in note and "0% done" not in note
