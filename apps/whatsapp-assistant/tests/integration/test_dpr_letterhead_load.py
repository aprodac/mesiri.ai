"""BE-19: load_letterhead reads company, branding and client logo for a DPR."""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import text
from tests.fixtures.db import build_sync_engine

from channel.dpr_document.letterhead import load_letterhead
from context.runtime import _LazyAsyncEngine
from mesiri.infrastructure.objectstorage.fake import FakeObjectStorage

pytestmark = pytest.mark.integration

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


@pytest.fixture
def world():
    engine = build_sync_engine()
    org, project, report, bare_report = (uuid.uuid4() for _ in range(4))
    logo = f"org/{org}/branding/logo-x.png"
    client_logo = f"org/{org}/projects/{project}/client-logo-x.png"
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO organizations (id, name, status, db_route, deployment_type, address, "
                "phone, email) VALUES (:id, 'Acme', 'active', 'shared', 'SaaS', '12 MG Road', "
                "'+91 20 1234', 'office@acme.test')"
            ),
            {"id": org},
        )
        c.execute(
            text(
                "INSERT INTO projects (id, organization_id, name, status, client, "
                "client_logo_object_key) VALUES (:id, :o, 'Skyline', 'on_track', 'Skyline Dev', :k)"
            ),
            {"id": project, "o": org, "k": client_logo},
        )
        c.execute(
            text(
                "INSERT INTO organization_settings (id, organization_id, key, value) "
                "VALUES (:id, :o, 'branding', CAST(:v AS jsonb))"
            ),
            {
                "id": uuid.uuid4(),
                "o": org,
                "v": json.dumps(
                    {
                        "letterhead_name": "Acme Builders Pvt Ltd",
                        "brand_color": "#C2410C",
                        "gstin": "27AAPFU0939F1ZV",
                        "signatory_name": "R. Rao",
                        "logo_object_key": logo,
                    }
                ),
            },
        )
        for rid in (report, bare_report):
            c.execute(
                text(
                    "INSERT INTO daily_reports (id, organization_id, project_id, level, "
                    "report_date) VALUES (:id, :o, :p, 'PROJECT', '2026-10-13')"
                ),
                {"id": rid, "o": org, "p": project},
            )
    yield engine, org, project, report, logo, client_logo
    with engine.begin() as c:
        c.execute(text("DELETE FROM daily_reports WHERE organization_id = :o"), {"o": org})
        c.execute(text("DELETE FROM organization_settings WHERE organization_id = :o"), {"o": org})
        c.execute(text("DELETE FROM projects WHERE id = :p"), {"p": project})
        c.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": org})
    engine.dispose()


@pytest.mark.anyio
async def test_letterhead_from_company_branding_and_project(world):
    _, org, _, report, logo, client_logo = world
    storage = FakeObjectStorage()
    await storage.put_object(logo, PNG, content_type="image/png")
    await storage.put_object(client_logo, PNG, content_type="image/png")

    async with _LazyAsyncEngine().connect() as conn:
        lh = await load_letterhead(conn, storage, report)

    assert lh.company_name == "Acme Builders Pvt Ltd"
    assert lh.address == "12 MG Road"
    assert lh.contact == "+91 20 1234 · office@acme.test"
    assert lh.gstin == "27AAPFU0939F1ZV"
    assert lh.brand_color == "#C2410C"
    assert lh.signatory_name == "R. Rao"
    assert lh.client_name == "Skyline Dev"
    assert lh.logo_data_uri.startswith("data:image/png;base64,")
    assert lh.client_logo_data_uri.startswith("data:image/png;base64,")


@pytest.mark.anyio
async def test_missing_logo_files_and_unknown_report(world):
    _, _, _, report, _, _ = world

    async with _LazyAsyncEngine().connect() as conn:
        lh = await load_letterhead(conn, FakeObjectStorage(), report)  # files not stored
        unknown = await load_letterhead(conn, FakeObjectStorage(), uuid.uuid4())

    assert lh.company_name == "Acme Builders Pvt Ltd"
    assert lh.logo_data_uri is None and lh.client_logo_data_uri is None
    assert unknown is None


@pytest.mark.anyio
async def test_a_failed_lookup_leaves_the_sending_transaction_usable(world, monkeypatch):
    """project_auto_dpr hands over the transaction that then sends the DPR."""
    from channel.dpr_document import letterhead as module

    async def broken(conn, *_args):
        await conn.execute(text("SELECT * FROM table_that_does_not_exist"))

    monkeypatch.setattr(module, "_fetch", broken)
    _, _, _, report, _, _ = world

    async with _LazyAsyncEngine().connect() as conn, conn.begin():
        assert await load_letterhead(conn, FakeObjectStorage(), report) is None
        assert (await conn.execute(text("SELECT 1"))).scalar() == 1
