"""ACC-12 contract: manual vouchers through the real routes, on a real Postgres (run with `pytest -m integration`).

A Journal (bank charges) and a Contra (cash deposited in the bank) reach the trial balance and the ledger statement;
an unbalanced voucher, a Contra on another ledger and a voucher in a closed month are refused; a voucher of a closed
month is reversed on the first open day, flagged; the sweep re-posting everything leaves manual vouchers alone;
another company never sees them; a project manager and a site engineer get 403. Fixtures and the month of records are
the accounts contract's.
"""

from __future__ import annotations

import datetime
import uuid

import pytest

from contract import test_accounts_contract as books
from contract.test_accounts_contract import _company, _row, _run, _user

pytestmark = pytest.mark.integration

test_engine, client = books.test_engine, books.client


async def _ledgers(client, h) -> dict[str, dict]:
    r = await client.get("/accounts/vouchers/ledgers", headers=h)
    assert r.status_code == 200, r.text
    return {x["name"]: x for x in r.json()["ledgers"]}


def _voucher(day, kind, narration, *lines):
    return {"date": str(day), "voucher_type": kind, "narration": narration,
            "lines": [{"ledger_id": led, "debit": dr, "credit": cr} for led, dr, cr in lines]}


async def test_journal_and_contra_reach_the_books_and_the_wrong_ones_are_refused(client, test_engine):
    ids = await _company(test_engine)
    h = {"Authorization": f"Bearer {ids['admin']}"}
    try:
        led = await _ledgers(client, h)
        bank, petty, charges = led["SBI current"]["id"], led["Block A petty cash"]["id"], led["Bank charges"]["id"]
        assert led["SBI current"]["contra"] and not led["Bank charges"]["contra"]
        day = ids["day"]
        j = await client.post("/accounts/vouchers", headers=h, json=_voucher(
            day, "journal", "SBI charges, October", (charges, "354.00", "0"), (bank, "0", "354.00")))
        assert j.status_code == 201, j.text
        j = j.json()
        assert (j["voucher_type"], j["manual"], j["amount"], j["created_by_name"]) == ("journal", True, "354.00", "Ravi")
        c = await client.post("/accounts/vouchers", headers=h, json=_voucher(
            day, "contra", "Cash deposited in SBI", (bank, "1500", "0"), (petty, "0", "1500")))
        assert c.status_code == 201, c.text
        assert c.json()["ref"].startswith("CON/") and c.json()["number"] == 2  # the sweep's transfer is CON 1

        tb = (await client.get(f"/accounts/trial-balance?date_from={ids['month']}", headers=h)).json()
        assert tb["totals"]["balanced"] is True
        assert _row(tb, "Bank charges")["closing"] == "354.00"
        # Bank: 1,60,000 from the records (no client receipt here: 1,10,000) − 354 + 1,500.
        assert _row(tb, "SBI current")["closing"] == "111146.00"
        assert _row(tb, "Block A petty cash")["closing"] == "1500.00"
        st = (await client.get(f"/accounts/ledgers/{charges}/statement?date_from={ids['month']}", headers=h)).json()
        assert [ln["narration"] for ln in st["lines"]] == ["SBI charges, October"] and st["closing"] == "354.00"

        bad = await client.post("/accounts/vouchers", headers=h, json=_voucher(
            day, "journal", "Typo", (charges, "100", "0"), (bank, "0", "90")))
        assert bad.status_code == 422 and "differ by 10" in bad.json()["detail"]
        wrong = await client.post("/accounts/vouchers", headers=h, json=_voucher(
            day, "contra", "Not money", (charges, "100", "0"), (bank, "0", "100")))
        assert wrong.status_code == 422 and "cash and bank only" in wrong.json()["detail"]
        both = await client.post("/accounts/vouchers", headers=h, json=_voucher(
            day, "journal", "Both sides", (charges, "100", "100"), (bank, "0", "0")))
        assert both.status_code == 422

        for role in ("PROJECT_MANAGER", "SITE_ENGINEER"):
            _, tok = await _user(test_engine, ids["org"], role)
            o = {"Authorization": f"Bearer {tok}"}
            assert (await client.post("/accounts/vouchers", headers=o, json=_voucher(
                day, "journal", "No", (charges, "1", "0"), (bank, "0", "1")))).status_code == 403
            assert (await client.post(f"/accounts/entries/{j['id']}/reverse", headers=o,
                                      json={"reason": "not allowed"})).status_code == 403
        other = uuid.uuid4()
        await _run(test_engine, "INSERT INTO organizations (id, name, deployment_type, db_route, status, created_at, "
                   "updated_at) VALUES (:id, 'Other', 'local', 'default', 'active', now(), now())", id=other)
        try:
            _, stranger = await _user(test_engine, other, "admin")
            s = {"Authorization": f"Bearer {stranger}"}
            assert (await client.get(f"/accounts/entries/{j['id']}", headers=s)).status_code == 404
            assert (await client.post(f"/accounts/entries/{j['id']}/reverse", headers=s,
                                      json={"reason": "not mine"})).status_code == 404
            theirs = await client.post("/accounts/vouchers", headers=s, json=_voucher(
                day, "journal", "Using another company's ledgers", (charges, "1", "0"), (bank, "0", "1")))
            assert theirs.status_code == 422 and "not in this company's chart" in theirs.json()["detail"]
        finally:
            await _run(test_engine, "DELETE FROM organizations WHERE id = :id", id=other)
    finally:
        await _run(test_engine, "DELETE FROM organizations WHERE id = :id", id=ids["org"])


async def test_closed_month_refuses_vouchers_and_a_reversal_lands_on_the_first_open_day(client, test_engine):
    ids = await _company(test_engine)
    h = {"Authorization": f"Bearer {ids['admin']}"}
    try:
        led = await _ledgers(client, h)
        bank, charges = led["SBI current"]["id"], led["Bank charges"]["id"]
        j = (await client.post("/accounts/vouchers", headers=h, json=_voucher(
            ids["day"], "journal", "Charges", (charges, "500", "0"), (bank, "0", "500")))).json()
        month = ids["month"].strftime("%Y-%m")
        assert (await client.post(f"/accounts/periods/{month}/close", headers=h)).status_code == 200
        refused = await client.post("/accounts/vouchers", headers=h, json=_voucher(
            ids["day"], "journal", "Late", (charges, "1", "0"), (bank, "0", "1")))
        assert refused.status_code == 409
        assert f"{ids['month']:%B %Y} is closed" in refused.json()["detail"] and "reopen" in refused.json()["detail"]

        rev = await client.post(f"/accounts/entries/{j['id']}/reverse", headers=h, json={"reason": "Charged twice"})
        assert rev.status_code == 201, rev.text
        rev = rev.json()
        next_month = (ids["month"].replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
        assert (rev["date"], rev["after_close"], rev["reverses_id"], rev["reversal_reason"]) == (
            str(next_month), True, j["id"], "Charged twice")
        assert [(ln["ledger"], ln["debit"], ln["credit"]) for ln in rev["lines"]] == [
            ("Bank charges", "0.00", "500.00"), ("SBI current", "500.00", "0.00")]
        assert (await client.get(f"/accounts/entries/{j['id']}", headers=h)).json()["reversed_by_id"] == rev["id"]
        again = await client.post(f"/accounts/entries/{j['id']}/reverse", headers=h, json={"reason": "again"})
        assert again.status_code == 409
        swept = (await client.get(f"/accounts/day-book?date_from={ids['month']}&voucher_type=purchase", headers=h)).json()
        not_manual = swept["entries"][0]["id"]
        assert (await client.post(f"/accounts/entries/{not_manual}/reverse", headers=h,
                                  json={"reason": "not allowed"})).status_code == 409

        _, fin = await _user(test_engine, ids["org"], "FINANCE")
        assert (await client.post(f"/accounts/entries/{rev['id']}/correct", headers={"Authorization": f"Bearer {fin}"},
                                  json={"reason": "Finance tries", "voucher": _voucher(next_month, "journal", "x",
                                        (charges, "1", "0"), (bank, "0", "1"))})).status_code == 403
    finally:
        await _run(test_engine, "DELETE FROM organizations WHERE id = :id", id=ids["org"])


async def test_correct_reverses_and_posts_in_one_step(client, test_engine):
    ids = await _company(test_engine)
    h = {"Authorization": f"Bearer {ids['admin']}"}
    try:
        led = await _ledgers(client, h)
        bank, charges = led["SBI current"]["id"], led["Bank charges"]["id"]
        j = (await client.post("/accounts/vouchers", headers=h, json=_voucher(
            ids["day"], "journal", "Charges", (charges, "500", "0"), (bank, "0", "500")))).json()
        fixed = await client.post(f"/accounts/entries/{j['id']}/correct", headers=h, json={
            "reason": "Was 50", "voucher": _voucher(ids["day"], "journal", "Charges", (charges, "50", "0"), (bank, "0", "50"))})
        assert fixed.status_code == 201, fixed.text
        tb = (await client.get(f"/accounts/trial-balance?date_from={ids['month']}", headers=h)).json()
        assert _row(tb, "Bank charges")["closing"] == "50.00"
    finally:
        await _run(test_engine, "DELETE FROM organizations WHERE id = :id", id=ids["org"])


async def test_the_sweep_reposting_everything_leaves_manual_vouchers_alone(client, test_engine, monkeypatch):
    ids = await _company(test_engine)
    h = {"Authorization": f"Bearer {ids['admin']}"}
    try:
        led = await _ledgers(client, h)
        bank, diff = led["SBI current"]["id"], led["Opening balance difference"]["id"]
        j = (await client.post("/accounts/vouchers", headers=h, json=_voucher(
            ids["month"], "journal", "Opening balance", (bank, "2500", "0"), (diff, "0", "2500")))).json()
        before = (await client.get(f"/accounts/entries/{j['id']}", headers=h)).json()
        # A rule change re-posts every record (§14: the derived journals are rebuilt from the records).
        monkeypatch.setattr("mesiri.domains.accounts.posting.RULES_VERSION", "test-repost")
        done = (await client.post("/accounts/post", headers=h)).json()
        assert done["reposted"] > 0
        after = (await client.get(f"/accounts/entries/{j['id']}", headers=h)).json()
        assert {k: after[k] for k in ("id", "number", "date", "narration", "lines")} == {
            k: before[k] for k in ("id", "number", "date", "narration", "lines")}
    finally:
        await _run(test_engine, "DELETE FROM organizations WHERE id = :id", id=ids["org"])
