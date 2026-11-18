"""Variations (NXT-04, CC-24): extra or changed work the client asked for, priced, sent, approved, then billed.

A variation is asked for (``draft``), sent to the client with its price (``sent``), and decided by the client
(``approved`` / ``rejected``); ``cancelled`` drops it before then. Each is numbered per project: VO-01, VO-02 ...

On approval the BOQ changes through its own repository, so everything that reads the BOQ follows (the budget, cost
control, the material plan, the site's work and the RA bills):

- ``new`` (work not in the BOQ): a line in the project's "Variations" section, code VO-xx, at the client rate;
- ``more`` (more of a BOQ line): the line's planned quantity goes up by the variation's, as a revision whose reason
  names the VO (the BOQ's own history keeps the old quantity).

The site's work on a VO line is then measured and billed on RA bills like any line (``bills.unbilled_lines``): no
second way to bill. A ``more`` one is billed with its line, so its own done / billed is not split out.

Amounts: quantity × client rate (to the paisa); the margin, when we priced our cost, is amount − cost estimate.

Who: the people who see client bills (``may_manage_money``: owner, admin, finance), the same as RA bills; a project
outside the person's scope is not theirs.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.authorization.roles import may_manage_money
from mesiri.domains.projects.router import get_auth_context
from mesiri.infrastructure.postgres.dependency import get_db_conn

router = APIRouter(tags=["billing"])

PAISA = Decimal("0.01")
SECTION = "Variations"
OPEN = ("draft", "sent")


# -- pure ---------------------------------------------------------------------------------------------------------


def ref(number: int) -> str:
    return f"VO-{number:02d}"


def amount(quantity: Any, rate: Any) -> Decimal:
    return (Decimal(quantity) * Decimal(rate)).quantize(PAISA, rounding=ROUND_HALF_UP)


def margin(value: Decimal, cost: Any) -> tuple[Decimal | None, Decimal | None]:
    """(margin, margin %) from the amount and our cost estimate; (None, None) when we did not price our cost."""
    if cost is None:
        return None, None
    m = value - Decimal(cost)
    return m.quantize(PAISA), ((m / value * 100).quantize(Decimal("0.1")) if value else None)


def summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    """The page's figures: counts by state, and money asked, approved, waiting on the client and billed."""
    def total(states: tuple[str, ...], key: str = "amount") -> Decimal:
        return sum((Decimal(i[key] or 0) for i in items if i["status"] in states), Decimal(0)).quantize(PAISA)

    approved = [i for i in items if i["status"] == "approved"]
    return {
        "counts": {s: sum(1 for i in items if i["status"] == s) for s in ("draft", "sent", "approved", "rejected", "cancelled")},
        "waiting": total(("sent",)),
        "draft": total(("draft",)),
        "approved": total(("approved",)),
        "rejected": total(("rejected",)),
        "billed": total(("approved",), "billed_amount"),
        "days_added": sum((i["days_added"] or 0) for i in approved),
        "not_priced": sum(1 for i in items if i["status"] in OPEN and i["cost_estimate"] is None),
    }


# -- store --------------------------------------------------------------------------------------------------------

_SELECT = (
    "SELECT v.*, p.name AS project_name, s.name AS site_name, u.full_name AS created_by_name, "
    "li.boq_code AS line_code, li.work_type AS line_work "
    "FROM variations v JOIN projects p ON p.id = v.project_id LEFT JOIN sites s ON s.id = v.site_id "
    "LEFT JOIN users u ON u.id = v.created_by LEFT JOIN work_package_planned_items li ON li.id = v.line_id "
    "WHERE v.organization_id = :org"
)


async def _rows(conn: AsyncConnection, org: uuid.UUID, project_ids: set | None, variation_id: Any = None) -> list[dict]:
    sql, params = _SELECT, {"org": org}
    if project_ids is not None:
        sql += " AND v.project_id = ANY(:ps)"
        params["ps"] = list(project_ids)
    if variation_id is not None:
        sql += " AND v.id = :id"
        params["id"] = variation_id
    return [dict(r) for r in (await conn.execute(text(sql + " ORDER BY v.asked_on DESC, v.number DESC"), params)).mappings()]


async def _progress(conn: AsyncConnection, org: uuid.UUID, rows: list[dict]) -> dict[Any, dict[str, Decimal]]:
    """For each approved ``new`` variation: the work measured on its BOQ line and what RA bills took of it."""
    from mesiri.domains.billing.bills import previous_by_line
    from mesiri.domains.progress.boq_router import done_by_line
    from mesiri.infrastructure.postgres.repositories.boq import PostgresBoqRepository

    out: dict[Any, dict[str, Decimal]] = {}
    repo = PostgresBoqRepository(conn)
    for project_id in {r["project_id"] for r in rows if r["kind"] == "new" and r["planned_item_id"]}:
        current = await repo.current_revision_of(org, project_id)
        lines = await repo.list_lines(org, project_id)
        done = await done_by_line(repo, org, project_id, lines)
        billed = await previous_by_line(conn, org, project_id)
        for r in rows:
            if r["project_id"] != project_id or r["kind"] != "new" or not r["planned_item_id"]:
                continue
            line = current.get(r["planned_item_id"], r["planned_item_id"])
            out[r["id"]] = {"done": done.get(line, {}).get("done", Decimal(0)), "billed": billed.get(line, Decimal(0)),
                            "line": line}
    return out


def _out_row(r: dict, today: datetime.date, progress: dict | None) -> dict[str, Any]:
    value = amount(r["quantity"], r["client_rate"])
    m, pct = margin(value, r["cost_estimate"])
    billed_q = progress["billed"] if progress else None
    return {
        "id": r["id"], "ref": ref(r["number"]), "number": r["number"], "project_id": r["project_id"],
        "project": r["project_name"], "site_id": r["site_id"], "site": r["site_name"], "kind": r["kind"],
        "title": r["title"], "description": r["description"],
        "line": {"id": r["line_id"], "code": r["line_code"], "work": r["line_work"]} if r["line_id"] else None,
        "unit": r["unit"], "quantity": r["quantity"], "client_rate": r["client_rate"], "amount": value,
        "cost_estimate": r["cost_estimate"], "margin": m, "margin_pct": pct, "days_added": r["days_added"],
        "asked_by": r["asked_by"], "asked_on": r["asked_on"], "status": r["status"], "sent_on": r["sent_on"],
        "decided_on": r["decided_on"], "decided_by": r["decided_by"], "decision_note": r["decision_note"],
        # How long the client has had it (sent) or it has waited to be sent (draft).
        "waiting_days": (today - (r["sent_on"] or r["asked_on"])).days if r["status"] in OPEN else None,
        "planned_item_id": (progress or {}).get("line") or r["planned_item_id"],
        "done": progress["done"] if progress else None,
        "billed": billed_q,
        "billed_amount": amount(billed_q, r["client_rate"]) if billed_q is not None else None,
        "created_by_name": r["created_by_name"], "created_at": r["created_at"],
    }


async def _section(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID, user_id: uuid.UUID) -> uuid.UUID:
    from mesiri.infrastructure.postgres.repositories.boq import PostgresBoqRepository

    found = (await conn.execute(text(
        "SELECT id FROM work_packages WHERE organization_id = :org AND project_id = :p AND lower(name) = lower(:n) "
        "ORDER BY created_at LIMIT 1"), {"org": org, "p": project_id, "n": SECTION})).scalar()
    if found:
        return found
    return await PostgresBoqRepository(conn).create_section(org, project_id, SECTION, None, None, user_id)


async def _apply_to_boq(conn: AsyncConnection, org: uuid.UUID, v: dict, user_id: uuid.UUID) -> uuid.UUID:
    """The approved variation into the BOQ (its own repository): a new VO line, or more of the line."""
    from mesiri.domains.progress.boq_router import _unit_id
    from mesiri.infrastructure.postgres.repositories.boq import PostgresBoqRepository

    repo = PostgresBoqRepository(conn)
    code = ref(v["number"])
    if v["kind"] == "more":
        current = (await repo.current_revision_of(org, v["project_id"])).get(v["line_id"], v["line_id"])
        line = await repo.get_line(org, v["project_id"], current)
        if line is None:
            raise HTTPException(status_code=409, detail="Its BOQ line is no longer in the BOQ")
        return await repo.revise_quantity(org, line, Decimal(line["planned_quantity"]) + Decimal(v["quantity"]),
                                          f"{code} approved by the client", user_id)
    section = await _section(conn, org, v["project_id"], user_id)
    unit_id = await _unit_id(conn, v["unit"])
    work = v["title"]
    if await repo.current_line_with(section, work, unit_id):
        work = f"{work} ({code})"
    return await repo.create_line(org, section, {
        "work_type": work, "unit_id": unit_id, "planned_quantity": Decimal(v["quantity"]), "boq_code": code,
        "client_rate": Decimal(v["client_rate"])}, user_id)


# -- API ----------------------------------------------------------------------------------------------------------


def _out(value: Any) -> Any:
    if isinstance(value, datetime.date | datetime.datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID | Decimal):
        return str(value)
    if isinstance(value, dict):
        return {k: _out(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_out(v) for v in value]
    return value


def _clean(v: str | None) -> str | None:
    v = (v or "").strip()
    return v or None


def _require(auth: AuthorizationContext, project_id: uuid.UUID | None = None) -> None:
    if not may_manage_money(auth.role):
        raise HTTPException(status_code=403, detail="Variations are for the owner, an admin or finance")
    if project_id is not None and not auth.project_scope.grants_all_org_projects \
            and project_id not in auth.project_scope.project_ids:
        raise HTTPException(status_code=403, detail="Not authorized for this project")


def _scope(auth: AuthorizationContext, project_id: uuid.UUID | None) -> set | None:
    if project_id is not None:
        return {project_id}
    return None if auth.project_scope.grants_all_org_projects else set(auth.project_scope.project_ids)


async def _today(conn: AsyncConnection, org: uuid.UUID) -> datetime.date:
    from mesiri.application.dpr.project_day import company_today

    return await company_today(conn, org)


async def _one(conn: AsyncConnection, auth: AuthorizationContext, variation_id: uuid.UUID) -> dict:
    _require(auth)
    rows = await _rows(conn, auth.organization_id, None, variation_id)
    if not rows:
        raise HTTPException(status_code=404, detail="Variation not found")
    _require(auth, rows[0]["project_id"])
    return rows[0]


async def _shown(conn: AsyncConnection, auth: AuthorizationContext, variation_id: uuid.UUID) -> dict[str, Any]:
    row = await _one(conn, auth, variation_id)
    today = await _today(conn, auth.organization_id)
    return _out(_out_row(row, today, (await _progress(conn, auth.organization_id, [row])).get(row["id"])))


_Qty = Field(gt=0, max_digits=14, decimal_places=3)
_Money = Field(ge=0, max_digits=14, decimal_places=2)


class VariationIn(BaseModel):
    kind: Literal["new", "more"] = "new"
    title: str = Field(min_length=1, max_length=300, description="What the client asked for: 'Extra balcony, 1st floor'")
    description: str | None = Field(default=None, max_length=2000)
    line_id: uuid.UUID | None = Field(default=None, description="kind 'more': the BOQ line it adds to")
    site_id: uuid.UUID | None = None
    unit: str | None = Field(default=None, max_length=40, description="kind 'new'; 'more' takes its line's")
    quantity: Decimal = _Qty
    client_rate: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2,
                                        description="kind 'more' defaults to its line's client rate")
    cost_estimate: Decimal | None = Field(default=None, ge=0, max_digits=16, decimal_places=2)
    days_added: int | None = Field(default=None, ge=0, le=1000)
    asked_by: str | None = Field(default=None, max_length=120)
    asked_on: datetime.date | None = None
    send: bool = Field(default=False, description="Sent to the client at once")

    _clean_text = field_validator("title", "description", "unit", "asked_by")(_clean)


class VariationPatch(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    description: str | None = Field(default=None, max_length=2000)
    site_id: uuid.UUID | None = None
    unit: str | None = Field(default=None, max_length=40)
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=3)
    client_rate: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    cost_estimate: Decimal | None = Field(default=None, ge=0, max_digits=16, decimal_places=2)
    days_added: int | None = Field(default=None, ge=0, le=1000)
    asked_by: str | None = Field(default=None, max_length=120)
    asked_on: datetime.date | None = None

    _clean_text = field_validator("title", "description", "unit", "asked_by")(_clean)


class Decision(BaseModel):
    decided_by: str | None = Field(default=None, max_length=120, description="Who at the client said yes or no")
    decided_on: datetime.date | None = None
    note: str | None = Field(default=None, max_length=1000)

    _clean_text = field_validator("decided_by", "note")(_clean)


@router.get("/billing/variations")
async def list_variations(project_id: uuid.UUID | None = None, auth: AuthorizationContext = Depends(get_auth_context),
                          conn: AsyncConnection = Depends(get_db_conn)):
    """Every variation the person may see (newest first) with its money, state and, once approved, its BOQ line's
    work measured and billed; and the figures for the page."""
    _require(auth, project_id)
    org = auth.organization_id
    rows = await _rows(conn, org, _scope(auth, project_id))
    today = await _today(conn, org)
    progress = await _progress(conn, org, rows)
    items = [_out_row(r, today, progress.get(r["id"])) for r in rows]
    return _out({"date": today, "items": items, "summary": summary(items)})


@router.get("/billing/variations/{variation_id}")
async def get_variation(variation_id: uuid.UUID, auth: AuthorizationContext = Depends(get_auth_context),
                        conn: AsyncConnection = Depends(get_db_conn)):
    return await _shown(conn, auth, variation_id)


@router.post("/projects/{project_id}/variations", status_code=201)
async def create_variation(project_id: uuid.UUID, body: VariationIn, auth: AuthorizationContext = Depends(get_auth_context),
                           conn: AsyncConnection = Depends(get_db_conn)):
    from mesiri.infrastructure.postgres.repositories.boq import PostgresBoqRepository

    _require(auth, project_id)
    org = auth.organization_id
    repo = PostgresBoqRepository(conn)
    if not await repo.project_exists(org, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    if body.site_id is not None and not await repo.site_in_project(project_id, body.site_id):
        raise HTTPException(status_code=422, detail="site_id is not a site of this project")
    unit, rate = body.unit, body.client_rate
    if body.kind == "more":
        if body.line_id is None:
            raise HTTPException(status_code=422, detail="Pick the BOQ line it adds to")
        line = await repo.get_line(org, project_id, body.line_id)
        if line is None:
            raise HTTPException(status_code=422, detail="That BOQ line is not a current line of this project")
        unit = line["unit"]
        rate = rate if rate is not None else line["client_rate"]
    else:
        if not unit:
            raise HTTPException(status_code=422, detail="Say the unit (cum, sqm, nos ...)")
        from mesiri.domains.progress.boq_router import _unit_id

        await _unit_id(conn, unit)  # a unit Mesiri knows, or a 422 now rather than at approval
    if rate is None:
        raise HTTPException(status_code=422, detail="Give the rate the client is asked to pay")
    today = await _today(conn, org)
    number = (await conn.execute(text("SELECT COALESCE(MAX(number), 0) + 1 FROM variations WHERE project_id = :p"),
                                 {"p": project_id})).scalar_one()
    new_id = (await conn.execute(text(
        "INSERT INTO variations (organization_id, project_id, site_id, number, kind, title, description, line_id, unit, "
        "quantity, client_rate, cost_estimate, days_added, asked_by, asked_on, status, sent_on, created_by) VALUES "
        "(:org, :p, :site, :n, :kind, :title, :desc, :line, :unit, :q, :rate, :cost, :days, :by, :on, :status, :sent, "
        ":me) RETURNING id"),
        {"org": org, "p": project_id, "site": body.site_id, "n": number, "kind": body.kind, "title": body.title,
         "desc": body.description, "line": body.line_id if body.kind == "more" else None, "unit": unit,
         "q": body.quantity, "rate": rate, "cost": body.cost_estimate, "days": body.days_added, "by": body.asked_by,
         "on": body.asked_on or today, "status": "sent" if body.send else "draft", "sent": today if body.send else None,
         "me": auth.user_id})).scalar_one()
    return await _shown(conn, auth, new_id)


@router.patch("/billing/variations/{variation_id}")
async def update_variation(variation_id: uuid.UUID, body: VariationPatch,
                           auth: AuthorizationContext = Depends(get_auth_context),
                           conn: AsyncConnection = Depends(get_db_conn)):
    v = await _one(conn, auth, variation_id)
    if v["status"] not in OPEN:
        raise HTTPException(status_code=409, detail="Only a variation not decided yet can change")
    changes = body.model_dump(exclude_unset=True)
    for required in ("title", "quantity", "client_rate"):
        if required in changes and changes[required] is None:
            raise HTTPException(status_code=422, detail=f"{required} can't be empty")
    if "unit" in changes:
        if v["kind"] == "more":
            raise HTTPException(status_code=422, detail="It takes its BOQ line's unit")
        from mesiri.domains.progress.boq_router import _unit_id

        await _unit_id(conn, changes["unit"] or "")
    if changes:
        sets = ", ".join(f"{k} = :{k}" for k in changes)
        await conn.execute(text(f"UPDATE variations SET {sets}, updated_at = now() WHERE id = :id"),  # noqa: S608
                           {**changes, "id": variation_id})
    return await _shown(conn, auth, variation_id)


@router.post("/billing/variations/{variation_id}/send")
async def send_variation(variation_id: uuid.UUID, auth: AuthorizationContext = Depends(get_auth_context),
                         conn: AsyncConnection = Depends(get_db_conn)):
    v = await _one(conn, auth, variation_id)
    if v["status"] != "draft":
        raise HTTPException(status_code=409, detail="Only a draft is sent")
    await conn.execute(text("UPDATE variations SET status = 'sent', sent_on = :d, updated_at = now() WHERE id = :id"),
                       {"d": await _today(conn, auth.organization_id), "id": variation_id})
    return await _shown(conn, auth, variation_id)


@router.post("/billing/variations/{variation_id}/approve")
async def approve_variation(variation_id: uuid.UUID, body: Decision,
                            auth: AuthorizationContext = Depends(get_auth_context),
                            conn: AsyncConnection = Depends(get_db_conn)):
    """The client said yes: the BOQ gets the work (a VO line, or more of the line), so it is measured and billed."""
    v = await _one(conn, auth, variation_id)
    if v["status"] not in OPEN:
        raise HTTPException(status_code=409, detail="It is already decided")
    line = await _apply_to_boq(conn, auth.organization_id, v, auth.user_id)
    today = await _today(conn, auth.organization_id)
    await conn.execute(text(
        "UPDATE variations SET status = 'approved', decided_on = :on, decided_by = :by, decision_note = :note, "
        "sent_on = COALESCE(sent_on, :on), planned_item_id = :line, updated_at = now() WHERE id = :id"),
        {"on": body.decided_on or today, "by": body.decided_by, "note": body.note, "line": line, "id": variation_id})
    return await _shown(conn, auth, variation_id)


@router.post("/billing/variations/{variation_id}/reject")
async def reject_variation(variation_id: uuid.UUID, body: Decision, auth: AuthorizationContext = Depends(get_auth_context),
                           conn: AsyncConnection = Depends(get_db_conn)):
    v = await _one(conn, auth, variation_id)
    if v["status"] not in OPEN:
        raise HTTPException(status_code=409, detail="It is already decided")
    today = await _today(conn, auth.organization_id)
    await conn.execute(text(
        "UPDATE variations SET status = 'rejected', decided_on = :on, decided_by = :by, decision_note = :note, "
        "updated_at = now() WHERE id = :id"),
        {"on": body.decided_on or today, "by": body.decided_by, "note": body.note, "id": variation_id})
    return await _shown(conn, auth, variation_id)


@router.post("/billing/variations/{variation_id}/cancel")
async def cancel_variation(variation_id: uuid.UUID, auth: AuthorizationContext = Depends(get_auth_context),
                           conn: AsyncConnection = Depends(get_db_conn)):
    v = await _one(conn, auth, variation_id)
    if v["status"] not in OPEN:
        raise HTTPException(status_code=409, detail="A decided variation stays; its BOQ line can be changed on the BOQ")
    await conn.execute(text("UPDATE variations SET status = 'cancelled', updated_at = now() WHERE id = :id"),
                       {"id": variation_id})
    return await _shown(conn, auth, variation_id)


@router.delete("/billing/variations/{variation_id}", status_code=204)
async def delete_variation(variation_id: uuid.UUID, auth: AuthorizationContext = Depends(get_auth_context),
                           conn: AsyncConnection = Depends(get_db_conn)):
    v = await _one(conn, auth, variation_id)
    if v["status"] != "draft":
        raise HTTPException(status_code=409, detail="Only a draft can be removed; cancel a sent one")
    await conn.execute(text("DELETE FROM variations WHERE id = :id"), {"id": variation_id})
    return Response(status_code=204)
