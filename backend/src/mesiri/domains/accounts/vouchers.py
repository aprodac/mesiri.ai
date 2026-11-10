"""ACC-12: manual vouchers, for what no record on site or in the office says (a provision, a correction, a
reclassification, depreciation adjusted by the CA). Kept as records (``account_vouchers``); the posting sweep posts
them like any other record, so a closed month is never changed (D-ACC2) and the books can always be re-posted.

Rules, checked here before anything is saved:

- at least two lines; each a debit or a credit, never both, never negative; debits equal credits to the paisa;
- each ledger is the company's and switched on, and never a bank or cash account (or the TDS payable account):
  money that moved is a movement in Finance › Money (a transfer posts as a contra on its own), so the bank and cash
  books keep agreeing with Finance;
- a voucher is dated in an open month; a closed month is reopened first (the owner or an admin, with a reason);
- a project or site on a line is the company's.

Cancelling keeps the voucher (with who, when and why) and takes it out of the books; after its month is closed, the
difference is posted on the first open day, marked "changed after close", as for any record.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.domains.accounts import periods

_ZERO = Decimal(0)
_C = Decimal("0.01")


class VoucherError(ValueError):
    """A voucher that cannot be saved, with what to change (shown as it is)."""

    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


def check_lines(lines: list[dict[str, Any]]) -> tuple[Decimal, Decimal]:
    """Pure: the shape of the lines (for tests). Returns (debits, credits)."""
    if len(lines) < 2:
        raise VoucherError("A voucher needs at least two lines: what is debited and what is credited.")
    debit = credit = _ZERO
    for i, ln in enumerate(lines, start=1):
        dr = Decimal(str(ln.get("debit") or 0))
        cr = Decimal(str(ln.get("credit") or 0))
        if dr < 0 or cr < 0:
            raise VoucherError(f"Line {i}: an amount is never negative; put it on the other side.")
        if dr != dr.quantize(_C) or cr != cr.quantize(_C):
            raise VoucherError(f"Line {i}: amounts are to the paisa (two decimals).")
        if (dr > 0) == (cr > 0):
            raise VoucherError(f"Line {i}: give a debit or a credit, not both and not neither.")
        debit += dr
        credit += cr
    if debit != credit:
        raise VoucherError(f"Debits (₹{debit:,.2f}) and credits (₹{credit:,.2f}) differ by ₹{abs(debit - credit):,.2f}.")
    return debit, credit


async def _ledgers(conn: AsyncConnection, org: uuid.UUID, ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, Any]]:
    return {r["id"]: dict(r) for r in (await conn.execute(text(
        "SELECT l.id, l.name, l.link_kind, l.is_active FROM ledgers l WHERE l.organization_id = :org AND l.id = ANY(:ids)"),
        {"org": org, "ids": ids})).mappings()}


async def validate(conn: AsyncConnection, org: uuid.UUID, day: datetime.date, lines: list[dict[str, Any]]) -> None:
    check_lines(lines)
    found = await _ledgers(conn, org, [ln["ledger_id"] for ln in lines])
    for i, ln in enumerate(lines, start=1):
        led = found.get(ln["ledger_id"])
        if led is None:
            raise VoucherError(f"Line {i}: that ledger is not in your chart of accounts.", 404)
        if not led["is_active"]:
            raise VoucherError(f"Line {i}: {led['name']} is switched off; switch it on in the chart of accounts first.")
        if led["link_kind"] == "money_account":
            raise VoucherError(f"Line {i}: {led['name']} is a bank or cash account. Money that moved is recorded in "
                               "Finance › Money (a transfer between your own accounts posts here as a contra on its "
                               "own), so the books keep agreeing with it.")
    projects = {ln["project_id"] for ln in lines if ln.get("project_id")}
    sites = {ln["site_id"] for ln in lines if ln.get("site_id")}
    if projects and (await conn.execute(text(
            "SELECT COUNT(*) FROM projects WHERE organization_id = :org AND id = ANY(:ids)"),
            {"org": org, "ids": list(projects)})).scalar() != len(projects):
        raise VoucherError("A project on a line is not this company's.", 404)
    if sites and (await conn.execute(text(
            "SELECT COUNT(*) FROM sites WHERE organization_id = :org AND id = ANY(:ids)"),
            {"org": org, "ids": list(sites)})).scalar() != len(sites):
        raise VoucherError("A site on a line is not this company's.", 404)
    await open_on(conn, org, day)


async def open_on(conn: AsyncConnection, org: uuid.UUID, day: datetime.date) -> None:
    """Refuse a day in a closed month (or a closed year), naming it."""
    for start, end in await periods.closed_spans(conn, org):
        if start <= day <= end:
            raise VoucherError(f"{start:%B %Y} is closed. Date the voucher in an open month, or reopen {start:%B %Y} "
                               "first (Accounts › Months).", 409)


async def _write_lines(conn: AsyncConnection, org: uuid.UUID, voucher_id: uuid.UUID, lines: list[dict[str, Any]]) -> None:
    await conn.execute(text("DELETE FROM account_voucher_lines WHERE voucher_id = :v"), {"v": voucher_id})
    await conn.execute(text(
        "INSERT INTO account_voucher_lines (organization_id, voucher_id, line_no, ledger_id, debit, credit, project_id, "
        "site_id, cost_centre) VALUES (:org, :v, :no, :l, :dr, :cr, :p, :s, :cc)"),
        [{"org": org, "v": voucher_id, "no": i, "l": ln["ledger_id"], "dr": Decimal(str(ln.get("debit") or 0)),
          "cr": Decimal(str(ln.get("credit") or 0)), "p": ln.get("project_id"), "s": ln.get("site_id"),
          "cc": (ln.get("cost_centre") or None)} for i, ln in enumerate(lines, start=1)])


async def create(conn: AsyncConnection, org: uuid.UUID, user_id: uuid.UUID, day: datetime.date, narration: str,
                 lines: list[dict[str, Any]]) -> uuid.UUID:
    await validate(conn, org, day, lines)
    vid = (await conn.execute(text(
        "INSERT INTO account_vouchers (organization_id, voucher_date, narration, created_by, updated_by) "
        "VALUES (:org, :d, :n, :u, :u) RETURNING id"), {"org": org, "d": day, "n": narration.strip(), "u": user_id})).scalar_one()
    await _write_lines(conn, org, vid, lines)
    return vid


async def _own(conn: AsyncConnection, org: uuid.UUID, voucher_id: uuid.UUID) -> dict[str, Any]:
    row = (await conn.execute(text(
        "SELECT id, voucher_date, status FROM account_vouchers WHERE id = :v AND organization_id = :org"),
        {"v": voucher_id, "org": org})).mappings().first()
    if row is None:
        raise VoucherError("Voucher not found.", 404)
    return dict(row)


async def update(conn: AsyncConnection, org: uuid.UUID, user_id: uuid.UUID, voucher_id: uuid.UUID,
                 day: datetime.date, narration: str, lines: list[dict[str, Any]]) -> None:
    """Change a voucher of an open month (moving it into another open month too); a closed month's stays as it is."""
    v = await _own(conn, org, voucher_id)
    if v["status"] != "posted":
        raise VoucherError("A cancelled voucher is kept as it was; make a new one.", 409)
    await open_on(conn, org, v["voucher_date"])
    await validate(conn, org, day, lines)
    await conn.execute(text(
        "UPDATE account_vouchers SET voucher_date = :d, narration = :n, updated_by = :u, updated_at = now() WHERE id = :v"),
        {"d": day, "n": narration.strip(), "u": user_id, "v": voucher_id})
    await _write_lines(conn, org, voucher_id, lines)


async def cancel(conn: AsyncConnection, org: uuid.UUID, user_id: uuid.UUID, voucher_id: uuid.UUID, reason: str) -> None:
    v = await _own(conn, org, voucher_id)
    if v["status"] == "cancelled":
        return
    await conn.execute(text(
        "UPDATE account_vouchers SET status = 'cancelled', cancelled_by = :u, cancelled_at = now(), cancel_reason = :r, "
        "updated_at = now() WHERE id = :v"), {"u": user_id, "r": reason.strip(), "v": voucher_id})


async def listing(conn: AsyncConnection, org: uuid.UUID, date_from: datetime.date, date_to: datetime.date,
                  voucher_id: uuid.UUID | None = None) -> list[dict[str, Any]]:
    """The manual vouchers of a period (or one), with their lines, who made them and the journal each posted as."""
    where = "v.organization_id = :org AND " + ("v.id = :id" if voucher_id else "v.voucher_date BETWEEN :f AND :t")
    head = [dict(r) for r in (await conn.execute(text(
        "SELECT v.id, v.voucher_date, v.narration, v.status, v.created_at, cu.full_name AS created_by, v.updated_at, "
        "v.cancelled_at, xu.full_name AS cancelled_by, v.cancel_reason, "
        "(SELECT j.id FROM journal_entries j WHERE j.organization_id = v.organization_id AND j.source_kind = 'voucher' "
        " AND j.source_id = v.id AND NOT j.after_close ORDER BY j.created_at LIMIT 1) AS entry_id, "
        "(SELECT j.financial_year || '/' || j.number FROM journal_entries j WHERE j.organization_id = v.organization_id "
        " AND j.source_kind = 'voucher' AND j.source_id = v.id AND NOT j.after_close ORDER BY j.created_at LIMIT 1) AS ref "
        "FROM account_vouchers v LEFT JOIN users cu ON cu.id = v.created_by LEFT JOIN users xu ON xu.id = v.cancelled_by "
        f"WHERE {where} ORDER BY v.voucher_date DESC, v.created_at DESC"),  # noqa: S608 (fixed SQL)
        {"org": org, "f": date_from, "t": date_to, "id": voucher_id})).mappings()]
    lines: dict[Any, list] = {}
    if head:
        for r in (await conn.execute(text(
                "SELECT x.voucher_id, x.line_no, x.ledger_id, l.name AS ledger, x.debit, x.credit, x.project_id, "
                "p.name AS project, x.site_id, s.name AS site, x.cost_centre FROM account_voucher_lines x "
                "JOIN ledgers l ON l.id = x.ledger_id LEFT JOIN projects p ON p.id = x.project_id "
                "LEFT JOIN sites s ON s.id = x.site_id WHERE x.voucher_id = ANY(:ids) ORDER BY x.line_no"),
                {"ids": [h["id"] for h in head]})).mappings():
            lines.setdefault(r["voucher_id"], []).append(dict(r))
    out = []
    for h in head:
        ls = lines.get(h["id"], [])
        out.append({**h, "date": h.pop("voucher_date"), "ref": f"JOU/{h['ref']}" if h["ref"] else None,
                    "amount": sum((Decimal(x["debit"]) for x in ls), _ZERO), "lines": ls})
    return out
