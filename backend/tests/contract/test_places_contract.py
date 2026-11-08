"""Contract tests for places on site (LP-01..05): setup, work at a place, progress by place, what's left.

Requires a live Postgres reachable via Settings().postgres.dsn() -- run with `pytest -m integration`.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from mesiri.bootstrap.settings import Settings
from mesiri.domains.identity.auth_service import create_access_token
from mesiri.http.app import create_app
from mesiri.infrastructure.postgres.dependency import get_db_conn

pytestmark = pytest.mark.integration


@pytest.fixture
async def test_engine():
    engine = create_async_engine(Settings().postgres.dsn(), echo=False)
    yield engine
    await engine.dispose()


@pytest.fixture
async def client(test_engine: AsyncEngine, monkeypatch):
    # The work save handler opens its own transaction on the app's database: point it at the real one.
    from mesiri.infrastructure.postgres.database import PostgresDatabase

    database = PostgresDatabase(Settings().postgres)
    await database.connect()
    monkeypatch.setattr("mesiri.domains.shared.modules._database_for", lambda request: None)
    monkeypatch.setattr("mesiri.domains.shared.modules.database_for", lambda request: database)
    monkeypatch.setattr("mesiri.domains.shared.execution.database_for", lambda request: database)
    app = create_app()

    async def override_get_db_conn():
        async with test_engine.begin() as conn:
            yield conn

    app.dependency_overrides[get_db_conn] = override_get_db_conn
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        yield c
    await database.disconnect()


async def _user(engine, org_id, role: str) -> str:
    user_id = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(sa.text(
            "INSERT INTO users (id, organization_id, email, hashed_password, full_name, role, status, access_policy, "
            "created_at, updated_at) VALUES (:id, :org, :email, 'hash', 'Ravi', :role, 'active', "
            "CAST('{\"mode\": \"all_projects\", \"projects\": []}' AS jsonb), now(), now())"),
            {"id": user_id, "org": org_id, "email": f"{uuid.uuid4().hex[:8]}@example.com", "role": role})
    return create_access_token(data={"sub": str(user_id), "org": str(org_id), "role": role})


@pytest.fixture
async def ctx(test_engine):
    org, project, site = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with test_engine.begin() as conn:
        await conn.execute(sa.text(
            "INSERT INTO organizations (id, name, deployment_type, db_route, status, created_at, updated_at) "
            "VALUES (:id, 'Places Org', 'local', 'default', 'active', now(), now())"), {"id": org})
        await conn.execute(sa.text("INSERT INTO projects (id, organization_id, name, created_at, updated_at) "
                                   "VALUES (:id, :org, 'Green Villa', now(), now())"), {"id": project, "org": org})
        await conn.execute(sa.text(
            "INSERT INTO sites (id, project_id, organization_id, name, status, created_at, updated_at) "
            "VALUES (:id, :p, :org, 'Main building', 'active', now(), now())"), {"id": site, "p": project, "org": org})
    yield {"org": org, "project": project, "site": site, "admin": await _user(test_engine, org, "admin"),
            "engineer": await _user(test_engine, org, "site_engineer")}
    # Leave nothing behind for the suites after this one (they delete users; places and documents point at them).
    async with test_engine.begin() as conn:
        await conn.execute(sa.text("DELETE FROM progress_updates WHERE activity_id IN (SELECT id FROM activities "
                                   "WHERE organization_id = :org)"), {"org": org})
        await conn.execute(sa.text("DELETE FROM activities WHERE organization_id = :org"), {"org": org})
        await conn.execute(sa.text("DELETE FROM organizations WHERE id = :org"), {"org": org})


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _setup(client, ctx):
    r = await client.post(f"/projects/{ctx['project']}/places/setup", headers=_h(ctx["admin"]),
                          json={"floors": ["Ground Floor", "First Floor"], "rooms": ["Room-1", "Room-2", "Kitchen"]})
    assert r.status_code == 200, r.text
    return r.json()


async def _work(client, ctx, place, work_type="Plastering", finished=False, token="engineer", key=None):
    headers = _h(ctx[token]) | ({"Idempotency-Key": key} if key else {})
    return await client.post("/progress/activities", headers=headers, json={
        "project_id": str(ctx["project"]), "site_id": str(ctx["site"]), "activity_date": "2026-11-08",
        "work_type": work_type, "narrative": f"{work_type} at {place}", "place": place, "finished": finished,
        "quantities": [{"quantity": "50", "unit": "sqft"}]})


async def test_quick_setup_makes_floors_by_rooms_once(client, ctx):
    made = await _setup(client, ctx)
    assert made["made"] == {"floors": 2, "rooms": 6}
    labels = [p["label"] for p in made["places"]]
    assert labels[:4] == ["Ground Floor", "Ground Floor / Room-1", "Ground Floor / Room-2", "Ground Floor / Kitchen"]
    again = await _setup(client, ctx)  # running it again never doubles a place
    assert again["made"] == {"floors": 0, "rooms": 0} and len(again["places"]) == 8


async def test_site_engineer_reads_but_cannot_set_up(client, ctx):
    r = await client.post(f"/projects/{ctx['project']}/places/setup", headers=_h(ctx["engineer"]),
                          json={"floors": ["Ground Floor"]})
    assert r.status_code == 403
    await _setup(client, ctx)
    r = await client.get(f"/projects/{ctx['project']}/places", headers=_h(ctx["engineer"]))
    assert r.status_code == 200 and r.json()["can_edit"] is False and len(r.json()["places"]) == 8


async def test_work_lands_on_the_room_named_in_words(client, ctx, test_engine):
    await _setup(client, ctx)
    r = await _work(client, ctx, "FF R2", finished=True)
    assert r.status_code == 201, r.text
    assert r.json()["place"] == "First Floor / Room-2" and r.json()["finished"] is True
    async with test_engine.begin() as conn:
        row = (await conn.execute(sa.text(
            "SELECT n.name, a.status FROM activities a JOIN location_nodes n ON n.id = a.location_id "
            "WHERE a.id = :id"), {"id": r.json()["id"]})).first()
    assert row == ("Room-2", "COMPLETED")


async def test_unclear_place_is_refused_with_the_choices(client, ctx):
    await _setup(client, ctx)
    r = await _work(client, ctx, "kitchen")  # on both floors
    assert r.status_code == 422
    assert "Ground Floor / Kitchen" in r.json()["detail"][0] and "First Floor / Kitchen" in r.json()["detail"][0]


async def test_no_places_set_up_saves_the_work_without_one(client, ctx):
    r = await _work(client, ctx, "first floor")
    assert r.status_code == 201 and "place" not in r.json()


async def test_progress_grid_and_whats_left_on_a_floor(client, ctx):
    await _setup(client, ctx)
    for room in ("first floor room-1", "first floor room 2", "onnam nila kitchen"):
        assert (await _work(client, ctx, room, finished=True)).status_code == 201
    assert (await _work(client, ctx, "GF kitchen", work_type="Brickwork")).status_code == 201
    assert (await _work(client, ctx, "1st floor R1", work_type="brickwork ")).status_code == 201

    grid = (await client.get(f"/projects/{ctx['project']}/places/progress", headers=_h(ctx["engineer"]))).json()
    assert [k["key"] for k in grid["kinds"]] == ["plastering", "brickwork"]
    by = {p["label"]: p for p in grid["places"]}
    assert by["First Floor"]["cells"]["plastering"]["state"] == "done"  # every room done
    assert by["First Floor"]["cells"]["brickwork"]["state"] == "in_progress"
    assert by["Ground Floor"]["cells"]["plastering"]["state"] == "not_started"
    assert by["Ground Floor / Kitchen"]["cells"]["brickwork"]["state"] == "in_progress"

    left = (await client.get(f"/projects/{ctx['project']}/places/progress", params={"place": "first floor"},
                             headers=_h(ctx["engineer"]))).json()
    assert left["place"] == "First Floor"
    assert left["places"][0]["left"] == ["Brickwork"] and left["places"][0]["done"] == ["Plastering"]
    assert len(left["places"]) == 4  # the floor and its three rooms

    unknown = (await client.get(f"/projects/{ctx['project']}/places/progress", params={"place": "third floor"},
                                headers=_h(ctx["engineer"]))).json()
    assert unknown["place"] is None and unknown["options"] == ["Ground Floor", "First Floor"]


async def test_place_work_lists_the_rooms_work(client, ctx):
    made = await _setup(client, ctx)
    await _work(client, ctx, "FF R2", finished=True)
    first = next(p for p in made["places"] if p["label"] == "First Floor")
    r = await client.get(f"/projects/{ctx['project']}/places/{first['id']}/work", headers=_h(ctx["engineer"]))
    assert r.status_code == 200
    work = r.json()["work"]
    assert len(work) == 1 and work[0]["place"] == "First Floor / Room-2" and work[0]["finished"] is True


async def test_rename_move_and_archive_keeps_the_work(client, ctx, test_engine):
    made = await _setup(client, ctx)
    ids = {p["label"]: p["id"] for p in made["places"]}
    base = f"/projects/{ctx['project']}/places"
    r = await client.patch(f"{base}/{ids['Ground Floor / Room-1']}", json={"name": "Kitchen"}, headers=_h(ctx["admin"]))
    assert r.status_code == 422  # the floor already has a Kitchen
    r = await client.patch(f"{base}/{ids['Ground Floor / Room-1']}", json={"name": "Bedroom 1"},
                           headers=_h(ctx["admin"]))
    assert r.status_code == 200
    # Move a room to the other floor: its path follows.
    r = await client.patch(f"{base}/{ids['Ground Floor / Room-2']}",
                           json={"move": True, "parent_id": ids["First Floor"], "name": "Room-3"},
                           headers=_h(ctx["admin"]))
    assert r.status_code == 200, r.text
    labels = [p["label"] for p in (await client.get(base, headers=_h(ctx["admin"]))).json()["places"]]
    assert "First Floor / Room-3" in labels and "Ground Floor / Bedroom 1" in labels
    r = await client.patch(f"{base}/{ids['First Floor']}", json={"move": True, "parent_id": ids["First Floor"]},
                           headers=_h(ctx["admin"]))
    assert r.status_code == 422  # never inside itself

    await _work(client, ctx, "GF kitchen")
    assert (await client.delete(f"{base}/{ids['Ground Floor']}", headers=_h(ctx["admin"]))).json()["outcome"] == \
        "archived"
    assert (await client.delete(f"{base}/{ids['First Floor']}", headers=_h(ctx["admin"]))).json()["outcome"] == \
        "deleted"
    assert (await client.get(base, headers=_h(ctx["admin"]))).json()["places"] == []
    async with test_engine.begin() as conn:
        kept = (await conn.execute(sa.text("SELECT count(*) FROM activities WHERE project_id = :p "
                                           "AND location_id IS NOT NULL"), {"p": ctx["project"]})).scalar()
    assert kept == 1


def _structural_pdf() -> bytes:
    """A footing plan on a grid (A-C across, 1-3 down) with a footing schedule, laid out like a consultant's set."""
    from fpdf import FPDF

    pdf = FPDF(unit="pt", format="A4")
    pdf.add_page()
    pdf.set_font("Helvetica", size=6)
    items = [(130, 89, "A"), (250, 89, "B"), (370, 89, "C"), (78, 143, "1"), (78, 228, "2"), (78, 313, "3")]
    for x, y, col in ((130, 143, "C1"), (250, 143, "C1"), (370, 143, "C2"), (130, 228, "C1"), (250, 228, "C1"),
                      (250, 313, "C2")):
        items += [(x - 15, y - 15, "F1-250X250" if col == "C1" else "F2-220X220"), (x, y, col)]
    items += [(90, 600, "1 F1 250X250 70 20 16 nos. 16 dia bars 16 nos. 16 dia bars"),
              (90, 610, "2 F2 220X220 60 20 12 nos. 16 dia bars 12 nos. 16 dia bars"),
              (90, 700, "Grade of Concrete: M20"), (90, 710, "Grade of Steel: Fe 500"),
              (300, 700, "DWG NO :12/ST/01/01"), (300, 720, "DRAWING TITLE"), (300, 730, "FOOTING DETAILS")]
    for x, y, t in items:
        pdf.text(x, y, t)
    return bytes(pdf.output())


async def test_a_structural_drawing_becomes_a_live_footing_plan(client, ctx):
    """DR-10: upload the set, track its footings, site's "B3 footing concreted" turns B3 done on the plan."""
    r = await client.post(f"/projects/{ctx['project']}/documents", headers=_h(ctx["admin"]),
                          files={"file": ("S-01 footing plan.pdf", _structural_pdf(), "application/pdf")})
    assert r.status_code == 201, r.text
    doc = r.json()["id"]
    assert (await client.post(f"/documents/{doc}/track", headers=_h(ctx["engineer"]))).status_code == 403
    tracked = (await client.post(f"/documents/{doc}/track", headers=_h(ctx["admin"]))).json()
    assert tracked == {"made": 6, "tracked": 6, "untracked": 0}
    assert (await client.post(f"/documents/{doc}/track", headers=_h(ctx["admin"]))).json()["made"] == 0

    saved = await _work(client, ctx, "B3 footing concreted", work_type="Footing concrete", finished=True)
    assert saved.status_code == 201 and saved.json()["place"] == "Foundation / B3"
    await _work(client, ctx, "A1 PCC", work_type="PCC")

    live = (await client.get(f"/projects/{ctx['project']}/live-plan", headers=_h(ctx["engineer"]))).json()["live"]
    by = {m["grid"]: m for m in live["markers"]}
    assert set(by) == {"A1", "B1", "C1", "A2", "B2", "B3"}
    assert (by["B3"]["state"], by["B3"]["mark"], by["B3"]["last_work"]) == ("done", "F2", "Footing concrete")
    assert by["A1"]["state"] == "in_progress" and by["C1"]["state"] == "not_started"
    assert 0 < by["B3"]["x"] < 1 and 0 < by["B3"]["y"] < 1
    s = live["summary"]
    assert (s["done"], s["in_progress"], s["not_started"]) == (1, 1, 4)
    # B3 is an F2: 12 bars of 16 mm each way, 220 − 2×5 + 2×(20 − 10) = 230 cm long.
    assert s["steel_done_kg"] == pytest.approx(2 * 12 * 2.30 * 256 / 162, abs=0.2) and s["concrete_done_cum"] > 0
