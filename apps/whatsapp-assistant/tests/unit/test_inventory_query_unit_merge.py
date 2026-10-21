"""Unit tests for MaterialInventoryQueryService's row aggregation.

Previously this module also merged unit spelling variants ("bag"/"bags"/
"sack") at read time, because material_receipts/material_usage stored
whatever free-text unit extraction produced. Migration 0290/0300 replaced
that with a real units_of_measure FK + material_movements ledger — the
repository's get_stock_levels now groups by unit_id and always returns one
canonical unit code per material, so there is nothing left to merge for
spelling anymore.

What get_stock_levels still legitimately returns multiple rows for is the
SAME material_id across different sites (it groups by (org, project, site,
material_id, unit_id)) -- an org-wide or "All Sites Combined" query spanning
more than one site produces one row per site for the same material. This
module re-aggregates those by material_id before returning, so a live bug
report ("Cement" showing as two separate un-summed lines because it existed
at two sites) doesn't recur.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from runtime.inventory_query import MaterialInventoryQueryService

ORG = "11111111-1111-4111-8111-111111111111"
CEMENT_ID = "11111111-1111-4111-8111-111111111112"
SAND_ID = "11111111-1111-4111-8111-111111111113"


class _FakeConn:
    pass


class _FakeTxn:
    async def __aenter__(self):
        return _FakeConn()

    async def __aexit__(self, *exc):
        return False


class _FakeDb:
    def transaction(self):
        return _FakeTxn()


def _row(material_id: str, material_name: str, unit: str, received: str, used: str, stock: str) -> dict:
    return {
        "material_id": material_id,
        "material_name": material_name,
        "unit": unit,
        "total_received": Decimal(received),
        "total_used": Decimal(used),
        "current_stock": Decimal(stock),
    }


async def _query(rows: list[dict], *, monkeypatch, material_name: str | None = None) -> list[dict]:
    class _FakeRepo:
        def __init__(self, conn):
            pass

        async def get_stock_levels(self, **kwargs):
            return rows

    monkeypatch.setattr(
        "mesiri.infrastructure.postgres.repositories.materials.PostgresMaterialReadRepository",
        _FakeRepo,
    )
    service = MaterialInventoryQueryService(_FakeDb())
    return await service.query(
        organization_id=ORG, project_id=None, site_id=None, material_name=material_name
    )


@pytest.mark.anyio
async def test_passes_through_canonical_rows_and_filters_by_material_name(monkeypatch):
    rows = [
        _row(CEMENT_ID, "cement", "bags", "182", "0", "182"),
        _row(SAND_ID, "sand", "tons", "10", "0", "10"),
    ]

    levels = await _query(rows, monkeypatch=monkeypatch, material_name="cement")

    assert len(levels) == 1
    assert levels[0]["unit"] == "bags"
    assert levels[0]["current_stock"] == 182.0


@pytest.mark.anyio
async def test_same_material_across_multiple_sites_is_summed_into_one_line(monkeypatch):
    """Regression test for the live bug report: "Cement" showed twice (80
    bags, 72 bags) in the same inventory reply because get_stock_levels
    returned one row per site for the same material_id and nothing summed
    them. An org-wide/combined query must show one line with the total."""
    rows = [
        _row(CEMENT_ID, "Cement", "bags", "80", "0", "80"),
        _row(CEMENT_ID, "Cement", "bags", "72", "0", "72"),
    ]

    levels = await _query(rows, monkeypatch=monkeypatch)

    assert len(levels) == 1, "two rows sharing material_id must merge into one line"
    assert levels[0]["material_name"] == "Cement"
    assert levels[0]["current_stock"] == 152.0
    assert levels[0]["received"] == 152.0


@pytest.mark.anyio
async def test_different_materials_stay_on_separate_lines(monkeypatch):
    rows = [
        _row(CEMENT_ID, "Cement", "bags", "80", "0", "80"),
        _row(SAND_ID, "Sand", "tons", "10", "0", "10"),
    ]

    levels = await _query(rows, monkeypatch=monkeypatch)

    assert len(levels) == 2
    stock_by_name = {lvl["material_name"]: lvl["current_stock"] for lvl in levels}
    assert stock_by_name == {"Cement": 80.0, "Sand": 10.0}


@pytest.mark.anyio
async def test_the_same_material_in_two_units_is_never_added_together(monkeypatch):
    """WA-42 (live test, 21 Oct): "427 bags used" against a stock card of 237
    -- cement movements in kg were added into the bags total and labelled
    "bags". Each unit keeps its own line; sites are still summed per unit."""
    rows = [
        _row(CEMENT_ID, "Cement", "bag", "575", "237", "338"),
        _row(CEMENT_ID, "Cement", "kg", "0", "190", "-190"),
        _row(CEMENT_ID, "Cement", "bag", "10", "0", "10"),  # another site, same unit
    ]

    levels = await _query(rows, monkeypatch=monkeypatch)

    by_unit = {lvl["unit"]: (lvl["received"], lvl["used"], lvl["current_stock"]) for lvl in levels}
    assert by_unit == {"bag": (585.0, 237.0, 348.0), "kg": (0.0, 190.0, -190.0)}
