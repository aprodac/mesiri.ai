from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from pydantic import BaseModel


class MaterialReceiptResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    project_id: uuid.UUID
    site_id: uuid.UUID | None
    material_name: str
    quantity: Decimal
    unit: str
    unit_cost: Decimal | None
    total_cost: Decimal | None
    supplier: str | None
    # A correction has been posted against this purchase, so its cost must not
    # be counted toward spend totals -- the money was netted off.
    is_reversed: bool = False
    occurred_date: datetime.date
    occurred_time: datetime.time | None
    correlation_id: str | None
    source: str
    occurred_date_source: str
    material_id: uuid.UUID | None
    movement_reason: str
    notes: str | None
    reverses_movement_id: uuid.UUID | None
    # BE-32: set on both halves of a transfer between sites.
    transfer_id: uuid.UUID | None = None
    # WEB-35: the supplier invoice this purchase came from, so the ledger can
    # open the document. Was stored but never returned, so the link never showed.
    invoice_id: uuid.UUID | None = None
    # True when a correction has already been posted against THIS movement, so
    # the UI can hide "Correct" rather than offer an action that now 409s.
    # Absent on list endpoints (it needs a per-row lookup); only the detail
    # endpoints populate it, which is where the button actually lives.
    already_reversed: bool = False
    created_at: datetime.datetime
    created_by: uuid.UUID
    updated_at: datetime.datetime
    updated_by: uuid.UUID | None


class MaterialReceiptsListResponse(BaseModel):
    items: list[MaterialReceiptResponse]
    total: int


class MaterialUsageResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    project_id: uuid.UUID
    site_id: uuid.UUID | None
    material_name: str
    quantity: Decimal
    unit: str
    work_item: str | None
    occurred_date: datetime.date
    occurred_time: datetime.time | None
    correlation_id: str | None
    source: str
    occurred_date_source: str
    material_id: uuid.UUID | None
    movement_reason: str
    notes: str | None
    reverses_movement_id: uuid.UUID | None
    # BE-32: set on both halves of a transfer between sites.
    transfer_id: uuid.UUID | None = None
    # True when a correction has already been posted against THIS movement, so
    # the UI can hide "Correct" rather than offer an action that now 409s.
    # Absent on list endpoints (it needs a per-row lookup); only the detail
    # endpoints populate it, which is where the button actually lives.
    already_reversed: bool = False
    created_at: datetime.datetime
    created_by: uuid.UUID
    updated_at: datetime.datetime
    updated_by: uuid.UUID | None


class MaterialUsageListResponse(BaseModel):
    items: list[MaterialUsageResponse]
    total: int


class MaterialStockResponse(BaseModel):
    organization_id: uuid.UUID
    project_id: uuid.UUID
    site_id: uuid.UUID | None
    material_id: uuid.UUID | None
    material_name: str
    unit: str
    total_received: Decimal
    total_used: Decimal
    current_stock: Decimal
    last_movement_at: datetime.datetime | None
    stock_state: str


class MaterialCatalogResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    default_unit: str | None
    # The Stock Unit's id: what every inflow/outflow/transfer for this
    # material must send as unit_id. The dashboard's record dialogs read it
    # from here; without it they send no unit_id and every write is a 422.
    default_unit_id: uuid.UUID | None = None
    category: str | None
    sku: str | None
    is_active: bool
    created_at: datetime.datetime
    updated_at: datetime.datetime


class MaterialCatalogListResponse(BaseModel):
    items: list[MaterialCatalogResponse]
    total: int


class MaterialLedgerEntryResponse(BaseModel):
    id: uuid.UUID
    direction: str
    movement_reason: str
    quantity: Decimal
    unit: str
    occurred_date: datetime.date
    occurred_time: datetime.time | None
    source: str
    notes: str | None
    context: str | None
    reverses_movement_id: uuid.UUID | None
    created_by: uuid.UUID
    created_at: datetime.datetime
    running_balance: Decimal


class MaterialLedgerResponse(BaseModel):
    items: list[MaterialLedgerEntryResponse]
    total: int
    current_balance: Decimal | None
    unit: str | None
