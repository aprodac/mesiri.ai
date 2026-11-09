# ruff: noqa: F811 -- pytest fixtures imported from the schedule contract test are used as test arguments
"""GM-08 with TSK-05: the morning brief on a real Postgres (run with `pytest -m integration`).

From 8 am company time, once a day: the person's act-now alerts (an old high issue), what waits for them, their tasks
due. Not before 8; not twice; not to someone who turned it off; nothing when there is nothing to say.
"""

from __future__ import annotations

import datetime
import uuid

import pytest

from contract.company_day import company_today
from contract.test_schedule_contract import _exec, _h, client, ctx, test_engine  # noqa: F401
from mesiri.domains.attention.brief import RULE, queue_morning_briefs

pytestmark = pytest.mark.integration


async def _briefs(test_engine, user) -> list:
    return list(await _exec(test_engine, "SELECT payload FROM notifications WHERE rule_key = :r AND recipient_user_id = :u",
                            r=RULE, u=user))


async def _run(test_engine, org, hour: int) -> int:
    today = company_today()
    async with test_engine.begin() as conn:
        return await queue_morning_briefs(conn, org, today, datetime.datetime.combine(today, datetime.time(hour, 5)))


async def test_brief_from_eight_once_a_day_and_off_when_asked(client, ctx, test_engine):
    await _exec(test_engine, "UPDATE users SET full_name = 'Ilan Usman', "
                "reply_language = 'english' WHERE id = :u", u=ctx["admin_id"])
    await _exec(test_engine, "INSERT INTO site_issues (id, organization_id, project_id, site_id, issue_type, severity, "
                "narrative, occurred_at, status) VALUES (:id, :org, :p, :s, 'OTHER', 'HIGH', 'No water at the site', "
                "now() - interval '4 days', 'OPEN')", id=uuid.uuid4(), org=ctx["org"], p=ctx["project"], s=ctx["site"])
    r = await client.post("/tasks", headers=_h(ctx["admin"]), json={
        "project_id": str(ctx["project"]), "title": "Tie steel grid B", "due_date": str(company_today()),
        "assignee_user_id": str(ctx["admin_id"])})
    assert r.status_code == 201, r.text

    assert await _run(test_engine, ctx["org"], 7) == 0 and await _briefs(test_engine, ctx["admin_id"]) == []
    assert await _run(test_engine, ctx["org"], 8) == 1
    msg = (await _briefs(test_engine, ctx["admin_id"]))[0].payload["message"]
    assert msg.startswith("☀️ *Good morning, Ilan*")
    assert "Open 4 days: No water at the site" in msg and "Tie steel grid B" in msg and "1 due today" in msg
    assert await _run(test_engine, ctx["org"], 9) == 0 and len(await _briefs(test_engine, ctx["admin_id"])) == 1

    off = await client.put("/me/morning-brief", headers=_h(ctx["admin"]), json={"on": False})
    assert off.status_code == 200 and off.json() == {"morning_brief": False}
    assert (await client.get("/me/preferences", headers=_h(ctx["admin"]))).json()["morning_brief"] is False
    await _exec(test_engine, "DELETE FROM notifications WHERE rule_key = :r", r=RULE)
    assert await _run(test_engine, ctx["org"], 10) == 0
