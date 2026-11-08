from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.domains.vendors.entities import Vendor

_vendors = sa.Table(
    "vendors",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True)),
    sa.Column("organization_id", sa.UUID(as_uuid=True)),
    sa.Column("name", sa.String),
    sa.Column("code", sa.String),
    sa.Column("status", sa.String),
    sa.Column("phone", sa.String),
    sa.Column("gstin", sa.String),
    sa.Column("address", sa.String),
    sa.Column("kind", sa.String),
    sa.Column("credit_days", sa.Integer),
    sa.Column("lead_time_days", sa.Integer),
    sa.Column("contact_person", sa.String),
    sa.Column("notes", sa.String),
    sa.Column("opening_balance", sa.Numeric),
    sa.Column("opening_balance_date", sa.Date),
    sa.Column("created_at", sa.DateTime(timezone=True)),
    sa.Column("created_by", sa.UUID(as_uuid=True)),
    sa.Column("updated_at", sa.DateTime(timezone=True)),
    sa.Column("updated_by", sa.UUID(as_uuid=True)),
)


from decimal import Decimal

_expenses = sa.Table(
    "expenses",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True)),
    sa.Column("organization_id", sa.UUID(as_uuid=True)),
    sa.Column("vendor_id", sa.UUID(as_uuid=True)),
    sa.Column("amount", sa.Numeric),
    sa.Column("workflow_status", sa.String),
)


def _row_to_vendor(row) -> Vendor:
    return Vendor(
        id=row.id,
        organization_id=row.organization_id,
        name=row.name,
        status=row.status,
        code=getattr(row, "code", None),
        phone=getattr(row, "phone", None),
        gstin=getattr(row, "gstin", None),
        address=getattr(row, "address", None),
    )


class PostgresVendorRepository:
    def __init__(self, conn: AsyncConnection):
        self.conn = conn

    async def list_active(self, organization_id: uuid.UUID) -> list[Vendor]:
        stmt = (
            sa.select(_vendors)
            .where(_vendors.c.organization_id == organization_id, _vendors.c.status == "active")
            .order_by(_vendors.c.name)
        )
        res = await self.conn.execute(stmt)
        return [_row_to_vendor(r) for r in res.mappings().all()]

    async def list_with_metrics(self, organization_id: uuid.UUID) -> list[dict]:
        """List all vendors for org along with expense count and total amount paid."""
        exp_count = sa.func.count(_expenses.c.id).label("expense_count")
        exp_sum = sa.func.coalesce(sa.func.sum(_expenses.c.amount), 0).label("total_amount")

        stmt = (
            sa.select(
                _vendors,
                exp_count,
                exp_sum,
            )
            .select_from(
                _vendors.outerjoin(
                    _expenses,
                    sa.and_(
                        _expenses.c.vendor_id == _vendors.c.id,
                        _expenses.c.workflow_status == "confirmed",
                    ),
                )
            )
            .where(_vendors.c.organization_id == organization_id)
            .group_by(_vendors.c.id)
            .order_by(exp_sum.desc(), _vendors.c.name.asc())
        )
        res = await self.conn.execute(stmt)
        results = []
        for row in res.mappings().all():
            vendor = _row_to_vendor(row)
            results.append({
                "vendor": vendor,
                "expense_count": row.expense_count,
                "total_amount": Decimal(row.total_amount),
            })
        return results

    async def get_by_id(self, organization_id: uuid.UUID, vendor_id: uuid.UUID) -> Vendor | None:
        stmt = sa.select(_vendors).where(
            _vendors.c.id == vendor_id, _vendors.c.organization_id == organization_id
        )
        res = await self.conn.execute(stmt)
        row = res.mappings().first()
        return _row_to_vendor(row) if row else None

    async def find_by_name_exact_active(
        self, organization_id: uuid.UUID, name: str
    ) -> Vendor | None:
        """Case-insensitive exact match against active vendors only."""
        stmt = sa.select(_vendors).where(
            _vendors.c.organization_id == organization_id,
            _vendors.c.status == "active",
            sa.func.lower(_vendors.c.name) == name.strip().lower(),
        )
        res = await self.conn.execute(stmt)
        row = res.mappings().first()
        return _row_to_vendor(row) if row else None

    async def create(
        self, organization_id: uuid.UUID, name: str, *, created_by: uuid.UUID
    ) -> Vendor:
        """Create-on-first-use: a new vendor name typed/spoken over WhatsApp
        becomes a real vendor row immediately."""
        # Compute next sequential VND-001 code for this organization
        seq_res = (
            await self.conn.execute(
                sa.text(
                    """
                    SELECT COALESCE(MAX(
                        CAST(SUBSTRING(code FROM 'VND-([0-9]+)') AS INTEGER)
                    ), 0) + 1 AS next_seq
                    FROM vendors
                    WHERE organization_id = :org_id
                    """
                ),
                {"org_id": organization_id},
            )
        ).mappings().first()
        next_seq = seq_res["next_seq"] if seq_res else 1
        vendor_code = f"VND-{next_seq:03d}"

        new_id = uuid.uuid4()
        await self.conn.execute(
            sa.text(
                "INSERT INTO vendors (id, organization_id, name, code, status, created_by) "
                "VALUES (:id, :organization_id, :name, :code, 'active', :created_by) "
                "ON CONFLICT (organization_id, name) DO NOTHING"
            ),
            {
                "id": new_id,
                "organization_id": organization_id,
                "name": name,
                "code": vendor_code,
                "created_by": created_by,
            },
        )
        existing = await self.find_by_name_exact_active(organization_id, name)
        if existing is None:
            # Request 198: the name belongs to a deactivated vendor (unique per company, so the
            # insert did nothing). The sender just said "add it": bring that vendor back, never fail.
            await self.conn.execute(
                sa.text(
                    "UPDATE vendors SET status = 'active', updated_by = :by, updated_at = now() "
                    "WHERE organization_id = :org AND name = :name"
                ),
                {"by": created_by, "org": organization_id, "name": name},
            )
            existing = await self.find_by_name_exact_active(organization_id, name)
        if existing is None:
            raise RuntimeError(f"vendor {name!r} could not be created or found")
        return existing

    async def update(
        self,
        organization_id: uuid.UUID,
        vendor_id: uuid.UUID,
        *,
        name: str | None = None,
        status: str | None = None,
        updated_by: uuid.UUID,
        details: dict | None = None,
    ) -> Vendor | None:
        """``details`` (PRC-04): phone / gstin / address to write, already cleaned; a key with None clears it."""
        values: dict = {"updated_by": updated_by, "updated_at": sa.func.now()}
        for key, value in (details or {}).items():
            if key in ("phone", "gstin", "address", "kind", "credit_days", "lead_time_days", "contact_person", "notes",
                       "opening_balance", "opening_balance_date"):
                values[key] = value
        if name is not None:
            values["name"] = name.strip()
        if status is not None:
            values["status"] = status.strip().lower()

        await self.conn.execute(
            sa.update(_vendors)
            .where(
                _vendors.c.id == vendor_id,
                _vendors.c.organization_id == organization_id,
            )
            .values(**values)
        )
        return await self.get_by_id(organization_id, vendor_id)

