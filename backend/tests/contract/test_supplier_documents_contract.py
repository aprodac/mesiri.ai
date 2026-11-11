"""PRC-52: supplier papers and delivery certificates on a real Postgres (run with `pytest -m integration`).

A supplier's own papers (GST, PAN, cheque, ...) are kept per supplier: upload, replace (the old one kept), archive (the
file kept), and a status per kind (valid, expiring within 15 days, expired, missing). A delivery's test certificate is
a project document in the test-reports folder linked to its GRN: it shows on the GRN and in the project's Documents.
A site engineer adds a certificate but never sees a PAN or a cheque; another company sees neither. Fixtures are the
quotations contract's (company, suppliers, items) with the documents contract's in-memory storage.
"""

from __future__ import annotations

import datetime
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from contract import test_rfqs_api_contract as rfq
from contract.company_day import company_today
from contract.test_documents_contract import _Storage
from contract.test_rfqs_api_contract import _exec, _user, _vendor_id
from contract.test_supplier_performance_contract import _order, _receive
from mesiri.http.app import create_app
from mesiri.infrastructure.objectstorage.dependency import get_object_storage
from mesiri.infrastructure.postgres.dependency import get_db_conn

pytestmark = pytest.mark.integration

test_engine, world = rfq.test_engine, rfq.world
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


@pytest.fixture
def storage():
    return _Storage()


@pytest.fixture
async def client(test_engine, monkeypatch, storage):
    monkeypatch.setattr("mesiri.domains.shared.modules._database_for", lambda request: None)
    app = create_app()

    async def override_get_db_conn():
        async with test_engine.begin() as conn:
            yield conn

    app.dependency_overrides[get_db_conn] = override_get_db_conn
    app.dependency_overrides[get_object_storage] = lambda: storage
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        yield c


async def _paper(client, w, vendor, kind, *, who="admin", until=None, number=None, body=PDF, name="paper.pdf"):
    data = {"kind": kind, **({"valid_until": str(until)} if until else {}), **({"number": number} if number else {})}
    return await client.post(f"/finance/vendors/{vendor}/documents", headers=w[who]["h"], data=data,
                             files={"file": (name, body, "application/pdf")})


def _kind(body: dict, kind: str) -> dict:
    return next(k for k in body["kinds"] if k["kind"] == kind)


async def test_supplier_papers_upload_replace_status_and_archive(client, world, storage):
    w = world
    malabar = await _vendor_id(client, w, "Malabar Hardware")  # has a GSTIN: GST and PAN are required
    start = (await client.get(f"/finance/vendors/{malabar}/documents", headers=w["admin"]["h"])).json()
    assert (_kind(start, "gst")["status"], _kind(start, "pan")["status"], _kind(start, "cheque")["status"]) == (
        "missing", "missing", "none")
    assert _kind(start, "pan")["on_record"] == "ABCDE1234F" and start["attention"] == "missing"  # PAN read from GSTIN

    today = company_today()
    first = await _paper(client, w, malabar, "gst", until=today + datetime.timedelta(days=400), number="32ABCDE1234F1Z5")
    assert first.status_code == 201, first.text
    assert _kind(first.json(), "gst")["status"] == "valid"
    soon = await _paper(client, w, malabar, "gst", until=today + datetime.timedelta(days=10), body=PDF + b" v2")
    gst = _kind(soon.json(), "gst")
    assert (gst["status"], gst["days_left"], len(gst["current"]), len(gst["history"])) == ("expiring", 10, 1, 1)
    old = await _paper(client, w, malabar, "pan", until=today - datetime.timedelta(days=1))
    body = old.json()
    assert _kind(body, "pan")["status"] == "expired" and body["attention"] == "expired"

    listed = {x["vendor_id"]: x for x in (await client.get("/finance/vendors/papers", headers=w["admin"]["h"])).json()["items"]}
    assert listed[malabar]["attention"] == "expired"
    assert {p["kind"] for p in listed[malabar]["papers"]} == {"gst", "pan"}

    newest = _kind(body, "gst")["current"][0]
    one = await client.get(f"/finance/vendors/{malabar}/documents/{newest['id']}", headers=w["admin"]["h"])
    assert one.status_code == 200 and one.json()["file_name"] == "paper.pdf"
    kept = len(storage.files)
    gone = await client.delete(f"/finance/vendors/{malabar}/documents/{newest['id']}", headers=w["admin"]["h"])
    assert gone.status_code == 200
    gst = _kind(gone.json(), "gst")
    assert gst["status"] == "valid" and gst["days_left"] > 300  # the one it replaced is current again
    assert len(storage.files) == kept  # archived: the file stays


async def test_a_grn_certificate_shows_on_the_grn_and_in_the_project_documents(client, world, test_engine):
    w = world
    order = await _order(client, w, company_today())
    received = await _receive(client, w, order, "100")
    grn = received["grns"][0]
    assert grn["needs_certificate"] is True and grn["certificates"] == []  # cement: a hint, never a blocker
    # A site engineer on the project adds it (anyone who can record the GRN).
    added = await client.post(f"/procurement/grns/{grn['id']}/certificates", headers=w["arun"]["h"],
                              data={"kind": "cement_test", "number": "CT-4521", "batch": "B-778"},
                              files={"file": ("mtc.pdf", PDF, "application/pdf")})
    assert added.status_code == 201, added.text
    cert = added.json()["certificates"][0]
    assert cert["title"] == f"Cement test certificate CT-4521 · Cement OPC 53 · {grn['ref']}"
    assert cert["notes"] == "Heat / batch: B-778"
    seen = (await client.get(f"/procurement/orders/{order['id']}", headers=w["admin"]["h"])).json()["grns"][0]
    assert [c["id"] for c in seen["certificates"]] == [cert["id"]]
    docs = (await client.get(f"/projects/{w['villa']}/documents", params={"folder": "test_report"},
                             headers=w["arun"]["h"])).json()["documents"]
    assert [(d["id"], d["goods_receipt_id"], d["goods_receipt_number"], d["number"]) for d in docs] == [
        (cert["id"], grn["id"], grn["number"], None)]  # never given a number, so never another paper's revision
    bad = await client.post(f"/procurement/grns/{grn['id']}/certificates", headers=w["admin"]["h"],
                            data={"kind": "nonsense"}, files={"file": ("x.pdf", PDF, "application/pdf")})
    assert bad.status_code == 422


async def test_site_engineers_see_no_pan_or_cheque_and_other_companies_see_nothing(client, world, test_engine):
    w = world
    malabar = await _vendor_id(client, w, "Malabar Hardware")
    pan = (await _paper(client, w, malabar, "pan")).json()
    pan_id = _kind(pan, "pan")["current"][0]["id"]
    site = (await client.get(f"/finance/vendors/{malabar}/documents", headers=w["arun"]["h"])).json()
    assert {k["kind"] for k in site["kinds"]} == {"gst", "iso_bis", "other"} and site["may_add"] is False
    assert (await client.get(f"/finance/vendors/{malabar}/documents/{pan_id}", headers=w["arun"]["h"])).status_code == 404
    assert (await _paper(client, w, malabar, "gst", who="arun")).status_code == 403

    order = await _order(client, w, company_today())
    grn = (await _receive(client, w, order, "100"))["grns"][0]
    other = uuid.uuid4()
    await _exec(test_engine, "INSERT INTO organizations (id, name, deployment_type, db_route, status, created_at, "
                "updated_at) VALUES (:id, 'Other', 'local', 'default', 'active', now(), now())", id=other)
    stranger = await _user(test_engine, other, "admin", "Stranger")
    assert (await client.get(f"/finance/vendors/{malabar}/documents", headers=stranger["h"])).status_code == 404
    assert (await client.get(f"/finance/vendors/{malabar}/documents/{pan_id}", headers=stranger["h"])).status_code == 404
    assert (await client.get("/finance/vendors/papers", headers=stranger["h"])).json()["items"] == []
    assert (await client.post(f"/procurement/grns/{grn['id']}/certificates", headers=stranger["h"], data={"kind": "other"},
                              files={"file": ("x.pdf", PDF, "application/pdf")})).status_code == 404
