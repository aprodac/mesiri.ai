"""GM-05: this week's board -- the schedule's activities in the week, the Tasks module's tasks due in it, what
slipped -- and the Monday note that carries it."""

from __future__ import annotations

import datetime

from mesiri.domains.schedule import reminders, week

MON = datetime.date(2026, 11, 9)
D = datetime.timedelta(days=1)


def _a(i, name, start, end, **over):
    return {"id": i, "name": name, "start": start, "end": end, "site_id": None, "site_name": None, "progress": 0,
            "state": "on_track", "done": False, "critical": False, "milestone": False, "days_late": 0,
            "actual_start": None, "forecast_end": None, **over}


def _t(i, title, due, status="open", **over):
    return {"id": i, "ref": f"T-{i}", "title": title, "due_date": due, "status": status, "site_id": None,
            "assignee_name": "Arun", "site_name": None, **over}


def test_board_has_the_weeks_activities_tasks_and_what_slipped():
    sched = {"activities": [
        _a("a1", "Slab 6F", MON - 3 * D, MON + 2 * D, progress=40),
        _a("a2", "Plastering", MON - 20 * D, MON - 3 * D, state="late"),
        _a("a3", "Painting", MON + 10 * D, MON + 20 * D),
        _a("a4", "Footings", MON - 20 * D, MON - 10 * D, done=True)]}
    tasks = [_t("1", "Pump booked", str(MON + 3 * D)), _t("2", "Water line", str(MON - 4 * D)),
             _t("3", "Done early", str(MON + D), status="done"), _t("4", "Old done", str(MON - 4 * D), status="done"),
             _t("5", "Cancelled", str(MON + D), status="cancelled"), _t("6", "No date", None)]
    b = week.board(sched, tasks, MON, MON + D)
    assert [a["id"] for a in b["activities"]] == ["a1"]
    assert b["activities"][0]["days"] == [str(MON), str(MON + D), str(MON + 2 * D)]
    assert [t["id"] for t in b["tasks"]] == ["3", "1"] and b["tasks"][0]["done"]
    assert [(s["kind"], s["id"]) for s in b["slipped"]] == [("activity", "a2"), ("task", "2")]
    assert b["counts"]["tasks"] == 2 and b["counts"]["tasks_done"] == 1 and b["counts"]["slipped"] == 2


def test_one_sites_board_keeps_the_projects_own_tasks():
    tasks = [_t("1", "A job", str(MON), site_id="A"), _t("2", "B job", str(MON), site_id="B"), _t("3", "Whole", str(MON))]
    assert [t["id"] for t in week.board({"activities": []}, tasks, MON, MON, "A")["tasks"]] == ["1", "3"]


def test_monday_note_names_tasks_due_and_overdue_and_stays_quiet_when_empty():
    tasks = [_t("1", "Pump booked", MON + 3 * D), _t("2", "Water line", MON - 4 * D),
             _t("3", "Done", MON + D, status="done")]
    note = reminders.week_message("Marina", {"activities": []}, MON, tasks)
    assert "Tasks this week: Pump booked (Arun, Thu 12 Nov)" in note
    assert "⚠️ Tasks overdue: Water line (Arun, Thu 5 Nov)" in note and "Done" not in note
    assert reminders.week_message("Marina", {"activities": []}, MON, []) is None
