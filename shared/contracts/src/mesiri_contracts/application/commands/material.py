"""Material Application Commands (M8) — the typed handoff from ConfirmedActionV2.

Two distinct commands, not one with a direction flag — mirrors the existing
"two tables, not one" decision for material_receipts/material_usage (they
carry genuinely different optional fields: supplier/cost vs work_item).

`project_id` is deliberately nullable here even though material_receipts/
material_usage require it NOT NULL — Domain validation rejects a missing
project_id (a real, routine outcome of unresolved M4 context), the mapper
must never invent one.

Ownership: SHARED ARCHITECTURE — part of the M0 contract surface. Version: v2.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel

from mesiri_contracts.assistant.v2.uuid_scope import CanonicalUuid

CONTRACT_VERSION = "v2"


class RecordMaterialReceiptCommand(BaseModel):
    """Record that material arrived on site."""

    version: str = CONTRACT_VERSION

    command_id: str
    idempotency_key: str
    correlation_id: str

    organization_id: CanonicalUuid
    project_id: CanonicalUuid | None
    site_id: CanonicalUuid | None

    material_name: str
    quantity: Decimal
    unit: str
    supplier: str | None = None
    #: Request 164: what the delivery cost, said with it (additive; the receipt
    #: table already has unit_cost / total_cost). Either may be given; the other
    #: is worked out from the quantity.
    total_cost: Decimal | None = None
    unit_cost: Decimal | None = None
    #: None is an ordinary delivery. "OPENING_STOCK" is what was already on
    #: site before Mesiri (entered once per site + material).
    movement_reason: str | None = None
    #: Request 171: why, in words ("Stock count: records 176, counted 20"); kept on the row.
    notes: str | None = None

    # Populated once the WhatsApp assistant's deterministic resolution gates
    # (or the Handler's defense-in-depth resolver, see application/materials/
    # handlers.py) have matched material_name/unit against materials_catalog/
    # units_of_measure. None until resolved.
    material_id: CanonicalUuid | None = None
    unit_id: CanonicalUuid | None = None

    occurred_date: date
    occurred_date_source: str = "inferred_at_confirmation"

    #: PHO-03: the bill / challan photo the delivery was read from, kept with
    #: the receipt (the object is already stored; only its key travels here).
    media_object_key: str | None = None

    created_by: CanonicalUuid

    model_config = {"extra": "forbid"}


class RecordMaterialUsageCommand(BaseModel):
    """Record that material was used/consumed on site."""

    version: str = CONTRACT_VERSION

    command_id: str
    idempotency_key: str
    correlation_id: str

    organization_id: CanonicalUuid
    project_id: CanonicalUuid | None
    site_id: CanonicalUuid | None

    material_name: str
    quantity: Decimal
    unit: str
    work_item: str | None = None
    #: Request 171: None is an ordinary use (CONSUMED). "ADJUSTMENT_OUT" is a stock
    #: count that found less than the books show; ``notes`` says why.
    movement_reason: str | None = None
    notes: str | None = None

    material_id: CanonicalUuid | None = None
    unit_id: CanonicalUuid | None = None

    occurred_date: date
    occurred_date_source: str = "inferred_at_confirmation"

    created_by: CanonicalUuid

    model_config = {"extra": "forbid"}


class RecordMaterialTransferCommand(BaseModel):
    """Record that material moved from one site to another (``project_id`` /
    ``site_id`` is the sending site)."""

    version: str = CONTRACT_VERSION

    command_id: str
    idempotency_key: str
    correlation_id: str

    organization_id: CanonicalUuid
    project_id: CanonicalUuid | None
    site_id: CanonicalUuid | None
    to_project_id: CanonicalUuid | None = None
    to_site_id: CanonicalUuid | None = None

    material_name: str
    quantity: Decimal
    unit: str

    material_id: CanonicalUuid | None = None
    unit_id: CanonicalUuid | None = None

    occurred_date: date
    occurred_date_source: str = "inferred_at_confirmation"

    created_by: CanonicalUuid

    model_config = {"extra": "forbid"}
