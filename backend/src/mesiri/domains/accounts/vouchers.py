"""ACC-12: manual vouchers -- what the accountant enters: an opening balance, a transfer between bank and cash, a
correction, a provision, bank charges.

A manual voucher is a ``journal_entries`` row with ``source_kind = 'manual'``, in the same books as everything the
sweep posts: numbered per voucher type and financial year with the same numbering, balanced by the same database check
(the deferred trigger is the real guard; ``validate`` only gives the person a clear word first), read by every report.
The sweep never reads, re-posts or deletes a manual voucher (``sweep._apply`` excludes ``source_kind = 'manual'``).

- **Journal**: any ledgers. **Contra**: only cash and bank ledgers (``Bank Accounts`` / ``Cash-in-Hand`` and groups
  under them), e.g. cash deposited in the bank.
- A line is a debit or a credit (never both, never negative, paise exact) on a ledger, with an optional project, site
  and cost centre. A party is its own ledger (a supplier, a client), so it is picked as the ledger.
- **Never edited or deleted.** ``reverse`` posts the mirror (debits and credits swapped), linked by ``reverses_id``
  with the reason; a voucher is reversed once. Dated the original's day, or, when that month is closed, the first
  open day after it, marked ``after_close`` (D-ACC2). "Correct" (owner / admin) is a reversal and a new voucher in
  one transaction.
- **A closed month takes no new voucher** (D-ACC2): refused, naming the month and who can reopen it.
- **Opening balances**: a Journal on the first day of the year against "Opening balance difference", the ledger the
  sweep's own opening balances use (``posting.opening_account_entries``).
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.domains.accounts import chart, periods

MANUAL = "manual"
TYPES = ("journal", "contra")
#: The groups a Contra may touch (and every group under them).
CONTRA_GROUPS = frozenset({"bank_accounts", "cash_in_hand"})
#: CC-01's cost centres (0521).
COST_CENTRES = ("materials", "labour", "subcontract", "equipment", "fuel", "overhead", "other")
MAX_LINES = 100
_C = Decimal("0.01")
_ZERO = Decimal(0)


class VoucherError(ValueError):
    """What is wrong with a voucher, in words the person can act on."""

    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


def _amount(value: Any, where: str) -> Decimal:
    try:
        d = Decimal(str(value if value not in (None, "") else 0))
    except InvalidOperation as exc:
        raise VoucherError(f"{where}: not an amount.") from exc
    if d < 0:
        raise VoucherError(f"{where}: no negative amounts; put it on the other side.")
    if d != d.quantize(_C):
        raise VoucherError(f"{where}: at most two decimals (paise).")
    return d


def validate(voucher_type: str, lines: list[dict[str, Any]], contra_ledgers: set[str]) -> list[dict[str, Any]]:
    """Clean lines (``ledger_id``, ``debit``, ``credit`` as Decimal, ``project_id``, ``site_id``, ``cost_centre``) or a
    ``VoucherError``. ``contra_ledgers``: ids of the cash and bank ledgers."""
    if voucher_type not in TYPES:
        raise VoucherError(f"A manual voucher is a {' or a '.join(TYPES)}.")
    if len(lines) < 2:
        raise VoucherError("A voucher needs at least two lines: one debit and one credit.")
    if len(lines) > MAX_LINES:
        raise VoucherError(f"At most {MAX_LINES} lines in one voucher.")
    out = []
    for i, ln in enumerate(lines, start=1):
        where = f"Line {i}"
        if not ln.get("ledger_id"):
            raise VoucherError(f"{where}: pick a ledger.")
        dr, cr = _amount(ln.get("debit"), where), _amount(ln.get("credit"), where)
        if (dr > 0) == (cr > 0):
            raise VoucherError(f"{where}: a debit or a credit, one of them.")
        cc = ln.get("cost_centre") or None
        if cc is not None and cc not in COST_CENTRES:
            raise VoucherError(f"{where}: cost centre is one of {', '.join(COST_CENTRES)}.")
        if voucher_type == "contra" and str(ln["ledger_id"]) not in contra_ledgers:
            raise VoucherError(f"{where}: a Contra moves money between cash and bank only. Use a Journal for other "
                               "ledgers.")
        out.append({"ledger_id": str(ln["ledger_id"]), "debit": dr, "credit": cr,
                    "project_id": str(ln["project_id"]) if ln.get("project_id") else None,
                    "site_id": str(ln["site_id"]) if ln.get("site_id") else None, "cost_centre": cc})
    debit = sum((ln["debit"] for ln in out), _ZERO)
    credit = sum((ln["credit"] for ln in out), _ZERO)
    if debit != credit:
        raise VoucherError(f"Debits {debit} and credits {credit} differ by {abs(debit - credit)}: a voucher balances.")
    return out


def mirror(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The reversal's lines: the same ledgers, projects, sites and cost centres, debits and credits swapped."""
    return [{**ln, "debit": ln["credit"], "credit": ln["debit"]} for ln in lines]


def month_words(day: datetime.date) -> str:
    return f"{day:%B %Y}"


# --- reads ---------------------------------------------------------------------------------------------------------

async def ledger_choices(conn: AsyncConnection, org: uuid.UUID) -> list[dict[str, Any]]:
    """Active ledgers for the voucher grid: name, group, and whether a Contra may use it."""
    groups = await chart.groups(conn, org)
    by_id = {g["id"]: g for g in groups}

    def cash_or_bank(group_id: Any) -> bool:
        g = by_id.get(group_id)
        while g is not None:
            if g["code"] in CONTRA_GROUPS:
                return True
            g = by_id.get(g["parent_id"])
        return False

    return [{"id": str(r["id"]), "name": r["name"], "group": by_id[r["group_id"]]["name"], "nature": r["nature"],
             "code": r["code"], "contra": cash_or_bank(r["group_id"])}
            for r in await chart.ledgers(conn, org) if r["is_active"]]


async def _entry(conn: AsyncConnection, org: uuid.UUID, entry_id: uuid.UUID) -> dict[str, Any] | None:
    row = (await conn.execute(text(
        "SELECT id, entry_date, voucher_type, financial_year, number, narration, source_kind, reverses_id, "
        "project_id, (SELECT r.id FROM journal_entries r WHERE r.reverses_id = j.id) AS reversed_by "
        "FROM journal_entries j WHERE id = :id AND organization_id = :org"), {"id": entry_id, "org": org})).mappings().first()
    return dict(row) if row else None


# --- writes --------------------------------------------------------------------------------------------------------

async def _check_refs(conn: AsyncConnection, org: uuid.UUID, lines: list[dict[str, Any]]) -> None:
    """Every ledger, project and site on the lines is this company's (and the ledger in use)."""
    ledgers = {str(r[0]) for r in await conn.execute(text(
        "SELECT id FROM ledgers WHERE organization_id = :org AND is_active AND id = ANY(:ids)"),
        {"org": org, "ids": [uuid.UUID(ln["ledger_id"]) for ln in lines]})}
    for i, ln in enumerate(lines, start=1):
        if ln["ledger_id"] not in ledgers:
            raise VoucherError(f"Line {i}: that ledger is not in this company's chart (or is switched off).")
    projects = {ln["project_id"] for ln in lines if ln["project_id"]}
    sites = {ln["site_id"] for ln in lines if ln["site_id"]}
    if projects and len({str(r[0]) for r in await conn.execute(text(
            "SELECT id FROM projects WHERE organization_id = :org AND id = ANY(:ids)"),
            {"org": org, "ids": [uuid.UUID(p) for p in projects]})}) != len(projects):
        raise VoucherError("A project on the voucher is not this company's.")
    if sites:
        found = {str(r[0]): str(r[1]) for r in await conn.execute(text(
            "SELECT id, project_id FROM sites WHERE organization_id = :org AND id = ANY(:ids)"),
            {"org": org, "ids": [uuid.UUID(s) for s in sites]})}
        for i, ln in enumerate(lines, start=1):
            if ln["site_id"] and (ln["site_id"] not in found or (ln["project_id"] and found[ln["site_id"]] != ln["project_id"])):
                raise VoucherError(f"Line {i}: that site is not in the line's project.")
            if ln["site_id"] and not ln["project_id"]:
                ln["project_id"] = found[ln["site_id"]]


async def _insert(conn: AsyncConnection, org: uuid.UUID, user_id: uuid.UUID, day: datetime.date, voucher_type: str,
                  narration: str, lines: list[dict[str, Any]], *, after_close: bool = False,
                  reverses_id: uuid.UUID | None = None, reason: str | None = None) -> uuid.UUID:
    fy = periods.fy_label(day)
    number = (await conn.execute(text(
        "SELECT COALESCE(MAX(number), 0) + 1 FROM journal_entries WHERE organization_id = :org AND voucher_type = :t "
        "AND financial_year = :fy"), {"org": org, "t": voucher_type, "fy": fy})).scalar_one()
    projects = {ln["project_id"] for ln in lines}
    entry_id = (await conn.execute(text(
        "INSERT INTO journal_entries (organization_id, entry_date, voucher_type, financial_year, number, narration, "
        "source_kind, source_part, after_close, project_id, created_by, reverses_id, reversal_reason) VALUES "
        "(:org, :d, :t, :fy, :no, :n, :k, 'main', :ac, CAST(:p AS uuid), :u, :rev, :why) RETURNING id"),
        {"org": org, "d": day, "t": voucher_type, "fy": fy, "no": number, "n": narration, "k": MANUAL, "ac": after_close,
         "p": next(iter(projects)) if len(projects) == 1 else None, "u": user_id, "rev": reverses_id,
         "why": reason})).scalar_one()
    await conn.execute(text(
        "INSERT INTO journal_lines (organization_id, entry_id, line_no, entry_date, ledger_id, debit, credit, project_id, "
        "site_id, cost_centre) VALUES (:org, :e, :no, :d, :l, :dr, :cr, CAST(:p AS uuid), CAST(:s AS uuid), :cc)"),
        [{"org": org, "e": entry_id, "no": i, "d": day, "l": uuid.UUID(ln["ledger_id"]), "dr": ln["debit"],
          "cr": ln["credit"], "p": ln["project_id"], "s": ln["site_id"], "cc": ln["cost_centre"]}
         for i, ln in enumerate(lines, start=1)])
    await periods.ensure_months(conn, org, {day})
    return entry_id


async def _lock(conn: AsyncConnection, org: uuid.UUID) -> None:
    """The sweep's lock: a manual voucher and a sweep never number at the same time."""
    await conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"mesiri-accounts:{org}"})


async def post(conn: AsyncConnection, org: uuid.UUID, user_id: uuid.UUID, *, day: datetime.date, voucher_type: str,
               narration: str, lines: list[dict[str, Any]]) -> uuid.UUID:
    """A new manual voucher (``VoucherError`` when it cannot be)."""
    await _lock(conn, org)
    await chart.ensure_chart(conn, org)
    contra = {x["id"] for x in await ledger_choices(conn, org) if x["contra"]}
    clean = validate(voucher_type, lines, contra)
    await _check_refs(conn, org, clean)
    closed = await periods.closed_spans(conn, org)
    for start, end in closed:
        if start <= day <= end:
            raise VoucherError(f"{month_words(start)} is closed, so it takes no new voucher. The owner or an admin can "
                               "reopen it in Accounts › Close the month, with a reason.", status=409)
    return await _insert(conn, org, user_id, day, voucher_type, narration.strip(), clean)


async def reverse(conn: AsyncConnection, org: uuid.UUID, user_id: uuid.UUID, entry_id: uuid.UUID,
                  reason: str) -> uuid.UUID:
    """The mirror of a manual voucher, linked to it. Returns the reversal's id."""
    await _lock(conn, org)
    original = await _entry(conn, org, entry_id)
    if original is None:
        raise VoucherError("Voucher not found.", status=404)
    if original["source_kind"] != MANUAL:
        raise VoucherError("Only a manual voucher is reversed here. A voucher posted from a record follows the "
                           "record: change or cancel the expense, payment or bill instead.", status=409)
    if original["reverses_id"] is not None:
        raise VoucherError("This voucher is itself a reversal. Post a new voucher instead.", status=409)
    if original["reversed_by"] is not None:
        raise VoucherError("This voucher is already reversed.", status=409)
    lines = [{"ledger_id": str(r["ledger_id"]), "debit": r["debit"], "credit": r["credit"],
              "project_id": str(r["project_id"]) if r["project_id"] else None,
              "site_id": str(r["site_id"]) if r["site_id"] else None, "cost_centre": r["cost_centre"]}
             for r in (await conn.execute(text(
                 "SELECT ledger_id, debit, credit, project_id, site_id, cost_centre FROM journal_lines "
                 "WHERE entry_id = :id ORDER BY line_no"), {"id": entry_id})).mappings()]
    closed = await periods.closed_spans(conn, org)
    day = periods.first_open_day(closed, original["entry_date"])
    late = day != original["entry_date"]
    ref = f"{original['voucher_type'][:3].upper()}/{original['financial_year']}/{original['number']}"
    words = (f"Reversal of {ref}" + (f" (dated {month_words(original['entry_date'])}, closed)" if late else "")
             + f" · {reason}")
    return await _insert(conn, org, user_id, day, original["voucher_type"], words, mirror(lines), after_close=late,
                         reverses_id=entry_id, reason=reason)
