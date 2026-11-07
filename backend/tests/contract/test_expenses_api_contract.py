"""Contract/integration tests for the narrow Expenses REST API.

Covers: idempotent RecordExpense (retried request with the same
Idempotency-Key returns the original outcome, not a second expense),
validation rejection, org isolation on read, and site/project authorization.

Requires a live Postgres reachable via Settings().postgres.dsn() — run with
`pytest -m integration`. Mirrors the fixture style of
test_materials_api_contract.py.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from contract.company_day import company_today
from mesiri.bootstrap.settings import Settings
from mesiri.domains.identity.auth_service import create_access_token
from mesiri.http.app import create_app
from mesiri.infrastructure.postgres.dependency import get_db_conn

pytestmark = pytest.mark.integration


@pytest.fixture
async def test_engine():
    settings = Settings()
    engine = create_async_engine(settings.postgres.dsn(), echo=False)
    yield engine
    await engine.dispose()


@pytest.fixture
async def clean_db(test_engine: AsyncEngine):
    async def wipe() -> None:
        async with test_engine.begin() as conn:
            await conn.execute(sa.text("DELETE FROM idempotency_keys WHERE command_type = 'record_expense'"))
            await conn.execute(sa.text("DELETE FROM notifications"))
            await conn.execute(sa.text("DELETE FROM expense_payments"))
            await conn.execute(sa.text("DELETE FROM money_transactions"))  # PRC-18: payments post one each
            await conn.execute(sa.text("DELETE FROM money_accounts"))
            await conn.execute(sa.text("DELETE FROM expense_attachments"))
            await conn.execute(sa.text("DELETE FROM expenses"))
            await conn.execute(sa.text("DELETE FROM vendors"))  # WEB-51: the list test names a vendor
            await conn.execute(sa.text("DELETE FROM expense_categories"))
            await conn.execute(sa.text("DELETE FROM sites"))
            await conn.execute(sa.text("DELETE FROM projects"))
            await conn.execute(sa.text("DELETE FROM users"))
            await conn.execute(sa.text("DELETE FROM organizations"))

    await wipe()
    yield
    # Also after: expenses left behind (they name vendors since WEB-51) made every later file's clean-up fail on
    # fk_expenses_vendor_id -- the 24 errors a full `contract/` run showed on 7 Nov.
    await wipe()


@pytest.fixture
async def client(test_engine: AsyncEngine, monkeypatch):
    # The module gate and the expense save handler (WA-121) open their own transaction on the app's database, which
    # is the in-memory fake under the test settings: point them at the real one.
    from mesiri.infrastructure.postgres.database import PostgresDatabase

    database = PostgresDatabase(Settings().postgres)
    await database.connect()
    monkeypatch.setattr("mesiri.domains.shared.modules._database_for", lambda request: database)
    monkeypatch.setattr("mesiri.domains.shared.modules.database_for", lambda request: database)
    app = create_app()

    async def override_get_db_conn():
        async with test_engine.begin() as conn:
            yield conn

    app.dependency_overrides[get_db_conn] = override_get_db_conn
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as test_client:
        yield test_client


@pytest.fixture
async def test_org(test_engine: AsyncEngine, clean_db):
    org_id = uuid.uuid4()
    async with test_engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO organizations (id, name, deployment_type, db_route, status, "
                "created_at, updated_at) VALUES (:id, :name, 'local', 'default', 'active', now(), now())"
            ),
            {"id": org_id, "name": "Test Org"},
        )
    return org_id


async def _make_user(test_engine, org_id, role: str) -> uuid.UUID:
    user_id = uuid.uuid4()
    async with test_engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO users (id, organization_id, email, hashed_password, full_name, "
                "role, status, access_policy, created_at, updated_at) "
                "VALUES (:id, :org_id, :email, 'hash', 'Test User', :role, 'active', "
                "CAST(:policy AS jsonb), now(), now())"
            ),
            {
                "id": user_id,
                "org_id": org_id,
                "email": f"{uuid.uuid4().hex[:8]}@example.com",
                "role": role,
                "policy": '{"mode": "all_projects", "projects": []}',
            },
        )
    return user_id


def _token(user_id: uuid.UUID, org_id: uuid.UUID, role: str) -> str:
    return create_access_token(data={"sub": str(user_id), "org": str(org_id), "role": role})


async def _make_project(test_engine, org_id) -> uuid.UUID:
    project_id = uuid.uuid4()
    async with test_engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO projects (id, organization_id, name, created_at, updated_at) "
                "VALUES (:id, :org_id, 'Test Project', now(), now())"
            ),
            {"id": project_id, "org_id": org_id},
        )
    return project_id


async def _make_category(test_engine, org_id, user_id) -> uuid.UUID:
    category_id = uuid.uuid4()
    async with test_engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO expense_categories (id, organization_id, name, status, created_by) "
                "VALUES (:id, :org_id, 'materials', 'active', :user_id)"
            ),
            {"id": category_id, "org_id": org_id, "user_id": user_id},
        )
    return category_id


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def admin_ctx(test_engine, test_org):
    user_id = await _make_user(test_engine, test_org, "admin")
    project_id = await _make_project(test_engine, test_org)
    category_id = await _make_category(test_engine, test_org, user_id)
    token = _token(user_id, test_org, "admin")
    return {
        "user_id": user_id,
        "project_id": project_id,
        "category_id": category_id,
        "token": token,
    }


def _body(ctx: dict, **overrides) -> dict:
    base = {
        "project_id": str(ctx["project_id"]),
        "category_id": str(ctx["category_id"]),
        "amount": "150.00",
        "occurred_date": company_today().isoformat(),
    }
    base.update(overrides)
    return base


async def test_record_expense_creates_confirmed_unpaid_expense(client, admin_ctx):
    resp = await client.post(
        "/expenses",
        json=_body(admin_ctx),
        headers={**_auth(admin_ctx["token"]), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert resp.status_code == 201, resp.text
    expense_id = resp.json()["id"]
    assert resp.json()["status"] == "succeeded"

    get_resp = await client.get(f"/expenses/{expense_id}", headers=_auth(admin_ctx["token"]))
    assert get_resp.status_code == 200
    body = get_resp.json()
    assert body["workflow_status"] == "confirmed"
    assert body["payment_status"] == "unpaid"
    assert Decimal(body["amount"]) == Decimal("150.00")


async def test_retried_record_expense_with_same_key_does_not_double_post(client, admin_ctx):
    key = str(uuid.uuid4())
    first = await client.post(
        "/expenses", json=_body(admin_ctx), headers={**_auth(admin_ctx["token"]), "Idempotency-Key": key}
    )
    second = await client.post(
        "/expenses",
        json=_body(admin_ctx, amount="999.00"),  # different body, same key
        headers={**_auth(admin_ctx["token"]), "Idempotency-Key": key},
    )

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["status"] == "already_executed"


async def test_non_uuid_idempotency_key_is_accepted_and_stays_idempotent(client, admin_ctx):
    """The Idempotency-Key header is client-supplied and never guaranteed to
    be a UUID (unlike Materials' CQRS path, whose idempotency_key IS a
    workflow_instance_id). The claim/replay logic and the workflow_instances
    phase-transition no-op (see PostgresExpenseExecutionRepository._transition)
    must both handle a plain non-UUID string without raising."""
    key = "order-42-not-a-uuid"
    first = await client.post(
        "/expenses",
        json=_body(admin_ctx),
        headers={**_auth(admin_ctx["token"]), "Idempotency-Key": key},
    )
    second = await client.post(
        "/expenses",
        json=_body(admin_ctx, amount="999.00"),
        headers={**_auth(admin_ctx["token"]), "Idempotency-Key": key},
    )

    assert first.status_code == 201, first.text
    assert second.status_code == 200, second.text
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["status"] == "already_executed"


async def test_missing_idempotency_key_header_is_rejected(client, admin_ctx):
    resp = await client.post("/expenses", json=_body(admin_ctx), headers=_auth(admin_ctx["token"]))
    assert resp.status_code == 422


async def test_non_positive_amount_is_rejected(client, admin_ctx):
    resp = await client.post(
        "/expenses",
        json=_body(admin_ctx, amount="0"),
        headers={**_auth(admin_ctx["token"]), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert resp.status_code == 422


async def test_write_to_inaccessible_project_is_rejected(client, test_engine, test_org, admin_ctx):
    other_project_id = await _make_project(test_engine, test_org)
    user_id = await _make_user(test_engine, test_org, "site_engineer")
    async with test_engine.begin() as conn:
        await conn.execute(
            sa.text(
                "UPDATE users SET access_policy = CAST(:policy AS jsonb) WHERE id = :id"
            ),
            {
                "id": user_id,
                "policy": f'{{"mode": "custom_projects", "projects": [{{"project_id": "{admin_ctx["project_id"]}", "site_ids": null}}]}}',
            },
        )
    token = _token(user_id, test_org, "site_engineer")

    resp = await client.post(
        "/expenses",
        json=_body(admin_ctx, project_id=str(other_project_id)),
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid.uuid4())},
    )
    assert resp.status_code == 403


async def test_cross_organization_read_is_rejected(client, test_engine, admin_ctx):
    resp = await client.post(
        "/expenses",
        json=_body(admin_ctx),
        headers={**_auth(admin_ctx["token"]), "Idempotency-Key": str(uuid.uuid4())},
    )
    expense_id = resp.json()["id"]

    other_org_id = uuid.uuid4()
    async with test_engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO organizations (id, name, deployment_type, db_route, status, "
                "created_at, updated_at) VALUES (:id, 'Other Org', 'local', 'default', 'active', now(), now())"
            ),
            {"id": other_org_id},
        )
    other_user_id = await _make_user(test_engine, other_org_id, "admin")
    other_token = _token(other_user_id, other_org_id, "admin")

    resp = await client.get(f"/expenses/{expense_id}", headers=_auth(other_token))
    assert resp.status_code == 404


async def test_the_list_names_the_vendor_project_site_and_number(client, admin_ctx):
    """WEB-51: the Expenses page showed "Direct Payee" / "Org Wide" for every row because the list did not carry them."""
    resp = await client.post(
        "/expenses",
        json={**_body(admin_ctx), "vendor_text": "KMS Agencies"},
        headers={**_auth(admin_ctx["token"]), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert resp.status_code == 201, resp.text
    rows = (await client.get("/expenses", headers=_auth(admin_ctx["token"]))).json()
    row = next(r for r in rows if r["id"] == resp.json()["id"])
    assert row["vendor_name"] == "KMS Agencies" and row["vendor_id"]
    assert row["project_name"] and row["expense_number"]


# WEB-65 (Ilan, 5 Nov: "make sure sent expense bill and all is there saved for an expense"): a bill is added to a
# saved expense, from the dashboard (a file) or from WhatsApp (a photo that came after the save).
_JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64


@pytest.fixture
def storage(client):
    from mesiri.infrastructure.objectstorage.dependency import get_object_storage
    from mesiri.infrastructure.objectstorage.fake import FakeObjectStorage

    class Store(FakeObjectStorage):
        async def generate_presigned_url(self, key, *, expires_in_seconds=900, method="GET"):
            return f"https://files.test/{key}"

    store = Store()
    client._transport.app.dependency_overrides[get_object_storage] = lambda: store
    return store


async def _expense(client, ctx) -> str:
    resp = await client.post(
        "/expenses", json=_body(ctx), headers={**_auth(ctx["token"]), "Idempotency-Key": str(uuid.uuid4())}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _inbound_photo(test_engine, org_id, key: str) -> None:
    async with test_engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO inbound_messages (id, correlation_id, sender_wa_id, message_type, raw_payload, "
                "normalized_message, dedup_key, raw_payload_captured, processing_status, organization_id, "
                "received_at, media_object_key) VALUES (:id, :c, '15555550199', 'image', '{}', '{}', :d, true, "
                "'completed', :org, now(), :key)"
            ),
            {"id": uuid.uuid4(), "c": f"c-{uuid.uuid4().hex}", "d": f"d-{uuid.uuid4().hex}", "org": org_id, "key": key},
        )


async def test_a_bill_file_from_the_dashboard_is_kept_and_listed(client, test_org, admin_ctx, storage):
    import base64

    expense_id = await _expense(client, admin_ctx)
    resp = await client.post(
        f"/expenses/{expense_id}/attachments",
        json={"data_base64": base64.b64encode(_JPEG).decode(), "content_type": "image/jpeg"},
        headers=_auth(admin_ctx["token"]),
    )
    assert resp.status_code == 201, resp.text
    assert len(resp.json()) == 1 and resp.json()[0]["attachment_type"] == "receipt"
    listed = (await client.get(f"/expenses/{expense_id}/attachments", headers=_auth(admin_ctx["token"]))).json()
    assert len(listed) == 1
    gallery = (await client.get("/expenses/attachments", headers=_auth(admin_ctx["token"]))).json()
    assert any(g["expense_id"] == expense_id for g in gallery)
    (key,) = list(storage._store)
    assert key.startswith(f"org/{test_org}/expenses/{expense_id}/bill-") and storage._store[key][1] == "image/jpeg"


async def test_a_file_that_is_not_a_bill_is_refused(client, admin_ctx, storage):
    import base64

    expense_id = await _expense(client, admin_ctx)
    for body in (
        {"data_base64": base64.b64encode(b"<svg/>").decode(), "content_type": "image/svg+xml"},
        {"data_base64": base64.b64encode(b"not a jpeg").decode(), "content_type": "image/jpeg"},
        {"data_base64": base64.b64encode(b"\xff\xd8\xff" + b"0" * (701 * 1024)).decode(), "content_type": "image/jpeg"},
        {},
    ):
        resp = await client.post(f"/expenses/{expense_id}/attachments", json=body, headers=_auth(admin_ctx["token"]))
        assert resp.status_code == 422, resp.text
    listed = (await client.get(f"/expenses/{expense_id}/attachments", headers=_auth(admin_ctx["token"]))).json()
    assert listed == []


async def test_a_whatsapp_photo_after_the_save_is_added_once(client, test_engine, test_org, admin_ctx, storage):
    expense_id = await _expense(client, admin_ctx)
    key = f"org/{test_org}/whatsapp/bill-{uuid.uuid4().hex}.jpg"
    await _inbound_photo(test_engine, test_org, key)
    for _ in range(2):
        resp = await client.post(
            f"/expenses/{expense_id}/attachments", json={"media_object_key": key}, headers=_auth(admin_ctx["token"])
        )
        assert resp.status_code == 201, resp.text
    assert len(resp.json()) == 1


async def test_another_companys_photo_is_never_attached(client, test_engine, admin_ctx, storage):
    expense_id = await _expense(client, admin_ctx)
    resp = await client.post(
        f"/expenses/{expense_id}/attachments",
        json={"media_object_key": f"org/{uuid.uuid4()}/whatsapp/x.jpg"},
        headers=_auth(admin_ctx["token"]),
    )
    assert resp.status_code == 404


async def test_a_bill_needs_access_to_the_expenses_project(client, test_engine, test_org, admin_ctx, storage):
    import base64

    expense_id = await _expense(client, admin_ctx)
    other_project = await _make_project(test_engine, test_org)
    user_id = await _make_user(test_engine, test_org, "site_engineer")
    async with test_engine.begin() as conn:
        await conn.execute(
            sa.text("UPDATE users SET access_policy = CAST(:policy AS jsonb) WHERE id = :id"),
            {"id": user_id,
             "policy": f'{{"mode": "custom_projects", "projects": [{{"project_id": "{other_project}", "site_ids": null}}]}}'},
        )
    resp = await client.post(
        f"/expenses/{expense_id}/attachments",
        json={"data_base64": base64.b64encode(_JPEG).decode(), "content_type": "image/jpeg"},
        headers=_auth(_token(user_id, test_org, "site_engineer")),
    )
    assert resp.status_code == 403


# PRC-18 (decision D3): every expense says how it was paid, from the account it was paid from; the list honours the
# supplier and the dates (the supplier sheet asked for one supplier's expenses and got every expense).
async def _account(test_engine, org_id, user_id, account_type: str, name: str) -> uuid.UUID:
    account_id = uuid.uuid4()
    async with test_engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO money_accounts (id, organization_id, account_type, name, currency, opening_balance, "
                "opening_balance_date, status, created_by) VALUES (:id, :org, :type, :name, 'INR', 100000, "
                "CURRENT_DATE - 60, 'active', :user)"
            ),
            {"id": account_id, "org": org_id, "type": account_type, "name": name, "user": user_id},
        )
    return account_id


async def test_each_expense_says_how_it_was_paid(client, test_engine, test_org, admin_ctx):
    h = {**_auth(admin_ctx["token"])}
    box = await _account(test_engine, test_org, admin_ctx["user_id"], "cash", "Villa petty cash")
    bank = await _account(test_engine, test_org, admin_ctx["user_id"], "bank", "SBI current")

    async def record(**extra) -> str:
        resp = await client.post("/expenses", json={**_body(admin_ctx), **extra},
                                 headers={**h, "Idempotency-Key": str(uuid.uuid4())})
        assert resp.status_code == 201, resp.text
        return resp.json()["id"]

    petty = await record(account_id=str(box), vendor_text="Tea stall")
    direct = await record(account_id=str(bank), vendor_text="Malabar Hardware", amount="12000.00")
    unpaid = await record(vendor_text="Malabar Hardware")
    own = await record(occurred_date=(company_today() - datetime.timedelta(days=40)).isoformat())
    async with test_engine.begin() as conn:  # "paid from my pocket" (the WhatsApp path's paid_from_own_pocket)
        await conn.execute(sa.text("UPDATE expenses SET payment_status = 'reimbursable' WHERE id = :id"), {"id": own})

    rows = {r["id"]: r for r in (await client.get("/expenses", headers=h)).json()}
    assert (rows[petty]["paid_via"], rows[petty]["account_name"], rows[petty]["account_type"]) == ("petty_cash", "Villa petty cash", "cash")
    assert (rows[direct]["paid_via"], rows[direct]["account_name"], rows[direct]["paid_amount"]) == ("direct", "SBI current", "12000.00")
    assert (rows[unpaid]["paid_via"], rows[unpaid]["account_name"]) == ("unpaid", None)
    assert rows[own]["paid_via"] == "own_pocket" and rows[own]["created_by_name"] == "Test User"
    assert rows[petty]["category_name"] == "materials"

    one = (await client.get(f"/expenses/{direct}", headers=h)).json()
    assert (one["paid_via"], one["account_type"]) == ("direct", "bank")

    # One supplier's expenses only; the dates bound the list.
    vendor_id = rows[direct]["vendor_id"]
    mine = (await client.get("/expenses", params={"vendor_id": vendor_id}, headers=h)).json()
    assert {r["id"] for r in mine} == {direct, unpaid}
    recent = (await client.get("/expenses", params={"date_from": (company_today() - datetime.timedelta(days=30)).isoformat()}, headers=h)).json()
    assert own not in {r["id"] for r in recent} and petty in {r["id"] for r in recent}


def test_paid_via_rule():
    from decimal import Decimal

    from mesiri.domains.expenses.paid_via import paid_via

    assert paid_via("paid", {"employee_advance": Decimal("300")}) == "petty_cash"
    assert paid_via("paid", {"cash": Decimal("100"), "bank": Decimal("900")}) == "direct"  # the larger part
    assert paid_via("partially_paid", {"other": Decimal("50")}) == "direct"
    assert paid_via("reimbursable", None) == "own_pocket"
    assert paid_via("unpaid", {}) == "unpaid"


# PRC-35 + SEC-03 (approved in session by the owner, 7 Nov 2026): an expense is paid, in part or in full, or the
# person who paid from their pocket is repaid, from an account; only the money roles may; a payment can be undone.
async def test_pay_an_expense_in_parts_undo_and_who_may(client, test_engine, test_org, admin_ctx):
    h = _auth(admin_ctx["token"])
    bank = await _account(test_engine, test_org, admin_ctx["user_id"], "bank", "SBI current")
    box = await _account(test_engine, test_org, admin_ctx["user_id"], "cash", "Villa petty cash")
    resp = await client.post("/expenses", json={**_body(admin_ctx), "amount": "1000.00"},
                             headers={**h, "Idempotency-Key": str(uuid.uuid4())})
    eid = resp.json()["id"]

    pm_id = await _make_user(test_engine, test_org, "project_manager")
    pm = _auth(_token(pm_id, test_org, "project_manager"))
    refused = await client.post(f"/expenses/{eid}/payments", json={"account_id": str(bank)}, headers=pm)
    assert refused.status_code == 403
    assert (await client.post("/finance/accounts", json={"name": "PM box", "account_type": "cash"}, headers=pm)).status_code == 403

    part = await client.post(f"/expenses/{eid}/payments", json={"account_id": str(box), "amount": "400"}, headers=h)
    assert part.status_code == 201, part.text
    assert (part.json()["paid"], part.json()["left"], part.json()["payment_status"]) == ("400.00", "600.00", "partially_paid")
    too_much = await client.post(f"/expenses/{eid}/payments", json={"account_id": str(bank), "amount": "700"}, headers=h)
    assert too_much.status_code == 422 and "600" in too_much.text
    rest = await client.post(f"/expenses/{eid}/payments", json={"account_id": str(bank)}, headers=h)  # what is left
    assert rest.json()["payment_status"] == "paid" and rest.json()["left"] == "0.00"
    assert (await client.post(f"/expenses/{eid}/payments", json={"account_id": str(bank)}, headers=h)).status_code == 409

    row = next(r for r in (await client.get("/expenses", headers=h)).json() if r["id"] == eid)
    assert (row["paid_via"], row["account_name"], row["paid_amount"]) == ("direct", "SBI current", "1000.00")  # the larger part
    one = (await client.get(f"/expenses/{eid}", headers=h)).json()
    assert one["account_name"] == "SBI current"  # was never found by the old ledger lookup

    # The Money page's transaction says which expense it paid.
    txs = (await client.get("/finance/transactions", headers=h)).json()
    assert {t["expense_id"] for t in txs if t["transaction_type"] == "expense_payment"} == {eid}

    undone = await client.post(f"/expenses/{eid}/payments/{rest.json()['payment_id']}/reverse", headers=h)
    assert undone.status_code == 200 and undone.json()["payment_status"] == "partially_paid"
    assert undone.json()["left"] == "600.00"


async def test_repay_someone_who_paid_from_their_pocket(client, test_engine, test_org, admin_ctx):
    h = _auth(admin_ctx["token"])
    box = await _account(test_engine, test_org, admin_ctx["user_id"], "cash", "Villa petty cash")
    eid = (await client.post("/expenses", json={**_body(admin_ctx), "amount": "250.00"},
                             headers={**h, "Idempotency-Key": str(uuid.uuid4())})).json()["id"]
    async with test_engine.begin() as conn:
        await conn.execute(sa.text("UPDATE expenses SET payment_status = 'reimbursable' WHERE id = :id"), {"id": eid})
    paid = await client.post(f"/expenses/{eid}/payments", json={"account_id": str(box)}, headers=h)
    assert paid.status_code == 201 and paid.json()["payment_status"] == "paid"
    row = next(r for r in (await client.get("/expenses", headers=h)).json() if r["id"] == eid)
    assert row["paid_via"] == "petty_cash"


# Petty cash running low is said on WhatsApp (approved in session by the owner, 7 Nov 2026): money leaving a cash box
# that ends under the company's line queues one note a day per person (holder + owner/admin/finance); a bank never.
async def test_a_cash_box_going_under_the_line_queues_one_note_per_person(client, test_engine, test_org, admin_ctx):
    h = _auth(admin_ctx["token"])
    box = await _account(test_engine, test_org, admin_ctx["user_id"], "cash", "Villa petty cash")  # opening 1,00,000
    bank = await _account(test_engine, test_org, admin_ctx["user_id"], "bank", "SBI current")
    finance_id = await _make_user(test_engine, test_org, "finance")
    await _make_user(test_engine, test_org, "site_engineer")  # not told

    async def spend(amount: str, account) -> None:
        r = await client.post("/expenses", json={**_body(admin_ctx), "amount": amount, "account_id": str(account)},
                              headers={**h, "Idempotency-Key": str(uuid.uuid4())})
        assert r.status_code == 201, r.text

    async def notes() -> list:
        async with test_engine.begin() as conn:
            return (await conn.execute(sa.text(
                "SELECT recipient_user_id, payload->>'message' AS m FROM notifications WHERE rule_key = 'petty_cash_low'"))).all()

    await spend("40000.00", box)  # 60,000 left: above the line
    assert await notes() == []
    await spend("90000.00", bank)
    assert await notes() == []
    await spend("15000.00", box)  # 45,000 left
    rows = await notes()
    assert {r.recipient_user_id for r in rows} == {admin_ctx["user_id"], finance_id}
    assert "Villa petty cash is low on cash: ₹45,000 left, below ₹50,000" in rows[0].m
    await spend("1000.00", box)  # again the same day: no second note
    assert len(await notes()) == 2
