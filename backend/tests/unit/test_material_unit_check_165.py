"""WA-165: ``GET /materials/{id}/unit-check`` says, before Save, whether a unit can be recorded for a material: the
Stock Unit, the company's own conversion, or a fixed one (the same decision saving makes, ``_known_per_stock_unit``).
Paraclette, 3 Nov: "1 load M-sand" with M-sand stocked in bags and no load size known was refused only at Save."""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from mesiri.domains.materials import router as materials_router
from mesiri.infrastructure.postgres.repositories import (
    material_unit_conversions as conversions_repo,
)

ORG = uuid.uuid4()
BAG, LOAD, KG, MT = (uuid.uuid4() for _ in range(4))
MSAND, STEEL = uuid.uuid4(), uuid.uuid4()
UNITS = {BAG: ("bags", "Bags"), LOAD: ("load", "Loads"), KG: ("kg", "Kilograms"), MT: ("mt", "Metric Tonnes")}
MATERIALS = {MSAND: {"id": MSAND, "name": "M-sand", "default_unit_id": BAG, "is_active": True},
             STEEL: {"id": STEEL, "name": "Steel", "default_unit_id": KG, "is_active": True}}


@pytest.fixture(autouse=True)
def _repos(monkeypatch: pytest.MonkeyPatch) -> dict:
    company: dict = {}

    class Catalog:
        def __init__(self, conn: object) -> None: ...

        async def get_by_id(self, org: uuid.UUID, material_id: uuid.UUID) -> dict | None:
            return MATERIALS.get(material_id) if org == ORG else None

        async def has_movements(self, material_id: uuid.UUID) -> bool:
            return material_id == STEEL

    class Units:
        def __init__(self, conn: object) -> None: ...

        async def get_by_id(self, unit_id: uuid.UUID) -> dict | None:
            code = UNITS.get(unit_id)
            return {"id": unit_id, "code": code[0], "display_name": code[1], "is_active": True} if code else None

    class Conversions:
        def __init__(self, conn: object) -> None: ...

        async def get(self, *, organization_id: uuid.UUID, material_id: uuid.UUID, from_unit_id: uuid.UUID):
            return company.get((material_id, from_unit_id))

    monkeypatch.setattr(materials_router, "PostgresMaterialCatalogRepository", Catalog)
    monkeypatch.setattr(materials_router, "UnitsOfMeasureRepository", Units)
    monkeypatch.setattr(conversions_repo, "PostgresMaterialUnitConversionRepository", Conversions)
    return company


async def _check(material: uuid.UUID, unit: uuid.UUID) -> dict:
    return await materials_router.check_material_unit(
        material, unit, auth_context=SimpleNamespace(organization_id=ORG), conn=object())


async def test_the_reported_load_of_msand_does_not_fit_and_names_both_units() -> None:
    found = await _check(MSAND, LOAD)
    assert found["fits"] is False and found["one_unit_equals"] is None
    assert (found["stock_unit_name"], found["unit_name"]) == ("Bags", "Loads")


async def test_once_the_company_sets_the_size_it_fits(_repos: dict) -> None:
    _repos[(MSAND, LOAD)] = (Decimal(1) / Decimal(60)).quantize(Decimal("0.0000001"))  # as the PUT stores it
    found = await _check(MSAND, LOAD)
    assert found["fits"] is True and found["one_unit_equals"] == "60"


async def test_guard_the_stock_unit_and_a_fixed_conversion_fit() -> None:
    assert (await _check(MSAND, BAG))["fits"] is True
    found = await _check(STEEL, MT)  # tonnes -> kg is a fixed fact
    assert found["fits"] is True and Decimal(found["one_unit_equals"]) == 1000


async def test_guard_another_companys_material_is_not_found() -> None:
    with pytest.raises(HTTPException) as err:
        await materials_router.check_material_unit(
            MSAND, BAG, auth_context=SimpleNamespace(organization_id=uuid.uuid4()), conn=object())
    assert err.value.status_code == 404


async def test_it_says_whether_the_material_has_stock_records_so_its_unit_can_still_change() -> None:
    # [232]: no records yet (M-sand here) = the Stock Unit can still change; the WhatsApp "save as ..." way out.
    assert (await _check(MSAND, LOAD))["has_movements"] is False
    assert (await _check(STEEL, KG))["has_movements"] is True
