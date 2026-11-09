"""ACC-06/08/23: P&L, balance sheet and overhead sharing, pure (domains/accounts/statements.py, posting.py)."""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from mesiri.domains.accounts import posting
from mesiri.domains.accounts.statements import bs_layout, pl_layout

G = {k: uuid.uuid4() for k in ("capital", "current_liabilities", "sundry_creditors", "current_assets", "bank_accounts",
                                "sales", "direct_expenses", "indirect_expenses", "indirect_income")}
NATURE = {"capital": "equity", "current_liabilities": "liability", "sundry_creditors": "liability",
          "current_assets": "asset", "bank_accounts": "asset", "sales": "income", "direct_expenses": "expense",
          "indirect_expenses": "expense", "indirect_income": "income"}
PARENT = {"sundry_creditors": "current_liabilities", "bank_accounts": "current_assets"}
GROUPS = [{"id": G[k], "parent_id": G.get(PARENT.get(k)) if k in PARENT else None, "name": k.replace("_", " ").title(),
           "nature": NATURE[k], "code": k, "sort": i} for i, k in enumerate(G)]
L = {k: uuid.uuid4() for k in ("capital", "vendor", "bank", "revenue", "cement", "rent", "interest", "overheads")}
LEDGERS = {
    L["capital"]: {"name": "Capital", "group_id": G["capital"], "nature": "equity", "code": None},
    L["vendor"]: {"name": "Malabar", "group_id": G["sundry_creditors"], "nature": "liability", "code": None},
    L["bank"]: {"name": "SBI", "group_id": G["bank_accounts"], "nature": "asset", "code": None},
    L["revenue"]: {"name": "Contract revenue", "group_id": G["sales"], "nature": "income", "code": "contract_revenue"},
    L["cement"]: {"name": "Cement", "group_id": G["direct_expenses"], "nature": "expense", "code": None},
    L["rent"]: {"name": "Office rent", "group_id": G["indirect_expenses"], "nature": "expense", "code": None},
    L["interest"]: {"name": "Interest", "group_id": G["indirect_income"], "nature": "income", "code": None},
    L["overheads"]: {"name": "Overheads allocated", "group_id": G["indirect_expenses"], "nature": "expense",
                     "code": "overheads_allocated"},
}
D = Decimal


def test_pl_gross_then_net_profit_with_margins_and_a_comparison():
    sums = {L["revenue"]: D(-100000), L["cement"]: D(60000), L["rent"]: D(10000), L["interest"]: D(-500)}
    out = pl_layout(sums, LEDGERS, GROUPS, prior={L["revenue"]: D(-50000), L["cement"]: D(45000)})
    t = out["totals"]
    assert (t["income"], t["direct"], t["gross_profit"]) == (D(100000), D(60000), D(40000))
    assert (t["other_income"], t["indirect"], t["net_profit"]) == (D(500), D(10000), D(30500))
    assert t["gross_margin"] == D("40.0") and t["net_margin"] == D("30.5")
    assert out["prior_totals"]["net_profit"] == D(5000)
    assert out["sections"]["direct"][0]["ledgers"][0]["name"] == "Cement"


def test_a_projects_pl_shows_its_overhead_share_apart():
    out = pl_layout({L["revenue"]: D(-100000), L["cement"]: D(60000), L["overheads"]: D(8000)}, LEDGERS, GROUPS, None)
    assert out["overheads"] == D(8000) and out["totals"]["net_profit"] == D(32000)
    assert out["net_before_overheads"] == D(40000) and out["prior_totals"] is None


def test_balance_sheet_balances_with_the_years_profit_in_capital():
    # Capital 5,00,000 in; earned 1,00,000 billed and banked last year; this year cement 60,000 on credit (unpaid
    # 20,000) and billed 1,00,000 banked.
    before = {L["capital"]: D(-500000), L["bank"]: D(600000), L["revenue"]: D(-100000)}
    now = {L["capital"]: D(-500000), L["bank"]: D(660000), L["vendor"]: D(-20000), L["revenue"]: D(-200000),
           L["cement"]: D(60000)}
    out = bs_layout(now, before, LEDGERS, GROUPS)
    assert out["balanced"] and out["total_assets"] == D(660000)
    assert out["earlier_profit"] == D(100000) and out["year_profit"] == D(40000)
    capital = next(g for g in out["liabilities"] if g["code"] == "capital")
    assert capital["amount"] == D(640000)
    assert {s["name"] for s in capital["subgroups"]} >= {"Profit or loss of earlier years", "Profit or loss this year"}


def test_overheads_are_shared_by_weight_the_last_takes_the_rounding_and_it_nets_to_nil():
    p1, p2, p3, office = (str(uuid.uuid4()) for _ in range(4))
    [e] = posting.overhead_entries(datetime.date(2026, 10, 31), D(10000), {p1: D(1), p2: D(1), p3: D(1)}, "cost", office)
    assert posting.balanced(e) and e["date"] == datetime.date(2026, 10, 31)
    debits = sorted(ln["debit"] for ln in e["lines"] if ln["debit"])
    assert sum(debits) == D(10000) and debits == [D("3333.33"), D("3333.33"), D("3333.34")]
    credit = next(ln for ln in e["lines"] if ln["credit"])
    assert credit["project_id"] == office and credit["ledger"] == posting.code("overheads_allocated")
    assert posting.overhead_entries(datetime.date(2026, 10, 31), D(0), {p1: D(1)}, "cost") == []
    assert posting.overhead_entries(datetime.date(2026, 10, 31), D(100), {p1: D(0)}, "billing") == []
