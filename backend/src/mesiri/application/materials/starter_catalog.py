"""Seed a company's materials catalogue with the starter list (BE-24).

Called by the create-company step (SS-03) inside its transaction. Safe to
run again: a name the company already has (case- and whitespace-insensitive,
the catalogue's own uniqueness rule) is left alone. Takes an
externally-supplied connection and never commits.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from mesiri.domains.materials.defaults import STARTER_MATERIALS, StarterMaterial
from mesiri.infrastructure.postgres.repositories.materials import (
    PostgresMaterialCatalogRepository,
    UnitsOfMeasureRepository,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection

_log = logging.getLogger(__name__)


async def seed_starter_materials(
    conn: AsyncConnection,
    organization_id: uuid.UUID,
    created_by: uuid.UUID,
    materials: tuple[StarterMaterial, ...] = STARTER_MATERIALS,
) -> int:
    """Add the starter materials the company doesn't have yet; returns how
    many were added. A material whose unit is missing from
    `units_of_measure` is skipped and logged rather than failing the
    company's creation over a convenience row."""
    catalog = PostgresMaterialCatalogRepository(conn)
    units = UnitsOfMeasureRepository(conn)
    unit_by_code: dict[str, dict | None] = {}
    added = 0
    for material in materials:
        if material.unit_code not in unit_by_code:
            unit_by_code[material.unit_code] = await units.get_by_code(material.unit_code)
        unit = unit_by_code[material.unit_code]
        if unit is None or not unit["is_active"]:
            _log.warning(
                "materials.starter_unit_missing unit=%s material=%s",
                material.unit_code,
                material.name,
            )
            continue
        if await catalog.get_by_name(organization_id, material.name) is not None:
            continue
        await catalog.create(
            organization_id=organization_id,
            name=material.name,
            default_unit=unit["code"],
            default_unit_id=unit["id"],
            category=material.category,
            sku=None,
            created_by=created_by,
        )
        added += 1
    return added
