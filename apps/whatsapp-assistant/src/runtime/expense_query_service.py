"""Expense query read service (wiring layer only).

Same shape and justification as runtime/money_account_query.py: adapts the
backend's PostgresExpenseRepository/PostgresExpenseCategoryRepository into a
plain async method the assistant can call directly (Finance Module Slice 2).
Never opens a write transaction.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from mesiri.domains.shared import clock

if TYPE_CHECKING:
    from mesiri.domains.expenses.entities import Expense
    from mesiri.infrastructure.postgres.database import PostgresDatabase

_DATE_RANGE_LABELS = {"today": "today", "this_week": "this week", "this_month": "this month"}


def resolve_date_range(bucket: str | None) -> tuple[datetime.date, datetime.date, str]:
    """Map an extracted `date_range` bucket to a concrete (start, end, label).
    Defaults to "this month" when no time period was mentioned -- matches
    the plan's example queries, which are usually implicitly recent."""
    today = clock.today()
    if bucket == "today":
        return today, today, _DATE_RANGE_LABELS["today"]
    if bucket == "this_week":
        start = today - datetime.timedelta(days=today.weekday())
        return start, today, _DATE_RANGE_LABELS["this_week"]
    return today.replace(day=1), today, _DATE_RANGE_LABELS["this_month"]


class ExpenseQueryService:
    def __init__(self, db: PostgresDatabase) -> None:
        self._db = db

    async def list_expenses(
        self,
        *,
        organization_id: str,
        project_id: str | None,
        site_id: str | None,
        start_date: datetime.date,
        end_date: datetime.date,
        category_name: str | None = None,
        missing_receipts_only: bool = False,
    ) -> list[Expense]:
        """Confirmed expenses in [start_date, end_date], scoped to the
        caller's current project/site. `category_name` that doesn't resolve
        to a real active category returns an empty list (a named-but-wrong
        category means "no expenses match", not "ignore the filter").
        `missing_receipts_only` is Slice 6's missing-receipt nudge."""
        from mesiri.infrastructure.postgres.repositories.expenses import (
            PostgresExpenseCategoryRepository,
            PostgresExpenseRepository,
        )

        org_id = uuid.UUID(organization_id)
        async with self._db.transaction() as conn:
            category_id: uuid.UUID | None = None
            if category_name:
                category_repo = PostgresExpenseCategoryRepository(conn)
                category = await category_repo.find_by_name_exact_active(org_id, category_name)
                if category is None:
                    return []
                category_id = category.id

            repo = PostgresExpenseRepository(conn)
            return await repo.list_confirmed(
                org_id,
                project_id=uuid.UUID(project_id) if project_id else None,
                site_id=uuid.UUID(site_id) if site_id else None,
                start_date=start_date,
                end_date=end_date,
                category_id=category_id,
                without_attachment=missing_receipts_only,
            )

    @staticmethod
    def total(expenses: list[Expense]) -> Decimal:
        return sum((expense.amount for expense in expenses), Decimal("0"))
