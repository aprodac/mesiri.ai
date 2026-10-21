"""Material inventory read service (wiring layer only).

Adapts the backend's PostgresMaterialReadRepository (already used by the
mobile app's /materials/inventory endpoint) into a plain async method the
inbound journey can call. Lives in runtime/ because that's the one layer
allowed to import concrete backend infrastructure directly -- the same
justification runtime/dependencies.py already relies on for the material
execution wiring.
"""

from __future__ import annotations

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
