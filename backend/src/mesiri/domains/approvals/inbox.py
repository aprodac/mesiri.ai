"""Approvals inbox (NXT-08): one "waiting for you" list, read from what each module already keeps.

No approval table and no copy of anyone's rules. Each source asks its module's OWN list route as the caller, so a
row is in the inbox exactly when that module's page would show it to this person, and the person may act on it
there: the same project and site access (BE-42), the same module switch, the same role rule for who decides.

Sources, and who they are waiting for:

- ``site_report``: site days (today and yesterday) with entries still to confirm. Anyone who reaches the site (the
  DPR page's own rule).
- ``material_request``: requests waiting for the office. Those who may decide one (``may_act_on_material_requests``).
- ``subcontract_bill``: a subcontractor's bill flagged by the check or sent for approval. Those who see spending
  (the approve route's own rule).
- ``ra_bill``: a client RA bill still in draft. Those who see client bills (``may_manage_money``).
- ``wage_sheet``: a past pay week to approve or pay. The roles that see wages.
- ``labour_split``: BOQ-02c, the last 7 days' labour Mesiri put on BOQ lines by itself, or on no line, per project,
  for a person to confirm. The roles that see the BOQ (cost control's own route, asked as the caller).
- ``task``: my own tasks, overdue or due today (the tasks module).
- ``stock_count``: UX-62, a stock count with something counted, still open. Those who may approve one (an admin or
  owner, D-P2-2: the count's own ``may_approve``). Urgent after ``STOCK_COUNT_STALE_DAYS`` days: the book is frozen
  at its start, so a count left open drifts from the site.

A source the person may not use is left out; a source that fails is named in ``unavailable`` so the page can say
so, and never hides the rest.
"""

from __future__ import annotations

import datetime
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.authorization.roles import (
    may_act_on_material_requests,
    may_manage_money,
    may_view_expenses,
)

logger = logging.getLogger(__name__)

KINDS = ("site_report", "material_request", "subcontract_bill", "ra_bill", "wage_sheet", "labour_split", "task",
         "stock_count")
#: The module each source belongs to (``organization.settings.MODULES``); None: always on.
MODULE_OF = {"site_report": "dpr", "material_request": "materials", "subcontract_bill": None, "ra_bill": "dpr",
             "wage_sheet": "labour", "labour_split": "cost", "task": "tasks", "stock_count": "materials"}
#: BOQ-02c: how far back labour splits are asked about (older ones are on the Budget page, never nagged about).
LABOUR_SPLIT_DAYS = 7
RA_DRAFT_STALE_DAYS = 7
STOCK_COUNT_STALE_DAYS = 3


def _item(kind: str, id_: Any, title: str, detail: str | None, *, since: Any, urgent: bool,
          project_id: Any = None, project_name: str | None = None, site_id: Any = None,
          site_name: str | None = None, ref: str | None = None, **ids: Any) -> dict[str, Any]:
    return {"kind": kind, "id": str(id_), "ref": ref, "title": title, "detail": detail,
            "project_id": str(project_id) if project_id else None, "project_name": project_name,
            "site_id": str(site_id) if site_id else None, "site_name": site_name,
            "since": since.isoformat() if isinstance(since, datetime.date | datetime.datetime) else since,
            "urgent": bool(urgent), **{k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in ids.items()}}


def _day(value: Any) -> str:
    """'8 Nov' from a date or ISO string (both channels show it as is); '' when there is none."""
    if not value:
        return ""
    day = value if isinstance(value, datetime.date) else datetime.date.fromisoformat(str(value)[:10])
    return f"{day.day} {day:%b}"


def _qty(value: Any) -> str:
    text = f"{value}"
    return text.rstrip("0").rstrip(".") if "." in text else text


async def _today(conn: AsyncConnection, org: uuid.UUID) -> datetime.date:
    from mesiri.application.dpr.project_day import company_today

    return await company_today(conn, org)


async def site_reports(conn: AsyncConnection, auth: AuthorizationContext, today: datetime.date) -> list[dict]:
    from mesiri.domains.dpr.router import list_site_days

    out = []
    for day in (today, today - datetime.timedelta(days=1)):
        listed = await list_site_days(report_date=day, project_id=None, auth_context=auth, conn=conn)
        for s in listed["items"]:
            n = int(s.get("drafts") or 0)
            if n <= 0:
                continue
            out.append(_item(
                "site_report", f"{s['site_id']}:{day.isoformat()}", f"{s['site_name']}: {n} to confirm",
                "Yesterday's report is still open" if day < today else "Today's updates from site",
                since=day, urgent=day < today, project_id=s["project_id"], project_name=s.get("project_name"),
                site_id=s["site_id"], site_name=s["site_name"], date=day.isoformat(), count=n))
    return out


async def material_requests(conn: AsyncConnection, auth: AuthorizationContext, today: datetime.date) -> list[dict]:
    if not may_act_on_material_requests(auth.role):
        return []
    from mesiri.domains.procurement.router import list_requests

    listed = await list_requests(status="waiting", project_id=None, site_id=None, requested_by=None,
                                 category_id=None, urgency=None, mine=False, auth_context=auth, conn=conn)
    out = []
    for r in listed["items"]:
        lines = r.get("lines") or []
        what = ", ".join(f"{ln.get('material')} {_qty(ln.get('quantity'))} {ln.get('unit') or ''}".strip()
                         for ln in lines[:2]) or (r.get("purpose") or "Material request")
        if len(lines) > 2:
            what += f" +{len(lines) - 2} more"
        who = r.get("requested_by_name")
        needed = r.get("needed_by")
        detail = " · ".join(x for x in (f"from {who}" if who else None,
                                         f"needed by {_day(needed)}" if needed else None) if x)
        out.append(_item("material_request", r["id"], what, detail or None, since=r.get("created_at"),
                         urgent=r.get("urgency") == "late", project_id=r.get("project_id"),
                         project_name=r.get("project_name"), site_id=r.get("site_id"), site_name=r.get("site_name"),
                         ref=r.get("ref")))
    return out


async def subcontract_bills(conn: AsyncConnection, auth: AuthorizationContext, today: datetime.date) -> list[dict]:
    if not may_view_expenses(auth.role):
        return []
    from mesiri.domains.subcontracts.router import bills_waiting

    out = []
    for b in await bills_waiting(auth_context=auth, conn=conn):
        flagged = b.get("check_status") == "flagged"
        why = (b.get("flags") or [{}])[0].get("words") if flagged else None
        ref = b.get("ref")
        out.append(_item("subcontract_bill", b["id"], f"{b.get('vendor_name') or 'Subcontractor'}: bill {ref or ''}".strip(),
                         why or ("Sent for approval" if not flagged else "Flagged by the check"),
                         since=b.get("created_at"), urgent=flagged, project_name=b.get("project_name"),
                         site_name=b.get("site_name"), ref=ref, work_order_id=b.get("work_order_id"),
                         amount=str(b["gross"]) if b.get("gross") is not None else None))
    return out


async def ra_bills(conn: AsyncConnection, auth: AuthorizationContext, today: datetime.date) -> list[dict]:
    if not may_manage_money(auth.role):
        return []
    from mesiri.domains.billing.router import list_ra_bills

    out = []
    for b in await list_ra_bills(project_id=None, auth=auth, conn=conn):
        if b.get("status") != "draft":
            continue
        made = b.get("created_at")
        made_day = datetime.date.fromisoformat(str(made)[:10]) if made else today
        out.append(_item("ra_bill", b["id"], f"{b.get('ref')} for {b.get('client_name') or b.get('project_name')}",
                         "Draft: check and submit to the client", since=made, ref=b.get("ref"),
                         urgent=(today - made_day).days >= RA_DRAFT_STALE_DAYS, project_id=b.get("project_id"),
                         project_name=b.get("project_name"), amount=b.get("net")))
    return out


async def tasks(conn: AsyncConnection, auth: AuthorizationContext, today: datetime.date) -> list[dict]:
    from mesiri.domains.tasks.router import list_tasks

    listed = await list_tasks(project_id=None, site_id=None, assignee="me", status="live", due="today", q=None,
                              limit=100, auth=auth, conn=conn)
    out = []
    for t in listed["items"]:
        due = t.get("due_date")
        overdue = bool(due) and str(due) < today.isoformat()
        out.append(_item("task", t["id"], f"{t.get('ref')}: {t.get('title')}",
                         (f"Was due {_day(due)}" if overdue else "Due today") if due else None,
                         since=due, urgent=overdue, project_id=t.get("project_id"),
                         project_name=t.get("project_name"), site_id=t.get("site_id"), site_name=t.get("site_name"),
                         ref=t.get("ref")))
    return out


async def wage_sheets(conn: AsyncConnection, auth: AuthorizationContext, today: datetime.date) -> list[dict]:
    """LW-08: a past pay week still in draft (approve it), or approved with money still due (pay it; urgent once its pay
    day has passed). The roles that see wages only."""
    if not may_view_expenses(auth.role):
        return []
    from mesiri.domains.workforce import pay_store

    scope = None if auth.project_scope.grants_all_org_projects else set(auth.project_scope.project_ids)
    out = []
    for w in await pay_store.list_sheets(conn, auth.organization_id, scope):
        net, paid = float(w["net"] or 0), float(w["paid"] or 0)
        where = w["site_name"] or w["project_name"]
        week = f"{w['period_from']:%d %b}–{w['period_to']:%d %b}"
        if w["status"] == "draft" and net > 0 and w["period_to"] < today:
            out.append(_item("wage_sheet", w["id"], f"Wages {week}: {where}", "Draft: check and approve",
                             since=w["period_to"], urgent=False, project_id=w["project_id"], project_name=w["project_name"],
                             site_id=w["site_id"], site_name=w["site_name"], amount=str(net), period_from=str(w["period_from"])))
        elif w["status"] == "approved" and net - paid > 0.005:
            out.append(_item("wage_sheet", w["id"], f"Wages {week}: {where}", f"Approved: ₹{net - paid:,.0f} to pay",
                             since=w["period_to"], urgent=w["period_to"] < today, project_id=w["project_id"],
                             project_name=w["project_name"], site_id=w["site_id"], site_name=w["site_name"],
                             amount=str(net - paid), period_from=str(w["period_from"])))
    return out


async def labour_splits(conn: AsyncConnection, auth: AuthorizationContext, today: datetime.date) -> list[dict]:
    """BOQ-02c: per running project, the last ``LABOUR_SPLIT_DAYS`` days' site-day-trades Mesiri put on BOQ lines by
    itself (``auto``) or that are on no line, from cost control's own labour route as the caller. One row a project."""
    if not may_view_expenses(auth.role):
        return []
    from sqlalchemy import text

    from mesiri.domains.costing.router import project_labour

    rows = (await conn.execute(text(
        "SELECT p.id, p.name FROM projects p WHERE p.organization_id = :org AND lower(coalesce(p.status, 'active')) "
        "NOT IN ('completed', 'closed', 'archived', 'cancelled') ORDER BY p.name"),
        {"org": auth.organization_id})).mappings().all()
    scope = None if auth.project_scope.grants_all_org_projects else set(auth.project_scope.project_ids)
    out = []
    for p in rows:
        if scope is not None and p["id"] not in scope:
            continue
        listed = await project_labour(project_id=p["id"], date_from=today - datetime.timedelta(days=LABOUR_SPLIT_DAYS),
                                      date_to=today, unallocated=False, to_confirm=True, auth=auth, conn=conn)
        groups = listed["groups"]
        if not groups:
            continue
        auto = sum(1 for g in groups if g.get("auto"))
        off = len(groups) - auto
        detail = ", ".join(x for x in (f"{auto} put on lines by Mesiri" if auto else "",
                                       f"{off} on no line" if off else "") if x)
        out.append(_item("labour_split", f"labour:{p['id']}", f"Labour on the BOQ: {p['name']}",
                         f"{detail}: check and confirm", since=min(g["date"] for g in groups), urgent=False,
                         project_id=p["id"], project_name=p["name"], count=len(groups)))
    return out


async def stock_counts(conn: AsyncConnection, auth: AuthorizationContext, today: datetime.date) -> list[dict]:
    """UX-62: open stock counts this person may approve (the materials module's own list, asked as the caller)."""
    from mesiri.domains.materials.stock_count_router import list_counts

    listed = await list_counts(status="open", site_id=None, auth_context=auth, conn=conn)
    out = []
    for c in listed["items"]:
        if not c.get("may_approve"):
            continue
        made = c.get("created_at")
        made_day = datetime.date.fromisoformat(str(made)[:10]) if made else today
        n = c.get("counts") or {}
        differing = int(n.get("differing") or 0)
        detail = f"{n.get('counted', 0)} counted" + (f", {differing} differ" if differing else ", all match")
        out.append(_item("stock_count", c["id"], f"Stock count {c.get('ref')}: {c.get('site_name')}", detail,
                         since=made, urgent=(today - made_day).days >= STOCK_COUNT_STALE_DAYS, ref=c.get("ref"),
                         project_id=c.get("project_id"), project_name=c.get("project_name"),
                         site_id=c.get("site_id"), site_name=c.get("site_name"), count=differing,
                         amount=c.get("net_value")))
    return out


SOURCES: dict[str, Callable[[AsyncConnection, AuthorizationContext, datetime.date], Awaitable[list[dict]]]] = {
    "site_report": site_reports, "material_request": material_requests, "subcontract_bill": subcontract_bills,
    "ra_bill": ra_bills, "wage_sheet": wage_sheets, "labour_split": labour_splits, "task": tasks, "stock_count": stock_counts,
}


def _sort_key(item: dict) -> tuple:
    return (not item["urgent"], item["since"] or "9999", item["title"])


async def waiting(conn: AsyncConnection, auth: AuthorizationContext, enabled: Callable[[str], bool],
                  kinds: tuple[str, ...] = KINDS) -> dict[str, Any]:
    """Everything waiting for this person, urgent first, then oldest first; counts per kind; the sources that could
    not be read."""
    today = await _today(conn, auth.organization_id)
    items: list[dict] = []
    unavailable: list[str] = []
    for kind in kinds:
        module = MODULE_OF[kind]
        if module is not None and not enabled(module):
            continue
        try:
            async with conn.begin_nested():  # one source failing must not abort the others' reads
                items.extend(await SOURCES[kind](conn, auth, today))
        except HTTPException as exc:
            if exc.status_code not in (403, 404):
                unavailable.append(kind)
        except Exception:  # noqa: BLE001 -- the rest of the inbox still shows
            logger.exception("approvals.source_failed kind=%s", kind)
            unavailable.append(kind)
    items.sort(key=_sort_key)
    counts = {k: sum(1 for i in items if i["kind"] == k) for k in kinds}
    return {"today": today.isoformat(), "total": len(items), "urgent": sum(1 for i in items if i["urgent"]),
            "counts": counts, "items": items, "unavailable": unavailable}
