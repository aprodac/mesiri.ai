"""Contract tests for the documents and drawings register (DOC-01, DOC-05 find, DR-07 facts kept, DR-08 facts).

Requires a live Postgres reachable via Settings().postgres.dsn() -- run with `pytest -m integration`. Files go to
the in-memory object storage.
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
from mesiri.infrastructure.objectstorage.dependency import get_object_storage
from mesiri.infrastructure.postgres.dependency import get_db_conn

pytestmark = pytest.mark.integration


def _drawing(number="S-101", rev="B", title="GROUND FLOOR PLAN", extra="") -> bytes:
    from fpdf import FPDF

    pdf = FPDF(unit="pt", format="A4")
    pdf.add_page()
    pdf.set_font("Helvetica", size=6)
    for x, y, text in [(340, 300, "ROOM-1"), (334, 307, "1740 x 590"), (336, 314, "1217 Sq.ft"),
                       (340, 420, "KITCHEN"), (334, 427, "400 x 300"),
                       (409, 722, "DWG.TITLE:"), (469, 734, title), (458, 771, "1:100"),
                       (300, 722, "DWG.NO"), (300, 734, number), (250, 722, "REV"), (250, 734, rev),
                       (100, 100, extra)]:
        pdf.text(x, y, text)
    return bytes(pdf.output())


class _Storage:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    async def put_object(self, key, data, *, content_type=None):
        self.files[key] = data

    async def get_object(self, key):
        from types import SimpleNamespace

        return SimpleNamespace(data=self.files[key], content_type=None)

    async def generate_presigned_url(self, key, *, expires_in_seconds=900, method="GET"):
        return f"https://files.test/{key}"


@pytest.fixture
async def test_engine():
    engine = create_async_engine(Settings().postgres.dsn(), echo=False)
    yield engine
    await engine.dispose()


@pytest.fixture
def storage():
    return _Storage()


@pytest.fixture
async def client(test_engine: AsyncEngine, monkeypatch, storage):
    monkeypatch.setattr("mesiri.domains.shared.modules._database_for", lambda request: None)
    app = create_app()

    async def override_get_db_conn():
        async with test_engine.begin() as conn:
            yield conn

    app.dependency_overrides[get_db_conn] = override_get_db_conn
    app.dependency_overrides[get_object_storage] = lambda: storage
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        yield c


async def _user(engine, org_id, role: str) -> str:
    user_id = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(sa.text(
            "INSERT INTO users (id, organization_id, email, hashed_password, full_name, role, status, access_policy, "
            "created_at, updated_at) VALUES (:id, :org, :email, 'hash', 'Anu', :role, 'active', "
            "CAST('{\"mode\": \"all_projects\", \"projects\": []}' AS jsonb), now(), now())"),
            {"id": user_id, "org": org_id, "email": f"{uuid.uuid4().hex[:8]}@example.com", "role": role})
    return create_access_token(data={"sub": str(user_id), "org": str(org_id), "role": role})


@pytest.fixture
async def ctx(test_engine):
    org, project = uuid.uuid4(), uuid.uuid4()
    async with test_engine.begin() as conn:
        await conn.execute(sa.text(
            "INSERT INTO organizations (id, name, deployment_type, db_route, status, created_at, updated_at) "
            "VALUES (:id, 'Docs Org', 'local', 'default', 'active', now(), now())"), {"id": org})
        await conn.execute(sa.text("INSERT INTO projects (id, organization_id, name, created_at, updated_at) "
                                   "VALUES (:id, :org, 'Green Villa', now(), now())"), {"id": project, "org": org})
    yield {"org": org, "project": project, "pm": await _user(test_engine, org, "project_manager"),
            "engineer": await _user(test_engine, org, "site_engineer")}
    # Leave nothing behind for the suites after this one (they delete users; places and documents point at them).
    async with test_engine.begin() as conn:
        await conn.execute(sa.text("DELETE FROM project_documents WHERE organization_id = :org"), {"org": org})
        await conn.execute(sa.text("DELETE FROM organizations WHERE id = :org"), {"org": org})


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _up(client, ctx, name, data, who="pm", **form):
    return await client.post(f"/projects/{ctx['project']}/documents", headers=_h(ctx[who]),
                             files={"file": (name, data, "application/octet-stream")},
                             data={k: str(v) for k, v in form.items()})


async def test_a_drawing_pdf_is_kept_with_its_title_block_and_facts(client, ctx, storage):
    # An architect's plan (A- number): its rooms are read. (An S- sheet is structural: no rooms, DR-09.)
    r = await _up(client, ctx, "ground floor.pdf", _drawing(number="A-101"))
    assert r.status_code == 201, r.text
    doc = r.json()
    assert (doc["folder"], doc["number"], doc["revision"], doc["discipline"]) == ("drawing", "A-101", "B",
                                                                                  "architectural")
    assert set(doc["guessed"]) >= {"folder", "number", "revision", "title"} and doc["has_facts"] is True
    assert doc["checks"] >= 1  # ROOM-1 labelled 1217 sq ft, drawn 1,105
    assert any(k.startswith(f"documents/{ctx['org']}/{ctx['project']}/") for k in storage.files)

    detail = (await client.get(f"/documents/{doc['id']}", headers=_h(ctx["engineer"]))).json()
    assert detail["url"].startswith("https://files.test/documents/") and detail["facts"]["checks"]

    facts = (await client.get(f"/projects/{ctx['project']}/drawing-facts", params={"q": "kitchen"},
                              headers=_h(ctx["engineer"]))).json()
    assert [r["label"] for r in facts["rooms"]] == ["KITCHEN"] and facts["rooms"][0]["floor"] == "Ground floor" and facts["rooms"][0]["revision"] == "B"


async def test_same_file_twice_is_refused(client, ctx):
    data = _drawing()
    assert (await _up(client, ctx, "a.pdf", data)).status_code == 201
    r = await _up(client, ctx, "copy of a.pdf", data)
    assert r.status_code == 409 and "already kept" in r.json()["detail"]["message"]


async def test_a_new_revision_supersedes_the_old_and_find_sends_the_current(client, ctx):
    old = (await _up(client, ctx, "s101.pdf", _drawing(rev="B"))).json()
    # Site may not issue a revision.
    r = await _up(client, ctx, "s101 c.pdf", _drawing(rev="C", extra="x"), who="engineer")
    assert r.status_code == 403 and "rev B is current" in r.json()["detail"]
    r = await _up(client, ctx, "s101 c.pdf", _drawing(rev="C", extra="x"))
    assert r.status_code == 201 and r.json()["superseded"]["revision"] == "B"
    new = r.json()
    hist = (await client.get(f"/documents/{new['id']}", headers=_h(ctx["pm"]))).json()["history"]
    assert [(h["revision"], h["status"]) for h in hist] == [("C", "current"), ("B", "superseded")]

    found = (await client.get(f"/projects/{ctx['project']}/documents/find", params={"q": "latest S-101 drawing"},
                              headers=_h(ctx["engineer"]))).json()
    assert [d["revision"] for d in found["documents"]] == ["C"]

    # Archiving the current revision brings the one before back.
    assert (await client.delete(f"/documents/{new['id']}", headers=_h(ctx["engineer"]))).status_code == 403
    assert (await client.delete(f"/documents/{new['id']}", headers=_h(ctx["pm"]))).status_code == 200
    again = (await client.get(f"/projects/{ctx['project']}/documents", headers=_h(ctx["pm"]))).json()
    assert [(d["id"], d["status"]) for d in again["documents"]] == [(old["id"], "current")]

    # The explicit route: a new revision of that document.
    r = await client.post(f"/documents/{old['id']}/revisions", headers=_h(ctx["pm"]), data={"revision": "D"},
                          files={"file": ("any name.pdf", _drawing(rev="B", extra="y"), "application/pdf")})
    assert r.status_code == 201 and r.json()["revision"] == "D" and r.json()["number"] == "S-101"


async def test_money_papers_only_reach_the_office(client, ctx):
    r = await _up(client, ctx, "Building agreement signed.pdf", _drawing(number="", title="", extra="agreement"))
    assert r.status_code == 201 and r.json()["folder"] == "contract"
    permit = await _up(client, ctx, "Building permit.jpg", b"\xff\xd8\xff fake jpeg", valid_until="2026-11-20")
    assert permit.status_code == 201 and permit.json()["folder"] == "approval"

    site = (await client.get(f"/projects/{ctx['project']}/documents", headers=_h(ctx["engineer"]))).json()
    assert [d["folder"] for d in site["documents"]] == ["approval"] and site["sees_restricted"] is False
    assert site["expiring"][0]["title"] == "Building permit"
    office = (await client.get(f"/projects/{ctx['project']}/documents", headers=_h(ctx["pm"]))).json()
    assert {d["folder"] for d in office["documents"]} == {"approval", "contract"}
    contract_id = next(d["id"] for d in office["documents"] if d["folder"] == "contract")
    assert (await client.get(f"/documents/{contract_id}", headers=_h(ctx["engineer"]))).status_code == 404
    found = (await client.get(f"/projects/{ctx['project']}/documents/find", params={"q": "agreement"},
                              headers=_h(ctx["engineer"]))).json()
    assert found["documents"] == []
    found = (await client.get(f"/projects/{ctx['project']}/documents/find", params={"q": "building permit evide"},
                              headers=_h(ctx["engineer"]))).json()
    assert [d["title"] for d in found["documents"]] == ["Building permit"]


async def test_unknown_kinds_and_bad_pdfs_are_refused(client, ctx):
    assert (await _up(client, ctx, "virus.exe", b"MZ")).status_code == 415
    assert (await _up(client, ctx, "plan.pdf", b"not a pdf")).status_code == 422


async def test_uploader_corrects_details_but_cannot_restrict(client, ctx):
    doc = (await _up(client, ctx, "Cube test report.pdf", _drawing(number="", title="", extra="cube"),
                     who="engineer")).json()
    url = f"/documents/{doc['id']}"
    assert (await client.patch(url, json={"title": "Cube test 28 days"}, headers=_h(ctx["engineer"]))).status_code \
        == 200
    assert (await client.patch(url, json={"restricted": True}, headers=_h(ctx["engineer"]))).status_code == 403
    r = await client.patch(url, json={"restricted": True}, headers=_h(ctx["pm"]))
    assert r.status_code == 200 and r.json()["restricted"] is True
    listed = (await client.get(f"/projects/{ctx['project']}/documents", headers=_h(ctx["engineer"]))).json()
    assert listed["documents"] == []


async def test_the_file_route_names_the_revision_and_keeps_money_papers_in(client, ctx):
    drawing = (await _up(client, ctx, "s101.pdf", _drawing(rev="C"))).json()
    r = await client.get(f"/documents/{drawing['id']}/file", headers=_h(ctx["engineer"]))
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    assert (r.headers["x-document-status"], r.headers["x-document-revision"], r.headers["x-document-number"]) == \
        ("current", "C", "S-101")
    assert 'filename="s101.pdf"' in r.headers["content-disposition"]
    contract = (await _up(client, ctx, "Agreement.pdf", _drawing(number="", title="", extra="agreement"))).json()
    assert (await client.get(f"/documents/{contract['id']}/file", headers=_h(ctx["engineer"]))).status_code == 404
    assert (await client.get(f"/documents/{contract['id']}/file", headers=_h(ctx["pm"]))).status_code == 200
