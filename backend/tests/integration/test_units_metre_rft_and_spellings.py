"""V1 audit WRK-02: the units and spellings migration 0489 adds resolve
through the same alias lookup every write path uses."""

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
    ("text", "code"),
    [
        ("meter", "m"),
        ("Metres", "m"),
        ("m", "m"),
        ("rmt", "m"),
        ("rft", "rft"),
        ("running feet", "rft"),
        ("sq ft", "sqft"),
        ("sq.ft", "sqft"),
        ("sft", "sqft"),
        ("m2", "sqm"),
        ("m²", "sqm"),
        ("sq m", "sqm"),
        ("m3", "cum"),
        ("m³", "cum"),
        ("cubic meter", "cum"),
        ("mt", "mt"),
    ],
)
async def test_spellings_resolve(units_repo: UnitsOfMeasureRepository, text: str, code: str):
    unit = await units_repo.resolve_alias(text)
    assert unit is not None
    assert unit["code"] == code
