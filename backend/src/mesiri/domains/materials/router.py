from __future__ import annotations

import contextlib
import datetime
import json
import uuid
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.domains.materials.invoices import (
    attach_invoice_document,
    build_expense_command,
    insert_invoice,
    insert_invoice_line,
)
from mesiri.domains.materials.posting import post_material_movement
from mesiri.domains.materials.responses import (
    MaterialCatalogListResponse,
    MaterialCatalogResponse,
    MaterialLedgerResponse,
    MaterialReceiptResponse,
    MaterialReceiptsListResponse,
    MaterialStockResponse,
    MaterialUsageListResponse,
    MaterialUsageResponse,
)
from mesiri.domains.materials.validation import (
    ADJUSTMENT_REASONS,
    is_valid_receipt_reason,
    is_valid_usage_reason,
    role_can_adjust,
)
from mesiri.domains.projects.router import get_auth_context
from mesiri.domains.shared.media import assert_downloadable_url
from mesiri.infrastructure.objectstorage.dependency import get_object_storage
from mesiri.infrastructure.postgres.dependency import get_db_conn
from mesiri_contracts.application.results.execution_result import ExecutionStatus
from mesiri_contracts.common.storage import ObjectStoragePort

#: Matches the expenses router's TTL — long enough to open the document, short
#: enough that a copied link stops working.
_ATTACHMENT_URL_TTL_SECONDS = 600
from mesiri.domains.shared.modules import require_module
from mesiri.infrastructure.postgres.repositories.materials import (
    MaterialMovementsRepository,
    PostgresMaterialCatalogRepository,
    PostgresMaterialReadRepository,
    UnitsOfMeasureRepository,
)

router = APIRouter(
    prefix="/materials",
    tags=["materials"],
    dependencies=[Depends(require_module("materials"))],
)


def _site_filter_denied(
    auth_context: AuthorizationContext,
    project_id: uuid.UUID | None,
    site_id: uuid.UUID | None,
) -> bool:
    """True if the requested site_id filter must be denied under the caller's site scope."""
    if site_id is None:
        return False
    if project_id is None:
        return not auth_context.project_scope.grants_all_org_projects
    site_scope = auth_context.site_scope_for_project(project_id)
    if site_scope.grants_all_sites:
        return False
    return site_id not in site_scope.site_ids


def _resolve_project_ids(
    auth_context: AuthorizationContext, project_id: uuid.UUID | None
) -> tuple[set[uuid.UUID] | None, bool]:
    """Returns (project_ids filter, denied). denied=True means caller has no access at all."""
    if project_id is not None:
        if not auth_context.project_scope.grants_all_org_projects:
            if project_id not in auth_context.project_scope.project_ids:
                return None, True
        return {project_id}, False
    if not auth_context.project_scope.grants_all_org_projects:
        if not auth_context.project_scope.project_ids:
            return None, True
        return auth_context.project_scope.project_ids, False
    return None, False


async def _publish_outbox_event(
    conn: AsyncConnection,
    *,
    aggregate_type: str,
    aggregate_id: uuid.UUID,
    event_type: str,
    payload: dict[str, Any],
    correlation_id: str | None = None,
) -> None:
    """Write an outbox_events row on the caller's connection/transaction."""
    await conn.execute(
        text(
            "INSERT INTO outbox_events "
            "(id, aggregate_type, aggregate_id, event_type, payload, correlation_id) "
            "VALUES (:id, :aggregate_type, :aggregate_id, :event_type, "
            "CAST(:payload AS jsonb), :correlation_id)"
        ),
        {
            "id": uuid.uuid4(),
            "aggregate_type": aggregate_type,
            "aggregate_id": aggregate_id,
            "event_type": event_type,
            "payload": json.dumps(payload),
            "correlation_id": correlation_id,
        },
    )


async def _claim_idempotency_key(
    conn: AsyncConnection, key: str, command_type: str
) -> dict | None:
    """Claim `key` for this request, or return the completed original's result.

    The REST materials path mints its own row id server-side, so a retried
    request -- a double tap, or a client timing out and resending on site wifi
    -- used to create a second, equally real movement that nobody could tell
    apart from a genuine second delivery. The WhatsApp path has been protected
    since 0160 via this same table; this brings REST to parity rather than
    inventing a second mechanism.

    Returns None when the caller won the claim and should proceed. Returns the
    stored result dict when this key already completed, so the caller replays
    it instead of writing again. Runs on the request's existing connection, so
    the claim commits or rolls back with the movement it guards.
    """
    row = (
        await conn.execute(
            text("SELECT status, result FROM idempotency_keys WHERE key = :key"),
            {"key": key},
        )
    ).mappings().first()
    if row is not None and row["status"] == "completed" and row["result"] is not None:
        stored = row["result"]
        return json.loads(stored) if isinstance(stored, str) else stored

    claimed = (
        await conn.execute(
            text(
                "INSERT INTO idempotency_keys (key, command_type, status) "
                "VALUES (:key, :command_type, 'in_progress') "
                "ON CONFLICT (key) DO NOTHING RETURNING key"
            ),
            {"key": key, "command_type": command_type},
        )
    ).first()
    if claimed is None:
        # Another transaction holds this key. Postgres's row lock means we only
        # get here once that transaction settled, so an in_progress row now is
        # one that failed and rolled back its work -- retrying is correct.
        raise HTTPException(
            status_code=409,
            detail="A request with this Idempotency-Key is already being processed.",
        )
    return None


async def _complete_idempotency_key(conn: AsyncConnection, key: str, result: dict) -> None:
    await conn.execute(
        text(
            "UPDATE idempotency_keys SET status = 'completed', "
            "result = CAST(:result AS jsonb), completed_at = now() WHERE key = :key"
        ),
        {"result": json.dumps(result, default=str), "key": key},
    )


async def _assert_site_in_project(
    conn: AsyncConnection,
    organization_id: uuid.UUID,
    project_id: uuid.UUID,
    site_id: uuid.UUID,
) -> None:
    row = (
        await conn.execute(
            text(
                "SELECT id FROM sites WHERE id = :site_id AND project_id = :project_id "
                "AND organization_id = :org_id"
            ),
            {"site_id": site_id, "project_id": project_id, "org_id": organization_id},
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=422, detail="Site does not belong to the specified Project")


def _authorize_write(
    auth_context: AuthorizationContext, project_id: uuid.UUID, site_id: uuid.UUID | None
) -> None:
    if not auth_context.project_scope.grants_all_org_projects:
        if project_id not in auth_context.project_scope.project_ids:
            raise HTTPException(status_code=403, detail="Not authorized for this project")
    if _site_filter_denied(auth_context, project_id, site_id):
        raise HTTPException(status_code=403, detail="Not authorized for this site")


# ---------------------------------------------------------------------------
# Materials Catalog
# ---------------------------------------------------------------------------
class MaterialCatalogCreate(BaseModel):
    name: str
    default_unit_id: uuid.UUID
    category: str | None = None
    sku: str | None = None


class MaterialCatalogUpdate(BaseModel):
    name: str | None = None
    default_unit_id: uuid.UUID | None = None
    category: str | None = None
    sku: str | None = None
    is_active: bool | None = None


@router.get("", response_model=MaterialCatalogListResponse)
async def list_materials(
    search: str | None = None,
    is_active: bool | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """List Materials accessible to the caller's organization."""
    repo = PostgresMaterialCatalogRepository(conn)
    items, total = await repo.list_materials(
        organization_id=auth_context.organization_id,
        search=search,
        is_active=is_active,
        limit=limit,
        offset=offset,
    )
    return {"items": items, "total": total}


@router.get("/units-of-measure")
async def list_units_of_measure(
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """List the fixed global units of measure — read-only, no per-org CRUD."""
    repo = UnitsOfMeasureRepository(conn)
    return {"items": await repo.list_active()}


@router.post("", response_model=MaterialCatalogResponse, status_code=201)
async def create_material(
    body: MaterialCatalogCreate,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Create a Material catalog entry (organization-scoped name) with its Stock Unit."""
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="name is required")
    units_repo = UnitsOfMeasureRepository(conn)
    unit = await units_repo.get_by_id(body.default_unit_id)
    if unit is None or not unit["is_active"]:
        raise HTTPException(status_code=422, detail="default_unit_id is not a valid active unit")

    repo = PostgresMaterialCatalogRepository(conn)
    # Case/whitespace-insensitive, matching migration 0459's unique index --
    # "cement" and "Cement" are one material, and letting the second through
    # would split one stockpile across two catalog rows (and make the WhatsApp
    # resolver, which is already lower()-based, pick between them arbitrarily).
    existing = await repo.get_by_name(auth_context.organization_id, name)
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=f"A Material named '{existing['name']}' already exists. Use that one instead.",
        )
    # Materials Catalog is org-scoped (no project_id/site_id), so it does not
    # fit the Timeline projector's per-project/site aggregate model — creation
    # is audited via the row's own created_at/created_by columns instead of
    # an outbox_events entry (see events/consumers/timeline_projector.py).
    return await repo.create(
        organization_id=auth_context.organization_id,
        name=name,
        default_unit=unit["code"],
        default_unit_id=unit["id"],
        category=body.category.strip() if body.category else None,
        sku=body.sku.strip() if body.sku else None,
        created_by=auth_context.user_id,
    )


@router.patch("/{material_id}", response_model=MaterialCatalogResponse)
async def update_material(
    material_id: uuid.UUID,
    body: MaterialCatalogUpdate,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Update a Material catalog entry. Stock Unit (default_unit_id) cannot change
    once any movement references this material — the unit a material is tracked
    in is fixed for its lifetime in V1 (no unit conversion)."""
    repo = PostgresMaterialCatalogRepository(conn)
    existing = await repo.get_by_id(auth_context.organization_id, material_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Material not found")

    default_unit_id = body.default_unit_id
    if default_unit_id is not None and default_unit_id != existing["default_unit_id"]:
        if await repo.has_movements(material_id):
            raise HTTPException(
                status_code=409,
                detail="Stock Unit cannot change: this material already has recorded movements",
            )
        units_repo = UnitsOfMeasureRepository(conn)
        unit = await units_repo.get_by_id(default_unit_id)
        if unit is None or not unit["is_active"]:
            raise HTTPException(status_code=422, detail="default_unit_id is not a valid active unit")

    name = body.name.strip() if body.name else None
    if name:
        clash = await repo.get_by_name(
            auth_context.organization_id, name, exclude_id=material_id
        )
        if clash is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Another Material is already named '{clash['name']}'.",
            )

    updated = await repo.update(
        auth_context.organization_id,
        material_id,
        name=name,
        default_unit_id=default_unit_id,
        category=body.category,
        sku=body.sku,
        is_active=body.is_active,
        updated_by=auth_context.user_id,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Material not found")
    return updated


@router.delete("/{material_id}", status_code=204)
async def delete_material(
    material_id: uuid.UUID,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Delete an unused Material catalog entry.

    Materials with ledger history must be deactivated instead so inventory and
    audit history keep resolving to the original catalog row.
    """
    repo = PostgresMaterialCatalogRepository(conn)
    existing = await repo.get_by_id(auth_context.organization_id, material_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Material not found")
    deleted = await repo.delete_unused(auth_context.organization_id, material_id)
    if not deleted:
        raise HTTPException(
            status_code=409,
            detail="Material has recorded movements and cannot be deleted. Deactivate it instead.",
        )
    return None


# ---------------------------------------------------------------------------
# Inflows (material_receipts, direction=IN)
# ---------------------------------------------------------------------------
@router.get("/inflows", response_model=MaterialReceiptsListResponse)
async def list_inflows(
    project_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    material_id: uuid.UUID | None = None,
    material_name: str | None = None,
    movement_reason: str | None = None,
    source: str | None = None,
    recorded_by_user_id: uuid.UUID | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """List material inflows (receipts) within the user's organization and project scope."""
    project_ids, denied = _resolve_project_ids(auth_context, project_id)
    if denied or _site_filter_denied(auth_context, project_id, site_id):
        return {"items": [], "total": 0}

    repo = PostgresMaterialReadRepository(conn)
    items, total = await repo.list_receipts(
        organization_id=auth_context.organization_id,
        project_ids=project_ids,
        site_id=site_id,
        material_id=material_id,
        material_name=material_name,
        movement_reason=movement_reason,
        source=source,
        recorded_by_user_id=recorded_by_user_id,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    return {"items": items, "total": total}


@router.get("/inflows/{receipt_id}", response_model=MaterialReceiptResponse)
async def get_inflow(
    receipt_id: uuid.UUID,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    repo = PostgresMaterialReadRepository(conn)
    item = await repo.get_receipt(auth_context.organization_id, receipt_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Inflow not found")
    if _site_filter_denied(auth_context, item["project_id"], item["site_id"]):
        raise HTTPException(status_code=403, detail="Not authorized for this movement")
    project_ids, denied = _resolve_project_ids(auth_context, item["project_id"])
    if denied:
        raise HTTPException(status_code=403, detail="Not authorized for this movement")
    item["already_reversed"] = (
        await repo.find_reversal_of(auth_context.organization_id, receipt_id)
    ) is not None
    return item


# ---------------------------------------------------------------------------
# Outflows (material_usage, direction=OUT)
# ---------------------------------------------------------------------------
@router.get("/outflows", response_model=MaterialUsageListResponse)
async def list_outflows(
    project_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    material_id: uuid.UUID | None = None,
    material_name: str | None = None,
    movement_reason: str | None = None,
    source: str | None = None,
    recorded_by_user_id: uuid.UUID | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """List material outflows (usages) within the user's organization and project scope."""
    project_ids, denied = _resolve_project_ids(auth_context, project_id)
    if denied or _site_filter_denied(auth_context, project_id, site_id):
        return {"items": [], "total": 0}

    repo = PostgresMaterialReadRepository(conn)
    items, total = await repo.list_usage(
        organization_id=auth_context.organization_id,
        project_ids=project_ids,
        site_id=site_id,
        material_id=material_id,
        material_name=material_name,
        movement_reason=movement_reason,
        source=source,
        recorded_by_user_id=recorded_by_user_id,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    return {"items": items, "total": total}


@router.get("/outflows/{usage_id}", response_model=MaterialUsageResponse)
async def get_outflow(
    usage_id: uuid.UUID,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    repo = PostgresMaterialReadRepository(conn)
    item = await repo.get_usage(auth_context.organization_id, usage_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Outflow not found")
    if _site_filter_denied(auth_context, item["project_id"], item["site_id"]):
        raise HTTPException(status_code=403, detail="Not authorized for this movement")
    project_ids, denied = _resolve_project_ids(auth_context, item["project_id"])
    if denied:
        raise HTTPException(status_code=403, detail="Not authorized for this movement")
    item["already_reversed"] = (
        await repo.find_reversal_of(auth_context.organization_id, usage_id)
    ) is not None
    return item


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------
@router.get("/inventory", response_model=list[MaterialStockResponse])
async def list_inventory(
    project_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    material_id: uuid.UUID | None = None,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Get aggregated material inventory (stock levels), derived from the movement ledger."""
    project_ids, denied = _resolve_project_ids(auth_context, project_id)
    if denied or _site_filter_denied(auth_context, project_id, site_id):
        return []

    repo = PostgresMaterialReadRepository(conn)
    return await repo.get_stock_levels(
        organization_id=auth_context.organization_id,
        project_ids=project_ids,
        site_id=site_id,
        material_id=material_id,
    )


@router.get("/stock-check")
async def check_available_stock(
    material_id: uuid.UUID,
    site_id: uuid.UUID | None = None,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Current balance for one Site + Material, so an entry form can warn
    before the user submits rather than after.

    Deliberately narrow: `/inventory` can answer this via `?material_id=`, but
    it returns the full stock row for every site the caller can see, which is a
    lot of payload for one number a dialog re-fetches on every material change.
    """
    if site_id is not None:
        site_row = (
            await conn.execute(
                text("SELECT project_id FROM sites WHERE id = :site_id AND organization_id = :org"),
                {"site_id": site_id, "org": auth_context.organization_id},
            )
        ).first()
        if site_row is None:
            raise HTTPException(status_code=404, detail="Site not found")
        if _site_filter_denied(auth_context, site_row[0], site_id):
            raise HTTPException(status_code=403, detail="Not authorized for this site")
        _, denied = _resolve_project_ids(auth_context, site_row[0])
        if denied:
            raise HTTPException(status_code=403, detail="Not authorized for this site")

    repo = PostgresMaterialReadRepository(conn)
    catalog = await PostgresMaterialCatalogRepository(conn).get_by_id(
        auth_context.organization_id, material_id
    )
    if catalog is None:
        raise HTTPException(status_code=404, detail="Material not found")

    available = await repo.get_available_stock(
        auth_context.organization_id, site_id, material_id
    )
    return {
        "material_id": material_id,
        "site_id": site_id,
        "available": available,
        "unit": catalog["default_unit"],
    }


@router.get("/last-purchase")
async def get_last_purchase_price(
    material_id: uuid.UUID,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """The last rate paid for a material, or nulls when none was ever recorded.

    Returns 200 with empty fields rather than 404 for "never priced": the
    entry form treats it as a hint, and a missing hint is not an error.
    """
    repo = PostgresMaterialReadRepository(conn)
    last = await repo.get_last_purchase_price(auth_context.organization_id, material_id)
    if last is None:
        return {"material_id": material_id, "unit_cost": None}
    return {
        "material_id": material_id,
        "unit_cost": last["unit_cost"],
        "unit": last["unit"],
        "occurred_date": last["occurred_date"],
        "supplier": last["supplier"],
    }


@router.get("/ledger/{site_id}/{material_id}", response_model=MaterialLedgerResponse)
async def get_material_ledger(
    site_id: uuid.UUID,
    material_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Chronological movement history + running balance for one Site + Material."""
    site_row = (
        await conn.execute(
            text("SELECT project_id FROM sites WHERE id = :site_id AND organization_id = :org_id"),
            {"site_id": site_id, "org_id": auth_context.organization_id},
        )
    ).first()
    if site_row is None:
        raise HTTPException(status_code=404, detail="Site not found")
    project_id = site_row[0]
    if _site_filter_denied(auth_context, project_id, site_id):
        raise HTTPException(status_code=403, detail="Not authorized for this site")
    _, denied = _resolve_project_ids(auth_context, project_id)
    if denied:
        raise HTTPException(status_code=403, detail="Not authorized for this site")

    repo = PostgresMaterialReadRepository(conn)
    items, total = await repo.get_ledger(
        organization_id=auth_context.organization_id,
        site_id=site_id,
        material_id=material_id,
        limit=limit,
        offset=offset,
    )
    current_balance = items[0]["running_balance"] if items else None
    unit = items[0]["unit"] if items else None
    return {"items": items, "total": total, "current_balance": current_balance, "unit": unit}


# ---------------------------------------------------------------------------
# Write Schemas & Endpoints
# ---------------------------------------------------------------------------
class MaterialInflowCreate(BaseModel):
    project_id: uuid.UUID
    site_id: uuid.UUID | None = None
    material_id: uuid.UUID
    unit_id: uuid.UUID
    quantity: Decimal
    movement_reason: str = "RECEIVED"
    supplier: str | None = None
    notes: str | None = None
    occurred_date: datetime.date
    # Rate per stock unit as printed on the supplier's document. Both stay
    # None when the price genuinely was not recorded -- see _resolve_costs for
    # why an unrecorded price must never be stored as zero.
    unit_cost: Decimal | None = None
    # Defaults to quantity x unit_cost, but is accepted as given when sent, so
    # a real invoice's discount, rounding or delivery charge survives instead
    # of being overwritten by arithmetic.
    total_cost: Decimal | None = None


class MaterialOutflowCreate(BaseModel):
    project_id: uuid.UUID
    site_id: uuid.UUID | None = None
    material_id: uuid.UUID
    unit_id: uuid.UUID
    quantity: Decimal
    movement_reason: str = "CONSUMED"
    work_item: str | None = None
    notes: str | None = None
    occurred_date: datetime.date
    # Defaults True so the WhatsApp and mobile write paths are unchanged by
    # this guard; the dashboard sends False and surfaces the confirmation.
    # Negative stock is a real situation (deliveries recorded late), so this is
    # a confirmation, never a prohibition.
    allow_negative: bool = True


def _resolve_costs(
    quantity: Decimal, unit_cost: Decimal | None, total_cost: Decimal | None
) -> tuple[Decimal | None, Decimal | None]:
    """Work out what to store for a purchase's rate and line total.

    Cost is optional throughout: plenty of real movements have no price
    (transfers between sites, returns, stock corrections), and a delivery whose
    invoice has not arrived yet is a normal state, not an error.

    The rule that matters is that "not recorded" is stored as NULL and never as
    zero. Zero is a claim -- it says the cement was free -- and it silently
    drags any average or total toward nonsense. `application/dpr/assembly.py`
    already refuses to report material cost for exactly this reason, noting
    that a partial figure "would read as complete and mislead".

    Both directions are supported because both happen: a storekeeper reads the
    rate off the invoice and the total follows; or the invoice shows only a
    line total after a discount and the effective rate follows from it.
    """
    if unit_cost is not None and unit_cost < 0:
        raise HTTPException(status_code=422, detail="unit_cost cannot be negative")
    if total_cost is not None and total_cost < 0:
        raise HTTPException(status_code=422, detail="total_cost cannot be negative")

    if unit_cost is not None and total_cost is None:
        total_cost = (unit_cost * quantity).quantize(Decimal("0.01"))
    elif total_cost is not None and unit_cost is None and quantity > 0:
        unit_cost = (total_cost / quantity).quantize(Decimal("0.01"))
    return unit_cost, total_cost


async def _resolve_and_validate_material_unit(
    conn: AsyncConnection,
    organization_id: uuid.UUID,
    material_id: uuid.UUID,
    unit_id: uuid.UUID,
) -> tuple[dict, dict]:
    """Look up the catalog material and unit by id and enforce the material's
    Stock Unit (materials_catalog.default_unit_id) — no free-text creation,
    no unit substitution. Raises HTTPException on any mismatch."""
    catalog_repo = PostgresMaterialCatalogRepository(conn)
    material = await catalog_repo.get_by_id(organization_id, material_id)
    if material is None or not material["is_active"]:
        raise HTTPException(status_code=422, detail="material_id is not a valid active catalog entry")

    units_repo = UnitsOfMeasureRepository(conn)
    unit = await units_repo.get_by_id(unit_id)
    if unit is None or not unit["is_active"]:
        raise HTTPException(status_code=422, detail="unit_id is not a valid active unit")

    if material["default_unit_id"] is not None and unit["id"] != material["default_unit_id"]:
        raise HTTPException(
            status_code=422,
            detail=(
                f"unit_id does not match {material['name']}'s Stock Unit "
                f"(expected {material['default_unit']}); no unit conversion is supported"
            ),
        )
    return material, unit


@router.post("/inflows", status_code=201)
async def create_inflow(
    body: MaterialInflowCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Log a material receipt/inflow (web or mobile direct entry).

    Send an `Idempotency-Key` header to make retries safe: the same key twice
    returns the first result rather than recording a second delivery. Omitting
    it keeps the previous behaviour exactly.
    """
    if idempotency_key:
        replayed = await _claim_idempotency_key(conn, idempotency_key, "material_inflow_rest")
        if replayed is not None:
            return {**replayed, "status": "replayed"}

    if not is_valid_receipt_reason(body.movement_reason):
        raise HTTPException(
            status_code=422, detail=f"Invalid inflow movement_reason: {body.movement_reason}"
        )
    if body.movement_reason in ADJUSTMENT_REASONS and not role_can_adjust(auth_context.role):
        raise HTTPException(status_code=403, detail="Not authorized to record adjustment movements")
    if body.quantity <= 0:
        raise HTTPException(status_code=422, detail="quantity must be greater than zero")

    _authorize_write(auth_context, body.project_id, body.site_id)
    if body.site_id is not None:
        await _assert_site_in_project(
            conn, auth_context.organization_id, body.project_id, body.site_id
        )

    material, unit = await _resolve_and_validate_material_unit(
        conn, auth_context.organization_id, body.material_id, body.unit_id
    )
    unit_cost, total_cost = _resolve_costs(body.quantity, body.unit_cost, body.total_cost)

    row_id = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO material_receipts "
            "(id, organization_id, project_id, site_id, material_name, quantity, unit, unit_id, "
            "supplier, occurred_date, occurred_date_source, source, movement_reason, notes, "
            "material_id, unit_cost, total_cost, created_by) "
            "VALUES (:id, :organization_id, :project_id, :site_id, :material_name, "
            ":quantity, :unit, :unit_id, :supplier, :occurred_date, 'reported', 'web', "
            ":movement_reason, :notes, :material_id, :unit_cost, :total_cost, :created_by)"
        ),
        {
            "id": row_id,
            "organization_id": auth_context.organization_id,
            "project_id": body.project_id,
            "site_id": body.site_id,
            "material_name": material["name"],
            "quantity": body.quantity,
            "unit": unit["code"],
            "unit_id": unit["id"],
            "supplier": body.supplier.strip() if body.supplier else None,
            "occurred_date": body.occurred_date,
            "movement_reason": body.movement_reason,
            "notes": body.notes.strip() if body.notes else None,
            "material_id": material["id"],
            "unit_cost": unit_cost,
            "total_cost": total_cost,
            "created_by": auth_context.user_id,
        },
    )
    await post_material_movement(
        conn,
        movement_type="RECEIPT",
        material_id=material["id"],
        unit_id=unit["id"],
        quantity=body.quantity,
        organization_id=auth_context.organization_id,
        project_id=body.project_id,
        site_id=body.site_id,
        occurred_at=datetime.datetime.combine(body.occurred_date, datetime.time.min),
        source_type="material_receipt",
        source_id=row_id,
        recorded_by_user_id=auth_context.user_id,
    )
    await _publish_outbox_event(
        conn,
        aggregate_type="material_receipt",
        aggregate_id=row_id,
        event_type="MaterialReceived",
        payload={
            "material_name": material["name"],
            "quantity": str(body.quantity),
            "unit": unit["code"],
            "movement_reason": body.movement_reason,
            "occurred_date": body.occurred_date.isoformat(),
            "occurred_date_source": "reported",
        },
    )
    result = {"id": row_id, "status": "success"}
    if idempotency_key:
        await _complete_idempotency_key(conn, idempotency_key, result)
    return result


@router.post("/outflows", status_code=201)
async def create_outflow(
    body: MaterialOutflowCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Log a material usage/outflow (web or mobile direct entry).

    Send an `Idempotency-Key` header to make retries safe (see create_inflow).

    Set `allow_negative` to record an issue that takes stock below zero. It
    defaults to True so WhatsApp and mobile keep their current behaviour; the
    dashboard opts in to the guard and asks the user to confirm instead.
    """
    if idempotency_key:
        replayed = await _claim_idempotency_key(conn, idempotency_key, "material_outflow_rest")
        if replayed is not None:
            return {**replayed, "status": "replayed"}

    if not is_valid_usage_reason(body.movement_reason):
        raise HTTPException(
            status_code=422, detail=f"Invalid outflow movement_reason: {body.movement_reason}"
        )
    if body.movement_reason in ADJUSTMENT_REASONS and not role_can_adjust(auth_context.role):
        raise HTTPException(status_code=403, detail="Not authorized to record adjustment movements")
    if body.quantity <= 0:
        raise HTTPException(status_code=422, detail="quantity must be greater than zero")

    _authorize_write(auth_context, body.project_id, body.site_id)
    if body.site_id is not None:
        await _assert_site_in_project(
            conn, auth_context.organization_id, body.project_id, body.site_id
        )

    material, unit = await _resolve_and_validate_material_unit(
        conn, auth_context.organization_id, body.material_id, body.unit_id
    )

    if not body.allow_negative:
        read_repo = PostgresMaterialReadRepository(conn)
        # Lock BEFORE reading. Stock is a SUM over rows that do not exist yet,
        # so there is nothing to SELECT ... FOR UPDATE -- without this, two
        # concurrent issues of 8 against 10 both read 10, both pass, and both
        # insert, leaving -6 with each user told the stock was fine.
        await read_repo.lock_stock_for_update(body.site_id, material["id"])
        available = await read_repo.get_available_stock(
            auth_context.organization_id, body.site_id, material["id"]
        )
        if body.quantity > available:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": (
                        f"Only {available} {unit['code']} of {material['name']} "
                        f"in stock, but {body.quantity} was entered."
                    ),
                    "available": str(available),
                    "requested": str(body.quantity),
                    "unit": unit["code"],
                    "material_name": material["name"],
                },
            )

    row_id = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO material_usage "
            "(id, organization_id, project_id, site_id, material_name, quantity, unit, unit_id, "
            "work_item, occurred_date, occurred_date_source, source, movement_reason, notes, "
            "material_id, created_by) "
            "VALUES (:id, :organization_id, :project_id, :site_id, :material_name, "
            ":quantity, :unit, :unit_id, :work_item, :occurred_date, 'reported', 'web', "
            ":movement_reason, :notes, :material_id, :created_by)"
        ),
        {
            "id": row_id,
            "organization_id": auth_context.organization_id,
            "project_id": body.project_id,
            "site_id": body.site_id,
            "material_name": material["name"],
            "quantity": body.quantity,
            "unit": unit["code"],
            "unit_id": unit["id"],
            "work_item": body.work_item.strip() if body.work_item else None,
            "occurred_date": body.occurred_date,
            "movement_reason": body.movement_reason,
            "notes": body.notes.strip() if body.notes else None,
            "material_id": material["id"],
            "created_by": auth_context.user_id,
        },
    )
    await post_material_movement(
        conn,
        movement_type="ISSUE",
        material_id=material["id"],
        unit_id=unit["id"],
        quantity=body.quantity,
        organization_id=auth_context.organization_id,
        project_id=body.project_id,
        site_id=body.site_id,
        occurred_at=datetime.datetime.combine(body.occurred_date, datetime.time.min),
        source_type="material_usage",
        source_id=row_id,
        recorded_by_user_id=auth_context.user_id,
    )
    await _publish_outbox_event(
        conn,
        aggregate_type="material_usage",
        aggregate_id=row_id,
        event_type="MaterialUsed",
        payload={
            "material_name": material["name"],
            "quantity": str(body.quantity),
            "unit": unit["code"],
            "movement_reason": body.movement_reason,
            "occurred_date": body.occurred_date.isoformat(),
            "occurred_date_source": "reported",
        },
    )
    result = {"id": row_id, "status": "success"}
    if idempotency_key:
        await _complete_idempotency_key(conn, idempotency_key, result)
    return result


# ---------------------------------------------------------------------------
# Supplier invoices (Phase C)
# ---------------------------------------------------------------------------
class MaterialInvoiceLine(BaseModel):
    material_id: uuid.UUID
    unit_id: uuid.UUID
    quantity: Decimal
    unit_cost: Decimal | None = None
    total_cost: Decimal | None = None


class MaterialInvoiceCreate(BaseModel):
    project_id: uuid.UUID
    site_id: uuid.UUID | None = None
    lines: list[MaterialInvoiceLine]
    supplier_name: str | None = None
    vendor_id: uuid.UUID | None = None
    invoice_number: str | None = None
    invoice_date: datetime.date | None = None
    # As printed on the document. Never derived from the lines: tax and freight
    # are not extracted in V1, so this legitimately differs from their sum.
    invoice_total: Decimal | None = None
    currency: str = "INR"
    notes: str | None = None
    # Object key of the already-uploaded document. The file is never copied --
    # Finance's expense attachment points at this same key.
    media_object_key: str | None = None
    source: str = "web"
    correlation_id: str | None = None
    # Set false only to record a purchase with no financial obligation (a free
    # replacement, an internal transfer documented on a supplier's paper).
    create_expense: bool = True


@router.post("/invoices", status_code=201)
async def create_invoice(
    body: MaterialInvoiceCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Record one supplier invoice: N purchases, stock, evidence, one expense.

    Everything lands in the request's single transaction, so a supervisor's one
    confirmation either updates inventory *and* Finance, or does nothing at all.
    Nobody re-keys the same document into two modules.
    """
    if idempotency_key:
        replayed = await _claim_idempotency_key(conn, idempotency_key, "material_invoice_rest")
        if replayed is not None:
            return {**replayed, "status": "replayed"}

    if not body.lines:
        raise HTTPException(status_code=422, detail="An invoice needs at least one material line")

    _authorize_write(auth_context, body.project_id, body.site_id)
    if body.site_id is not None:
        await _assert_site_in_project(
            conn, auth_context.organization_id, body.project_id, body.site_id
        )

    # Resolve every line before writing anything, so an unknown material on
    # line 3 does not leave lines 1 and 2 recorded.
    resolved: list[tuple[MaterialInvoiceLine, dict, dict, Decimal | None, Decimal | None]] = []
    for index, line in enumerate(body.lines, start=1):
        if line.quantity <= 0:
            raise HTTPException(
                status_code=422, detail=f"Line {index}: quantity must be greater than zero"
            )
        try:
            material, unit = await _resolve_and_validate_material_unit(
                conn, auth_context.organization_id, line.material_id, line.unit_id
            )
        except HTTPException as exc:
            # Re-raised with the line number attached: "unit does not match
            # Cement's Stock Unit" is unhelpful on a 12-line invoice.
            raise HTTPException(
                status_code=exc.status_code, detail=f"Line {index}: {exc.detail}"
            ) from exc
        unit_cost, total_cost = _resolve_costs(line.quantity, line.unit_cost, line.total_cost)
        resolved.append((line, material, unit, unit_cost, total_cost))

    if body.vendor_id is not None:
        vendor = (
            await conn.execute(
                text("SELECT id FROM vendors WHERE id = :id AND organization_id = :org"),
                {"id": body.vendor_id, "org": auth_context.organization_id},
            )
        ).first()
        # 404 rather than 403: confirming that another org's vendor exists
        # would leak it.
        if vendor is None:
            raise HTTPException(status_code=404, detail="Vendor not found")

    invoice_id = uuid.uuid4()
    occurred_date = body.invoice_date or datetime.date.today()
    supplier_name = body.supplier_name.strip() if body.supplier_name else None

    await insert_invoice(
        conn,
        invoice_id=invoice_id,
        organization_id=auth_context.organization_id,
        project_id=body.project_id,
        site_id=body.site_id,
        vendor_id=body.vendor_id,
        supplier_name=supplier_name,
        invoice_number=body.invoice_number.strip() if body.invoice_number else None,
        invoice_date=body.invoice_date,
        invoice_total=body.invoice_total,
        currency=body.currency,
        source=body.source,
        correlation_id=body.correlation_id,
        notes=body.notes.strip() if body.notes else None,
        created_by=auth_context.user_id,
    )

    receipt_ids: list[uuid.UUID] = []
    for line, material, unit, unit_cost, total_cost in resolved:
        receipt_ids.append(
            await insert_invoice_line(
                conn,
                invoice_id=invoice_id,
                organization_id=auth_context.organization_id,
                project_id=body.project_id,
                site_id=body.site_id,
                material=material,
                unit=unit,
                quantity=line.quantity,
                unit_cost=unit_cost,
                total_cost=total_cost,
                supplier_name=supplier_name,
                occurred_date=occurred_date,
                created_by=auth_context.user_id,
            )
        )

    if body.media_object_key:
        await attach_invoice_document(
            conn,
            invoice_id=invoice_id,
            media_object_key=body.media_object_key,
            created_by=auth_context.user_id,
        )

    expense_id = await _create_invoice_expense(conn, body, invoice_id, auth_context, resolved)

    await _publish_outbox_event(
        conn,
        aggregate_type="material_invoice",
        aggregate_id=invoice_id,
        event_type="MaterialInvoiceRecorded",
        payload={
            "supplier_name": supplier_name,
            "line_count": len(resolved),
            "invoice_total": str(body.invoice_total) if body.invoice_total is not None else None,
            "expense_id": str(expense_id) if expense_id else None,
        },
        correlation_id=body.correlation_id,
    )

    result = {
        "id": invoice_id,
        "receipt_ids": receipt_ids,
        "expense_id": expense_id,
        "status": "success",
    }
    if idempotency_key:
        await _complete_idempotency_key(conn, idempotency_key, result)
    return result


@router.get("/invoices/{invoice_id}")
async def get_invoice(
    invoice_id: uuid.UUID,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """One invoice with its purchases — what the Purchase History drill-in needs."""
    row = (
        await conn.execute(
            text(
                "SELECT i.*, v.name AS vendor_name "
                "FROM material_invoices i "
                "LEFT JOIN vendors v ON v.id = i.vendor_id "
                "WHERE i.id = :id AND i.organization_id = :org"
            ),
            {"id": invoice_id, "org": auth_context.organization_id},
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Invoice not found")

    invoice = dict(row)
    if _site_filter_denied(auth_context, invoice["project_id"], invoice["site_id"]):
        raise HTTPException(status_code=403, detail="Not authorized for this invoice")
    _, denied = _resolve_project_ids(auth_context, invoice["project_id"])
    if denied:
        raise HTTPException(status_code=403, detail="Not authorized for this invoice")

    lines = (
        await conn.execute(
            text(
                "SELECT id, material_id, material_name, quantity, unit, unit_cost, total_cost "
                "FROM material_receipts WHERE invoice_id = :id ORDER BY created_at"
            ),
            {"id": invoice_id},
        )
    ).mappings().all()
    attachments = (
        await conn.execute(
            text(
                "SELECT id, media_object_key, attachment_type FROM material_invoice_attachments "
                "WHERE invoice_id = :id ORDER BY created_at"
            ),
            {"id": invoice_id},
        )
    ).mappings().all()

    invoice["lines"] = [dict(r) for r in lines]
    invoice["has_attachment"] = len(attachments) > 0
    invoice["attachment_count"] = len(attachments)
    return invoice


@router.get("/invoices/{invoice_id}/attachment")
async def get_invoice_attachment(
    invoice_id: uuid.UUID,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
    object_storage: ObjectStoragePort = Depends(get_object_storage),
):
    """A short-lived link to the original document.

    Re-checked on every request rather than handed out once: an invoice shows
    supplier pricing, which is commercially sensitive.
    """
    row = (
        await conn.execute(
            text(
                "SELECT i.project_id, i.site_id, a.media_object_key, a.attachment_type "
                "FROM material_invoices i "
                "JOIN material_invoice_attachments a ON a.invoice_id = i.id "
                "WHERE i.id = :id AND i.organization_id = :org "
                "ORDER BY a.created_at LIMIT 1"
            ),
            {"id": invoice_id, "org": auth_context.organization_id},
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="No document attached to this invoice")
    if _site_filter_denied(auth_context, row["project_id"], row["site_id"]):
        raise HTTPException(status_code=403, detail="Not authorized for this invoice")
    _, denied = _resolve_project_ids(auth_context, row["project_id"])
    if denied:
        raise HTTPException(status_code=403, detail="Not authorized for this invoice")

    # assert_downloadable_url turns a misconfigured storage provider into a
    # clear 500 rather than a silently broken image in the browser.
    url = assert_downloadable_url(
        await object_storage.generate_presigned_url(
            row["media_object_key"], expires_in_seconds=_ATTACHMENT_URL_TTL_SECONDS
        )
    )
    return {"url": url, "attachment_type": row["attachment_type"]}


async def _create_invoice_expense(
    conn: AsyncConnection,
    body: MaterialInvoiceCreate,
    invoice_id: uuid.UUID,
    auth_context: AuthorizationContext,
    resolved: list,
) -> uuid.UUID | None:
    """Hand the obligation to Finance and record which expense it became.

    Materials never inserts into the expenses tables -- it calls Finance's own
    handler on this same connection, so the expense is created by the module
    that owns the rules and still rolls back with the purchases if anything
    later fails.

    The amount is the invoice total as printed when there is one, falling back
    to the sum of the priced lines. Never both: a printed total already includes
    tax and freight that the lines do not, so adding them would double-count.
    """
    if not body.create_expense:
        return None

    amount = body.invoice_total
    if amount is None:
        line_sum = sum((t for *_, t in resolved if t is not None), Decimal("0"))
        amount = line_sum if line_sum > 0 else None
    # No amount anywhere means no price was recorded at all. An expense of zero
    # would claim the delivery was free, so record the purchase and skip the
    # obligation rather than invent one.
    if amount is None or amount <= 0:
        return None

    from mesiri.application.expenses.handlers import RecordExpenseHandler
    from mesiri.infrastructure.postgres.repositories.expense_execution import (
        PostgresExpenseCategoryResolver,
        PostgresExpenseExecutionRepository,
        PostgresVendorResolver,
    )

    cmd = build_expense_command(
        invoice_id=invoice_id,
        organization_id=auth_context.organization_id,
        project_id=body.project_id,
        site_id=body.site_id,
        vendor_id=body.vendor_id,
        supplier_name=body.supplier_name.strip() if body.supplier_name else None,
        amount=amount,
        currency=body.currency,
        occurred_date=body.invoice_date or datetime.date.today(),
        media_object_key=body.media_object_key,
        created_by=auth_context.user_id,
        correlation_id=body.correlation_id,
    )
    handler = RecordExpenseHandler(
        PostgresExpenseExecutionRepository(),
        resolver=PostgresExpenseCategoryResolver(),
        vendor_resolver=PostgresVendorResolver(),
    )
    result = await handler.handle(conn, cmd)
    if result.status is ExecutionStatus.REJECTED:
        # Finance refusing is not something to paper over: the purchase would
        # silently carry no obligation and the books would be short.
        raise HTTPException(
            status_code=422,
            detail=f"Could not record the Finance expense: {result.rejection_reasons}",
        )

    expense_id = uuid.UUID(result.material_row_id)
    await conn.execute(
        text("UPDATE material_invoices SET expense_id = :expense_id WHERE id = :id"),
        {"expense_id": expense_id, "id": invoice_id},
    )
    return expense_id


# ---------------------------------------------------------------------------
# Corrections / Reversals
# ---------------------------------------------------------------------------
class MaterialReversalCreate(BaseModel):
    reason_note: str | None = None
    occurred_date: datetime.date | None = None


@contextlib.contextmanager
def _reversal_race_as_conflict():
    """Turn the 0459 uniqueness violation into the same 409 the pre-check gives.

    Two people tapping Correct at the same moment both pass
    `_assert_not_already_reversed` (each reads before the other writes). The
    partial unique index is what actually stops the second one -- this makes
    that loss read as "already corrected" rather than a 500.
    """
    try:
        yield
    except IntegrityError as exc:  # pragma: no cover - exercised in integration
        if "reverses_movement_id" in str(exc.orig):
            raise HTTPException(
                status_code=409,
                detail="This movement was already corrected. Refresh to see the correction.",
            ) from exc
        raise


async def _assert_not_already_reversed(
    repo: PostgresMaterialReadRepository,
    organization_id: uuid.UUID,
    original_id: uuid.UUID,
) -> None:
    """One movement, at most one correction.

    Correcting twice does not undo anything twice -- it posts a second
    offsetting movement, so a 50-bag receipt reversed twice leaves stock 100
    bags light, permanently, since the ledger is append-only. Nothing checked
    this before, and 0310's UNIQUE(source_type, source_id, movement_type) does
    not catch it (each reversal mints a fresh source_id).

    Migration 0459's partial unique index is the real guard -- this check
    exists so the user gets a sentence explaining what happened instead of an
    integrity error. Two simultaneous clicks can still both pass here; the
    index is what stops the second one, and the caller maps that to this same
    409 (see the IntegrityError handling in each reverse endpoint).
    """
    existing = await repo.find_reversal_of(organization_id, original_id)
    if existing is not None:
        when = existing.get("occurred_date")
        raise HTTPException(
            status_code=409,
            detail=(
                "This movement was already corrected"
                + (f" on {when}" if when else "")
                + ". Correcting it again would double the adjustment."
            ),
        )


@router.post("/inflows/{receipt_id}/reverse", status_code=201)
async def reverse_inflow(
    receipt_id: uuid.UUID,
    body: MaterialReversalCreate,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Correct a confirmed Inflow by recording an offsetting ADJUSTMENT_OUT outflow.

    The original movement is never edited or deleted; this inserts a new
    outflow row referencing it via reverses_movement_id, preserving history.
    """
    if not role_can_adjust(auth_context.role):
        raise HTTPException(status_code=403, detail="Not authorized to correct movements")

    row_id = await reverse_material_record(
        conn,
        kind="receipt",
        record_id=receipt_id,
        organization_id=auth_context.organization_id,
        user_id=auth_context.user_id,
        reason_note=body.reason_note,
        occurred_date=body.occurred_date,
        authorize=lambda original: _authorize_write(
            auth_context, original["project_id"], original["site_id"]
        ),
    )
    return {"id": row_id, "status": "success"}


@router.post("/outflows/{usage_id}/reverse", status_code=201)
async def reverse_outflow(
    usage_id: uuid.UUID,
    body: MaterialReversalCreate,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Correct a confirmed Outflow by recording an offsetting ADJUSTMENT_IN inflow."""
    if not role_can_adjust(auth_context.role):
        raise HTTPException(status_code=403, detail="Not authorized to correct movements")

    row_id = await reverse_material_record(
        conn,
        kind="usage",
        record_id=usage_id,
        organization_id=auth_context.organization_id,
        user_id=auth_context.user_id,
        reason_note=body.reason_note,
        occurred_date=body.occurred_date,
        authorize=lambda original: _authorize_write(
            auth_context, original["project_id"], original["site_id"]
        ),
    )
    return {"id": row_id, "status": "success"}


async def reverse_material_record(
    conn: AsyncConnection,
    *,
    kind: str,
    record_id: uuid.UUID,
    organization_id: uuid.UUID,
    user_id: uuid.UUID | None,
    reason_note: str | None,
    occurred_date: datetime.date | None = None,
    authorize: Callable[[dict], None] | None = None,
) -> uuid.UUID:
    """Reverse one inflow (`kind="receipt"`) or outflow (`kind="usage"`):
    an offsetting ADJUSTMENT_OUT/IN record plus its movement, never an edit
    of the original. Returns the new record's id. 404 when the record is
    unknown, 409 when it was already reversed.

    The one implementation of a material correction -- used by the two
    reverse routes above and by rejecting a draft (BE-09, fact reviews),
    so a rejected draft goes through exactly the same ledger rules."""
    repo = PostgresMaterialReadRepository(conn)
    if kind == "receipt":
        original = await repo.get_receipt(organization_id, record_id)
        if original is None:
            raise HTTPException(status_code=404, detail="Inflow not found")
    elif kind == "usage":
        original = await repo.get_usage(organization_id, record_id)
        if original is None:
            raise HTTPException(status_code=404, detail="Outflow not found")
    else:
        raise ValueError(f"unknown material record kind: {kind}")
    if authorize is not None:
        authorize(original)
    await _assert_not_already_reversed(repo, organization_id, record_id)

    row_id = uuid.uuid4()
    occurred_date = occurred_date or datetime.date.today()
    if kind == "usage":
        return await _reverse_outflow_record(
            conn,
            original=original,
            usage_id=record_id,
            row_id=row_id,
            organization_id=organization_id,
            user_id=user_id,
            reason_note=reason_note,
            occurred_date=occurred_date,
        )
    receipt_id = record_id
    with _reversal_race_as_conflict():
        await conn.execute(
            text(
                "INSERT INTO material_usage "
                "(id, organization_id, project_id, site_id, material_name, quantity, unit, "
                "unit_id, work_item, occurred_date, occurred_date_source, source, "
                "movement_reason, notes, material_id, reverses_movement_id, created_by) "
                "VALUES (:id, :organization_id, :project_id, :site_id, :material_name, "
                ":quantity, :unit, :unit_id, NULL, :occurred_date, 'reported', 'web', "
                "'ADJUSTMENT_OUT', :notes, :material_id, :reverses_movement_id, :created_by)"
            ),
            {
                "id": row_id,
                "organization_id": organization_id,
                "project_id": original["project_id"],
                "site_id": original["site_id"],
                "material_name": original["material_name"],
                "quantity": original["quantity"],
                "unit": original["unit"],
                "unit_id": original["unit_id"],
                "occurred_date": occurred_date,
                "notes": reason_note,
                "material_id": original["material_id"],
                "reverses_movement_id": receipt_id,
                "created_by": user_id,
            },
        )
    movements_repo = MaterialMovementsRepository(conn)
    original_movement = await movements_repo.get_by_source("material_receipt", receipt_id)
    await post_material_movement(
        conn,
        movement_type="ISSUE",
        material_id=original["material_id"],
        unit_id=original["unit_id"],
        quantity=original["quantity"],
        organization_id=organization_id,
        project_id=original["project_id"],
        site_id=original["site_id"],
        occurred_at=datetime.datetime.combine(occurred_date, datetime.time.min),
        source_type="material_usage",
        source_id=row_id,
        recorded_by_user_id=user_id,
        reversal_of_movement_id=original_movement["id"] if original_movement else None,
    )
    await _publish_outbox_event(
        conn,
        aggregate_type="material_usage",
        aggregate_id=row_id,
        event_type="MaterialMovementCorrected",
        payload={"reverses_movement_id": str(receipt_id), "movement_reason": "ADJUSTMENT_OUT"},
    )
    return row_id


async def _reverse_outflow_record(
    conn: AsyncConnection,
    *,
    original: dict,
    usage_id: uuid.UUID,
    row_id: uuid.UUID,
    organization_id: uuid.UUID,
    user_id: uuid.UUID | None,
    reason_note: str | None,
    occurred_date: datetime.date,
) -> uuid.UUID:
    """The outflow half of `reverse_material_record`: an ADJUSTMENT_IN inflow."""
    with _reversal_race_as_conflict():
        await conn.execute(
            text(
                "INSERT INTO material_receipts "
                "(id, organization_id, project_id, site_id, material_name, quantity, unit, "
                "unit_id, supplier, occurred_date, occurred_date_source, source, "
                "movement_reason, notes, material_id, reverses_movement_id, created_by) "
                "VALUES (:id, :organization_id, :project_id, :site_id, :material_name, "
                ":quantity, :unit, :unit_id, NULL, :occurred_date, 'reported', 'web', "
                "'ADJUSTMENT_IN', :notes, :material_id, :reverses_movement_id, :created_by)"
            ),
            {
                "id": row_id,
                "organization_id": organization_id,
                "project_id": original["project_id"],
                "site_id": original["site_id"],
                "material_name": original["material_name"],
                "quantity": original["quantity"],
                "unit": original["unit"],
                "unit_id": original["unit_id"],
                "occurred_date": occurred_date,
                "notes": reason_note,
                "material_id": original["material_id"],
                "reverses_movement_id": usage_id,
                "created_by": user_id,
            },
        )
    movements_repo = MaterialMovementsRepository(conn)
    original_movement = await movements_repo.get_by_source("material_usage", usage_id)
    await post_material_movement(
        conn,
        movement_type="RECEIPT",
        material_id=original["material_id"],
        unit_id=original["unit_id"],
        quantity=original["quantity"],
        organization_id=organization_id,
        project_id=original["project_id"],
        site_id=original["site_id"],
        occurred_at=datetime.datetime.combine(occurred_date, datetime.time.min),
        source_type="material_receipt",
        source_id=row_id,
        recorded_by_user_id=user_id,
        reversal_of_movement_id=original_movement["id"] if original_movement else None,
    )
    await _publish_outbox_event(
        conn,
        aggregate_type="material_receipt",
        aggregate_id=row_id,
        event_type="MaterialMovementCorrected",
        payload={"reverses_movement_id": str(usage_id), "movement_reason": "ADJUSTMENT_IN"},
    )
    return row_id
