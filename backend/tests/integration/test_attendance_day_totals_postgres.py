"""WA-287 (live check of WA-283, 13 Nov 2026, Mesiri Test Builders): "How many workers at Main Block today?" looked up
`GET /labour/attendance`, which lists each report as sent (16 in the morning: 6 masons, 8 helpers, 2 carpenters; then
4 masons and 6 helpers after a correction), and the model took the newest: 10. The Today page counts 12: a later report
replaces only the same trades, so the morning's 2 carpenters still count.

Fix: the list also gives ``day_totals``, per site and day, by the Today page's own rule. This test holds that the two
agree on a real Postgres, and that a corrected report, a voided one and another site do not leak into a total."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import text

from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.authorization.context import AuthorizationContext, ProjectAccessScope, SiteAccessScope
from mesiri.domains.dpr.router import list_site_days
from mesiri.domains.workforce.router import list_attendance

from .test_live_questions_postgres import NOW, conn  # noqa: F401 -- the shared fixture

pytestmark = pytest.mark.integration
DAY = NOW.date()


async def _report(conn, made, site, lines, *, minutes, corrects=None, voided=False):  # noqa: F811
    rid = uuid.uuid4()
    await conn.execute(text(
        "INSERT INTO labour_attendance_reports (id, organization_id, project_id, site_id, occurred_date, recorded_via, "
        "created_at, created_by, corrects_report_id, voided_at) VALUES (:id, :org, :p, :s, :d, 'whatsapp_text', :at, :u, "
        ":c, :v)"),
        {"id": rid, "org": made.organization_id, "p": made.project_id, "s": site, "d": DAY,
         "at": NOW + dt.timedelta(minutes=minutes), "u": made.owner_user_id, "c": corrects,
         "v": NOW if voided else None})
    for trade, heads in lines:
        await conn.execute(text(
            "INSERT INTO labour_attendance_lines (id, report_id, trade, headcount) VALUES (gen_random_uuid(), :r, :t, :h)"),
            {"r": rid, "t": trade, "h": heads})
    return rid


def _auth(made, sites=None):
    project = ProjectAccessScope(mode="all_projects", project_ids=set())
    scope = SiteAccessScope(mode="all_sites", site_ids=set()) if sites is None else SiteAccessScope(
        mode="custom_sites", site_ids=set(sites))
    return AuthorizationContext(user_id=made.owner_user_id, organization_id=made.organization_id, role="ADMIN",
                                status="active", access_policy={},  # type: ignore[arg-type]
                                project_scope=project, site_scopes={made.project_id: scope})


async def _list(conn, auth, **kw):  # noqa: F811
    return await list_attendance(project_id=None, site_id=kw.get("site_id"), date_from=DAY, date_to=DAY, limit=50,
                                 offset=0, auth_context=auth, conn=conn)


async def test_the_reported_day_counts_twelve_as_the_today_page_does(conn) -> None:  # noqa: F811
    made = await create_company(conn, NewCompany(
        name="Day Total Builders", owner_name="Ravi Kumar", owner_phone="+919876500287", project_name="Live Check",
        site_names=("Main Block", "Site B"), auto_dpr=False), now=NOW)
    main, other = made.sites[0].site_id, made.sites[1].site_id
    await _report(conn, made, main, [("mason", 6), ("helper", 8), ("carpenter", 2)], minutes=0)
    first_pm = await _report(conn, made, main, [("mason", 5), ("helper", 6)], minutes=60)
    await _report(conn, made, main, [("mason", 4), ("helper", 6)], minutes=61, corrects=first_pm)  # "alla, 4 mason"
    await _report(conn, made, main, [("mason", 40)], minutes=62, voided=True)  # taken back: never counts
    await _report(conn, made, other, [("mason", 3)], minutes=5)

    auth = _auth(made)
    got = await _list(conn, auth, site_id=main)
    (day,) = got["day_totals"]
    assert day["workers"] == 12
    assert sorted((t["trade"], t["workers"]) for t in day["trades"]) == [("carpenter", 2), ("helper", 6), ("mason", 4)]
    # The reports themselves are still listed as sent (the audit view), so the total cannot be read off them.
    assert sorted(i["total_headcount"] for i in got["items"]) != [12]

    today = await list_site_days(report_date=DAY, project_id=None, auth_context=auth, conn=conn)
    workers = {str(s["site_id"]): s["workers"] for s in today["items"]}
    assert workers[str(main)] == day["workers"]  # the Today page and the attendance list agree
    every = await _list(conn, auth)
    assert {(str(d["site_id"]), d["workers"]) for d in every["day_totals"]} == {(str(main), 12), (str(other), 3)}


async def test_guard_a_person_limited_to_one_site_sees_only_its_total(conn) -> None:  # noqa: F811
    made = await create_company(conn, NewCompany(
        name="Scoped Builders", owner_name="Anu", owner_phone="+919876500288", project_name="Live Check",
        site_names=("Main Block", "Site B"), auto_dpr=False), now=NOW)
    main, other = made.sites[0].site_id, made.sites[1].site_id
    await _report(conn, made, main, [("mason", 6)], minutes=0)
    await _report(conn, made, other, [("helper", 9)], minutes=1)
    got = await _list(conn, _auth(made, sites=[other]))
    assert [(str(d["site_id"]), d["workers"]) for d in got["day_totals"]] == [(str(other), 9)]
