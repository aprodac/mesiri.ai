# ruff: noqa: F811 -- pytest fixtures imported from the schedule contract test are used as test arguments
"""GM-04: the attention feed on a real Postgres (run with `pytest -m integration`).

A late activity on the critical path and the handover it moves, an issue open for days with no owner, a site that
sent nothing after its cut-off: each read through its own module's route, as the caller. Snoozed: gone until the day
after, counted apart; brought back. A person on another project sees none of it.
"""

from __future__ import annotations

import datetime
import json
import uuid

import pytest

from contract.company_day import company_today
from contract.test_schedule_contract import (  # noqa: F401
    _exec,
    _h,
    _line,
    _patch,
    _section,
    _user,
    client,
    ctx,
    test_engine,
)

pytestmark = pytest.mark.integration
D = datetime.timedelta(days=1)


async def _feed(client, token, **params) -> dict:
    r = await client.get("/attention", headers=_h(token), params=params)
    assert r.status_code == 200, r.text
    return r.json()


async def _world(client, ctx, test_engine) -> dict:
    today = company_today()
    slab = await _section(client, ctx, "Slab 6F")
    await _line(client, ctx, slab, "Slab concrete M25", "48")   # a BOQ: the cost and material plan reads run too
    assert (await _patch(client, ctx, slab, start=str(today - 10 * D), end=str(today - 3 * D))).status_code == 200
    await _exec(test_engine, "UPDATE projects SET reporting_cutoff_time = '00:00' WHERE id = :p", p=ctx["project"])
    issue = uuid.uuid4()
    await _exec(test_engine, "INSERT INTO site_issues (id, organization_id, project_id, site_id, issue_type, severity, "
                "narrative, occurred_at, status) VALUES (:id, :org, :p, :s, 'OTHER', 'HIGH', 'No water at the site', "
                "now() - interval '4 days', 'OPEN')", id=issue, org=ctx["org"], p=ctx["project"], s=ctx["site"])
    return {"slab": slab, "issue": str(issue)}


async def test_late_work_old_issue_and_a_silent_site_each_say_what_and_the_page(client, ctx, test_engine):
    w = await _world(client, ctx, test_engine)
    out = await _feed(client, ctx["admin"])
    by = {a["key"]: a for a in out["items"]}
    late = by[f"late:{w['slab']}"]
    assert late["severity"] == "bad" and late["title"] == "Slab 6F is 3 days late"
    assert late["action"]["link"] == f"/planning/schedule?project={ctx['project']}"
    assert f"handover:{ctx['project']}" in by
    issue = by[f"issue:{w['issue']}"]
    assert issue["severity"] == "bad" and issue["title"] == "Open 4 days: No water at the site"
    assert issue["detail"] == "High · no one is on it" and issue["site_name"] == "Main building"
    silent = [a for a in out["items"] if a["kind"] == "unreported"]
    assert len(silent) == 1 and silent[0]["title"] == "Main building has not reported today"
    assert out["items"][0]["severity"] == "bad" and out["counts"]["total"] == len(out["items"])
    count = (await client.get("/attention/count", headers=_h(ctx["admin"]))).json()["counts"]
    assert count == out["counts"]


async def test_snooze_hides_it_until_tomorrow_and_unsnooze_brings_it_back(client, ctx, test_engine):
    w = await _world(client, ctx, test_engine)
    key = f"issue:{w['issue']}"
    before = await _feed(client, ctx["admin"])
    r = await client.post("/attention/snooze", headers=_h(ctx["admin"]), json={"key": key})
    assert r.status_code == 200 and r.json()["until"] == str(company_today())
    after = await _feed(client, ctx["admin"])
    assert key not in {a["key"] for a in after["items"]}
    assert [a["key"] for a in after["snoozed"]] == [key]
    assert after["counts"]["snoozed"] == 1 and after["counts"]["total"] == before["counts"]["total"] - 1
    # Snoozed for one person only.
    _, other_admin = await _user(test_engine, ctx["org"], "admin")
    assert key in {a["key"] for a in (await _feed(client, other_admin))["items"]}
    assert (await client.delete(f"/attention/snooze/{key}", headers=_h(ctx["admin"]))).status_code == 200
    assert key in {a["key"] for a in (await _feed(client, ctx["admin"]))["items"]}
    assert (await client.post("/attention/snooze", headers=_h(ctx["admin"]), json={"key": key, "days": 9})).status_code == 422


async def test_a_person_on_another_project_sees_none_of_it(client, ctx, test_engine):
    await _world(client, ctx, test_engine)
    other = uuid.uuid4()
    await _exec(test_engine, "INSERT INTO projects (id, organization_id, name, created_at, updated_at) "
                "VALUES (:id, :org, 'Elsewhere', now(), now())", id=other, org=ctx["org"])
    policy = json.dumps({"mode": "custom_projects", "projects": [
        {"projectId": str(other), "siteAccess": {"mode": "all_sites", "siteIds": []}}]})
    uid, eng = await _user(test_engine, ctx["org"], "site_engineer", policy)
    await _exec(test_engine, "INSERT INTO project_members (id, project_id, user_id) VALUES (:id, :p, :u)",
                id=uuid.uuid4(), p=other, u=uid)
    out = await _feed(client, eng)
    assert [a for a in out["items"] if a["project_id"] == str(ctx["project"])] == []
