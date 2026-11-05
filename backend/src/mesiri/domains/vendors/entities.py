"""Domain entity for vendors/payees.

Plain dataclass — no SQLAlchemy. Mirrors the shape of
domains.expenses.entities.ExpenseCategory: a simple org-scoped named lookup
entity resolved from free text at expense-capture time (see
application/vendors/resolution.py).
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass


class VendorStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


@dataclass(frozen=True, slots=True)
class Vendor:
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    status: VendorStatus
    code: str | None = None
    #: PRC-04: contact details.
    phone: str | None = None
    gstin: str | None = None
    address: str | None = None
