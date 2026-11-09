"""GM-01: "Waiting for you" -- one list of what is waiting for the caller's decision, over each module's own statuses.

A read model, not an approval system: nothing is stored here and nothing is decided here. Each source reads its
module's own records through the module's own read code, keeps only what the caller may decide by that module's own
rule, and becomes one row of the same shape. The dashboard and the assistant decide through the module's own route.
Plan: docs/plans/gm-pm-plan.md (GM-01).

Sources, each with the rule that says who decides (the module's, never a second copy):

=================  ======================================  ===============================  ========================
kind               waiting means                           who decides                      module switch
=================  ======================================  ===============================  ========================
material_request   ``material_requests.status = waiting``  ``may_act_on_material_requests``  materials
                   and no open order covers it               (owner, admin, PM)
subcontract_bill   ``work_order_bills.check_status`` is    ``may_view_expenses``             --
                   ``waiting`` or ``flagged``                (owner, admin, finance, PM)
measurement        ``work_order_measurements.status =      whoever may record work at the    --
                   proposed`` (the subcontractor's)          work order's site
ra_bill            ``ra_bills.status = draft``             ``may_manage_money``              --
                                                             (owner, admin, finance)
size_request       ``material_size_requests.status =       ``may_set_unit_conversions``      materials
                   open`` (held lines wait for a size)       (owner, admin, PM)
=================  ======================================  ===============================  ========================

Not here, and why: purchase orders have no draft state (an order is placed or not); stock adjustments need no
approval (``role_can_adjust`` records them directly); expenses wait for confirmation only as subcontract bills (one
row, not two); hire bills (NXT-13) are checked but have no approve / reject state, so they could never leave the
list -- they join when the hire check gets a decision.

Every row carries **the one fact that decides it** (``fact``) and a tone (``ok`` / ``warn`` / ``bad``), so most
decisions take one look. Money (``amount``) only for the roles that see spending (SEC-01).
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.authorization.roles import (
    may_act_on_material_requests,
    may_manage_money,
    may_set_unit_conversions,
    may_view_expenses,
)
from mesiri.domains.equipment.rules import inr

KINDS = ("material_request", "subcontract_bill", "measurement", "ra_bill", "size_request")
#: Waiting longer than this many days: the "Older" group.
OLD_DAYS = 2
_TONE_RANK = {"bad": 0, "warn": 1, "info": 2, "ok": 3}


# --- the row ---------------------------------------------------------------------------------------------------------


def _row(kind: str, rid: Any, *, ref: str | None, title: str, project_id: Any = None, project_name: str | None = None,
         site_id: Any = None, site_name: str | None = None, asked_by: str | None, since: str, amount: Any = None,
         flagged: bool = False, fact: str, tone: str, actions: list[str], link: str,
         extra: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "key": f"{kind}:{rid}", "kind": kind, "id": str(rid), "ref": ref, "title": title,
        "project_id": str(project_id) if project_id else None, "project_name": project_name,
        "site_id": str(site_id) if site_id else None, "site_name": site_name,
        "asked_by": asked_by, "since": since, "amount": None if amount is None else str(amount),
        "flagged": flagged, "fact": fact, "tone": tone, "actions": actions, "link": link, "extra": extra or {},
    }


def _num(v: Any) -> str:
    return f"{Decimal(str(v)).normalize():f}"


def _day(iso: str) -> str:
    """"9 Nov", as people write a day."""
    d = datetime.date.fromisoformat(iso[:10])
    return f"{d.day} {d:%b}"


def _qty(v: Any, unit: str | None) -> str:
    return f"{_num(v)} {unit}".strip() if unit else _num(v)


# --- one builder per source (pure: the module's described record in, a row out) ----------------------------------


def material_request_row(item: dict[str, Any], *, with_money: bool) -> dict[str, Any]:
    """A waiting request, as Materials > Requests describes it (``procurement.requests.describe``)."""
    lines = item["lines"]
    first = lines[0] if lines else None
    title = f"{first['material']} × {_qty(first['quantity'], first['unit'])}" if first else item["ref"]
    if len(lines) > 1:
        title += f" and {len(lines) - 1} more"
    to_buy = [x for x in lines if Decimal(x["to_buy"]) > 0]
    if item["duplicates"]:
        fact, tone = f"Also asked in {', '.join(d['ref'] for d in item['duplicates'])}", "warn"
    elif not to_buy:
        fact, tone = "Enough at site or on order already", "ok"
    elif first:
        line = to_buy[0]
        coming = f" · {_qty(line['on_order'], line['unit'])} on order" if Decimal(line["on_order"]) > 0 else ""
        fact = f"{_qty(line['at_site'], line['unit'])} at site{coming} · {_qty(line['to_buy'], line['unit'])} to buy"
        tone = "warn"
    else:
        fact, tone = "No lines", "info"
    if item["urgency"] == "late":
        fact, tone = f"Needed by {item['needed_by']}, late · " + fact, "bad"
    elif item["urgency"] == "soon":
        fact = f"Needed by {item['needed_by']} · " + fact
        tone = "bad" if tone == "warn" else tone
    amount = None
    if with_money and lines and all(x.get("last_rate") for x in lines):
        amount = sum((Decimal(x["quantity"]) * Decimal(x["last_rate"]["unit_cost"]) for x in lines), Decimal(0))
        amount = amount.quantize(Decimal("0.01"))
    return _row("material_request", item["id"], ref=item["ref"], title=title, project_id=item["project_id"],
                project_name=item["project_name"], site_id=item["site_id"], site_name=item["site_name"],
                asked_by=item["requested_by_name"], since=item["created_at"], amount=amount, fact=fact, tone=tone,
                actions=["ordered", "sent", "rejected"], link=f"/materials/requests?id={item['id']}",
                extra={"needed_by": item["needed_by"], "urgency": item["urgency"], "amount_is_estimate": amount is not None,
                       "lines": [{"material": x["material"], "quantity": x["quantity"], "unit": x["unit"],
                                  "at_site": x["at_site"], "on_order": x["on_order"], "to_buy": x["to_buy"]}
                                 for x in lines]})


def subcontract_bill_row(bill: dict[str, Any], wo: dict[str, Any]) -> dict[str, Any]:
    """A subcontractor's bill waiting for its check or flagged by it (``subcontracts.store.fetch_bills``)."""
    flagged = bill["check_status"] == "flagged"
    flags = bill.get("flags") or []
    if flags:
        fact = flags[0]["words"][:1].upper() + flags[0]["words"][1:]
        if len(flags) > 1:
            fact += f" (+{len(flags) - 1} more)"
        tone = "bad"
    else:
        fact, tone = "Matches what was measured and agreed", "ok"
    caught = Decimal(bill.get("caught") or 0)
    if caught > 0:
        fact += f" · {inr(caught)} at risk"
    vendor = wo.get("vendor_name") or "Subcontractor"
    return _row("subcontract_bill", bill["id"], ref=bill["ref"], title=f"{vendor} · {bill['ref']} on {wo['ref']}",
                project_id=wo["project_id"], project_name=wo.get("project_name"), site_id=wo.get("site_id"),
                site_name=wo.get("site_name"), asked_by=vendor,
                since=bill["created_at"], amount=bill["gross"], flagged=flagged, fact=fact, tone=tone,
                actions=["approve", "reject"], link=f"/subcontract/work-orders/{wo['id']}",
                extra={"work_order_id": wo["id"], "work_order_ref": wo["ref"], "flags": [f["words"] for f in flags],
                       "recorded_by": bill.get("submitted_by_name"),
                       "lines": bill.get("lines", [])})


def measurement_row(m: dict[str, Any]) -> dict[str, Any]:
    """Work a subcontractor reported (``proposed``), waiting for the site to confirm it."""
    measured, agreed = Decimal(m["measured"] or 0), Decimal(m["agreed"] or 0)
    after = measured + Decimal(m["quantity"])
    if agreed and after > agreed:
        fact, tone = f"Takes the line to {_qty(after, m['unit'])} of {_qty(agreed, m['unit'])} agreed", "bad"
    else:
        fact = f"{_qty(measured, m['unit'])} confirmed so far" + (f" of {_qty(agreed, m['unit'])} agreed" if agreed else "")
        tone = "info"
    from mesiri.domains.subcontracts.store import ref as wo_ref

    return _row("measurement", m["id"], ref=wo_ref(m["wo_number"]),
                title=f"{m['description']} · {_qty(m['quantity'], m['unit'])} on {_day(m['measured_on'])}",
                project_id=m["project_id"], project_name=m["project_name"], site_id=m["site_id"],
                site_name=m["site_name"], asked_by=m["who"] or m["vendor_name"], since=m["created_at"],
                fact=fact, tone=tone, actions=["confirm", "reject"], link=f"/subcontract/work-orders/{m['work_order_id']}",
                extra={"work_order_id": str(m["work_order_id"]), "vendor_name": m["vendor_name"]})


def ra_bill_row(bill: dict[str, Any]) -> dict[str, Any]:
    """A client RA bill still a draft (``billing.bills.list_bills``): to check and submit."""
    gross = Decimal(bill.get("gross") or 0)
    tone = "ok" if gross > 0 else "warn"
    fact = (f"Gross {inr(gross)} · net {inr(Decimal(bill.get('net') or 0))} after deductions" if gross > 0
            else "Nothing measured to bill yet")
    return _row("ra_bill", bill["id"], ref=bill["ref"], title=f"{bill['ref']} to {bill.get('client_name') or 'the client'}",
                project_id=bill["project_id"], project_name=bill["project_name"], asked_by=None,
                since=bill["created_at"], amount=bill.get("net"), fact=fact, tone=tone, actions=["submit"],
                link="/billing/ra-bills")


def size_request_row(r: dict[str, Any]) -> dict[str, Any]:
    """A unit size nobody on site knew; the lines said in it wait until it is set (WA-168)."""
    held = r["waiting"]
    proposed = r.get("proposed_one_unit_equals")
    fact = f"{held} line{'s' if held != 1 else ''} held until the size is set" if held else "No lines held"
    if proposed:
        fact += f" · {r.get('proposed_by_name') or 'Site'} says 1 {r['unit']} = {proposed} {r.get('stock_unit') or ''}".rstrip()
    return _row("size_request", r["id"], ref=None, title=f"How much is 1 {r['unit']} of {r['material']}?",
                asked_by=r.get("requested_by_name"), since=r["created_at"], fact=fact,
                tone="warn" if held else "info", actions=["answer"], link="/materials?view=items",
                extra={"material": r["material"], "unit": r["unit"], "stock_unit": r.get("stock_unit"),
                       "proposed_one_unit_equals": proposed})


# --- ordering and grouping ---------------------------------------------------------------------------------------------


def group_of(row: dict[str, Any], now: datetime.datetime) -> str:
    """``flagged`` (a check found something), ``older`` (waiting more than OLD_DAYS days) or ``recent``."""
    if row["flagged"]:
        return "flagged"
    since = datetime.datetime.fromisoformat(row["since"])
    if since.tzinfo is None:
        since = since.replace(tzinfo=datetime.UTC)
    return "older" if (now - since).days >= OLD_DAYS else "recent"


def arrange(rows: list[dict[str, Any]], now: datetime.datetime) -> dict[str, Any]:
    """Flagged first, then the oldest waiting; within a group the worst tone first, then the oldest. Counts by
    group and by kind for the page's tabs and the sidebar badge."""
    for r in rows:
        r["group"] = group_of(r, now)
    order = {"flagged": 0, "older": 1, "recent": 2}
    rows.sort(key=lambda r: (order[r["group"]], _TONE_RANK.get(r["tone"], 9), r["since"]))
    counts: dict[str, int] = {"total": len(rows)}
    for g in order:
        counts[g] = sum(1 for r in rows if r["group"] == g)
    for k in KINDS:
        counts[k] = sum(1 for r in rows if r["kind"] == k)
    return {"items": rows, "counts": counts}


# --- collecting ----------------------------------------------------------------------------------------------------


async def _material_requests(conn: AsyncConnection, auth: AuthorizationContext,
                             project_id: uuid.UUID | None) -> list[dict]:
    if not may_act_on_material_requests(auth.role):
        return []
    from mesiri.domains.procurement.router import list_requests

    found = await list_requests(status="waiting", project_id=project_id, site_id=None, requested_by=None,
                                category_id=None, urgency=None, mine=False, auth_context=auth, conn=conn)
    money = may_view_expenses(auth.role)
    return [material_request_row(i, with_money=money) for i in found["items"] if i["may_decide"]]


def _project_scope(auth: AuthorizationContext, project_id: uuid.UUID | None) -> set[uuid.UUID] | None:
    scope = None if auth.project_scope.grants_all_org_projects else set(auth.project_scope.project_ids)
    if project_id is not None:
        return {project_id} if scope is None or project_id in scope else set()
    return scope


async def _subcontract_bills(conn: AsyncConnection, auth: AuthorizationContext,
                             project_id: uuid.UUID | None) -> list[dict]:
    from mesiri.domains.subcontracts.router import waiting_bills

    narrow = {project_id} if project_id is not None else None
    return [subcontract_bill_row(b, wo) for b, wo in await waiting_bills(conn, auth, narrow)]


async def _measurements(conn: AsyncConnection, auth: AuthorizationContext, project_id: uuid.UUID | None) -> list[dict]:
    from fastapi import HTTPException

    from mesiri.domains.materials.router import _authorize_write

    scope = _project_scope(auth, project_id)
    if scope is not None and not scope:
        return []
    params: dict[str, Any] = {"org": auth.organization_id}
    where = ""
    if scope is not None:
        where = " AND w.project_id = ANY(:ps)"
        params["ps"] = list(scope)
    rows = (await conn.execute(text(
        "SELECT m.id, m.work_order_id, m.quantity, m.measured_on, m.created_at, l.description, l.unit, "
        "l.quantity AS agreed, w.number AS wo_number, w.project_id, w.site_id, p.name AS project_name, "
        "s.name AS site_name, v.name AS vendor_name, COALESCE(u.full_name, m.recorded_by_name) AS who, "
        "(SELECT COALESCE(SUM(x.quantity), 0) FROM work_order_measurements x WHERE x.line_id = m.line_id "
        "  AND x.status = 'confirmed') AS measured "
        "FROM work_order_measurements m JOIN work_order_lines l ON l.id = m.line_id "
        "JOIN work_orders w ON w.id = m.work_order_id JOIN projects p ON p.id = w.project_id "
        "JOIN vendors v ON v.id = w.vendor_id LEFT JOIN sites s ON s.id = w.site_id "
        "LEFT JOIN users u ON u.id = m.recorded_by "
        f"WHERE m.organization_id = :org AND m.status = 'proposed'{where} ORDER BY m.created_at"),  # noqa: S608
        params)).mappings()
    out = []
    for r in rows:
        try:  # the subcontracts module's own rule (decide_measurement -> _may_record)
            _authorize_write(auth, r["project_id"], r["site_id"])
        except HTTPException:
            continue
        out.append(measurement_row({**r, "measured_on": r["measured_on"].isoformat(),
                                    "created_at": r["created_at"].isoformat()}))
    return out


async def _ra_bills(conn: AsyncConnection, auth: AuthorizationContext, project_id: uuid.UUID | None) -> list[dict]:
    if not may_manage_money(auth.role):
        return []
    from mesiri.domains.billing import bills

    scope = _project_scope(auth, project_id)
    if scope is not None and not scope:
        return []
    out = []
    for b in await bills.list_bills(conn, auth.organization_id, scope):
        if b["status"] == "draft":
            out.append(ra_bill_row({**b, "id": str(b["id"]), "project_id": str(b["project_id"]),
                                    "created_at": b["created_at"].isoformat()}))
    return out


async def _size_requests(conn: AsyncConnection, auth: AuthorizationContext, project_id: uuid.UUID | None) -> list[dict]:
    # Company-wide (a size is set for the whole company), so not narrowed to one project.
    if not may_set_unit_conversions(auth.role) or project_id is not None:
        return []
    from mesiri.domains.materials import size_requests

    return [size_request_row({**r, "id": str(r["id"]), "created_at": r["created_at"].isoformat()})
            for r in await size_requests.list_requests(conn, auth.organization_id, "open")]


#: kind -> (collector, the module switch it needs, or None).
SOURCES = {
    "material_request": (_material_requests, "materials"),
    "subcontract_bill": (_subcontract_bills, None),
    "measurement": (_measurements, None),
    "ra_bill": (_ra_bills, None),
    "size_request": (_size_requests, "materials"),
}


async def collect(conn: AsyncConnection, auth: AuthorizationContext, *, enabled: set[str],
                  project_id: uuid.UUID | None = None, kinds: set[str] | None = None) -> list[dict[str, Any]]:
    """Every row waiting for this caller, unordered. ``enabled``: the company's switched-on modules."""
    rows: list[dict[str, Any]] = []
    for kind, (source, module) in SOURCES.items():
        if (kinds and kind not in kinds) or (module and module not in enabled):
            continue
        rows += await source(conn, auth, project_id)
    return rows
