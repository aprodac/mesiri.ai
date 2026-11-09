# ruff: noqa: F811 -- pytest fixtures imported from the schedule contract test are used as test arguments
"""GM-05: this week's board on a real Postgres (run with `pytest -m integration`).

The week's activities come from the schedule; its tasks are the Tasks module's (given there, ticked there); a task
due before this week and still open has slipped. The Monday note names the week's tasks.
"""

from __future__ import annotations

import datetime

import pytest

from contract.company_day import company_today
from contract.test_schedule_contract import _exec, _h, _patch, _section, client, ctx, test_engine  # noqa: F401
from mesiri.domains.schedule import week

pytestmark = pytest.mark.integration
D = datetime.timedelta(days=1)


async def _task(client, ctx, title, due) -> dict:
    r = await client.post("/tasks", headers=_h(ctx["admin"]), json={"project_id": str(ctx["project"]), "title": title,
                                                                    "due_date": str(due)})
    assert r.status_code == 201, r.text
    return r.json()


async def test_board_reads_the_schedule_and_the_tasks_module(client, ctx, test_engine):
    mon = week.monday(company_today())
    slab = await _section(client, ctx, "Slab 6F")
    assert (await _patch(client, ctx, slab, start=str(mon), end=str(mon + 3 * D))).status_code == 200
    await _task(client, ctx, "Concrete pump booked", mon + 2 * D)
    old = await _task(client, ctx, "Fix water line", mon + 2 * D)
    await _exec(test_engine, "UPDATE tasks SET due_date = :d WHERE id = :id", d=mon - 5 * D, id=old["id"])
    board = (await client.get(f"/projects/{ctx['project']}/week", headers=_h(ctx["admin"]))).json()
    assert board["week_start"] == str(mon) and board["tasks_module"] is True
    assert [a["name"] for a in board["activities"]] == ["Slab 6F"]
    assert [t["title"] for t in board["tasks"]] == ["Concrete pump booked"]
    assert [s["title"] for s in board["slipped"] if s["kind"] == "task"] == ["Fix water line"]
    later = (await client.get(f"/projects/{ctx['project']}/week", headers=_h(ctx["admin"]),
                              params={"start": str(mon + 9 * D)})).json()
    assert later["week_start"] == str(mon + 7 * D) and later["tasks"] == []


async def test_the_monday_note_carries_the_tasks(client, ctx, test_engine):
    from mesiri.domains.schedule.reminders import WEEK_RULE, queue_schedule_reminders

    mon = week.monday(company_today())
    await _task(client, ctx, "Concrete pump booked", mon + 2 * D)
    slab = await _section(client, ctx, "Slab 6F")
    await _patch(client, ctx, slab, start=str(mon), end=str(mon + 3 * D))
    await _exec(test_engine, "UPDATE projects SET stage = 'running' WHERE id = :p", p=ctx["project"])
    async with test_engine.begin() as conn:
        await queue_schedule_reminders(conn, ctx["org"], mon)
    rows = list(await _exec(test_engine, "SELECT payload FROM notifications WHERE rule_key = :r AND recipient_user_id = :u",
                            r=WEEK_RULE, u=ctx["admin_id"]))
    assert rows and "Tasks this week: Concrete pump booked" in rows[0].payload["message"]
