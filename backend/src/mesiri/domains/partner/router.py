"""The subcontractor's own API (NXT-16, option B; approved by Alan 8 Nov 2026). Plan: subcontractors-plan.md S6.

Deny by default:
- a contact's token is signed with its own key (``PARTNER_KEY``), so every staff route -- each of which decodes with
  the staff key -- rejects it as an invalid token, without any change to them;
- only these ``/partner`` routes accept it, each scoped to the contact's subcontractor and company, and only while
  the contact and the subcontractor are active and the company has ``partner_access`` on (Finance settings);
- answers are built here from whitelisted fields: their work orders (lines with agreed / done / billed and rates), their
  bills and payments, their statement. Never the company's other suppliers, budgets, client rates, margins or staff.
- what they send never takes effect by itself: a bill waits for the company's check (``check_status = waiting``), a
  report of work done waits for the site engineer (a ``proposed`` measurement);
- every request is written to ``partner_audit``.
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.domains.identity.auth_service import ALGORITHM, SECRET_KEY
from mesiri.domains.subcontracts import rules, store
from mesiri.infrastructure.postgres.dependency import get_db_conn
from mesiri.infrastructure.postgres.tenant import apply_tenant, bind_tenant

router = APIRouter(prefix="/partner", tags=["partner"])

#: A different key from staff tokens: a partner token is not a staff token anywhere.
PARTNER_KEY = f"{SECRET_KEY}:partner-v1"
KIND = "vendor_contact"


def partner_token(contact_id: Any, organization_id: Any, vendor_id: Any, minutes: int = 10) -> str:
    now = datetime.datetime.now(tz=datetime.UTC)
    return jwt.encode({"sub": str(contact_id), "org": str(organization_id), "vendor": str(vendor_id), "kind": KIND,
                       "exp": now + datetime.timedelta(minutes=minutes)}, PARTNER_KEY, algorithm=ALGORITHM)


@dataclass(frozen=True)
class Partner:
    contact_id: uuid.UUID
    organization_id: uuid.UUID
    vendor_id: uuid.UUID
    name: str
    vendor_name: str
    company_name: str


async def contact_by_phone(conn: AsyncConnection, phone: str) -> dict | None:
    """The active contact with this WhatsApp number whose company lets subcontractors in (staff numbers are resolved
    before this is ever asked). None otherwise."""
    digits = "".join(ch for ch in phone if ch.isdigit())
    if len(digits) < 6:
        return None
    rows = (await conn.execute(text(
        "SELECT c.id, c.organization_id, c.vendor_id, c.name, c.language, v.name AS vendor_name, o.name AS company_name, "
        "s.value AS settings FROM vendor_contacts c JOIN vendors v ON v.id = c.vendor_id "
        "JOIN organizations o ON o.id = c.organization_id "
        "LEFT JOIN organization_settings s ON s.organization_id = c.organization_id AND s.key = 'finance_settings' "
        "WHERE c.status = 'active' AND v.status = 'active' AND right(regexp_replace(c.phone, '\\D', '', 'g'), 10) = right(:d, 10)"),
        {"d": digits})).mappings().all()
    open_ = [dict(r) for r in rows if isinstance(r["settings"], dict) and r["settings"].get("partner_access")]
    return open_[0] if len(open_) == 1 else None


async def get_partner(request: Request, authorization: str | None = Header(None),
                      conn: AsyncConnection = Depends(get_db_conn)) -> Partner:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    try:
        claims = jwt.decode(authorization[7:], PARTNER_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc
    if claims.get("kind") != KIND:
        raise HTTPException(status_code=401, detail="Invalid token")
    org = uuid.UUID(claims["org"])
    bind_tenant(org)
    await apply_tenant(conn)
    row = (await conn.execute(text(
        "SELECT c.id, c.name, c.vendor_id, v.name AS vendor_name, o.name AS company_name, s.value AS settings "
        "FROM vendor_contacts c JOIN vendors v ON v.id = c.vendor_id JOIN organizations o ON o.id = c.organization_id "
        "LEFT JOIN organization_settings s ON s.organization_id = c.organization_id AND s.key = 'finance_settings' "
        "WHERE c.id = :c AND c.organization_id = :org AND c.vendor_id = :v AND c.status = 'active' AND v.status = 'active'"),
        {"c": uuid.UUID(claims["sub"]), "org": org, "v": uuid.UUID(claims["vendor"])})).mappings().first()
    if row is None or not (isinstance(row["settings"], dict) and row["settings"].get("partner_access")):
        raise HTTPException(status_code=403, detail="Access for subcontractors is off.")
    await conn.execute(text("INSERT INTO partner_audit (organization_id, contact_id, method, path) VALUES (:org, :c, :m, :p)"),
                       {"org": org, "c": row["id"], "m": request.method, "p": request.url.path[:300]})
    await conn.execute(text("UPDATE vendor_contacts SET last_seen_at = now() WHERE id = :c"), {"c": row["id"]})
    return Partner(contact_id=row["id"], organization_id=org, vendor_id=row["vendor_id"], name=row["name"],
                   vendor_name=row["vendor_name"], company_name=row["company_name"])


# --- what they may see (whitelisted fields only) ------------------------------------------------------------------

_LINE = ("id", "description", "unit", "quantity", "rate", "amount", "measured", "proposed", "billed", "billed_amount", "remaining")
_BILL = ("id", "ref", "their_bill_no", "bill_date", "gross", "check_status", "retention_amount", "retention_released",
         "advance_recovered", "tds_amount", "net_payable", "paid_cash", "payable_now")
_TOTALS = ("value", "measured_value", "billed", "approved", "paid", "retention_held", "advance_given", "advance_left", "payable_now",
           "progress_pct")


def _wo_out(w: dict) -> dict:
    return {"id": w["id"], "ref": w["ref"], "status": w["status"], "name": w["title"], "project": w["project_name"],
            "site": w["site_name"], "start_date": w["start_date"], "end_date": w["end_date"], "retention_pct": w["retention_pct"],
            "lines": [{k: x.get(k) for k in _LINE} for x in w["lines"]],
            "bills": [{**{k: b[k] for k in _BILL}, "why": [f["words"] for f in b["flags"]] if b["check_status"] in ("flagged", "rejected") else [],
                       "decision_reason": b["decision_reason"]} for b in w["bills"]],
            "totals": {k: w["totals"].get(k) for k in _TOTALS}}


async def _theirs(conn: AsyncConnection, p: Partner) -> list[dict]:
    return [w for w in await store.fetch(conn, p.organization_id, vendor_id=p.vendor_id) if w["status"] in ("issued", "completed", "closed")]


@router.get("/me")
async def me(p: Partner = Depends(get_partner)):
    return {"name": p.name, "subcontractor": p.vendor_name, "company": p.company_name}


@router.get("/work-orders")
async def work_orders(p: Partner = Depends(get_partner), conn: AsyncConnection = Depends(get_db_conn)):
    """Their work orders with the company: what was agreed, done, billed and paid, and their bills' status."""
    return [_wo_out(w) for w in await _theirs(conn, p)]


@router.get("/statement")
async def statement(p: Partner = Depends(get_partner), conn: AsyncConnection = Depends(get_db_conn)):
    """What is pending for them: payable now, retention held, advance still to recover, bills waiting for a check."""
    wos = await _theirs(conn, p)
    keys = ("value", "billed", "approved", "paid", "retention_held", "advance_left", "payable_now")
    totals = {k: store._m(sum((Decimal(w["totals"][k]) for w in wos), Decimal(0))) for k in keys}
    waiting = [{"ref": b["ref"], "work_order": w["ref"], "gross": b["gross"], "status": b["check_status"]}
               for w in wos for b in w["bills"] if b["check_status"] in ("waiting", "flagged")]
    return {"subcontractor": p.vendor_name, "company": p.company_name, "totals": totals, "waiting_for_check": waiting,
            "work_orders": [{"ref": w["ref"], "name": w["title"], "site": w["site_name"] or w["project_name"],
                             "status": w["status"], "progress_pct": w["totals"]["progress_pct"],
                             "payable_now": w["totals"]["payable_now"]} for w in wos]}


async def _their_wo(conn: AsyncConnection, p: Partner, wo_id: uuid.UUID) -> dict:
    found = await store.fetch(conn, p.organization_id, vendor_id=p.vendor_id, wo_id=wo_id)
    if not found or found[0]["status"] not in ("issued", "completed"):
        raise HTTPException(status_code=404, detail="Work order not found")
    return found[0]


async def _tell_office(conn: AsyncConnection, p: Partner, wo: dict, message: str, subject: str) -> None:
    """The project's office (owner / admin / PM in the project) hears it, held for their next message when needed."""
    from mesiri.infrastructure.postgres.repositories.notifications import (
        PostgresNotificationRepository,
    )

    people = (await conn.execute(text(
        "SELECT DISTINCT u.id FROM users u LEFT JOIN project_members m ON m.user_id = u.id AND m.project_id = :p "
        "WHERE u.organization_id = :org AND u.status = 'active' AND (upper(u.role) IN ('OWNER', 'ADMIN', 'FINANCE') "
        "OR (upper(u.role) = 'PROJECT_MANAGER' AND m.user_id IS NOT NULL) OR u.id = :creator)"),
        {"p": wo["project_id"], "org": p.organization_id, "creator": await _creator(conn, wo)})).scalars().all()
    repo = PostgresNotificationRepository(conn)
    for uid in people:
        async with conn.begin_nested():
            await repo.claim(organization_id=p.organization_id, rule_key="partner_sent", subject_id=f"{subject}:{uid}",
                             occurred_on=datetime.date.today(), recipient_user_id=uid, project_id=uuid.UUID(wo["project_id"]),
                             site_id=uuid.UUID(wo["site_id"]) if wo["site_id"] else None,
                             payload={"message": message, "hold_until_window": True, "hold_days": 3})


async def _creator(conn: AsyncConnection, wo: dict) -> uuid.UUID | None:
    return (await conn.execute(text("SELECT created_by FROM work_orders WHERE id = :w"), {"w": wo["id"]})).scalar()


class WorkDoneIn(BaseModel):
    work_order_id: uuid.UUID
    line_id: uuid.UUID
    quantity: Decimal = Field(gt=0)
    done_on: datetime.date | None = None
    notes: str | None = None


@router.post("/work-done", status_code=201)
async def report_work(body: WorkDoneIn, p: Partner = Depends(get_partner), conn: AsyncConnection = Depends(get_db_conn)):
    """Work they say is done: waits for the site engineer's confirmation before it counts."""
    wo = await _their_wo(conn, p, body.work_order_id)
    line = next((x for x in wo["lines"] if x["id"] == str(body.line_id)), None)
    if line is None:
        raise HTTPException(status_code=404, detail="Line not found")
    when = body.done_on or datetime.date.today()
    await conn.execute(text(
        "INSERT INTO work_order_measurements (organization_id, work_order_id, line_id, measured_on, quantity, notes, status, "
        "source, recorded_by_name, reported_by_contact) VALUES (:org, :wo, :l, :d, :q, :n, 'proposed', 'partner', :who, :c)"),
        {"org": p.organization_id, "wo": body.work_order_id, "l": body.line_id, "d": when, "q": body.quantity,
         "n": (body.notes or "").strip() or None, "who": f"{p.name} ({p.vendor_name})", "c": p.contact_id})
    words = f"{rules.qty(body.quantity)} {line['unit']} {line['description']} on {when.isoformat()}"
    await store.log(conn, p.organization_id, body.work_order_id, "reported", f"{p.vendor_name} reported {words}", None, p.name)
    await _tell_office(conn, p, wo, f"📏 {p.vendor_name} ({p.name}) reports {words} on {wo['ref']}: confirm it on the work order.",
                       f"work:{wo['id']}:{body.line_id}:{when.isoformat()}")
    return {"status": "waiting for the site engineer", "work_order": wo["ref"], "reported": words}


class BillLine(BaseModel):
    line_id: uuid.UUID
    quantity: Decimal = Field(gt=0)
    rate: Decimal | None = Field(default=None, ge=0)


class PartnerBillIn(BaseModel):
    work_order_id: uuid.UUID
    lines: list[BillLine] = Field(min_length=1)
    amount: Decimal | None = Field(default=None, gt=0)
    their_bill_no: str | None = None
    bill_date: datetime.date | None = None
    media_object_key: str | None = None


@router.post("/bills", status_code=201)
async def send_bill(body: PartnerBillIn, p: Partner = Depends(get_partner), conn: AsyncConnection = Depends(get_db_conn)):
    """Their bill: recorded on the work order as waiting for the company's check (never approved or paid by itself).
    The answer says what the check found, in their words."""
    from mesiri.domains.subcontracts.router import BillIn, BillLineIn, _bill_expense, _check

    wo = await _their_wo(conn, p, body.work_order_id)
    bill = BillIn(lines=[BillLineIn(line_id=x.line_id, quantity=x.quantity, rate=x.rate) for x in body.lines], amount=body.amount,
                  their_bill_no=body.their_bill_no, bill_date=body.bill_date, media_object_key=body.media_object_key)
    result = await _check(conn, p.organization_id, wo, bill)
    recorder = await _creator(conn, wo) or (await conn.execute(text(
        "SELECT id FROM users WHERE organization_id = :org AND upper(role) IN ('OWNER', 'ADMIN') AND status = 'active' "
        "ORDER BY created_at LIMIT 1"), {"org": p.organization_id})).scalar()
    if recorder is None:
        raise HTTPException(status_code=409, detail="The company has nobody to receive bills yet.")
    number = int((await conn.execute(text("SELECT COALESCE(MAX(number), 0) + 1 FROM work_order_bills WHERE work_order_id = :w"),
                                     {"w": body.work_order_id})).scalar())
    when = body.bill_date or datetime.date.today()
    expense_id = await _bill_expense(conn, p.organization_id, recorder, wo, number, Decimal(result["gross"]), when, bill)
    bill_id = uuid.uuid4()
    import json

    await conn.execute(text(
        "INSERT INTO work_order_bills (id, organization_id, work_order_id, expense_id, number, their_bill_no, bill_date, gross, "
        "check_status, flags, submitted_by_contact, source) VALUES (:id, :org, :wo, :e, :n, :no, :d, :g, 'waiting', "
        "CAST(:f AS jsonb), :c, 'partner')"),
        {"id": bill_id, "org": p.organization_id, "wo": body.work_order_id, "e": expense_id, "n": number,
         "no": (body.their_bill_no or "").strip() or None, "d": when, "g": Decimal(result["gross"]),
         "f": json.dumps(result["flags"]), "c": p.contact_id})
    for bl in result["lines"]:
        await conn.execute(text("INSERT INTO work_order_bill_lines (organization_id, bill_id, line_id, quantity, rate) VALUES "
                                "(:org, :b, :l, :q, :r)"), {"org": p.organization_id, "b": bill_id, "l": bl["line_id"],
                                                             "q": Decimal(bl["quantity"]), "r": Decimal(bl["rate"])})
    ref = store.bill_ref(number)
    await store.log(conn, p.organization_id, body.work_order_id, "billed", f"{ref} ₹{result['gross']} sent by {p.name} ({p.vendor_name})",
                    None, p.name)
    why = "; ".join(f["words"] for f in result["flags"])
    await _tell_office(conn, p, wo, f"🧾 {p.vendor_name} sent bill {ref} ₹{result['gross']} on {wo['ref']}"
                       + (f" — the check found: {why}." if why else " — it matches the work measured.") + " Approve or reject it on the work order.",
                       f"bill:{bill_id}")
    return {"ref": ref, "work_order": wo["ref"], "amount": result["gross"], "status": "waiting for the company's check",
            "check": [f["words"] for f in result["flags"]] or ["matches the work measured and the agreed rates"]}
