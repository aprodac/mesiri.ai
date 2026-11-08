"""Narrow REST API for expenses (M9 scope): RecordExpense + read-back,
plus read-only receipt attachment access.

No WhatsApp/Planner, no budgets/payments endpoints yet — those are
separate, later work (see application/expenses/commands.py's docstring on
why RecordExpenseCommand is local rather than a shared contract).
RecordExpense is idempotent via a client-supplied `Idempotency-Key` header,
backed by the same `idempotency_keys` table Materials' CQRS path uses (see
application/expenses/repository.py's docstring for how the transaction-
ownership model differs from that path).

Attachment reads (`/attachments`, `/{expense_id}/attachments`) serve
receipt photos captured via the WhatsApp image-purpose picker (Finance
Module Slice 6b). Since 5 Nov 2026 (WEB-65) a bill is also added to a saved
expense with `POST /{expense_id}/attachments`: a file from the dashboard, or a
WhatsApp photo that came after the expense was saved. `media_object_key`
is never returned as-is; every attachment is resolved to a short-lived
presigned URL via `ObjectStoragePort.generate_presigned_url()` so the
dashboard never needs to know about R2/bucket keys directly.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.application.expenses.commands import RecordExpenseCommand
from mesiri.application.expenses.handlers import RecordExpenseHandler
from mesiri.application.expenses.resolution import PostgresExpenseCategoryResolver
from mesiri.application.finance.reverse_commands import ReverseTransactionCommand
from mesiri.application.finance.reverse_handler import ReverseTransactionHandler
from mesiri.application.finance.reverse_resolution import PostgresReverseTargetResolver
from mesiri.application.vendors.resolution import PostgresVendorResolver
from mesiri.authorization.context import AuthorizationContext
from mesiri.authorization.roles import may_manage_money, may_view_expenses
from mesiri.domains.expenses.bill_file import bill_key, decode_bill
from mesiri.domains.expenses.paid_via import paid_via
from mesiri.domains.expenses.responses import ExpenseResponse, RecordExpenseResponse
from mesiri.domains.projects.router import get_auth_context
from mesiri.domains.shared.media import assert_downloadable_url
from mesiri.domains.shared.modules import require_module
from mesiri.infrastructure.objectstorage.dependency import get_object_storage
from mesiri.infrastructure.postgres.dependency import get_db_conn
from mesiri.infrastructure.postgres.repositories.expense_execution import (
    PostgresExpenseExecutionRepository,
)
from mesiri.infrastructure.postgres.repositories.expenses import (
    PostgresExpenseAttachmentRepository,
    PostgresExpenseCategoryRepository,
    PostgresExpenseRepository,
)
from mesiri.infrastructure.postgres.repositories.reverse_execution import (
    PostgresReverseExecutionRepository,
)
from mesiri.infrastructure.postgres.repositories.vendors import PostgresVendorRepository
from mesiri_contracts.application.results.execution_result import ExecutionStatus
from mesiri_contracts.common.storage import ObjectStoragePort

router = APIRouter(
    prefix="/expenses",
    tags=["expenses"],
    dependencies=[Depends(require_module("finance"))],
)

def _expense_view_scope(auth_context: AuthorizationContext) -> set[uuid.UUID] | None:
    """SEC-01: the projects whose expenses this person may read -- None for
    every project in the org. A role that may not read expenses at all gets a
    403 (it can still record one: POST "" and the category list stay open)."""
    if not may_view_expenses(auth_context.role):
        raise HTTPException(status_code=403, detail="Not authorized to view expenses")
    if auth_context.project_scope.grants_all_org_projects:
        return None
    return set(auth_context.project_scope.project_ids)


def _in_scope(project_id: uuid.UUID | None, scope: set[uuid.UUID] | None) -> bool:
    """An expense with no project is company-wide: only an all-projects scope sees it."""
    return scope is None or (project_id is not None and project_id in scope)


# Presigned URLs are short-lived by design (they must be re-fetched, never
# cached across sessions) -- 10 minutes is long enough to load a lightbox or
# a gallery grid without expiring mid-view, short enough that a leaked URL
# isn't a standing liability.
_ATTACHMENT_URL_TTL_SECONDS = 600


class ExpenseAttachmentResponse(BaseModel):
    id: uuid.UUID
    expense_id: uuid.UUID
    attachment_type: str
    created_at: datetime.datetime | None = None
    url: str


class ExpenseAttachmentGalleryItem(BaseModel):
    id: uuid.UUID
    expense_id: uuid.UUID
    attachment_type: str
    created_at: datetime.datetime | None = None
    url: str
    amount: Decimal
    description: str | None = None
    occurred_date: datetime.date
    project_id: uuid.UUID
    category_name: str | None = None
    vendor_name: str | None = None


class RecordExpenseRequest(BaseModel):
    project_id: uuid.UUID
    amount: Decimal
    occurred_date: datetime.date
    # Either category_id (a real, already-fetched id) or category_text (a
    # free-typed name the resolver matches against expense_categories, or
    # falls back to "Uncategorized" for -- see application/expenses/
    # resolution.py's ExpenseCategoryResolver) must be usable; at least one
    # of the two should be sent, but neither is required at the schema level
    # since an absent category_text still resolves to the default category.
    category_id: uuid.UUID | None = None
    category_text: str | None = None
    site_id: uuid.UUID | None = None
    vendor_id: uuid.UUID | None = None
    vendor_text: str | None = None
    # Paid immediately from a specific org account (e.g. a petty cash box) --
    # same field RecordExpenseCommand already exposes for the WhatsApp path
    # (expense_execution.py records the payment + ledger transaction when
    # set). Omit to leave the expense unpaid, exactly as before this field
    # existed on the REST request.
    account_id: uuid.UUID | None = None
    #: PRC-18 (7 Nov): someone paid it themselves and is owed it back ('reimbursable'); the WhatsApp path already
    #: could, the dashboard form had a "Paid" button that saved nothing.
    paid_from_own_pocket: bool = False
    currency: str = "INR"
    description: str | None = None
    occurred_time: datetime.time | None = None
    source: str = "web"
    source_message_id: str | None = None
    correlation_id: str | None = None
    tax_rate: Decimal | None = None
    tax_amount: Decimal | None = None
    is_tax_inclusive: bool = True
    #: WA-124: the bill photo, as stored when it arrived on this company's WhatsApp
    #: (``inbound_messages.media_object_key``). Attached to the expense as its receipt.
    media_object_key: str | None = None


def _authorize_write(
    auth_context: AuthorizationContext, project_id: uuid.UUID, site_id: uuid.UUID | None
) -> None:
    if not auth_context.project_scope.grants_all_org_projects:
        if project_id not in auth_context.project_scope.project_ids:
            raise HTTPException(status_code=403, detail="Not authorized for this project")
    if site_id is not None:
        site_scope = auth_context.site_scope_for_project(project_id)
        if not site_scope.grants_all_sites and site_id not in site_scope.site_ids:
            raise HTTPException(status_code=403, detail="Not authorized for this site")


@router.post("", response_model=RecordExpenseResponse)
async def record_expense(
    body: RecordExpenseRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Record an expense. Retried requests with the same Idempotency-Key
    return the original outcome rather than creating a second expense."""
    _authorize_write(auth_context, body.project_id, body.site_id)

    cmd = RecordExpenseCommand(
        idempotency_key=idempotency_key,
        organization_id=str(auth_context.organization_id),
        project_id=str(body.project_id),
        site_id=str(body.site_id) if body.site_id else None,
        category_id=str(body.category_id) if body.category_id else None,
        category_text=body.category_text,
        vendor_id=str(body.vendor_id) if body.vendor_id else None,
        vendor_text=body.vendor_text,
        account_id=str(body.account_id) if body.account_id else None,
        paid_from_own_pocket=body.paid_from_own_pocket and body.account_id is None,
        amount=body.amount,
        currency=body.currency,
        description=body.description,
        occurred_date=body.occurred_date,
        occurred_time=body.occurred_time,
        source=body.source,
        source_message_id=body.source_message_id,
        correlation_id=body.correlation_id,
        created_by=str(auth_context.user_id),
        tax_rate=body.tax_rate,
        tax_amount=body.tax_amount,
        is_tax_inclusive=body.is_tax_inclusive,
        media_object_key=body.media_object_key,
    )

    from mesiri.domains.subcontracts.store import refuse_tds_account

    await refuse_tds_account(conn, auth_context.organization_id, body.account_id)
    if body.media_object_key and not await _photo_is_ours(
        conn, auth_context.organization_id, body.media_object_key
    ):
        raise HTTPException(status_code=404, detail="Photo not found")

    # Resolvers wired in (previously absent on the REST path -- a request
    # with no category_id and no matching category_text would have hit
    # expense_execution.py's "Handler must resolve this" RuntimeError). Same
    # ports the WhatsApp path uses (runtime/dependencies.py's expense wiring),
    # just constructed per-request here rather than once at startup.
    handler = RecordExpenseHandler(
        PostgresExpenseExecutionRepository(),
        resolver=PostgresExpenseCategoryResolver(),
        vendor_resolver=PostgresVendorResolver(),
    )
    result = await handler.handle(conn, cmd)

    if result.status == ExecutionStatus.REJECTED:
        raise HTTPException(status_code=422, detail=result.rejection_reasons)

    status_code = 201 if result.status == ExecutionStatus.SUCCEEDED else 200
    content: dict = {"id": result.material_row_id, "status": result.status.value}
    if result.status == ExecutionStatus.SUCCEEDED and result.material_row_id:
        # PRC-11: a supplier's bill typed as an expense -- the deliveries it is for, linked when certain, else offered
        # (domains/vendors/matching.py), so a delivery and its bill are owed and cost once.
        from mesiri.domains.vendors import matching

        found = await matching.for_expense(conn, auth_context.organization_id, uuid.UUID(str(result.material_row_id)))
        if found:
            content["unbilled_deliveries"] = found
    return JSONResponse(status_code=status_code, content=content)


class CategoryResponse(BaseModel):
    id: uuid.UUID
    name: str
    code: str | None = None
    status: str
    expense_count: int = 0
    total_amount_spent: Decimal = Decimal("0")


class CreateCategoryRequest(BaseModel):
    name: str
    code: str | None = None


class UpdateCategoryRequest(BaseModel):
    name: str | None = None
    code: str | None = None
    status: str | None = None


@router.get("/categories", response_model=list[CategoryResponse])
async def list_expense_categories(
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Return all expense categories for the org with metrics. Seeds a
    construction-generic starter set the first time an org's category list
    is read empty (see PostgresExpenseCategoryRepository.seed_defaults_if_empty)
    -- otherwise this dropdown, and the AI extraction it stays in sync
    with, would start from nothing."""
    cat_repo = PostgresExpenseCategoryRepository(conn)
    await cat_repo.seed_defaults_if_empty(
        auth_context.organization_id, created_by=auth_context.user_id
    )
    metrics = await cat_repo.list_with_metrics(auth_context.organization_id)
    # SEC-01: the names stay (recording an expense needs them); the spending
    # per category is only for those who may read expenses.
    sees_money = may_view_expenses(auth_context.role)
    return [
        CategoryResponse(
            id=m["category"].id,
            name=m["category"].name,
            code=m["category"].code,
            status=m["category"].status,
            expense_count=m["expense_count"] if sees_money else 0,
            total_amount_spent=m["total_amount"] if sees_money else Decimal("0"),
        )
        for m in metrics
    ]


def _may_manage_categories(auth_context: AuthorizationContext) -> None:
    """SEC-04: the roles that manage money, the same rule as ``PATCH /cost/categories`` (a category's cost centre)."""
    from mesiri.authorization.roles import may_manage_money

    if not may_manage_money(auth_context.role):
        raise HTTPException(status_code=403, detail="Only the owner, an admin or finance can add or change expense categories.")


@router.post("/categories", response_model=CategoryResponse, status_code=201)
async def create_expense_category(
    body: CreateCategoryRequest,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Create a new expense category (owner, admin or finance: a category decides the cost centre its spending counts
    in, CC-01, and later its ledger; SEC-04, decided 8 Nov)."""
    _may_manage_categories(auth_context)
    cat_repo = PostgresExpenseCategoryRepository(conn)
    existing = await cat_repo.find_by_name_exact_active(auth_context.organization_id, body.name)
    if existing:
        raise HTTPException(status_code=409, detail="Category with this name already exists")
    cat = await cat_repo.create(
        organization_id=auth_context.organization_id,
        name=body.name,
        code=body.code,
        created_by=auth_context.user_id,
    )
    return CategoryResponse(
        id=cat.id,
        name=cat.name,
        code=cat.code,
        status=cat.status,
        expense_count=0,
        total_amount_spent=Decimal("0"),
    )


@router.patch("/categories/{category_id}", response_model=CategoryResponse)
async def update_expense_category(
    category_id: uuid.UUID,
    body: UpdateCategoryRequest,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Update category name, code, or status (owner, admin or finance, SEC-04)."""
    _may_manage_categories(auth_context)
    cat_repo = PostgresExpenseCategoryRepository(conn)
    cat = await cat_repo.get_by_id(auth_context.organization_id, category_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    updated = await cat_repo.update(
        organization_id=auth_context.organization_id,
        category_id=category_id,
        name=body.name,
        code=body.code,
        status=body.status,
        updated_by=auth_context.user_id,
    )
    assert updated is not None
    return CategoryResponse(
        id=updated.id,
        name=updated.name,
        code=updated.code,
        status=updated.status,
        expense_count=0,
        total_amount_spent=Decimal("0"),
    )


async def _list_names(conn: AsyncConnection, organization_id: uuid.UUID, items: list) -> dict[str, dict]:
    """Vendor, project and site names for a page of expenses, one query per kind."""
    from sqlalchemy import text

    out: dict[str, dict] = {"vendors": {}, "projects": {}, "sites": {}, "expense_categories": {}, "users": {}}
    wanted = {
        "vendors": {getattr(i, "vendor_id", None) for i in items} - {None},
        "projects": {i.project_id for i in items} - {None},
        "sites": {i.site_id for i in items} - {None},
        "expense_categories": {i.category_id for i in items} - {None},
        "users": {getattr(i, "created_by", None) for i in items} - {None},
    }
    for kind, ids in wanted.items():
        if not ids:
            continue
        name = "full_name" if kind == "users" else "name"
        rows = await conn.execute(
            text(f"SELECT id, {name} AS name FROM {kind} WHERE organization_id = :org AND id = ANY(:ids)"),  # noqa: S608 -- fixed names
            {"org": organization_id, "ids": list(ids)},
        )
        out[kind] = {r.id: r.name for r in rows}
    return out


async def _work_order_of(conn: AsyncConnection, organization_id: uuid.UUID, expense_id: uuid.UUID) -> dict | None:
    """NXT-06: when this expense is a subcontractor's bill on a work order: which, and its check."""
    from mesiri.domains.subcontracts.store import fetch_bills

    found = await fetch_bills(conn, organization_id, expense_ids=[expense_id])
    if not found:
        return None
    b = found[0]
    return {k: b[k] for k in ("work_order_id", "wo_ref", "ref", "check_status", "flags", "retention_held", "payable_now")}


async def _source_invoice(conn: AsyncConnection, organization_id: uuid.UUID, expense_id: uuid.UUID) -> dict | None:
    """The supplier bill that made this expense (material_invoices.expense_id), its deliveries and their orders."""
    from mesiri.domains.procurement.orders import ref as order_ref

    inv = (await conn.execute(text(
        "SELECT i.id, i.invoice_number, i.invoice_date, COALESCE(v.name, i.supplier_name) AS supplier "
        "FROM material_invoices i LEFT JOIN vendors v ON v.id = i.vendor_id "
        "WHERE i.organization_id = :org AND i.expense_id = :eid LIMIT 1"), {"org": organization_id, "eid": expense_id})).mappings().first()
    if inv is None:
        return None
    rows = (await conn.execute(text(
        "SELECT COALESCE(mc.name, r.material_name) AS material, r.quantity, r.unit, r.unit_cost, po.id AS order_id, "
        "po.number AS order_number FROM material_receipts r LEFT JOIN materials_catalog mc ON mc.id = r.material_id "
        "LEFT JOIN purchase_order_lines pol ON pol.id = r.purchase_order_line_id "
        "LEFT JOIN purchase_orders po ON po.id = pol.purchase_order_id "
        "WHERE r.organization_id = :org AND r.invoice_id = :inv AND r.reverses_movement_id IS NULL ORDER BY r.created_at"),
        {"org": organization_id, "inv": inv["id"]})).mappings().all()
    return {
        "id": str(inv["id"]), "number": inv["invoice_number"],
        "date": inv["invoice_date"].isoformat() if inv["invoice_date"] else None, "supplier": inv["supplier"],
        "items": [{"material": r["material"], "quantity": format(Decimal(r["quantity"]).normalize(), "f"), "unit": r["unit"],
                   "rate": str(r["unit_cost"]) if r["unit_cost"] is not None else None,
                   "order_id": str(r["order_id"]) if r["order_id"] else None,
                   "order_ref": order_ref(r["order_number"]) if r["order_number"] else None} for r in rows],
    }


async def _list_payments(conn: AsyncConnection, organization_id: uuid.UUID, expense_ids: list) -> dict:
    """PRC-18: per expense, its confirmed payments: the account paid most from (name, type), the total paid, and the
    amount per account type that ``paid_via`` reads. One query for the page."""
    from sqlalchemy import text

    if not expense_ids:
        return {}
    rows = await conn.execute(
        text(
            "SELECT p.expense_id, a.id AS account_id, a.name AS account_name, a.account_type, SUM(p.amount) AS paid "
            "FROM expense_payments p JOIN money_accounts a ON a.id = p.account_id "
            "WHERE p.organization_id = :org AND p.expense_id = ANY(:ids) AND p.status = 'confirmed' "
            "GROUP BY p.expense_id, a.id, a.name, a.account_type ORDER BY p.expense_id, SUM(p.amount) DESC"
        ),
        {"org": organization_id, "ids": list(expense_ids)},
    )
    out: dict = {}
    for r in rows.mappings():
        e = out.setdefault(r["expense_id"], {"account_id": str(r["account_id"]), "account_name": r["account_name"],
                                             "account_type": r["account_type"], "paid": Decimal(0), "by_type": {}})
        e["paid"] += Decimal(r["paid"])
        e["by_type"][r["account_type"]] = e["by_type"].get(r["account_type"], Decimal(0)) + Decimal(r["paid"])
    return out


@router.get("", response_model=list[ExpenseResponse])
async def list_expenses(
    project_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
    vendor_id: uuid.UUID | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Confirmed expenses, newest first. 7 Nov (PRC-18): ``vendor_id`` and the dates are honoured (the supplier sheet
    asked for one supplier's expenses and got every expense), and each row says how it was paid (``paid_via``),
    from which account, and who recorded it (whom a "reimbursable" one is owed to)."""
    scope = _expense_view_scope(auth_context)
    repo = PostgresExpenseRepository(conn)

    items = await repo.list_confirmed(
        auth_context.organization_id,
        project_id=project_id,
        site_id=site_id,
        category_id=category_id,
        vendor_id=vendor_id,
        start_date=date_from,
        end_date=date_to,
    )
    items = [item for item in items if _in_scope(item.project_id, scope)]

    # WEB-51: the list names the vendor, project and site (the dashboard showed "Direct Payee" / "Org Wide" for every
    # row without them), one query each; categories, payments and people the same way.
    names = await _list_names(conn, auth_context.organization_id, items)
    cat_names = names["expense_categories"]
    payments = await _list_payments(conn, auth_context.organization_id, [i.id for i in items])

    return [
        ExpenseResponse(
            id=item.id,
            organization_id=item.organization_id,
            project_id=item.project_id,
            project_name=names["projects"].get(item.project_id),
            site_id=item.site_id,
            site_name=names["sites"].get(item.site_id),
            vendor_id=getattr(item, "vendor_id", None),
            vendor_name=names["vendors"].get(getattr(item, "vendor_id", None)),
            expense_number=getattr(item, "expense_number", None),
            tax_amount=getattr(item, "tax_amount", None),
            category_id=item.category_id,
            category_name=cat_names.get(item.category_id),
            account_id=payments.get(item.id, {}).get("account_id"),
            account_name=payments.get(item.id, {}).get("account_name"),
            account_type=payments.get(item.id, {}).get("account_type"),
            paid_amount=payments.get(item.id, {}).get("paid"),
            paid_via=paid_via(item.payment_status, payments.get(item.id, {}).get("by_type")),
            tax_rate=getattr(item, "tax_rate", None),
            is_tax_inclusive=getattr(item, "is_tax_inclusive", True) if getattr(item, "is_tax_inclusive", None) is not None else True,
            created_by_name=names["users"].get(item.created_by),
            amount=item.amount,
            currency=item.currency,
            description=item.description,
            occurred_date=item.occurred_date,
            occurred_time=item.occurred_time,
            workflow_status=item.workflow_status,
            payment_status=item.payment_status,
            source=item.source,
            source_message_id=item.source_message_id,
            correlation_id=item.correlation_id,
            created_by=item.created_by,
        )
        for item in items
    ]


@router.get("/attachments", response_model=list[ExpenseAttachmentGalleryItem])
async def list_all_attachments(
    project_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    start_date: datetime.date | None = None,
    end_date: datetime.date | None = None,
    limit: int = 50,
    offset: int = 0,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
    object_storage: ObjectStoragePort = Depends(get_object_storage),
):
    """Every receipt across the org, newest first -- the "see all receipts
    together" gallery view. Declared before `/{expense_id}` so "attachments"
    is never matched as an expense id."""
    scope = _expense_view_scope(auth_context)
    attachment_repo = PostgresExpenseAttachmentRepository(conn)
    rows = await attachment_repo.list_for_organization(
        auth_context.organization_id,
        project_id=project_id,
        site_id=site_id,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset,
    )

    rows = [row for row in rows if _in_scope(row.project_id, scope)]

    # Batch-resolve category/vendor names in one pass each, same convention
    # list_expenses already uses below -- avoids N queries per row.
    cat_repo = PostgresExpenseCategoryRepository(conn)
    vendor_repo = PostgresVendorRepository(conn)
    cat_names: dict[uuid.UUID, str] = {}
    vendor_names: dict[uuid.UUID, str] = {}
    for row in rows:
        if row.category_id is not None and row.category_id not in cat_names:
            cat = await cat_repo.get_by_id(auth_context.organization_id, row.category_id)
            if cat:
                cat_names[row.category_id] = cat.name
        if row.vendor_id is not None and row.vendor_id not in vendor_names:
            vendor = await vendor_repo.get_by_id(auth_context.organization_id, row.vendor_id)
            if vendor:
                vendor_names[row.vendor_id] = vendor.name

    return [
        ExpenseAttachmentGalleryItem(
            id=row.id,
            expense_id=row.expense_id,
            attachment_type=row.attachment_type,
            created_at=row.created_at,
            url=assert_downloadable_url(
                await object_storage.generate_presigned_url(
                    row.media_object_key, expires_in_seconds=_ATTACHMENT_URL_TTL_SECONDS
                )
            ),
            amount=row.amount,
            description=row.description,
            occurred_date=row.occurred_date,
            project_id=row.project_id,
            category_name=cat_names.get(row.category_id) if row.category_id else None,
            vendor_name=vendor_names.get(row.vendor_id) if row.vendor_id else None,
        )
        for row in rows
    ]


@router.get("/{expense_id}", response_model=ExpenseResponse)
async def get_expense(
    expense_id: uuid.UUID,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    scope = _expense_view_scope(auth_context)
    repo = PostgresExpenseRepository(conn)
    expense = await repo.get_by_id(auth_context.organization_id, expense_id)
    if expense is None or not _in_scope(expense.project_id, scope):
        raise HTTPException(status_code=404, detail="Expense not found")

    cat_name = None
    if expense.category_id:
        cat_repo = PostgresExpenseCategoryRepository(conn)
        cat = await cat_repo.get_by_id(auth_context.organization_id, expense.category_id)
        if cat:
            cat_name = cat.name

    vendor_name = None
    if getattr(expense, "vendor_id", None):
        v_repo = PostgresVendorRepository(conn)
        v = await v_repo.get_by_id(auth_context.organization_id, expense.vendor_id)
        if v:
            vendor_name = v.name

    proj_name, proj_code = None, None
    if expense.project_id:
        from sqlalchemy import text
        res = await conn.execute(
            text("SELECT name, code FROM projects WHERE id = :pid AND organization_id = :org_id"),
            {"pid": str(expense.project_id), "org_id": str(auth_context.organization_id)},
        )
        prow = res.mappings().first()
        if prow:
            proj_name = prow["name"]
            proj_code = prow.get("code")

    site_name = None
    if expense.site_id:
        from sqlalchemy import text
        sres = await conn.execute(
            text("SELECT name FROM sites WHERE id = :sid AND organization_id = :org_id"),
            {"sid": str(expense.site_id), "org_id": str(auth_context.organization_id)},
        )
        srow = sres.mappings().first()
        if srow:
            site_name = srow["name"]

    account_id, account_name, custodian_name = None, None, None
    try:
        from sqlalchemy import text
        tx_res = await conn.execute(
            text("SELECT from_account_id FROM money_transactions WHERE source_id = :eid LIMIT 1"),
            {"eid": str(expense.id)},
        )
        tx_row = tx_res.mappings().first()
        if tx_row and tx_row["from_account_id"]:
            acc_id = tx_row["from_account_id"]
            acc_res = await conn.execute(
                text("SELECT id, name, owner_user_id FROM money_accounts WHERE id = :aid"),
                {"aid": str(acc_id)},
            )
            acc_row = acc_res.mappings().first()
            if acc_row:
                account_id = str(acc_row["id"])
                account_name = acc_row["name"]
                if acc_row["owner_user_id"]:
                    c_res = await conn.execute(
                        text("SELECT full_name FROM users WHERE id = :uid"),
                        {"uid": str(acc_row["owner_user_id"])},
                    )
                    c_row = c_res.mappings().first()
                    if c_row:
                        custodian_name = c_row["full_name"]
    except Exception as ex:
        print(f"Failed resolving money account details for expense: {ex}")

    paid = (await _list_payments(conn, auth_context.organization_id, [expense.id])).get(expense.id, {})

    user_name, user_email, user_role = None, None, None
    if expense.created_by:
        from sqlalchemy import text
        ures = await conn.execute(
            text("SELECT full_name, email, role FROM users WHERE id = :uid"),
            {"uid": str(expense.created_by)},
        )
        user_row = ures.mappings().first()
        if user_row:
            user_name = user_row["full_name"]
            user_email = user_row["email"]
            user_role = user_row["role"]

    return ExpenseResponse(
        id=expense.id,
        organization_id=expense.organization_id,
        project_id=expense.project_id,
        project_name=proj_name,
        project_code=proj_code,
        site_id=expense.site_id,
        site_name=site_name,
        category_id=expense.category_id,
        category_name=cat_name,
        vendor_id=getattr(expense, "vendor_id", None),
        vendor_name=vendor_name,
        # The ledger lookup above reads money_transactions by the expense's id, but a payment's transaction carries
        # the payment's id, so it never matched: the payments say which account paid it.
        account_id=paid.get("account_id") or account_id,
        account_name=paid.get("account_name") or account_name,
        custodian_name=custodian_name,
        account_type=paid.get("account_type"),
        paid_amount=paid.get("paid"),
        paid_via=paid_via(expense.payment_status, paid.get("by_type")),
        source_invoice=await _source_invoice(conn, auth_context.organization_id, expense.id),
        work_order=await _work_order_of(conn, auth_context.organization_id, expense.id),
        amount=expense.amount,
        currency=expense.currency,
        description=expense.description,
        occurred_date=expense.occurred_date,
        occurred_time=expense.occurred_time,
        workflow_status=expense.workflow_status,
        payment_status=expense.payment_status,
        source=expense.source,
        source_message_id=expense.source_message_id,
        correlation_id=expense.correlation_id,
        tax_rate=getattr(expense, "tax_rate", None),
        tax_amount=getattr(expense, "tax_amount", None),
        is_tax_inclusive=getattr(expense, "is_tax_inclusive", True) if getattr(expense, "is_tax_inclusive", None) is not None else True,
        created_by=expense.created_by,
        created_by_name=user_name,
        created_by_email=user_email,
        created_by_role=user_role,
        created_at=getattr(expense, "created_at", None),
    )


@router.get("/{expense_id}/attachments", response_model=list[ExpenseAttachmentResponse])
async def list_expense_attachments(
    expense_id: uuid.UUID,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
    object_storage: ObjectStoragePort = Depends(get_object_storage),
):
    """Receipt(s) attached to one expense -- what the Expenses page's
    per-row lightbox needs."""
    scope = _expense_view_scope(auth_context)
    repo = PostgresExpenseRepository(conn)
    expense = await repo.get_by_id(auth_context.organization_id, expense_id)
    if expense is None or not _in_scope(expense.project_id, scope):
        raise HTTPException(status_code=404, detail="Expense not found")

    return await _attachment_responses(conn, object_storage, auth_context.organization_id, expense_id)


async def _attachment_responses(
    conn: AsyncConnection, object_storage: ObjectStoragePort, organization_id: uuid.UUID, expense_id: uuid.UUID
) -> list[ExpenseAttachmentResponse]:
    attachment_repo = PostgresExpenseAttachmentRepository(conn)
    attachments = await attachment_repo.list_for_expense(organization_id, expense_id)
    return [
        ExpenseAttachmentResponse(
            id=a.id,
            expense_id=a.expense_id,
            attachment_type=a.attachment_type,
            created_at=getattr(a, "created_at", None),
            url=assert_downloadable_url(
                await object_storage.generate_presigned_url(
                    a.media_object_key, expires_in_seconds=_ATTACHMENT_URL_TTL_SECONDS
                )
            ),
        )
        for a in attachments
    ]


async def _photo_is_ours(conn: AsyncConnection, organization_id: uuid.UUID, key: str) -> bool:
    """Only a file this company's own WhatsApp received: a key names no company, so
    without this a caller could attach (and then read) another company's photo."""
    owned = (
        await conn.execute(
            text(
                "SELECT 1 FROM inbound_messages "
                "WHERE organization_id = :org AND media_object_key = :key LIMIT 1"
            ),
            {"org": organization_id, "key": key},
        )
    ).first()
    return owned is not None


class AddBill(BaseModel):
    """A bill for an expense already saved: a file from the dashboard (``data_base64`` +
    ``content_type``: a photo or a PDF, 700 KB or under), or a photo this company's
    WhatsApp received (``media_object_key``). Exactly one of the two."""

    data_base64: str | None = None
    content_type: str | None = None
    media_object_key: str | None = None


@router.post(
    "/{expense_id}/attachments", response_model=list[ExpenseAttachmentResponse], status_code=201
)
async def add_expense_bill(
    expense_id: uuid.UUID,
    body: AddBill,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
    object_storage: ObjectStoragePort = Depends(get_object_storage),
):
    """Add a bill photo (or PDF) to an expense; returns the expense's bills.

    Whoever may record an expense on its project may add its bill: the same rule as
    recording one with a photo (``_authorize_write``). Bills are evidence, so one is
    added, never replaced; the same WhatsApp photo twice is kept once.
    """
    if bool(body.data_base64) == bool(body.media_object_key):
        raise HTTPException(status_code=422, detail="Send either a file or a WhatsApp photo.")
    expense = await PostgresExpenseRepository(conn).get_by_id(auth_context.organization_id, expense_id)
    if expense is None:
        raise HTTPException(status_code=404, detail="Expense not found")
    _authorize_write(auth_context, expense.project_id, expense.site_id)
    if body.media_object_key:
        key = body.media_object_key
        if not await _photo_is_ours(conn, auth_context.organization_id, key):
            raise HTTPException(status_code=404, detail="Photo not found")
        already = (
            await conn.execute(
                text("SELECT 1 FROM expense_attachments WHERE expense_id = :e AND media_object_key = :k LIMIT 1"),
                {"e": expense_id, "k": key},
            )
        ).first()
    else:
        try:
            data, extension, content_type = decode_bill(body.data_base64 or "", body.content_type or "")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        key = bill_key(auth_context.organization_id, expense_id, extension)
        await object_storage.put_object(key, data, content_type=content_type)
        already = None
    if already is None:
        await PostgresExpenseAttachmentRepository(conn).create(
            expense_id=expense_id,
            media_object_key=key,
            attachment_type="receipt",
            created_by=auth_context.user_id,
        )
    return await _attachment_responses(conn, object_storage, auth_context.organization_id, expense_id)


@router.post("/{expense_id}/reverse")
async def reverse_expense(
    expense_id: uuid.UUID,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Reverse / void a confirmed expense, including reversing any ledger payments."""
    # SEC-03 (7 Nov 2026): the same rule as the reversal itself (application/finance/reverse_validation.py), said
    # as a 403 instead of a 422 after the work.
    if not may_manage_money(auth_context.role):
        raise HTTPException(status_code=403, detail="Only the owner, an admin or finance can take back an expense.")

    ikey = idempotency_key or f"rev_rest_{expense_id}_{uuid.uuid4().hex[:8]}"
    cmd = ReverseTransactionCommand(
        idempotency_key=ikey,
        organization_id=str(auth_context.organization_id),
        created_by=str(auth_context.user_id),
        created_by_role=auth_context.role,
        target_kind="expense",
        expense_id=str(expense_id),
    )

    handler = ReverseTransactionHandler(
        repo=PostgresReverseExecutionRepository(),
        resolver=PostgresReverseTargetResolver(),
    )
    result = await handler.handle(conn, cmd)

    if result.status == ExecutionStatus.REJECTED:
        raise HTTPException(status_code=422, detail=result.rejection_reasons)

    return {"id": str(expense_id), "status": "voided"}



# ---------------------------------------------------------------------------------------------------------------------
# PRC-35 (approved in session by the owner, 7 Nov 2026): mark an expense paid from an account, in full or in part, or
# repay someone who paid from their own pocket (the same thing: a payment from the account the money leaves). Each
# payment posts its ledger entry (expense_payments + money_transactions, record_payment) and the expense's payment
# status follows. For the roles in authorization.roles.may_manage_money; the expense's project must be in scope.
# ---------------------------------------------------------------------------------------------------------------------


class PayExpenseRequest(BaseModel):
    account_id: uuid.UUID
    #: Without it: what is still unpaid.
    amount: Decimal | None = None
    paid_date: datetime.date | None = None
    reference: str | None = None
    method: str | None = None


async def _payable_expense(conn: AsyncConnection, auth_context: AuthorizationContext, expense_id: uuid.UUID):
    if not may_manage_money(auth_context.role):
        raise HTTPException(status_code=403, detail="Only the owner, an admin or finance can pay an expense.")
    scope = _expense_view_scope(auth_context)
    expense = await PostgresExpenseRepository(conn).get_by_id(auth_context.organization_id, expense_id)
    if expense is None or not _in_scope(expense.project_id, scope):
        raise HTTPException(status_code=404, detail="Expense not found")
    if expense.workflow_status == "pending_confirmation":
        raise HTTPException(status_code=409, detail="This bill waits for its check: approve it first (it is not owed yet).")
    if expense.workflow_status != "confirmed":
        raise HTTPException(status_code=409, detail="This expense was taken back.")
    return expense


async def _payments_out(conn: AsyncConnection, organization_id: uuid.UUID, expense_id: uuid.UUID) -> list[dict]:
    rows = await conn.execute(
        text(
            "SELECT p.id, p.amount, p.paid_date, p.status, p.reference_number, p.payment_method, p.created_at, "
            "p.advance_id, a.id AS account_id, a.name AS account_name, a.account_type, u.full_name AS paid_by "
            "FROM expense_payments p JOIN money_accounts a ON a.id = p.account_id "
            "LEFT JOIN users u ON u.id = p.created_by "
            "WHERE p.organization_id = :org AND p.expense_id = :eid ORDER BY p.paid_date, p.created_at"
        ),
        {"org": organization_id, "eid": expense_id},
    )
    return [
        {"id": str(r["id"]), "amount": str(r["amount"]), "paid_date": r["paid_date"].isoformat(), "status": r["status"],
         "reference": r["reference_number"], "method": r["payment_method"], "account_id": str(r["account_id"]),
         "account_name": r["account_name"], "account_type": r["account_type"], "recorded_by": r["paid_by"],
         # CC-10: paid from an advance given to the supplier earlier (no money moved now).
         "from_advance": r["advance_id"] is not None}
        for r in rows.mappings()
    ]


async def _vendor_advance(conn: AsyncConnection, organization_id: uuid.UUID, vendor_id: uuid.UUID | None) -> dict | None:
    """CC-10: what the bill's supplier still holds of our advances, so paying the bill can use it first."""
    if vendor_id is None:
        return None
    rows = (await conn.execute(text(
        "SELECT p.id, p.paid_date, p.amount - COALESCE((SELECT SUM(x.amount) FROM expense_payments x "
        "WHERE x.advance_id = p.id AND x.status = 'confirmed'), 0) AS left_, v.name "
        "FROM expense_payments p JOIN vendors v ON v.id = p.vendor_id "
        "WHERE p.organization_id = :org AND p.vendor_id = :v AND p.expense_id IS NULL AND p.status = 'confirmed' "
        "ORDER BY p.paid_date, p.created_at"), {"org": organization_id, "v": vendor_id})).mappings().all()
    open_ = [r for r in rows if r["left_"] > 0]
    if not open_:
        return None
    return {"vendor_id": str(vendor_id), "vendor": open_[0]["name"],
            "left": str(sum((Decimal(r["left_"]) for r in open_), Decimal(0)).quantize(Decimal("0.01"))),
            "advances": [{"id": str(r["id"]), "date": r["paid_date"].isoformat(),
                          "left": str(Decimal(r["left_"]).quantize(Decimal("0.01")))} for r in open_]}


@router.get("/{expense_id}/payments")
async def list_expense_payments(
    expense_id: uuid.UUID,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    scope = _expense_view_scope(auth_context)
    expense = await PostgresExpenseRepository(conn).get_by_id(auth_context.organization_id, expense_id)
    if expense is None or not _in_scope(expense.project_id, scope):
        raise HTTPException(status_code=404, detail="Expense not found")
    payments = await _payments_out(conn, auth_context.organization_id, expense_id)
    paid = sum((Decimal(p["amount"]) for p in payments if p["status"] == "confirmed"), Decimal(0))
    cents = Decimal("0.01")
    left = max(Decimal(0), Decimal(expense.amount) - paid)
    return {"expense_id": str(expense_id), "amount": str(Decimal(expense.amount).quantize(cents)),
            "paid": str(paid.quantize(cents)), "left": str(left.quantize(cents)),
            "payment_status": expense.payment_status, "payments": payments,
            "vendor_advance": await _vendor_advance(conn, auth_context.organization_id, expense.vendor_id)
            if left > 0 else None}


@router.post("/{expense_id}/payments", status_code=201)
async def pay_expense(
    expense_id: uuid.UUID,
    body: PayExpenseRequest,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Pay an expense (or repay who paid it) from one of the company's accounts."""
    from mesiri.domains.subcontracts.store import refuse_tds_account
    from mesiri.infrastructure.postgres.repositories.expenses import (
        PostgresExpensePaymentRepository,
    )
    from mesiri.infrastructure.postgres.repositories.finance import PostgresMoneyAccountRepository

    expense = await _payable_expense(conn, auth_context, expense_id)
    await refuse_tds_account(conn, auth_context.organization_id, body.account_id)
    account = await PostgresMoneyAccountRepository(conn).get_by_id(auth_context.organization_id, body.account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    if str(getattr(account.status, "value", account.status)) != "active":
        raise HTTPException(status_code=409, detail=f"{account.name} is closed.")
    payments = PostgresExpensePaymentRepository(conn)
    already = sum((Decimal(p["amount"]) for p in await _payments_out(conn, auth_context.organization_id, expense_id)
                   if p["status"] == "confirmed"), Decimal(0))
    left = Decimal(expense.amount) - already
    amount = body.amount if body.amount is not None else left
    if left <= 0:
        raise HTTPException(status_code=409, detail="This expense is already paid.")
    if amount <= 0:
        raise HTTPException(status_code=422, detail="The amount must be more than zero.")
    if amount > left:
        raise HTTPException(status_code=422, detail=f"Only {left} is still unpaid.")
    # NXT-06/07: a subcontractor's bill is paid only once checked, and never its retention held.
    from mesiri.domains.subcontracts.store import payable_caps

    cap = (await payable_caps(conn, auth_context.organization_id, [expense_id])).get(expense_id)
    if cap is not None and amount > cap:
        raise HTTPException(status_code=409, detail=(
            "This subcontract bill waits for its check (approve it on the work order first)." if cap <= 0
            else f"Only ₹{cap} of this bill can be paid now; the rest is retention held until it is released."))
    try:
        payment = await payments.record_payment(
            organization_id=auth_context.organization_id, expense_id=expense_id, account_id=body.account_id,
            amount=amount, paid_date=body.paid_date or datetime.date.today(), created_by=auth_context.user_id,
            payment_method=body.method, reference_number=body.reference,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"payment_id": str(payment.id), **(await list_expense_payments(expense_id, auth_context, conn))}


@router.post("/{expense_id}/payments/{payment_id}/reverse")
async def reverse_expense_payment(
    expense_id: uuid.UUID,
    payment_id: uuid.UUID,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Undo a payment made by mistake: the money goes back to the account, the expense is unpaid again for that part."""
    from mesiri.infrastructure.postgres.repositories.expenses import (
        PostgresExpensePaymentRepository,
    )

    await _payable_expense(conn, auth_context, expense_id)
    owned = await conn.execute(
        text("SELECT 1 FROM expense_payments WHERE id = :pid AND expense_id = :eid AND organization_id = :org"),
        {"pid": payment_id, "eid": expense_id, "org": auth_context.organization_id},
    )
    if owned.first() is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    try:
        await PostgresExpensePaymentRepository(conn).reverse_payment(auth_context.organization_id, payment_id,
                                                                      auth_context.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return await list_expense_payments(expense_id, auth_context, conn)
