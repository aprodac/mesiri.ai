"""MK-02 end to end: the size route reads the seeded reference (migration 0515) and refuses the impossible.

The real cases: New India's "1 load M-sand = 60 cum" (5 Nov 2026) and the test company's "20 TMT bars = 1 ton"
(31 Oct), on a fresh company's starter materials; a usual size still saves.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.authorization.context import AuthorizationContext, ProjectAccessScope
from mesiri.domains.materials import router as materials_router
from mesiri.domains.materials.plausibility import implausible, load_reference

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


async def _company(conn, phone: str):
    created = await create_company(
        conn,
        NewCompany(name=f"Plausible Builders {phone[-4:]}", owner_name="Ravi", owner_phone=phone,
                   project_name="Green Villa", site_names=("Main",)),
        now=dt.datetime(2026, 11, 7, 10, 0, tzinfo=dt.UTC),
    )
    auth = AuthorizationContext(
        user_id=created.owner_user_id, organization_id=created.organization_id, role="ADMIN", status="active",
        access_policy={},  # type: ignore[arg-type]
        project_scope=ProjectAccessScope(mode="all_projects", project_ids=set()),
    )
    return created, auth


async def _id(conn, sql: str, **params) -> uuid.UUID:
    return (await conn.execute(text(sql), params)).scalar_one()


async def _material(conn, org, name: str, unit: str, by: uuid.UUID | None = None) -> uuid.UUID:
    found = (await conn.execute(text("SELECT id FROM materials_catalog WHERE organization_id = :o AND name = :n"),
                                {"o": org, "n": name})).scalar()
    if found:
        return found
    material_id = uuid.uuid4()
    await conn.execute(text(
        "INSERT INTO materials_catalog (id, organization_id, name, default_unit, default_unit_id, is_active, created_by) "
        "SELECT :id, :o, :n, u.code, u.id, true, :by FROM units_of_measure u WHERE u.code = :u"),
        {"id": material_id, "o": org, "n": name, "u": unit, "by": by})
    return material_id


async def _set(conn, auth, material_id, unit_code: str, value: str):
    unit_id = await _id(conn, "SELECT id FROM units_of_measure WHERE code = :c", c=unit_code)
    return await materials_router.set_unit_conversion(
        material_id, materials_router.UnitConversionSet(from_unit_id=unit_id, one_unit_equals=Decimal(value)),
        auth_context=auth, conn=conn)


async def test_the_seeded_reference_is_read() -> None:
    from sqlalchemy.ext.asyncio import create_async_engine

    from mesiri.bootstrap.settings import Settings

    engine = create_async_engine(Settings().postgres.dsn())
    async with engine.connect() as c:
        reference = await load_reference(c)
    await engine.dispose()
    assert {k.code for k in reference.kinds} >= {"tmt_bar", "sand"}
    assert implausible(reference, material_name="M Sand", from_code="load", from_label="Loads", stock_code="cum",
                       stock_label="Cubic Meters", one_unit_equals=Decimal(60)) is not None


async def test_new_indias_load_is_refused_and_nothing_is_saved(conn) -> None:
    created, auth = await _company(conn, "9876500091")
    m_sand = await _material(conn, created.organization_id, "M Sand", "cum")
    with pytest.raises(HTTPException) as refused:
        await _set(conn, auth, m_sand, "load", "60")
    assert refused.value.status_code == 422
    assert "usually 50 to 600 cft" in refused.value.detail
    saved = (await conn.execute(text("SELECT count(*) FROM material_unit_conversions WHERE material_id = :m"),
                                {"m": m_sand})).scalar_one()
    assert saved == 0


async def test_a_usual_load_still_saves(conn) -> None:
    created, auth = await _company(conn, "9876500092")
    m_sand = await _material(conn, created.organization_id, "M Sand", "cum")
    result = await _set(conn, auth, m_sand, "load", "4.25")  # 150 cft
    assert result["message"].startswith("Saved for the company")


async def test_twenty_bars_a_ton_is_refused_for_a_sized_bar(conn) -> None:
    created, auth = await _company(conn, "9876500093")
    tmt12 = await _material(conn, created.organization_id, "TMT 12mm", "tons", created.owner_user_id)
    with pytest.raises(HTTPException) as refused:
        await _set(conn, auth, tmt12, "nos", "0.05")
    assert "10.67 kg" in refused.value.detail
    assert (await _set(conn, auth, tmt12, "nos", "0.0107"))["message"].startswith("Saved for the company")


async def test_unit_check_says_before_save_whether_a_proposed_size_is_plausible(conn) -> None:
    """MK-02b: the read-only check the assistant (and the dashboard) asks before a size is held."""
    created, auth = await _company(conn, "9876500094")
    m_sand = await _material(conn, created.organization_id, "M Sand", "cum")
    load = await _id(conn, "SELECT id FROM units_of_measure WHERE code = 'load'")
    bad = await materials_router.check_material_unit(m_sand, load, one_unit_equals=Decimal(60), auth_context=auth,
                                                     conn=conn)
    assert bad["plausible"] is False
    assert bad["implausible"]["said_in_usual_unit"] == "2119"
    assert (bad["implausible"]["usual_low"], bad["implausible"]["usual_high"]) == ("50", "600")
    good = await materials_router.check_material_unit(m_sand, load, one_unit_equals=Decimal("4.25"),
                                                      auth_context=auth, conn=conn)
    assert good["plausible"] is True and "implausible" not in good
    plain = await materials_router.check_material_unit(m_sand, load, one_unit_equals=None, auth_context=auth,
                                                       conn=conn)
    assert "plausible" not in plain  # guard: without a size the answer is as before
