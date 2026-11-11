"""ACC-19: the Tally XML from posted journal entries -- one voucher per entry of its own type, lines netted per ledger,
masters under Tally's reserved groups (a company's own group created under its parent), the party named."""

from __future__ import annotations

import datetime
import xml.etree.ElementTree as ET
from decimal import Decimal

import pytest

from mesiri.domains.finance.tally import TALLY_TYPES, from_books

G = {"bank": "g1", "creditors": "g2", "expenses": "g3", "mine": "g4", "suspense": "g5"}
GROUPS = [
    {"id": G["bank"], "code": "bank_accounts", "name": "Banks (renamed)", "parent_id": None},
    {"id": G["creditors"], "code": "sundry_creditors", "name": "Sundry Creditors", "parent_id": None},
    {"id": G["expenses"], "code": "indirect_expenses", "name": "Indirect Expenses", "parent_id": None},
    {"id": G["mine"], "code": None, "name": "Site overheads", "parent_id": G["expenses"]},
    {"id": G["suspense"], "code": "suspense", "name": "Suspense A/c", "parent_id": None},
]
LEDGERS = [{"id": "l-bank", "group_id": G["bank"]}, {"id": "l-mal", "group_id": G["creditors"]},
           {"id": "l-tea", "group_id": G["mine"]}, {"id": "l-cash", "group_id": G["bank"]}]


def _ln(lid, name, dr="0", cr="0", link=None):
    return {"ledger_id": lid, "ledger": name, "debit": dr, "credit": cr, "link_kind": link}


def _e(kind, *lines, manual=False, late=False, n=1):
    return {"id": f"e-{kind}-{n}", "voucher_type": kind, "date": datetime.date(2026, 10, 5), "ref": f"{kind[:3].upper()}/2026-27/{n}",
            "narration": f"{kind} words", "after_close": late, "manual": manual, "lines": list(lines)}


@pytest.mark.parametrize("kind", list(TALLY_TYPES))
def test_each_voucher_type_is_its_tally_type_and_balances(kind):
    xml, counts = from_books("Co", GROUPS, LEDGERS, [_e(kind, _ln("l-tea", "Tea", "100"), _ln("l-bank", "SBI", cr="100"))])
    v = ET.fromstring(xml).find(".//VOUCHER")
    assert (v.get("VCHTYPE"), v.findtext("VOUCHERNUMBER"), v.findtext("NARRATION")) == (
        TALLY_TYPES[kind], f"{kind[:3].upper()}/2026-27/1", f"{kind} words")
    assert sum(Decimal(x.findtext("AMOUNT")) for x in v.findall("ALLLEDGERENTRIES.LIST")) == 0
    assert counts["vouchers"] == 1 and counts["source"] == "books"


def test_lines_of_one_ledger_are_netted_and_the_party_is_named():
    xml, _ = from_books("Co", GROUPS, LEDGERS, [_e("payment", _ln("l-mal", "Malabar", "60", link="vendor"),
                                                   _ln("l-mal", "Malabar", "40", link="vendor"), _ln("l-bank", "SBI", cr="100"))])
    v = ET.fromstring(xml).find(".//VOUCHER")
    assert [(x.findtext("LEDGERNAME"), x.findtext("AMOUNT")) for x in v.findall("ALLLEDGERENTRIES.LIST")] == [
        ("Malabar", "-100.00"), ("SBI", "100.00")]
    assert v.findtext("PARTYLEDGERNAME") == "Malabar"


def test_masters_use_reserved_groups_and_create_the_companys_own():
    xml, counts = from_books("Co", GROUPS, LEDGERS, [_e("journal", _ln("l-tea", "Tea", "100"), _ln("l-cash", "Cash", cr="100"),
                                                        manual=True, late=True)])
    root = ET.fromstring(xml)
    assert {g.get("NAME"): g.findtext("PARENT") for g in root.iter("GROUP")} == {"Site overheads": "Indirect Expenses"}
    assert {x.get("NAME"): x.findtext("PARENT") for x in root.iter("LEDGER")} == {
        "Tea": "Site overheads", "Cash": "Bank Accounts"}  # the renamed group exports as Tally's own
    assert "changed after its month was closed" in root.findtext(".//NARRATION")
    assert (counts["manual"], counts["after_close"], counts["groups"]) == (1, 1, 1)
