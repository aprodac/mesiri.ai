from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from pydantic import BaseModel


class ExpenseResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    project_id: uuid.UUID
    project_name: str | None = None
    project_code: str | None = None
    site_id: uuid.UUID | None = None
    site_name: str | None = None
    category_id: uuid.UUID
    category_name: str | None = None
    vendor_id: uuid.UUID | None = None
    vendor_name: str | None = None
    #: WEB-51: the company's sequential number ("EXP-0042"); None for expenses made before numbering.
    expense_number: str | None = None
    account_id: str | None = None
    account_name: str | None = None
    custodian_name: str | None = None
    amount: Decimal
    currency: str
    description: str | None
    occurred_date: datetime.date
    occurred_time: datetime.time | None
    workflow_status: str
    payment_status: str
    source: str
    source_message_id: str | None
    correlation_id: str | None
    tax_rate: Decimal | None = None
    tax_amount: Decimal | None = None
    is_tax_inclusive: bool = True
    whatsapp_sender: str | None = None
    raw_message_text: str | None = None
    created_by: uuid.UUID
    created_by_name: str | None = None
    created_by_email: str | None = None
    created_by_role: str | None = None
    created_at: datetime.datetime | str | None = None


class RecordExpenseResponse(BaseModel):
    id: uuid.UUID
    status: str
