"""WA [103]: the `brass` unit (migration 0487) resolves from the spellings
sites type, through the same alias lookup every write path uses."""

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


@pytest.mark.parametrize("text", ["brass", "Brass", " brasses "])
async def test_brass_spellings_resolve_to_brass(units_repo: UnitsOfMeasureRepository, text: str):
    unit = await units_repo.resolve_alias(text)
    assert unit is not None
    assert unit["code"] == "brass"


async def test_units_the_plan_needs_all_exist(units_repo: UnitsOfMeasureRepository):
    codes = {u["code"] for u in await units_repo.list_active()}
    assert {"cft", "tons", "load", "brass", "cum"} <= codes
