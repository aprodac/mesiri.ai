"""Resolve a RecordExpenseCommand's vendor_text against vendors.

Mirrors application/expenses/resolution.py's ExpenseCategoryResolver, with
one deliberate difference: vendor is never rejected AND never defaulted --
`vendor_text` absent leaves `vendor_id` null (an expense genuinely may have
no vendor concept), while a present `vendor_text` that doesn't match an
existing vendor gets a brand-new vendor row instead of falling into a shared
"Uncategorized"-style bucket (see PostgresVendorRepository.create's
docstring for why). This never blocks the workflow -- there is no
"unresolvable vendor" outcome.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

from mesiri.infrastructure.postgres.repositories.vendors import PostgresVendorRepository

from ..expenses.commands import RecordExpenseCommand

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection


@dataclass(frozen=True, slots=True)
class VendorResolutionResult:
    vendor_id: uuid.UUID | None


class VendorResolver(ABC):
    @abstractmethod
    async def resolve(
        self, conn: AsyncConnection, cmd: RecordExpenseCommand
    ) -> VendorResolutionResult: ...


class PostgresVendorResolver(VendorResolver):
    async def resolve(
        self, conn: AsyncConnection, cmd: RecordExpenseCommand
    ) -> VendorResolutionResult:
        if not cmd.vendor_text:
            return VendorResolutionResult(vendor_id=None)

        vendor_id = await vendor_for_name(
            conn, uuid.UUID(cmd.organization_id), cmd.vendor_text, created_by=uuid.UUID(cmd.created_by)
        )
        return VendorResolutionResult(vendor_id=vendor_id)


async def vendor_for_name(
    conn: AsyncConnection, organization_id: uuid.UUID, name: str | None, *, created_by: uuid.UUID | None
) -> uuid.UUID | None:
    """The one rule for a shop named in words (an expense's vendor, a delivery's supplier, PRC-04): the company's
    active vendor with exactly that name (case aside), else a new vendor with it; None when no name was given."""
    text = (name or "").strip()
    if not text:
        return None
    repo = PostgresVendorRepository(conn)
    vendor = await repo.find_by_name_exact_active(organization_id, text)
    if vendor is None:
        vendor = await repo.create(organization_id, text, created_by=created_by)
    return vendor.id
