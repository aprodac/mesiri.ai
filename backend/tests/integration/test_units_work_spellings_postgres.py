"""WRK-02 (audit 04): the units people type for work done all resolve
(integration, real Postgres, migration 0489 applied). Every test rolls back."""

from __future__ import annotations

import pytest

from mesiri.infrastructure.postgres.repositories.materials import UnitsOfMeasureRepository

pytestmark = pytest.mark.integration


@pytest.fixture
async def conn():
    from sqlalchemy.ext.asyncio import create_async_engine

    from mesiri.bootstrap.settings import Settings

    engine = create_async_engine(Settings().postgres.dsn())
    async with engine.connect() as connection:
        tx = await connection.begin()
        yield connection
        await tx.rollback()
    await engine.dispose()


SPELLINGS = {
    "m": ["m", "meter", "Meters", "metre", "MTR"],
    "rm": ["rm", "running meter", "running metres"],
    "rft": ["rft", "RFT", "running feet", "running ft", "r.ft"],
    "sqft": ["sqft", "sq ft", "Sq.Ft", "sft", "square feet", "Square Feet", "sq. ft", "SQ FT"],
    "sqm": ["sqm", "m2", "m²", "sq m", "sq.m", "square meters", "Square Meters"],
    "cum": ["cum", "m3", "m³", "cu m", "cubic meters", "Cubic Meters", "cbm"],
    "nos": ["nos", "no", "Nos.", "numbers", "each"],
    "percent": ["%", "percent", "per cent"],
    "cft": ["cft", "cu ft", "cu.ft"],
    "bags": ["bags", "bag"],
}


@pytest.mark.parametrize("code,text", [(c, t) for c, texts in SPELLINGS.items() for t in texts])
async def test_wrk02_every_spelling_resolves_to_its_unit(conn, code, text):
    unit = await UnitsOfMeasureRepository(conn).resolve_alias(text)
    assert unit is not None and unit["code"] == code, (text, unit)


async def test_wrk02_an_unknown_unit_is_still_unknown(conn):
    repo = UnitsOfMeasureRepository(conn)
    assert await repo.resolve_alias("furlongs") is None
    assert await repo.resolve_alias("   ") is None
