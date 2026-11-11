"""Finance > Vendors (suppliers): the list, their details, and the supplier ledger (CC-09) with paying them (CC-10).

The list and details are for everyone with Finance (a vendor is picked when recording an expense). What the company
owes them (balances, ledger, payables) is for the roles that see spending (SEC-01 ``may_view_expenses``), within their
projects; paying, opening balances, billing deliveries, deleting and merging are for the roles that manage money
(SEC-03 ``may_manage_money``). Ledger rules: ``ledger.py``.

PRC-52, a supplier's own papers (``documents.py``): ``GET /finance/vendors/papers`` (who needs attention: expired,
missing, expiring), ``GET|POST /finance/vendors/{id}/documents``, ``GET|DELETE /finance/vendors/{id}/documents/{doc}``
(a short-lived link; archive). PAN, cheque and agreement for the roles that see spending, who also add and archive.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.authorization.roles import may_manage_money, may_view_expenses
from mesiri.domains.projects.router import get_auth_context
from mesiri.domains.shared.modules import require_module
from mesiri.domains.vendors import documents as papers
from mesiri.domains.vendors import ledger
from mesiri.domains.vendors.details import (
    VendorDetailError,
    clean_address,
    clean_gstin,
    clean_phone,
)
from mesiri.infrastructure.objectstorage.dependency import get_object_storage
from mesiri.infrastructure.postgres.dependency import get_db_conn
from mesiri.infrastructure.postgres.repositories.vendors import PostgresVendorRepository
from mesiri_contracts.common.storage import ObjectStoragePort

router = APIRouter(
    prefix="/finance/vendors",
    tags=["vendors"],
    dependencies=[Depends(require_module("finance"))],
)


class VendorResponse(BaseModel):
    id: uuid.UUID
    name: str
    code: str | None = None
    status: str
    phone: str | None = None
    gstin: str | None = None
    address: str | None = None
    #: CC-09: what kind of vendor, the credit they give, a contact, notes, the opening balance.
    kind: str = "supplier"
    credit_days: int | None = None
    #: MP-03: days from order to delivery; the material plan's order-by date (3 when not set).
    lead_time_days: int | None = None
    contact_person: str | None = None
    notes: str | None = None
    opening_balance: Decimal | None = None
    opening_balance_date: datetime.date | None = None
    expense_count: int = 0
    total_amount_paid: Decimal = Decimal("0")


KINDS = ("supplier", "subcontractor", "hire", "service", "labour")  # labour: a labour contractor's team (LW-01)


class CreateVendorRequest(BaseModel):
    name: str
    phone: str | None = None
    gstin: str | None = None
    address: str | None = None
    kind: str | None = None
    credit_days: int | None = Field(default=None, ge=0, le=365)
    lead_time_days: int | None = Field(default=None, ge=0, le=120)
    contact_person: str | None = None
    notes: str | None = None
    opening_balance: Decimal | None = None
    opening_balance_date: datetime.date | None = None


class UpdateVendorRequest(BaseModel):
    name: str | None = None
    status: str | None = None
    #: PRC-04: sent as null or "", the detail is cleared; left out, it stays.
    phone: str | None = None
    gstin: str | None = None
    address: str | None = None
    kind: str | None = None
    credit_days: int | None = Field(default=None, ge=0, le=365)
    lead_time_days: int | None = Field(default=None, ge=0, le=120)
    contact_person: str | None = None
    notes: str | None = None
    opening_balance: Decimal | None = None
    opening_balance_date: datetime.date | None = None


def _text(value: str | None) -> str | None:
    t = " ".join((value or "").split())
    return t or None


def _details(body: BaseModel, auth_context: AuthorizationContext | None = None) -> dict:
    """The details the request sent, cleaned; a 422 with the person's message for a wrong one."""
    cleaners = {"phone": clean_phone, "gstin": clean_gstin, "address": clean_address, "contact_person": _text,
                "notes": lambda v: (v or "").strip() or None}
    sent = body.model_fields_set
    try:
        out = {k: cleaners[k](getattr(body, k)) for k in cleaners if k in sent}
    except VendorDetailError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if "kind" in sent:
        kind = (body.kind or "supplier").strip().lower()
        if kind not in KINDS:
            raise HTTPException(status_code=422, detail="A vendor is a supplier, subcontractor, hire or service.")
        out["kind"] = kind
    if "credit_days" in sent:
        out["credit_days"] = body.credit_days
    if "lead_time_days" in sent:
        out["lead_time_days"] = body.lead_time_days
    if {"opening_balance", "opening_balance_date"} & sent:
        if auth_context is not None and not may_manage_money(auth_context.role):
            raise HTTPException(status_code=403, detail="Only the owner, an admin or finance can set an opening balance.")
        balance = body.opening_balance
        out["opening_balance"] = balance.quantize(Decimal("0.01")) if balance is not None else None
        when = body.opening_balance_date
        out["opening_balance_date"] = when or (datetime.date.today() if balance is not None else None)
    return out


def _response(vendor, **metrics) -> VendorResponse:  # noqa: ANN001
    return VendorResponse(
        id=vendor.id,
        name=vendor.name,
        code=vendor.code,
        status=vendor.status,
        phone=vendor.phone,
        gstin=vendor.gstin,
        address=vendor.address,
        **metrics,
    )


async def _with_extras(conn: AsyncConnection, org: uuid.UUID, responses: list[VendorResponse]) -> list[VendorResponse]:
    """The CC-09 details for each vendor (one query for the list)."""
    extra = await ledger.vendors_of(conn, org)
    out = []
    for r in responses:
        v = extra.get(r.id)
        if v:
            r = r.model_copy(update={k: v[k] for k in ("kind", "credit_days", "lead_time_days", "contact_person", "notes",
                                                        "opening_balance", "opening_balance_date")})
        out.append(r)
    return out


@router.get("", response_model=list[VendorResponse])
async def list_vendors(
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """List all vendors for the organization with live disbursement metrics."""
    repo = PostgresVendorRepository(conn)
    metrics = await repo.list_with_metrics(auth_context.organization_id)
    return await _with_extras(conn, auth_context.organization_id, [
        _response(m["vendor"], expense_count=m["expense_count"], total_amount_paid=m["total_amount"])
        for m in metrics
    ])


@router.post("", response_model=VendorResponse, status_code=201)
async def create_vendor(
    body: CreateVendorRequest,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Create a new vendor in the organization."""
    repo = PostgresVendorRepository(conn)
    details = _details(body, auth_context)
    if not body.name.strip():
        raise HTTPException(status_code=422, detail="A vendor needs a name.")
    existing = await repo.find_by_name_exact_active(auth_context.organization_id, body.name)
    if existing:
        raise HTTPException(status_code=409, detail="Vendor with this name already exists")
    vendor = await repo.create(
        organization_id=auth_context.organization_id,
        name=body.name.strip(),
        created_by=auth_context.user_id,
    )
    if details:
        vendor = await repo.update(
            auth_context.organization_id, vendor.id, updated_by=auth_context.user_id, details=details
        )
    return (await _with_extras(conn, auth_context.organization_id,
                               [_response(vendor, expense_count=0, total_amount_paid=Decimal("0"))]))[0]


@router.patch("/{vendor_id}", response_model=VendorResponse)
async def update_vendor(
    vendor_id: uuid.UUID,
    body: UpdateVendorRequest,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Update vendor name or active/inactive status."""
    repo = PostgresVendorRepository(conn)
    vendor = await repo.get_by_id(auth_context.organization_id, vendor_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")
    if body.name is not None:
        if not body.name.strip():
            raise HTTPException(status_code=422, detail="A vendor needs a name.")
        clash = await repo.find_by_name_exact_active(auth_context.organization_id, body.name)
        if clash and clash.id != vendor_id:
            raise HTTPException(status_code=409, detail=f"{clash.name} is already a vendor: merge the two instead.")
    if body.status is not None and body.status.strip().lower() not in ("active", "inactive"):
        raise HTTPException(status_code=422, detail="status is active or inactive")
    updated = await repo.update(
        organization_id=auth_context.organization_id,
        vendor_id=vendor_id,
        name=body.name,
        status=body.status,
        updated_by=auth_context.user_id,
        details=_details(body, auth_context),
    )
    assert updated is not None
    return (await _with_extras(conn, auth_context.organization_id,
                               [_response(updated, expense_count=0, total_amount_paid=Decimal("0"))]))[0]


# ---------------------------------------------------------------------------------------------------------------------
# CC-09 supplier ledger and payables; CC-10 paying a supplier (on account, applied to bills oldest first).
# ---------------------------------------------------------------------------------------------------------------------


def _view_scope(auth: AuthorizationContext) -> set[uuid.UUID] | None:
    """The projects whose money this person sees (SEC-01, the same as expenses); None: the whole company."""
    if not may_view_expenses(auth.role):
        raise HTTPException(status_code=403, detail="Supplier balances are shown to the roles that see spending.")
    if auth.project_scope.grants_all_org_projects:
        return None
    return set(auth.project_scope.project_ids)


def _narrow(scope: set[uuid.UUID] | None, project_id: uuid.UUID | None) -> set[uuid.UUID] | None:
    if project_id is None:
        return scope
    if scope is not None and project_id not in scope:
        raise HTTPException(status_code=404, detail="Project not found")
    return {project_id}


def _manage(auth: AuthorizationContext, what: str) -> None:
    if not may_manage_money(auth.role):
        raise HTTPException(status_code=403, detail=f"Only the owner, an admin or finance can {what}.")


async def _today(conn: AsyncConnection, org: uuid.UUID) -> datetime.date:
    from mesiri.application.dpr import project_day

    return await project_day.company_today(conn, org)


async def _vendor(conn: AsyncConnection, org: uuid.UUID, vendor_id: uuid.UUID) -> dict:
    v = (await ledger.vendors_of(conn, org, vendor_id)).get(vendor_id)
    if v is None:
        raise HTTPException(status_code=404, detail="Vendor not found")
    return v


@router.get("/payables")
async def payables(
    project_id: uuid.UUID | None = None,
    include_settled: bool = False,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Every supplier with what we owe them: balance, not billed yet, open and overdue bills, advances, age."""
    projects = _narrow(_view_scope(auth_context), project_id)
    org = auth_context.organization_id
    entries, state = await ledger.fetch_entries(conn, org, vendor_id=None, projects=projects)
    today = await _today(conn, org)
    rows = []
    totals = {k: Decimal(0) for k in ("payable", "advance", "overdue", "unbilled", "bills_left")}
    buckets = {key: Decimal(0) for *_, key in ledger.BUCKETS}
    for v in state["vendors"].values():
        s = ledger.summarise(v, entries, state, today)
        if not s["lines"] and not include_settled:
            continue
        bal = Decimal(s["balance"])
        if not include_settled and bal == 0 and not s["bills_open"] and Decimal(s["advance_left"]) == 0:
            continue
        totals["payable"] += max(bal, Decimal(0))
        totals["advance"] += max(-bal, Decimal(0))
        for k in ("overdue", "unbilled", "bills_left"):
            totals[k] += Decimal(s[k])
        for k, val in s["buckets"].items():
            buckets[k] += Decimal(val)
        s.pop("open_bills")
        s.pop("advances")
        rows.append({**ledger.vendor_out(v), **s,
                     "oldest_unbilled": s["oldest_unbilled"].isoformat() if s["oldest_unbilled"] else None})
    rows.sort(key=lambda r: (-Decimal(r["overdue"]), -Decimal(r["balance"]), r["name"].lower()))
    return {"as_of": today.isoformat(), "partial": projects is not None,
            "totals": {k: ledger.money(v) for k, v in totals.items()},
            "buckets": {k: ledger.money(v) for k, v in buckets.items()},
            "vendors": rows}


@router.get("/unbilled")
async def unbilled_deliveries(
    project_id: uuid.UUID | None = None,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """PRC-11: every delivery with no bill yet, oldest first -- with a rate or without, from a supplier on the list or
    only named, or with no supplier at all -- and whether it came against an order. What the office chases."""
    projects = _narrow(_view_scope(auth_context), project_id)
    from mesiri.domains.procurement.rates import BILLED_SQL

    sql = (
        "SELECT r.id, r.occurred_date, r.quantity, r.unit_cost, r.total_cost, mc.name AS material, "
        "COALESCE(u.code, r.unit) AS unit, r.project_id, p.name AS project, s.name AS site, r.vendor_id, "
        "v.name AS vendor, NULLIF(trim(r.supplier), '') AS supplier, po.id AS order_id, po.number AS order_number "
        "FROM material_receipts r JOIN materials_catalog mc ON mc.id = r.material_id "
        "LEFT JOIN units_of_measure u ON u.id = mc.default_unit_id LEFT JOIN projects p ON p.id = r.project_id "
        "LEFT JOIN sites s ON s.id = r.site_id LEFT JOIN vendors v ON v.id = r.vendor_id "
        "LEFT JOIN purchase_order_lines pol ON pol.id = r.purchase_order_line_id "
        "LEFT JOIN purchase_orders po ON po.id = pol.purchase_order_id "
        "WHERE r.organization_id = :org AND r.quantity > 0 AND r.movement_reason = 'RECEIVED' AND r.transfer_id IS NULL "
        "AND r.reverses_movement_id IS NULL "
        "AND NOT EXISTS (SELECT 1 FROM material_usage x WHERE x.reverses_movement_id = r.id) "
        "AND NOT EXISTS (SELECT 1 FROM material_receipts y WHERE y.reverses_movement_id = r.id) "
        "AND NOT " + BILLED_SQL
    )
    params: dict = {"org": auth_context.organization_id}
    sql = ledger._scope(sql, params, "r.project_id", projects)
    rows = (await conn.execute(text(sql + " ORDER BY r.occurred_date, r.created_at"), params)).mappings().all()
    today = await _today(conn, auth_context.organization_id)
    from mesiri.domains.procurement.orders import ref as order_ref
    from mesiri.domains.vendors.matching import value

    out = []
    for r in rows:
        v = value(r)
        out.append({"receipt_id": str(r["id"]), "date": r["occurred_date"].isoformat(), "days": (today - r["occurred_date"]).days,
                    "material": r["material"], "quantity": format(Decimal(r["quantity"]).normalize(), "f"), "unit": r["unit"],
                    "rate": ledger.money(r["unit_cost"]) if r["unit_cost"] is not None else None,
                    "amount": ledger.money(v) if v is not None else None, "project_id": str(r["project_id"]),
                    "project": r["project"], "site": r["site"], "vendor_id": str(r["vendor_id"]) if r["vendor_id"] else None,
                    "supplier": r["vendor"] or r["supplier"], "order_id": str(r["order_id"]) if r["order_id"] else None,
                    "order_ref": order_ref(r["order_number"]) if r["order_number"] else None})
    return {"as_of": today.isoformat(), "deliveries": out,
            "totals": {"count": len(out), "amount": ledger.money(sum((Decimal(d["amount"]) for d in out if d["amount"]), Decimal(0))),
                       "unpriced": sum(1 for d in out if d["amount"] is None),
                       "no_order": sum(1 for d in out if not d["order_id"]),
                       "no_supplier": sum(1 for d in out if not d["supplier"])}}


@router.get("/unlinked-names")
async def unlinked_names(
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Supplier names typed on deliveries that point at no supplier record (older deliveries, or a name typed
    differently): they are on no supplier's account until linked. With a likely supplier when one looks like it."""
    _view_scope(auth_context)
    rows = (await conn.execute(text(
        "SELECT lower(trim(r.supplier)) AS k, min(trim(r.supplier)) AS name, COUNT(*) AS n, max(r.occurred_date) AS last, "
        "SUM(COALESCE(r.total_cost, r.unit_cost * r.quantity)) AS amount FROM material_receipts r "
        "WHERE r.organization_id = :org AND r.vendor_id IS NULL AND NULLIF(trim(r.supplier), '') IS NOT NULL "
        "AND r.movement_reason = 'RECEIVED' AND r.transfer_id IS NULL GROUP BY 1 ORDER BY COUNT(*) DESC"),
        {"org": auth_context.organization_id})).mappings().all()
    vendors = list((await ledger.vendors_of(conn, auth_context.organization_id)).values())

    def likely(name: str) -> dict | None:
        n = name.lower()
        first = n.split()[0] if n.split() else n
        for v in sorted(vendors, key=lambda v: len(v["name"])):
            vn = v["name"].lower()
            if vn == n or vn.startswith(n) or n.startswith(vn) or (len(first) > 3 and vn.split()[0] == first):
                return {"id": str(v["id"]), "name": v["name"]}
        return None

    return [{"name": r["name"], "deliveries": int(r["n"]), "last": r["last"].isoformat() if r["last"] else None,
             "amount": ledger.money(r["amount"]) if r["amount"] is not None else None, "likely": likely(r["name"])}
            for r in rows]


class LinkNameRequest(BaseModel):
    name: str
    #: The supplier these deliveries are from; left out with ``create``: a new supplier of that name.
    vendor_id: uuid.UUID | None = None
    create: bool = False


@router.post("/link-name")
async def link_name(
    body: LinkNameRequest,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Every delivery with this supplier name and no supplier record goes on that supplier's account (and from then
    on its rates, ledger and bills)."""
    _manage(auth_context, "link supplier names")
    org = auth_context.organization_id
    if body.vendor_id is not None:
        v = await _vendor(conn, org, body.vendor_id)
    elif body.create:
        repo = PostgresVendorRepository(conn)
        created = await repo.create(organization_id=org, name=body.name.strip(), created_by=auth_context.user_id)
        v = await _vendor(conn, org, created.id)
    else:
        raise HTTPException(status_code=422, detail="Say which supplier, or create one.")
    res = await conn.execute(text(
        "UPDATE material_receipts SET vendor_id = :v WHERE organization_id = :org AND vendor_id IS NULL "
        "AND lower(trim(supplier)) = lower(trim(:n))"), {"v": v["id"], "org": org, "n": body.name})
    return {"vendor": ledger.vendor_out(v), "deliveries": res.rowcount}


@router.get("/papers")
async def papers_attention(auth_context: AuthorizationContext = Depends(get_auth_context),
                           conn: AsyncConnection = Depends(get_db_conn)):
    """PRC-52: suppliers whose papers are expired, missing or expiring within 15 days (the list's warning, Today)."""
    org = auth_context.organization_id
    return {"items": await papers.attention_by_vendor(conn, org, await _today(conn, org),
                                                      see_restricted=may_view_expenses(auth_context.role))}


async def _papers(conn: AsyncConnection, auth: AuthorizationContext, vendor_id: uuid.UUID) -> dict:
    v = await _vendor(conn, auth.organization_id, vendor_id)
    see = may_view_expenses(auth.role)
    out = papers.describe(await papers.fetch(conn, auth.organization_id, vendor_id), gstin=v.get("gstin"),
                          today=await _today(conn, auth.organization_id), see_restricted=see)
    return {**out, "vendor_id": str(vendor_id), "may_add": see}


@router.get("/{vendor_id}/documents")
async def vendor_documents(vendor_id: uuid.UUID, auth_context: AuthorizationContext = Depends(get_auth_context),
                           conn: AsyncConnection = Depends(get_db_conn)):
    """PRC-52: per kind the current paper, its status and history, and what the supplier record already holds."""
    return await _papers(conn, auth_context, vendor_id)


@router.post("/{vendor_id}/documents", status_code=201)
async def add_vendor_document(
    vendor_id: uuid.UUID,
    file: UploadFile = File(...),
    kind: str = Form(...),
    number: str | None = Form(default=None, max_length=60),
    valid_until: str | None = Form(default=None),
    notes: str | None = Form(default=None, max_length=500),
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
    object_storage: ObjectStoragePort = Depends(get_object_storage),
):
    """Keep a paper (photo or PDF, the documents register's checks). A paper of a kind already on file replaces it
    (the old one is kept as history); "other" papers sit side by side."""
    import hashlib

    from mesiri.domains.documents.router import _date, _read, object_key

    if not may_view_expenses(auth_context.role):
        raise HTTPException(status_code=403, detail="Only the owner, an admin, finance or a project manager can add a "
                            "supplier's papers.")
    if kind not in papers.KINDS:
        raise HTTPException(status_code=422, detail=f"kind is one of {', '.join(papers.KINDS)}")
    org = auth_context.organization_id
    await _vendor(conn, org, vendor_id)
    data, name, content_type = await _read(file)
    current = [d for d in await papers.fetch(conn, org, vendor_id) if d["kind"] == kind and d["status"] == "current"]
    doc_id = uuid.uuid4()
    key = object_key(org, f"vendors/{vendor_id}", doc_id, name)
    await object_storage.put_object(key, data, content_type=content_type)
    await papers.insert(conn, org, {
        "id": doc_id, "vendor_id": vendor_id, "kind": kind, "number": (number or "").strip() or None,
        "valid_until": _date(valid_until, "valid_until"), "status": "current",
        "supersedes_id": current[0]["id"] if current and kind != "other" else None, "object_key": key,
        "file_name": name, "content_type": content_type, "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(), "notes": (notes or "").strip() or None,
        "uploaded_by": auth_context.user_id})
    return await _papers(conn, auth_context, vendor_id)


async def _paper(conn: AsyncConnection, auth: AuthorizationContext, vendor_id: uuid.UUID, doc_id: uuid.UUID) -> dict:
    doc = await papers.one(conn, auth.organization_id, vendor_id, doc_id)
    if doc is None or (doc["kind"] in papers.RESTRICTED_KINDS and not may_view_expenses(auth.role)):
        raise HTTPException(status_code=404, detail="Document not found")  # never say a hidden one exists
    return doc


@router.get("/{vendor_id}/documents/{doc_id}")
async def vendor_document(vendor_id: uuid.UUID, doc_id: uuid.UUID,
                          auth_context: AuthorizationContext = Depends(get_auth_context),
                          conn: AsyncConnection = Depends(get_db_conn),
                          object_storage: ObjectStoragePort = Depends(get_object_storage)):
    """One paper with a short-lived link to its file."""
    from mesiri.domains.shared.media import signed_media_url

    doc = await _paper(conn, auth_context, vendor_id, doc_id)
    return {**papers._out(doc), "url": await signed_media_url(object_storage, doc["object_key"])}


@router.delete("/{vendor_id}/documents/{doc_id}")
async def archive_vendor_document(vendor_id: uuid.UUID, doc_id: uuid.UUID,
                                  auth_context: AuthorizationContext = Depends(get_auth_context),
                                  conn: AsyncConnection = Depends(get_db_conn)):
    """Archive (kept, file and all; hidden); the paper it replaced is current again. Never a hard delete."""
    if not may_view_expenses(auth_context.role):
        raise HTTPException(status_code=403, detail="Only the owner, an admin, finance or a project manager can "
                            "archive a supplier's papers.")
    doc = await _paper(conn, auth_context, vendor_id, doc_id)
    await papers.archive(conn, auth_context.organization_id, doc)
    return await _papers(conn, auth_context, vendor_id)


@router.get("/{vendor_id}")
async def get_vendor(
    vendor_id: uuid.UUID,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """One vendor's details, and what is linked to it (so a delete can say why it is refused)."""
    v = await _vendor(conn, auth_context.organization_id, vendor_id)
    return {**ledger.vendor_out(v), "linked": await _links(conn, auth_context.organization_id, vendor_id)}


@router.get("/{vendor_id}/ledger")
async def vendor_ledger(
    vendor_id: uuid.UUID,
    project_id: uuid.UUID | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """The supplier's account, line by line with a running balance; ``date_from`` brings the earlier lines forward
    as one balance. Also the open bills (due, overdue), deliveries not billed and advances not used yet."""
    projects = _narrow(_view_scope(auth_context), project_id)
    org = auth_context.organization_id
    v = await _vendor(conn, org, vendor_id)
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=422, detail="date_from is after date_to")
    entries, state = await ledger.fetch_entries(conn, org, vendor_id=vendor_id, projects=projects)
    today = await _today(conn, org)
    summary = ledger.summarise(v, entries, state, today)
    balance = Decimal(0)
    forward = Decimal(0)
    lines = []
    for e in entries:
        balance += e["owe"] - e["paid"]
        if date_from and e["date"] < date_from:
            forward = balance
            continue
        if date_to and e["date"] > date_to:
            continue
        lines.append(ledger.entry_out(e, balance))
    closing = Decimal(lines[-1]["balance"]) if lines else forward
    unbilled = [ledger.entry_out(e, Decimal(0)) for e in entries if e["kind"] == "delivery"]
    return {
        "vendor": ledger.vendor_out(v), "as_of": today.isoformat(), "partial": projects is not None,
        "date_from": date_from.isoformat() if date_from else None, "date_to": date_to.isoformat() if date_to else None,
        "brought_forward": ledger.money(forward) if date_from else None,
        "closing": ledger.money(closing),
        "period": {"owed": ledger.money(sum((Decimal(x["owe"] or 0) for x in lines), Decimal(0))),
                   "paid": ledger.money(sum((Decimal(x["paid"] or 0) for x in lines), Decimal(0)))},
        "summary": {k: (v2.isoformat() if isinstance(v2, datetime.date) else v2) for k, v2 in summary.items()},
        "unbilled": unbilled,
        "lines": lines,
    }


class PayVendorRequest(BaseModel):
    account_id: uuid.UUID
    amount: Decimal = Field(gt=0)
    paid_date: datetime.date | None = None
    reference: str | None = None
    method: str | None = None
    project_id: uuid.UUID | None = None
    #: The bills to pay, in this order. Left out: the oldest open bills first. ``[]``: keep it all as an advance.
    bill_ids: list[uuid.UUID] | None = None


async def _open_bills(conn: AsyncConnection, auth: AuthorizationContext, vendor_id: uuid.UUID,
                      bill_ids: list[uuid.UUID] | None, project_id: uuid.UUID | None = None) -> list[dict]:
    """The bills a payment may go to: open, this vendor's, in the caller's projects -- and in the payment's project
    when it has one (8 Nov 2026: a payment made for one project paid another project's older bills); oldest first
    unless named."""
    scope = _narrow(_view_scope(auth), project_id)
    entries, state = await ledger.fetch_entries(conn, auth.organization_id, vendor_id=vendor_id, projects=scope)
    # Only what may be paid now: a subcontract bill waiting for its check is not, nor its retention held (NXT-06/07).
    open_ = {b["id"]: {**b, "left": b["payable"]} for b in state["bills"].values() if b["payable"] > 0}
    if bill_ids is None:
        return sorted(open_.values(), key=lambda b: (b["date"], b["number"] or ""))
    out = []
    for bid in bill_ids:
        b = open_.get(str(bid))
        if b is None:
            raise HTTPException(status_code=409, detail="One of those bills is not open for this vendor.")
        out.append(b)
    return out


async def _apply(conn: AsyncConnection, auth: AuthorizationContext, advance_id: uuid.UUID, bills: list[dict]) -> list:
    from mesiri.infrastructure.postgres.repositories.expenses import (
        PostgresExpensePaymentRepository,
    )

    repo = PostgresExpensePaymentRepository(conn)
    used = []
    for b in bills:
        left = await repo.advance_left(auth.organization_id, advance_id)
        if left <= 0:
            break
        part = min(left, b["left"])
        if part <= 0:
            continue
        await repo.apply_advance(organization_id=auth.organization_id, advance_id=advance_id,
                                 expense_id=uuid.UUID(b["id"]), amount=part, created_by=auth.user_id)
        used.append({"expense_id": b["id"], "number": b["number"], "amount": ledger.money(part)})
    return used


@router.post("/{vendor_id}/payments", status_code=201)
async def pay_vendor(
    vendor_id: uuid.UUID,
    body: PayVendorRequest,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Pay a supplier from an account: the money leaves once, then pays open bills oldest first (or the ones named);
    what is left over stays with them as an advance and pays the next bill."""
    from mesiri.infrastructure.postgres.repositories.expenses import (
        PostgresExpensePaymentRepository,
    )
    from mesiri.infrastructure.postgres.repositories.finance import PostgresMoneyAccountRepository

    _manage(auth_context, "pay a supplier")
    org = auth_context.organization_id
    v = await _vendor(conn, org, vendor_id)
    scope = _view_scope(auth_context)
    if body.project_id is not None:
        _narrow(scope, body.project_id)
    from mesiri.domains.subcontracts.store import refuse_tds_account

    await refuse_tds_account(conn, org, body.account_id)
    account = await PostgresMoneyAccountRepository(conn).get_by_id(org, body.account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    if str(getattr(account.status, "value", account.status)) != "active":
        raise HTTPException(status_code=409, detail=f"{account.name} is closed.")
    bills = await _open_bills(conn, auth_context, vendor_id, body.bill_ids, body.project_id)
    amount = body.amount.quantize(Decimal("0.01"))
    payment = await PostgresExpensePaymentRepository(conn).record_on_account(
        organization_id=org, vendor_id=vendor_id, account_id=body.account_id, amount=amount,
        paid_date=body.paid_date or await _today(conn, org), created_by=auth_context.user_id,
        project_id=body.project_id, payment_method=_text(body.method), reference_number=_text(body.reference),
        description=f"Paid to {v['name']}",
    )
    used = await _apply(conn, auth_context, payment.id, bills)
    left = amount - sum((Decimal(u["amount"]) for u in used), Decimal(0))
    return {"payment_id": str(payment.id), "vendor_id": str(vendor_id), "vendor": v["name"], "amount": ledger.money(amount),
            "account": account.name, "paid_date": payment.paid_date.isoformat(), "bills_paid": used,
            "advance_left": ledger.money(left)}


class ApplyRequest(BaseModel):
    #: Left out: the oldest open bills first.
    bill_ids: list[uuid.UUID] | None = None


@router.post("/{vendor_id}/payments/{payment_id}/apply")
async def apply_advance(
    vendor_id: uuid.UUID,
    payment_id: uuid.UUID,
    body: ApplyRequest,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Use what is left of an advance on bills (oldest first, or the ones named). No money moves."""
    from mesiri.infrastructure.postgres.repositories.expenses import (
        PostgresExpensePaymentRepository,
    )

    _manage(auth_context, "use an advance on a bill")
    await _on_account(conn, auth_context.organization_id, vendor_id, payment_id)
    left = await PostgresExpensePaymentRepository(conn).advance_left(auth_context.organization_id, payment_id)
    if left <= 0:
        raise HTTPException(status_code=409, detail="Nothing of this payment is left to use.")
    advance_project = (await conn.execute(text("SELECT project_id FROM expense_payments WHERE id = :p"),
                                          {"p": payment_id})).scalar()
    bills = await _open_bills(conn, auth_context, vendor_id, body.bill_ids, advance_project)
    if not bills:
        raise HTTPException(status_code=409, detail="No open bill to use it on.")
    used = await _apply(conn, auth_context, payment_id, bills)
    after = await PostgresExpensePaymentRepository(conn).advance_left(auth_context.organization_id, payment_id)
    return {"payment_id": str(payment_id), "bills_paid": used, "advance_left": ledger.money(after)}


async def _on_account(conn: AsyncConnection, org: uuid.UUID, vendor_id: uuid.UUID, payment_id: uuid.UUID) -> None:
    row = (await conn.execute(text(
        "SELECT 1 FROM expense_payments WHERE id = :p AND organization_id = :org AND vendor_id = :v "
        "AND expense_id IS NULL"), {"p": payment_id, "org": org, "v": vendor_id})).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Payment not found")


@router.post("/{vendor_id}/payments/{payment_id}/reverse")
async def reverse_vendor_payment(
    vendor_id: uuid.UUID,
    payment_id: uuid.UUID,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Undo a payment made by mistake: the bills it paid are open again and the money goes back to the account."""
    from mesiri.infrastructure.postgres.repositories.expenses import (
        PostgresExpensePaymentRepository,
    )

    _manage(auth_context, "undo a payment")
    await _on_account(conn, auth_context.organization_id, vendor_id, payment_id)
    try:
        await PostgresExpensePaymentRepository(conn).reverse_on_account(auth_context.organization_id, payment_id,
                                                                        auth_context.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"payment_id": str(payment_id), "status": "reversed"}


# --- Deliveries and bills: "these deliveries are on this bill" (D-CC3: the bill replaces the deliveries) -----------


class BillDeliveriesRequest(BaseModel):
    receipt_ids: list[uuid.UUID] = Field(min_length=1)
    #: Left out: the deliveries' total.
    amount: Decimal | None = Field(default=None, gt=0)
    bill_number: str | None = None
    bill_date: datetime.date | None = None
    tax_amount: Decimal | None = Field(default=None, ge=0)


class MatchRequest(BaseModel):
    receipt_ids: list[uuid.UUID] = Field(min_length=1)


async def _unbilled(conn: AsyncConnection, auth: AuthorizationContext, vendor_id: uuid.UUID,
                    receipt_ids: list[uuid.UUID]) -> list[dict]:
    scope = _view_scope(auth)
    entries, _ = await ledger.fetch_entries(conn, auth.organization_id, vendor_id=vendor_id, projects=scope)
    open_ = {e["links"]["receipt_id"]: e for e in entries if e["kind"] == "delivery"}
    rows = []
    for rid in dict.fromkeys(receipt_ids):
        e = open_.get(str(rid))
        if e is None:
            raise HTTPException(status_code=409, detail="One of those deliveries is not an unbilled delivery of this vendor.")
        rows.append(e)
    return rows


async def _link(conn: AsyncConnection, auth: AuthorizationContext, v: dict, expense: dict, rows: list[dict],
                bill_number: str | None, bill_date: datetime.date | None) -> list[str]:
    """One material invoice per project for the bill (an invoice belongs to one project), the deliveries on it."""
    by_project: dict = {}
    for e in rows:
        by_project.setdefault(e["project_id"], []).append(e)
    ids = []
    for project_id, group in by_project.items():
        inv = uuid.uuid4()
        await conn.execute(text(
            "INSERT INTO material_invoices (id, organization_id, project_id, vendor_id, supplier_name, invoice_number, "
            "invoice_date, invoice_total, expense_id, source, created_by, notes) VALUES (:id, :org, :p, :v, :name, :no, "
            ":d, :total, :e, 'web', :by, 'Linked on the supplier ledger')"),
            {"id": inv, "org": auth.organization_id, "p": project_id, "v": v["id"], "name": v["name"],
             "no": bill_number, "d": bill_date or expense["occurred_date"],
             "total": expense["amount"] if len(by_project) == 1 else None, "e": expense["id"], "by": auth.user_id})
        from mesiri.domains.vendors.matching import link

        await link(conn, auth.organization_id, inv, [{"id": uuid.UUID(e["links"]["receipt_id"]), "quantity": None}
                                                     for e in group], v["id"], None, None)
        ids.append(str(inv))
    return ids


async def _bill(conn: AsyncConnection, auth: AuthorizationContext, vendor_id: uuid.UUID, expense_id: uuid.UUID) -> dict:
    scope = _view_scope(auth)
    row = (await conn.execute(text(
        "SELECT id, amount, occurred_date, project_id, workflow_status FROM expenses "
        "WHERE id = :e AND organization_id = :org AND vendor_id = :v"),
        {"e": expense_id, "org": auth.organization_id, "v": vendor_id})).mappings().first()
    if row is None or (scope is not None and row["project_id"] not in scope):
        raise HTTPException(status_code=404, detail="Bill not found")
    if row["workflow_status"] != "confirmed":
        raise HTTPException(status_code=409, detail="This bill was taken back.")
    return dict(row)


@router.post("/{vendor_id}/bills", status_code=201)
async def bill_deliveries(
    vendor_id: uuid.UUID,
    body: BillDeliveriesRequest,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """The supplier's bill for deliveries already recorded: one bill (an expense, unpaid) replaces them on the ledger
    and in the cost; its amount is what the bill says (GST, freight), the deliveries' total when not given."""
    from mesiri.application.expenses.handlers import RecordExpenseHandler
    from mesiri.application.expenses.resolution import PostgresExpenseCategoryResolver
    from mesiri.application.vendors.resolution import PostgresVendorResolver
    from mesiri.domains.materials.invoices import build_expense_command
    from mesiri.infrastructure.postgres.repositories.expense_execution import (
        PostgresExpenseExecutionRepository,
    )
    from mesiri_contracts.application.results.execution_result import ExecutionStatus

    _manage(auth_context, "record a supplier's bill")
    org = auth_context.organization_id
    v = await _vendor(conn, org, vendor_id)
    rows = await _unbilled(conn, auth_context, vendor_id, body.receipt_ids)
    projects = {e["project_id"] for e in rows}
    if len(projects) != 1:
        raise HTTPException(status_code=422, detail="Bill one project's deliveries at a time.")
    total = sum((e["owe"] for e in rows), Decimal(0))
    amount = (body.amount or total).quantize(Decimal("0.01"))
    if amount <= 0:
        raise HTTPException(status_code=422, detail="These deliveries have no price; say the bill's amount.")
    sites = {e["site"] for e in rows}
    site_id = None
    if len(sites) == 1:
        site_id = (await conn.execute(text(
            "SELECT site_id FROM material_receipts WHERE id = :r"),
            {"r": uuid.UUID(rows[0]["links"]["receipt_id"])})).scalar()
    key = uuid.uuid4()
    cmd = build_expense_command(
        invoice_id=key, organization_id=org, project_id=projects.pop(), site_id=site_id, vendor_id=vendor_id,
        supplier_name=v["name"], amount=amount, currency="INR",
        occurred_date=body.bill_date or await _today(conn, org), media_object_key=None, created_by=auth_context.user_id,
        correlation_id=None,
    )
    number = _text(body.bill_number)
    cmd = cmd.model_copy(update={"description": f"Bill {number}" if number else f"Bill for {len(rows)} deliveries",
                                 "idempotency_key": f"supplier-bill:{key}", "tax_amount": body.tax_amount})
    result = await RecordExpenseHandler(
        PostgresExpenseExecutionRepository(), resolver=PostgresExpenseCategoryResolver(),
        vendor_resolver=PostgresVendorResolver(),
    ).handle(conn, cmd)
    if result.status is ExecutionStatus.REJECTED or not result.material_row_id:
        raise HTTPException(status_code=422, detail=f"The bill could not be saved: {result.rejection_reasons}")
    expense_id = uuid.UUID(result.material_row_id)
    expense = await _bill(conn, auth_context, vendor_id, expense_id)
    await _link(conn, auth_context, v, expense, rows, number, body.bill_date)
    return {"expense_id": str(expense_id), "amount": ledger.money(amount), "deliveries": len(rows),
            "deliveries_total": ledger.money(total), "difference": ledger.money(amount - total)}


@router.post("/{vendor_id}/bills/{expense_id}/deliveries")
async def match_deliveries(
    vendor_id: uuid.UUID,
    expense_id: uuid.UUID,
    body: MatchRequest,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """These deliveries are on a bill already recorded (an expense typed without them): from now on they are owed and
    cost once, through the bill."""
    _manage(auth_context, "link deliveries to a bill")
    v = await _vendor(conn, auth_context.organization_id, vendor_id)
    expense = await _bill(conn, auth_context, vendor_id, expense_id)
    rows = await _unbilled(conn, auth_context, vendor_id, body.receipt_ids)
    await _link(conn, auth_context, v, expense, rows, None, None)
    total = sum((e["owe"] for e in rows), Decimal(0))
    return {"expense_id": str(expense_id), "deliveries": len(rows), "deliveries_total": ledger.money(total),
            "bill_amount": ledger.money(expense["amount"]), "difference": ledger.money(Decimal(expense["amount"]) - total)}


@router.get("/{vendor_id}/bills/{expense_id}/deliveries")
async def bill_delivery_list(
    vendor_id: uuid.UUID,
    expense_id: uuid.UUID,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    _view_scope(auth_context)
    await _bill(conn, auth_context, vendor_id, expense_id)
    rows = (await conn.execute(text(
        "SELECT r.id, r.occurred_date, r.quantity, r.unit_cost, r.total_cost, r.billed_quantity, r.billed_rate, "
        "mc.name AS material, COALESCE(u.code, r.unit) AS unit, s.name AS site FROM material_receipts r "
        "JOIN material_invoices i ON i.id = r.invoice_id JOIN materials_catalog mc ON mc.id = r.material_id "
        "LEFT JOIN units_of_measure u ON u.id = mc.default_unit_id LEFT JOIN sites s ON s.id = r.site_id "
        "WHERE i.expense_id = :e AND r.organization_id = :org ORDER BY r.occurred_date"),
        {"e": expense_id, "org": auth_context.organization_id})).mappings().all()
    from mesiri.domains.vendors.matching import flags

    return [{"receipt_id": str(r["id"]), "date": r["occurred_date"].isoformat(), "material": r["material"],
             "billed_quantity": format(Decimal(r["billed_quantity"]).normalize(), "f") if r["billed_quantity"] is not None else None,
             "billed_rate": ledger.money(r["billed_rate"]) if r["billed_rate"] is not None else None,
             "flags": flags(Decimal(r["quantity"]), Decimal(r["billed_quantity"]) if r["billed_quantity"] is not None else None,
                            Decimal(r["unit_cost"]) if r["unit_cost"] is not None else None,
                            Decimal(r["billed_rate"]) if r["billed_rate"] is not None else None, r["unit"]),
             "quantity": format(Decimal(r["quantity"]).normalize(), "f"), "unit": r["unit"], "site": r["site"],
             "amount": ledger.money(r["total_cost"] if r["total_cost"] is not None
                                    else (Decimal(r["unit_cost"]) * Decimal(r["quantity"]) if r["unit_cost"] is not None else None))
             if (r["total_cost"] is not None or r["unit_cost"] is not None) else None}
            for r in rows]


@router.delete("/{vendor_id}/bills/{expense_id}/deliveries/{receipt_id}")
async def unmatch_delivery(
    vendor_id: uuid.UUID,
    expense_id: uuid.UUID,
    receipt_id: uuid.UUID,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """A delivery put on the wrong bill: it is owed (and costs) by itself again."""
    _manage(auth_context, "change a bill's deliveries")
    await _bill(conn, auth_context, vendor_id, expense_id)
    res = await conn.execute(text(
        "UPDATE material_receipts r SET invoice_id = NULL FROM material_invoices i "
        "WHERE r.id = :r AND r.organization_id = :org AND i.id = r.invoice_id AND i.expense_id = :e"),
        {"r": receipt_id, "org": auth_context.organization_id, "e": expense_id})
    if not res.rowcount:
        raise HTTPException(status_code=404, detail="That delivery is not on this bill.")
    return {"receipt_id": str(receipt_id), "status": "unbilled"}


# --- Delete and merge -----------------------------------------------------------------------------------------------

#: Every table that points at a vendor (checked against the database's foreign keys in a test).
VENDOR_LINKS = (
    ("expenses", "vendor_id", "expenses"),
    ("material_receipts", "vendor_id", "deliveries"),
    ("material_invoices", "vendor_id", "bills"),
    ("purchase_orders", "vendor_id", "orders"),
    ("expense_payments", "vendor_id", "payments"),
    ("work_orders", "vendor_id", "work orders"),
    ("labour_attendance_lines", "vendor_id", "attendance lines"),
    ("vendor_contacts", "vendor_id", "contacts"),  # NXT-16
    ("equipment", "vendor_id", "machines"),  # NXT-11: machines hired from them
    ("equipment_hire_bills", "vendor_id", "hire bills"),  # NXT-13
    ("project_documents", "vendor_id", "documents"),  # DOC-01 (0527 added it; missed here until TSK-01's run)
    ("tasks", "assignee_vendor_id", "tasks"),  # TSK-01: tasks given to a subcontractor
    ("rfq_vendors", "vendor_id", "quotes"),  # PRC-40 (0540 added it; missed here until PRC-46's run)
    ("material_returns", "vendor_id", "returns"),  # PRC-46: material sent back and its debit note
    ("vendor_ratings", "vendor_id", "ratings"),  # PRC-50 (0544 added it; missed here until PRC-52's run)
    ("vendor_documents", "vendor_id", "papers"),  # PRC-52: GST, PAN, cheque, agreement, ISO / BIS
)
#: How a table's rows are this company's (default: its own organization_id).
_OWNED = {"labour_attendance_lines": "report_id IN (SELECT id FROM labour_attendance_reports WHERE organization_id = :org)"}


async def _links(conn: AsyncConnection, org: uuid.UUID, vendor_id: uuid.UUID) -> dict:
    out = {}
    for table, col, label in VENDOR_LINKS:
        n = (await conn.execute(text(
            f"SELECT COUNT(*) FROM {table} WHERE {_OWNED.get(table, 'organization_id = :org')} AND {col} = :v"),  # noqa: S608
            {"org": org, "v": vendor_id})).scalar()
        out[label] = int(n or 0)
    return out


@router.delete("/{vendor_id}")
async def delete_vendor(
    vendor_id: uuid.UUID,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Delete a vendor added by mistake. One with history is refused (switch it off, or merge it into the right one)."""
    _manage(auth_context, "delete a vendor")
    org = auth_context.organization_id
    v = await _vendor(conn, org, vendor_id)
    links = await _links(conn, org, vendor_id)
    used = {k: n for k, n in links.items() if n}
    if used or v["opening_balance"]:
        said = ", ".join(f"{n} {k}" for k, n in used.items()) or "an opening balance"
        raise HTTPException(status_code=409, detail=f"{v['name']} has {said}: switch it off, or merge it into another vendor.")
    await conn.execute(text("DELETE FROM vendors WHERE id = :v AND organization_id = :org"), {"v": vendor_id, "org": org})
    return {"id": str(vendor_id), "status": "deleted"}


class MergeRequest(BaseModel):
    into_vendor_id: uuid.UUID


@router.post("/{vendor_id}/merge")
async def merge_vendor(
    vendor_id: uuid.UUID,
    body: MergeRequest,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """The same supplier saved twice ("Malabar" and "Malabar Traders"): everything of this one moves to the other,
    contact details it lacks are copied, opening balances add up, and this one is deleted."""
    _manage(auth_context, "merge vendors")
    org = auth_context.organization_id
    if body.into_vendor_id == vendor_id:
        raise HTTPException(status_code=422, detail="Pick a different vendor to merge into.")
    src = await _vendor(conn, org, vendor_id)
    dst = await _vendor(conn, org, body.into_vendor_id)
    moved = await _links(conn, org, vendor_id)
    for table, col, _ in VENDOR_LINKS:
        await conn.execute(text(
            f"UPDATE {table} SET {col} = :dst WHERE {_OWNED.get(table, 'organization_id = :org')} AND {col} = :src"),  # noqa: S608
            {"dst": dst["id"], "src": src["id"], "org": org})
    fill = {k: src[k] for k in ("phone", "gstin", "address", "contact_person", "credit_days", "lead_time_days")
            if dst[k] is None and src[k] is not None}
    ob = [x for x in (src, dst) if x["opening_balance"] is not None]
    if ob:
        fill["opening_balance"] = sum((Decimal(x["opening_balance"]) for x in ob), Decimal(0))
        fill["opening_balance_date"] = max(x["opening_balance_date"] for x in ob if x["opening_balance_date"]) \
            if any(x["opening_balance_date"] for x in ob) else None
    notes = "\n".join(x for x in (dst["notes"], src["notes"]) if x)
    if src["notes"]:
        fill["notes"] = notes
    if fill:
        sets = ", ".join(f"{k} = :{k}" for k in fill)
        await conn.execute(text(f"UPDATE vendors SET {sets}, updated_at = now(), updated_by = :by "  # noqa: S608
                                "WHERE id = :id AND organization_id = :org"),
                           {**fill, "by": auth_context.user_id, "id": dst["id"], "org": org})
    await conn.execute(text("DELETE FROM vendors WHERE id = :v AND organization_id = :org"), {"v": src["id"], "org": org})
    return {"into": ledger.vendor_out(await _vendor(conn, org, dst["id"])), "moved": moved, "deleted": str(src["id"])}


# --- NXT-16: a subcontractor's contacts who may use Mesiri's WhatsApp (option B, approved by Alan 8 Nov 2026) ------


class ContactIn(BaseModel):
    name: str = Field(min_length=1)
    phone: str
    language: str | None = None


class ContactEdit(BaseModel):
    name: str | None = None
    phone: str | None = None
    language: str | None = None
    status: str | None = None


def _contacts_manager(auth: AuthorizationContext) -> None:
    from mesiri.authorization.roles import may_act_on_material_requests

    if not (may_manage_money(auth.role) or may_act_on_material_requests(auth.role)):
        raise HTTPException(status_code=403, detail="Only the owner, an admin, finance or a project manager can manage a subcontractor's contacts.")


async def _clean_contact_phone(conn: AsyncConnection, org: uuid.UUID, phone: str, besides: uuid.UUID | None = None) -> str:
    try:
        cleaned = clean_phone(phone)
    except VendorDetailError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not cleaned:
        raise HTTPException(status_code=422, detail="A contact needs a WhatsApp number.")
    last10 = "".join(c for c in cleaned if c.isdigit())[-10:]
    staff = (await conn.execute(text(
        "SELECT full_name FROM users WHERE status = 'active' AND right(regexp_replace(COALESCE(whatsapp_number, ''), '\\D', '', 'g'), 10) = :d"),
        {"d": last10})).scalar()
    if staff:
        raise HTTPException(status_code=409, detail=f"That number is {staff}'s, who uses Mesiri as staff.")
    clash = (await conn.execute(text(
        "SELECT v.name FROM vendor_contacts c JOIN vendors v ON v.id = c.vendor_id WHERE c.organization_id = :org AND c.status = 'active' "
        "AND right(regexp_replace(c.phone, '\\D', '', 'g'), 10) = :d AND (CAST(:me AS uuid) IS NULL OR c.id <> :me)"),
        {"org": org, "d": last10, "me": besides})).scalar()
    if clash:
        raise HTTPException(status_code=409, detail=f"That number is already a contact of {clash}.")
    return cleaned


def _contact_out(r) -> dict:  # noqa: ANN001
    return {"id": str(r["id"]), "name": r["name"], "phone": r["phone"], "language": r["language"], "status": r["status"],
            "last_seen_at": r["last_seen_at"].isoformat() if r["last_seen_at"] else None, "created_at": r["created_at"].isoformat()}


@router.get("/{vendor_id}/contacts")
async def list_contacts(vendor_id: uuid.UUID, auth_context: AuthorizationContext = Depends(get_auth_context),
                        conn: AsyncConnection = Depends(get_db_conn)):
    await _vendor(conn, auth_context.organization_id, vendor_id)
    rows = (await conn.execute(text("SELECT * FROM vendor_contacts WHERE organization_id = :org AND vendor_id = :v ORDER BY status, name"),
                               {"org": auth_context.organization_id, "v": vendor_id})).mappings().all()
    from mesiri.domains.subcontracts.router import _settings

    return {"partner_access": bool((await _settings(conn, auth_context.organization_id)).get("partner_access")),
            "contacts": [_contact_out(r) for r in rows]}


@router.post("/{vendor_id}/contacts", status_code=201)
async def add_contact(vendor_id: uuid.UUID, body: ContactIn, auth_context: AuthorizationContext = Depends(get_auth_context),
                      conn: AsyncConnection = Depends(get_db_conn)):
    """A person of this subcontractor who may ask Mesiri on WhatsApp what is pending, send bills and report work (all of
    it waiting for the company's check). Never a login to anything else."""
    _contacts_manager(auth_context)
    org = auth_context.organization_id
    await _vendor(conn, org, vendor_id)
    phone = await _clean_contact_phone(conn, org, body.phone)
    row = (await conn.execute(text(
        "INSERT INTO vendor_contacts (organization_id, vendor_id, name, phone, language, invited_by) VALUES (:org, :v, :n, :p, :l, :u) "
        "RETURNING *"), {"org": org, "v": vendor_id, "n": body.name.strip(), "p": phone, "l": body.language, "u": auth_context.user_id})).mappings().one()
    return _contact_out(row)


@router.patch("/{vendor_id}/contacts/{contact_id}")
async def edit_contact(vendor_id: uuid.UUID, contact_id: uuid.UUID, body: ContactEdit,
                       auth_context: AuthorizationContext = Depends(get_auth_context), conn: AsyncConnection = Depends(get_db_conn)):
    """Change a contact, or switch them off (their next message is not answered as the subcontractor)."""
    _contacts_manager(auth_context)
    org = auth_context.organization_id
    sets, p = [], {"id": contact_id, "org": org, "v": vendor_id}
    if body.name is not None:
        sets.append("name = :name")
        p["name"] = body.name.strip()
    if body.phone is not None:
        sets.append("phone = :phone")
        p["phone"] = await _clean_contact_phone(conn, org, body.phone, besides=contact_id)
    if body.language is not None:
        sets.append("language = :lang")
        p["lang"] = body.language or None
    if body.status is not None:
        if body.status not in ("active", "inactive"):
            raise HTTPException(status_code=422, detail="status is active or inactive")
        sets.append("status = :status")
        p["status"] = body.status
    if not sets:
        raise HTTPException(status_code=422, detail="Nothing to change.")
    row = (await conn.execute(text(f"UPDATE vendor_contacts SET {', '.join(sets)}, updated_at = now() "  # noqa: S608
                                   "WHERE id = :id AND organization_id = :org AND vendor_id = :v RETURNING *"), p)).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Contact not found")
    return _contact_out(row)
