"""Domain entities for expenses, categories, attachments, payments, and budgets.

Plain dataclasses — no SQLAlchemy. Expense is the business event ("what
money was spent on"); ExpensePayment is the money movement out of a
MoneyAccount to cover it (zero, one, or several per expense).
"""

from __future__ import annotations

import datetime
import enum
import uuid
from dataclasses import dataclass
from decimal import Decimal


class WorkflowStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING_CONFIRMATION = "pending_confirmation"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    VOIDED = "voided"


class PaymentStatus(str, enum.Enum):
    UNPAID = "unpaid"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"
    REIMBURSABLE = "reimbursable"
    REIMBURSED = "reimbursed"


class ExpensePaymentRowStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REVERSED = "reversed"


class AttachmentType(str, enum.Enum):
    RECEIPT = "receipt"
    BILL = "bill"
    PAYMENT_PROOF = "payment_proof"
    SUPPORTING_IMAGE = "supporting_image"
    OTHER = "other"


class CategoryStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class BudgetStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


@dataclass(frozen=True, slots=True)
class ExpenseCategory:
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    status: CategoryStatus
    code: str | None = None
    parent_category_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class Expense:
    id: uuid.UUID
    organization_id: uuid.UUID
    project_id: uuid.UUID
    category_id: uuid.UUID
    amount: Decimal
    currency: str
    occurred_date: datetime.date
    workflow_status: WorkflowStatus
    payment_status: PaymentStatus
    source: str
    created_by: uuid.UUID
    site_id: uuid.UUID | None = None
    vendor_id: uuid.UUID | None = None
    expense_number: str | None = None
    description: str | None = None
    occurred_time: datetime.time | None = None
    source_message_id: str | None = None
    correlation_id: str | None = None
    tax_rate: Decimal | None = None
    tax_amount: Decimal | None = None
    is_tax_inclusive: bool = True


@dataclass(frozen=True, slots=True)
class ExpenseAttachment:
    id: uuid.UUID
    expense_id: uuid.UUID
    media_object_key: str
    attachment_type: AttachmentType
    created_by: uuid.UUID


@dataclass(frozen=True, slots=True)
class ExpensePayment:
    id: uuid.UUID
    organization_id: uuid.UUID
    #: None for a payment made to a supplier on account (CC-10): an advance, or against the running balance.
    expense_id: uuid.UUID | None
    account_id: uuid.UUID
    amount: Decimal
    paid_date: datetime.date
    status: ExpensePaymentRowStatus
    created_by: uuid.UUID
    payment_method: str | None = None
    reference_number: str | None = None
    paid_time: datetime.time | None = None
    #: CC-10: the supplier an on-account payment went to.
    vendor_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    #: CC-10: set when this row is part of an on-account payment applied to a bill; it moves no money itself.
    advance_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class Budget:
    id: uuid.UUID
    organization_id: uuid.UUID
    project_id: uuid.UUID
    name: str
    amount: Decimal
    currency: str
    status: BudgetStatus
    created_by: uuid.UUID
    start_date: datetime.date | None = None
    end_date: datetime.date | None = None


@dataclass(frozen=True, slots=True)
class BudgetAllocation:
    id: uuid.UUID
    budget_id: uuid.UUID
    amount: Decimal
    created_by: uuid.UUID
    category_id: uuid.UUID | None = None
