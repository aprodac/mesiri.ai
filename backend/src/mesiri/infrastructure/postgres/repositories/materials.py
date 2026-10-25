from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.application.dpr import fact_review

_material_receipts = sa.Table(
    "material_receipts",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True)),
    sa.Column("organization_id", sa.UUID(as_uuid=True)),
    sa.Column("project_id", sa.UUID(as_uuid=True)),
    sa.Column("site_id", sa.UUID(as_uuid=True)),
    sa.Column("material_name", sa.String),
    sa.Column("quantity", sa.Numeric),
    sa.Column("unit", sa.String),
    sa.Column("unit_id", sa.UUID(as_uuid=True)),
    sa.Column("transfer_id", sa.UUID(as_uuid=True)),
    # WEB-35: set when the purchase came from a supplier invoice.
    sa.Column("invoice_id", sa.UUID(as_uuid=True)),
    sa.Column("unit_cost", sa.Numeric),
    sa.Column("total_cost", sa.Numeric),
    sa.Column("supplier", sa.String),
    sa.Column("occurred_date", sa.Date),
    sa.Column("occurred_time", sa.Time),
    sa.Column("correlation_id", sa.String),
    sa.Column("source", sa.String),
    sa.Column("occurred_date_source", sa.String),
    sa.Column("material_id", sa.UUID(as_uuid=True)),
    sa.Column("movement_reason", sa.String),
    sa.Column("notes", sa.String),
    sa.Column("reverses_movement_id", sa.UUID(as_uuid=True)),
    sa.Column("created_at", sa.DateTime(timezone=True)),
    sa.Column("created_by", sa.UUID(as_uuid=True)),
    sa.Column("updated_at", sa.DateTime(timezone=True)),
    sa.Column("updated_by", sa.UUID(as_uuid=True)),
)

_material_usage = sa.Table(
    "material_usage",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True)),
    sa.Column("organization_id", sa.UUID(as_uuid=True)),
    sa.Column("project_id", sa.UUID(as_uuid=True)),
    sa.Column("site_id", sa.UUID(as_uuid=True)),
    sa.Column("material_name", sa.String),
    sa.Column("quantity", sa.Numeric),
    sa.Column("unit", sa.String),
    sa.Column("unit_id", sa.UUID(as_uuid=True)),
    sa.Column("transfer_id", sa.UUID(as_uuid=True)),
    sa.Column("work_item", sa.String),
    sa.Column("occurred_date", sa.Date),
    sa.Column("occurred_time", sa.Time),
    sa.Column("correlation_id", sa.String),
    sa.Column("source", sa.String),
    sa.Column("occurred_date_source", sa.String),
    sa.Column("material_id", sa.UUID(as_uuid=True)),
    sa.Column("movement_reason", sa.String),
    sa.Column("notes", sa.String),
    sa.Column("reverses_movement_id", sa.UUID(as_uuid=True)),
    sa.Column("created_at", sa.DateTime(timezone=True)),
    sa.Column("created_by", sa.UUID(as_uuid=True)),
    sa.Column("updated_at", sa.DateTime(timezone=True)),
    sa.Column("updated_by", sa.UUID(as_uuid=True)),
)

_materials_catalog = sa.Table(
    "materials_catalog",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True)),
    sa.Column("organization_id", sa.UUID(as_uuid=True)),
    sa.Column("name", sa.String),
    sa.Column("default_unit", sa.String),
    sa.Column("default_unit_id", sa.UUID(as_uuid=True)),
    sa.Column("category", sa.String),
    sa.Column("sku", sa.String),
    sa.Column("is_active", sa.Boolean),
    sa.Column("created_at", sa.DateTime(timezone=True)),
    sa.Column("created_by", sa.UUID(as_uuid=True)),
    sa.Column("updated_at", sa.DateTime(timezone=True)),
    sa.Column("updated_by", sa.UUID(as_uuid=True)),
)

_units_of_measure = sa.Table(
    "units_of_measure",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True)),
    sa.Column("code", sa.String),
    sa.Column("display_name", sa.String),
    sa.Column("is_active", sa.Boolean),
    sa.Column("created_at", sa.DateTime(timezone=True)),
    sa.Column("updated_at", sa.DateTime(timezone=True)),
)

_unit_aliases = sa.Table(
    "unit_aliases",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True)),
    sa.Column("unit_id", sa.UUID(as_uuid=True)),
    sa.Column("alias_text", sa.String),
    sa.Column("created_at", sa.DateTime(timezone=True)),
)

_material_movements = sa.Table(
    "material_movements",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True)),
    sa.Column("organization_id", sa.UUID(as_uuid=True)),
    sa.Column("project_id", sa.UUID(as_uuid=True)),
    sa.Column("site_id", sa.UUID(as_uuid=True)),
    sa.Column("material_id", sa.UUID(as_uuid=True)),
    sa.Column("unit_id", sa.UUID(as_uuid=True)),
    sa.Column("movement_type", sa.String),
    sa.Column("quantity", sa.Numeric),
    sa.Column("occurred_at", sa.DateTime(timezone=True)),
    sa.Column("source_type", sa.String),
    sa.Column("source_id", sa.UUID(as_uuid=True)),
    sa.Column("recorded_by_user_id", sa.UUID(as_uuid=True)),
    sa.Column("reversal_of_movement_id", sa.UUID(as_uuid=True)),
    sa.Column("idempotency_key", sa.String),
    sa.Column("created_at", sa.DateTime(timezone=True)),
)


def _receipt_where(
    organization_id: uuid.UUID,
    project_ids: set[uuid.UUID] | None,
    site_id: uuid.UUID | None,
    material_id: uuid.UUID | None,
    material_name: str | None,
    movement_reason: str | None,
    source: str | None,
    recorded_by_user_id: uuid.UUID | None,
    date_from: datetime.date | None,
    date_to: datetime.date | None,
) -> list:
    where_clauses = [_material_receipts.c.organization_id == organization_id]
    if project_ids is not None:
        where_clauses.append(_material_receipts.c.project_id.in_(project_ids))
    if site_id is not None:
        where_clauses.append(_material_receipts.c.site_id == site_id)
    if material_id is not None:
        where_clauses.append(_material_receipts.c.material_id == material_id)
    if material_name is not None:
        where_clauses.append(_material_receipts.c.material_name.ilike(f"%{material_name}%"))
    if movement_reason is not None:
        where_clauses.append(_material_receipts.c.movement_reason == movement_reason)
    if source is not None:
        where_clauses.append(_material_receipts.c.source == source)
    if recorded_by_user_id is not None:
        where_clauses.append(_material_receipts.c.created_by == recorded_by_user_id)
    if date_from is not None:
        where_clauses.append(_material_receipts.c.occurred_date >= date_from)
    if date_to is not None:
        where_clauses.append(_material_receipts.c.occurred_date <= date_to)
    return where_clauses


def _usage_where(
    organization_id: uuid.UUID,
    project_ids: set[uuid.UUID] | None,
    site_id: uuid.UUID | None,
    material_id: uuid.UUID | None,
    material_name: str | None,
    movement_reason: str | None,
    source: str | None,
    recorded_by_user_id: uuid.UUID | None,
    date_from: datetime.date | None,
    date_to: datetime.date | None,
) -> list:
    where_clauses = [_material_usage.c.organization_id == organization_id]
    if project_ids is not None:
        where_clauses.append(_material_usage.c.project_id.in_(project_ids))
    if site_id is not None:
        where_clauses.append(_material_usage.c.site_id == site_id)
    if material_id is not None:
        where_clauses.append(_material_usage.c.material_id == material_id)
    if material_name is not None:
        where_clauses.append(_material_usage.c.material_name.ilike(f"%{material_name}%"))
    if movement_reason is not None:
        where_clauses.append(_material_usage.c.movement_reason == movement_reason)
    if source is not None:
        where_clauses.append(_material_usage.c.source == source)
    if recorded_by_user_id is not None:
        where_clauses.append(_material_usage.c.created_by == recorded_by_user_id)
    if date_from is not None:
        where_clauses.append(_material_usage.c.occurred_date >= date_from)
    if date_to is not None:
        where_clauses.append(_material_usage.c.occurred_date <= date_to)
    return where_clauses


class PostgresMaterialReadRepository:
    """PostgreSQL read-side repository for material inflows, outflows, and stock levels."""

    def __init__(self, conn: AsyncConnection):
        self.conn = conn

    async def list_receipts(
        self,
        organization_id: uuid.UUID,
        project_ids: set[uuid.UUID] | None = None,
        site_id: uuid.UUID | None = None,
        material_id: uuid.UUID | None = None,
        material_name: str | None = None,
        movement_reason: str | None = None,
        source: str | None = None,
        recorded_by_user_id: uuid.UUID | None = None,
        date_from: datetime.date | None = None,
        date_to: datetime.date | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """List material receipts (inflows) matching parameters, with total count."""
        where_clauses = _receipt_where(
            organization_id,
            project_ids,
            site_id,
            material_id,
            material_name,
            movement_reason,
            source,
            recorded_by_user_id,
            date_from,
            date_to,
        )

        count_stmt = (
            sa.select(sa.func.count()).select_from(_material_receipts).where(*where_clauses)
        )
        total = (await self.conn.execute(count_stmt)).scalar_one()

        # A reversed purchase was not actually spent, so any cost total that
        # counted it would overstate what the company paid. Surfaced per row
        # rather than filtered out, because the purchase still happened and
        # still belongs in the history -- it is the money that has to net off.
        # Cheap: 0459's partial unique index covers reverses_movement_id.
        is_reversed = sa.exists(
            sa.select(sa.literal(1))
            .select_from(_material_usage)
            .where(_material_usage.c.reverses_movement_id == _material_receipts.c.id)
        ).label("is_reversed")

        stmt = (
            sa.select(_material_receipts, is_reversed)
            .where(*where_clauses)
            .order_by(
                _material_receipts.c.occurred_date.desc(), _material_receipts.c.created_at.desc()
            )
            .limit(limit)
            .offset(offset)
        )
        res = await self.conn.execute(stmt)
        items = [dict(r) for r in res.mappings().all()]
        return items, total

    async def get_receipt(self, organization_id: uuid.UUID, receipt_id: uuid.UUID) -> dict | None:
        stmt = sa.select(_material_receipts).where(
            _material_receipts.c.id == receipt_id,
            _material_receipts.c.organization_id == organization_id,
        )
        res = await self.conn.execute(stmt)
        row = res.mappings().first()
        return dict(row) if row else None

    async def list_usage(
        self,
        organization_id: uuid.UUID,
        project_ids: set[uuid.UUID] | None = None,
        site_id: uuid.UUID | None = None,
        material_id: uuid.UUID | None = None,
        material_name: str | None = None,
        movement_reason: str | None = None,
        source: str | None = None,
        recorded_by_user_id: uuid.UUID | None = None,
        date_from: datetime.date | None = None,
        date_to: datetime.date | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """List material usages (outflows) matching parameters, with total count."""
        where_clauses = _usage_where(
            organization_id,
            project_ids,
            site_id,
            material_id,
            material_name,
            movement_reason,
            source,
            recorded_by_user_id,
            date_from,
            date_to,
        )

        count_stmt = sa.select(sa.func.count()).select_from(_material_usage).where(*where_clauses)
        total = (await self.conn.execute(count_stmt)).scalar_one()

        stmt = (
            sa.select(_material_usage)
            .where(*where_clauses)
            .order_by(_material_usage.c.occurred_date.desc(), _material_usage.c.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        res = await self.conn.execute(stmt)
        items = [dict(r) for r in res.mappings().all()]
        return items, total

    async def get_usage(self, organization_id: uuid.UUID, usage_id: uuid.UUID) -> dict | None:
        stmt = sa.select(_material_usage).where(
            _material_usage.c.id == usage_id,
            _material_usage.c.organization_id == organization_id,
        )
        res = await self.conn.execute(stmt)
        row = res.mappings().first()
        return dict(row) if row else None

    async def get_stock_levels(
        self,
        organization_id: uuid.UUID,
        project_ids: set[uuid.UUID] | None = None,
        site_id: uuid.UUID | None = None,
        material_id: uuid.UUID | None = None,
        *,
        include_unsaved: bool = False,
    ) -> list[dict]:
        """Aggregated inventory stock levels, derived solely from material_movements.

        WA-77 (Alan, 25 Oct): stock is what is saved; an entry still waiting
        for its Save on WhatsApp is left out. `include_unsaved` counts it,
        for the over-stock hint while capturing (what was reported so far).

        RECEIPT movements add, ISSUE movements subtract; a reversal posts the
        opposite movement_type of what it corrects, so summing signed quantity
        per (org, project, site, material, unit) is the whole computation —
        no separate receipts-minus-usage query (see migration 0300).
        """
        signed_qty = sa.case(
            (_material_movements.c.movement_type == "RECEIPT", _material_movements.c.quantity),
            else_=-_material_movements.c.quantity,
        )
        # A reversal takes back what it corrects: reversing a receipt lowers
        # "received", it is not material used (and the other way round), so
        # the totals stay net of corrections and received - used = stock.
        is_reversal = _material_movements.c.reversal_of_movement_id.is_not(None)
        received = sa.func.sum(
            sa.case(
                (
                    sa.and_(_material_movements.c.movement_type == "RECEIPT", ~is_reversal),
                    _material_movements.c.quantity,
                ),
                (
                    sa.and_(_material_movements.c.movement_type == "ISSUE", is_reversal),
                    -_material_movements.c.quantity,
                ),
                else_=0,
            )
        )
        used = sa.func.sum(
            sa.case(
                (
                    sa.and_(_material_movements.c.movement_type == "ISSUE", ~is_reversal),
                    _material_movements.c.quantity,
                ),
                (
                    sa.and_(_material_movements.c.movement_type == "RECEIPT", is_reversal),
                    -_material_movements.c.quantity,
                ),
                else_=0,
            )
        )
        current_stock = sa.func.sum(signed_qty)

        stmt = sa.select(
            _material_movements.c.organization_id,
            _material_movements.c.project_id,
            _material_movements.c.site_id,
            _material_movements.c.material_id,
            _materials_catalog.c.name.label("material_name"),
            _units_of_measure.c.code.label("unit"),
            received.label("total_received"),
            used.label("total_used"),
            current_stock.label("current_stock"),
            sa.func.max(_material_movements.c.created_at).label("last_movement_at"),
        ).select_from(
            _material_movements.join(
                _materials_catalog, _materials_catalog.c.id == _material_movements.c.material_id
            ).join(_units_of_measure, _units_of_measure.c.id == _material_movements.c.unit_id)
        ).where(_material_movements.c.organization_id == organization_id)

        if not include_unsaved:
            stmt = stmt.where(sa.text(fact_review.movement_counted_sql("material_movements")))
        if project_ids is not None:
            stmt = stmt.where(_material_movements.c.project_id.in_(project_ids))
        if site_id is not None:
            stmt = stmt.where(_material_movements.c.site_id == site_id)
        if material_id is not None:
            stmt = stmt.where(_material_movements.c.material_id == material_id)

        stmt = stmt.group_by(
            _material_movements.c.organization_id,
            _material_movements.c.project_id,
            _material_movements.c.site_id,
            _material_movements.c.material_id,
            _materials_catalog.c.name,
            _units_of_measure.c.code,
        ).order_by(_materials_catalog.c.name.asc())

        res = await self.conn.execute(stmt)
        rows = [dict(r) for r in res.mappings().all()]
        for row in rows:
            stock = row["current_stock"]
            row["stock_state"] = (
                "NEGATIVE_STOCK" if stock < 0 else "OUT_OF_STOCK" if stock == 0 else "AVAILABLE"
            )
        return rows

    async def get_last_purchase_price(
        self, organization_id: uuid.UUID, material_id: uuid.UUID
    ) -> dict | None:
        """The most recent recorded rate for a material, org-wide.

        Shown while recording a delivery so a rate that has jumped is noticed
        at the moment it can still be questioned, rather than in a report three
        weeks later. Org-wide rather than per-site on purpose: the price a
        supplier charges is a commercial fact about the company, not about one
        site, and per-site would return nothing for a site's first delivery --
        exactly when the check is most useful.

        Rows with no recorded cost are skipped rather than treated as zero.
        """
        stmt = (
            sa.select(
                _material_receipts.c.unit_cost,
                _material_receipts.c.total_cost,
                _material_receipts.c.occurred_date,
                _material_receipts.c.supplier,
                _material_receipts.c.unit,
            )
            .where(
                _material_receipts.c.organization_id == organization_id,
                _material_receipts.c.material_id == material_id,
                _material_receipts.c.unit_cost.isnot(None),
            )
            .order_by(
                _material_receipts.c.occurred_date.desc(),
                _material_receipts.c.created_at.desc(),
            )
            .limit(1)
        )
        res = await self.conn.execute(stmt)
        row = res.mappings().first()
        return dict(row) if row else None

    async def find_reversal_of(
        self, organization_id: uuid.UUID, original_id: uuid.UUID
    ) -> dict | None:
        """The correcting row already posted against `original_id`, if any.

        A reversal of a receipt is written into material_usage and vice versa,
        so both tables are checked -- the caller knows which direction it is
        correcting, but not which table an earlier correction landed in if the
        data predates that convention.
        """
        for table in (_material_receipts, _material_usage):
            res = await self.conn.execute(
                sa.select(
                    table.c.id, table.c.occurred_date, table.c.created_at, table.c.created_by
                ).where(
                    table.c.organization_id == organization_id,
                    table.c.reverses_movement_id == original_id,
                )
            )
            row = res.mappings().first()
            if row is not None:
                return dict(row)
        return None

    async def lock_stock_for_update(
        self, site_id: uuid.UUID | None, material_id: uuid.UUID
    ) -> None:
        """Serialise concurrent stock decisions for one site+material.

        Stock is a SUM over rows that do not exist yet, so there is no row to
        SELECT ... FOR UPDATE. Without this, two outflows racing against the
        same balance both read "10 available", both pass the guard, and both
        insert -- the check is worthless in exactly the case it exists for.

        Transaction-scoped: released on COMMIT or ROLLBACK with no cleanup path
        to forget. Only writers touching the SAME site+material contend; every
        other material, site, project and module is unaffected. A single lock
        with no ordering cannot deadlock.
        """
        await self.conn.execute(
            sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"{site_id}:{material_id}"},
        )

    async def get_available_stock(
        self,
        organization_id: uuid.UUID,
        site_id: uuid.UUID | None,
        material_id: uuid.UUID,
    ) -> Decimal:
        """Current balance for one site+material, from the movement ledger.

        Returns 0 when the material has never moved at this site -- which is
        the truthful answer, not a missing one: you cannot issue what was never
        received.
        """
        signed_qty = sa.case(
            (_material_movements.c.movement_type == "RECEIPT", _material_movements.c.quantity),
            else_=-_material_movements.c.quantity,
        )
        where = [
            _material_movements.c.organization_id == organization_id,
            _material_movements.c.material_id == material_id,
        ]
        where.append(
            _material_movements.c.site_id.is_(None)
            if site_id is None
            else _material_movements.c.site_id == site_id
        )
        res = await self.conn.execute(sa.select(sa.func.sum(signed_qty)).where(*where))
        return res.scalar_one_or_none() or Decimal("0")

    async def get_ledger(
        self,
        organization_id: uuid.UUID,
        site_id: uuid.UUID,
        material_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """Chronological IN+OUT movement history for one Site + Material, with running balance.

        Reads directly from material_movements as the single source of truth,
        left-joining material_receipts/material_usage to resolve rich audit metadata.
        Computes running balance via window function, returning in newest-first order.
        """
        stmt_base = (
            sa.select(
                _material_movements.c.id,
                sa.case(
                    (_material_movements.c.movement_type == "RECEIPT", "IN"),
                    else_="OUT"
                ).label("direction"),
                sa.func.coalesce(
                    _material_receipts.c.movement_reason,
                    _material_usage.c.movement_reason,
                    _material_movements.c.movement_type,
                ).label("movement_reason"),
                _material_movements.c.quantity,
                _units_of_measure.c.code.label("unit"),
                sa.func.coalesce(
                    _material_receipts.c.occurred_date,
                    _material_usage.c.occurred_date,
                    sa.cast(_material_movements.c.occurred_at, sa.Date),
                ).label("occurred_date"),
                sa.func.coalesce(
                    _material_receipts.c.occurred_time,
                    _material_usage.c.occurred_time,
                    sa.cast(_material_movements.c.occurred_at, sa.Time),
                ).label("occurred_time"),
                sa.func.coalesce(
                    _material_receipts.c.source,
                    _material_usage.c.source,
                    sa.literal("system"),
                ).label("source"),
                sa.func.coalesce(
                    _material_receipts.c.notes,
                    _material_usage.c.notes
                ).label("notes"),
                sa.func.coalesce(
                    _material_receipts.c.supplier,
                    _material_usage.c.work_item
                ).label("context"),
                sa.func.coalesce(
                    _material_receipts.c.reverses_movement_id,
                    _material_usage.c.reverses_movement_id
                ).label("reverses_movement_id"),
                sa.func.coalesce(
                    _material_movements.c.recorded_by_user_id,
                    _material_receipts.c.created_by,
                    _material_usage.c.created_by,
                ).label("created_by"),
                _material_movements.c.created_at,
            )
            .select_from(
                _material_movements.join(
                    _units_of_measure,
                    _units_of_measure.c.id == _material_movements.c.unit_id
                )
                .outerjoin(
                    _material_receipts,
                    sa.and_(
                        _material_movements.c.source_id == _material_receipts.c.id,
                        _material_movements.c.source_type == "material_receipt"
                    )
                )
                .outerjoin(
                    _material_usage,
                    sa.and_(
                        _material_movements.c.source_id == _material_usage.c.id,
                        _material_movements.c.source_type == "material_usage"
                    )
                )
            )
            .where(
                _material_movements.c.organization_id == organization_id,
                _material_movements.c.site_id == site_id,
                _material_movements.c.material_id == material_id,
                # WA-77: the ledger is what is saved (an unsaved entry isn't in it yet).
                sa.text(fact_review.movement_counted_sql("material_movements")),
            )
        )

        combined = stmt_base.cte("ledger_combined")

        signed_qty = sa.case(
            (combined.c.direction == "IN", combined.c.quantity),
            else_=-combined.c.quantity,
        )
        running_balance = sa.func.sum(signed_qty).over(
            order_by=[combined.c.occurred_date.asc(), combined.c.created_at.asc()]
        )

        with_balance = sa.select(combined, running_balance.label("running_balance")).cte(
            "ledger_with_balance"
        )

        total = (
            await self.conn.execute(sa.select(sa.func.count()).select_from(with_balance))
        ).scalar_one()

        stmt = (
            sa.select(with_balance)
            .order_by(with_balance.c.occurred_date.desc(), with_balance.c.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        res = await self.conn.execute(stmt)
        items = [dict(r) for r in res.mappings().all()]
        return items, total


class PostgresMaterialCatalogRepository:
    """PostgreSQL repository for the org-scoped Material catalog."""

    def __init__(self, conn: AsyncConnection):
        self.conn = conn

    async def list_materials(
        self,
        organization_id: uuid.UUID,
        search: str | None = None,
        is_active: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        where_clauses = [_materials_catalog.c.organization_id == organization_id]
        if search is not None:
            where_clauses.append(_materials_catalog.c.name.ilike(f"%{search}%"))
        if is_active is not None:
            where_clauses.append(_materials_catalog.c.is_active == is_active)

        count_stmt = (
            sa.select(sa.func.count()).select_from(_materials_catalog).where(*where_clauses)
        )
        total = (await self.conn.execute(count_stmt)).scalar_one()

        stmt = (
            sa.select(_materials_catalog)
            .where(*where_clauses)
            .order_by(_materials_catalog.c.name.asc())
            .limit(limit)
            .offset(offset)
        )
        res = await self.conn.execute(stmt)
        items = [dict(r) for r in res.mappings().all()]
        return items, total

    async def get_by_id(self, organization_id: uuid.UUID, material_id: uuid.UUID) -> dict | None:
        stmt = sa.select(_materials_catalog).where(
            _materials_catalog.c.id == material_id,
            _materials_catalog.c.organization_id == organization_id,
        )
        res = await self.conn.execute(stmt)
        row = res.mappings().first()
        return dict(row) if row else None

    async def get_by_name(
        self, organization_id: uuid.UUID, name: str, *, exclude_id: uuid.UUID | None = None
    ) -> dict | None:
        """Case- and whitespace-insensitive name lookup within one organization.

        Matches migration 0459's `uq_materials_catalog_org_name_ci`, so the
        409 raised by create/update fires for exactly the names the database
        would reject. Exact-match here would let "cement" through when
        "Cement" exists and then fail on the constraint with a 500.

        `exclude_id` lets the update path ask "does any OTHER material own this
        name?" without matching the row being renamed.
        """
        where = [
            _materials_catalog.c.organization_id == organization_id,
            sa.func.lower(sa.func.btrim(_materials_catalog.c.name)) == name.strip().lower(),
        ]
        if exclude_id is not None:
            where.append(_materials_catalog.c.id != exclude_id)
        res = await self.conn.execute(sa.select(_materials_catalog).where(*where))
        row = res.mappings().first()
        return dict(row) if row else None

    async def find_by_name_exact_active(self, organization_id: uuid.UUID, name: str) -> dict | None:
        """Case-insensitive exact match against active catalog entries only."""
        stmt = sa.select(_materials_catalog).where(
            _materials_catalog.c.organization_id == organization_id,
            _materials_catalog.c.is_active.is_(True),
            sa.func.lower(_materials_catalog.c.name) == name.strip().lower(),
        )
        res = await self.conn.execute(stmt)
        row = res.mappings().first()
        return dict(row) if row else None

    async def find_by_name_fuzzy(
        self, organization_id: uuid.UUID, name: str, limit: int = 5
    ) -> list[dict]:
        """Substring/ILIKE match against active catalog entries — candidates for a
        WhatsApp disambiguation picker, never auto-accepted."""
        needle = name.strip()
        if not needle:
            return []
        stmt = (
            sa.select(_materials_catalog)
            .where(
                _materials_catalog.c.organization_id == organization_id,
                _materials_catalog.c.is_active.is_(True),
                _materials_catalog.c.name.ilike(f"%{needle}%"),
            )
            .order_by(_materials_catalog.c.name.asc())
            .limit(limit)
        )
        res = await self.conn.execute(stmt)
        return [dict(r) for r in res.mappings().all()]

    async def create(
        self,
        organization_id: uuid.UUID,
        name: str,
        default_unit: str | None,
        default_unit_id: uuid.UUID | None,
        category: str | None,
        sku: str | None,
        created_by: uuid.UUID,
    ) -> dict:
        new_id = uuid.uuid4()
        stmt = sa.insert(_materials_catalog).values(
            id=new_id,
            organization_id=organization_id,
            name=name,
            default_unit=default_unit,
            default_unit_id=default_unit_id,
            category=category,
            sku=sku,
            is_active=True,
            created_by=created_by,
        )
        await self.conn.execute(stmt)
        return await self.get_by_id(organization_id, new_id)  # type: ignore[return-value]

    async def update(
        self,
        organization_id: uuid.UUID,
        material_id: uuid.UUID,
        *,
        name: str | None = None,
        default_unit_id: uuid.UUID | None = None,
        category: str | None = None,
        sku: str | None = None,
        is_active: bool | None = None,
        updated_by: uuid.UUID,
    ) -> dict | None:
        values: dict = {"updated_by": updated_by}
        if name is not None:
            values["name"] = name
        if default_unit_id is not None:
            values["default_unit_id"] = default_unit_id
        if category is not None:
            values["category"] = category
        if sku is not None:
            values["sku"] = sku
        if is_active is not None:
            values["is_active"] = is_active
        stmt = (
            sa.update(_materials_catalog)
            .where(
                _materials_catalog.c.id == material_id,
                _materials_catalog.c.organization_id == organization_id,
            )
            .values(**values)
        )
        await self.conn.execute(stmt)
        return await self.get_by_id(organization_id, material_id)

    async def has_movements(self, material_id: uuid.UUID) -> bool:
        """True if any material_movements row already references this material —
        used to lock Stock Unit (default_unit_id) once movements exist."""
        stmt = (
            sa.select(sa.literal(1))
            .select_from(_material_movements)
            .where(_material_movements.c.material_id == material_id)
            .limit(1)
        )
        res = await self.conn.execute(stmt)
        return res.first() is not None

    async def delete_unused(self, organization_id: uuid.UUID, material_id: uuid.UUID) -> bool:
        """Delete a catalog row only when no immutable ledger movement references it."""
        no_movements = ~sa.exists(
            sa.select(sa.literal(1))
            .select_from(_material_movements)
            .where(_material_movements.c.material_id == material_id)
        )
        stmt = (
            sa.delete(_materials_catalog)
            .where(
                _materials_catalog.c.id == material_id,
                _materials_catalog.c.organization_id == organization_id,
                no_movements,
            )
            .returning(_materials_catalog.c.id)
        )
        res = await self.conn.execute(stmt)
        return res.scalar_one_or_none() is not None


class UnitsOfMeasureRepository:
    """PostgreSQL repository for the fixed global units_of_measure list + aliases."""

    def __init__(self, conn: AsyncConnection):
        self.conn = conn

    async def get_by_id(self, unit_id: uuid.UUID) -> dict | None:
        stmt = sa.select(_units_of_measure).where(_units_of_measure.c.id == unit_id)
        res = await self.conn.execute(stmt)
        row = res.mappings().first()
        return dict(row) if row else None

    async def get_by_code(self, code: str) -> dict | None:
        stmt = sa.select(_units_of_measure).where(_units_of_measure.c.code == code)
        res = await self.conn.execute(stmt)
        row = res.mappings().first()
        return dict(row) if row else None

    async def list_active(self) -> list[dict]:
        stmt = (
            sa.select(_units_of_measure)
            .where(_units_of_measure.c.is_active.is_(True))
            .order_by(_units_of_measure.c.display_name.asc())
        )
        res = await self.conn.execute(stmt)
        return [dict(r) for r in res.mappings().all()]

    async def resolve_alias(self, text_value: str) -> dict | None:
        """Resolve free text (exact code, known alias or display name,
        case/whitespace-insensitive) to its active canonical unit. No unit
        conversion -- spelling only.

        WRK-02: spacing, dots and the superscript digits do not matter either
        ("sq.ft", "sq ft", "sft"; "m²", "m3"): the text is tried as typed,
        then folded (``fold_unit_text``) against the aliases folded the same
        way. The exact spelling wins."""
        needle = text_value.strip().lower()
        if not needle:
            return None
        base = (
            sa.select(_units_of_measure)
            .select_from(
                _unit_aliases.join(_units_of_measure, _units_of_measure.c.id == _unit_aliases.c.unit_id)
            )
            .where(_units_of_measure.c.is_active.is_(True))
        )
        row = (await self.conn.execute(base.where(_unit_aliases.c.alias_text == needle))).mappings().first()
        if row is None:
            folded = fold_unit_text(needle)
            column = sa.func.regexp_replace(
                sa.func.translate(sa.func.lower(_unit_aliases.c.alias_text), "²³", "23"),
                "[^[:alnum:]%]", "", "g",
            )
            row = (
                await self.conn.execute(base.where(column == folded).order_by(_unit_aliases.c.created_at))
            ).mappings().first()
        if row is None:
            by_name = sa.select(_units_of_measure).where(
                sa.func.lower(_units_of_measure.c.display_name) == needle,
                _units_of_measure.c.is_active.is_(True),
            )
            row = (await self.conn.execute(by_name)).mappings().first()
        return dict(row) if row else None


def fold_unit_text(text_value: str) -> str:
    """"Sq. Ft" / "sq ft" / "SQFT" -> "sqft"; "m²" -> "m2": letters, digits and
    "%" only (SQL side: the same fold in ``resolve_alias``)."""
    translated = text_value.lower().translate(str.maketrans("²³", "23"))
    return "".join(ch for ch in translated if ch.isalnum() or ch == "%")


class MaterialMovementsRepository:
    """PostgreSQL repository for the immutable material_movements ledger.

    Insert-only: application code never UPDATEs or DELETEs a movement row.
    Corrections are posted as a new movement with reversal_of_movement_id set
    (see migration 0300's docstring and domains/materials/posting.py).
    """

    def __init__(self, conn: AsyncConnection):
        self.conn = conn

    async def insert(
        self,
        *,
        movement_id: uuid.UUID,
        organization_id: uuid.UUID,
        project_id: uuid.UUID,
        site_id: uuid.UUID | None,
        material_id: uuid.UUID,
        unit_id: uuid.UUID,
        movement_type: str,
        quantity,
        occurred_at,
        source_type: str,
        source_id: uuid.UUID,
        recorded_by_user_id: uuid.UUID,
        reversal_of_movement_id: uuid.UUID | None = None,
        idempotency_key: str | None = None,
    ) -> dict:
        stmt = sa.insert(_material_movements).values(
            id=movement_id,
            organization_id=organization_id,
            project_id=project_id,
            site_id=site_id,
            material_id=material_id,
            unit_id=unit_id,
            movement_type=movement_type,
            quantity=quantity,
            occurred_at=occurred_at,
            source_type=source_type,
            source_id=source_id,
            recorded_by_user_id=recorded_by_user_id,
            reversal_of_movement_id=reversal_of_movement_id,
            idempotency_key=idempotency_key,
        )
        await self.conn.execute(stmt)
        res = await self.conn.execute(
            sa.select(_material_movements).where(_material_movements.c.id == movement_id)
        )
        return dict(res.mappings().one())

    async def get_by_source(self, source_type: str, source_id: uuid.UUID) -> dict | None:
        stmt = sa.select(_material_movements).where(
            _material_movements.c.source_type == source_type,
            _material_movements.c.source_id == source_id,
            _material_movements.c.reversal_of_movement_id.is_(None),
        )
        res = await self.conn.execute(stmt)
        row = res.mappings().first()
        return dict(row) if row else None
