"""Material catalog / units-of-measure read service (wiring layer only).

Same shape and justification as runtime/inventory_query.py: adapts the
backend's PostgresMaterialCatalogRepository/UnitsOfMeasureRepository into
plain async methods the inbound journey's material/unit resolution gate can
call, without the WhatsApp assistant depending on backend infrastructure
anywhere outside runtime/.

No fuzzy scoring beyond the repository's ILIKE substring match, no
auto-create (beyond create_material), no unit conversion of its own (WA-41's
conversions are looked up and set here, applied by the gate) -- ambiguity/absence is returned as plain
data (0, 1, or many candidates) and the caller (runtime/inbound_journey.py)
decides whether that means "resolved silently" or "ask the user".
"""

from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mesiri.infrastructure.postgres.database import PostgresDatabase


class MaterialCatalogQueryService:
    """Read-only: never opens a write transaction, never mutates state."""

    def __init__(self, db: PostgresDatabase) -> None:
        self._db = db

    async def find_materials(self, *, organization_id: str, name: str) -> list[dict[str, Any]]:
        """Active catalog matches for `name`. An exact (case-insensitive) match
        always wins outright and is returned alone; otherwise substring
        candidates (0, 1, or many) so the caller can ask/report accordingly."""
        from mesiri.infrastructure.postgres.repositories.materials import (
            PostgresMaterialCatalogRepository,
        )

        org = uuid.UUID(organization_id)
        async with self._db.transaction() as conn:
            repo = PostgresMaterialCatalogRepository(conn)
            exact = await repo.find_by_name_exact_active(org, name)
            if exact is not None:
                return [exact]
            return await repo.find_by_name_fuzzy(org, name, limit=10)

    async def list_active_materials(self, *, organization_id: str) -> list[dict[str, Any]]:
        """Fallback candidate list when nothing matched the reported name at
        all -- still gives the user something to pick from."""
        from mesiri.infrastructure.postgres.repositories.materials import (
            PostgresMaterialCatalogRepository,
        )

        async with self._db.transaction() as conn:
            repo = PostgresMaterialCatalogRepository(conn)
            items, _total = await repo.list_materials(
                organization_id=uuid.UUID(organization_id), is_active=True, limit=10
            )
            return items

    async def get_material(self, *, organization_id: str, material_id: str) -> dict[str, Any] | None:
        from mesiri.infrastructure.postgres.repositories.materials import (
            PostgresMaterialCatalogRepository,
        )

        async with self._db.transaction() as conn:
            repo = PostgresMaterialCatalogRepository(conn)
            return await repo.get_by_id(uuid.UUID(organization_id), uuid.UUID(material_id))

    async def resolve_unit(self, text: str) -> dict[str, Any] | None:
        """Resolve free text (exact code or known alias) to its canonical unit."""
        from mesiri.infrastructure.postgres.repositories.materials import (
            UnitsOfMeasureRepository,
        )

        async with self._db.transaction() as conn:
            repo = UnitsOfMeasureRepository(conn)
            return await repo.resolve_alias(text)

    async def get_unit(self, unit_id: str) -> dict[str, Any] | None:
        from mesiri.infrastructure.postgres.repositories.materials import (
            UnitsOfMeasureRepository,
        )

        async with self._db.transaction() as conn:
            repo = UnitsOfMeasureRepository(conn)
            return await repo.get_by_id(uuid.UUID(unit_id))

    async def list_units(self) -> list[dict[str, Any]]:
        """The fixed global units list -- what the unit picker is built from
        when a brand-new material's Stock Unit can't be inferred from the
        reported text (see runtime/inbound_journey.py's material-create gate)."""
        from mesiri.infrastructure.postgres.repositories.materials import (
            UnitsOfMeasureRepository,
        )

        async with self._db.transaction() as conn:
            repo = UnitsOfMeasureRepository(conn)
            return await repo.list_active()

    async def create_material(
        self,
        *,
        organization_id: str,
        name: str,
        unit_id: str,
        created_by: str,
    ) -> dict[str, Any] | None:
        """Add a catalog entry from a WhatsApp report (STA-139).

        The one write on this otherwise read-only service, deliberately kept
        here rather than in a new module so the material gate has a single
        catalog collaborator. Mirrors the REST create_material endpoint's
        rules: the unit must be a real active unit, and an existing entry
        with the same name wins instead of creating a duplicate (two people
        reporting the same new material at once must not produce two rows --
        the name is org-unique in the schema, so this also keeps the insert
        from raising).

        Returns None when the unit turns out not to be valid; the caller
        decides what to tell the user.
        """
        from mesiri.infrastructure.postgres.repositories.materials import (
            PostgresMaterialCatalogRepository,
            UnitsOfMeasureRepository,
        )

        org = uuid.UUID(organization_id)
        clean_name = name.strip()
        async with self._db.transaction() as conn:
            units_repo = UnitsOfMeasureRepository(conn)
            unit = await units_repo.get_by_id(uuid.UUID(unit_id))
            if unit is None or not unit["is_active"]:
                return None

            repo = PostgresMaterialCatalogRepository(conn)
            existing = await repo.get_by_name(org, clean_name)
            if existing is not None:
                return existing

            return await repo.create(
                organization_id=org,
                name=clean_name,
                default_unit=unit["code"],
                default_unit_id=unit["id"],
                category=None,
                sku=None,
                created_by=uuid.UUID(created_by),
            )

    async def find_conversion(
        self, *, organization_id: str, material: dict[str, Any], from_unit: dict[str, Any], stock_unit: dict[str, Any]
    ) -> Decimal | None:
        """WA-41: how many ``from_unit`` make one stock unit of ``material`` --
        the company's own answer first, then a fixed one (kg/tons, cft/m³,
        cement 50 kg/bag). None when nobody has said yet."""
        from mesiri.domains.materials.unit_conversion import built_in_per_stock_unit
        from mesiri.infrastructure.postgres.repositories.material_unit_conversions import (
            PostgresMaterialUnitConversionRepository,
        )

        async with self._db.transaction() as conn:
            stored = await PostgresMaterialUnitConversionRepository(conn).get(
                organization_id=uuid.UUID(organization_id),
                material_id=uuid.UUID(str(material["id"])),
                from_unit_id=uuid.UUID(str(from_unit["id"])),
            )
        if stored is not None:
            return stored
        return built_in_per_stock_unit(
            str(from_unit.get("code") or ""), str(stock_unit.get("code") or ""), str(material.get("name") or "")
        )

    async def set_conversion(
        self,
        *,
        organization_id: str,
        role: str | None,
        user_id: str | None,
        material_name: str,
        unit_text: str,
        count: Decimal | float | str,
    ) -> str:
        """WA-41: "``count`` ``unit_text`` make one stock unit of the material",
        for the whole company. Only an admin or project manager may (Ilan, 21
        Oct 2026). Returns the one line to tell them."""
        from mesiri.authorization.roles import may_set_unit_conversions
        from mesiri.infrastructure.postgres.repositories.material_unit_conversions import (
            PostgresMaterialUnitConversionRepository,
        )

        if not may_set_unit_conversions(role):
            return "Only your admin or a project manager can set that for the company."
        try:
            per_stock_unit = Decimal(str(count))
        except (InvalidOperation, ValueError):
            per_stock_unit = Decimal(0)
        if per_stock_unit <= 0:
            return "That needs a number above zero."
        matches = await self.find_materials(organization_id=organization_id, name=material_name)
        if len(matches) != 1:
            return f"I couldn't tell which material \"{material_name}\" is; say its exact name."
        material = matches[0]
        from_unit = await self.resolve_unit(unit_text)
        stock_unit = await self.get_unit(str(material["default_unit_id"])) if material.get("default_unit_id") else None
        if from_unit is None or stock_unit is None:
            return f"I don't know the unit \"{unit_text}\"."
        if str(from_unit["id"]) == str(stock_unit["id"]):
            return f"{material['name']} is already counted in {stock_unit['display_name']}."
        async with self._db.transaction() as conn:
            await PostgresMaterialUnitConversionRepository(conn).upsert(
                organization_id=uuid.UUID(organization_id),
                material_id=uuid.UUID(str(material["id"])),
                from_unit_id=uuid.UUID(str(from_unit["id"])),
                per_stock_unit=per_stock_unit,
                user_id=_uuid_or_none(user_id),
            )
        return (
            f"Saved for the company: {per_stock_unit.normalize():f} {from_unit['display_name'].lower()} "
            f"of {material['name']} = 1 {stock_unit['display_name']}."
        )


def _uuid_or_none(value: Any) -> uuid.UUID | None:
    text = str(value or "").removeprefix("ctx_user_")
    try:
        return uuid.UUID(text)
    except ValueError:
        return None
