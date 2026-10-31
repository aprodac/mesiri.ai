"""Material inventory read service (wiring layer only).

Adapts the backend's PostgresMaterialReadRepository (already used by the
mobile app's /materials/inventory endpoint) into a plain async method the
inbound journey can call. Lives in runtime/ because that's the one layer
allowed to import concrete backend infrastructure directly -- the same
justification runtime/dependencies.py already relies on for the material
execution wiring.
"""

from __future__ import annotations

import datetime
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mesiri.infrastructure.postgres.database import PostgresDatabase


class MaterialInventoryQueryService:
    """Read-only: never opens a write transaction, never mutates state."""

    def __init__(self, db: PostgresDatabase) -> None:
        self._db = db

    async def query(
        self,
        *,
        organization_id: str,
        project_id: str | None,
        site_id: str | None,
        material_name: str | None,
        material_id: str | None = None,
        include_unsaved: bool = False,
    ) -> list[dict[str, Any]]:
        """Stock levels for the given scope, optionally filtered to one material
        (substring match). Returns plain JSON-safe dicts: material_name, unit,
        received, used, current_stock -- Decimal/UUID values are never leaked.

        Rows come from get_stock_levels, which derives stock from
        material_movements grouped by material_id/unit_id (a real FK to
        units_of_measure, not a free-text string) -- unit spelling is
        already canonical by construction, so no read-time alias merging is
        needed here anymore (see migration 0290/0300 and posting.py)."""
        from mesiri.infrastructure.postgres.repositories.materials import (
            PostgresMaterialReadRepository,
        )

        async with self._db.transaction() as conn:
            repo = PostgresMaterialReadRepository(conn)
            rows = await repo.get_stock_levels(
                organization_id=uuid.UUID(organization_id),
                project_ids={uuid.UUID(project_id)} if project_id else None,
                site_id=uuid.UUID(site_id) if site_id else None,
                include_unsaved=include_unsaved,
            )

        # get_stock_levels groups by (org, project, site, material_id, unit_id)
        # -- when the query spans more than one site/project (site_id is None,
        # e.g. the site-selection gate's "All Sites Combined" choice, or an
        # org-wide query), the same material_id legitimately produces one row
        # per site. Re-aggregate by material (and unit) here so the reply shows one
        # line per material with a combined total, instead of a separate
        # "Cement" line per site the caller never asked to see broken out.
        totals: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            if material_id is not None and str(row["material_id"]) != str(material_id):
                # ARCH-01: by id, so "cement" never picks up "Cement Paint".
                continue
            # Per material AND unit (WA-42): get_stock_levels keeps each unit
            # apart, and adding kg into a total labelled "bag" made "427 bags
            # used" out of two different units (21 Oct live test).
            key = (str(row["material_id"]), str(row["unit"]))
            entry = totals.setdefault(
                key,
                {"material_name": row["material_name"], "unit": row["unit"], "received": 0.0, "used": 0.0, "current_stock": 0.0},
            )
            entry["received"] += float(row["total_received"])
            entry["used"] += float(row["total_used"])
            entry["current_stock"] += float(row["current_stock"])

        levels = list(totals.values())

        if material_name:
            needle = material_name.strip().lower()
            levels = [lvl for lvl in levels if needle in lvl["material_name"].lower()]

        return levels

    async def period_totals(
        self,
        *,
        organization_id: str,
        project_id: str | None,
        site_id: str | None,
        start_date: datetime.date,
        end_date: datetime.date,
        timezone_name: str,
        material_id: str | None = None,
    ) -> dict[tuple[str, str], dict[str, float]]:
        """MAT-03: what was received and used between two project-zone days,
        per (lower-cased material name, unit) -- from ``material_movements``,
        counted as the DPR counts a day (``application.dpr.assembly``: a
        corrected entry and its correction cancel out, receipts by reason).
        Read-only. The keys match ``query``'s rows."""
        import sqlalchemy as sa

        from mesiri.application.dpr.assembly import _material_summary

        scope = ""
        params: dict[str, Any] = {
            "org": uuid.UUID(organization_id), "start": start_date, "end": end_date, "tz": timezone_name,
        }
        if project_id:
            scope += " AND mm.project_id = :project"
            params["project"] = uuid.UUID(project_id)
        if site_id:
            scope += " AND mm.site_id = :site"
            params["site"] = uuid.UUID(site_id)
        if material_id:
            scope += " AND mm.material_id = :material"
            params["material"] = uuid.UUID(material_id)
        from mesiri.application.dpr import fact_review

        sql = sa.text(
            """
            SELECT mm.material_id, mc.name AS material_name, u.code AS unit,
                   mm.movement_type, mm.quantity,
                   COALESCE(mr.movement_reason, mu.movement_reason) AS movement_reason
            FROM material_movements mm
            JOIN materials_catalog mc ON mc.id = mm.material_id
            JOIN units_of_measure u ON u.id = mm.unit_id
            LEFT JOIN material_receipts mr
                   ON mm.source_type = 'material_receipt' AND mr.id = mm.source_id
            LEFT JOIN material_usage mu
                   ON mm.source_type = 'material_usage' AND mu.id = mm.source_id
            WHERE mm.organization_id = :org
              AND (mm.occurred_at AT TIME ZONE :tz)::date BETWEEN :start AND :end
              AND mm.reversal_of_movement_id IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM material_movements r WHERE r.reversal_of_movement_id = mm.id
              )
            """
            # WA-77: the period's totals are what was saved, as the stock is.
            + f" AND {fact_review.movement_counted_sql('mm')}"
            + scope
        )
        async with self._db.transaction() as conn:
            rows = [dict(r) for r in (await conn.execute(sql, params)).mappings().all()]
        totals: dict[tuple[str, str], dict[str, float]] = {}
        # One summary per site would double-count nothing: rows are added up per material and unit.
        for entry in _material_summary(rows):
            key = (str(entry["material_name"]).lower(), str(entry["unit"]))
            total = totals.setdefault(key, {"received": 0.0, "used": 0.0})
            total["received"] += float(entry["received"])
            total["used"] += float(entry["used"])
        return totals

    async def period_costs(
        self,
        *,
        organization_id: str,
        project_id: str | None,
        site_id: str | None,
        start_date: datetime.date,
        end_date: datetime.date,
    ) -> dict[tuple[str, str], float]:
        """Request 164: the rate paid per unit for what was received in the period,
        per (lower-cased material name, unit): the cost recorded with the
        deliveries divided by their quantity (only deliveries that carry a cost).
        Read-only."""
        import sqlalchemy as sa

        scope = ""
        params: dict[str, Any] = {"org": uuid.UUID(organization_id), "start": start_date, "end": end_date}
        if project_id:
            scope += " AND r.project_id = :project"
            params["project"] = uuid.UUID(project_id)
        if site_id:
            scope += " AND r.site_id = :site"
            params["site"] = uuid.UUID(site_id)
        sql = sa.text(
            "SELECT lower(c.name) AS name, u.code AS unit, SUM(r.total_cost) AS cost, SUM(r.quantity) AS qty "
            "FROM material_receipts r JOIN materials_catalog c ON c.id = r.material_id "
            "JOIN units_of_measure u ON u.id = r.unit_id "
            "WHERE r.organization_id = :org AND r.occurred_date BETWEEN :start AND :end "
            "AND r.total_cost IS NOT NULL AND r.quantity > 0 "
            "AND NOT EXISTS (SELECT 1 FROM material_usage x WHERE x.reverses_movement_id = r.id)"
            + scope
            + " GROUP BY 1, 2"
        )
        async with self._db.transaction() as conn:
            rows = (await conn.execute(sql, params)).mappings().all()
        return {(str(r["name"]), str(r["unit"])): float(r["cost"]) / float(r["qty"]) for r in rows if r["qty"]}

    async def usage_last_days(
        self,
        *,
        organization_id: str,
        project_id: str | None,
        site_id: str | None,
        days: int = 7,
        now: datetime.datetime | None = None,
    ) -> dict[tuple[str, str], float]:
        """Request 91: what was used in the last ``days`` days, per
        (lower-cased material name, unit) -- the same keys ``query`` rows give.
        Read-only, from material_movements, counted the way get_stock_levels
        counts "used" (a reversal of a receipt is use taken back, and the
        other way round)."""
        import sqlalchemy as sa

        since = (now or datetime.datetime.now(datetime.UTC)) - datetime.timedelta(days=days)
        scope = ""
        params: dict[str, Any] = {"org": uuid.UUID(organization_id), "since": since}
        if project_id:
            scope += " AND m.project_id = :project"
            params["project"] = uuid.UUID(project_id)
        if site_id:
            scope += " AND m.site_id = :site"
            params["site"] = uuid.UUID(site_id)
        from mesiri.application.dpr import fact_review

        sql = sa.text(
            """
            SELECT lower(c.name) AS name, u.code AS unit,
                   COALESCE(SUM(CASE
                       WHEN m.movement_type = 'ISSUE' AND m.reversal_of_movement_id IS NULL
                           THEN m.quantity
                       WHEN m.movement_type = 'RECEIPT' AND m.reversal_of_movement_id IS NOT NULL
                           THEN -m.quantity
                       ELSE 0 END), 0) AS used
            FROM material_movements m
            JOIN materials_catalog c ON c.id = m.material_id
            JOIN units_of_measure u ON u.id = m.unit_id
            WHERE m.organization_id = :org AND m.occurred_at >= :since
            """
            + f" AND {fact_review.movement_counted_sql('m')}"
            + scope
            + " GROUP BY lower(c.name), u.code"
        )
        async with self._db.transaction() as conn:
            rows = (await conn.execute(sql, params)).mappings().all()
        usage: dict[tuple[str, str], float] = {}
        for row in rows:
            key = (str(row["name"]), str(row["unit"]))
            usage[key] = usage.get(key, 0.0) + float(row["used"])
        return usage
