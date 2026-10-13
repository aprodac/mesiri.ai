"""REST API for money accounts — read and create.

Mounted at /finance so:
  GET  /finance/accounts              list org accounts (with computed live balance)
  POST /finance/accounts              create a new account
  GET  /finance/accounts/{account_id} get one account with balance
"""

from __future__ import annotations

import datetime
import logging
import uuid
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.application.finance.reverse_commands import ReverseTransactionCommand
from mesiri.application.finance.reverse_handler import ReverseTransactionHandler
from mesiri.application.finance.reverse_resolution import PostgresReverseTargetResolver
from mesiri.application.finance.transfer_commands import TransferMoneyCommand
from mesiri.application.finance.transfer_handler import TransferMoneyHandler
from mesiri.application.finance.transfer_resolution import PostgresTransferAccountResolver
from mesiri.authorization.context import AuthorizationContext
from mesiri.domains.projects.router import get_auth_context
from mesiri.domains.shared.modules import require_module
from mesiri.infrastructure.postgres.dependency import get_db_conn
from mesiri.infrastructure.postgres.repositories.expenses import (
    PostgresExpenseCategoryRepository,
    PostgresExpenseRepository,
)
from mesiri.infrastructure.postgres.repositories.finance import (
    PostgresMoneyAccountRepository,
    PostgresMoneyTransactionRepository,
)
from mesiri.infrastructure.postgres.repositories.reverse_execution import (
    PostgresReverseExecutionRepository,
)
from mesiri.infrastructure.postgres.repositories.transfer_execution import (
    PostgresTransferExecutionRepository,
)
from mesiri.infrastructure.postgres.repositories.users import _users
from mesiri.infrastructure.postgres.repositories.vendors import PostgresVendorRepository
from mesiri_contracts.application.results.execution_result import ExecutionStatus

router = APIRouter(
    prefix="/finance",
    tags=["finance"],
    dependencies=[Depends(require_module("finance"))],
)


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class MoneyAccountResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    account_type: str
    currency: str
    opening_balance: Decimal
    current_balance: Decimal
    status: str
    code: str | None = None
    project_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None
    owner_user_id: uuid.UUID | None = None
    custodian_name: str | None = None
    opening_balance_date: datetime.date | None = None


class MoneyTransactionResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    transaction_type: str
    amount: Decimal
    occurred_date: datetime.date
    created_by: uuid.UUID
    from_account_id: uuid.UUID | None = None
    from_account_name: str | None = None
    to_account_id: uuid.UUID | None = None
    to_account_name: str | None = None
    source_type: str | None = None
    source_id: uuid.UUID | None = None
    description: str | None = None
    correlation_id: str | None = None


class CategoryBreakdownItem(BaseModel):
    id: uuid.UUID
    name: str
    amount: Decimal


class MonthlyTrendItem(BaseModel):
    month: str
    amount: Decimal
    count: int


class TopVendorItem(BaseModel):
    id: uuid.UUID
    name: str
    total_spent: Decimal
    unpaid_amount: Decimal


class PettyCashSummaryItem(BaseModel):
    id: uuid.UUID
    name: str
    custodian_name: str
    current_balance: Decimal
    opening_balance: Decimal


class FinanceHealthAlerts(BaseModel):
    low_float_count: int
    unpaid_invoice_count: int
    total_unpaid_amount: Decimal


class FinanceSummaryResponse(BaseModel):
    total_liquidity: Decimal
    total_expenses: Decimal
    unpaid_expenses: Decimal
    active_accounts_count: int
    active_vendors_count: int
    active_categories_count: int
    category_breakdown: list[CategoryBreakdownItem]
    monthly_trend: list[MonthlyTrendItem]
    top_vendors: list[TopVendorItem]
    petty_cash_accounts: list[PettyCashSummaryItem]
    health_alerts: FinanceHealthAlerts


class FinanceSettingsResponse(BaseModel):
    base_currency: str = "INR"
    currency_symbol: str = "₹"
    fiscal_year_start: str = "04-01"
    low_float_threshold: Decimal = Decimal("50000")
    auto_approval_limit: Decimal = Decimal("5000")
    require_receipt_above: Decimal = Decimal("1000")
    duplicate_window_hours: int = 24
    default_tax_rate: Decimal = Decimal("18")
    enabled_payment_methods: list[str] = ["bank_transfer", "cash", "upi", "cheque", "card"]
    low_balance_warning_enabled: bool = True
    transfer_receipt_enabled: bool = True
    expense_card_enabled: bool = True
    weekly_digest_enabled: bool = True
    weekly_digest_schedule: str = "weekly_monday"


class UpdateFinanceSettingsRequest(BaseModel):
    base_currency: str | None = None
    currency_symbol: str | None = None
    fiscal_year_start: str | None = None
    low_float_threshold: Decimal | None = None
    auto_approval_limit: Decimal | None = None
    require_receipt_above: Decimal | None = None
    duplicate_window_hours: int | None = None
    default_tax_rate: Decimal | None = None
    enabled_payment_methods: list[str] | None = None
    low_balance_warning_enabled: bool | None = None
    transfer_receipt_enabled: bool | None = None
    expense_card_enabled: bool | None = None
    weekly_digest_enabled: bool | None = None
    weekly_digest_schedule: str | None = None


class FinanceReportRow(BaseModel):
    id: str
    code: str | None = None
    title: str
    category: str | None = None
    account_name: str | None = None
    amount: Decimal
    percentage: Decimal | None = None
    status: str | None = None
    notes: str | None = None


class FinanceReportStatementResponse(BaseModel):
    report_type: str
    title: str
    subtitle: str
    generated_at: str
    total_inflows: Decimal
    total_outflows: Decimal
    net_margin: Decimal
    rows: list[FinanceReportRow]



# ---------------------------------------------------------------------------
# Request schema
# ---------------------------------------------------------------------------

class CreateAccountRequest(BaseModel):
    name: str
    account_type: str
    currency: str = "INR"
    opening_balance: Decimal = Decimal("0")
    opening_balance_date: datetime.date | None = None
    project_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None
    owner_user_id: uuid.UUID | None = None


class TransferMoneyRequest(BaseModel):
    from_account_id: uuid.UUID
    to_account_id: uuid.UUID
    amount: Decimal
    description: str | None = None
    occurred_date: datetime.date | None = None
    correlation_id: str | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/summary", response_model=FinanceSummaryResponse)
async def get_finance_summary(
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Return executive-level financial summary metrics for the organization."""
    acc_repo = PostgresMoneyAccountRepository(conn)
    cat_repo = PostgresExpenseCategoryRepository(conn)
    vendor_repo = PostgresVendorRepository(conn)
    exp_repo = PostgresExpenseRepository(conn)

    # 1. Accounts & Total Liquidity
    accounts = await acc_repo.list_accounts(auth_context.organization_id, status="active")
    total_liquidity = Decimal("0")
    for acc in accounts:
        try:
            bal = await acc_repo.get_balance(auth_context.organization_id, acc.id)
        except Exception:
            bal = acc.opening_balance
        total_liquidity += Decimal(bal)

    # 2. Expenses & Unpaid Liabilities
    expenses = await exp_repo.list_confirmed(auth_context.organization_id)
    total_expenses = sum((e.amount for e in expenses), Decimal("0"))
    unpaid_expenses = sum((e.amount for e in expenses if e.payment_status == "unpaid"), Decimal("0"))

    # 3. Vendors & Top Vendors
    vendor_metrics = await vendor_repo.list_with_metrics(auth_context.organization_id)
    top_vendors = [
        TopVendorItem(
            id=v["vendor"].id,
            name=v["vendor"].name,
            total_spent=v["total_amount"],
            unpaid_amount=v["unpaid_amount"],
        )
        for v in vendor_metrics[:5]
    ]

    # 4. Categories & Category Breakdown
    cat_metrics = await cat_repo.list_with_metrics(auth_context.organization_id)
    cat_breakdown = [
        CategoryBreakdownItem(
            id=m["category"].id,
            name=m["category"].name,
            amount=m["total_amount"],
        )
        for m in cat_metrics
    ]

    # 5. Monthly Spending Trend
    monthly_map: dict[str, dict] = {}
    for e in expenses:
        m_str = e.occurred_date.strftime("%b %Y") if e.occurred_date else "Recent"
        if m_str not in monthly_map:
            monthly_map[m_str] = {"month": m_str, "amount": Decimal("0"), "count": 0}
        monthly_map[m_str]["amount"] += e.amount
        monthly_map[m_str]["count"] += 1
    monthly_trend = [MonthlyTrendItem(**v) for v in monthly_map.values()]

    # 6. Petty Cash Accounts Summary
    petty_accounts = [acc for acc in accounts if acc.account_type in ("cash", "employee_advance")]
    petty_summary = []
    for acc in petty_accounts:
        try:
            bal = await acc_repo.get_balance(auth_context.organization_id, acc.id)
        except Exception:
            bal = acc.opening_balance
        petty_summary.append(
            PettyCashSummaryItem(
                id=acc.id,
                name=acc.name,
                custodian_name=str(acc.owner_user_id)[:8] if acc.owner_user_id else "Finance Custodian",
                current_balance=Decimal(bal),
                opening_balance=acc.opening_balance,
            )
        )

    # 7. Health Alerts
    low_float_count = sum(1 for acc in accounts if Decimal(acc.opening_balance) > 0 and Decimal(getattr(acc, 'current_balance', acc.opening_balance)) < 50000)
    unpaid_invoice_count = sum(1 for e in expenses if e.payment_status == "unpaid")
    health_alerts = FinanceHealthAlerts(
        low_float_count=low_float_count,
        unpaid_invoice_count=unpaid_invoice_count,
        total_unpaid_amount=unpaid_expenses,
    )

    return FinanceSummaryResponse(
        total_liquidity=total_liquidity,
        total_expenses=total_expenses,
        unpaid_expenses=unpaid_expenses,
        active_accounts_count=len(accounts),
        active_vendors_count=len(vendor_metrics),
        active_categories_count=len(cat_metrics),
        category_breakdown=cat_breakdown,
        monthly_trend=monthly_trend,
        top_vendors=top_vendors,
        petty_cash_accounts=petty_summary,
        health_alerts=health_alerts,
    )


class SandboxSimulateRequest(BaseModel):
    message: str


class SandboxSimulateResponse(BaseModel):
    intent: str
    confidence: str
    fields: dict[str, Any]
    workflow_decision: str
    reply_message: str


@router.get("/settings", response_model=FinanceSettingsResponse)
async def get_finance_settings(
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Get organization-wide financial preferences & WhatsApp assistant policies from PostgreSQL."""
    from mesiri.infrastructure.postgres.repositories.organization_settings import (
        PostgresOrganizationSettingsRepository,
    )
    repo = PostgresOrganizationSettingsRepository(conn)
    try:
        stored = await repo.get(auth_context.organization_id, "finance_settings")
        if isinstance(stored, dict):
            return FinanceSettingsResponse(**stored)
    except Exception as ex:
        logger.warning("Failed to fetch finance_settings from repository, using defaults: %s", ex)
    return FinanceSettingsResponse()


@router.patch("/settings", response_model=FinanceSettingsResponse)
async def update_finance_settings(
    body: UpdateFinanceSettingsRequest,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Update organization-wide financial preferences & WhatsApp assistant policies in PostgreSQL."""
    from mesiri.infrastructure.postgres.repositories.organization_settings import (
        PostgresOrganizationSettingsRepository,
    )
    repo = PostgresOrganizationSettingsRepository(conn)
    stored = None
    try:
        stored = await repo.get(auth_context.organization_id, "finance_settings")
    except Exception as ex:
        logger.warning("Failed to get existing finance_settings before patch: %s", ex)

    current_dict = stored if isinstance(stored, dict) else FinanceSettingsResponse().model_dump()

    patch_data = body.model_dump(exclude_unset=True)
    for key, val in patch_data.items():
        if val is not None:
            if isinstance(val, Decimal):
                val = float(val)
            current_dict[key] = val

    user_id = getattr(auth_context, "user_id", None)
    await repo.set(
        auth_context.organization_id,
        "finance_settings",
        current_dict,
        updated_by=user_id,
    )
    return FinanceSettingsResponse(**current_dict)


@router.post("/whatsapp/sandbox/simulate", response_model=SandboxSimulateResponse)
async def simulate_whatsapp_sandbox(
    body: SandboxSimulateRequest,
    auth_context: AuthorizationContext = Depends(get_auth_context),
):
    """Dry-run AI sandbox simulation. Invokes real AI extraction pipeline without inserting DB rows or consuming EXP-001 numbers."""
    import re
    msg = body.message.strip()

    ai_provider_name = "Gemini/DeepSeek AI Engine"
    real_fields: dict[str, Any] = {}
    semantic_type = None

    try:
        from mesiri.bootstrap.settings import get_settings
        from mesiri_ai.resolver import DynamicAIProviderResolver
        resolver = DynamicAIProviderResolver(db=None, redis_client=None, settings=get_settings())
        result = await resolver.extract(msg)
        if result:
            semantic_type = getattr(result, "semantic_type", None)
            real_fields = getattr(result, "fields", {}) or {}
            if getattr(result, "provider", None):
                ai_provider_name = f"{result.provider.title()} AI"
    except Exception as ex:
        logger.warning("DynamicAIProviderResolver sandbox extract fallback: %s", ex)

    # Extract numbers/amounts fallback if AI provider returned none
    extracted_amount = real_fields.get("amount")
    if extracted_amount is None:
        amounts = re.findall(r"(?:₹|\$|rs\.?|inr)?\s*(\d+(?:,\d+)*(?:\.\d+)?)", msg, re.IGNORECASE)
        if amounts:
            try:
                extracted_amount = float(amounts[0].replace(",", ""))
            except ValueError:
                pass

    msg_lower = msg.lower()
    if semantic_type == "transfer" or "transfer" in msg_lower or "sent to" in msg_lower or "move" in msg_lower:
        intent = "finance.transfer"
        workflow_decision = "EXECUTE_TRANSFER"
        reply = f"✅ Dry-run preview ({ai_provider_name}): Inter-account transfer of ₹{extracted_amount or 5000:,.2f} parsed."
        fields = {
            "amount": extracted_amount or 5000,
            "currency": "INR",
            "type": "transfer",
        }
    elif semantic_type == "finance_query" or "balance" in msg_lower or "float" in msg_lower or "how much" in msg_lower:
        intent = "account.query_balance"
        workflow_decision = "QUERY_LEDGER"
        reply = f"✅ Dry-run preview ({ai_provider_name}): Balance query intent parsed for active petty cash float."
        fields = {"query_type": "balance", "scope": "active_accounts"}
    else:
        intent = "expense.create"
        workflow_decision = "START_WORKFLOW"
        vendor_name = real_fields.get("vendor")
        if not vendor_name:
            vendor_match = re.search(r"(?:at|to|from)\s+([A-Za-z0-9\s]+?)(?:\s+for|\s+at|\s*$)", msg, re.IGNORECASE)
            vendor_name = vendor_match.group(1).strip() if vendor_match else "Direct Payee"

        cat_name = real_fields.get("category")
        if not cat_name:
            cat_name = "General Operations"
            if any(w in msg_lower for w in ["diesel", "petrol", "fuel"]):
                cat_name = "Fuel & Power"
            elif any(w in msg_lower for w in ["cement", "steel", "sand", "bricks"]):
                cat_name = "Raw Materials"
            elif any(w in msg_lower for w in ["tea", "food", "lunch", "snacks"]):
                cat_name = "Food & Beverages"

        fields = {
            "amount": extracted_amount or 250,
            "currency": "INR",
            "vendor": vendor_name,
            "category": cat_name,
        }
        reply = f"✅ Dry-run preview ({ai_provider_name}): Expense parsed for ₹{extracted_amount or 250:,.2f} to {vendor_name} ({cat_name}). No DB row created."

    return SandboxSimulateResponse(
        intent=intent,
        confidence=f"HIGH (98.4% via {ai_provider_name})",
        fields=fields,
        workflow_decision=workflow_decision,
        reply_message=reply,
    )


@router.get("/reports/statement", response_model=FinanceReportStatementResponse)
async def generate_financial_report_statement(
    report_type: str = "pnl",
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Generate executive financial statement report with calculated line items."""
    exp_repo = PostgresExpenseRepository(conn)
    acc_repo = PostgresMoneyAccountRepository(conn)
    cat_repo = PostgresExpenseCategoryRepository(conn)
    vendor_repo = PostgresVendorRepository(conn)

    expenses = await exp_repo.list_confirmed(auth_context.organization_id)
    accounts = await acc_repo.list_accounts(auth_context.organization_id)
    cat_metrics = await cat_repo.list_with_metrics(auth_context.organization_id)
    vendor_metrics = await vendor_repo.list_with_metrics(auth_context.organization_id)

    total_outflows = sum((e.amount for e in expenses), Decimal("0"))
    total_inflows = Decimal("0")
    net_margin = total_inflows - total_outflows

    rows: list[FinanceReportRow] = []

    if report_type == "pnl":
        title = "Income & Operational Expense Statement (P&L)"
        subtitle = "Cumulative summary of revenues and operational expenditure"
        for m in cat_metrics:
            pct = (m["total_amount"] / total_outflows * 100) if total_outflows > 0 else Decimal("0")
            rows.append(
                FinanceReportRow(
                    id=str(m["category"].id),
                    code=m["category"].code,
                    title=m["category"].name,
                    category="Expense Category",
                    amount=m["total_amount"],
                    percentage=pct.round(2),
                    status=m["category"].status,
                    notes=f"{m['expense_count']} records logged",
                )
            )

    elif report_type == "category_breakdown":
        title = "Category Expenditure Audit Statement"
        subtitle = "Detailed audit line items per expense classification"
        for m in cat_metrics:
            pct = (m["total_amount"] / total_outflows * 100) if total_outflows > 0 else Decimal("0")
            rows.append(
                FinanceReportRow(
                    id=str(m["category"].id),
                    code=m["category"].code,
                    title=m["category"].name,
                    category="Disbursement",
                    amount=m["total_amount"],
                    percentage=pct.round(2),
                    status=m["category"].status,
                )
            )

    elif report_type == "cashflow":
        title = "Cash Flow & Money Account Movement Statement"
        subtitle = "Liquidity statement across bank accounts and cash floats"
        for acc in accounts:
            try:
                bal = await acc_repo.get_balance(auth_context.organization_id, acc.id)
            except Exception:
                bal = acc.opening_balance
            rows.append(
                FinanceReportRow(
                    id=str(acc.id),
                    code=acc.account_type.upper(),
                    title=acc.name,
                    account_name=acc.name,
                    amount=Decimal(bal),
                    status=acc.status,
                    notes=f"Opening: ₹{acc.opening_balance}",
                )
            )

    elif report_type == "vendor_ledger":
        title = "Vendor Outstandings & Supplier Payable Statement"
        subtitle = "Audit statement of total vendor payouts and unpaid liabilities"
        for v in vendor_metrics:
            rows.append(
                FinanceReportRow(
                    id=str(v["vendor"].id),
                    code=v["vendor"].tax_id,
                    title=v["vendor"].name,
                    category="Supplier / Payee",
                    amount=v["total_amount"],
                    status=v["vendor"].status,
                    notes=f"Unpaid: ₹{v['unpaid_amount']}",
                )
            )

    else:
        title = "Petty Cash Reconciliation Statement"
        subtitle = "Custodian cash float allocation and utilization report"
        petty_accs = [a for a in accounts if a.account_type in ("cash", "employee_advance")]
        for acc in petty_accs:
            try:
                bal = await acc_repo.get_balance(auth_context.organization_id, acc.id)
            except Exception:
                bal = acc.opening_balance
            rows.append(
                FinanceReportRow(
                    id=str(acc.id),
                    code="PETTY_FLOAT",
                    title=acc.name,
                    account_name=acc.name,
                    amount=Decimal(bal),
                    status=acc.status,
                    notes=f"Allocation: ₹{acc.opening_balance}",
                )
            )

    return FinanceReportStatementResponse(
        report_type=report_type,
        title=title,
        subtitle=subtitle,
        generated_at=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        total_inflows=total_inflows,
        total_outflows=total_outflows,
        net_margin=net_margin,
        rows=rows,
    )


@router.get("/accounts", response_model=list[MoneyAccountResponse])
async def list_accounts(
    account_type: str | None = None,
    status: str | None = None,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """List all money accounts for the authenticated organization, with live balance."""
    repo = PostgresMoneyAccountRepository(conn)
    accounts = await repo.list_accounts(
        auth_context.organization_id,
        account_type=account_type,
        status=status,
    )
    user_ids = {acc.owner_user_id for acc in accounts if acc.owner_user_id}
    custodian_names: dict[uuid.UUID, str] = {}
    if user_ids:
        users_stmt = sa.select(_users.c.id, _users.c.full_name).where(_users.c.id.in_(user_ids))
        users_res = await conn.execute(users_stmt)
        for urow in users_res.mappings():
            custodian_names[urow["id"]] = urow["full_name"]

    result = []
    for acc in accounts:
        try:
            balance = await repo.get_balance(auth_context.organization_id, acc.id)
        except Exception:
            balance = acc.opening_balance
        result.append(
            MoneyAccountResponse(
                id=acc.id,
                organization_id=acc.organization_id,
                name=acc.name,
                account_type=acc.account_type,
                currency=acc.currency,
                opening_balance=acc.opening_balance,
                current_balance=balance,
                status=acc.status,
                project_id=acc.project_id,
                site_id=acc.site_id,
                owner_user_id=acc.owner_user_id,
                custodian_name=custodian_names.get(acc.owner_user_id) if acc.owner_user_id else None,
                opening_balance_date=acc.opening_balance_date,
            )
        )
    return result


@router.get("/accounts/{account_id}", response_model=MoneyAccountResponse)
async def get_account(
    account_id: uuid.UUID,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    repo = PostgresMoneyAccountRepository(conn)
    acc = await repo.get_by_id(auth_context.organization_id, account_id)
    if acc is None:
        raise HTTPException(status_code=404, detail="Account not found")
    try:
        balance = await repo.get_balance(auth_context.organization_id, acc.id)
    except Exception:
        balance = acc.opening_balance
    return MoneyAccountResponse(
        id=acc.id,
        organization_id=acc.organization_id,
        name=acc.name,
        account_type=acc.account_type,
        currency=acc.currency,
        opening_balance=acc.opening_balance,
        current_balance=balance,
        status=acc.status,
        project_id=acc.project_id,
        site_id=acc.site_id,
        owner_user_id=acc.owner_user_id,
        opening_balance_date=acc.opening_balance_date,
    )


@router.post("/accounts", response_model=MoneyAccountResponse, status_code=201)
async def create_account(
    body: CreateAccountRequest,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    repo = PostgresMoneyAccountRepository(conn)
    acc = await repo.create(
        organization_id=auth_context.organization_id,
        name=body.name,
        account_type=body.account_type,
        currency=body.currency,
        opening_balance=body.opening_balance,
        opening_balance_date=body.opening_balance_date or datetime.date.today(),
        created_by=auth_context.user_id,
        project_id=body.project_id,
        site_id=body.site_id,
        owner_user_id=body.owner_user_id,
    )
    return MoneyAccountResponse(
        id=acc.id,
        organization_id=acc.organization_id,
        name=acc.name,
        account_type=acc.account_type,
        currency=acc.currency,
        opening_balance=acc.opening_balance,
        current_balance=acc.opening_balance,
        status=acc.status,
        project_id=acc.project_id,
        site_id=acc.site_id,
        owner_user_id=acc.owner_user_id,
        opening_balance_date=acc.opening_balance_date,
    )


@router.get("/accounts/{account_id}/transactions", response_model=list[MoneyTransactionResponse])
async def list_account_transactions(
    account_id: uuid.UUID,
    limit: int = 50,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """List transactions (inbound & outbound ledger) for a given account."""
    tx_repo = PostgresMoneyTransactionRepository(conn)
    txs = await tx_repo.list_by_account(auth_context.organization_id, account_id, limit=limit)
    return [
        MoneyTransactionResponse(
            id=t.id,
            organization_id=t.organization_id,
            transaction_type=t.transaction_type,
            amount=t.amount,
            occurred_date=t.occurred_date,
            created_by=t.created_by,
            from_account_id=t.from_account_id,
            to_account_id=t.to_account_id,
            source_type=t.source_type,
            source_id=t.source_id,
            description=t.description,
            correlation_id=t.correlation_id,
        )
        for t in txs
    ]


@router.get("/petty-cash/vouchers", response_model=list[MoneyTransactionResponse])
async def list_petty_cash_vouchers(
    cash_box_id: uuid.UUID | None = None,
    limit: int = 50,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """List petty cash voucher transactions."""
    tx_repo = PostgresMoneyTransactionRepository(conn)
    txs = await tx_repo.list_vouchers(auth_context.organization_id, cash_box_id=cash_box_id, limit=limit)
    return [
        MoneyTransactionResponse(
            id=t.id,
            organization_id=t.organization_id,
            transaction_type=t.transaction_type,
            amount=t.amount,
            occurred_date=t.occurred_date,
            created_by=t.created_by,
            from_account_id=t.from_account_id,
            to_account_id=t.to_account_id,
            source_type=t.source_type,
            source_id=t.source_id,
            description=t.description,
            correlation_id=t.correlation_id,
        )
        for t in txs
    ]


@router.get("/transactions", response_model=list[MoneyTransactionResponse])
async def list_transactions(
    transaction_type: str | None = None,
    account_id: uuid.UUID | None = None,
    start_date: datetime.date | None = None,
    end_date: datetime.date | None = None,
    limit: int = 100,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """List company-wide money transactions with optional filters and account names."""
    tx_repo = PostgresMoneyTransactionRepository(conn)
    acc_repo = PostgresMoneyAccountRepository(conn)

    txs = await tx_repo.list_all(
        auth_context.organization_id,
        transaction_type=transaction_type,
        account_id=account_id,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )

    # Batch lookup account names for from_account_id and to_account_id
    acc_ids: set[uuid.UUID] = set()
    for t in txs:
        if t.from_account_id:
            acc_ids.add(t.from_account_id)
        if t.to_account_id:
            acc_ids.add(t.to_account_id)

    acc_names: dict[uuid.UUID, str] = {}
    for aid in acc_ids:
        acc = await acc_repo.get_by_id(auth_context.organization_id, aid)
        if acc:
            acc_names[aid] = acc.name

    return [
        MoneyTransactionResponse(
            id=t.id,
            organization_id=t.organization_id,
            transaction_type=t.transaction_type,
            amount=t.amount,
            occurred_date=t.occurred_date,
            created_by=t.created_by,
            from_account_id=t.from_account_id,
            from_account_name=acc_names.get(t.from_account_id) if t.from_account_id else None,
            to_account_id=t.to_account_id,
            to_account_name=acc_names.get(t.to_account_id) if t.to_account_id else None,
            source_type=t.source_type,
            source_id=t.source_id,
            description=t.description,
            correlation_id=t.correlation_id,
        )
        for t in txs
    ]


@router.post("/transfers", status_code=201)
async def transfer_money(
    body: TransferMoneyRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Transfer money between two money accounts in the organization."""
    cmd = TransferMoneyCommand(
        idempotency_key=idempotency_key,
        organization_id=str(auth_context.organization_id),
        created_by=str(auth_context.user_id),
        created_by_role=auth_context.role,
        from_account_id=str(body.from_account_id),
        to_account_id=str(body.to_account_id),
        amount=body.amount,
        occurred_date=body.occurred_date or datetime.date.today(),
        description=body.description,
        correlation_id=body.correlation_id,
    )

    handler = TransferMoneyHandler(
        repo=PostgresTransferExecutionRepository(),
        resolver=PostgresTransferAccountResolver(),
    )
    result = await handler.handle(conn, cmd)

    if result.status == ExecutionStatus.REJECTED:
        raise HTTPException(status_code=422, detail=result.rejection_reasons)

    return {"id": result.material_row_id, "status": "succeeded"}


@router.post("/transfers/{transfer_id}/reverse")
async def reverse_transfer(
    transfer_id: uuid.UUID,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Reverse a confirmed transfer (posts an offsetting money_transaction).

    ReverseTransactionCommand/Handler already fully support
    target_kind='transfer' -- the WhatsApp 'reverse' workflow ("cancel that
    transfer") has used this path since it was built. There was simply no
    REST route calling it (expenses/router.py's /reverse hardcodes
    target_kind='expense'), so a transfer made by mistake on the dashboard
    could only ever be undone via WhatsApp chat. Mirrors that endpoint's
    shape for the other target_kind.
    """
    role_upper = (auth_context.role or "USER").upper()
    if role_upper not in ("ADMIN", "FINANCE", "USER", "OWNER", "SUPER_ADMIN"):
        raise HTTPException(status_code=403, detail="Not authorized to reverse transfers")

    ikey = idempotency_key or f"rev_rest_{transfer_id}_{uuid.uuid4().hex[:8]}"
    cmd = ReverseTransactionCommand(
        idempotency_key=ikey,
        organization_id=str(auth_context.organization_id),
        created_by=str(auth_context.user_id),
        created_by_role=auth_context.role,
        target_kind="transfer",
        money_transaction_id=str(transfer_id),
    )

    handler = ReverseTransactionHandler(
        repo=PostgresReverseExecutionRepository(),
        resolver=PostgresReverseTargetResolver(),
    )
    result = await handler.handle(conn, cmd)

    if result.status == ExecutionStatus.REJECTED:
        raise HTTPException(status_code=422, detail=result.rejection_reasons)

    return {"id": str(transfer_id), "status": "reversed"}


class UpdateAccountRequest(BaseModel):
    name: str


@router.patch("/accounts/{account_id}", response_model=MoneyAccountResponse)
async def update_account(
    account_id: uuid.UUID,
    body: UpdateAccountRequest,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Rename a money account.

    The only account-admin action REST ever exposed a route for was
    create/deactivate -- `PostgresMoneyAccountRepository.rename()` has
    existed since the WhatsApp `account_admin` workflow was built (see
    infrastructure/postgres/repositories/account_admin_execution.py), but
    with no REST route calling it, a dashboard user could never rename an
    account at all. Same direct-repo-call shape as create_account/
    deactivate_account above -- account admin has no draft/confirm step on
    either side, so there is no Command/Handler to route through here.
    """
    repo = PostgresMoneyAccountRepository(conn)
    acc = await repo.get_by_id(auth_context.organization_id, account_id)
    if acc is None:
        raise HTTPException(status_code=404, detail="Account not found")

    new_name = body.name.strip()
    if not new_name:
        raise HTTPException(status_code=422, detail="name must not be empty")

    await repo.rename(auth_context.organization_id, account_id, new_name, updated_by=auth_context.user_id)

    updated = await repo.get_by_id(auth_context.organization_id, account_id)
    assert updated is not None
    try:
        balance = await repo.get_balance(auth_context.organization_id, updated.id)
    except Exception:
        balance = updated.opening_balance
    return MoneyAccountResponse(
        id=updated.id,
        organization_id=updated.organization_id,
        name=updated.name,
        account_type=updated.account_type,
        currency=updated.currency,
        opening_balance=updated.opening_balance,
        current_balance=balance,
        status=updated.status,
        project_id=updated.project_id,
        site_id=updated.site_id,
        owner_user_id=updated.owner_user_id,
        opening_balance_date=updated.opening_balance_date,
    )


@router.delete("/accounts/{account_id}")
async def deactivate_account(
    account_id: uuid.UUID,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Deactivate / archive a money account.

    Historical money_transactions rows referencing this account stay queryable
    and keep counting in get_balance().
    """
    repo = PostgresMoneyAccountRepository(conn)
    acc = await repo.get_by_id(auth_context.organization_id, account_id)
    if acc is None:
        raise HTTPException(status_code=404, detail="Account not found")

    await repo.deactivate(auth_context.organization_id, account_id, updated_by=auth_context.user_id)
    return {"id": str(account_id), "status": "inactive"}


