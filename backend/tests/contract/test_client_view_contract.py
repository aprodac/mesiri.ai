"""Contract tests for the client view (CV-01, CV-02): secret links and what the client sees.

Requires a live Postgres reachable via Settings().postgres.dsn() -- run with `pytest -m integration`.
Fixtures mirror test_billing_contract.py.

The guards that matter most: nothing priced at our cost or rate reaches the page (``test_page_never_shows``), a
revoked or made-up link is a 404 that says nothing, one company's link never shows another company's data, and a
photo from a site report nobody approved stays off the page.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from mesiri.bootstrap.settings import Settings
from mesiri.domains.client_view import links
from mesiri.domains.identity.auth_service import create_access_token
from mesiri.http.app import create_app
from mesiri.infrastructure.objectstorage.dependency import get_object_storage
from mesiri.infrastructure.objectstorage.fake import FakeObjectStorage
from mesiri.infrastructure.postgres.dependency import get_db_conn

pytestmark = pytest.mark.integration


class _Store(FakeObjectStorage):
    async def generate_presigned_url(self, key, *, expires_in_seconds=900, method="GET"):
        return f"https://files.test/{key}"


@pytest.fixture
async def test_engine():
    engine = create_async_engine(Settings().postgres.dsn(), echo=False)
    yield engine
    await engine.dispose()


@pytest.fixture
async def clean_db(test_engine: AsyncEngine):
    yield
    async with test_engine.begin() as conn:
        await conn.execute(sa.text("DELETE FROM client_receipts"))
        await conn.execute(sa.text("DELETE FROM ra_bills"))
        # Its own bank account, so suites that wipe users afterwards are not blocked by it (the INF-33 class).
        await conn.execute(sa.text("DELETE FROM money_transactions WHERE to_account_id IN (SELECT id FROM money_accounts "
                                   "WHERE name = 'HDFC current 5521')"))
        await conn.execute(sa.text("DELETE FROM money_accounts WHERE name = 'HDFC current 5521'"))


@pytest.fixture
async def client(test_engine: AsyncEngine, monkeypatch, clean_db):
    monkeypatch.setattr("mesiri.domains.shared.modules._database_for", lambda request: None)
    app = create_app()

    async def override_get_db_conn():
        async with test_engine.begin() as conn:
            yield conn

    app.dependency_overrides[get_db_conn] = override_get_db_conn
    app.dependency_overrides[get_object_storage] = _Store
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        yield c


async def _exec(engine, sql: str, **params):
    async with engine.begin() as conn:
        return await conn.execute(sa.text(sql), params)


async def _org(engine, name="Builders Co") -> uuid.UUID:
    org_id = uuid.uuid4()
    await _exec(engine, "INSERT INTO organizations (id, name, deployment_type, db_route, status, created_at, updated_at) "
                        "VALUES (:id, :n, 'local', 'default', 'active', now(), now())", id=org_id, n=name)
    return org_id


async def _user(engine, org_id, role: str, projects: list | None = None) -> dict:
    user_id = uuid.uuid4()
    policy = {"mode": "selected_projects", "projects": [str(p) for p in projects]} if projects is not None \
        else {"mode": "all_projects", "projects": []}
    await _exec(engine, "INSERT INTO users (id, organization_id, email, hashed_password, full_name, role, status, "
                        "access_policy, created_at, updated_at) VALUES (:id, :org, :email, 'hash', 'Office', :role, "
                        "'active', CAST(:policy AS jsonb), now(), now())",
                id=user_id, org=org_id, email=f"{uuid.uuid4().hex[:8]}@example.com", role=role,
                policy=json.dumps(policy))
    if projects:
        for p in projects:
            await _exec(engine, "INSERT INTO project_members (id, project_id, user_id, role, site_access_mode) "
                                "VALUES (gen_random_uuid(), :p, :u, :r, 'all_sites')", p=p, u=user_id, r=role)
    token = create_access_token(data={"sub": str(user_id), "org": str(org_id), "role": role})
    return {"Authorization": f"Bearer {token}"}


async def _project(engine, org_id, name="Villa Kakkanad") -> tuple[uuid.UUID, uuid.UUID]:
    project_id, site_id = uuid.uuid4(), uuid.uuid4()
    await _exec(engine, "INSERT INTO projects (id, organization_id, name, created_at, updated_at) "
                        "VALUES (:id, :org, :n, now(), now())", id=project_id, org=org_id, n=name)
    await _exec(engine, "INSERT INTO sites (id, project_id, organization_id, name, status, created_at, updated_at) "
                        "VALUES (:id, :p, :org, 'Main building', 'active', now(), now())",
                id=site_id, p=project_id, org=org_id)
    return project_id, site_id


@pytest.fixture
async def co(test_engine):
    org = await _org(test_engine)
    project, site = await _project(test_engine, org)
    return {"org": org, "project": project, "site": site, "admin": await _user(test_engine, org, "admin")}


async def _link(client, co, label="Mr. Thomas") -> dict:
    r = await client.post(f"/projects/{co['project']}/client-links", json={"label": label}, headers=co["admin"])
    assert r.status_code == 201, r.text
    return r.json()


async def _boq_and_bill(client, co, test_engine) -> dict:
    """A priced BOQ line, measured work on it, a submitted RA bill, money received against it, and a draft bill."""
    h, base = co["admin"], f"/projects/{co['project']}/boq"
    sec = (await client.post(f"{base}/sections", json={"name": "Structure"}, headers=h)).json()
    line = (await client.post(f"{base}/sections/{sec['id']}/lines", json={
        "work": "M20 in slab", "unit": "cum", "planned_quantity": "300", "client_rate": "6500",
        "budget_rate": "5100"}, headers=h)).json()
    await client.put(f"/projects/{co['project']}/contract", json={
        "contract_value": "25000000", "retention_pct": "5", "gst_pct": "18", "tds_pct": "2",
        "new_client": {"name": "Mr. Thomas"}}, headers=h)
    async with test_engine.begin() as conn:
        unit_id = (await conn.execute(sa.text("SELECT id FROM units_of_measure WHERE code = 'cum'"))).scalar_one()
        activity_id = uuid.uuid4()
        await conn.execute(sa.text(
            "INSERT INTO activities (id, organization_id, project_id, site_id, work_type, activity_date, source) "
            "VALUES (:id, :org, :p, :s, 'work', current_date, 'dashboard')"),
            {"id": activity_id, "org": co["org"], "p": co["project"], "s": co["site"]})
        await conn.execute(sa.text(
            "INSERT INTO activity_quantities (id, activity_id, unit_id, quantity, planned_item_id) "
            "VALUES (:id, :a, :u, :q, :line)"),
            {"id": uuid.uuid4(), "a": activity_id, "u": unit_id, "q": Decimal("120"), "line": line["id"]})
        creator = (await conn.execute(sa.text("SELECT id FROM users WHERE organization_id = :o LIMIT 1"),
                                      {"o": co["org"]})).scalar_one()
        account = uuid.uuid4()
        await conn.execute(sa.text(
            "INSERT INTO money_accounts (id, organization_id, account_type, name, opening_balance, opening_balance_date, "
            "created_by) VALUES (:id, :org, 'bank', 'HDFC current 5521', 0, current_date - 90, :u)"),
            {"id": account, "org": co["org"], "u": creator})
    bill = (await client.post(f"/projects/{co['project']}/ra-bills", json={"bill_date": "2026-10-01"},
                              headers=h)).json()
    assert (await client.post(f"/billing/ra-bills/{bill['id']}/submit", headers=h)).status_code == 200
    r = await client.post("/billing/receipts", headers=h, json={
        "ra_bill_id": bill["id"], "amount": "500000", "account_id": str(account), "reference": "NEFT 778"})
    assert r.status_code == 201, r.text
    return (await client.get(f"/billing/ra-bills/{bill['id']}", headers=h)).json()


async def test_link_made_once_listed_without_its_token_and_opened_without_login(client, co):
    made = await _link(client, co)
    token = made["token"]
    assert links.well_formed(token) and made["link"]["label"] == "Mr. Thomas"
    listed = (await client.get(f"/projects/{co['project']}/client-links", headers=co["admin"])).json()["links"]
    assert [x["id"] for x in listed] == [made["link"]["id"]]
    assert token not in json.dumps(listed)  # the token is never shown again
    assert (await client.get("/client-links", headers=co["admin"])).json()["links"][0]["project_name"] == "Villa Kakkanad"

    r = await client.get(f"/client/{token}")  # no Authorization header
    assert r.status_code == 200, r.text
    page = r.json()
    assert page["project"]["name"] == "Villa Kakkanad" and page["company"]["name"] == "Builders Co"
    assert r.headers["cache-control"] == "no-store"
    opened = (await client.get(f"/projects/{co['project']}/client-links", headers=co["admin"])).json()["links"][0]
    assert opened["open_count"] == 1 and opened["last_opened_at"]


async def test_revoked_unknown_and_malformed_links_are_the_same_404(client, co):
    made = await _link(client, co)
    r = await client.post(f"/client-links/{made['link']['id']}/revoke", headers=co["admin"])
    assert r.status_code == 200 and r.json()["link"]["revoked_at"]
    for token in (made["token"], links.new_token(), "short", "x" * 43 + "'"):
        r = await client.get(f"/client/{token}")
        assert r.status_code == 404 and "not valid" in r.json()["detail"], token


async def test_who_may_share(client, co, test_engine):
    url = f"/projects/{co['project']}/client-links"
    for role, code in (("finance", 201), ("owner", 201), ("project_manager", 403), ("site_engineer", 403)):
        h = await _user(test_engine, co["org"], role)
        assert (await client.post(url, json={}, headers=h)).status_code == code, role
        assert (await client.get("/client-links", headers=h)).status_code == (200 if code == 201 else 403), role
    # Finance limited to another project can neither share nor revoke this one.
    other, _ = await _project(test_engine, co["org"], "Other job")
    limited = await _user(test_engine, co["org"], "finance", projects=[other])
    assert (await client.post(url, json={}, headers=limited)).status_code == 403
    made = await _link(client, co)
    assert (await client.post(f"/client-links/{made['link']['id']}/revoke", headers=limited)).status_code == 403
    assert all(x["project_id"] != str(co["project"])
               for x in (await client.get("/client-links", headers=limited)).json()["links"])
    assert (await client.post(f"/projects/{uuid.uuid4()}/client-links", json={}, headers=co["admin"])).status_code \
        in (403, 404)


async def test_another_companys_admin_cannot_see_or_revoke_a_link(client, co, test_engine):
    made = await _link(client, co)
    other_org = await _org(test_engine, "Rival Builders")
    rival = await _user(test_engine, other_org, "admin")
    assert (await client.get("/client-links", headers=rival)).json()["links"] == []
    assert (await client.post(f"/client-links/{made['link']['id']}/revoke", headers=rival)).status_code == 404
    assert (await client.post(f"/projects/{co['project']}/client-links", json={}, headers=rival)).status_code == 404
    # The rival's own link shows the rival's project, never ours.
    rival_project, _ = await _project(test_engine, other_org, "Rival tower")
    r = await client.post(f"/projects/{rival_project}/client-links", json={}, headers=rival)
    page = (await client.get(f"/client/{r.json()['token']}")).json()
    assert page["project"]["name"] == "Rival tower" and page["company"]["name"] == "Rival Builders"
    assert page["bills"] == [] and page["payments"] == []


async def test_page_shows_bills_and_money_received_but_never_rates_costs_or_accounts(client, co, test_engine):
    bill = await _boq_and_bill(client, co, test_engine)
    # A second bill left in draft (more work measured since) must not show.
    activity_id = uuid.uuid4()
    await _exec(test_engine, "INSERT INTO activities (id, organization_id, project_id, site_id, work_type, "
                             "activity_date, source) VALUES (:id, :org, :p, :s, 'work', current_date, 'dashboard')",
                id=activity_id, org=co["org"], p=co["project"], s=co["site"])
    await _exec(test_engine, "INSERT INTO activity_quantities (id, activity_id, unit_id, quantity, planned_item_id) "
                             "SELECT gen_random_uuid(), :a, unit_id, 30, planned_item_id FROM activity_quantities "
                             "WHERE planned_item_id IS NOT NULL AND activity_id IN (SELECT id FROM activities "
                             "WHERE project_id = :p) LIMIT 1", a=activity_id, p=co["project"])
    draft = await client.post(f"/projects/{co['project']}/ra-bills", json={}, headers=co["admin"])
    assert draft.status_code == 201 and draft.json()["status"] == "draft", draft.text
    page = (await client.get(f"/client/{(await _link(client, co))['token']}")).json()

    [shown] = page["bills"]
    assert shown["ref"] == "RA-01" and shown["status"] == "submitted" and shown["net"] == bill["net"]
    assert shown["received"] == "500000.00"
    assert Decimal(shown["left"]) == Decimal(bill["net"]) - 500000
    assert page["totals"]["received"] == "500000.00" and page["totals"]["due"] == shown["left"]
    assert [(p["amount"], p["bill_ref"]) for p in page["payments"]] == [("500000.00", "RA-01")]
    assert page["project"]["contract_value"] == "25000000.00" and page["project"]["client_name"] == "Mr. Thomas"

    text = json.dumps(page)
    for never in ("6500", "5100", "budget", "client_rate", "rate", "HDFC", "5521", "account", "NEFT 778", "Office",
                  "lines", "cost", "vendor", "supplier"):
        assert never not in text, never


async def test_page_never_shows_fields_outside_the_allow_list(client, co, test_engine):
    await _boq_and_bill(client, co, test_engine)
    page = (await client.get(f"/client/{(await _link(client, co))['token']}")).json()
    assert set(page) == {"company", "project", "today", "schedule", "schedule_kind", "photos", "bills", "payments",
                         "totals"}
    assert set(page["company"]) == {"name", "phone", "brand_color", "logo_url"}
    assert set(page["project"]) == {"name", "stage", "start_date", "contract_finish", "forecast_finish", "slip_days",
                                    "progress", "contract_value", "client_name"}
    for b in page["bills"]:
        assert set(b) == {"ref", "bill_date", "period_to", "status", "gross", "retention", "advance_recovery", "gst",
                          "tds", "net", "certified_amount", "certified_on", "received", "left"}
    for p in page["payments"]:
        assert set(p) == {"received_on", "amount", "kind", "bill_ref"}
    for a in page["schedule"]:
        assert set(a) == {"name", "milestone", "start", "end", "actual_start", "actual_end", "done", "progress",
                          "state", "forecast_end"}


async def _photo(engine, co, key: str, report_status: str | None) -> None:
    """A photo on today's work; a site report for today in ``report_status`` (None: no report)."""
    activity_id = uuid.uuid4()
    await _exec(engine, "INSERT INTO activities (id, organization_id, project_id, site_id, work_type, activity_date, "
                        "source) VALUES (:id, :org, :p, :s, 'Brickwork', current_date, 'dashboard')",
                id=activity_id, org=co["org"], p=co["project"], s=co["site"])
    await _exec(engine, "INSERT INTO progress_attachments (id, parent_type, parent_id, media_object_key, "
                        "attachment_type, mime_type, caption, created_at) VALUES (:id, 'ACTIVITY', :a, :k, 'photo', "
                        "'image/jpeg', 'East wall', now())", id=uuid.uuid4(), a=activity_id, k=key)
    if report_status:
        await _exec(engine, "INSERT INTO daily_reports (id, organization_id, project_id, site_id, level, report_date, "
                            "code, status) VALUES (:id, :org, :p, :s, 'SITE', CAST(now() AT TIME ZONE 'Asia/Kolkata' "
                            "AS date), :code, CAST(:st AS daily_report_status)) ON CONFLICT DO NOTHING",
                    id=uuid.uuid4(), org=co["org"], p=co["project"], s=co["site"],
                    code=f"DPR-{uuid.uuid4().hex[:6]}", st=report_status)


async def test_photos_only_from_site_reports_the_company_approved(client, co, test_engine):
    token = (await _link(client, co))["token"]
    await _photo(test_engine, co, f"{co['org']}/unreviewed.jpg", None)
    assert (await client.get(f"/client/{token}")).json()["photos"] == []
    await _exec(test_engine, "DELETE FROM daily_reports WHERE project_id = :p", p=co["project"])
    await _photo(test_engine, co, f"{co['org']}/in-review.jpg", "IN_REVIEW")
    assert (await client.get(f"/client/{token}")).json()["photos"] == []
    await _exec(test_engine, "UPDATE daily_reports SET status = 'APPROVED' WHERE project_id = :p", p=co["project"])
    photos = (await client.get(f"/client/{token}")).json()["photos"]
    assert {p["url"] for p in photos} == {f"https://files.test/{co['org']}/unreviewed.jpg",
                                          f"https://files.test/{co['org']}/in-review.jpg"}
    assert photos[0]["caption"] == "East wall" and photos[0]["work"] == "Brickwork"
