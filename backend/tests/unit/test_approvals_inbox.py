"""NXT-08 unit tests: how the approvals inbox puts its sources together (no database).

The contract tests (test_approvals_contract.py) cover each real source per role. Here: one source failing never
hides the others (and is named), a source the person may not use is left out quietly, a switched-off module is not
asked, the order is urgent first then oldest, and a subcontractor's flagged bill reads as urgent with the check's
words.
"""

from __future__ import annotations

import contextlib
import datetime
import uuid

import pytest
from fastapi import HTTPException

from mesiri.domains.approvals import inbox

TODAY = datetime.date(2026, 11, 9)


class _Conn:
    def begin_nested(self):
        @contextlib.asynccontextmanager
        async def nested():
            yield

        return nested()


class _Auth:
    organization_id = uuid.uuid4()
    user_id = uuid.uuid4()
    role = "ADMIN"


@pytest.fixture(autouse=True)
def _today(monkeypatch):
    async def today(conn, org):
        return TODAY

    monkeypatch.setattr(inbox, "_today", today)


def _source(*items):
    async def run(conn, auth, today):
        return list(items)

    return run


def _row(kind, since, urgent, title="x"):
    return inbox._item(kind, uuid.uuid4(), title, None, since=since, urgent=urgent)


async def test_urgent_first_then_oldest_and_counts(monkeypatch):
    monkeypatch.setattr(inbox, "SOURCES", {
        "site_report": _source(_row("site_report", "2026-11-09", False, "today"),
                               _row("site_report", "2026-11-08", True, "yesterday")),
        "material_request": _source(_row("material_request", "2026-11-01", False, "old request")),
        "subcontract_bill": _source(), "measurement": _source(), "ra_bill": _source(), "wage_sheet": _source(),
        "size_request": _source(), "task": _source(_row("task", "2026-11-07", True, "late")),
    })
    box = await inbox.waiting(_Conn(), _Auth(), lambda m: True)
    assert [i["title"] for i in box["items"]] == ["late", "yesterday", "old request", "today"]
    assert box["counts"]["site_report"] == 2 and box["total"] == 4 and box["urgent"] == 2


async def test_a_failing_source_is_named_and_hides_nothing_else(monkeypatch):
    async def broken(conn, auth, today):
        raise RuntimeError("database hiccup")

    async def refused(conn, auth, today):
        raise HTTPException(status_code=403, detail="Only the owner")

    async def odd(conn, auth, today):
        raise HTTPException(status_code=409, detail="?")

    monkeypatch.setattr(inbox, "SOURCES", {
        "site_report": _source(_row("site_report", "2026-11-09", False)), "material_request": broken,
        "subcontract_bill": refused, "measurement": _source(), "ra_bill": odd, "wage_sheet": _source(),
        "size_request": _source(), "task": _source(),
    })
    box = await inbox.waiting(_Conn(), _Auth(), lambda m: True)
    assert box["total"] == 1 and box["unavailable"] == ["material_request", "ra_bill"]  # a 403 is "not yours", quiet


async def test_a_switched_off_module_is_not_asked(monkeypatch):
    asked = []

    def spy(kind):
        async def run(conn, auth, today):
            asked.append(kind)
            return []

        return run

    monkeypatch.setattr(inbox, "SOURCES", {k: spy(k) for k in inbox.KINDS})
    await inbox.waiting(_Conn(), _Auth(), lambda m: m in ("dpr",))
    assert asked == ["site_report", "subcontract_bill", "measurement", "ra_bill"]  # materials and tasks are off


async def test_subcontract_bill_rows(monkeypatch):
    async def bills_waiting(auth_context, conn):
        return [
            {"id": uuid.uuid4(), "ref": "B-3", "vendor_name": "Ajay Tiling", "check_status": "flagged",
             "flags": [{"words": "Billed 120 sqm, measured 96"}], "created_at": "2026-11-05T10:00:00",
             "project_name": "Villa", "site_name": "Main", "work_order_id": uuid.uuid4(), "gross": "84000.00"},
            {"id": uuid.uuid4(), "ref": "B-4", "vendor_name": "Suresh Masonry", "check_status": "waiting", "flags": [],
             "created_at": "2026-11-08T09:00:00", "project_name": "Villa", "site_name": "Main",
             "work_order_id": uuid.uuid4(), "gross": "12000.00"},
        ]

    monkeypatch.setattr("mesiri.domains.subcontracts.router.bills_waiting", bills_waiting)
    rows = await inbox.subcontract_bills(_Conn(), _Auth(), TODAY)
    assert [(r["title"], r["urgent"], r["detail"]) for r in rows] == [
        ("Ajay Tiling: bill B-3", True, "Billed 120 sqm, measured 96"),
        ("Suresh Masonry: bill B-4", False, "Sent for approval")]
    assert rows[0]["work_order_id"] and rows[0]["amount"] == "84000.00"


async def test_roles_that_may_not_decide_get_no_rows():
    class SiteEngineer(_Auth):
        role = "SITE_ENGINEER"

    for source in (inbox.material_requests, inbox.subcontract_bills, inbox.ra_bills):
        assert await source(_Conn(), SiteEngineer(), TODAY) == []


async def test_wage_weeks_wait_to_be_approved_then_paid(monkeypatch):
    """LW-08: a past draft week asks for approval; an approved week with money due asks for payment (urgent once its
    pay day passed); this week's draft and a paid week are not waiting; a site engineer sees none of it."""
    import datetime as dt
    import uuid as _uuid

    def sheet(status, period_to, net, paid):
        return {"id": _uuid.uuid4(), "project_id": _uuid.uuid4(), "project_name": "Villa", "site_id": None,
                "site_name": "Main", "period_from": period_to - dt.timedelta(days=6), "period_to": period_to,
                "status": status, "net": net, "paid": paid}

    today = dt.date(2026, 11, 18)
    sheets = [sheet("draft", dt.date(2026, 11, 14), 9550, 0),       # last week, not approved: waiting
              sheet("draft", dt.date(2026, 11, 21), 4000, 0),       # this week: not yet
              sheet("approved", dt.date(2026, 11, 7), 9000, 5000),  # approved, 4,000 still due, pay day passed: urgent
              sheet("approved", dt.date(2026, 10, 31), 8000, 8000)]  # paid in full: not waiting

    async def list_sheets(conn, org, scope, project_id=None, site_id=None):
        return sheets

    monkeypatch.setattr("mesiri.domains.workforce.pay_store.list_sheets", list_sheets)

    class _Owner(_Auth):
        class project_scope:  # noqa: N801 - stands in for ProjectAccessScope
            grants_all_org_projects = True
            project_ids: set = set()

    items = await inbox.wage_sheets(_Conn(), _Owner(), today)
    assert [(i["detail"], i["urgent"]) for i in items] == [("Draft: check and approve", False),
                                                          ("Approved: ₹4,000 to pay", True)]

    class _Engineer(_Owner):
        role = "SITE_ENGINEER"

    assert await inbox.wage_sheets(_Conn(), _Engineer(), today) == []
