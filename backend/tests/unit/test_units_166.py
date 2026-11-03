"""WA-166: a new material is counted in its kind's unit; a size the wrong way round is refused (Paraclette's
"1 load holobricks = 0.33 nos")."""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from mesiri.domains.materials import router as materials_router
from mesiri.domains.materials.unit_conversion import natural_stock_unit


@pytest.mark.parametrize(("name", "unit"), [
    ("TMT Steel Bars", "kg"), ("Binding Wire", "kg"), ("കമ്പി", "kg"),
    ("M sand", "cft"), ("P sand", "cft"), ("എംസാന്റ്", "cft"), ("Blue metal 20mm", "cft"),
    ("Cement", "bags"), ("സിമൻറ്", "bags"),
    ("holobricks", "nos"), ("ചെങ്കല്ല്", "nos"), ("ഇഷ്ടിക", "nos"),
    ("Paint", "litres"), ("Primer", "litres"), ("Thinner", "litres"),
    ("fevicol", None), ("Tiles", None), ("Plywood", None),  # unknown kinds keep the person's unit
])
def test_paraclettes_materials_get_their_kinds_unit(name: str, unit: str | None) -> None:
    assert natural_stock_unit(name) == unit


@pytest.fixture
def _put(monkeypatch: pytest.MonkeyPatch):  # noqa: ANN202
    holo, load, nos = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    saved: list = []

    class Catalog:
        def __init__(self, conn: object) -> None: ...

        async def get_by_id(self, org: uuid.UUID, material_id: uuid.UUID) -> dict:
            return {"id": holo, "name": "holobricks", "default_unit_id": nos}

    class Units:
        def __init__(self, conn: object) -> None: ...

        async def get_by_id(self, unit_id: uuid.UUID) -> dict:
            code = {load: ("load", "Loads"), nos: ("nos", "Numbers")}[unit_id]
            return {"id": unit_id, "code": code[0], "display_name": code[1]}

    class Conversions:
        def __init__(self, conn: object) -> None: ...

        async def upsert(self, **kwargs: object) -> None:
            saved.append(kwargs)

    from mesiri.infrastructure.postgres.repositories import material_unit_conversions as repo

    monkeypatch.setattr(materials_router, "PostgresMaterialCatalogRepository", Catalog)
    monkeypatch.setattr(materials_router, "UnitsOfMeasureRepository", Units)
    monkeypatch.setattr(repo, "PostgresMaterialUnitConversionRepository", Conversions)

    async def put(size: str) -> dict:
        return await materials_router.set_unit_conversion(
            holo, materials_router.UnitConversionSet(from_unit_id=load, one_unit_equals=Decimal(size)),
            auth_context=SimpleNamespace(role="ADMIN", organization_id=uuid.uuid4(), user_id=uuid.uuid4()), conn=object())

    return put, saved


async def test_a_load_of_holobricks_below_one_brick_is_refused(_put) -> None:  # noqa: ANN001
    put, saved = _put
    with pytest.raises(HTTPException) as err:
        await put("0.33")
    assert err.value.status_code == 422 and "how many Numbers are in 1 Loads" in err.value.detail
    assert saved == []


async def test_guard_a_real_load_of_holobricks_is_saved(_put) -> None:  # noqa: ANN001
    put, saved = _put
    assert (await put("300"))["one_unit_equals"] == "300"
    assert len(saved) == 1
