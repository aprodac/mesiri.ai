"""Subcontracts API (NXT-05/06/07, CC-04): work orders, measurement, bills checked against both, retention / advance /
TDS. Plan: docs/plans/subcontractors-plan.md (S1-S4). Rules: ``rules.py``; reads: ``store.py``.

Who (decisions 8 Nov 2026):
- everyone with a project in scope sees its work orders (quantities and progress); rates, amounts, bills and money only
  for the roles that see spending (SEC-01);
- the office (``may_act_on_material_requests``) creates, edits, issues, completes, closes and cancels work orders;
- anyone who may record work at the site records a measurement;
- the roles that see spending record a subcontractor's bill and approve or reject a flagged one (D-S3: owner, admin,
  finance, and a PM within their projects);
- giving an advance and releasing retention move money: owner, admin, finance (SEC-03).
"""

from __future__ import annotations

import datetime
import json
import uuid
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.authorization.roles import (
    may_act_on_material_requests,
    may_manage_money,
    may_view_expenses,
)
from mesiri.domains.projects.router import get_auth_context
from mesiri.domains.subcontracts import rules, store
from mesiri.infrastructure.postgres.dependency import get_db_conn

router = APIRouter(prefix="/subcontracts", tags=["subcontracts"])


# --- who ----------------------------------------------------------------------------------------------------------


def _scope(auth: AuthorizationContext) -> set[uuid.UUID] | None:
    return None if auth.project_scope.grants_all_org_projects else set(auth.project_scope.project_ids)


def _in_scope(auth: AuthorizationContext, project_id: Any) -> bool:
    scope = _scope(auth)
    return scope is None or uuid.UUID(str(project_id)) in scope


def _office(auth: AuthorizationContext) -> None:
    if not may_act_on_material_requests(auth.role):
        raise HTTPException(status_code=403, detail="Work orders are given by the office (owner, admin, project manager).")


def _money(auth: AuthorizationContext, what: str) -> None:
    if not may_view_expenses(auth.role):
        raise HTTPException(status_code=403, detail=f"Only the roles that see spending can {what}.")


def _pays(auth: AuthorizationContext, what: str) -> None:
    if not may_manage_money(auth.role):
        raise HTTPException(status_code=403, detail=f"Only the owner, an admin or finance can {what}.")


def _shown(auth: AuthorizationContext, wo: dict) -> dict:
    """A site engineer sees quantities and progress, never rates, amounts or bills."""
    if may_view_expenses(auth.role):
        return {**wo, "with_money": True}
    lines = [{k: v for k, v in line.items() if k not in ("rate", "amount", "billed_amount")} for line in wo["lines"]]
    totals = {k: wo["totals"][k] for k in ("progress_pct", "bills", "to_check")}
    hidden = ("bills", "advance_agreed", "advance_recovery_pct", "tds_pct", "vendor_tds_pct", "retention_pct")
    return {**{k: v for k, v in wo.items() if k not in hidden}, "lines": lines, "totals": totals, "with_money": False}


async def _one(conn: AsyncConnection, auth: AuthorizationContext, wo_id: uuid.UUID, *, lock: bool = False) -> dict:
    if lock:
        await conn.execute(text("SELECT 1 FROM work_orders WHERE id = :id AND organization_id = :org FOR UPDATE"),
                           {"id": wo_id, "org": auth.organization_id})
    found = await store.fetch(conn, auth.organization_id, wo_id=wo_id)
    if not found or not _in_scope(auth, found[0]["project_id"]):
        raise HTTPException(status_code=404, detail="Work order not found")
    return found[0]


async def _who(conn: AsyncConnection, auth: AuthorizationContext) -> str | None:
    return (await conn.execute(text("SELECT full_name FROM users WHERE id = :u"), {"u": auth.user_id})).scalar()


async def _settings(conn: AsyncConnection, org: uuid.UUID) -> dict:
    from mesiri.infrastructure.postgres.repositories.organization_settings import (
        PostgresOrganizationSettingsRepository,
    )

    stored = await PostgresOrganizationSettingsRepository(conn).get(org, "finance_settings")
    return stored if isinstance(stored, dict) else {}


async def _today(conn: AsyncConnection, org: uuid.UUID) -> datetime.date:
    from mesiri.application.dpr import project_day

    return await project_day.company_today(conn, org)


# --- list, one ------------------------------------------------------------------------------------------------------


@router.get("/work-orders")
async def list_work_orders(
    project_id: uuid.UUID | None = None,
    vendor_id: uuid.UUID | None = None,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Work orders in scope, newest first, with progress; and the figures the tiles show."""
    scope = _scope(auth_context)
    if project_id is not None:
        if scope is not None and project_id not in scope:
            raise HTTPException(status_code=404, detail="Project not found")
        scope = {project_id}
    rows = [_shown(auth_context, w) for w in await store.fetch(conn, auth_context.organization_id, project_ids=scope,
                                                               vendor_id=vendor_id)]
    live = [w for w in rows if w["status"] in ("draft", "issued")]
    money = may_view_expenses(auth_context.role)
    summary = {
        "open": len([w for w in rows if w["status"] == "issued"]), "drafts": len([w for w in rows if w["status"] == "draft"]),
        "to_check": sum(w["totals"]["to_check"] for w in rows), "flagged_lines": sum(w["flags"] for w in live),
    }
    if money:
        summary.update({
            "value": store._m(sum((Decimal(w["totals"]["value"]) for w in live), Decimal(0))),
            "retention_held": store._m(sum((Decimal(w["totals"]["retention_held"]) for w in rows), Decimal(0))),
            "advance_left": store._m(sum((Decimal(w["totals"]["advance_left"]) for w in rows), Decimal(0))),
            "payable_now": store._m(sum((Decimal(w["totals"]["payable_now"]) for w in rows), Decimal(0))),
        })
    return {"work_orders": rows, "summary": summary, "with_money": money}


@router.get("/work-orders/{wo_id}")
async def get_work_order(wo_id: uuid.UUID, auth_context: AuthorizationContext = Depends(get_auth_context),
                         conn: AsyncConnection = Depends(get_db_conn)):
    wo = await _one(conn, auth_context, wo_id)
    out = _shown(auth_context, wo)
    out["measurements"] = await store.measurements(conn, wo_id)
    out["history"] = await store.history(conn, wo_id)
    out["team"] = await store.team_days(conn, auth_context.organization_id, wo["vendor_id"], wo["project_id"], wo["site_id"])
    return out


# --- create / edit / status --------------------------------------------------------------------------------------


class LineIn(BaseModel):
    id: uuid.UUID | None = None
    planned_item_id: uuid.UUID | None = None
    description: str | None = None
    unit: str | None = None
    quantity: Decimal = Field(gt=0)
    rate: Decimal = Field(ge=0)


class WorkOrderIn(BaseModel):
    vendor_id: uuid.UUID | None = None
    #: A new subcontractor by name (added as kind subcontractor) when there is no vendor_id.
    vendor_name: str | None = None
    project_id: uuid.UUID
    site_id: uuid.UUID | None = None
    #: The work order's name ("First-floor slab"); `title` would clash with JSON-schema keywords in tool schemas.
    name: str | None = None
    start_date: datetime.date | None = None
    end_date: datetime.date | None = None
    retention_pct: Decimal | None = Field(default=None, ge=0, le=50)
    defect_days: int | None = Field(default=None, ge=0, le=1825)
    advance_agreed: Decimal | None = Field(default=None, ge=0)
    advance_recovery_pct: Decimal | None = Field(default=None, ge=0, le=100)
    tds_pct: Decimal | None = Field(default=None, ge=0, le=20)
    their_ref: str | None = None
    terms: str | None = None
    notes: str | None = None
    lines: list[LineIn] = Field(min_length=1)
    issue: bool = False


class WorkOrderEdit(BaseModel):
    site_id: uuid.UUID | None = None
    #: The work order's name ("First-floor slab"); `title` would clash with JSON-schema keywords in tool schemas.
    name: str | None = None
    start_date: datetime.date | None = None
    end_date: datetime.date | None = None
    retention_pct: Decimal | None = Field(default=None, ge=0, le=50)
    defect_days: int | None = Field(default=None, ge=0, le=1825)
    advance_agreed: Decimal | None = Field(default=None, ge=0)
    advance_recovery_pct: Decimal | None = Field(default=None, ge=0, le=100)
    tds_pct: Decimal | None = Field(default=None, ge=0, le=20)
    their_ref: str | None = None
    terms: str | None = None
    notes: str | None = None
    lines: list[LineIn] | None = None


async def _boq_line(conn: AsyncConnection, auth: AuthorizationContext, item_id: uuid.UUID, project_id: uuid.UUID) -> dict:
    row = (await conn.execute(text(
        "SELECT pi.id, pi.work_type, pi.subcontract_rate, u.code AS unit FROM work_package_planned_items pi "
        "JOIN work_packages wp ON wp.id = pi.work_package_id LEFT JOIN units_of_measure u ON u.id = pi.unit_id "
        "WHERE pi.id = :id AND pi.organization_id = :org AND wp.project_id = :p"),
        {"id": item_id, "org": auth.organization_id, "p": project_id})).mappings().first()
    if row is None:
        raise HTTPException(status_code=422, detail="That BOQ line is not in this project.")
    return dict(row)


async def _clean_lines(conn: AsyncConnection, auth: AuthorizationContext, project_id: uuid.UUID, lines: list[LineIn]) -> list[dict]:
    out = []
    for i, line in enumerate(lines, start=1):
        desc, unit = (line.description or "").strip(), (line.unit or "").strip()
        if line.planned_item_id is not None:
            boq = await _boq_line(conn, auth, line.planned_item_id, project_id)
            desc = desc or boq["work_type"]
            unit = unit or (boq["unit"] or "")
        if not desc or not unit:
            raise HTTPException(status_code=422, detail=f"Line {i}: say the work and its unit (m³, sq ft, nos…).")
        out.append({"id": line.id, "planned_item_id": line.planned_item_id, "description": desc, "unit": unit,
                    "quantity": line.quantity, "rate": line.rate.quantize(Decimal("0.01")), "position": i})
    return out


async def _vendor_for(conn: AsyncConnection, auth: AuthorizationContext, body: WorkOrderIn) -> uuid.UUID:
    from mesiri.infrastructure.postgres.repositories.vendors import PostgresVendorRepository

    repo = PostgresVendorRepository(conn)
    if body.vendor_id is not None:
        v = await repo.get_by_id(auth.organization_id, body.vendor_id)
        if v is None:
            raise HTTPException(status_code=404, detail="Subcontractor not found")
        return v.id
    name = (body.vendor_name or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="Who is the work given to?")
    v = await repo.find_by_name_exact_active(auth.organization_id, name) or await repo.create(
        organization_id=auth.organization_id, name=name, created_by=auth.user_id)
    await conn.execute(text("UPDATE vendors SET kind = 'subcontractor' WHERE id = :v AND kind = 'supplier' "
                            "AND NOT EXISTS (SELECT 1 FROM material_receipts r WHERE r.vendor_id = :v)"), {"v": v.id})
    return v.id


@router.post("/work-orders", status_code=201)
async def create_work_order(body: WorkOrderIn, auth_context: AuthorizationContext = Depends(get_auth_context),
                            conn: AsyncConnection = Depends(get_db_conn)):
    """A work order for a subcontractor: lines from the BOQ or typed, agreed rate and quantity, retention, advance."""
    _office(auth_context)
    if not _in_scope(auth_context, body.project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    if body.site_id is not None:
        ok = (await conn.execute(text("SELECT 1 FROM sites WHERE id = :s AND project_id = :p AND organization_id = :org"),
                                 {"s": body.site_id, "p": body.project_id, "org": auth_context.organization_id})).first()
        if not ok:
            raise HTTPException(status_code=422, detail="That site is not in this project.")
    if body.start_date and body.end_date and body.end_date < body.start_date:
        raise HTTPException(status_code=422, detail="The end date is before the start.")
    org = auth_context.organization_id
    vendor_id = await _vendor_for(conn, auth_context, body)
    lines = await _clean_lines(conn, auth_context, body.project_id, body.lines)
    settings = await _settings(conn, org)
    number = await store.next_number(conn, org)
    wo_id = uuid.uuid4()
    await conn.execute(text(
        "INSERT INTO work_orders (id, organization_id, number, vendor_id, project_id, site_id, title, status, start_date, "
        "end_date, retention_pct, defect_days, advance_agreed, advance_recovery_pct, tds_pct, their_ref, terms, notes, "
        "created_by, issued_at) VALUES (:id, :org, :n, :v, :p, :s, :title, :status, :sd, :ed, :ret, :dd, :adv, :rec, "
        ":tds, :ref, :terms, :notes, :by, :issued)"),
        {"id": wo_id, "org": org, "n": number, "v": vendor_id, "p": body.project_id, "s": body.site_id,
         "title": (body.name or "").strip() or None, "status": "issued" if body.issue else "draft",
         "sd": body.start_date, "ed": body.end_date,
         "ret": body.retention_pct if body.retention_pct is not None else Decimal(str(settings.get("retention_default_pct", rules.DEFAULT_RETENTION_PCT))),
         "dd": body.defect_days or 0, "adv": body.advance_agreed, "rec": body.advance_recovery_pct, "tds": body.tds_pct,
         "ref": (body.their_ref or "").strip() or None, "terms": (body.terms or "").strip() or None,
         "notes": (body.notes or "").strip() or None, "by": auth_context.user_id,
         "issued": datetime.datetime.now(tz=datetime.UTC) if body.issue else None})
    await _insert_lines(conn, org, wo_id, lines)
    who = await _who(conn, auth_context)
    await store.log(conn, org, wo_id, "created", f"{store.ref(number)} written with {len(lines)} lines"
                    + (" and issued" if body.issue else " (draft)"), auth_context.user_id, who)
    return _shown(auth_context, await _one(conn, auth_context, wo_id))


async def _insert_lines(conn: AsyncConnection, org: uuid.UUID, wo_id: uuid.UUID, lines: list[dict]) -> None:
    for line in lines:
        await conn.execute(text(
            "INSERT INTO work_order_lines (organization_id, work_order_id, planned_item_id, description, unit, quantity, "
            "rate, position) VALUES (:org, :wo, :pi, :d, :u, :q, :r, :pos)"),
            {"org": org, "wo": wo_id, "pi": line["planned_item_id"], "d": line["description"], "u": line["unit"],
             "q": line["quantity"], "r": line["rate"], "pos": line["position"]})


@router.patch("/work-orders/{wo_id}")
async def edit_work_order(wo_id: uuid.UUID, body: WorkOrderEdit, auth_context: AuthorizationContext = Depends(get_auth_context),
                          conn: AsyncConnection = Depends(get_db_conn)):
    """Change a work order. A draft changes freely; an issued one keeps its history (every change logged), and a line
    can never go below what was already measured or billed on it."""
    _office(auth_context)
    wo = await _one(conn, auth_context, wo_id, lock=True)
    if wo["status"] in ("closed", "cancelled"):
        raise HTTPException(status_code=409, detail=f"{wo['ref']} is {wo['status']}: reopen it first.")
    org = auth_context.organization_id
    changes: list[str] = []
    fields = {"site_id": "site", "name": "name", "start_date": "start", "end_date": "end", "retention_pct": "retention %",
              "defect_days": "defect days", "advance_agreed": "advance", "advance_recovery_pct": "advance recovery %",
              "tds_pct": "TDS %", "their_ref": "their reference", "terms": "terms", "notes": "notes"}
    sets, params = [], {"id": wo_id, "org": org}
    for key, label in fields.items():
        if key in body.model_fields_set:
            val = getattr(body, key)
            if isinstance(val, str):
                val = val.strip() or None
            before = wo.get("title" if key == "name" else key)
            if str(before or "") != str(val if val is not None else ""):
                sets.append(f"{'title' if key == 'name' else key} = :{key}")
                params[key] = val
                changes.append(f"{label}: {before or '—'} → {val if val is not None else '—'}")
    if sets:
        await conn.execute(text(f"UPDATE work_orders SET {', '.join(sets)}, updated_at = now() "  # noqa: S608
                                "WHERE id = :id AND organization_id = :org"), params)
    if body.lines is not None:
        new = await _clean_lines(conn, auth_context, uuid.UUID(wo["project_id"]), body.lines)
        old = {line["id"]: line for line in wo["lines"]}
        kept = {str(x["id"]) for x in new if x["id"]}
        for line_id, line in old.items():
            if line_id not in kept:
                if Decimal(line["measured"]) > 0 or Decimal(line["billed"]) > 0:
                    raise HTTPException(status_code=409, detail=f"“{line['description']}” has work measured or billed: it can't be taken off.")
                await conn.execute(text("DELETE FROM work_order_lines WHERE id = :id"), {"id": line_id})
                changes.append(f"line taken off: {line['description']}")
        for x in new:
            if x["id"] and str(x["id"]) in old:
                o = old[str(x["id"])]
                floor = max(Decimal(o["measured"]), Decimal(o["billed"]))
                if x["quantity"] < floor:
                    raise HTTPException(status_code=409, detail=f"“{o['description']}”: {rules.qty(floor)} {o['unit']} is already measured or billed.")
                await conn.execute(text(
                    "UPDATE work_order_lines SET description = :d, unit = :u, quantity = :q, rate = :r, position = :pos, "
                    "planned_item_id = :pi WHERE id = :id"), {"d": x["description"], "u": x["unit"], "q": x["quantity"],
                                                             "r": x["rate"], "pos": x["position"], "pi": x["planned_item_id"], "id": x["id"]})
                if Decimal(o["quantity"]) != x["quantity"] or Decimal(o["rate"]) != x["rate"]:
                    changes.append(f"{o['description']}: {o['quantity']} {o['unit']} @ ₹{o['rate']} → {rules.qty(x['quantity'])} @ ₹{x['rate']}")
            else:
                await _insert_lines(conn, org, wo_id, [x])
                changes.append(f"line added: {x['description']} {rules.qty(x['quantity'])} {x['unit']} @ ₹{x['rate']}")
    if changes:
        await store.log(conn, org, wo_id, "changed", "; ".join(changes), auth_context.user_id, await _who(conn, auth_context))
    return _shown(auth_context, await _one(conn, auth_context, wo_id))


# --- measurement (S2) ---------------------------------------------------------------------------------------------


class MeasurementIn(BaseModel):
    line_id: uuid.UUID
    quantity: Decimal = Field(gt=0)
    measured_on: datetime.date | None = None
    notes: str | None = None
    photo_key: str | None = None
    source: str = "web"


async def _may_record(conn: AsyncConnection, auth: AuthorizationContext, wo: dict) -> None:
    from mesiri.domains.materials.router import _authorize_write

    _authorize_write(auth, uuid.UUID(wo["project_id"]), uuid.UUID(wo["site_id"]) if wo["site_id"] else None)


@router.post("/work-orders/{wo_id}/measurements", status_code=201)
async def add_measurement(wo_id: uuid.UUID, body: MeasurementIn, auth_context: AuthorizationContext = Depends(get_auth_context),
                          conn: AsyncConnection = Depends(get_db_conn)):
    """Work done on a line, measured or reported on site. More than the line agreed is saved and flagged."""
    wo = await _one(conn, auth_context, wo_id)
    await _may_record(conn, auth_context, wo)
    if wo["status"] not in ("issued", "completed"):
        raise HTTPException(status_code=409, detail=f"{wo['ref']} is {wo['status']}: work is measured on an issued work order.")
    line = next((x for x in wo["lines"] if x["id"] == str(body.line_id)), None)
    if line is None:
        raise HTTPException(status_code=404, detail="Line not found")
    when = body.measured_on or await _today(conn, auth_context.organization_id)
    who = await _who(conn, auth_context)
    mid = (await conn.execute(text(
        "INSERT INTO work_order_measurements (organization_id, work_order_id, line_id, measured_on, quantity, notes, "
        "photo_key, status, source, recorded_by, recorded_by_name, decided_by, decided_at) VALUES (:org, :wo, :l, :d, :q, "
        ":n, :ph, 'confirmed', :src, :u, :who, :u, now()) RETURNING id"),
        {"org": auth_context.organization_id, "wo": wo_id, "l": body.line_id, "d": when, "q": body.quantity,
         "n": (body.notes or "").strip() or None, "ph": body.photo_key, "src": body.source if body.source in ("web", "whatsapp") else "web",
         "u": auth_context.user_id, "who": who})).scalar()
    await store.log(conn, auth_context.organization_id, wo_id, "measured",
                    f"{rules.qty(body.quantity)} {line['unit']} {line['description']} on {when.isoformat()}", auth_context.user_id, who)
    after = await _one(conn, auth_context, wo_id)
    now_line = next(x for x in after["lines"] if x["id"] == str(body.line_id))
    return {"measurement_id": str(mid), "line": {k: now_line[k] for k in ("id", "description", "unit", "quantity", "measured", "remaining", "over_agreed")},
            "work_order": _shown(auth_context, after)}


class DecideIn(BaseModel):
    reason: str | None = None


@router.post("/measurements/{mid}/{decision}")
async def decide_measurement(mid: uuid.UUID, decision: str, body: DecideIn | None = None,
                             auth_context: AuthorizationContext = Depends(get_auth_context),
                             conn: AsyncConnection = Depends(get_db_conn)):
    """confirm / reject a measurement the subcontractor reported (proposed); remove one recorded by mistake."""
    if decision not in ("confirm", "reject", "remove"):
        raise HTTPException(status_code=404, detail="Not found")
    row = (await conn.execute(text("SELECT * FROM work_order_measurements WHERE id = :id AND organization_id = :org"),
                              {"id": mid, "org": auth_context.organization_id})).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Measurement not found")
    wo = await _one(conn, auth_context, row["work_order_id"])
    await _may_record(conn, auth_context, wo)
    to = {"confirm": "confirmed", "reject": "rejected", "remove": "removed"}[decision]
    if decision in ("confirm", "reject") and row["status"] != "proposed":
        raise HTTPException(status_code=409, detail="Only a measurement waiting for a check is confirmed or rejected.")
    if decision == "remove":
        line = next(x for x in wo["lines"] if x["id"] == str(row["line_id"]))
        if row["status"] == "confirmed" and Decimal(line["billed"]) > Decimal(line["measured"]) - Decimal(row["quantity"]):
            raise HTTPException(status_code=409, detail="That much of this line is billed already: it can't be taken off.")
    await conn.execute(text("UPDATE work_order_measurements SET status = :s, decided_by = :u, decided_at = now() WHERE id = :id"),
                       {"s": to, "u": auth_context.user_id, "id": mid})
    if decision == "remove" and row["activity_quantity_id"]:
        await conn.execute(text("UPDATE activity_quantities SET work_order_line_id = NULL WHERE id = :a"), {"a": row["activity_quantity_id"]})
    reason = ((body.reason if body else None) or "").strip()
    await store.log(conn, auth_context.organization_id, row["work_order_id"], f"measurement_{decision}",
                    f"{rules.qty(row['quantity'])} measured on {row['measured_on'].isoformat()} {to}" + (f": {reason}" if reason else ""),
                    auth_context.user_id, await _who(conn, auth_context))
    return _shown(auth_context, await _one(conn, auth_context, row["work_order_id"]))


@router.get("/work-orders/{wo_id}/site-work")
async def site_work(wo_id: uuid.UUID, auth_context: AuthorizationContext = Depends(get_auth_context),
                    conn: AsyncConnection = Depends(get_db_conn)):
    """CC-04: work recorded on site (daily work updates) that may be this work order's, not counted on any line yet:
    same project (and site), last 90 days, with a quantity; the line it most likely is (same unit; the contractor named
    or the words of the line in the work)."""
    wo = await _one(conn, auth_context, wo_id)
    p = {"org": auth_context.organization_id, "proj": wo["project_id"], "from": (await _today(conn, auth_context.organization_id)) - datetime.timedelta(days=90)}
    sql = ("SELECT q.id, q.quantity, q.work_type AS q_work, u.code AS unit, a.activity_date, a.work_type, a.contractor, "
           "a.narrative, s.name AS site FROM activity_quantities q JOIN activities a ON a.id = q.activity_id "
           "JOIN units_of_measure u ON u.id = q.unit_id LEFT JOIN sites s ON s.id = a.site_id "
           "WHERE a.organization_id = :org AND a.project_id = :proj AND a.deleted_at IS NULL AND q.work_order_line_id IS NULL "
           "AND a.activity_date >= :from")
    if wo["site_id"]:
        sql += " AND a.site_id = :site"
        p["site"] = wo["site_id"]
    rows = (await conn.execute(text(sql + " ORDER BY a.activity_date DESC LIMIT 200"), p)).mappings().all()
    vendor_word = wo["vendor_name"].split()[0].lower()
    out = []
    for r in rows:
        words = " ".join(x for x in (r["work_type"], r["q_work"], r["narrative"]) if x).lower()
        fits = [line for line in wo["lines"] if _same_unit(line["unit"], r["unit"])]
        best = max(fits, key=lambda line: _overlap(line["description"], words), default=None)
        named = bool(r["contractor"] and vendor_word in r["contractor"].lower())
        if not fits:
            continue
        out.append({"activity_quantity_id": str(r["id"]), "date": r["activity_date"].isoformat(), "quantity": rules.qty(r["quantity"]),
                    "unit": r["unit"], "work": r["work_type"] or r["q_work"], "contractor": r["contractor"], "site": r["site"],
                    "line_id": best["id"] if best else None, "line": best["description"] if best else None,
                    "likely": named or (best is not None and _overlap(best["description"], words) > 0)})
    out.sort(key=lambda x: (not x["likely"], x["date"]), reverse=False)
    return out


def _same_unit(a: str, b: str) -> bool:
    norm = {"m3": "cum", "m³": "cum", "cum": "cum", "cu.m": "cum", "m2": "sqm", "m²": "sqm", "sqm": "sqm", "sq.m": "sqm",
            "sqft": "sqft", "sq ft": "sqft", "sft": "sqft", "rft": "rft", "rmt": "rmt", "m": "rmt", "nos": "nos", "no": "nos", "kg": "kg"}
    return norm.get(a.strip().lower(), a.strip().lower()) == norm.get(b.strip().lower(), b.strip().lower())


def _overlap(desc: str, words: str) -> int:
    return sum(1 for w in desc.lower().replace("-", " ").split() if len(w) > 3 and w in words)


class LinkWorkIn(BaseModel):
    activity_quantity_id: uuid.UUID
    line_id: uuid.UUID


@router.post("/work-orders/{wo_id}/site-work", status_code=201)
async def count_site_work(wo_id: uuid.UUID, body: LinkWorkIn, auth_context: AuthorizationContext = Depends(get_auth_context),
                          conn: AsyncConnection = Depends(get_db_conn)):
    """Count work recorded on site on a line: a measurement from that work update (never twice)."""
    wo = await _one(conn, auth_context, wo_id)
    await _may_record(conn, auth_context, wo)
    line = next((x for x in wo["lines"] if x["id"] == str(body.line_id)), None)
    if line is None:
        raise HTTPException(status_code=404, detail="Line not found")
    q = (await conn.execute(text(
        "SELECT q.id, q.quantity, q.work_order_line_id, a.activity_date FROM activity_quantities q JOIN activities a ON a.id = q.activity_id "
        "WHERE q.id = :q AND a.organization_id = :org AND a.project_id = :p"),
        {"q": body.activity_quantity_id, "org": auth_context.organization_id, "p": wo["project_id"]})).mappings().first()
    if q is None:
        raise HTTPException(status_code=404, detail="Work update not found")
    if q["work_order_line_id"] is not None:
        raise HTTPException(status_code=409, detail="That work is already counted on a work order.")
    who = await _who(conn, auth_context)
    await conn.execute(text(
        "INSERT INTO work_order_measurements (organization_id, work_order_id, line_id, measured_on, quantity, status, source, "
        "activity_quantity_id, recorded_by, recorded_by_name, decided_by, decided_at) VALUES (:org, :wo, :l, :d, :qty, "
        "'confirmed', 'activity', :aq, :u, :who, :u, now())"),
        {"org": auth_context.organization_id, "wo": wo_id, "l": body.line_id, "d": q["activity_date"], "qty": q["quantity"],
         "aq": q["id"], "u": auth_context.user_id, "who": who})
    await conn.execute(text("UPDATE activity_quantities SET work_order_line_id = :l, planned_item_id = COALESCE(planned_item_id, :pi) WHERE id = :q"),
                       {"l": body.line_id, "pi": line["planned_item_id"], "q": q["id"]})
    await store.log(conn, auth_context.organization_id, wo_id, "measured",
                    f"{rules.qty(q['quantity'])} {line['unit']} {line['description']} from the site's work update of {q['activity_date'].isoformat()}",
                    auth_context.user_id, who)
    return _shown(auth_context, await _one(conn, auth_context, wo_id))


# --- bills (S3) and their money (S4) ------------------------------------------------------------------------------


class BillLineIn(BaseModel):
    line_id: uuid.UUID
    quantity: Decimal = Field(gt=0)
    rate: Decimal | None = Field(default=None, ge=0)


class BillIn(BaseModel):
    lines: list[BillLineIn] = Field(min_length=1)
    #: The bill's total as written; left out: its lines.
    amount: Decimal | None = Field(default=None, gt=0)
    their_bill_no: str | None = None
    bill_date: datetime.date | None = None
    media_object_key: str | None = None
    notes: str | None = None
    #: Override this bill's deductions (left out: the work order's rules).
    retention_pct: Decimal | None = Field(default=None, ge=0, le=50)
    advance_recover: Decimal | None = Field(default=None, ge=0)
    tds_pct: Decimal | None = Field(default=None, ge=0, le=20)
    source: str = "web"


async def _check(conn: AsyncConnection, auth: AuthorizationContext, wo: dict, body: BillIn, *, besides: uuid.UUID | None = None) -> dict:
    """The check and the deductions a bill would get, without saving anything."""
    lines = {x["id"]: {"description": x["description"], "unit": x["unit"], "quantity": Decimal(x["quantity"]), "rate": Decimal(x["rate"])}
             for x in wo["lines"]}
    measured = {x["id"]: Decimal(x["measured"]) for x in wo["lines"]}
    billed = {x["id"]: Decimal(x["billed"]) for x in wo["lines"]}
    if besides is not None:  # re-checking a saved bill: its own lines are not "before"
        for bl in (await conn.execute(text("SELECT line_id, quantity FROM work_order_bill_lines WHERE bill_id = :b"), {"b": besides})).mappings():
            billed[str(bl["line_id"])] -= Decimal(bl["quantity"])
    bill_lines = []
    for bl in body.lines:
        key = str(bl.line_id)
        if key not in lines:
            raise HTTPException(status_code=422, detail="A bill line is not on this work order.")
        bill_lines.append({"line_id": key, "quantity": bl.quantity, "rate": bl.rate if bl.rate is not None else lines[key]["rate"]})
    gross = rules.money(body.amount if body.amount is not None else sum((b["quantity"] * b["rate"] for b in bill_lines), Decimal(0)))
    flags = rules.check_bill(lines, measured, billed, bill_lines, gross)
    settings = await _settings(conn, auth.organization_id)
    tds = None
    if settings.get("tds_enabled"):
        tds = body.tds_pct if body.tds_pct is not None else Decimal(str(wo.get("tds_pct") or wo.get("vendor_tds_pct") or settings.get("tds_default_pct", rules.DEFAULT_TDS_PCT)))
    value = Decimal(wo["totals"]["value"])
    rec = rules.recovery_pct(Decimal(wo["advance_agreed"]) if wo.get("advance_agreed") else None, value,
                             Decimal(wo["advance_recovery_pct"]) if wo.get("advance_recovery_pct") else None)
    left = Decimal(wo["totals"]["advance_left"])
    d = rules.deductions(gross, retention_pct=body.retention_pct if body.retention_pct is not None else Decimal(wo["retention_pct"]),
                         recovery_pct_=rec, advance_outstanding=left, tds_pct=tds)
    if body.advance_recover is not None:
        d = rules.deductions(gross, retention_pct=body.retention_pct if body.retention_pct is not None else Decimal(wo["retention_pct"]),
                             recovery_pct_=Decimal(100) * min(body.advance_recover, left) / gross if gross else Decimal(0),
                             advance_outstanding=min(body.advance_recover, left), tds_pct=tds)
    return {"gross": store._m(gross), "flags": flags, "status": "flagged" if flags else "passed",
            "deductions": {k: store._m(v) for k, v in d.items()}, "tds_pct": store._m(tds) if tds is not None else None,
            "lines": [{**b, "quantity": rules.qty(b["quantity"]), "rate": store._m(b["rate"])} for b in bill_lines]}


@router.post("/work-orders/{wo_id}/bills/check")
async def check_bill(wo_id: uuid.UUID, body: BillIn, auth_context: AuthorizationContext = Depends(get_auth_context),
                     conn: AsyncConnection = Depends(get_db_conn)):
    """What a bill would be: passed or flagged (why), and retention / advance / TDS / net payable. Saves nothing."""
    _money(auth_context, "check a subcontractor's bill")
    return await _check(conn, auth_context, await _one(conn, auth_context, wo_id), body)


@router.post("/work-orders/{wo_id}/bills", status_code=201)
async def record_bill(wo_id: uuid.UUID, body: BillIn, auth_context: AuthorizationContext = Depends(get_auth_context),
                      conn: AsyncConnection = Depends(get_db_conn)):
    """A subcontractor's bill on a work order: an expense (unpaid) with the quantity per line, checked against the work
    measured and the agreed rates. Passed: payable now, after retention / advance / TDS. Flagged: waits for a person."""
    _money(auth_context, "record a subcontractor's bill")
    wo = await _one(conn, auth_context, wo_id, lock=True)
    if wo["status"] not in ("issued", "completed"):
        raise HTTPException(status_code=409, detail=f"{wo['ref']} is {wo['status']}: bills are recorded on an issued work order.")
    result = await _check(conn, auth_context, wo, body)
    org = auth_context.organization_id
    number = int((await conn.execute(text("SELECT COALESCE(MAX(number), 0) + 1 FROM work_order_bills WHERE work_order_id = :w"),
                                     {"w": wo_id})).scalar())
    when = body.bill_date or await _today(conn, org)
    expense_id = await _bill_expense(conn, auth_context, wo, number, Decimal(result["gross"]), when, body)
    bill_id = uuid.uuid4()
    await conn.execute(text(
        "INSERT INTO work_order_bills (id, organization_id, work_order_id, expense_id, number, their_bill_no, bill_date, gross, "
        "check_status, flags, tds_pct, submitted_by, source) VALUES (:id, :org, :wo, :e, :n, :no, :d, :g, :st, CAST(:f AS jsonb), "
        ":tds, :u, :src)"),
        {"id": bill_id, "org": org, "wo": wo_id, "e": expense_id, "n": number, "no": (body.their_bill_no or "").strip() or None,
         "d": when, "g": Decimal(result["gross"]), "st": result["status"], "f": json.dumps(result["flags"]),
         "tds": Decimal(result["tds_pct"]) if result["tds_pct"] else None, "u": auth_context.user_id,
         "src": body.source if body.source in ("web", "whatsapp") else "web"})
    for bl in result["lines"]:
        await conn.execute(text("INSERT INTO work_order_bill_lines (organization_id, bill_id, line_id, quantity, rate) "
                                "VALUES (:org, :b, :l, :q, :r)"), {"org": org, "b": bill_id, "l": bl["line_id"], "q": Decimal(bl["quantity"]), "r": Decimal(bl["rate"])})
    who = await _who(conn, auth_context)
    await store.log(conn, org, wo_id, "billed", f"{store.bill_ref(number)} ₹{result['gross']} "
                    + ("passed the check" if not result["flags"] else "flagged: " + "; ".join(f["words"] for f in result["flags"])),
                    auth_context.user_id, who)
    if not result["flags"]:
        await _settle(conn, auth_context, wo_id, bill_id, body)
    return {"bill": (await store.fetch_bills(conn, org, bill_id=bill_id))[0], "check": result,
            "work_order": _shown(auth_context, await _one(conn, auth_context, wo_id))}


async def _bill_expense(conn: AsyncConnection, auth: AuthorizationContext, wo: dict, number: int, gross: Decimal,
                        when: datetime.date, body: BillIn) -> uuid.UUID:
    from mesiri.application.expenses.commands import RecordExpenseCommand
    from mesiri.application.expenses.handlers import RecordExpenseHandler
    from mesiri.application.expenses.resolution import PostgresExpenseCategoryResolver
    from mesiri.application.vendors.resolution import PostgresVendorResolver
    from mesiri.infrastructure.postgres.repositories.expense_execution import (
        PostgresExpenseExecutionRepository,
    )
    from mesiri_contracts.application.results.execution_result import ExecutionStatus

    words = f"{wo['ref']} · {store.bill_ref(number)}" + (f" (their bill {body.their_bill_no.strip()})" if (body.their_bill_no or "").strip() else "")
    cmd = RecordExpenseCommand(
        idempotency_key=f"wo-bill:{uuid.uuid4()}", organization_id=str(auth.organization_id), project_id=wo["project_id"],
        site_id=wo["site_id"], vendor_id=wo["vendor_id"], category_text="Subcontract work", amount=gross,
        occurred_date=when, description=words + (f" — {body.notes.strip()}" if (body.notes or "").strip() else ""),
        media_object_key=body.media_object_key, source="web", created_by=str(auth.user_id))
    result = await RecordExpenseHandler(PostgresExpenseExecutionRepository(), resolver=PostgresExpenseCategoryResolver(),
                                        vendor_resolver=PostgresVendorResolver()).handle(conn, cmd)
    if result.status is ExecutionStatus.REJECTED or not result.material_row_id:
        raise HTTPException(status_code=422, detail=f"The bill could not be saved: {result.rejection_reasons}")
    return uuid.UUID(result.material_row_id)


async def _settle(conn: AsyncConnection, auth: AuthorizationContext, wo_id: uuid.UUID, bill_id: uuid.UUID,
                  body: BillIn | None = None) -> None:
    """A bill becomes payable: hold retention, recover the advance (the work order's advances, oldest first, no money
    moves) and deduct TDS (a payment from the TDS payable account). Net payable is what is left."""
    from mesiri.infrastructure.postgres.repositories.expenses import (
        PostgresExpensePaymentRepository,
    )

    org = auth.organization_id
    wo = await _one(conn, auth, wo_id)
    bill = (await store.fetch_bills(conn, org, bill_id=bill_id))[0]
    lines = [BillLineIn(line_id=uuid.UUID(x["line_id"]), quantity=Decimal(x["quantity"]), rate=Decimal(x["rate"])) for x in bill["lines"]]
    again = BillIn(lines=lines, amount=Decimal(bill["gross"]),
                   retention_pct=body.retention_pct if body else None, advance_recover=body.advance_recover if body else None,
                   tds_pct=Decimal(bill["tds_pct"]) if bill["tds_pct"] else (body.tds_pct if body else None))
    d = (await _check(conn, auth, wo, again, besides=bill_id))["deductions"]
    if bill["tds_pct"] is None and (await _settings(conn, org)).get("tds_enabled") is not True:
        d["tds"] = "0.00"
        d["net"] = store._m(Decimal(d["gross"]) - Decimal(d["retention"]) - Decimal(d["advance"]))
    repo = PostgresExpensePaymentRepository(conn)
    expense_id = uuid.UUID(bill["expense_id"])
    if Decimal(d["tds"]) > 0:
        acc = await store.tds_account(conn, org, auth.user_id)
        await repo.record_payment(organization_id=org, expense_id=expense_id, account_id=acc, amount=Decimal(d["tds"]),
                                  paid_date=datetime.date.fromisoformat(bill["bill_date"]), created_by=auth.user_id,
                                  payment_method="TDS 194C", reference_number=f"{bill['wo_ref']} {bill['ref']}")
    want, recovered = Decimal(d["advance"]), Decimal(0)
    if want > 0:
        advances = (await conn.execute(text(
            "SELECT id FROM expense_payments WHERE work_order_id = :w AND expense_id IS NULL AND status = 'confirmed' "
            "ORDER BY paid_date, created_at"), {"w": wo_id})).scalars().all()
        for adv in advances:
            left = await repo.advance_left(org, adv)
            part = min(left, want - recovered)
            if part > 0:
                await repo.apply_advance(organization_id=org, advance_id=adv, expense_id=expense_id, amount=part, created_by=auth.user_id)
                recovered += part
            if recovered >= want:
                break
    net = Decimal(d["gross"]) - Decimal(d["retention"]) - recovered - Decimal(d["tds"])
    await conn.execute(text(
        "UPDATE work_order_bills SET retention_amount = :r, advance_recovered = :a, tds_amount = :t, net_payable = :n, "
        "tds_pct = CASE WHEN CAST(:t AS numeric) > 0 THEN tds_pct ELSE NULL END WHERE id = :id"),
        {"r": Decimal(d["retention"]), "a": recovered, "t": Decimal(d["tds"]), "n": net, "id": bill_id})


class DecisionIn(BaseModel):
    reason: str = Field(min_length=2)


@router.post("/bills/{bill_id}/approve")
async def approve_bill(bill_id: uuid.UUID, body: DecisionIn, auth_context: AuthorizationContext = Depends(get_auth_context),
                       conn: AsyncConnection = Depends(get_db_conn)):
    """A flagged (or waiting) bill is approved with a reason: it becomes payable after its deductions."""
    return await _decide(conn, auth_context, bill_id, "approved", body.reason)


@router.post("/bills/{bill_id}/reject")
async def reject_bill(bill_id: uuid.UUID, body: DecisionIn, auth_context: AuthorizationContext = Depends(get_auth_context),
                      conn: AsyncConnection = Depends(get_db_conn)):
    """A bill turned down: its expense is taken back (nothing owed for it), the reason kept."""
    return await _decide(conn, auth_context, bill_id, "rejected", body.reason)


async def _decide(conn: AsyncConnection, auth: AuthorizationContext, bill_id: uuid.UUID, to: str, reason: str) -> dict:
    _money(auth, "approve or reject a subcontractor's bill")
    found = await store.fetch_bills(conn, auth.organization_id, bill_id=bill_id)
    if not found:
        raise HTTPException(status_code=404, detail="Bill not found")
    bill = found[0]
    await _one(conn, auth, uuid.UUID(bill["work_order_id"]))  # in scope
    if bill["check_status"] not in ("waiting", "flagged"):
        raise HTTPException(status_code=409, detail=f"{bill['ref']} is {bill['check_status']} already.")
    await conn.execute(text("UPDATE work_order_bills SET check_status = :s, decided_by = :u, decided_at = now(), "
                            "decision_reason = :r WHERE id = :id"), {"s": to, "u": auth.user_id, "r": reason.strip(), "id": bill_id})
    if to == "approved":
        await _settle(conn, auth, uuid.UUID(bill["work_order_id"]), bill_id)
    else:
        from mesiri.application.finance.reverse_commands import ReverseTransactionCommand
        from mesiri.application.finance.reverse_handler import ReverseTransactionHandler
        from mesiri.application.finance.reverse_resolution import PostgresReverseTargetResolver
        from mesiri.infrastructure.postgres.repositories.reverse_execution import (
            PostgresReverseExecutionRepository,
        )

        cmd = ReverseTransactionCommand(idempotency_key=f"wo-bill-reject:{bill_id}", organization_id=str(auth.organization_id),
                                        created_by=str(auth.user_id), created_by_role=auth.role, target_kind="expense",
                                        expense_id=bill["expense_id"])
        await ReverseTransactionHandler(repo=PostgresReverseExecutionRepository(), resolver=PostgresReverseTargetResolver()).handle(conn, cmd)
    await store.log(conn, auth.organization_id, bill["work_order_id"], f"bill_{to}", f"{bill['ref']} {to}: {reason.strip()}",
                    auth.user_id, await _who(conn, auth))
    return {"bill": (await store.fetch_bills(conn, auth.organization_id, bill_id=bill_id))[0],
            "work_order": _shown(auth, await _one(conn, auth, uuid.UUID(bill["work_order_id"])))}


class ReleaseIn(BaseModel):
    #: Left out: all retention held on the work order.
    amount: Decimal | None = Field(default=None, gt=0)
    note: str | None = None


@router.post("/work-orders/{wo_id}/retention/release")
async def release_retention(wo_id: uuid.UUID, body: ReleaseIn, auth_context: AuthorizationContext = Depends(get_auth_context),
                            conn: AsyncConnection = Depends(get_db_conn)):
    """Retention held becomes payable (the work is complete, or the defect period is over), oldest bills first."""
    _pays(auth_context, "release retention")
    wo = await _one(conn, auth_context, wo_id, lock=True)
    held = Decimal(wo["totals"]["retention_held"])
    amount = body.amount if body.amount is not None else held
    if held <= 0:
        raise HTTPException(status_code=409, detail="No retention is held on this work order.")
    if amount > held:
        raise HTTPException(status_code=422, detail=f"Only ₹{store._m(held)} is held.")
    left = amount
    for b in wo["bills"]:
        h = Decimal(b["retention_held"])
        if left <= 0 or h <= 0:
            continue
        part = min(h, left)
        await conn.execute(text("UPDATE work_order_bills SET retention_released = retention_released + :p WHERE id = :id"),
                           {"p": part, "id": b["id"]})
        left -= part
    note = (body.note or "").strip()
    await store.log(conn, auth_context.organization_id, wo_id, "retention_released", f"₹{store._m(amount)} of retention released"
                    + (f": {note}" if note else ""), auth_context.user_id, await _who(conn, auth_context))
    return _shown(auth_context, await _one(conn, auth_context, wo_id))


class AdvanceIn(BaseModel):
    account_id: uuid.UUID
    amount: Decimal = Field(gt=0)
    paid_date: datetime.date | None = None
    reference: str | None = None
    method: str | None = None


@router.post("/work-orders/{wo_id}/advance", status_code=201)
async def give_advance(wo_id: uuid.UUID, body: AdvanceIn, auth_context: AuthorizationContext = Depends(get_auth_context),
                       conn: AsyncConnection = Depends(get_db_conn)):
    """An advance to the subcontractor against this work order: money leaves the account now (the supplier ledger's
    on-account payment) and is recovered from the work order's bills."""
    from mesiri.infrastructure.postgres.repositories.expenses import (
        PostgresExpensePaymentRepository,
    )

    _pays(auth_context, "give an advance")
    wo = await _one(conn, auth_context, wo_id)
    if wo["status"] not in ("draft", "issued"):
        raise HTTPException(status_code=409, detail=f"{wo['ref']} is {wo['status']}.")
    acc = (await conn.execute(text("SELECT name, status FROM money_accounts WHERE id = :a AND organization_id = :org"),
                              {"a": body.account_id, "org": auth_context.organization_id})).mappings().first()
    if acc is None:
        raise HTTPException(status_code=404, detail="Account not found")
    if acc["status"] != "active":
        raise HTTPException(status_code=409, detail=f"{acc['name']} is closed.")
    p = await PostgresExpensePaymentRepository(conn).record_on_account(
        organization_id=auth_context.organization_id, vendor_id=uuid.UUID(wo["vendor_id"]), account_id=body.account_id,
        amount=body.amount.quantize(Decimal("0.01")), paid_date=body.paid_date or await _today(conn, auth_context.organization_id),
        created_by=auth_context.user_id, project_id=uuid.UUID(wo["project_id"]), payment_method=body.method,
        reference_number=(body.reference or "").strip() or None, description=f"Advance to {wo['vendor_name']} for {wo['ref']}")
    await conn.execute(text("UPDATE expense_payments SET work_order_id = :w WHERE id = :p"), {"w": wo_id, "p": p.id})
    await store.log(conn, auth_context.organization_id, wo_id, "advance", f"advance ₹{store._m(body.amount)} from {acc['name']}",
                    auth_context.user_id, await _who(conn, auth_context))
    return _shown(auth_context, await _one(conn, auth_context, wo_id))


# --- team, statement ------------------------------------------------------------------------------------------------


@router.get("/work-orders/{wo_id}/attendance")
async def team_lines(wo_id: uuid.UUID, auth_context: AuthorizationContext = Depends(get_auth_context),
                     conn: AsyncConnection = Depends(get_db_conn)):
    """Attendance lines at the work order's site (last 30 days) and whether they are this subcontractor's team."""
    wo = await _one(conn, auth_context, wo_id)
    p = {"org": auth_context.organization_id, "proj": wo["project_id"], "from": (await _today(conn, auth_context.organization_id)) - datetime.timedelta(days=30)}
    sql = ("SELECT l.id, l.trade, l.headcount, l.vendor_id, r.occurred_date, s.name AS site FROM labour_attendance_lines l "
           "JOIN labour_attendance_reports r ON r.id = l.report_id LEFT JOIN sites s ON s.id = r.site_id "
           "WHERE r.organization_id = :org AND r.project_id = :proj AND r.occurred_date >= :from")
    if wo["site_id"]:
        sql += " AND r.site_id = :s"
        p["s"] = wo["site_id"]
    rows = (await conn.execute(text(sql + " ORDER BY r.occurred_date DESC LIMIT 300"), p)).mappings().all()
    return [{"id": str(r["id"]), "date": r["occurred_date"].isoformat(), "trade": r["trade"], "headcount": r["headcount"],
             "site": r["site"], "theirs": str(r["vendor_id"]) == wo["vendor_id"] if r["vendor_id"] else False,
             "other_team": bool(r["vendor_id"]) and str(r["vendor_id"]) != wo["vendor_id"]} for r in rows]


class TeamIn(BaseModel):
    line_ids: list[uuid.UUID]
    theirs: bool = True


@router.post("/work-orders/{wo_id}/attendance")
async def mark_team(wo_id: uuid.UUID, body: TeamIn, auth_context: AuthorizationContext = Depends(get_auth_context),
                    conn: AsyncConnection = Depends(get_db_conn)):
    """These attendance lines were this subcontractor's team (or not): their man-days show on the work order."""
    wo = await _one(conn, auth_context, wo_id)
    await _may_record(conn, auth_context, wo)
    await conn.execute(text(
        "UPDATE labour_attendance_lines l SET vendor_id = :v FROM labour_attendance_reports r WHERE r.id = l.report_id "
        "AND r.organization_id = :org AND r.project_id = :p AND l.id = ANY(:ids)"),
        {"v": uuid.UUID(wo["vendor_id"]) if body.theirs else None, "org": auth_context.organization_id, "p": wo["project_id"],
         "ids": body.line_ids})
    return await store.team_days(conn, auth_context.organization_id, wo["vendor_id"], wo["project_id"], wo["site_id"])


@router.get("/vendors/{vendor_id}/statement")
async def statement(vendor_id: uuid.UUID, auth_context: AuthorizationContext = Depends(get_auth_context),
                    conn: AsyncConnection = Depends(get_db_conn)):
    """S5: a subcontractor's statement: each work order (agreed, measured, billed, approved, retention held, advance,
    paid, payable now) and their bills; what the subcontractor is sent, and what they see on WhatsApp (S6)."""
    _money(auth_context, "see a subcontractor's statement")
    return await statement_for(conn, auth_context.organization_id, vendor_id, _scope(auth_context))


async def statement_for(conn: AsyncConnection, org: uuid.UUID, vendor_id: uuid.UUID, scope: set | None) -> dict:
    vendor = (await conn.execute(text("SELECT id, name, phone, gstin FROM vendors WHERE id = :v AND organization_id = :org"),
                                 {"v": vendor_id, "org": org})).mappings().first()
    if vendor is None:
        raise HTTPException(status_code=404, detail="Subcontractor not found")
    wos = [w for w in await store.fetch(conn, org, vendor_id=vendor_id, project_ids=scope) if w["status"] != "cancelled"]
    keys = ("value", "measured_value", "billed", "approved", "paid", "retention_held", "advance_given", "advance_recovered",
            "advance_left", "payable_now")
    totals = {k: store._m(sum((Decimal(w["totals"][k]) for w in wos), Decimal(0))) for k in keys}
    tds = store._m(sum((Decimal(b["tds_amount"]) for w in wos for b in w["bills"] if b["check_status"] in store.PAYABLE), Decimal(0)))
    return {"vendor": {"id": str(vendor["id"]), "name": vendor["name"], "phone": vendor["phone"], "gstin": vendor["gstin"]},
            "as_of": (await _today(conn, org)).isoformat(), "totals": {**totals, "tds": tds},
            "work_orders": [{k: w[k] for k in ("id", "ref", "status", "title", "project_name", "site_name", "lines", "totals", "bills",
                                                "retention_pct", "start_date", "end_date", "completed_on")} for w in wos]}


@router.get("/bills/waiting")
async def bills_waiting(auth_context: AuthorizationContext = Depends(get_auth_context), conn: AsyncConnection = Depends(get_db_conn)):
    """Bills waiting for a person (flagged or sent by a subcontractor): what Today and the approvals list show."""
    if not may_view_expenses(auth_context.role):
        return []
    wos = await store.fetch(conn, auth_context.organization_id, project_ids=_scope(auth_context))
    return [{**b, "vendor_name": w["vendor_name"], "project_name": w["project_name"], "site_name": w["site_name"]}
            for w in wos for b in w["bills"] if b["check_status"] in ("waiting", "flagged")]


# --- status moves (last: its path would otherwise catch /advance, /bills, ...) -------------------------


class StatusIn(BaseModel):
    note: str | None = None
    completed_on: datetime.date | None = None


_MOVES = {"issue": (("draft",), "issued"), "complete": (("issued",), "completed"), "close": (("issued", "completed"), "closed"),
          "cancel": (("draft", "issued"), "cancelled"), "reopen": (("completed", "closed", "cancelled"), "issued")}


@router.post("/work-orders/{wo_id}/{move}")
async def move_work_order(wo_id: uuid.UUID, move: str, body: StatusIn | None = None,
                          auth_context: AuthorizationContext = Depends(get_auth_context),
                          conn: AsyncConnection = Depends(get_db_conn)):
    """issue (draft -> issued), complete (work done; the retention clock starts), close, cancel, reopen."""
    if move not in _MOVES:
        raise HTTPException(status_code=404, detail="Not found")
    _office(auth_context)
    wo = await _one(conn, auth_context, wo_id, lock=True)
    allowed, to = _MOVES[move]
    if wo["status"] not in allowed:
        raise HTTPException(status_code=409, detail=f"{wo['ref']} is {wo['status']}.")
    if move == "cancel" and any(Decimal(x["measured"]) > 0 or Decimal(x["billed"]) > 0 for x in wo["lines"]):
        raise HTTPException(status_code=409, detail=f"{wo['ref']} has work measured or billed: complete or close it instead.")
    note = ((body.note if body else None) or "").strip() or None
    when = (body.completed_on if body else None) or await _today(conn, auth_context.organization_id)
    await conn.execute(text(
        "UPDATE work_orders SET status = :to, status_note = COALESCE(:note, status_note), updated_at = now(), "
        "issued_at = CASE WHEN :to = 'issued' AND issued_at IS NULL THEN now() ELSE issued_at END, "
        "completed_on = CASE WHEN :to = 'completed' THEN CAST(:when AS date) WHEN :to = 'issued' THEN NULL ELSE completed_on END "
        "WHERE id = :id"), {"to": to, "note": note, "when": when, "id": wo_id})
    words = {"issue": "issued", "complete": f"work completed on {when.isoformat()}", "close": "closed",
             "cancel": "cancelled", "reopen": "reopened"}[move]
    await store.log(conn, auth_context.organization_id, wo_id, move, words + (f": {note}" if note else ""),
                    auth_context.user_id, await _who(conn, auth_context))
    return _shown(auth_context, await _one(conn, auth_context, wo_id))
