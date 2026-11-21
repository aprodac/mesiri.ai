"""Resolve a RecordExpenseCommand's category_text against expense_categories.

Defense-in-depth guard, mirrors application/materials/resolution.py, with
one deliberate asymmetry between the two entry points:

- REST's `category_id` is a client-chosen, already-real id (the client
  fetched it from the categories list) — if it doesn't resolve, that's a
  genuine integrity error worth surfacing as a rejection.
- WhatsApp's `category_text` is an AI guess (extraction is nudged toward the
  org's real category names — see understanding/pipeline.py's
  `expense_categories` param — but is not guaranteed to comply exactly).
  Rejecting the whole expense over an AI naming mismatch would just
  reproduce the "category_id or category_text is required"-style rejection
  bug this module was built to avoid. So an unmatched or absent
  category_text both fall back to the default "Uncategorized" category
  (get_or_create_default) instead of rejecting — only a REST category_id
  lookup failure is a hard rejection.

`ExpenseCategoryResolver` is an injectable port so Handler unit tests can
supply a fake instead of hitting Postgres — see application/expenses/fakes.py.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

from mesiri.infrastructure.postgres.repositories.expenses import PostgresExpenseCategoryRepository

from .commands import RecordExpenseCommand

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection


@dataclass(frozen=True, slots=True)
class ResolutionResult:
    category_id: uuid.UUID | None
    reasons: list[str]


class ExpenseCategoryResolver(ABC):
    @abstractmethod
    async def resolve(self, conn: AsyncConnection, cmd: RecordExpenseCommand) -> ResolutionResult: ...


class PostgresExpenseCategoryResolver(ExpenseCategoryResolver):
    async def resolve(self, conn: AsyncConnection, cmd: RecordExpenseCommand) -> ResolutionResult:
        organization_id = uuid.UUID(cmd.organization_id)
        repo = PostgresExpenseCategoryRepository(conn)

        if cmd.category_id is not None:
            category = await repo.get_by_id(organization_id, uuid.UUID(cmd.category_id))
            if category is None or category.status != "active":
                return ResolutionResult(
                    category_id=None, reasons=[f"category '{cmd.category_id}' not found"]
                )
            return ResolutionResult(category_id=category.id, reasons=[])

        # UX-93: a company's first expense can come before anyone opened its category list; the starter set (with
        # cost centres) is made here too, so "Materials" on a supplier's bill finds its category from day one.
        await repo.seed_defaults_if_empty(organization_id, created_by=uuid.UUID(cmd.created_by))
        if cmd.category_text:
            category = await repo.find_by_name_exact_active(organization_id, cmd.category_text)
            if category is not None:
                return ResolutionResult(category_id=category.id, reasons=[])
            # AI-guessed text that didn't match a real category -- fall
            # through to the default rather than rejecting (see module
            # docstring).

        category = await repo.get_or_create_default(
            organization_id, created_by=uuid.UUID(cmd.created_by)
        )
        return ResolutionResult(category_id=category.id, reasons=[])
