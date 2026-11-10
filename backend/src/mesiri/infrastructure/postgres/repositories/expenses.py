from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.domains.expenses.entities import (
    Expense,
    ExpenseAttachment,
    ExpenseCategory,
    ExpensePayment,
)
from mesiri.infrastructure.postgres.repositories.finance import PostgresMoneyTransactionRepository

_expense_categories = sa.Table(
    "expense_categories",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True)),
    sa.Column("organization_id", sa.UUID(as_uuid=True)),
    sa.Column("name", sa.String),
    sa.Column("code", sa.String),
    sa.Column("parent_category_id", sa.UUID(as_uuid=True)),
    sa.Column("status", sa.String),
    sa.Column("created_at", sa.DateTime(timezone=True)),
    sa.Column("created_by", sa.UUID(as_uuid=True)),
    sa.Column("updated_at", sa.DateTime(timezone=True)),
    sa.Column("updated_by", sa.UUID(as_uuid=True)),
)

_expenses = sa.Table(
    "expenses",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True)),
    sa.Column("organization_id", sa.UUID(as_uuid=True)),
    sa.Column("project_id", sa.UUID(as_uuid=True)),
    sa.Column("site_id", sa.UUID(as_uuid=True)),
    sa.Column("category_id", sa.UUID(as_uuid=True)),
    sa.Column("vendor_id", sa.UUID(as_uuid=True)),
    sa.Column("expense_number", sa.String),
    sa.Column("amount", sa.Numeric),
    sa.Column("currency", sa.String),
    sa.Column("description", sa.String),
    sa.Column("occurred_date", sa.Date),
    sa.Column("occurred_time", sa.Time),
    sa.Column("workflow_status", sa.String),
    sa.Column("payment_status", sa.String),
    sa.Column("source", sa.String),
    sa.Column("source_message_id", sa.String),
    sa.Column("correlation_id", sa.String),
    sa.Column("tax_rate", sa.Numeric),
    sa.Column("tax_amount", sa.Numeric),
    sa.Column("is_tax_inclusive", sa.Boolean),
    sa.Column("created_at", sa.DateTime(timezone=True)),
    sa.Column("created_by", sa.UUID(as_uuid=True)),
    sa.Column("updated_at", sa.DateTime(timezone=True)),
    sa.Column("updated_by", sa.UUID(as_uuid=True)),
)

_expense_attachments = sa.Table(
    "expense_attachments",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True)),
    sa.Column("expense_id", sa.UUID(as_uuid=True)),
    sa.Column("media_object_key", sa.String),
    sa.Column("attachment_type", sa.String),
    sa.Column("created_at", sa.DateTime(timezone=True)),
    sa.Column("created_by", sa.UUID(as_uuid=True)),
)

_expense_payments = sa.Table(
    "expense_payments",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True)),
    sa.Column("organization_id", sa.UUID(as_uuid=True)),
    sa.Column("expense_id", sa.UUID(as_uuid=True)),
    sa.Column("account_id", sa.UUID(as_uuid=True)),
    sa.Column("amount", sa.Numeric),
    sa.Column("payment_method", sa.String),
    sa.Column("reference_number", sa.String),
    sa.Column("paid_date", sa.Date),
    sa.Column("paid_time", sa.Time),
    sa.Column("status", sa.String),
    sa.Column("created_at", sa.DateTime(timezone=True)),
    sa.Column("created_by", sa.UUID(as_uuid=True)),
    sa.Column("updated_at", sa.DateTime(timezone=True)),
    sa.Column("updated_by", sa.UUID(as_uuid=True)),
    sa.Column("vendor_id", sa.UUID(as_uuid=True)),
    sa.Column("project_id", sa.UUID(as_uuid=True)),
    sa.Column("advance_id", sa.UUID(as_uuid=True)),
)

_budgets = sa.Table(
    "budgets",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True)),
    sa.Column("organization_id", sa.UUID(as_uuid=True)),
    sa.Column("project_id", sa.UUID(as_uuid=True)),
    sa.Column("name", sa.String),
    sa.Column("amount", sa.Numeric),
    sa.Column("currency", sa.String),
    sa.Column("start_date", sa.Date),
    sa.Column("end_date", sa.Date),
    sa.Column("status", sa.String),
    sa.Column("created_at", sa.DateTime(timezone=True)),
    sa.Column("created_by", sa.UUID(as_uuid=True)),
    sa.Column("updated_at", sa.DateTime(timezone=True)),
    sa.Column("updated_by", sa.UUID(as_uuid=True)),
)

_budget_allocations = sa.Table(
    "budget_allocations",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True)),
    sa.Column("budget_id", sa.UUID(as_uuid=True)),
    sa.Column("category_id", sa.UUID(as_uuid=True)),
    sa.Column("amount", sa.Numeric),
    sa.Column("created_at", sa.DateTime(timezone=True)),
    sa.Column("created_by", sa.UUID(as_uuid=True)),
    sa.Column("updated_at", sa.DateTime(timezone=True)),
    sa.Column("updated_by", sa.UUID(as_uuid=True)),
)


def _row_to_category(row) -> ExpenseCategory:
    return ExpenseCategory(
        id=row.id,
        organization_id=row.organization_id,
        name=row.name,
        status=row.status,
        code=row.code,
        parent_category_id=row.parent_category_id,
    )


def _row_to_expense(row) -> Expense:
    return Expense(
        id=row.id,
        organization_id=row.organization_id,
        project_id=row.project_id,
        category_id=row.category_id,
        vendor_id=row.vendor_id,
        amount=row.amount,
        currency=row.currency,
        occurred_date=row.occurred_date,
        workflow_status=row.workflow_status,
        payment_status=row.payment_status,
        source=row.source,
        created_by=row.created_by,
        site_id=row.site_id,
        expense_number=row.expense_number,
        description=row.description,
        occurred_time=row.occurred_time,
        source_message_id=row.source_message_id,
        correlation_id=row.correlation_id,
        tax_rate=getattr(row, "tax_rate", None),
        tax_amount=getattr(row, "tax_amount", None),
        is_tax_inclusive=getattr(row, "is_tax_inclusive", True) if getattr(row, "is_tax_inclusive", None) is not None else True,
    )


def _row_to_payment(row) -> ExpensePayment:
    return ExpensePayment(
        id=row.id,
        organization_id=row.organization_id,
        expense_id=row.expense_id,
        account_id=row.account_id,
        amount=row.amount,
        paid_date=row.paid_date,
        status=row.status,
        created_by=row.created_by,
        payment_method=row.payment_method,
        reference_number=row.reference_number,
        paid_time=row.paid_time,
        vendor_id=row.get("vendor_id"),
        project_id=row.get("project_id"),
        advance_id=row.get("advance_id"),
    )


# Construction-generic starter set, seeded once per org the first time its
# category list is read empty (see PostgresExpenseCategoryRepository.
# seed_defaults_if_empty). Deliberately small and broad -- an admin can
# rename/deactivate/add freely afterward via the Categories page; this only
# exists so day-one AI extraction and the dashboard's category dropdown
# aren't staring at an empty list.
_DEFAULT_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("Materials", "MAT"),
    ("Labour", "LAB"),
    ("Fuel & Transport", "FUEL"),
    ("Equipment Rental", "EQUIP"),
    ("Site Utilities", "UTIL"),
    ("Miscellaneous", "MISC"),
)


class PostgresExpenseCategoryRepository:
    def __init__(self, conn: AsyncConnection):
        self.conn = conn

    async def list_active(self, organization_id: uuid.UUID) -> list[ExpenseCategory]:
        stmt = (
            sa.select(_expense_categories)
            .where(
                _expense_categories.c.organization_id == organization_id,
                _expense_categories.c.status == "active",
            )
            .order_by(_expense_categories.c.name)
        )
        res = await self.conn.execute(stmt)
        return [_row_to_category(r) for r in res.mappings().all()]

    async def get_by_id(
        self, organization_id: uuid.UUID, category_id: uuid.UUID
    ) -> ExpenseCategory | None:
        stmt = sa.select(_expense_categories).where(
            _expense_categories.c.id == category_id,
            _expense_categories.c.organization_id == organization_id,
        )
        res = await self.conn.execute(stmt)
        row = res.mappings().first()
        return _row_to_category(row) if row else None

    async def find_by_name_exact_active(
        self, organization_id: uuid.UUID, name: str
    ) -> ExpenseCategory | None:
        """Case-insensitive exact match against active categories only."""
        stmt = sa.select(_expense_categories).where(
            _expense_categories.c.organization_id == organization_id,
            _expense_categories.c.status == "active",
            sa.func.lower(_expense_categories.c.name) == name.strip().lower(),
        )
        res = await self.conn.execute(stmt)
        row = res.mappings().first()
        return _row_to_category(row) if row else None

    async def get_or_create_default(
        self, organization_id: uuid.UUID, *, created_by: uuid.UUID
    ) -> ExpenseCategory:
        """The org-scoped "Uncategorized" bucket, created on first use.

        Mirrors migration 0310's `units_of_measure` "unspecified" fallback:
        category is documented as optional on the extraction side, so an
        expense with no category shouldn't be rejected outright — it lands
        here instead. ON CONFLICT DO NOTHING on the (organization_id, name)
        unique constraint makes concurrent first-use races safe.
        """
        existing = await self.find_by_name_exact_active(organization_id, "Uncategorized")
        if existing is not None:
            return existing

        await self.conn.execute(
            sa.text(
                "INSERT INTO expense_categories (id, organization_id, name, status, created_by) "
                "VALUES (:id, :organization_id, 'Uncategorized', 'active', :created_by) "
                "ON CONFLICT (organization_id, name) DO NOTHING"
            ),
            {"id": uuid.uuid4(), "organization_id": organization_id, "created_by": created_by},
        )
        category = await self.find_by_name_exact_active(organization_id, "Uncategorized")
        assert category is not None
        return category

    async def seed_defaults_if_empty(
        self, organization_id: uuid.UUID, *, created_by: uuid.UUID
    ) -> list[ExpenseCategory]:
        """A brand-new org otherwise starts with zero categories -- every
        expense falls through to `get_or_create_default`'s single
        "Uncategorized" bucket until someone remembers to visit the
        Categories page, which defeats category-aware AI extraction from
        message one (see understanding/pipeline.py's `expense_categories`
        nudge). Seeds a small construction-generic starter set the first
        time categories are read for an org -- mirrors
        runtime/money_account_query.py's default-account bootstrap (same
        lazy, create-on-first-use, ON-CONFLICT-safe shape), not an
        org-creation hook, so this stays free of any org-lifecycle wiring.
        An org with at least one active category already is left
        untouched -- this only ever fires once, for a genuinely empty list.
        """
        existing = await self.list_active(organization_id)
        if existing:
            return existing
        for name, code in _DEFAULT_CATEGORIES:
            await self.conn.execute(
                sa.text(
                    "INSERT INTO expense_categories (id, organization_id, name, code, status, created_by) "
                    "VALUES (:id, :organization_id, :name, :code, 'active', :created_by) "
                    "ON CONFLICT (organization_id, name) DO NOTHING"
                ),
                {
                    "id": uuid.uuid4(),
                    "organization_id": organization_id,
                    "name": name,
                    "code": code,
                    "created_by": created_by,
                },
            )
        return await self.list_active(organization_id)

    async def list_with_metrics(self, organization_id: uuid.UUID, project_id: uuid.UUID | None = None) -> list[dict]:
        """List categories for org along with expense count and total spend."""
        exp_count = sa.func.count(_expenses.c.id).label("expense_count")
        exp_sum = sa.func.coalesce(sa.func.sum(_expenses.c.amount), 0).label("total_amount")

        stmt = (
            sa.select(
                _expense_categories,
                exp_count,
                exp_sum,
            )
            .select_from(
                _expense_categories.outerjoin(
                    _expenses,
                    sa.and_(
                        _expenses.c.category_id == _expense_categories.c.id,
                        _expenses.c.workflow_status == "confirmed",
                        # SCP-08: one project's spending (None: the whole company, as before).
                        sa.true() if project_id is None else _expenses.c.project_id == project_id,
                    ),
                )
            )
            .where(_expense_categories.c.organization_id == organization_id)
            .group_by(_expense_categories.c.id)
            .order_by(_expense_categories.c.name)
        )
        res = await self.conn.execute(stmt)
        results = []
        for row in res.mappings().all():
            cat = _row_to_category(row)
            results.append({
                "category": cat,
                "expense_count": row.expense_count,
                "total_amount": Decimal(row.total_amount),
            })
        return results

    async def create(
        self,
        organization_id: uuid.UUID,
        name: str,
        *,
        code: str | None = None,
        parent_category_id: uuid.UUID | None = None,
        created_by: uuid.UUID,
    ) -> ExpenseCategory:
        category_code = code.strip().upper() if code else None
        if not category_code:
            seq_res = (
                await self.conn.execute(
                    sa.text(
                        """
                        SELECT COALESCE(MAX(
                            CAST(SUBSTRING(code FROM 'CAT-([0-9]+)') AS INTEGER)
                        ), 0) + 1 AS next_seq
                        FROM expense_categories
                        WHERE organization_id = :org_id
                        """
                    ),
                    {"org_id": organization_id},
                )
            ).mappings().first()
            next_seq = seq_res["next_seq"] if seq_res else 1
            category_code = f"CAT-{next_seq:03d}"

        new_id = uuid.uuid4()
        await self.conn.execute(
            sa.insert(_expense_categories).values(
                id=new_id,
                organization_id=organization_id,
                name=name.strip(),
                code=category_code,
                parent_category_id=parent_category_id,
                status="active",
                created_by=created_by,
            )
        )
        return await self.get_by_id(organization_id, new_id)  # type: ignore[return-value]

    async def update(
        self,
        organization_id: uuid.UUID,
        category_id: uuid.UUID,
        *,
        name: str | None = None,
        code: str | None = None,
        status: str | None = None,
        updated_by: uuid.UUID,
    ) -> ExpenseCategory | None:
        values: dict = {"updated_by": updated_by, "updated_at": sa.func.now()}
        if name is not None:
            values["name"] = name.strip()
        if code is not None:
            values["code"] = code.strip().upper() if code else None
        if status is not None:
            values["status"] = status.strip().lower()

        await self.conn.execute(
            sa.update(_expense_categories)
            .where(
                _expense_categories.c.id == category_id,
                _expense_categories.c.organization_id == organization_id,
            )
            .values(**values)
        )
        return await self.get_by_id(organization_id, category_id)



class PostgresExpenseRepository:
    def __init__(self, conn: AsyncConnection):
        self.conn = conn

    async def get_by_id(self, organization_id: uuid.UUID, expense_id: uuid.UUID) -> Expense | None:
        stmt = sa.select(_expenses).where(
            _expenses.c.id == expense_id,
            _expenses.c.organization_id == organization_id,
        )
        res = await self.conn.execute(stmt)
        row = res.mappings().first()
        return _row_to_expense(row) if row else None

    async def find_latest_confirmed(
        self,
        organization_id: uuid.UUID,
        *,
        project_id: uuid.UUID | None = None,
        site_id: uuid.UUID | None = None,
    ) -> Expense | None:
        """Finance Module Slice 7: the most recently recorded confirmed
        (non-voided) expense -- candidate for "reverse my last expense"."""
        where_clauses = [
            _expenses.c.organization_id == organization_id,
            _expenses.c.workflow_status == "confirmed",
        ]
        if project_id is not None:
            where_clauses.append(_expenses.c.project_id == project_id)
        if site_id is not None:
            where_clauses.append(_expenses.c.site_id == site_id)
        stmt = (
            sa.select(_expenses)
            .where(*where_clauses)
            .order_by(_expenses.c.created_at.desc())
            .limit(1)
        )
        row = (await self.conn.execute(stmt)).mappings().first()
        return _row_to_expense(row) if row else None

    async def find_potential_duplicate(
        self,
        organization_id: uuid.UUID,
        *,
        amount: Decimal,
        occurred_date: datetime.date,
        project_id: uuid.UUID | None = None,
        vendor_id: uuid.UUID | None = None,
        category_id: uuid.UUID | None = None,
    ) -> Expense | None:
        """Finance Module Slice 8: a confirmed expense already recorded for
        the same amount and date, matched additionally by vendor (preferred,
        Slice 4) or category (fallback) -- whichever signal the caller
        resolved. Neither given means there is no signal beyond amount+date
        alone, too weak on its own, so this returns None without querying."""
        if vendor_id is None and category_id is None:
            return None
        where_clauses = [
            _expenses.c.organization_id == organization_id,
            _expenses.c.workflow_status == "confirmed",
            _expenses.c.amount == amount,
            _expenses.c.occurred_date == occurred_date,
        ]
        if project_id is not None:
            where_clauses.append(_expenses.c.project_id == project_id)
        if vendor_id is not None:
            where_clauses.append(_expenses.c.vendor_id == vendor_id)
        else:
            where_clauses.append(_expenses.c.category_id == category_id)
        stmt = (
            sa.select(_expenses)
            .where(*where_clauses)
            .order_by(_expenses.c.created_at.desc())
            .limit(1)
        )
        row = (await self.conn.execute(stmt)).mappings().first()
        return _row_to_expense(row) if row else None

    async def list_confirmed(
        self,
        organization_id: uuid.UUID,
        *,
        project_id: uuid.UUID | None = None,
        site_id: uuid.UUID | None = None,
        start_date: datetime.date | None = None,
        end_date: datetime.date | None = None,
        category_id: uuid.UUID | None = None,
        vendor_id: uuid.UUID | None = None,
        without_attachment: bool = False,
    ) -> list[Expense]:
        """Confirmed (non-voided, non-draft) expenses matching the given
        filters -- read path for Finance Module Slice 2's expense query
        workflow. All filters are optional and additive (AND'd together)."""
        where_clauses = [
            _expenses.c.organization_id == organization_id,
            _expenses.c.workflow_status == "confirmed",
        ]
        if project_id is not None:
            where_clauses.append(_expenses.c.project_id == project_id)
        if site_id is not None:
            where_clauses.append(_expenses.c.site_id == site_id)
        if start_date is not None:
            where_clauses.append(_expenses.c.occurred_date >= start_date)
        if end_date is not None:
            where_clauses.append(_expenses.c.occurred_date <= end_date)
        if category_id is not None:
            where_clauses.append(_expenses.c.category_id == category_id)
        if vendor_id is not None:
            where_clauses.append(_expenses.c.vendor_id == vendor_id)
        if without_attachment:
            where_clauses.append(
                ~sa.exists(
                    sa.select(1).where(_expense_attachments.c.expense_id == _expenses.c.id)
                )
            )

        stmt = (
            sa.select(_expenses)
            .where(*where_clauses)
            .order_by(_expenses.c.occurred_date.desc())
        )
        res = await self.conn.execute(stmt)
        return [_row_to_expense(r) for r in res.mappings().all()]


@dataclass(frozen=True, slots=True)
class ExpenseAttachmentWithContext:
    """An attachment plus enough of its parent expense to render a gallery
    thumbnail's caption -- a read-projection, not a domain entity (nothing
    else needs this shape), so it lives next to the query that builds it
    rather than in domains/expenses/entities.py."""

    id: uuid.UUID
    expense_id: uuid.UUID
    media_object_key: str
    attachment_type: str
    created_at: datetime.datetime | None
    amount: Decimal
    description: str | None
    occurred_date: datetime.date
    project_id: uuid.UUID
    category_id: uuid.UUID | None
    vendor_id: uuid.UUID | None


class PostgresExpenseAttachmentRepository:
    def __init__(self, conn: AsyncConnection):
        self.conn = conn

    async def create(
        self,
        *,
        expense_id: uuid.UUID,
        media_object_key: str,
        attachment_type: str,
        created_by: uuid.UUID,
    ) -> ExpenseAttachment:
        """Append-only evidence row -- no organization_id of its own (scoped
        via expense_id, matching migration 0330's shape) and no
        updated_at/updated_by, since an attachment is never edited, only
        added (see AttachmentType for the allowed values)."""
        new_id = uuid.uuid4()
        await self.conn.execute(
            sa.insert(_expense_attachments).values(
                id=new_id,
                expense_id=expense_id,
                media_object_key=media_object_key,
                attachment_type=attachment_type,
                created_by=created_by,
            )
        )
        return ExpenseAttachment(
            id=new_id,
            expense_id=expense_id,
            media_object_key=media_object_key,
            attachment_type=attachment_type,
            created_by=created_by,
        )

    async def list_for_expense(
        self, organization_id: uuid.UUID, expense_id: uuid.UUID
    ) -> list[ExpenseAttachment]:
        stmt = (
            sa.select(_expense_attachments)
            .select_from(_expense_attachments.join(_expenses, _expenses.c.id == _expense_attachments.c.expense_id))
            .where(
                _expense_attachments.c.expense_id == expense_id,
                _expenses.c.organization_id == organization_id,
            )
        )
        res = await self.conn.execute(stmt)
        return [
            ExpenseAttachment(
                id=r.id,
                expense_id=r.expense_id,
                media_object_key=r.media_object_key,
                attachment_type=r.attachment_type,
                created_by=r.created_by,
            )
            for r in res.mappings().all()
        ]

    async def list_for_organization(
        self,
        organization_id: uuid.UUID,
        *,
        project_id: uuid.UUID | None = None,
        site_id: uuid.UUID | None = None,
        start_date: datetime.date | None = None,
        end_date: datetime.date | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ExpenseAttachmentWithContext]:
        """All attachments across the org, newest first -- the "see every
        receipt together" gallery view. Joined through expenses (an
        attachment carries no organization_id of its own) both for tenant
        scoping and to bring back enough of the parent expense to caption
        each thumbnail without a second round trip per row."""
        where_clauses = [_expenses.c.organization_id == organization_id]
        if project_id is not None:
            where_clauses.append(_expenses.c.project_id == project_id)
        if site_id is not None:
            where_clauses.append(_expenses.c.site_id == site_id)
        if start_date is not None:
            where_clauses.append(_expenses.c.occurred_date >= start_date)
        if end_date is not None:
            where_clauses.append(_expenses.c.occurred_date <= end_date)

        stmt = (
            sa.select(
                _expense_attachments.c.id,
                _expense_attachments.c.expense_id,
                _expense_attachments.c.media_object_key,
                _expense_attachments.c.attachment_type,
                _expense_attachments.c.created_at,
                _expenses.c.amount,
                _expenses.c.description,
                _expenses.c.occurred_date,
                _expenses.c.project_id,
                _expenses.c.category_id,
                _expenses.c.vendor_id,
            )
            .select_from(
                _expense_attachments.join(_expenses, _expenses.c.id == _expense_attachments.c.expense_id)
            )
            .where(*where_clauses)
            .order_by(_expense_attachments.c.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        res = await self.conn.execute(stmt)
        return [
            ExpenseAttachmentWithContext(
                id=r.id,
                expense_id=r.expense_id,
                media_object_key=r.media_object_key,
                attachment_type=r.attachment_type,
                created_at=r.created_at,
                amount=r.amount,
                description=r.description,
                occurred_date=r.occurred_date,
                project_id=r.project_id,
                category_id=r.category_id,
                vendor_id=r.vendor_id,
            )
            for r in res.mappings().all()
        ]


class PostgresExpensePaymentRepository:
    """Applies the confirmed-payment domain rules: overpayment rejection,
    atomic payment + money_transaction creation, and payment_status recompute.
    """

    def __init__(self, conn: AsyncConnection):
        self.conn = conn
        self._transactions = PostgresMoneyTransactionRepository(conn)

    async def list_for_expense(
        self, organization_id: uuid.UUID, expense_id: uuid.UUID
    ) -> list[ExpensePayment]:
        stmt = sa.select(_expense_payments).where(
            _expense_payments.c.expense_id == expense_id,
            _expense_payments.c.organization_id == organization_id,
        )
        res = await self.conn.execute(stmt)
        return [_row_to_payment(r) for r in res.mappings().all()]

    async def _confirmed_paid_total(self, expense_id: uuid.UUID) -> Decimal:
        stmt = sa.select(sa.func.coalesce(sa.func.sum(_expense_payments.c.amount), 0)).where(
            _expense_payments.c.expense_id == expense_id,
            _expense_payments.c.status == "confirmed",
        )
        return Decimal((await self.conn.execute(stmt)).scalar_one())

    async def _recompute_payment_status(self, organization_id: uuid.UUID, expense_id: uuid.UUID) -> None:
        expense_row = (
            await self.conn.execute(
                sa.select(_expenses.c.amount, _expenses.c.payment_status).where(
                    _expenses.c.id == expense_id, _expenses.c.organization_id == organization_id
                ).with_for_update()  # two payments at once must not both fit under the amount
            )
        ).mappings().one()
        paid_total = await self._confirmed_paid_total(expense_id)
        if expense_row["payment_status"] in ("reimbursable", "reimbursed"):
            # Paid by a member of staff from their own pocket: the supplier was paid; payments here repay the staff
            # member. Until repaid in full it stays owed to them (8 Nov 2026: a part repayment made it
            # "partially paid", which read as owed to the supplier).
            status = "reimbursed" if paid_total >= Decimal(expense_row["amount"]) else "reimbursable"
        elif paid_total <= 0:
            status = "unpaid"
        elif paid_total < Decimal(expense_row["amount"]):
            status = "partially_paid"
        else:
            status = "paid"
        await self.conn.execute(
            sa.update(_expenses)
            .where(_expenses.c.id == expense_id, _expenses.c.organization_id == organization_id)
            .values(payment_status=status)
        )

    async def record_payment(
        self,
        *,
        organization_id: uuid.UUID,
        expense_id: uuid.UUID,
        account_id: uuid.UUID,
        amount: Decimal,
        paid_date: datetime.date,
        created_by: uuid.UUID,
        payment_method: str | None = None,
        reference_number: str | None = None,
    ) -> ExpensePayment:
        expense_row = (
            await self.conn.execute(
                sa.select(_expenses.c.amount).where(
                    _expenses.c.id == expense_id, _expenses.c.organization_id == organization_id
                ).with_for_update()  # two payments at once must not both fit under the amount
            )
        ).mappings().first()
        if expense_row is None:
            raise ValueError("expense not found")

        already_paid = await self._confirmed_paid_total(expense_id)
        if already_paid + amount > Decimal(expense_row["amount"]):
            raise ValueError("confirmed payment total cannot exceed expense amount")

        payment_id = uuid.uuid4()
        await self.conn.execute(
            sa.insert(_expense_payments).values(
                id=payment_id,
                organization_id=organization_id,
                expense_id=expense_id,
                account_id=account_id,
                amount=amount,
                payment_method=payment_method,
                reference_number=reference_number,
                paid_date=paid_date,
                status="confirmed",
                created_by=created_by,
            )
        )
        await self._transactions.record(
            organization_id=organization_id,
            transaction_type="expense_payment",
            amount=amount,
            occurred_date=paid_date,
            created_by=created_by,
            from_account_id=account_id,
            source_type="expense_payment",
            source_id=payment_id,
        )
        await self._recompute_payment_status(organization_id, expense_id)

        res = await self.conn.execute(
            sa.select(_expense_payments).where(_expense_payments.c.id == payment_id)
        )
        return _row_to_payment(res.mappings().one())

    async def reverse_payment(
        self, organization_id: uuid.UUID, payment_id: uuid.UUID, created_by: uuid.UUID
    ) -> ExpensePayment:
        """Undo one payment row.

        - A bill payment or an on-account payment (CC-10) moved money: the money goes back to its account.
        - A part of an on-account payment applied to a bill (``advance_id``) moved none: undoing it only frees that
          part of the advance again, no money moves (8 Nov 2026; before, every undo refunded the account).
        - An on-account payment still applied to bills is refused: undo those first (``reverse_on_account`` does both).
        """
        payment_row = (
            await self.conn.execute(
                sa.select(_expense_payments).where(
                    _expense_payments.c.id == payment_id,
                    _expense_payments.c.organization_id == organization_id,
                )
            )
        ).mappings().first()
        if payment_row is None:
            raise ValueError("expense payment not found")
        if payment_row["status"] != "confirmed":
            raise ValueError("only confirmed payments can be reversed")
        if payment_row["expense_id"] is None and await self._applied_total(payment_id) > 0:
            raise ValueError("this payment is used on bills; undo those first")

        await self.conn.execute(
            sa.update(_expense_payments)
            .where(_expense_payments.c.id == payment_id)
            .values(status="reversed", updated_by=created_by, updated_at=sa.func.now())
        )
        if payment_row["advance_id"] is None:
            await self._transactions.record(
                organization_id=organization_id,
                transaction_type="reversal",
                amount=payment_row["amount"],
                occurred_date=datetime.date.today(),
                created_by=created_by,
                to_account_id=payment_row["account_id"],
                source_type="expense_payment",
                source_id=payment_id,
            )
        if payment_row["expense_id"] is not None:
            await self._recompute_payment_status(organization_id, payment_row["expense_id"])

        res = await self.conn.execute(
            sa.select(_expense_payments).where(_expense_payments.c.id == payment_id)
        )
        return _row_to_payment(res.mappings().one())

    # --- CC-10: paying a supplier on account (an advance, or against the running balance) -----------------------

    async def _applied_total(self, advance_id: uuid.UUID) -> Decimal:
        stmt = sa.select(sa.func.coalesce(sa.func.sum(_expense_payments.c.amount), 0)).where(
            _expense_payments.c.advance_id == advance_id, _expense_payments.c.status == "confirmed"
        )
        return Decimal((await self.conn.execute(stmt)).scalar_one())

    async def advance_left(self, organization_id: uuid.UUID, advance_id: uuid.UUID) -> Decimal:
        """What of an on-account payment is not yet applied to a bill (0 when undone or not one)."""
        row = (
            await self.conn.execute(
                sa.select(_expense_payments.c.amount, _expense_payments.c.status, _expense_payments.c.expense_id).where(
                    _expense_payments.c.id == advance_id, _expense_payments.c.organization_id == organization_id
                )
            )
        ).mappings().first()
        if row is None or row["status"] != "confirmed" or row["expense_id"] is not None:
            return Decimal(0)
        return Decimal(row["amount"]) - await self._applied_total(advance_id)

    async def record_on_account(
        self,
        *,
        organization_id: uuid.UUID,
        vendor_id: uuid.UUID,
        account_id: uuid.UUID,
        amount: Decimal,
        paid_date: datetime.date,
        created_by: uuid.UUID,
        project_id: uuid.UUID | None = None,
        payment_method: str | None = None,
        reference_number: str | None = None,
        description: str | None = None,
    ) -> ExpensePayment:
        """Money paid to a supplier with no bill picked: it leaves the account now (one money transaction) and is
        applied to bills by ``apply_advance``."""
        if amount <= 0:
            raise ValueError("amount must be positive")
        payment_id = uuid.uuid4()
        await self.conn.execute(
            sa.insert(_expense_payments).values(
                id=payment_id, organization_id=organization_id, expense_id=None, vendor_id=vendor_id,
                project_id=project_id, account_id=account_id, amount=amount, payment_method=payment_method,
                reference_number=reference_number, paid_date=paid_date, status="confirmed", created_by=created_by,
            )
        )
        await self._transactions.record(
            organization_id=organization_id,
            transaction_type="expense_payment",
            amount=amount,
            occurred_date=paid_date,
            created_by=created_by,
            from_account_id=account_id,
            source_type="expense_payment",
            source_id=payment_id,
            description=description,
        )
        res = await self.conn.execute(sa.select(_expense_payments).where(_expense_payments.c.id == payment_id))
        return _row_to_payment(res.mappings().one())

    async def apply_advance(
        self,
        *,
        organization_id: uuid.UUID,
        advance_id: uuid.UUID,
        expense_id: uuid.UUID,
        amount: Decimal,
        created_by: uuid.UUID,
    ) -> ExpensePayment:
        """Use ``amount`` of an on-account payment on a bill: the bill is paid by that much, no money moves."""
        adv = (
            await self.conn.execute(
                sa.select(_expense_payments).where(
                    _expense_payments.c.id == advance_id, _expense_payments.c.organization_id == organization_id
                ).with_for_update()  # one advance used by two requests at once must not be spent twice
            )
        ).mappings().first()
        if adv is None or adv["expense_id"] is not None:
            raise ValueError("on-account payment not found")
        left = await self.advance_left(organization_id, advance_id)
        if amount <= 0 or amount > left:
            raise ValueError(f"only {left} of this payment is left to use")
        bill = (
            await self.conn.execute(
                sa.select(_expenses.c.amount).where(
                    _expenses.c.id == expense_id, _expenses.c.organization_id == organization_id
                ).with_for_update()  # two payments at once must not both fit under the amount
            )
        ).mappings().first()
        if bill is None:
            raise ValueError("expense not found")
        if await self._confirmed_paid_total(expense_id) + amount > Decimal(bill["amount"]):
            raise ValueError("confirmed payment total cannot exceed expense amount")
        row_id = uuid.uuid4()
        await self.conn.execute(
            sa.insert(_expense_payments).values(
                id=row_id, organization_id=organization_id, expense_id=expense_id, advance_id=advance_id,
                vendor_id=adv["vendor_id"], account_id=adv["account_id"], amount=amount,
                payment_method=adv["payment_method"], reference_number=adv["reference_number"],
                paid_date=adv["paid_date"], status="confirmed", created_by=created_by,
            )
        )
        await self._recompute_payment_status(organization_id, expense_id)
        res = await self.conn.execute(sa.select(_expense_payments).where(_expense_payments.c.id == row_id))
        return _row_to_payment(res.mappings().one())

    async def reverse_on_account(
        self, organization_id: uuid.UUID, payment_id: uuid.UUID, created_by: uuid.UUID
    ) -> ExpensePayment:
        """Undo an on-account payment: its uses on bills first (those bills are unpaid again), then the money."""
        applied = (
            await self.conn.execute(
                sa.select(_expense_payments.c.id).where(
                    _expense_payments.c.advance_id == payment_id,
                    _expense_payments.c.organization_id == organization_id,
                    _expense_payments.c.status == "confirmed",
                )
            )
        ).scalars().all()
        for row_id in applied:
            await self.reverse_payment(organization_id, row_id, created_by)
        return await self.reverse_payment(organization_id, payment_id, created_by)


class PostgresBudgetRepository:
    def __init__(self, conn: AsyncConnection):
        self.conn = conn

    async def get_actual_spend(self, organization_id: uuid.UUID, budget_id: uuid.UUID) -> Decimal:
        """Sum of confirmed, non-voided expenses in the budget's project,
        restricted to allocated categories when the budget has allocations."""
        budget_row = (
            await self.conn.execute(
                sa.select(_budgets.c.project_id).where(
                    _budgets.c.id == budget_id, _budgets.c.organization_id == organization_id
                )
            )
        ).mappings().first()
        if budget_row is None:
            raise ValueError("budget not found")

        allocation_categories = (
            await self.conn.execute(
                sa.select(_budget_allocations.c.category_id).where(
                    _budget_allocations.c.budget_id == budget_id,
                    _budget_allocations.c.category_id.is_not(None),
                )
            )
        ).scalars().all()

        where_clauses = [
            _expenses.c.organization_id == organization_id,
            _expenses.c.project_id == budget_row["project_id"],
            _expenses.c.workflow_status == "confirmed",
        ]
        if allocation_categories:
            where_clauses.append(_expenses.c.category_id.in_(allocation_categories))

        stmt = sa.select(sa.func.coalesce(sa.func.sum(_expenses.c.amount), 0)).where(*where_clauses)
        return Decimal((await self.conn.execute(stmt)).scalar_one())
