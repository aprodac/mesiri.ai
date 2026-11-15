"""BOQ-01: a work update goes on its BOQ line by itself when the line is clear, and offers the lines to tap when
it is not (``boq_router.place_new_work``), against the real schema."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from mesiri.domains.progress.boq_router import place_new_work, set_work_line_checked
from mesiri.infrastructure.postgres.repositories.boq import PostgresBoqRepository


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


async def _unit(conn, code: str) -> uuid.UUID:
    return (await conn.execute(text("SELECT id FROM units_of_measure WHERE code = :c"), {"c": code})).scalar_one()


async def _project(conn):
    org, project, site, section = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await conn.execute(text("INSERT INTO organizations (id, name, deployment_type, db_route, status, created_at) "
                            "VALUES (:id, 'BOQ-01 Co', 'local', 'default', 'active', now())"), {"id": org})
    await conn.execute(text("INSERT INTO projects (id, organization_id, name) VALUES (:id, :o, 'Villa')"),
                       {"id": project, "o": org})
    await conn.execute(text("INSERT INTO sites (id, organization_id, project_id, name) VALUES (:id, :o, :p, 'Plot 4')"),
                       {"id": site, "o": org, "p": project})
    await conn.execute(text("INSERT INTO work_packages (id, organization_id, project_id, name) "
                            "VALUES (:id, :o, :p, 'Finishes')"), {"id": section, "o": org, "p": project})
    return org, project, site, section


async def _line(conn, org, section, work: str, unit: uuid.UUID) -> uuid.UUID:
    line = uuid.uuid4()
    await conn.execute(text("INSERT INTO work_package_planned_items (id, organization_id, work_package_id, work_type, "
                            "unit_id, planned_quantity) VALUES (:id, :o, :s, :w, :u, 1000)"),
                       {"id": line, "o": org, "s": section, "w": work, "u": unit})
    return line


async def _work(conn, org, project, site, work: str, unit: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    activity, quantity = uuid.uuid4(), uuid.uuid4()
    await conn.execute(text("INSERT INTO activities (id, organization_id, project_id, site_id, activity_date, work_type) "
                            "VALUES (:id, :o, :p, :s, :d, :w)"),
                       {"id": activity, "o": org, "p": project, "s": site, "d": dt.date(2026, 11, 15), "w": work})
    await conn.execute(text("INSERT INTO activity_quantities (id, activity_id, unit_id, quantity, work_type) "
                            "VALUES (:id, :a, :u, 400, :w)"), {"id": quantity, "a": activity, "u": unit, "w": work})
    return activity, quantity


async def _on(conn, quantity):
    return (await conn.execute(text("SELECT planned_item_id FROM activity_quantities WHERE id = :q"),
                               {"q": quantity})).scalar_one()


async def test_a_clear_line_is_linked_on_save_and_said(conn):
    org, project, site, section = await _project(conn)
    sqft, cum = await _unit(conn, "sqft"), await _unit(conn, "cum")
    plaster = await _line(conn, org, section, "Internal plastering 12 mm", sqft)
    await _line(conn, org, section, "M20 concrete slab", cum)
    activity, quantity = await _work(conn, org, project, site, "internal plastering", sqft)

    out = await place_new_work(conn, org, activity)

    assert out == [{"quantity_id": str(quantity), "work": "internal plastering",
                    "line": {"id": str(plaster), "work": "Internal plastering 12 mm"},
                    "auto": True, "choices": []}]
    assert await _on(conn, quantity) == plaster


async def test_an_unclear_line_is_left_off_with_the_lines_to_tap(conn):
    org, project, site, section = await _project(conn)
    sqft = await _unit(conn, "sqft")
    walls = await _line(conn, org, section, "Plastering walls", sqft)
    ceiling = await _line(conn, org, section, "Plastering ceiling", sqft)
    activity, quantity = await _work(conn, org, project, site, "plastering", sqft)

    out = await place_new_work(conn, org, activity)

    assert out[0]["line"] is None and out[0]["auto"] is False
    assert {c["id"] for c in out[0]["choices"]} == {str(walls), str(ceiling)}
    assert await _on(conn, quantity) is None  # never a guess

    # The tap: the same check as the BOQ page puts it on the chosen line.
    line = await set_work_line_checked(PostgresBoqRepository(conn), org, project, quantity, ceiling)
    assert line["work_type"] == "Plastering ceiling" and await _on(conn, quantity) == ceiling


async def test_another_unit_is_never_linked_nor_offered_nor_accepted(conn):
    org, project, site, section = await _project(conn)
    sqft, cum = await _unit(conn, "sqft"), await _unit(conn, "cum")
    concrete = await _line(conn, org, section, "Concrete", cum)
    activity, quantity = await _work(conn, org, project, site, "concrete", sqft)

    out = await place_new_work(conn, org, activity)

    assert out == [{"quantity_id": str(quantity), "work": "concrete", "line": None, "auto": False, "choices": []}]
    with pytest.raises(HTTPException) as refused:
        await set_work_line_checked(PostgresBoqRepository(conn), org, project, quantity, concrete)
    assert refused.value.status_code == 422


async def test_no_boq_says_nothing(conn):
    org, project, site, _ = await _project(conn)
    activity, _ = await _work(conn, org, project, site, "plastering", await _unit(conn, "sqft"))
    assert await place_new_work(conn, org, activity) == []


async def test_boq02_a_days_labour_follows_the_work_linked_that_day(conn):
    """BOQ-02 wiring: the work placed by BOQ-01 is what the day's labour is split by (one read, ``_allocations``)."""
    from mesiri.domains.costing.router import _allocations

    org, project, site, section = await _project(conn)
    sqft = await _unit(conn, "sqft")
    plaster = await _line(conn, org, section, "Internal plastering 12 mm", sqft)
    activity, _ = await _work(conn, org, project, site, "internal plastering", sqft)
    await place_new_work(conn, org, activity)
    day = dt.date(2026, 11, 15)
    group = {"site_id": site, "work_date": day, "trade_key": "mason", "man_days": 4, "priced_man_days": 4,
             "cost": 4400, "activities": []}

    rows = await _allocations(conn, PostgresBoqRepository(conn), org, project, day, day, [group])

    assert [(r["planned_item_id"], r["man_days"], r.get("auto")) for r in rows] == [(plaster, 4, True)]
    other_day = {**group, "work_date": day - dt.timedelta(days=1)}
    assert await _allocations(conn, PostgresBoqRepository(conn), org, project, day - dt.timedelta(days=1), day,
                              [other_day]) == []


async def test_boq03_an_issue_is_placed_on_the_activity_it_holds_up_and_listed_there(conn):
    from mesiri.domains.schedule import store

    org, project, site, finishes = await _project(conn)
    slab = uuid.uuid4()
    await conn.execute(text("INSERT INTO work_packages (id, organization_id, project_id, name) "
                            "VALUES (:id, :o, :p, 'First floor slab')"), {"id": slab, "o": org, "p": project})
    await _line(conn, org, slab, "Shuttering for slab", await _unit(conn, "sqft"))
    await _line(conn, org, finishes, "Internal plastering", await _unit(conn, "sqft"))

    placed = await store.place_issue(conn, org, project, site, "Shuttering material not came, slab delayed")
    assert placed == slab
    assert await store.place_issue(conn, org, project, site, "rain, work stopped") is None

    from mesiri.infrastructure.postgres.repositories.progress import PostgresProgressReadRepository

    user = uuid.uuid4()
    await conn.execute(text("INSERT INTO users (id, organization_id, full_name, role, status, hashed_password) "
                            "VALUES (:id, :o, 'Ravi', 'SITE_SUPERVISOR', 'active', 'x')"), {"id": user, "o": org})
    await PostgresProgressReadRepository(conn).create_issue(org, user, {
        "project_id": project, "site_id": site, "issue_type": "MATERIAL_SHORTAGE", "severity": "HIGH",
        "narrative": "Shuttering material not came, slab delayed", "work_package_id": placed})

    sched = await store.load(conn, org, project, dt.date(2026, 11, 15))
    by_name = {a["name"]: a for a in sched["activities"]}
    assert by_name["First floor slab"]["open_issues"] == 1
    assert by_name["First floor slab"]["issues"][0]["what"] == "Shuttering material not came, slab delayed"
    assert by_name["Finishes"]["open_issues"] == 0
    assert sched["summary"]["open_issues"] == 1 and sched["summary"]["issues_on_no_activity"] == 0
