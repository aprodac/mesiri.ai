"""BE-39: the `cft` and `load` units (migration 0474) resolve from the spellings
Kerala sites actually type, through the same alias lookup every write path uses."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from mesiri.bootstrap.settings import Settings
from mesiri.infrastructure.postgres.repositories.materials import UnitsOfMeasureRepository

pytestmark = pytest.mark.integration


@pytest.fixture
async def units_repo():
    engine = create_async_engine(Settings().postgres.dsn(), echo=False)
    async with engine.connect() as conn:
        yield UnitsOfMeasureRepository(conn)
    await engine.dispose()


@pytest.mark.parametrize(
    "text",
    ["cft", "CFT", " cft ", "cubic feet", "Cubic Foot", "cu ft", "cu.ft", "cuft", "ft3", "ft³"],
)
async def test_cubic_feet_spellings_resolve_to_cft(units_repo: UnitsOfMeasureRepository, text: str):
    unit = await units_repo.resolve_alias(text)
    assert unit is not None
    assert unit["code"] == "cft"


@pytest.mark.parametrize(
    "text",
    [
        "load",
        "Loads",
        "lorry",
        "lorry load",
        "tipper",
        "Tipper Load",
        "truck load",
        "truckload",
        "ലോഡ്",
    ],
)
async def test_load_spellings_resolve_to_load(units_repo: UnitsOfMeasureRepository, text: str):
    unit = await units_repo.resolve_alias(text)
    assert unit is not None
    assert unit["code"] == "load"


async def test_existing_units_unchanged(units_repo: UnitsOfMeasureRepository):
    assert (await units_repo.resolve_alias("cum"))["code"] == "cum"
    assert (await units_repo.resolve_alias("sack"))["code"] == "bags"


async def test_new_units_listed_for_pickers(units_repo: UnitsOfMeasureRepository):
    codes = {u["code"] for u in await units_repo.list_active()}
    assert {"cft", "load"} <= codes
