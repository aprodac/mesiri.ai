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
    #: PRC-17b: the material's category ("Main › Sub") and main category, in lists; None when it has none.
    category: str | None = None
    main_category: str | None = None
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
    #: PRC-17b: the material's category ("Main › Sub") and main category, in lists; None when it has none.
    category: str | None = None
    main_category: str | None = None
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
    #: PRC-01: the material's category (main or sub), for stock grouped by category.
    category_id: uuid.UUID | None = None
    #: PRC-17a: "Electrical › Switches & sockets" (or just the main category); None when it has none.
    category: str | None = None
    #: The main category's name, for grouping a stock answer.
    main_category: str | None = None
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
    #: PRC-01: its place in the company's category tree (``material_categories``); ``category`` is the old free text.
    category_id: uuid.UUID | None = None
    sku: str | None
    is_active: bool
    created_at: datetime.datetime
    updated_at: datetime.datetime
    #: WA-127: what this company's people call it on WhatsApp ("kambi", "ചെങ്കല്ല്"), from
    #: material_aliases. Listed by GET /materials; empty elsewhere.
    aliases: list[str] = []


class MaterialCatalogListResponse(BaseModel):
    items: list[MaterialCatalogResponse]
    total: int


class MaterialLedgerEntryResponse(BaseModel):
    id: uuid.UUID
    # WEB-36: the material_receipts / material_usage row this movement came from.
    source_id: uuid.UUID | None = None
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


class MaterialCategoryResponse(BaseModel):
    """PRC-01: one category; ``parent_id`` is None for a main category."""

    id: uuid.UUID
    parent_id: uuid.UUID | None
    name: str
    sort_order: int
    is_active: bool
    #: Materials directly in this category (not counting its sub-categories).
    material_count: int = 0


class MaterialCategoryListResponse(BaseModel):
    items: list[MaterialCategoryResponse]
    #: Materials with no category yet.
    uncategorised: int


class CategorySuggestionResponse(BaseModel):
    """PRC-02: the category a new material would go in, or none."""

    category_id: uuid.UUID | None = None
    #: "Main › Sub", or the main category's name; empty when none.
    label: str = ""
    #: "rule" (its name fits the standard list), "hint" (the caller's words named one), or "" (none).
    source: str = ""


class StandardCategoriesResponse(BaseModel):
    categories_added: int
    materials_placed: int


class MaterialStockSummaryResponse(BaseModel):
    """PRC-17: one site+material over a period. opening + received + adjusted - used == closing."""

    project_id: uuid.UUID
    site_id: uuid.UUID | None
    material_id: uuid.UUID
    material_name: str
    unit: str
    category_id: uuid.UUID | None = None
    category: str | None = None
    main_category: str | None = None
    opening: Decimal
    received: Decimal
    used: Decimal
    #: Opening stock, adjustments and corrections in the period: what moved stock besides deliveries and use.
    adjusted: Decimal
    closing: Decimal
    #: Days the closing stock lasts at the last 7 days' use; None when nothing was used or nothing is left.
    days_left: int | None = None
    #: At or below zero, or under 3 days left at that use.
    running_low: bool
