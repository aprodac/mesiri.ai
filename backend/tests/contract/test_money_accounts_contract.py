"""WEB-66 (Ilan, 5 Nov 2026: "what about bank accounts page", "bank account connecting it to a user"): a money account
keeps its bank details and the person who holds it, and both can be changed.

Before: the create dialog sent the account number, bank and IFSC and the API dropped them; the holder could be set
only on create; the holder's name was read without checking the company. Run with `pytest -m integration`.
"""

# ruff: noqa: F811 -- pytest fixtures shared with the expense contract tests are imported and then used by name
from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from contract.test_expenses_api_contract import (  # noqa: F401 -- fixtures
    _auth,
    _make_user,
    _token,
    client,
    test_engine,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def clean_db(test_engine: AsyncEngine):
    async with test_engine.begin() as conn:
        for table in ("money_transactions", "money_accounts", "expense_payments", "expense_attachments", "expenses",
                      "vendors", "expense_categories", "sites", "projects", "users", "organizations"):
            await conn.execute(sa.text(f"DELETE FROM {table}"))
    yield


async def _org(test_engine) -> uuid.UUID:
    org_id = uuid.uuid4()
    async with test_engine.begin() as conn:
        await conn.execute(
            sa.text("INSERT INTO organizations (id, name, deployment_type, db_route, status, created_at, updated_at) "
                    "VALUES (:id, 'Org', 'local', 'default', 'active', now(), now())"),
            {"id": org_id},
        )
    return org_id


@pytest.fixture
async def ctx(test_engine, clean_db):
    org = await _org(test_engine)
    admin = await _make_user(test_engine, org, "admin")
    holder = await _make_user(test_engine, org, "site_engineer")
    async with test_engine.begin() as conn:
        await conn.execute(sa.text("UPDATE users SET full_name = 'Ravi Kumar' WHERE id = :id"), {"id": holder})
    return {"org": org, "admin": admin, "holder": holder, "h": _auth(_token(admin, org, "admin"))}


async def test_a_bank_account_keeps_its_bank_ifsc_last_4_and_holder(client, ctx):
    resp = await client.post("/finance/accounts", headers=ctx["h"], json={
        "name": "HDFC current", "account_type": "bank", "opening_balance": 100000,
        "bank_name": " HDFC  Bank ", "ifsc_code": "hdfc0001234", "account_number": "50100 123456 7890",
        "owner_user_id": str(ctx["holder"])})
    assert resp.status_code == 201, resp.text
    acc = resp.json()
    assert (acc["bank_name"], acc["ifsc_code"], acc["account_last4"]) == ("HDFC Bank", "HDFC0001234", "7890")
    assert acc["owner_user_id"] == str(ctx["holder"]) and acc["custodian_name"] == "Ravi Kumar"
    listed = next(a for a in (await client.get("/finance/accounts", headers=ctx["h"])).json() if a["id"] == acc["id"])
    assert listed["account_last4"] == "7890" and listed["custodian_name"] == "Ravi Kumar"
    one = (await client.get(f"/finance/accounts/{acc['id']}", headers=ctx["h"])).json()
    assert one["custodian_name"] == "Ravi Kumar" and one["bank_name"] == "HDFC Bank"


async def test_the_full_account_number_is_never_stored(client, test_engine, ctx):
    resp = await client.post("/finance/accounts", headers=ctx["h"], json={
        "name": "SBI", "account_type": "bank", "opening_balance": 0, "account_number": "123456789012"})
    async with test_engine.begin() as conn:
        row = (await conn.execute(sa.text("SELECT * FROM money_accounts WHERE id = :id"),
                                  {"id": resp.json()["id"]})).mappings().one()
    assert "123456789012" not in str(dict(row)) and row["account_number_last4"] == "9012"


async def test_holder_and_bank_details_change_and_clear(client, ctx):
    acc = (await client.post("/finance/accounts", headers=ctx["h"], json={
        "name": "Site cash", "account_type": "cash", "opening_balance": 5000})).json()
    resp = await client.patch(f"/finance/accounts/{acc['id']}", headers=ctx["h"], json={
        "owner_user_id": str(ctx["holder"]), "bank_name": "Canara", "account_last4": "4321"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["custodian_name"] == "Ravi Kumar" and resp.json()["name"] == "Site cash"
    resp = await client.patch(f"/finance/accounts/{acc['id']}", headers=ctx["h"], json={
        "owner_user_id": None, "bank_name": "", "name": "Block A cash"})
    body = resp.json()
    assert (body["owner_user_id"], body["custodian_name"], body["bank_name"]) == (None, None, None)
    assert body["name"] == "Block A cash" and body["account_last4"] == "4321"  # not sent: kept


async def test_rename_alone_still_works(client, ctx):
    acc = (await client.post("/finance/accounts", headers=ctx["h"], json={
        "name": "Old", "account_type": "bank", "opening_balance": 0, "bank_name": "ICICI"})).json()
    resp = await client.patch(f"/finance/accounts/{acc['id']}", headers=ctx["h"], json={"name": "New"})
    assert resp.json()["name"] == "New" and resp.json()["bank_name"] == "ICICI"


@pytest.mark.parametrize("bad", [{"ifsc_code": "HDFC1234"}, {"account_number": "12"}, {"bank_name": "x" * 81}])
async def test_bad_bank_details_are_refused_with_a_reason(client, ctx, bad):
    resp = await client.post("/finance/accounts", headers=ctx["h"], json={
        "name": "X", "account_type": "bank", "opening_balance": 0, **bad})
    assert resp.status_code == 422 and isinstance(resp.json()["detail"], str)


async def test_a_person_of_another_company_never_holds_an_account(client, test_engine, ctx):
    other_org = await _org(test_engine)
    stranger = await _make_user(test_engine, other_org, "admin")
    resp = await client.post("/finance/accounts", headers=ctx["h"], json={
        "name": "X", "account_type": "bank", "opening_balance": 0, "owner_user_id": str(stranger)})
    assert resp.status_code == 422
    acc = (await client.post("/finance/accounts", headers=ctx["h"], json={
        "name": "Y", "account_type": "bank", "opening_balance": 0})).json()
    resp = await client.patch(f"/finance/accounts/{acc['id']}", headers=ctx["h"], json={"owner_user_id": str(stranger)})
    assert resp.status_code == 422


async def test_an_inactive_person_cannot_be_made_the_holder(client, test_engine, ctx):
    async with test_engine.begin() as conn:
        await conn.execute(sa.text("UPDATE users SET status = 'inactive' WHERE id = :id"), {"id": ctx["holder"]})
    resp = await client.post("/finance/accounts", headers=ctx["h"], json={
        "name": "X", "account_type": "cash", "opening_balance": 0, "owner_user_id": str(ctx["holder"])})
    assert resp.status_code == 422
