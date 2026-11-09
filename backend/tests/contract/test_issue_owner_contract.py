# ruff: noqa: F811 -- pytest fixtures imported from the schedule contract test are used as test arguments
"""GM-06: who is on an issue and by when, on a real Postgres (run with `pytest -m integration`).

Put someone on it with a date: saved, shown on the issue, and they are told on WhatsApp once. Remind: once a day.
Refused: someone not on the project, a date already gone, no one to remind, a closed issue. Past its date, the
attention feed says overdue and who said by when.
"""

from __future__ import annotations

import datetime
import json
import uuid

import pytest

from contract.company_day import company_today
from contract.test_schedule_contract import _exec, _h, _user, client, ctx, test_engine  # noqa: F401

pytestmark = pytest.mark.integration
D = datetime.timedelta(days=1)


async def _issue(test_engine, ctx) -> str:
    iid = uuid.uuid4()
    await _exec(test_engine, "INSERT INTO site_issues (id, organization_id, project_id, site_id, issue_type, severity, "
                "narrative, occurred_at, status) VALUES (:id, :org, :p, :s, 'OTHER', 'MEDIUM', 'Props short for 6F', "
                "now() - interval '1 day', 'OPEN')", id=iid, org=ctx["org"], p=ctx["project"], s=ctx["site"])
    return str(iid)


async def _member(test_engine, ctx, project) -> tuple:
    policy = json.dumps({"mode": "custom_projects", "projects": [
        {"projectId": str(project), "siteAccess": {"mode": "all_sites", "siteIds": []}}]})
    uid, token = await _user(test_engine, ctx["org"], "site_engineer", policy)
    await _exec(test_engine, "INSERT INTO project_members (id, project_id, user_id) VALUES (:id, :p, :u)",
                id=uuid.uuid4(), p=project, u=uid)
    return uid, token


async def _notes(test_engine, rule: str, recipient) -> list:
    rows = await _exec(test_engine, "SELECT recipient_user_id, payload FROM notifications WHERE rule_key = :r "
                       "AND recipient_user_id = :u", r=rule, u=recipient)
    return list(rows)


async def test_put_someone_on_it_tell_them_once_and_remind_once_a_day(client, ctx, test_engine):
    iid = await _issue(test_engine, ctx)
    anil, _ = await _member(test_engine, ctx, ctx["project"])
    due = company_today() + 2 * D
    r = await client.put(f"/progress/issues/{iid}/owner", headers=_h(ctx["admin"]), json={"assigned_user_id": str(anil), "due_on": str(due)})
    assert r.status_code == 200, r.text
    assert r.json()["assigned_user_id"] == str(anil) and r.json()["due_on"] == str(due) and r.json()["assigned_user_name"] == "T"
    notes = await _notes(test_engine, "issue_assigned", anil)
    assert len(notes) == 1 and notes[0].recipient_user_id == anil and "Props short for 6F" in json.dumps(notes[0].payload)
    # The same owner and date again: not told twice.
    await client.put(f"/progress/issues/{iid}/owner", headers=_h(ctx["admin"]), json={"assigned_user_id": str(anil), "due_on": str(due)})
    assert len(await _notes(test_engine, "issue_assigned", anil)) == 1
    first = await client.post(f"/progress/issues/{iid}/remind", headers=_h(ctx["admin"]))
    again = await client.post(f"/progress/issues/{iid}/remind", headers=_h(ctx["admin"]))
    assert first.json()["sent"] is True and again.json()["sent"] is False
    assert "already reminded today" in again.json()["message"]
    listed = (await client.get("/progress/issues", headers=_h(ctx["admin"]), params={"project_id": str(ctx["project"])})).json()["items"]
    assert listed[0]["due_on"] == str(due) and listed[0]["assigned_user_name"] == "T"


async def test_refusals(client, ctx, test_engine):
    iid = await _issue(test_engine, ctx)
    other_project = uuid.uuid4()
    await _exec(test_engine, "INSERT INTO projects (id, organization_id, name, created_at, updated_at) "
                "VALUES (:id, :org, 'Elsewhere', now(), now())", id=other_project, org=ctx["org"])
    stranger, _ = await _member(test_engine, ctx, other_project)
    h = _h(ctx["admin"])
    assert (await client.put(f"/progress/issues/{iid}/owner", headers=h, json={"assigned_user_id": str(stranger)})).status_code == 422
    assert (await client.put(f"/progress/issues/{iid}/owner", headers=h,
                             json={"due_on": str(company_today() - D)})).status_code == 422
    nobody = await client.post(f"/progress/issues/{iid}/remind", headers=h)
    assert nobody.status_code == 409 and "No one is on this issue" in nobody.text
    await _exec(test_engine, "UPDATE site_issues SET status = 'RESOLVED' WHERE id = :id", id=uuid.UUID(iid))
    assert (await client.put(f"/progress/issues/{iid}/owner", headers=h, json={})).status_code == 409


async def test_past_its_date_the_feed_says_overdue_and_who(client, ctx, test_engine):
    iid = await _issue(test_engine, ctx)
    anil, _ = await _member(test_engine, ctx, ctx["project"])
    await client.put(f"/progress/issues/{iid}/owner", headers=_h(ctx["admin"]), json={"assigned_user_id": str(anil)})
    await _exec(test_engine, "UPDATE site_issues SET due_on = CURRENT_DATE - 1 WHERE id = :id", id=uuid.UUID(iid))
    alerts = (await client.get("/attention", headers=_h(ctx["admin"]))).json()["items"]
    a = next(x for x in alerts if x["key"] == f"issue:{iid}")
    assert a["severity"] == "bad" and a["title"].startswith("Overdue since") and "T said by" in a["detail"]


async def test_by_name_as_said_on_whatsapp(client, ctx, test_engine):
    iid = await _issue(test_engine, ctx)
    anil, _ = await _member(test_engine, ctx, ctx["project"])
    await _exec(test_engine, "UPDATE users SET full_name = 'Anil Kumar' WHERE id = :u", u=anil)
    r = await client.put(f"/progress/issues/{iid}/owner", headers=_h(ctx["admin"]), json={"assigned_user_name": "anil"})
    assert r.status_code == 200, r.text
    assert r.json()["assigned_user_name"] == "Anil Kumar"
    nobody = await client.put(f"/progress/issues/{iid}/owner", headers=_h(ctx["admin"]), json={"assigned_user_name": "Biju"})
    assert nobody.status_code == 422 and "No one called Biju works on this project" in nobody.text
    other, _ = await _member(test_engine, ctx, ctx["project"])
    await _exec(test_engine, "UPDATE users SET full_name = 'Anil Raj' WHERE id = :u", u=other)
    two = await client.put(f"/progress/issues/{iid}/owner", headers=_h(ctx["admin"]), json={"assigned_user_name": "Anil"})
    assert two.status_code == 422 and "Anil Kumar" in two.text and "Anil Raj" in two.text
