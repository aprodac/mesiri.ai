"""NXT-11 / NXT-13 / NXT-14 / NXT-15: the equipment API (dashboard Equipment, and the assistant's tools).

- **Machines** (the register): owned or hired, the hire company (a vendor of kind ``hire``), the rate per hour / day /
  month and the hire's minimum hours, where it is now, on / off hire, service every N hours. The office adds and
  changes them; anyone who can write at a site can add one there ("a hired JCB came today").
- **Day logs**: per machine per day, hours worked, idle, breakdown (and why), diesel, operator, trips, meter. One
  live log per machine per day: a second message the same day adds to it or changes what it says ("JCB 6 hrs", then
  "JCB 30 L diesel"). A log at another site moves the machine there. Breakdown hours raise a site issue
  (``EQUIPMENT_BREAKDOWN``) once. Voided, never deleted.
- **Hire bills** (NXT-13): the hire company's bill for one machine and period, checked against the logs.
- **Costs**: hire earned (``rules.hire_lines``) and diesel per site, for the cost centres (``finance/costs.py``).
- **Returnables** (NXT-14): shuttering, scaffolding and tools are materials in a returnable category, held per site
  and moved with material transfers; this only reads them.

Rates, costs and bills only for the roles that see spending (SEC-01, ``may_view_expenses``).
"""

from __future__ import annotations

import datetime
import re
import uuid
from collections import defaultdict
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.authorization.roles import (
    may_act_on_material_requests,
    may_manage_money,
    may_view_expenses,
)
from mesiri.domains.equipment import rules, store
from mesiri.domains.equipment.reads import machine_costs
from mesiri.domains.materials.router import (
    _authorize_write,
    _resolve_project_ids,
    _site_filter_denied,
)
from mesiri.domains.projects.router import get_auth_context
from mesiri.domains.shared.modules import require_module
from mesiri.infrastructure.postgres.dependency import get_db_conn

router = APIRouter(prefix="/equipment", tags=["equipment"], dependencies=[Depends(require_module("equipment"))])

Kind = Literal["machine", "vehicle"]
Ownership = Literal["owned", "hired"]
RateUnit = Literal["hour", "day", "month"]
Status = Literal["active", "off_hire", "retired"]
Hours = Field(default=None, ge=0, le=24)


# ---------------------------------------------------------------------------------------------------------------
# Who may do what, and what they see
# ---------------------------------------------------------------------------------------------------------------

def _office(auth: AuthorizationContext, what: str) -> None:
    if not may_act_on_material_requests(auth.role):
        raise HTTPException(status_code=403, detail=f"Only an admin, owner or project manager can {what}.")


def _money(auth: AuthorizationContext) -> bool:
    return may_view_expenses(auth.role)


def _visible(auth: AuthorizationContext, project_id: uuid.UUID | None, site_id: uuid.UUID | None) -> bool:
    if project_id is None:  # a machine at no site: the company's, seen by those who see every project
        return auth.project_scope.grants_all_org_projects or may_act_on_material_requests(auth.role)
    if not auth.project_scope.grants_all_org_projects and project_id not in auth.project_scope.project_ids:
        return False
    return site_id is None or not _site_filter_denied(auth, project_id, site_id)


async def _today(conn: AsyncConnection, org: uuid.UUID) -> datetime.date:
    from mesiri.application.dpr import project_day

    return await project_day.company_today(conn, org)  # type: ignore[return-value]


async def _machine(conn: AsyncConnection, auth: AuthorizationContext, machine_id: uuid.UUID) -> dict:
    m = await store.fetch_machine(conn, auth.organization_id, machine_id)
    if m is None or not _visible(auth, m["project_id"], m["site_id"]):
        raise HTTPException(status_code=404, detail="Machine not found")
    return m


def _iso(v: Any) -> str | None:
    return v.isoformat() if v is not None else None


def _s(v: Any) -> str | None:
    return str(v) if v is not None else None


# ---------------------------------------------------------------------------------------------------------------
# What a machine and a log show
# ---------------------------------------------------------------------------------------------------------------

def log_out(x: dict, money: bool) -> dict:
    worked, idle, broke = rules.worked(x), rules.d(x.get("idle_hours")), rules.d(x.get("breakdown_hours"))
    return {
        "id": str(x["id"]), "equipment_id": str(x["equipment_id"]), "machine": x.get("machine_name"),
        "ref": rules.ref(x["machine_number"]) if x.get("machine_number") else None,
        "kind": x.get("machine_kind"), "ownership": x.get("machine_ownership"), "type": x.get("machine_type"),
        "event_type": x["event_type"], "date": x["occurred_date"].isoformat(),
        "project_id": _s(x["project_id"]), "project_name": x.get("project_name"),
        "site_id": _s(x["site_id"]), "site_name": x.get("site_name"),
        "from_site_id": _s(x.get("from_site_id")), "from_site_name": x.get("from_site_name"),
        "to_site_id": _s(x.get("to_site_id")), "to_site_name": x.get("to_site_name"),
        "worked_hours": rules.num(worked) if x.get("duration_hours") is not None else None,
        "idle_hours": rules.num(idle) if x.get("idle_hours") is not None else None,
        "breakdown_hours": rules.num(broke) if x.get("breakdown_hours") is not None else None,
        "breakdown_reason": x.get("breakdown_reason"),
        "fuel_litres": rules.num(rules.d(x["fuel_quantity"])) if x.get("fuel_quantity") is not None else None,
        "fuel_cost": rules.money(rules.d(x["fuel_cost"])) if money and x.get("fuel_cost") is not None else None,
        "expense_id": _s(x.get("expense_id")),
        "operator_name": x.get("operator_name") or x.get("operator_worker_name"),
        "operator_worker_id": _s(x.get("operator_worker_id")),
        "trips": x.get("trips"), "meter_reading": rules.num(x["meter_reading"]) if x.get("meter_reading") is not None else None,
        "issue_id": _s(x.get("issue_id")), "issue_status": x.get("issue_status"),
        "notes": x.get("notes"), "source": x.get("source"),
        "created_by_name": x.get("created_by_name"), "created_at": _iso(x.get("created_at")),
        "voided": x.get("voided_at") is not None,
        "utilisation": _pct(rules.utilisation(worked, idle, broke)),
    }


def _pct(v: Decimal | None) -> float | None:
    return float(v) if v is not None else None


def _totals(logs: list[dict]) -> dict[str, Decimal]:
    t = {"worked": rules.ZERO, "idle": rules.ZERO, "breakdown": rules.ZERO, "fuel": rules.ZERO, "fuel_cost": rules.ZERO,
         "trips": rules.ZERO}
    for x in logs:
        t["worked"] += rules.worked(x)
        t["idle"] += rules.d(x.get("idle_hours"))
        t["breakdown"] += rules.d(x.get("breakdown_hours"))
        t["fuel"] += rules.d(x.get("fuel_quantity"))
        t["fuel_cost"] += rules.d(x.get("fuel_cost"))
        t["trips"] += rules.d(x.get("trips"))
    return t


def machine_out(m: dict, *, money: bool, today: datetime.date, logs: list[dict], hours_since_service: Decimal,
                month_from: datetime.date, bills: list[dict] | None = None) -> dict:
    """One machine for the board: who and where, today's log, this month, the last 14 days, service."""
    mine = [x for x in logs if x["equipment_id"] == m["id"]]
    today_log = next((x for x in mine if x["occurred_date"] == today), None)
    month = [x for x in mine if month_from <= x["occurred_date"] <= today]
    t = _totals(month)
    hire = sum((h["amount"] for h in rules.hire_lines(m, mine, month_from, today, today)), rules.ZERO)
    last = max((x["occurred_date"] for x in mine), default=None)
    meter = next((x["meter_reading"] for x in mine if x.get("meter_reading") is not None), None)
    recent = []
    for i in range(13, -1, -1):
        day = today - datetime.timedelta(days=i)
        x = next((y for y in mine if y["occurred_date"] == day), None)
        recent.append({"date": day.isoformat(), "worked": rules.num(rules.worked(x)) if x else None,
                       "idle": rules.num(rules.d(x.get("idle_hours"))) if x else None,
                       "breakdown": rules.num(rules.d(x.get("breakdown_hours"))) if x else None,
                       "fuel": rules.num(rules.d(x.get("fuel_quantity"))) if x else None})
    out = {
        "id": str(m["id"]), "number": m["number"], "ref": rules.ref(m["number"]), "name": m["name"], "type": m["type"],
        "kind": m["kind"], "ownership": m["ownership"],
        "vendor_id": _s(m["vendor_id"]), "vendor_name": m.get("vendor_name"),
        "rate": rules.money(rules.d(m["rate"])) if money and m["rate"] is not None else None,
        "rate_unit": m["rate_unit"],
        "min_hours_per_day": rules.num(rules.d(m["min_hours_per_day"])) if m["min_hours_per_day"] is not None else None,
        "registration_no": m["registration_no"], "make_model": m["make_model"], "fuel_type": m["fuel_type"],
        "project_id": _s(m["project_id"]), "project_name": m.get("project_name"),
        "site_id": _s(m["site_id"]), "site_name": m.get("site_name"),
        "status": m["status"], "on_hire_from": _iso(m["on_hire_from"]), "off_hire_on": _iso(m["off_hire_on"]),
        "service_every_hours": rules.num(rules.d(m["service_every_hours"])) if m["service_every_hours"] is not None else None,
        "last_service_on": _iso(m["last_service_on"]),
        "operator_name": m["operator_name"] or m.get("operator_worker_name"), "operator_worker_id": _s(m["operator_worker_id"]),
        "notes": m["notes"], "created_at": _iso(m["created_at"]),
        "state": rules.state(m, today_log),
        "today": log_out(today_log, money) if today_log else None,
        "last_log_date": _iso(last),
        "meter_reading": rules.num(rules.d(meter)) if meter is not None else None,
        "month": {
            "from": month_from.isoformat(), "worked": rules.num(t["worked"]), "idle": rules.num(t["idle"]),
            "breakdown": rules.num(t["breakdown"]), "fuel_litres": rules.num(t["fuel"]),
            "days_logged": len({x["occurred_date"] for x in month}), "trips": int(t["trips"]),
            "utilisation": _pct(rules.utilisation(t["worked"], t["idle"], t["breakdown"])),
            "litres_per_hour": rules.num(t["fuel"] / t["worked"]) if t["worked"] and t["fuel"] else None,
            "fuel_cost": rules.money(t["fuel_cost"]) if money else None,
            "hire_cost": rules.money(hire) if money and m["ownership"] == "hired" else None,
            "cost": rules.money(hire + t["fuel_cost"]) if money else None,
        },
        "recent": recent,
        "service": rules.service(m, rules.d(hours_since_service)),
    }
    if bills is not None:
        out["bills"] = [bill_out(b, money) for b in bills if b["equipment_id"] == m["id"]]
    return out


def bill_out(b: dict, money: bool, check: dict | None = None) -> dict:
    out = {
        "id": str(b["id"]), "equipment_id": str(b["equipment_id"]), "machine": b.get("machine_name"),
        "ref": rules.ref(b["machine_number"]) if b.get("machine_number") else None,
        "vendor_id": _s(b["vendor_id"]), "vendor_name": b.get("vendor_name"),
        "period_from": b["period_from"].isoformat(), "period_to": b["period_to"].isoformat(),
        "billed_hours": rules.num(rules.d(b["billed_hours"])) if b["billed_hours"] is not None else None,
        "billed_days": rules.num(rules.d(b["billed_days"])) if b["billed_days"] is not None else None,
        "amount": rules.money(rules.d(b["amount"])) if money else None,
        "bill_ref": b["bill_ref"], "bill_date": _iso(b["bill_date"]), "expense_id": _s(b["expense_id"]),
        "notes": b["notes"], "created_by_name": b.get("created_by_name"), "created_at": _iso(b["created_at"]),
    }
    if check is not None:
        out["check"] = check
    return out


async def _board(conn: AsyncConnection, auth: AuthorizationContext, machines: list[dict], *, with_bills: bool = False,
                 period: tuple[datetime.date, datetime.date] | None = None) -> tuple[list[dict], datetime.date]:
    org = auth.organization_id
    today = await _today(conn, org)
    month_from = today.replace(day=1)
    since = min(month_from, today - datetime.timedelta(days=13))
    if period is not None:
        since = min(since, period[0])
    ids = [m["id"] for m in machines]
    logs = await store.fetch_events(conn, org, equipment_ids=ids, date_from=since, date_to=today) if ids else []
    logs = [x for x in logs if _visible(auth, x["project_id"], x["site_id"])]
    service = await store.worked_since(conn, org, ids)
    bills = await store.fetch_bills(conn, org, equipment_ids=ids) if with_bills and ids else None
    money = _money(auth)
    return [machine_out(m, money=money, today=today, logs=logs, hours_since_service=service.get(m["id"], 0),
                        month_from=month_from, bills=bills) for m in machines], today


# ---------------------------------------------------------------------------------------------------------------
# Machines
# ---------------------------------------------------------------------------------------------------------------

class MachineIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    type: str | None = Field(default=None, max_length=60)
    kind: Kind | None = None
    ownership: Ownership | None = None
    #: The hire company from the list, or ``hire_company`` in words (the company's vendor of that name, made when new).
    vendor_id: uuid.UUID | None = None
    hire_company: str | None = Field(default=None, max_length=120)
    rate: Decimal | None = Field(default=None, ge=0)
    rate_unit: RateUnit | None = None
    min_hours_per_day: Decimal | None = Field(default=None, ge=0, le=24)
    registration_no: str | None = Field(default=None, max_length=40)
    make_model: str | None = Field(default=None, max_length=80)
    fuel_type: str | None = Field(default=None, max_length=20)
    site_id: uuid.UUID | None = None
    on_hire_from: datetime.date | None = None
    service_every_hours: Decimal | None = Field(default=None, gt=0)
    last_service_on: datetime.date | None = None
    operator_name: str | None = Field(default=None, max_length=80)
    operator_worker_id: uuid.UUID | None = None
    notes: str | None = Field(default=None, max_length=500)


class MachineCreate(MachineIn):
    name: str = Field(min_length=1, max_length=80)  # type: ignore[assignment]


class MachineUpdate(MachineIn):
    status: Status | None = None
    off_hire_on: datetime.date | None = None


async def _values(conn: AsyncConnection, auth: AuthorizationContext, body: MachineIn, *,
                  current: dict | None) -> dict[str, Any]:
    """The columns this body sets, checked: the hire company is the company's vendor (made when named in words, and
    then a hire company), the site is the company's, the operator one of its workers."""
    org = auth.organization_id
    given = body.model_dump(exclude_unset=True)
    values: dict[str, Any] = {k: v for k, v in given.items() if k in store.MACHINE_FIELDS}
    if "name" in values:
        values["name"] = " ".join(values["name"].split())
        if await store.name_taken(conn, org, values["name"], other_than=current["id"] if current else None):
            raise HTTPException(status_code=409, detail={
                "code": "name_taken", "message": f"There is already a machine called {values['name']}. Give this one "
                                                 "another name (JCB 2, JCB Kerala Earthmovers)."})
    if body.vendor_id is not None:
        row = (await conn.execute(text("SELECT id FROM vendors WHERE id = :id AND organization_id = :org"),
                                  {"id": body.vendor_id, "org": org})).first()
        if row is None:
            raise HTTPException(status_code=422, detail="vendor_id is not one of this company's vendors")
    elif body.hire_company:
        from mesiri.application.vendors.resolution import vendor_for_name
        from mesiri.infrastructure.postgres.repositories.vendors import PostgresVendorRepository

        known = await PostgresVendorRepository(conn).find_by_name_exact_active(org, body.hire_company.strip())
        vendor_id = await vendor_for_name(conn, org, body.hire_company, created_by=auth.user_id)
        if known is None:  # made just now: it is a hire company
            await conn.execute(text("UPDATE vendors SET kind = 'hire' WHERE id = :id AND organization_id = :org"),
                               {"id": vendor_id, "org": org})
        values["vendor_id"] = vendor_id
    if values.get("vendor_id") and "ownership" not in values and (current is None or current["ownership"] != "hired"):
        values["ownership"] = "hired"  # a machine from a hire company is hired
    if "rate" in values and values["rate"] is not None and "rate_unit" not in values and not (current or {}).get("rate_unit"):
        values["rate_unit"] = "hour"
    if "site_id" in given:
        if body.site_id is None:
            values["project_id"] = None
        else:
            project = await store.site_project(conn, org, body.site_id)
            if project is None:
                raise HTTPException(status_code=422, detail="site_id is not one of this company's sites")
            _authorize_write(auth, project, body.site_id)
            values["project_id"] = project
    if body.operator_worker_id is not None:
        row = (await conn.execute(text("SELECT 1 FROM workforce_workers WHERE id = :id AND organization_id = :org"),
                                  {"id": body.operator_worker_id, "org": org})).first()
        if row is None:
            raise HTTPException(status_code=422, detail="operator_worker_id is not one of this company's workers")
    return values


@router.get("")
async def list_machines(
    project_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    status: str = Query(default="all", description="active, off_hire, retired, current (active and off hire), all"),
    kind: Kind | None = None,
    vendor_id: uuid.UUID | None = None,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """The company's machines and vehicles the caller can see, each with today's log, this month's hours, diesel and
    cost, the last 14 days and service; counts for the page's tiles."""
    if status not in ("active", "off_hire", "retired", "current", "all"):
        raise HTTPException(status_code=422, detail="status is one of active, off_hire, retired, current, all")
    project_ids, denied = _resolve_project_ids(auth_context, project_id)
    if denied:
        return {"items": [], "counts": {}, "today": None}
    rows = await store.fetch_machines(conn, auth_context.organization_id, vendor_id=vendor_id)
    rows = [m for m in rows if _visible(auth_context, m["project_id"], m["site_id"])]
    if project_ids is not None:
        rows = [m for m in rows if m["project_id"] in project_ids or (m["project_id"] is None and project_id is None)]
    if site_id is not None:
        rows = [m for m in rows if m["site_id"] == site_id]
    if kind is not None:
        rows = [m for m in rows if m["kind"] == kind]
    if status == "current":
        rows = [m for m in rows if m["status"] != "retired"]
    elif status != "all":
        rows = [m for m in rows if m["status"] == status]
    items, today = await _board(conn, auth_context, rows)
    live = [x for x in items if x["status"] == "active"]
    counts = {
        "on_site": sum(1 for x in live if x["site_id"]),
        "working": sum(1 for x in live if x["state"] == "working"),
        "idle": sum(1 for x in live if x["state"] == "idle"),
        "breakdown": sum(1 for x in live if x["state"] == "breakdown"),
        "not_logged": sum(1 for x in live if x["state"] == "not_logged"),
        "service_due": sum(1 for x in live if x["service"] and x["service"]["status"] != "ok"),
        "off_hire": sum(1 for x in items if x["status"] == "off_hire"),
        "hired": sum(1 for x in live if x["ownership"] == "hired"),
    }
    money = _money(auth_context)
    month_cost = sum((Decimal(x["month"]["cost"]) for x in items if x["month"]["cost"]), Decimal(0)) if money else None
    return {"items": items, "counts": counts, "today": today.isoformat(),
            "month_cost": rules.money(month_cost) if month_cost is not None else None}


@router.post("", status_code=201)
async def create_machine(body: MachineCreate, auth_context: AuthorizationContext = Depends(get_auth_context),
                         conn: AsyncConnection = Depends(get_db_conn)):
    """Add a machine or vehicle. At a site: anyone who can write there ("a hired JCB came today from Kerala
    Earthmovers, ₹1,100 an hour"); with no site: the office."""
    if body.site_id is None:
        _office(auth_context, "add a machine that is not at a site")
    values = await _values(conn, auth_context, body, current=None)
    values.setdefault("kind", "machine")
    values.setdefault("ownership", "owned")
    if values["ownership"] == "hired" and values.get("site_id") and not values.get("on_hire_from"):
        values["on_hire_from"] = await _today(conn, auth_context.organization_id)
    machine_id = await store.insert_machine(conn, auth_context.organization_id, values, by=auth_context.user_id)
    m = await store.fetch_machine(conn, auth_context.organization_id, machine_id)
    assert m is not None
    if m["site_id"]:
        await store.insert_event(conn, auth_context.organization_id, m, event_type="arrived", project_id=m["project_id"],
                                 site_id=m["site_id"], day=values.get("on_hire_from") or await _today(conn, m["organization_id"]),
                                 by=auth_context.user_id, source="dashboard")
    items, _ = await _board(conn, auth_context, [m])
    return items[0]


@router.patch("/{machine_id}")
async def update_machine(machine_id: uuid.UUID, body: MachineUpdate,
                         auth_context: AuthorizationContext = Depends(get_auth_context),
                         conn: AsyncConnection = Depends(get_db_conn)):
    """Change a machine's details (the office). Moving it is ``/move``; on / off hire ``/off-hire`` and ``/on-hire``."""
    _office(auth_context, "change a machine")
    m = await _machine(conn, auth_context, machine_id)
    values = await _values(conn, auth_context, body, current=m)
    values.pop("site_id", None)
    values.pop("project_id", None)
    if values.get("status") == "retired":
        values.update(site_id=None, project_id=None)
    await store.update_machine(conn, auth_context.organization_id, machine_id, values, by=auth_context.user_id)
    items, _ = await _board(conn, auth_context, [await _machine_any(conn, auth_context, machine_id)])
    return items[0]


async def _machine_any(conn: AsyncConnection, auth: AuthorizationContext, machine_id: uuid.UUID) -> dict:
    m = await store.fetch_machine(conn, auth.organization_id, machine_id)
    assert m is not None
    return m


@router.delete("/{machine_id}")
async def delete_machine(machine_id: uuid.UUID, auth_context: AuthorizationContext = Depends(get_auth_context),
                         conn: AsyncConnection = Depends(get_db_conn)):
    """Delete a machine added by mistake. One with logs or bills is refused: retire it instead (it keeps its history)."""
    _office(auth_context, "delete a machine")
    m = await _machine(conn, auth_context, machine_id)
    n = await store.history_count(conn, auth_context.organization_id, machine_id)
    if n:
        raise HTTPException(status_code=409, detail=f"{m['name']} has {n} log{'s' if n != 1 else ''} or bills: retire it "
                                                    "instead, so its history stays.")
    await store.delete_machine(conn, auth_context.organization_id, machine_id)
    return {"id": str(machine_id), "status": "deleted"}


class MoveIn(BaseModel):
    site_id: uuid.UUID
    date: datetime.date | None = None
    notes: str | None = Field(default=None, max_length=300)


async def _move(conn: AsyncConnection, auth: AuthorizationContext, m: dict, site_id: uuid.UUID, day: datetime.date,
                source: str, notes: str | None = None) -> dict | None:
    """The machine is now at this site: one ``moved`` event (or ``arrived`` when it was at none). None when it is
    there already."""
    if m["site_id"] == site_id:
        return None
    org = auth.organization_id
    project = await store.site_project(conn, org, site_id)
    if project is None:
        raise HTTPException(status_code=422, detail="site_id is not one of this company's sites")
    _authorize_write(auth, project, site_id)
    await store.insert_event(conn, org, m, event_type="moved" if m["site_id"] else "arrived", project_id=project,
                             site_id=site_id, day=day, by=auth.user_id, source=source, from_site_id=m["site_id"],
                             to_site_id=site_id, values={"notes": notes} if notes else None)
    await store.update_machine(conn, org, m["id"], {"site_id": site_id, "project_id": project}, by=auth.user_id)
    return {"from_site_id": _s(m["site_id"]), "from_site_name": m.get("site_name"), "to_site_id": str(site_id)}


@router.post("/{machine_id}/move")
async def move_machine(machine_id: uuid.UUID, body: MoveIn, auth_context: AuthorizationContext = Depends(get_auth_context),
                       conn: AsyncConnection = Depends(get_db_conn)):
    """The machine went to another site (anyone who can write at the site it goes to)."""
    m = await _machine(conn, auth_context, machine_id)
    if m["status"] == "retired":
        raise HTTPException(status_code=409, detail=f"{m['name']} is retired.")
    day = body.date or await _today(conn, auth_context.organization_id)
    await _move(conn, auth_context, m, body.site_id, day, "dashboard", body.notes)
    if m["status"] == "off_hire":
        await store.update_machine(conn, auth_context.organization_id, machine_id,
                                   {"status": "active", "off_hire_on": None, "on_hire_from": day}, by=auth_context.user_id)
    items, _ = await _board(conn, auth_context, [await _machine_any(conn, auth_context, machine_id)])
    return items[0]


class HireIn(BaseModel):
    date: datetime.date | None = None
    site_id: uuid.UUID | None = None
    notes: str | None = Field(default=None, max_length=300)


@router.post("/{machine_id}/off-hire")
async def off_hire(machine_id: uuid.UUID, body: HireIn, auth_context: AuthorizationContext = Depends(get_auth_context),
                   conn: AsyncConnection = Depends(get_db_conn)):
    """Sent back to the hire company (or an owned machine stood down): it stops earning hire from this day."""
    org = auth_context.organization_id
    m = await _machine(conn, auth_context, machine_id)
    if m["project_id"]:
        _authorize_write(auth_context, m["project_id"], m["site_id"])
    else:
        _office(auth_context, "change a machine")
    if m["status"] != "active":
        raise HTTPException(status_code=409, detail=f"{m['name']} is {m['status'].replace('_', ' ')} already.")
    day = body.date or await _today(conn, org)
    if m["project_id"]:
        await store.insert_event(conn, org, m, event_type="departed", project_id=m["project_id"], site_id=m["site_id"],
                                 day=day, by=auth_context.user_id, source="dashboard",
                                 values={"notes": body.notes} if body.notes else None, from_site_id=m["site_id"])
    await store.update_machine(conn, org, machine_id, {"status": "off_hire", "off_hire_on": day, "site_id": None,
                                                       "project_id": None}, by=auth_context.user_id)
    items, _ = await _board(conn, auth_context, [await _machine_any(conn, auth_context, machine_id)])
    return items[0]


@router.post("/{machine_id}/on-hire")
async def on_hire(machine_id: uuid.UUID, body: HireIn, auth_context: AuthorizationContext = Depends(get_auth_context),
                  conn: AsyncConnection = Depends(get_db_conn)):
    """Back on hire at a site."""
    org = auth_context.organization_id
    m = await _machine(conn, auth_context, machine_id)
    if m["status"] == "active":
        raise HTTPException(status_code=409, detail=f"{m['name']} is on hire already.")
    if body.site_id is None:
        raise HTTPException(status_code=422, detail="Say which site it goes to.")
    day = body.date or await _today(conn, org)
    await _move(conn, auth_context, m, body.site_id, day, "dashboard", body.notes)
    await store.update_machine(conn, org, machine_id, {"status": "active", "on_hire_from": day, "off_hire_on": None},
                               by=auth_context.user_id)
    items, _ = await _board(conn, auth_context, [await _machine_any(conn, auth_context, machine_id)])
    return items[0]


class ServiceIn(BaseModel):
    date: datetime.date | None = None
    meter_reading: Decimal | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=300)
    cost: Decimal | None = Field(default=None, ge=0)


@router.post("/{machine_id}/service")
async def record_service(machine_id: uuid.UUID, body: ServiceIn,
                         auth_context: AuthorizationContext = Depends(get_auth_context),
                         conn: AsyncConnection = Depends(get_db_conn)):
    """NXT-15: the machine was serviced; the hours to the next service count from today."""
    org = auth_context.organization_id
    m = await _machine(conn, auth_context, machine_id)
    if m["project_id"]:
        _authorize_write(auth_context, m["project_id"], m["site_id"])
    else:
        _office(auth_context, "record a service")
    day = body.date or await _today(conn, org)
    if m["project_id"]:
        await store.insert_event(conn, org, m, event_type="serviced", project_id=m["project_id"], site_id=m["site_id"],
                                 day=day, by=auth_context.user_id, source="dashboard",
                                 values={"notes": body.notes, "meter_reading": body.meter_reading})
    await store.update_machine(conn, org, machine_id, {"last_service_on": day, "last_service_meter": body.meter_reading},
                               by=auth_context.user_id)
    items, _ = await _board(conn, auth_context, [await _machine_any(conn, auth_context, machine_id)])
    return items[0]


# ---------------------------------------------------------------------------------------------------------------
# Day logs
# ---------------------------------------------------------------------------------------------------------------

class LogLine(BaseModel):
    """One machine's day. Each figure given is the day's (it replaces one saved earlier that day); one left out stays."""

    #: The machine from the list, or ``machine`` as people say it ("JCB", "JCB 2", "EQ-0003", "the mixer").
    equipment_id: uuid.UUID | None = None
    machine: str | None = Field(default=None, max_length=80)
    #: Where it worked; left out: where the machine is. Another site moves it there.
    site_id: uuid.UUID | None = None
    worked_hours: Decimal | None = Hours
    idle_hours: Decimal | None = Hours
    breakdown_hours: Decimal | None = Hours
    breakdown_reason: str | None = Field(default=None, max_length=200)
    fuel_litres: Decimal | None = Field(default=None, ge=0, le=5000)
    #: What the diesel cost (shown to the roles that see spending). Paid from petty cash: an expense, put in expense_id.
    fuel_cost: Decimal | None = Field(default=None, ge=0)
    expense_id: uuid.UUID | None = None
    operator_name: str | None = Field(default=None, max_length=80)
    operator_worker_id: uuid.UUID | None = None
    trips: int | None = Field(default=None, ge=0, le=500)
    meter_reading: Decimal | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=300)
    #: Breakdown hours of today or yesterday raise a site issue (once per day log) unless false.
    raise_issue: bool = True


class LogCreate(BaseModel):
    occurred_date: datetime.date | None = None
    lines: list[LogLine] = Field(min_length=1, max_length=60)
    source: Literal["dashboard", "whatsapp", "api"] = "dashboard"


_LOG_MAP = {"worked_hours": "duration_hours", "idle_hours": "idle_hours", "breakdown_hours": "breakdown_hours",
            "breakdown_reason": "breakdown_reason", "fuel_litres": "fuel_quantity", "fuel_cost": "fuel_cost",
            "expense_id": "expense_id", "operator_name": "operator_name", "operator_worker_id": "operator_worker_id",
            "trips": "trips", "meter_reading": "meter_reading", "notes": "notes"}


def _words(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", s.casefold())


def resolve_machine(machines: list[dict], said: str, site_id: uuid.UUID | None) -> tuple[dict | None, list[dict]]:
    """The machine meant by the words ("JCB", "JCB 2", "EQ-0003", "3", "mixer"): exact name or number first, then the
    one machine whose name or type has every word (one at the site said wins over several elsewhere). Returns
    (machine, []) or (None, the candidates) -- none found, or several."""
    live = [m for m in machines if m["status"] != "retired"]
    s = " ".join(said.split()).casefold()
    num = re.fullmatch(r"(?:eq[-\s]?)?0*(\d+)", s)
    if num:
        hit = [m for m in live if m["number"] == int(num.group(1))]
        if hit:
            return hit[0], []
    exact = [m for m in live if m["name"].casefold() == s]
    if exact:
        return exact[0], []
    words = [w.rstrip("s") if len(w) > 3 else w for w in _words(s)]
    if not words:
        return None, []

    def has(m: dict) -> bool:
        hay = _words(f"{m['name']} {m.get('type') or ''} {m.get('make_model') or ''} {m.get('registration_no') or ''}")
        hay += [w.rstrip("s") for w in hay]
        return all(any(h == w or (len(w) >= 3 and h.startswith(w)) for h in hay) for w in words)

    found = [m for m in live if has(m)]
    if len(found) > 1 and site_id is not None:
        here = [m for m in found if m["site_id"] == site_id]
        if len(here) == 1:
            return here[0], []
    if len(found) > 1:
        active = [m for m in found if m["status"] == "active"]
        if len(active) == 1:
            return active[0], []
    return (found[0], []) if len(found) == 1 else (None, found)


async def _issue_for(conn: AsyncConnection, auth: AuthorizationContext, m: dict, project_id: uuid.UUID,
                     site_id: uuid.UUID, hours: Decimal, reason: str | None) -> uuid.UUID:
    """The site issue a breakdown raises, through the one path issues are made (Progress). The hours are in its words,
    not its ``delay_duration_minutes``: a machine broken for 4 hours is not 4 hours the site lost (the DPR's hours lost
    adds the issues' delays up; two machines broken at once read as a day lost)."""
    from mesiri.infrastructure.postgres.repositories.progress import PostgresProgressReadRepository

    said = f"{m['name']} breakdown, {rules.num(hours)} hrs" + (f": {reason}" if reason else "")
    issue = await PostgresProgressReadRepository(conn).create_issue(
        organization_id=auth.organization_id, user_id=auth.user_id,
        payload={"project_id": project_id, "site_id": site_id, "issue_type": "EQUIPMENT_BREAKDOWN",
                 "severity": "HIGH" if hours >= 4 else "MEDIUM", "narrative": said})
    return issue["id"]


@router.post("/logs", status_code=201)
async def save_logs(body: LogCreate, auth_context: AuthorizationContext = Depends(get_auth_context),
                    conn: AsyncConnection = Depends(get_db_conn)):
    """Save the day for one or more machines ("JCB 6 hrs, 2 hrs breakdown, 30 L diesel"). Per line: the machine by id
    or in words; the site (else where the machine is; another site moves it there). A machine named that is not in
    the register is a 422 ``unknown_machine`` naming the ones there are (add it first); several that fit is a 409
    ``which_machine`` with them. Nothing is saved unless every line is right."""
    org = auth_context.organization_id
    day = body.occurred_date or await _today(conn, org)
    today = await _today(conn, org)
    if day > today:
        raise HTTPException(status_code=422, detail="That date is in the future: a day is logged on or after it.")
    machines = await store.fetch_machines(conn, org)
    visible = [m for m in machines if _visible(auth_context, m["project_id"], m["site_id"]) or m["project_id"] is None]
    by_id = {m["id"]: m for m in machines}
    plan: list[tuple[LogLine, dict, uuid.UUID, uuid.UUID]] = []
    seen: set[uuid.UUID] = set()
    for line in body.lines:
        if line.equipment_id is not None:
            m = by_id.get(line.equipment_id)
            if m is None:
                raise HTTPException(status_code=422, detail="equipment_id is not one of this company's machines")
        elif line.machine:
            m, candidates = resolve_machine(visible, line.machine, line.site_id)
            if m is None:
                names = [f"{x['name']} ({rules.ref(x['number'])})" for x in (candidates or visible) if x["status"] != "retired"]
                if candidates:
                    raise HTTPException(status_code=409, detail={
                        "code": "which_machine", "said": line.machine,
                        "message": f"Which {line.machine}? {', '.join(names)}.",
                        "candidates": [{"id": str(x["id"]), "name": x["name"], "ref": rules.ref(x["number"]),
                                        "site_name": x.get("site_name")} for x in candidates]})
                raise HTTPException(status_code=422, detail={
                    "code": "unknown_machine", "said": line.machine,
                    "message": f"No machine called {line.machine} yet. Add it first (owned or hired, and from whom)."
                               + (f" Machines now: {', '.join(names[:12])}." if names else ""),
                    "machines": [{"id": str(x["id"]), "name": x["name"], "ref": rules.ref(x["number"])} for x in visible
                                 if x["status"] != "retired"][:30]})
        else:
            raise HTTPException(status_code=422, detail="Each line needs the machine: equipment_id or machine.")
        if m["id"] in seen:
            raise HTTPException(status_code=422, detail=f"{m['name']} is on two lines; one line per machine per day.")
        seen.add(m["id"])
        if m["status"] == "retired":
            raise HTTPException(status_code=409, detail=f"{m['name']} is retired.")
        if m["status"] == "off_hire" and m["off_hire_on"] and day >= m["off_hire_on"] and line.site_id is None:
            raise HTTPException(status_code=409, detail=f"{m['name']} is off hire since {m['off_hire_on']:%d %b}: say "
                                                        "which site it is back at, or put it on hire first.")
        site_id = line.site_id or m["site_id"]
        if site_id is None:
            raise HTTPException(status_code=422, detail={"code": "which_site",
                                                         "message": f"Which site did {m['name']} work at?"})
        project_id = await store.site_project(conn, org, site_id)
        if project_id is None:
            raise HTTPException(status_code=422, detail="site_id is not one of this company's sites")
        _authorize_write(auth_context, project_id, site_id)
        given = line.model_dump(exclude_unset=True)
        if not any(k in given for k in _LOG_MAP):
            raise HTTPException(status_code=422, detail=f"Say what {m['name']} did: hours worked, idle, breakdown or diesel.")
        plan.append((line, m, project_id, site_id))

    saved, replaced, moved, issues = [], [], [], []
    for line, m, project_id, site_id in plan:
        given = line.model_dump(exclude_unset=True)
        values = {_LOG_MAP[k]: v for k, v in given.items() if k in _LOG_MAP}
        if "fuel_quantity" in values:
            values["fuel_unit"] = "L"
        if values.get("operator_worker_id") is not None:
            row = (await conn.execute(text("SELECT 1 FROM workforce_workers WHERE id = :id AND organization_id = :org"),
                                      {"id": values["operator_worker_id"], "org": org})).first()
            if row is None:
                raise HTTPException(status_code=422, detail="operator_worker_id is not one of this company's workers")
        if values.get("expense_id") is not None:
            row = (await conn.execute(text("SELECT 1 FROM expenses WHERE id = :id AND organization_id = :org"),
                                      {"id": values["expense_id"], "org": org})).first()
            if row is None:
                raise HTTPException(status_code=422, detail="expense_id is not one of this company's expenses")
        if "operator_name" not in values and "operator_worker_id" not in values and (m["operator_name"] or m["operator_worker_id"]):
            values.setdefault("operator_name", m["operator_name"])
            values.setdefault("operator_worker_id", m["operator_worker_id"])
        existing = await store.day_log_of(conn, org, m["id"], day)
        merged = {**(existing or {}), **values}
        total = sum((rules.d(merged.get(k)) for k in ("duration_hours", "idle_hours", "breakdown_hours")), rules.ZERO)
        if total > 24:
            raise HTTPException(status_code=422, detail=f"{m['name']}: {rules.num(total)} hours in one day is more than 24.")
        issue_id = existing.get("issue_id") if existing else None
        broke = rules.d(merged.get("breakdown_hours"))
        # Only a breakdown of today or yesterday is news: the issue is dated when it is raised, so an older day's
        # breakdown (a back-dated log) would show as a new problem on today's report. It stays on its log.
        if broke > 0 and line.raise_issue and issue_id is None and day >= today - datetime.timedelta(days=1):
            issue_id = await _issue_for(conn, auth_context, m, project_id, site_id, broke, merged.get("breakdown_reason"))
            issues.append({"machine": m["name"], "issue_id": str(issue_id)})
        if day >= (m["off_hire_on"] or day) and m["site_id"] != site_id and (m["status"] != "off_hire" or line.site_id):
            # Logged at another site (on the latest day): the machine is there now.
            if day >= today - datetime.timedelta(days=1) or m["site_id"] is None:
                mv = await _move(conn, auth_context, m, site_id, day, body.source)
                if mv:
                    moved.append({"machine": m["name"], **mv})
                if m["status"] == "off_hire":
                    await store.update_machine(conn, org, m["id"], {"status": "active", "off_hire_on": None,
                                                                    "on_hire_from": day}, by=auth_context.user_id)
        if existing:
            replaced.append({"machine": m["name"], "was": log_out({**existing, "machine_name": m["name"],
                                                                  "machine_number": m["number"]}, _money(auth_context))})
            await store.update_day_log(conn, org, existing["id"], project_id=project_id, site_id=site_id, values=values,
                                       by=auth_context.user_id, source=body.source, issue_id=issue_id)
            saved.append(existing["id"])
        else:
            saved.append(await store.insert_event(conn, org, m, event_type="day_log", project_id=project_id,
                                                  site_id=site_id, day=day, by=auth_context.user_id, source=body.source,
                                                  values=values, issue_id=issue_id))
    rows = await store.fetch_events(conn, org, ids=saved)
    money = _money(auth_context)
    return {"date": day.isoformat(), "items": [log_out(x, money) for x in rows], "replaced": replaced, "moved": moved,
            "issues": issues}


@router.get("/logs")
async def list_logs(
    date: datetime.date | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    project_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    equipment_id: uuid.UUID | None = None,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Day logs (one date, or a period; default today), newest first, with the totals; and for a single date the
    machines at the sites in view with no log yet (``missing``), so the Daily log page can fill them."""
    org = auth_context.organization_id
    project_ids, denied = _resolve_project_ids(auth_context, project_id)
    if denied:
        return {"items": [], "totals": {}, "missing": []}
    today = await _today(conn, org)
    if date is not None:
        date_from = date_to = date
    date_to = date_to or today
    date_from = date_from or date_to
    if date_from > date_to:
        raise HTTPException(status_code=422, detail="date_from is after date_to")
    rows = await store.fetch_events(conn, org, project_ids=project_ids, site_id=site_id, date_from=date_from,
                                    date_to=date_to, equipment_ids=[equipment_id] if equipment_id else None)
    rows = [x for x in rows if _visible(auth_context, x["project_id"], x["site_id"])]
    money = _money(auth_context)
    t = _totals(rows)
    missing: list[dict] = []
    if date_from == date_to:
        logged = {x["equipment_id"] for x in rows}
        machines = await store.fetch_machines(conn, org)
        for m in machines:
            if m["status"] != "active" or m["id"] in logged or not m["site_id"]:
                continue
            if not _visible(auth_context, m["project_id"], m["site_id"]):
                continue
            if (project_ids is not None and m["project_id"] not in project_ids) or (site_id and m["site_id"] != site_id):
                continue
            missing.append({"id": str(m["id"]), "ref": rules.ref(m["number"]), "name": m["name"], "type": m["type"],
                            "kind": m["kind"], "ownership": m["ownership"], "site_id": str(m["site_id"]),
                            "site_name": m.get("site_name"), "project_id": str(m["project_id"]),
                            "project_name": m.get("project_name"),
                            "operator_name": m["operator_name"] or m.get("operator_worker_name")})
    return {
        "date_from": date_from.isoformat(), "date_to": date_to.isoformat(),
        "items": [log_out(x, money) for x in rows],
        "totals": {"worked": rules.num(t["worked"]), "idle": rules.num(t["idle"]), "breakdown": rules.num(t["breakdown"]),
                   "fuel_litres": rules.num(t["fuel"]), "fuel_cost": rules.money(t["fuel_cost"]) if money else None,
                   "machines": len({x["equipment_id"] for x in rows}), "logs": len(rows)},
        "missing": missing,
    }


@router.delete("/logs/{log_id}")
async def void_log(log_id: uuid.UUID, auth_context: AuthorizationContext = Depends(get_auth_context),
                   conn: AsyncConnection = Depends(get_db_conn)):
    """Take back a day log (saved by mistake). It stays in the history as voided; the issue it raised stays open."""
    org = auth_context.organization_id
    rows = await store.fetch_events(conn, org, ids=[log_id], event_types=None)
    if not rows or not _visible(auth_context, rows[0]["project_id"], rows[0]["site_id"]):
        raise HTTPException(status_code=404, detail="Log not found")
    x = rows[0]
    if x["event_type"] != "day_log":
        raise HTTPException(status_code=422, detail="Only a day's log can be taken back.")
    _authorize_write(auth_context, x["project_id"], x["site_id"])
    await store.void_event(conn, org, log_id, by=auth_context.user_id)
    return {"id": str(log_id), "status": "voided"}


# ---------------------------------------------------------------------------------------------------------------
# Hire bills and the hire check (NXT-13)
# ---------------------------------------------------------------------------------------------------------------

def _bills_role(auth: AuthorizationContext) -> None:
    if not (may_manage_money(auth.role) or may_act_on_material_requests(auth.role)):
        raise HTTPException(status_code=403, detail="Only an admin, owner, finance or project manager can enter hire bills.")


def _see_money(auth: AuthorizationContext) -> None:
    if not _money(auth):
        raise HTTPException(status_code=403, detail="Hire bills and costs are for the roles that see spending.")


class BillIn(BaseModel):
    equipment_id: uuid.UUID
    period_from: datetime.date
    period_to: datetime.date
    billed_hours: Decimal | None = Field(default=None, ge=0)
    billed_days: Decimal | None = Field(default=None, ge=0)
    amount: Decimal = Field(ge=0)
    bill_ref: str | None = Field(default=None, max_length=60)
    bill_date: datetime.date | None = None
    #: The bill's expense (on the hire company's ledger), when it was recorded in Expenses.
    expense_id: uuid.UUID | None = None
    notes: str | None = Field(default=None, max_length=300)


class BillUpdate(BaseModel):
    period_from: datetime.date | None = None
    period_to: datetime.date | None = None
    billed_hours: Decimal | None = Field(default=None, ge=0)
    billed_days: Decimal | None = Field(default=None, ge=0)
    amount: Decimal | None = Field(default=None, ge=0)
    bill_ref: str | None = Field(default=None, max_length=60)
    bill_date: datetime.date | None = None
    expense_id: uuid.UUID | None = None
    notes: str | None = Field(default=None, max_length=300)


async def _check_expense(conn: AsyncConnection, org: uuid.UUID, expense_id: uuid.UUID | None) -> None:
    if expense_id is None:
        return
    row = (await conn.execute(text("SELECT 1 FROM expenses WHERE id = :id AND organization_id = :org"),
                              {"id": expense_id, "org": org})).first()
    if row is None:
        raise HTTPException(status_code=422, detail="expense_id is not one of this company's expenses")


async def _bill_with_check(conn: AsyncConnection, auth: AuthorizationContext, bill_id: uuid.UUID) -> dict:
    org = auth.organization_id
    b = (await store.fetch_bills(conn, org, ids=[bill_id]))[0]
    m = await _machine_any(conn, auth, b["equipment_id"])
    logs = await store.fetch_events(conn, org, equipment_ids=[m["id"]])
    return bill_out(b, True, rules.hire_check(m, logs, b, await _today(conn, org)))


@router.post("/hire-bills", status_code=201)
async def create_bill(body: BillIn, auth_context: AuthorizationContext = Depends(get_auth_context),
                      conn: AsyncConnection = Depends(get_db_conn)):
    """A hire company's bill for one machine and period, checked at once against the hours recorded."""
    _bills_role(auth_context)
    _see_money(auth_context)
    org = auth_context.organization_id
    m = await _machine(conn, auth_context, body.equipment_id)
    if body.period_to < body.period_from:
        raise HTTPException(status_code=422, detail="The period ends before it starts.")
    await _check_expense(conn, org, body.expense_id)
    overlap = [b for b in await store.fetch_bills(conn, org, equipment_ids=[m["id"]], date_from=body.period_from,
                                                  date_to=body.period_to)]
    if overlap:
        b = overlap[0]
        raise HTTPException(status_code=409, detail={
            "code": "overlapping_bill",
            "message": f"{m['name']} already has a bill for {b['period_from']:%d %b} – {b['period_to']:%d %b}"
                       + (f" ({b['bill_ref']})" if b["bill_ref"] else "") + "."})
    bill_id = await store.insert_bill(conn, org, {**body.model_dump(), "vendor_id": m["vendor_id"]}, by=auth_context.user_id)
    return await _bill_with_check(conn, auth_context, bill_id)


@router.patch("/hire-bills/{bill_id}")
async def update_bill(bill_id: uuid.UUID, body: BillUpdate, auth_context: AuthorizationContext = Depends(get_auth_context),
                      conn: AsyncConnection = Depends(get_db_conn)):
    _bills_role(auth_context)
    _see_money(auth_context)
    org = auth_context.organization_id
    rows = await store.fetch_bills(conn, org, ids=[bill_id])
    if not rows:
        raise HTTPException(status_code=404, detail="Hire bill not found")
    await _machine(conn, auth_context, rows[0]["equipment_id"])
    values = body.model_dump(exclude_unset=True)
    f, t = values.get("period_from", rows[0]["period_from"]), values.get("period_to", rows[0]["period_to"])
    if t < f:
        raise HTTPException(status_code=422, detail="The period ends before it starts.")
    await _check_expense(conn, org, values.get("expense_id"))
    await store.update_bill(conn, org, bill_id, values)
    return await _bill_with_check(conn, auth_context, bill_id)


@router.delete("/hire-bills/{bill_id}")
async def delete_bill(bill_id: uuid.UUID, auth_context: AuthorizationContext = Depends(get_auth_context),
                      conn: AsyncConnection = Depends(get_db_conn)):
    _bills_role(auth_context)
    org = auth_context.organization_id
    rows = await store.fetch_bills(conn, org, ids=[bill_id])
    if not rows:
        raise HTTPException(status_code=404, detail="Hire bill not found")
    await _machine(conn, auth_context, rows[0]["equipment_id"])
    await store.delete_bill(conn, org, bill_id)
    return {"id": str(bill_id), "status": "deleted"}


@router.get("/hire-check")
async def hire_check(
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    vendor_id: uuid.UUID | None = None,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Per hired machine in the period (default this month): what the hours recorded on site come to, the bills that
    cover it with their check, and what is not billed yet. The owner's "the bill says 8 hours a day; how many did it
    work?"."""
    _see_money(auth_context)
    org = auth_context.organization_id
    today = await _today(conn, org)
    date_from = date_from or today.replace(day=1)
    date_to = date_to or today
    if date_from > date_to:
        raise HTTPException(status_code=422, detail="date_from is after date_to")
    machines = [m for m in await store.fetch_machines(conn, org, vendor_id=vendor_id)
                if m["ownership"] == "hired" and _visible(auth_context, m["project_id"], m["site_id"])]
    ids = [m["id"] for m in machines]
    logs = await store.fetch_events(conn, org, equipment_ids=ids, date_to=date_to) if ids else []
    bills = await store.fetch_bills(conn, org, equipment_ids=ids, date_from=date_from, date_to=date_to) if ids else []
    out, totals = [], defaultdict(lambda: rules.ZERO)
    for m in machines:
        mine = [x for x in logs if x["equipment_id"] == m["id"]]
        lines = rules.hire_lines(m, mine, date_from, date_to, today)
        in_period = [x for x in mine if date_from <= x["occurred_date"] <= date_to]
        if not lines and not in_period and m["status"] != "active":
            continue
        t = _totals(in_period)
        expected = sum((x["amount"] for x in lines), rules.ZERO)
        my_bills = [b for b in bills if b["equipment_id"] == m["id"]]
        billed_amount = sum((rules.d(b["amount"]) for b in my_bills), rules.ZERO)
        unbilled = sum((x["amount"] for x in lines if rules.billed(x["date"], my_bills) is None), rules.ZERO)
        checks = [bill_out(b, True, rules.hire_check(m, mine, b, today)) for b in my_bills]
        status = "over" if any(c["check"]["status"] == "over" for c in checks) else \
            "unbilled" if unbilled > 0 else "check" if any(c["check"]["status"] == "check" for c in checks) else \
            "ok" if my_bills else "no_bill"
        totals["expected"] += expected
        totals["billed"] += billed_amount
        totals["unbilled"] += unbilled
        out.append({
            "id": str(m["id"]), "ref": rules.ref(m["number"]), "name": m["name"], "type": m["type"],
            "vendor_id": _s(m["vendor_id"]), "vendor_name": m.get("vendor_name"),
            "rate": rules.money(rules.d(m["rate"])) if m["rate"] is not None else None, "rate_unit": m["rate_unit"],
            "min_hours_per_day": rules.num(rules.d(m["min_hours_per_day"])) if m["min_hours_per_day"] is not None else None,
            "site_name": m.get("site_name"), "project_name": m.get("project_name"), "status": m["status"],
            "worked": rules.num(t["worked"]), "idle": rules.num(t["idle"]), "breakdown": rules.num(t["breakdown"]),
            "days_on_site": sum(1 for x in in_period if rules.on_site(x)), "days_logged": len(in_period),
            "charged_hours": rules.num(sum((x["hours"] for x in lines), rules.ZERO)),
            "expected": rules.money(expected), "billed": rules.money(billed_amount), "unbilled": rules.money(unbilled),
            "bills": checks, "state": status,
        })
    order = {"over": 0, "unbilled": 1, "check": 2, "no_bill": 3, "ok": 4}
    out.sort(key=lambda x: (order[x["state"]], x["name"].casefold()))
    return {"date_from": date_from.isoformat(), "date_to": date_to.isoformat(), "items": out,
            "totals": {k: rules.money(v) for k, v in totals.items()} | {
                "over": sum(1 for x in out if x["state"] == "over")}}


# ---------------------------------------------------------------------------------------------------------------
# Costs (for the cost centres, CC-01) and the DPR
# ---------------------------------------------------------------------------------------------------------------

@router.get("/costs")
async def costs(
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    project_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Hire and diesel per site for the period (default this month): what the machines cost."""
    _see_money(auth_context)
    org = auth_context.organization_id
    project_ids, denied = _resolve_project_ids(auth_context, project_id)
    if denied:
        return {"by_site": [], "total": "0.00"}
    today = await _today(conn, org)
    date_from, date_to = date_from or today.replace(day=1), date_to or today
    rows = await machine_costs(conn, org, project_ids=project_ids, site_id=site_id, date_from=date_from, date_to=date_to,
                               visible=lambda p, s: _visible(auth_context, p, s))
    names = {}
    if rows:
        found = (await conn.execute(text(
            "SELECT s.id, s.name, p.name AS project FROM sites s JOIN projects p ON p.id = s.project_id "
            "WHERE s.organization_id = :org AND s.id = ANY(:ids)"),
            {"org": org, "ids": [k[1] for k in rows if k[1]]})).mappings().all()
        names = {r["id"]: (r["project"], r["name"]) for r in found}
    by_site = sorted(({"project_id": str(p), "site_id": _s(s), "project_name": names.get(s, ("", ""))[0],
                       "site_name": names.get(s, ("", None))[1], "hire": rules.money(v["hire"]),
                       "fuel": rules.money(v["fuel"]), "total": rules.money(v["hire"] + v["fuel"]),
                       "hours": rules.num(v["hours"]), "litres": rules.num(v["litres"])}
                      for (p, s), v in rows.items()), key=lambda x: -Decimal(x["total"]))
    hire = sum((v["hire"] for v in rows.values()), rules.ZERO)
    fuel = sum((v["fuel"] for v in rows.values()), rules.ZERO)
    return {"date_from": date_from.isoformat(), "date_to": date_to.isoformat(), "hire": rules.money(hire),
            "fuel": rules.money(fuel), "total": rules.money(hire + fuel), "by_site": by_site}


# ---------------------------------------------------------------------------------------------------------------
# Shuttering, scaffolding and tools (NXT-14): materials in a returnable category
# ---------------------------------------------------------------------------------------------------------------

@router.get("/returnables")
async def returnables(
    project_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """What each site holds of the returnable items (plates, props, scaffold pipes, tools), from stock; what went
    out as lost or damaged (usage marked wastage); and the categories, so the office can mark one returnable."""
    from mesiri.infrastructure.postgres.repositories.materials import PostgresMaterialReadRepository

    org = auth_context.organization_id
    cats = (await conn.execute(text(
        "SELECT c.id, c.name, c.parent_id, c.returnable, p.name AS parent_name, p.returnable AS parent_returnable "
        "FROM material_categories c LEFT JOIN material_categories p ON p.id = c.parent_id "
        "WHERE c.organization_id = :org AND c.is_active ORDER BY COALESCE(p.name, c.name), c.parent_id NULLS FIRST, c.name"),
        {"org": org})).mappings().all()
    returnable_ids = {c["id"] for c in cats if c["returnable"] or c["parent_returnable"]}
    categories = [{"id": str(c["id"]), "name": c["name"], "parent_id": _s(c["parent_id"]),
                   "parent_name": c["parent_name"], "returnable": bool(c["returnable"]),
                   "via_parent": bool(c["parent_returnable"]) and not c["returnable"]} for c in cats]
    project_ids, denied = _resolve_project_ids(auth_context, project_id)
    if denied or not returnable_ids:
        return {"items": [], "sites": [], "categories": categories}
    stock = await PostgresMaterialReadRepository(conn).get_stock_levels(organization_id=org, project_ids=project_ids,
                                                                        site_id=site_id)
    stock = [s for s in stock if s.get("category_id") in returnable_ids and s.get("site_id")
             and _visible(auth_context, s["project_id"], s["site_id"])]
    # Lost / damaged: usage recorded as wastage, in the stock unit (its movement), not taken back.
    lost_rows = (await conn.execute(text(
        "SELECT mv.material_id, mv.site_id, SUM(mv.quantity) AS q FROM material_movements mv "
        "JOIN material_usage u ON u.id = mv.source_id AND mv.source_type = 'material_usage' "
        "WHERE mv.organization_id = :org AND u.movement_reason = 'WASTAGE' AND mv.movement_type = 'ISSUE' "
        "AND mv.reversal_of_movement_id IS NULL AND mv.material_id = ANY(:mats) "
        "AND NOT EXISTS (SELECT 1 FROM material_movements r WHERE r.reversal_of_movement_id = mv.id) "
        "GROUP BY mv.material_id, mv.site_id"),
        {"org": org, "mats": list({s["material_id"] for s in stock})})).mappings().all() if stock else []
    lost = {(r["material_id"], r["site_id"]): r["q"] for r in lost_rows}
    site_names = {}
    if stock:
        found = (await conn.execute(text(
            "SELECT s.id, s.name, s.project_id, p.name AS project FROM sites s JOIN projects p ON p.id = s.project_id "
            "WHERE s.organization_id = :org AND s.id = ANY(:ids)"),
            {"org": org, "ids": list({s["site_id"] for s in stock})})).mappings().all()
        site_names = {r["id"]: r for r in found}
    items: dict[uuid.UUID, dict] = {}
    for s in stock:
        it = items.setdefault(s["material_id"], {
            "material_id": str(s["material_id"]), "name": s["material_name"], "category": s.get("category"),
            "main_category": s.get("main_category"), "unit": s["unit"], "total": rules.ZERO, "lost": rules.ZERO,
            "sites": []})
        held = rules.d(s["current_stock"])
        gone = rules.d(lost.get((s["material_id"], s["site_id"])))
        it["total"] += held
        it["lost"] += gone
        site = site_names.get(s["site_id"])
        it["sites"].append({"site_id": str(s["site_id"]), "site_name": site["name"] if site else None,
                            "project_id": str(s["project_id"]), "project_name": site["project"] if site else None,
                            "held": rules.num(held), "received": rules.num(rules.d(s["total_received"])),
                            "lost": rules.num(gone)})
    out = sorted(items.values(), key=lambda x: (x["main_category"] or "", x["name"].casefold()))
    for it in out:
        it["total"], it["lost"] = rules.num(it["total"]), rules.num(it["lost"])
    sites = sorted({(x["site_id"], x["site_name"], x["project_name"]) for it in out for x in it["sites"]},
                   key=lambda x: (x[2] or "", x[1] or ""))
    return {"items": out, "categories": categories,
            "sites": [{"site_id": s[0], "site_name": s[1], "project_name": s[2]} for s in sites]}


class ReturnableIn(BaseModel):
    returnable: bool


@router.put("/returnables/categories/{category_id}")
async def set_returnable(category_id: uuid.UUID, body: ReturnableIn,
                         auth_context: AuthorizationContext = Depends(get_auth_context),
                         conn: AsyncConnection = Depends(get_db_conn)):
    """Mark a material category returnable (shuttering, scaffolding, tools): its items show here per site."""
    _office(auth_context, "change which categories are returnable")
    res = await conn.execute(text(
        "UPDATE material_categories SET returnable = :r, updated_at = now(), updated_by = :by "
        "WHERE id = :id AND organization_id = :org"),
        {"r": body.returnable, "by": auth_context.user_id, "id": category_id, "org": auth_context.organization_id})
    if not res.rowcount:  # type: ignore[attr-defined]
        raise HTTPException(status_code=404, detail="Category not found")
    return {"id": str(category_id), "returnable": body.returnable}


# Declared last: "/{machine_id}" would otherwise take /logs, /hire-check, /costs and /returnables.
@router.get("/{machine_id}")
async def get_machine(
    machine_id: uuid.UUID,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """One machine: the board's figures, its logbook for the period (default the last 30 days), what happened to it
    (moves, on / off hire, service), its hire bills with their check, and the period's totals."""
    org = auth_context.organization_id
    m = await _machine(conn, auth_context, machine_id)
    today = await _today(conn, org)
    date_to = date_to or today
    date_from = date_from or date_to - datetime.timedelta(days=29)
    if date_from > date_to:
        raise HTTPException(status_code=422, detail="date_from is after date_to")
    items, _ = await _board(conn, auth_context, [m], period=(date_from, date_to))
    out = items[0]
    money = _money(auth_context)
    every = await store.fetch_events(conn, org, equipment_ids=[m["id"]], event_types=None, include_voided=False)
    every = [x for x in every if _visible(auth_context, x["project_id"], x["site_id"])]
    logs = [x for x in every if x["event_type"] == "day_log" and date_from <= x["occurred_date"] <= date_to]
    t = _totals(logs)
    hire = rules.hire_lines(m, [x for x in every if x["event_type"] == "day_log"], date_from, date_to, today)
    bills = await store.fetch_bills(conn, org, equipment_ids=[m["id"]])
    all_logs = [x for x in every if x["event_type"] == "day_log"]
    out.update({
        "period": {"from": date_from.isoformat(), "to": date_to.isoformat(), "worked": rules.num(t["worked"]),
                   "idle": rules.num(t["idle"]), "breakdown": rules.num(t["breakdown"]),
                   "fuel_litres": rules.num(t["fuel"]), "trips": int(t["trips"]), "days_logged": len(logs),
                   "utilisation": _pct(rules.utilisation(t["worked"], t["idle"], t["breakdown"])),
                   "litres_per_hour": rules.num(t["fuel"] / t["worked"]) if t["worked"] and t["fuel"] else None,
                   "hire_cost": rules.money(sum((h["amount"] for h in hire), rules.ZERO)) if money else None,
                   "fuel_cost": rules.money(t["fuel_cost"]) if money else None},
        "logs": [log_out(x, money) for x in logs],
        "events": [log_out(x, money) for x in every if x["event_type"] != "day_log"][:50],
        "bills": [bill_out(b, money, rules.hire_check(m, all_logs, b, today) if money else None) for b in bills],
        "breakdowns": [log_out(x, money) for x in all_logs if rules.d(x.get("breakdown_hours")) > 0][:20],
    })
    return out
