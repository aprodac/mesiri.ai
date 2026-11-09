"""ACC-01: the chart of accounts (D-ACC8): Tally's primary groups and the ledgers a construction company needs,
seeded per company on first use; linked ledgers (one per supplier, client, money account, expense category and member
of staff owed money) made by the posting sweep, never typed.

The company renames, adds and regroups (``router.py``); seeded rows keep their ``code`` however they are renamed, so
posting always finds them. A linked ledger is named after its record (rename the supplier in Vendors and the ledger
follows); it can be moved to another group.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

#: (code, name, nature, parent code). Order is the order shown (balance sheet first, then P&L), as Tally lists them.
GROUPS: tuple[tuple[str, str, str, str | None], ...] = (
    ("capital", "Capital Account", "equity", None),
    ("reserves", "Reserves & Surplus", "equity", "capital"),
    ("loans", "Loans (Liability)", "liability", None),
    ("current_liabilities", "Current Liabilities", "liability", None),
    ("sundry_creditors", "Sundry Creditors", "liability", "current_liabilities"),
    ("duties_taxes", "Duties & Taxes", "liability", "current_liabilities"),
    ("provisions", "Provisions", "liability", "current_liabilities"),
    ("suspense", "Suspense A/c", "liability", None),
    ("fixed_assets", "Fixed Assets", "asset", None),
    ("current_assets", "Current Assets", "asset", None),
    ("sundry_debtors", "Sundry Debtors", "asset", "current_assets"),
    ("bank_accounts", "Bank Accounts", "asset", "current_assets"),
    ("cash_in_hand", "Cash-in-Hand", "asset", "current_assets"),
    ("loans_advances", "Loans & Advances (Asset)", "asset", "current_assets"),
    ("deposits", "Deposits (Asset)", "asset", "current_assets"),
    ("sales", "Sales Accounts", "income", None),
    ("direct_income", "Direct Incomes", "income", None),
    ("indirect_income", "Indirect Incomes", "income", None),
    ("purchases", "Purchase Accounts", "expense", None),
    ("direct_expenses", "Direct Expenses", "expense", None),
    ("indirect_expenses", "Indirect Expenses", "expense", None),
)

#: (code, name, group code, what it is for). Names match the Tally export (``finance/tally.py``) where it has them.
LEDGERS: tuple[tuple[str, str, str, str], ...] = (
    ("contract_revenue", "Contract revenue", "sales", "RA bills sent to clients (gross, before GST)"),
    ("output_gst", "Output GST", "duties_taxes", "GST on RA bills"),
    ("input_gst", "Input GST", "duties_taxes", "GST on supplier bills the company can claim back"),
    ("tds_receivable", "TDS receivable", "loans_advances", "TDS clients deduct from RA bills"),
    ("retention_receivable", "Retention receivable", "loans_advances", "Retention clients hold back from RA bills"),
    ("advance_received", "Mobilisation advance received", "current_liabilities",
     "Advances from clients, recovered from RA bills"),
    ("expenses_payable", "Expenses payable", "current_liabilities", "Expenses with no supplier, until paid"),
    ("funds_introduced", "Funds introduced", "capital", "Money put into an account from outside (fund received)"),
    ("opening_difference", "Opening balance difference", "suspense",
     "The other side of opening balances, and a supplier's records from before their opening date"),
    ("balance_adjustments", "Money balance adjustments", "suspense", "Adjustments to an account balance, to classify"),
    ("no_client", "Client (not set)", "sundry_debtors", "RA bills of a project with no client set"),
    ("retention_payable", "Retention payable", "current_liabilities", "Retention held back from subcontractors"),
    ("bank_charges", "Bank charges", "indirect_expenses", "Charges the bank takes"),
    ("round_off", "Round off", "indirect_expenses", "Rounding differences"),
    ("overheads_allocated", "Head office overheads allocated", "indirect_expenses",
     "Each project's monthly share of head-office costs, when sharing is on (nil company-wide)"),
    # LW-06 (9 Nov 2026): labour is cost when worked (attendance at its wage) and money when paid.
    ("labour_wages", "Labour wages", "direct_expenses", "Attendance at its wage, per project and site (the labour cost)"),
    ("wages_payable", "Wages payable", "current_liabilities", "Wages earned on site and not yet paid"),
    ("labour_advances", "Advances to labour", "loans_advances",
     "Advances given to workers and labour contractors, until taken back from their wages"),
)

#: The groups a linked ledger is made in (``link_kind`` -> group code). Money accounts depend on the account type.
LINK_GROUP = {"vendor": "sundry_creditors", "client": "sundry_debtors", "expense_category": "direct_expenses",
              "staff": "current_liabilities"}
ACCOUNT_TYPE_GROUP = {"bank": "bank_accounts", "cash": "cash_in_hand", "employee_advance": "cash_in_hand",
                      "other": "current_assets"}
#: The TDS payable money account (``subcontracts/store.py``) is money owed to the government, not money held.
TDS_ACCOUNT_GROUP = "duties_taxes"

#: Natures whose balance is a debit when positive (assets, expenses); the others are credits.
DEBIT_NATURES = frozenset({"asset", "expense"})
PL_NATURES = frozenset({"income", "expense"})


def account_group(account_type: str | None, name: str | None) -> str:
    from mesiri.domains.subcontracts.store import TDS_ACCOUNT

    if name == TDS_ACCOUNT:
        return TDS_ACCOUNT_GROUP
    return ACCOUNT_TYPE_GROUP.get((account_type or "").lower(), "current_assets")


async def ensure_chart(conn: AsyncConnection, org: uuid.UUID) -> None:
    """Seed the groups and ledgers the company does not have yet (by code). Idempotent; never renames or moves."""
    have = {r[0] for r in (await conn.execute(text(
        "SELECT code FROM ledger_groups WHERE organization_id = :org AND code IS NOT NULL"), {"org": org}))}
    for sort, (code, name, nature, parent) in enumerate(GROUPS):
        if code in have:
            continue
        await conn.execute(text(
            "INSERT INTO ledger_groups (organization_id, parent_id, name, nature, code, sort) VALUES (:org, "
            "(SELECT id FROM ledger_groups WHERE organization_id = :org AND code = :parent), :name, :nature, :code, :sort) "
            "ON CONFLICT DO NOTHING"),
            {"org": org, "parent": parent, "name": name, "nature": nature, "code": code, "sort": sort})
    have = {r[0] for r in (await conn.execute(text(
        "SELECT code FROM ledgers WHERE organization_id = :org AND code IS NOT NULL"), {"org": org}))}
    for code, name, group, notes in LEDGERS:
        if code in have:
            continue
        await conn.execute(text(
            "INSERT INTO ledgers (organization_id, group_id, name, code, notes) VALUES (:org, "
            "(SELECT id FROM ledger_groups WHERE organization_id = :org AND code = :g), :name, :code, :notes) "
            "ON CONFLICT DO NOTHING"), {"org": org, "g": group, "name": name, "code": code, "notes": notes})


async def groups(conn: AsyncConnection, org: uuid.UUID) -> list[dict[str, Any]]:
    return [dict(r) for r in (await conn.execute(text(
        "SELECT id, parent_id, name, nature, code, sort FROM ledger_groups WHERE organization_id = :org "
        "ORDER BY sort, name"), {"org": org})).mappings()]


async def ledgers(conn: AsyncConnection, org: uuid.UUID) -> list[dict[str, Any]]:
    return [dict(r) for r in (await conn.execute(text(
        "SELECT l.id, l.group_id, l.name, l.code, l.link_kind, l.link_id, l.notes, l.is_active, g.nature "
        "FROM ledgers l JOIN ledger_groups g ON g.id = l.group_id WHERE l.organization_id = :org ORDER BY l.name"),
        {"org": org})).mappings()]
