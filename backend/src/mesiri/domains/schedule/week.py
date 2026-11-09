"""GM-05: this week's board -- the schedule's activities that fall in the week, and the Tasks module's tasks due in it.

Nothing is stored here. The activities are the schedule's (``store.load``): their progress comes from site work
updates (CC-04), so they tick themselves. The tasks are the Tasks module's (TSK, ``GET /tasks`` as the caller):
who does what by when, ticked through that module. **Slipped**: activities that should have finished before this
week and are not done, and tasks due before this week still open. Pure: the routes gather, this arranges.
"""

from __future__ import annotations

import datetime
from typing import Any

DAY = datetime.timedelta(days=1)
#: The site week: Monday to Saturday.
WORK_DAYS = 6
_LIVE = ("open", "doing", "blocked")


def monday(d: datetime.date) -> datetime.date:
    return d - DAY * d.weekday()


def _d(v: Any) -> datetime.date | None:
    if v is None or isinstance(v, datetime.date):
        return v
    return datetime.date.fromisoformat(str(v)[:10])


def board(schedule: dict[str, Any], tasks: list[dict[str, Any]], week_start: datetime.date, today: datetime.date,
          site_id: str | None = None) -> dict[str, Any]:
    """The week: its days, the activities in it (with the days each covers), the tasks due in it, and what slipped
    into it. ``tasks``: the project's tasks as ``GET /tasks`` gives them. ``site_id``: one site's (and the project's
    own, with no site)."""
    days = [week_start + DAY * i for i in range(WORK_DAYS)]
    week_end = days[-1]

    def site_ok(sid: Any) -> bool:
        return site_id is None or sid is None or str(sid) == str(site_id)

    activities, slipped = [], []
    for a in schedule.get("activities", []):
        start, end = _d(a.get("start")), _d(a.get("end"))
        if start is None or end is None or not site_ok(a.get("site_id")):
            continue
        item = {"id": str(a["id"]), "name": a["name"], "site_name": a.get("site_name"), "start": start.isoformat(),
                "end": end.isoformat(), "progress": a.get("progress"), "state": a.get("state"),
                "done": bool(a.get("done")), "critical": bool(a.get("critical")), "milestone": bool(a.get("milestone"))}
        if start <= week_end and end >= week_start:
            activities.append({**item, "days": [d.isoformat() for d in days if start <= d <= end],
                               "finishes_this_week": week_start <= end <= week_end})
        elif end < week_start and not item["done"]:
            slipped.append({**item, "kind": "activity", "days_late": (today - end).days})
    activities.sort(key=lambda x: (x["start"], x["name"]))

    week_tasks = []
    for t in tasks:
        due = _d(t.get("due_date"))
        if due is None or not site_ok(t.get("site_id")):
            continue
        row = {"id": str(t["id"]), "ref": t.get("ref"), "title": t["title"], "due_date": due.isoformat(),
               "status": t["status"], "done": t["status"] == "done", "assignee_name": t.get("assignee_name"),
               "site_name": t.get("site_name")}
        if week_start <= due <= week_end + DAY and t["status"] != "cancelled":
            week_tasks.append(row)
        elif due < week_start and t["status"] in _LIVE:
            slipped.append({**row, "kind": "task", "days_late": (today - due).days})
    week_tasks.sort(key=lambda x: (x["due_date"], x["title"]))

    return {
        "week_start": week_start.isoformat(), "days": [d.isoformat() for d in days], "today": today.isoformat(),
        "activities": activities, "tasks": week_tasks, "slipped": slipped,
        "counts": {"activities": len(activities),
                   "finishing": sum(1 for a in activities if a["finishes_this_week"]),
                   "finished": sum(1 for a in activities if a["finishes_this_week"] and a["done"]),
                   "critical": sum(1 for a in activities if a["critical"] and not a["done"]),
                   "tasks": len(week_tasks), "tasks_done": sum(1 for t in week_tasks if t["done"]),
                   "slipped": len(slipped)},
    }
