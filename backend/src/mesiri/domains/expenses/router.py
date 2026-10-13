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
Module Slice 6b) — write access stays WhatsApp-only, the dashboard never
uploads a receipt itself, only views ones already captured. `media_object_key`
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
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.application.expenses.commands import RecordExpenseCommand
from mesiri.application.expenses.handlers import RecordExpenseHandler
from mesiri.application.expenses.resolution import PostgresExpenseCategoryResolver
from mesiri.application.finance.reverse_commands import ReverseTransactionCommand
from mesiri.application.finance.reverse_handler import ReverseTransactionHandler
from mesiri.application.finance.reverse_resolution import PostgresReverseTargetResolver
from mesiri.application.vendors.resolution import PostgresVendorResolver
from mesiri.authorization.context import AuthorizationContext
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
    currency: str = "INR"
    description: str | None = None
    occurred_time: datetime.time | None = None
    source: str = "web"
    source_message_id: str | None = None
    correlation_id: str | None = None
    tax_rate: Decimal | None = None
    tax_amount: Decimal | None = None
    is_tax_inclusive: bool = True


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
    )

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
    return JSONResponse(
        status_code=status_code,
        content={"id": result.material_row_id, "status": result.status.value},
    )


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
    return [
        CategoryResponse(
            id=m["category"].id,
            name=m["category"].name,
            code=m["category"].code,
            status=m["category"].status,
            expense_count=m["expense_count"],
            total_amount_spent=m["total_amount"],
        )
        for m in metrics
    ]


@router.post("/categories", response_model=CategoryResponse, status_code=201)
async def create_expense_category(
    body: CreateCategoryRequest,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Create a new expense category."""
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
    """Update category name, code, or status."""
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


@router.get("", response_model=list[ExpenseResponse])
async def list_expenses(
    project_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    repo = PostgresExpenseRepository(conn)
    cat_repo = PostgresExpenseCategoryRepository(conn)

    items = await repo.list_confirmed(
        auth_context.organization_id,
        project_id=project_id,
        site_id=site_id,
        category_id=category_id,
    )

    # Build a category name lookup in one pass (avoids N queries)
    cat_ids = {item.category_id for item in items if item.category_id}
    cat_names: dict[uuid.UUID, str] = {}
    for cid in cat_ids:
        cat = await cat_repo.get_by_id(auth_context.organization_id, cid)
        if cat:
            cat_names[cid] = cat.name

    return [
        ExpenseResponse(
            id=item.id,
            organization_id=item.organization_id,
            project_id=item.project_id,
            site_id=item.site_id,
            category_id=item.category_id,
            category_name=cat_names.get(item.category_id),
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
    repo = PostgresExpenseRepository(conn)
    expense = await repo.get_by_id(auth_context.organization_id, expense_id)
    if expense is None:
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
        account_id=account_id,
        account_name=account_name,
        custodian_name=custodian_name,
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
    repo = PostgresExpenseRepository(conn)
    expense = await repo.get_by_id(auth_context.organization_id, expense_id)
    if expense is None:
        raise HTTPException(status_code=404, detail="Expense not found")

    attachment_repo = PostgresExpenseAttachmentRepository(conn)
    attachments = await attachment_repo.list_for_expense(auth_context.organization_id, expense_id)
    return [
        ExpenseAttachmentResponse(
            id=a.id,
            expense_id=a.expense_id,
            attachment_type=a.attachment_type,
            url=assert_downloadable_url(
                await object_storage.generate_presigned_url(
                    a.media_object_key, expires_in_seconds=_ATTACHMENT_URL_TTL_SECONDS
                )
            ),
        )
        for a in attachments
    ]


@router.post("/{expense_id}/reverse")
async def reverse_expense(
    expense_id: uuid.UUID,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Reverse / void a confirmed expense, including reversing any ledger payments."""
    role_upper = (auth_context.role or "USER").upper()
    if role_upper not in ("ADMIN", "FINANCE", "USER", "OWNER", "SUPER_ADMIN"):
        raise HTTPException(
            status_code=403, detail="Not authorized to void expenses"
        )

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

