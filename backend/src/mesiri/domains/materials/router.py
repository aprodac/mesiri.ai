from __future__ import annotations

import contextlib
import datetime
import json
import uuid
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.domains.materials.categories import clean_category_name
from mesiri.domains.materials.invoices import (
    attach_invoice_document,
    build_expense_command,
    insert_invoice,
    insert_invoice_line,
)
from mesiri.domains.materials.names import MaterialNameError, require_latin_name
from mesiri.domains.materials.posting import post_material_movement
from mesiri.domains.materials.responses import (
    CategorySuggestionResponse,
    MaterialCatalogListResponse,
    MaterialCatalogResponse,
    MaterialCategoryListResponse,
    MaterialCategoryResponse,
    MaterialLedgerResponse,
    MaterialReceiptResponse,
    MaterialReceiptsListResponse,
    MaterialStockResponse,
    MaterialUsageListResponse,
    MaterialUsageResponse,
    StandardCategoriesResponse,
)
from mesiri.domains.materials.transfers import (
    MaterialRuleError,
    assert_no_opening_stock,
    record_transfer,
)
from mesiri.domains.materials.validation import (
    ADJUSTMENT_REASONS,
    ELEVATED_REASONS,
    OPENING_STOCK,
    RECEIPT_REASONS,
    USAGE_REASONS,
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
    #: PRC-01: its category (main or sub) in the company's tree.
    category_id: uuid.UUID | None = None
    sku: str | None = None


class MaterialCatalogUpdate(BaseModel):
    name: str | None = None
    default_unit_id: uuid.UUID | None = None
    category: str | None = None
    #: PRC-01: sent as null, the material leaves its category; left out, it stays.
    category_id: uuid.UUID | None = None
    sku: str | None = None
    is_active: bool | None = None


async def _require_category(conn: AsyncConnection, organization_id: uuid.UUID, category_id: uuid.UUID) -> dict:
    """The company's own, switched-on category, or a 422 (a material is never put in another company's)."""
    from mesiri.infrastructure.postgres.repositories.material_categories import (
        PostgresMaterialCategoryRepository,
    )

    category = await PostgresMaterialCategoryRepository(conn).get(organization_id, category_id)
    if category is None or not category["is_active"]:
        raise HTTPException(status_code=422, detail="category_id is not one of this company's categories")
    return category


@router.get("", response_model=MaterialCatalogListResponse)
async def list_materials(
    search: str | None = None,
    is_active: bool | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """List Materials accessible to the caller's organization, each with what its people call it
    (aliases); ``search`` matches the name or an alias (WA-127)."""
    repo = PostgresMaterialCatalogRepository(conn)
    items, total = await repo.list_materials(
        organization_id=auth_context.organization_id,
        search=search,
        is_active=is_active,
        limit=limit,
        offset=offset,
    )
    aliases = await repo.list_aliases(auth_context.organization_id) if items else {}
    for item in items:
        item["aliases"] = aliases.get(str(item["id"]), [])
    return {"items": items, "total": total}


# ---------------------------------------------------------------------------
# Material categories (PRC-01): main category -> sub-category, per company
# ---------------------------------------------------------------------------
class MaterialCategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    #: A main category's id to make a sub-category; left out, it is a main category.
    parent_id: uuid.UUID | None = None


class MaterialCategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    sort_order: int | None = None
    is_active: bool | None = None


def _category_repo(conn: AsyncConnection):
    from mesiri.infrastructure.postgres.repositories.material_categories import (
        PostgresMaterialCategoryRepository,
    )

    return PostgresMaterialCategoryRepository(conn)


@router.get("/categories", response_model=MaterialCategoryListResponse)
async def list_material_categories(
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """The company's categories (main and sub, in order), how many materials sit in each, and how many have none."""
    repo = _category_repo(conn)
    items = await repo.list_all(auth_context.organization_id)
    return {"items": items, "uncategorised": await repo.count_uncategorised(auth_context.organization_id)}


@router.get("/categories/suggest", response_model=CategorySuggestionResponse)
async def suggest_material_category(
    name: str | None = Query(default=None, max_length=200, description="The material's name"),
    hint: str | None = Query(default=None, max_length=200, description="A category in words: 'Plumbing & CP > Pipes'"),
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """PRC-02: where a material goes. The ``hint`` in words first (the caller read the whole name: "Stainless steel
    sink" is sanitaryware, not steel), then the name alone when it settles it (fixed rules). Only one of the company's
    own switched-on categories, never a new one. None found: none."""
    from mesiri.domains.materials.categories import suggest

    return suggest(await _category_repo(conn).list_all(auth_context.organization_id), name, hint)


@router.post("/categories", response_model=MaterialCategoryResponse, status_code=201)
async def create_material_category(
    body: MaterialCategoryCreate,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Add a main category, or a sub-category under a main one (two levels: sizes and types are materials)."""
    repo = _category_repo(conn)
    name = clean_category_name(body.name)
    if not name:
        raise HTTPException(status_code=422, detail="name is required")
    if body.parent_id is not None:
        parent = await repo.get(auth_context.organization_id, body.parent_id)
        if parent is None:
            raise HTTPException(status_code=422, detail="parent_id is not one of this company's categories")
        if parent["parent_id"] is not None:
            raise HTTPException(
                status_code=422,
                detail=f"'{parent['name']}' is already a sub-category; add this under its main category instead.",
            )
    clash = await repo.find(auth_context.organization_id, body.parent_id, name)
    if clash is not None:
        raise HTTPException(status_code=409, detail=f"'{clash['name']}' already exists here.")
    return await repo.create(
        auth_context.organization_id,
        name=name,
        parent_id=body.parent_id,
        sort_order=await repo.next_sort_order(auth_context.organization_id, body.parent_id),
        created_by=auth_context.user_id,
    )


@router.post("/categories/standard", response_model=StandardCategoriesResponse)
async def apply_standard_material_categories(
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """PRC-03: add the builder's standard categories the company doesn't have yet, and place the materials
    that fit them by fixed rules. Safe to repeat; never moves a material someone already placed."""
    from mesiri.application.materials.categories import apply_standard_categories

    result = await apply_standard_categories(conn, auth_context.organization_id, auth_context.user_id)
    return {"categories_added": result.categories_added, "materials_placed": result.materials_placed}


@router.patch("/categories/{category_id}", response_model=MaterialCategoryResponse)
async def update_material_category(
    category_id: uuid.UUID,
    body: MaterialCategoryUpdate,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Rename, reorder, or switch a category off (its materials keep it; it is no longer offered)."""
    repo = _category_repo(conn)
    existing = await repo.get(auth_context.organization_id, category_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Category not found")
    name = clean_category_name(body.name) if body.name is not None else None
    if body.name is not None and not name:
        raise HTTPException(status_code=422, detail="name can't be empty")
    if name and name != existing["name"]:
        clash = await repo.find(auth_context.organization_id, existing["parent_id"], name, exclude_id=category_id)
        if clash is not None:
            raise HTTPException(status_code=409, detail=f"'{clash['name']}' already exists here.")
    updated = await repo.update(
        auth_context.organization_id,
        category_id,
        name=name,
        sort_order=body.sort_order,
        is_active=body.is_active,
        updated_by=auth_context.user_id,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Category not found")
    return updated


@router.delete("/categories/{category_id}", status_code=204)
async def delete_material_category(
    category_id: uuid.UUID,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Delete an empty category. One with materials or sub-categories is switched off instead."""
    repo = _category_repo(conn)
    if await repo.get(auth_context.organization_id, category_id) is None:
        raise HTTPException(status_code=404, detail="Category not found")
    if await repo.is_in_use(auth_context.organization_id, category_id):
        raise HTTPException(
            status_code=409,
            detail="This category has materials or sub-categories. Move them out first, or switch it off instead.",
        )
    await repo.delete(auth_context.organization_id, category_id)
    return None


class UnitConversionSet(BaseModel):
    """How much ONE of the reported unit is in the material's Stock Unit ("1 bar = 10.67 kg")."""

    from_unit_id: uuid.UUID
    one_unit_equals: Decimal = Field(gt=0, description="How many Stock Units one `from_unit` is, e.g. 10.67 (kg per bar)")


@router.put("/{material_id}/unit-conversions")
async def set_unit_conversion(
    material_id: uuid.UUID,
    body: UnitConversionSet,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """2 Nov 2026 (WA-151): set, for the whole company, how much one unit sites count in (a bar, a load) is in the
    material's Stock Unit; receipts, usage and transfers in that unit are converted from then on. The same table
    WhatsApp classic writes (WA-41); only an admin or a project manager may (Ilan, 21 Oct)."""
    from mesiri.authorization.roles import may_set_unit_conversions
    from mesiri.infrastructure.postgres.repositories.material_unit_conversions import (
        PostgresMaterialUnitConversionRepository,
    )

    if not may_set_unit_conversions(auth_context.role):
        raise HTTPException(status_code=403, detail="Only an admin or a project manager can set a unit conversion.")
    material = await PostgresMaterialCatalogRepository(conn).get_by_id(auth_context.organization_id, material_id)
    if material is None or material.get("default_unit_id") is None:
        raise HTTPException(status_code=404, detail="Material not found")
    units = UnitsOfMeasureRepository(conn)
    unit, stock = await units.get_by_id(body.from_unit_id), await units.get_by_id(material["default_unit_id"])
    if unit is None or stock is None:
        raise HTTPException(status_code=422, detail="from_unit_id is not a valid active unit")
    if str(unit["id"]) == str(stock["id"]):
        raise HTTPException(status_code=422, detail=f"{material['name']} is already counted in {stock['display_name']}.")
    from mesiri.domains.materials.unit_conversion import COUNT_UNITS

    if str(stock["code"]).lower() in COUNT_UNITS and body.one_unit_equals < 1:
        # WA-166 (Paraclette: "1 load holobricks = 0.33 nos" was saved, the size the wrong way round).
        raise HTTPException(status_code=422, detail=(
            f"1 {unit['display_name']} of {material['name']} cannot be less than 1 {stock['display_name']}: "
            f"how many {stock['display_name']} are in 1 {unit['display_name']}?"))
    per_stock_unit = (Decimal(1) / body.one_unit_equals).quantize(Decimal("0.0000001"))
    await PostgresMaterialUnitConversionRepository(conn).upsert(
        organization_id=auth_context.organization_id, material_id=material["id"], from_unit_id=unit["id"],
        per_stock_unit=per_stock_unit, user_id=auth_context.user_id,
    )
    return {
        "material": material["name"], "from_unit": unit["display_name"], "stock_unit": stock["display_name"],
        "one_unit_equals": f"{body.one_unit_equals.normalize():f}",  # WA-166: never "3E+2"
        "message": f"Saved for the company: 1 {unit['display_name']} of {material['name']} = "
                   f"{body.one_unit_equals.normalize():f} {stock['display_name']}.",
    }


class SizeRequestOpen(BaseModel):
    """WA-168: a size nobody knew (a line held for it), or a size someone without the right proposes."""

    material_id: uuid.UUID
    from_unit_id: uuid.UUID
    one_unit_equals: Decimal | None = Field(default=None, gt=0)
    #: The line that waits: the route it saves through, its body as reported, its words, its idempotency key.
    line_path: str | None = None
    line_body: dict | None = None
    line_summary: str = ""
    line_key: str | None = None


class SizeAnswer(BaseModel):
    one_unit_equals: Decimal = Field(gt=0)


def _may_answer(auth_context: AuthorizationContext) -> None:
    from mesiri.authorization.roles import may_set_unit_conversions

    if not may_set_unit_conversions(auth_context.role):
        raise HTTPException(status_code=403, detail="Only an admin or a project manager can set a size.")


@router.get("/size-requests")
async def list_size_requests(
    status: str | None = Query(default="open"),
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """WA-168: the sizes the company is asked for (open by default): material, unit, any proposal, lines waiting."""
    from mesiri.domains.materials import size_requests

    return {"items": await size_requests.list_requests(conn, auth_context.organization_id, status or None)}


@router.post("/size-requests", status_code=201)
async def open_size_request(
    body: SizeRequestOpen,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """WA-168: anyone in the company asks for a size (holding the line that needs it) or proposes one. The line is
    checked when it is answered, as the person who reported it, like any other entry of theirs."""
    from mesiri.domains.materials import size_requests

    material = await PostgresMaterialCatalogRepository(conn).get_by_id(auth_context.organization_id, body.material_id)
    if material is None:
        raise HTTPException(status_code=404, detail="Material not found")
    if await UnitsOfMeasureRepository(conn).get_by_id(body.from_unit_id) is None:
        raise HTTPException(status_code=422, detail="from_unit_id is not a valid active unit")
    line = None
    if body.line_path or body.line_body:
        try:
            line = size_requests.held_line(body.line_path or "", body.line_body or {}, body.line_summary,
                                           body.line_key, auth_context.user_id, auth_context.role)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return await size_requests.open_request(
        conn, auth_context.organization_id, body.material_id, body.from_unit_id, auth_context.user_id,
        proposed=body.one_unit_equals, line=line)


async def _save_held(conn: AsyncConnection, organization_id: uuid.UUID, line: dict) -> dict:
    """One held line saved now, as the person who reported it (their access decides), converted by the size just set."""
    from mesiri.authorization.service import AuthorizationService

    done = {"summary": line.get("summary"), "user_id": line.get("user_id")}
    try:
        async with conn.begin_nested():
            reporter = await AuthorizationService(conn).resolve_from_jwt(
                uuid.UUID(line["user_id"]), organization_id, str(line.get("role") or ""))
            if line["path"] == "/materials/inflows":
                result = await create_inflow(MaterialInflowCreate(**line["body"]), line.get("idempotency_key"),
                                             auth_context=reporter, conn=conn)
            else:
                result = await create_outflow(MaterialOutflowCreate(**line["body"]), line.get("idempotency_key"),
                                              auth_context=reporter, conn=conn)
        return {**done, "saved": True, "converted": (result or {}).get("converted") if isinstance(result, dict) else None}
    except HTTPException as exc:
        return {**done, "saved": False, "reason": str(exc.detail)[:200]}
    except Exception as exc:  # noqa: BLE001 -- one line never blocks the others or the size
        return {**done, "saved": False, "reason": type(exc).__name__}


@router.post("/size-requests/{request_id}/answer")
async def answer_size_request(
    request_id: uuid.UUID,
    body: SizeAnswer,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """WA-168: an admin or project manager answers: the size is set for the company (the same checks as setting it
    directly) and every line that waited for it saves now, converted, as the person who reported it."""
    from mesiri.domains.materials import size_requests

    _may_answer(auth_context)
    request = await size_requests.get_request(conn, auth_context.organization_id, request_id, lock=True)
    if request is None:
        raise HTTPException(status_code=404, detail="Size request not found")
    if request["status"] != "open":
        raise HTTPException(status_code=409, detail="This size was already answered.")
    await set_unit_conversion(
        request["material_id"], UnitConversionSet(from_unit_id=request["from_unit_id"], one_unit_equals=body.one_unit_equals),
        auth_context=auth_context, conn=conn)
    outcome = [await _save_held(conn, auth_context.organization_id, line) for line in request["held_lines"]]
    await size_requests.close_request(conn, request_id, "answered", auth_context.user_id, body.one_unit_equals, outcome)
    size = f"{body.one_unit_equals.normalize():f}"
    await _tell_reporters(conn, auth_context.organization_id, request_id, outcome,
                          f"1 {request['unit_name']} {request['material']} = {size} {request['stock_unit_name']}")
    return {"id": str(request_id), "material": request["material"], "unit_name": request["unit_name"],
            "stock_unit_name": request["stock_unit_name"], "one_unit_equals": size, "lines": outcome,
            "message": f"1 {request['unit_name']} of {request['material']} = {size} {request['stock_unit_name']}, "
                       f"for the whole company. {sum(1 for o in outcome if o['saved'])} of {len(outcome)} waiting "
                       "lines saved."}


async def _tell_reporters(conn: AsyncConnection, organization_id: uuid.UUID, request_id: uuid.UUID,
                          outcome: list[dict], size: str) -> None:
    """WA-168: each person whose line waited is told, on WhatsApp, that it is saved now (the notification queue:
    inside their 24-hour window; never more than once per request)."""
    import datetime as _dt

    from mesiri.infrastructure.postgres.repositories.notifications import (
        PostgresNotificationRepository,
    )

    by_person: dict[str, list[str]] = {}
    for line in outcome:
        if line.get("saved") and line.get("user_id"):
            by_person.setdefault(str(line["user_id"]), []).append(str(line.get("summary") or ""))
    for user_id, lines in by_person.items():
        try:
            async with conn.begin_nested():
                await PostgresNotificationRepository(conn).claim(
                    organization_id=organization_id, rule_key="size_request_saved",
                    subject_id=f"{request_id}:{user_id}", occurred_on=_dt.date.today(),
                    recipient_user_id=uuid.UUID(user_id),
                    payload={"message": f"✅ Saved now: {'; '.join(lines)} ({size}, set for the company)."})
        except Exception:  # noqa: BLE001 -- the lines are saved; the note is a courtesy
            continue


@router.post("/size-requests/{request_id}/dismiss")
async def dismiss_size_request(
    request_id: uuid.UUID,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """WA-168: not a size to set (the unit was a mistake): closed, nothing saved; the lines that waited are listed."""
    from mesiri.domains.materials import size_requests

    _may_answer(auth_context)
    request = await size_requests.get_request(conn, auth_context.organization_id, request_id, lock=True)
    if request is None:
        raise HTTPException(status_code=404, detail="Size request not found")
    if request["status"] != "open":
        raise HTTPException(status_code=409, detail="This size was already answered.")
    outcome = [{"summary": line.get("summary"), "user_id": line.get("user_id"), "saved": False, "reason": "dismissed"}
               for line in request["held_lines"]]
    await size_requests.close_request(conn, request_id, "dismissed", auth_context.user_id, None, outcome)
    return {"id": str(request_id), "lines": outcome}


@router.get("/unit-conversions")
async def list_unit_conversions(
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """WA-168: every size the company has set (the dashboard's Sizes page)."""
    from mesiri.domains.materials import size_requests

    return {"items": await size_requests.list_conversions(conn, auth_context.organization_id)}


@router.delete("/{material_id}/unit-conversions/{from_unit_id}", status_code=204)
async def delete_unit_conversion(
    material_id: uuid.UUID,
    from_unit_id: uuid.UUID,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """WA-168: remove a size that is wrong; it is asked again the next time someone uses that unit. Quantities saved
    with it stay as they were saved."""
    _may_answer(auth_context)
    result = await conn.execute(
        text("DELETE FROM material_unit_conversions WHERE organization_id = :org AND material_id = :m "
             "AND from_unit_id = :u"),
        {"org": auth_context.organization_id, "m": material_id, "u": from_unit_id})
    if not result.rowcount:
        raise HTTPException(status_code=404, detail="No such size")


@router.get("/{material_id}/unit-check")
async def check_material_unit(
    material_id: uuid.UUID,
    unit_id: uuid.UUID,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """3 Nov 2026 (WA-165, Paraclette: "1 load M-sand" was prepared, then refused at Save because M-sand is stocked
    in bags): can a quantity in ``unit_id`` be recorded for this material? Yes when it is the Stock Unit or a
    conversion into it is known (the same decision saving makes). Read-only, so the question comes before Save."""
    material = await PostgresMaterialCatalogRepository(conn).get_by_id(auth_context.organization_id, material_id)
    if material is None:
        raise HTTPException(status_code=404, detail="Material not found")
    units = UnitsOfMeasureRepository(conn)
    unit = await units.get_by_id(unit_id)
    if unit is None or not unit.get("is_active", True):
        raise HTTPException(status_code=422, detail="unit_id is not a valid active unit")
    stock = await units.get_by_id(material["default_unit_id"]) if material.get("default_unit_id") else None
    answer = {
        "material": material["name"], "unit": unit["code"], "unit_name": unit["display_name"],
        "stock_unit": (stock or unit)["code"], "stock_unit_name": (stock or unit)["display_name"],
        "stock_unit_id": str((stock or unit)["id"]),
    }
    if stock is None or str(stock["id"]) == str(unit["id"]):
        return {**answer, "fits": True, "one_unit_equals": "1"}
    per = await _known_per_stock_unit(conn, auth_context.organization_id, material, unit, stock)
    one = f"{(Decimal(1) / per).quantize(Decimal('0.001')).normalize():f}" if per else None  # stored to 7 places
    return {**answer, "fits": per is not None, "one_unit_equals": one}


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
    try:
        name = require_latin_name(name)
    except MaterialNameError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
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
    if body.category_id is not None:
        await _require_category(conn, auth_context.organization_id, body.category_id)
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
        category_id=body.category_id,
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
    if name == existing["name"]:
        name = None  # unchanged: an old non-English name does not block editing other fields
    if name:
        try:
            name = require_latin_name(name)
        except MaterialNameError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        clash = await repo.get_by_name(
            auth_context.organization_id, name, exclude_id=material_id
        )
        if clash is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Another Material is already named '{clash['name']}'.",
            )

    set_category_id = "category_id" in body.model_fields_set
    if set_category_id and body.category_id is not None and body.category_id != existing.get("category_id"):
        await _require_category(conn, auth_context.organization_id, body.category_id)

    updated = await repo.update(
        auth_context.organization_id,
        material_id,
        name=name,
        default_unit_id=default_unit_id,
        category=body.category,
        sku=body.sku,
        is_active=body.is_active,
        updated_by=auth_context.user_id,
        set_category_id=set_category_id,
        category_id=body.category_id,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Material not found")
    return updated


class MaterialAliasCreate(BaseModel):
    """Another name this company's people call the material ("primer" for Paint, "സിമന്റ്" for Cement)."""

    alias: str = Field(min_length=1, max_length=120)


@router.post("/{material_id}/aliases", status_code=201)
async def add_material_alias(
    material_id: uuid.UUID,
    body: MaterialAliasCreate,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """[210]: remember a word for a material, for the whole company, so it finds that material next time.
    Any script (the catalogue name stays English). A word already used for another material is refused."""
    repo = PostgresMaterialCatalogRepository(conn)
    existing = await repo.get_by_id(auth_context.organization_id, material_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Material not found")
    alias = body.alias.strip()
    other = await repo.find_by_alias(auth_context.organization_id, alias)
    if other is not None and str(other["id"]) != str(material_id):
        raise HTTPException(status_code=409, detail=f"'{alias}' is already a name for {other['name']}.")
    await repo.add_alias(auth_context.organization_id, material_id, alias, auth_context.user_id)
    return {"material_id": str(material_id), "name": existing["name"], "alias": alias}


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
    category_id: uuid.UUID | None = Query(
        default=None, description="Only materials in this category; a main category includes its sub-categories."
    ),
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
        category_id=category_id,
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
    category_id: uuid.UUID | None = Query(
        default=None, description="Only materials in this category; a main category includes its sub-categories."
    ),
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
        category_id=category_id,
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
    category_id: uuid.UUID | None = Query(
        default=None, description="Only materials in this category; a main category includes its sub-categories."
    ),
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Get aggregated material inventory (stock levels), derived from the movement ledger.
    Each row names its category (PRC-17a)."""
    project_ids, denied = _resolve_project_ids(auth_context, project_id)
    if denied or _site_filter_denied(auth_context, project_id, site_id):
        return []

    repo = PostgresMaterialReadRepository(conn)
    return await repo.get_stock_levels(
        organization_id=auth_context.organization_id,
        project_ids=project_ids,
        site_id=site_id,
        material_id=material_id,
        category_id=category_id,
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
    # WA-119: valid values shown in the schema; validation unchanged (422 on another value).
    movement_reason: str = Field(default="RECEIVED", json_schema_extra={"enum": list(RECEIPT_REASONS)})
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
    movement_reason: str = Field(default="CONSUMED", json_schema_extra={"enum": list(USAGE_REASONS)})
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


async def _known_per_stock_unit(
    conn: AsyncConnection, organization_id: uuid.UUID, material: dict, unit: dict, stock: dict
) -> Decimal | None:
    """How many ``unit`` make one Stock Unit of ``material``: the company's own conversion (WA-41), else a fixed one;
    None when neither is known. The one place this is decided: saving converts with it, ``unit-check`` reports it."""
    from mesiri.domains.materials.unit_conversion import built_in_per_stock_unit
    from mesiri.infrastructure.postgres.repositories.material_unit_conversions import (
        PostgresMaterialUnitConversionRepository,
    )

    per = await PostgresMaterialUnitConversionRepository(conn).get(
        organization_id=organization_id, material_id=material["id"], from_unit_id=unit["id"]
    ) or built_in_per_stock_unit(str(unit["code"]), str(stock["code"]), str(material["name"]))
    return per if per is not None and per > 0 else None


async def _convert_to_stock_unit(conn: AsyncConnection, organization_id: uuid.UUID, body: Any) -> str | None:
    """2 Nov 2026 (Ilan, Paraclette: "10 TMT steel bars used", TMT stocked in kg): a quantity reported in another
    unit is converted into the material's Stock Unit when the conversion is known -- the company's own
    (material_unit_conversions, WA-41) or a fixed one (kg/tonnes, cft/m3/brass, cement bags, steel bars by
    diameter). The body is rewritten in place (quantity, unit, a rate per unit) and the note keeps what was
    reported. Unknown: nothing changes, and the Stock Unit check below refuses with the unit it needs."""
    from mesiri.domains.materials.unit_conversion import to_stock_quantity

    material = await PostgresMaterialCatalogRepository(conn).get_by_id(organization_id, body.material_id)
    if not material or material.get("default_unit_id") is None or str(material["default_unit_id"]) == str(body.unit_id):
        return None
    units = UnitsOfMeasureRepository(conn)
    unit, stock = await units.get_by_id(body.unit_id), await units.get_by_id(material["default_unit_id"])
    if not unit or not stock:
        return None
    per = await _known_per_stock_unit(conn, organization_id, material, unit, stock)
    if per is None:
        return None
    said = f"{Decimal(str(body.quantity)).normalize():f} {unit['display_name']}"
    reported = f"reported as {said}"
    body.quantity = to_stock_quantity(body.quantity, per)
    body.unit_id = stock["id"]
    if getattr(body, "unit_cost", None) is not None:
        body.unit_cost = (Decimal(str(body.unit_cost)) * per).quantize(Decimal("0.01"))
    body.notes = f"{body.notes.strip()} ({reported})" if getattr(body, "notes", None) else reported
    # Said back to the person (2 Nov: Ilan saw only "Saved ✅ 10 TMT steel bars", not that it went in as 0.5 load).
    return f"{said} = {Decimal(str(body.quantity)).normalize():f} {stock['code']}"


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
        # 2 Nov: the material row carries only the unit's id, so this said "(expected None)".
        stock = await units_repo.get_by_id(material["default_unit_id"])
        expected = (stock or {}).get("code") or material.get("default_unit") or "its stock unit"
        raise HTTPException(
            status_code=422,
            detail=(
                f"unit_id does not match {material['name']}'s Stock Unit "
                f"(expected {expected}); no conversion from {unit['display_name']} is set "
                f"(PUT /materials/{material['id']}/unit-conversions sets one)"
            ),
        )
    return material, unit


async def _assert_no_opening_stock(
    conn: AsyncConnection,
    organization_id: uuid.UUID,
    site_id: uuid.UUID | None,
    material: dict,
) -> None:
    """Opening stock is entered once per site+material (BE-12); the rule lives
    in ``transfers.py`` so the WhatsApp save applies the same one."""
    try:
        await assert_no_opening_stock(conn, organization_id, site_id, material)
    except MaterialRuleError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


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
    if body.movement_reason in ELEVATED_REASONS and not role_can_adjust(auth_context.role):
        raise HTTPException(status_code=403, detail="Not authorized to record adjustment movements")
    if body.quantity <= 0:
        raise HTTPException(status_code=422, detail="quantity must be greater than zero")

    _authorize_write(auth_context, body.project_id, body.site_id)
    if body.site_id is not None:
        await _assert_site_in_project(
            conn, auth_context.organization_id, body.project_id, body.site_id
        )

    converted = await _convert_to_stock_unit(conn, auth_context.organization_id, body)
    material, unit = await _resolve_and_validate_material_unit(
        conn, auth_context.organization_id, body.material_id, body.unit_id
    )
    if body.movement_reason == OPENING_STOCK:
        await _assert_no_opening_stock(conn, auth_context.organization_id, body.site_id, material)
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
    result = {"id": row_id, "status": "success", **({"converted": converted} if converted else {})}
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

    converted = await _convert_to_stock_unit(conn, auth_context.organization_id, body)
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
    result = {"id": row_id, "status": "success", **({"converted": converted} if converted else {})}
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


# ---------------------------------------------------------------------------
# Transfers between sites (BE-32)
# ---------------------------------------------------------------------------
class MaterialTransferCreate(BaseModel):
    from_site_id: uuid.UUID
    to_site_id: uuid.UUID
    material_id: uuid.UUID
    unit_id: uuid.UUID
    quantity: Decimal
    occurred_date: datetime.date
    notes: str | None = None
    # Same guard as an outflow: refuse to send more than the sending site
    # holds unless the user confirmed it. Off by default -- this endpoint is
    # new, so no caller relies on the outflow route's permissive default.
    allow_negative: bool = False


async def _site_project_id(
    conn: AsyncConnection, organization_id: uuid.UUID, site_id: uuid.UUID
) -> uuid.UUID:
    row = (
        await conn.execute(
            text("SELECT project_id FROM sites WHERE id = :site_id AND organization_id = :org_id"),
            {"site_id": site_id, "org_id": organization_id},
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=422, detail="Site not found")
    return row[0]


@router.post("/transfers", status_code=201)
async def create_transfer(
    body: MaterialTransferCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Move material from one site's stock into another's, as one record.

    Writes a TRANSFER_OUT outflow at the sending site and a TRANSFER_IN
    inflow at the receiving one, each with its ledger movement, in the
    request's one transaction and sharing `transfer_id` -- so a transfer is
    never half-recorded. The sites may be in different projects (leftover
    shuttering moved to the next job); the caller needs write access to both.
    """
    if idempotency_key:
        replayed = await _claim_idempotency_key(conn, idempotency_key, "material_transfer_rest")
        if replayed is not None:
            return {**replayed, "status": "replayed"}
    if body.quantity <= 0:
        raise HTTPException(status_code=422, detail="quantity must be greater than zero")
    if body.from_site_id == body.to_site_id:
        raise HTTPException(status_code=422, detail="A transfer needs two different sites")

    org_id = auth_context.organization_id
    from_project_id = await _site_project_id(conn, org_id, body.from_site_id)
    to_project_id = await _site_project_id(conn, org_id, body.to_site_id)
    _authorize_write(auth_context, from_project_id, body.from_site_id)
    _authorize_write(auth_context, to_project_id, body.to_site_id)

    converted = await _convert_to_stock_unit(conn, org_id, body)
    material, unit = await _resolve_and_validate_material_unit(
        conn, org_id, body.material_id, body.unit_id
    )

    try:
        ids = await record_transfer(
            conn,
            organization_id=org_id,
            user_id=auth_context.user_id,
            material=material,
            unit=unit,
            from_project_id=from_project_id,
            from_site_id=body.from_site_id,
            to_project_id=to_project_id,
            to_site_id=body.to_site_id,
            quantity=body.quantity,
            occurred_date=body.occurred_date,
            notes=body.notes,
            allow_negative=body.allow_negative,
            publish_event=_publish_outbox_event,
        )
    except MaterialRuleError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    result = {
        "id": ids.transfer_id,
        "outflow_id": ids.outflow_id,
        "inflow_id": ids.inflow_id,
        "status": "success",
        **({"converted": converted} if converted else {}),
    }
    if idempotency_key:
        await _complete_idempotency_key(conn, idempotency_key, result)
    return result


@router.get("/transfers")
async def list_transfers(
    project_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Transfers that leave or enter a project the caller can see, newest first."""
    project_ids, denied = _resolve_project_ids(auth_context, project_id)
    if denied:
        return {"items": [], "total": 0}
    scope = ""
    params: dict[str, Any] = {"org_id": auth_context.organization_id, "limit": limit, "offset": offset}
    if project_ids is not None:
        scope = "AND (u.project_id = ANY(:project_ids) OR r.project_id = ANY(:project_ids))"
        params["project_ids"] = list(project_ids)
    rows = (
        await conn.execute(
            text(
                f"""
                SELECT u.transfer_id AS id, u.material_id, u.material_name, u.quantity, u.unit,
                       u.occurred_date, u.notes, u.created_by,
                       u.id AS outflow_id, u.project_id AS from_project_id,
                       u.site_id AS from_site_id, fs.name AS from_site_name,
                       r.id AS inflow_id, r.project_id AS to_project_id,
                       r.site_id AS to_site_id, ts.name AS to_site_name,
                       EXISTS (SELECT 1 FROM material_receipts c
                               WHERE c.reverses_movement_id = u.id) AS is_reversed,
                       COUNT(*) OVER () AS total
                FROM material_usage u
                JOIN material_receipts r ON r.transfer_id = u.transfer_id
                LEFT JOIN sites fs ON fs.id = u.site_id
                LEFT JOIN sites ts ON ts.id = r.site_id
                WHERE u.organization_id = :org_id AND u.transfer_id IS NOT NULL {scope}
                ORDER BY u.occurred_date DESC, u.created_at DESC
                LIMIT :limit OFFSET :offset
                """  # noqa: S608 - `scope` is one of two fixed strings
            ),
            params,
        )
    ).mappings().all()
    total = rows[0]["total"] if rows else 0
    return {"items": [{k: v for k, v in r.items() if k != "total"} for r in rows], "total": total}


@router.post("/transfers/{transfer_id}/reverse", status_code=201)
async def reverse_transfer(
    transfer_id: uuid.UUID,
    body: MaterialReversalCreate,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Correct a transfer: both halves are reversed together, through the same
    correction as any inflow/outflow, so stock goes back to where it was at
    both sites. Never one half alone."""
    if not role_can_adjust(auth_context.role):
        raise HTTPException(status_code=403, detail="Not authorized to correct movements")
    correction_ids = await reverse_transfer_record(
        conn,
        transfer_id=transfer_id,
        organization_id=auth_context.organization_id,
        user_id=auth_context.user_id,
        reason_note=body.reason_note,
        occurred_date=body.occurred_date,
        authorize=lambda original: _authorize_write(
            auth_context, original["project_id"], original["site_id"]
        ),
    )
    return {"id": transfer_id, "correction_ids": correction_ids, "status": "success"}


async def reverse_transfer_record(
    conn: AsyncConnection,
    *,
    transfer_id: uuid.UUID,
    organization_id: uuid.UUID,
    user_id: uuid.UUID | None,
    reason_note: str | None,
    occurred_date: datetime.date | None = None,
    authorize: Callable[[dict], None] | None = None,
) -> list[uuid.UUID]:
    """Reverse both halves of a transfer together (never one alone) -- the one
    implementation behind the web route and a rejected WhatsApp draft."""
    halves = (
        await conn.execute(
            text(
                "SELECT 'usage' AS kind, id FROM material_usage "
                "WHERE organization_id = :org_id AND transfer_id = :transfer_id "
                "UNION ALL "
                "SELECT 'receipt' AS kind, id FROM material_receipts "
                "WHERE organization_id = :org_id AND transfer_id = :transfer_id"
            ),
            {"org_id": organization_id, "transfer_id": transfer_id},
        )
    ).all()
    if not halves:
        raise HTTPException(status_code=404, detail="Transfer not found")

    correction_ids = []
    for kind, record_id in sorted(halves, key=lambda h: h[0] != "usage"):
        correction_ids.append(
            await reverse_material_record(
                conn,
                kind=kind,
                record_id=record_id,
                organization_id=organization_id,
                user_id=user_id,
                reason_note=reason_note,
                occurred_date=occurred_date,
                authorize=authorize,
                transfer_half=True,
            )
        )
    return correction_ids


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
    transfer_half: bool = False,
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
    if original.get("transfer_id") is not None and not transfer_half:
        # Correcting one half alone would leave the other site's stock wrong.
        raise HTTPException(
            status_code=409,
            detail="This movement is part of a transfer between sites. Correct the transfer.",
        )
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
