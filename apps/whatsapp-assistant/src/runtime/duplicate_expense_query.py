"""Duplicate-expense read service (wiring layer only).

Same shape and justification as runtime/expense_category_query.py: adapts
the backend's PostgresExpenseRepository.find_potential_duplicate into a
plain async method the inbound journey can call before the graph runs (a
node must never query a repository itself -- see
workflows/expense_capture/nodes.py's `check_duplicate` docstring). Finance
Module Slice 8. Never opens a write transaction, never mutates state.
"""

from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

from mesiri.domains.shared import clock

if TYPE_CHECKING:
    from mesiri.infrastructure.postgres.database import PostgresDatabase


def _decimal(value: object) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError):
        return None


class DuplicateExpenseQueryService:
    def __init__(self, db: PostgresDatabase) -> None:
        self._db = db

    async def find_potential_duplicate(
        self,
        *,
        organization_id: str,
        project_id: str | None,
        amount: object,
        vendor_name: str | None = None,
        category_name: str | None = None,
    ) -> bool:
        """True if a confirmed expense for the same amount, recorded today,
        already matches the given vendor (preferred) or category (fallback).
        A vendor_name/category_name that doesn't resolve to a real active
        vendor/category is treated the same as not having one -- there is
        nothing yet to compare against."""
        amount_decimal = _decimal(amount)
        if amount_decimal is None:
            return False

        from mesiri.infrastructure.postgres.repositories.expenses import (
            PostgresExpenseCategoryRepository,
            PostgresExpenseRepository,
        )
        from mesiri.infrastructure.postgres.repositories.vendors import PostgresVendorRepository

        org_id = uuid.UUID(organization_id)
        async with self._db.transaction() as conn:
            vendor_id: uuid.UUID | None = None
            category_id: uuid.UUID | None = None
            if vendor_name:
                vendor = await PostgresVendorRepository(conn).find_by_name_exact_active(
                    org_id, vendor_name
                )
                vendor_id = vendor.id if vendor else None
            if vendor_id is None and category_name:
                category = await PostgresExpenseCategoryRepository(conn).find_by_name_exact_active(
                    org_id, category_name
                )
                category_id = category.id if category else None
            if vendor_id is None and category_id is None:
                return False

            duplicate = await PostgresExpenseRepository(conn).find_potential_duplicate(
                org_id,
                amount=amount_decimal,
                occurred_date=clock.today(),
                project_id=uuid.UUID(project_id) if project_id else None,
                vendor_id=vendor_id,
                category_id=category_id,
            )
        return duplicate is not None
