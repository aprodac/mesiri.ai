"""ACC-17: year end and carry forward (April to March, D-ACC7).

**Closing a year** (the owner or an admin, once 31 March is past): every month of the year is closed (D-ACC2: its
entries never change again; a late change to a record is posted on the first open day of the next year, marked), and
the year is locked: none of its months can be reopened until the year itself is reopened, with a reason. What the
year carried forward is kept with it (``snapshot``): each balance-sheet ledger's closing balance and the year's profit.

**Carry forward** works the way Tally does it: no closing journal. Each income and expense ledger starts the next year
at nil, and the year's profit or loss joins capital as "Profit or loss of earlier years" (the balance sheet and the
trial balance already read it so). Balance-sheet ledgers carry their balance into the next year's opening.

**The checklist** before closing says what is not done, each with where to fix it. Only "the year is not over"
blocks; the rest are warnings the closer acknowledges (an accountant may close with a known difference and fix it
in the next year), so they are said, never hidden:

- months of the year still open (they will be closed with it);
- the trial balance does not balance (it always should: a sign of a bug, said loudly);
- "Opening balance difference" or "Money balance adjustments" not nil (opening balances or adjustments to classify);
- bank statement lines of the year neither matched, booked nor ignored (bank not reconciled);
- the year's depreciation not posted (it is posted once the year is over: a register with assets should show it).

A drift check compares a closed year's snapshot with its balances now: they always agree, because closed months are
never changed; a difference is a sign of a bug or a direct database edit, and is shown.
"""

from __future__ import annotations

import datetime
import json
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.domains.accounts import chart, periods, reports

_ZERO = Decimal(0)


def fy_from_label(label: str) -> datetime.date:
    """``2025-26`` -> 1 April 2025."""
    try:
        start = int(label[:4])
        if label[4] != "-" or int(label[5:]) != (start + 1) % 100:
            raise ValueError
    except (ValueError, IndexError) as exc:
        raise ValueError("A year as 2025-26.") from exc
    return datetime.date(start, periods.FY_START_MONTH, 1)


async def _balances(conn: AsyncConnection, org: uuid.UUID, as_of: datetime.date) -> dict[str, Any]:
    """Balance-sheet ledgers' balances on a day, the year's profit (income − expense since 1 April) and earlier
    years' (before it). Ledgers + both profits balance: debits = credits."""
    rows = (await conn.execute(text(
        "SELECT jl.ledger_id, g.nature, SUM(CASE WHEN jl.entry_date >= :fy THEN jl.debit - jl.credit ELSE 0 END) AS this, "
        "SUM(jl.debit - jl.credit) AS bal FROM journal_lines jl "
        "JOIN ledgers l ON l.id = jl.ledger_id JOIN ledger_groups g ON g.id = l.group_id "
        "WHERE jl.organization_id = :org AND jl.entry_date <= :t GROUP BY jl.ledger_id, g.nature"),
        {"org": org, "t": as_of, "fy": periods.fy_start(as_of)})).mappings()
    out: dict[str, Decimal] = {}
    profit = earlier = _ZERO
    for r in rows:
        if r["nature"] in chart.PL_NATURES:
            profit -= Decimal(r["this"])
            earlier -= Decimal(r["bal"]) - Decimal(r["this"])
        elif r["bal"]:
            out[str(r["ledger_id"])] = Decimal(r["bal"])
    return {"ledgers": out, "profit": profit, "earlier": earlier}


async def checklist(conn: AsyncConnection, org: uuid.UUID, start: datetime.date, today: datetime.date) -> list[dict]:
    end = periods.fy_end(start)
    items: list[dict[str, Any]] = []

    def add(key: str, ok: bool, words: str, to: str | None = None, blocks: bool = False, amount: Any = None) -> None:
        items.append({"key": key, "ok": ok, "words": words, "to": to, "blocks": blocks and not ok, "amount": amount})

    add("over", end < today, "The year is over (31 March has passed)." if end < today else
        f"The year runs to {end:%d %B %Y}: it can be closed from 1 April.", blocks=True)
    open_months = (await conn.execute(text(
        "SELECT COUNT(*) FROM accounting_periods WHERE organization_id = :org AND starts_on BETWEEN :f AND :t "
        "AND status = 'open'"), {"org": org, "f": start, "t": end})).scalar()
    add("months", not open_months, "Every month is closed." if not open_months else
        f"{open_months} month{'s' if open_months != 1 else ''} still open: closing the year closes them.",
        "/accounts/periods")
    tb = await reports.trial_balance(conn, org, start, end)
    t = tb["totals"]
    add("balanced", t["balanced"], "The trial balance balances." if t["balanced"] else
        "The trial balance does not balance. Tell Mesiri support before closing.", "/accounts/trial-balance",
        amount=t["closing_debit"] - t["closing_credit"])
    bal = await reports.balances(conn, org, end)
    for code_, words, to in (("opening_difference", "Opening balance difference", "/accounts/ledgers"),
                             ("balance_adjustments", "Money balance adjustments", "/accounts/ledgers")):
        lid = (await conn.execute(text("SELECT id FROM ledgers WHERE organization_id = :org AND code = :c"),
                                  {"org": org, "c": code_})).scalar()
        amount = bal.get(lid, _ZERO) if lid else _ZERO
        add(code_, not amount, f"{words} is nil." if not amount else
            f"{words} is not nil: move it to the right ledgers with a voucher.", to, amount=abs(amount))
    open_lines = (await conn.execute(text(
        "SELECT COUNT(*) FROM bank_statement_lines WHERE organization_id = :org AND line_date BETWEEN :f AND :t "
        "AND status = 'open'"), {"org": org, "f": start, "t": end})).scalar()
    imported = (await conn.execute(text(
        "SELECT COUNT(*) FROM bank_statement_lines WHERE organization_id = :org AND line_date BETWEEN :f AND :t"),
        {"org": org, "f": start, "t": end})).scalar()
    add("bank", imported > 0 and not open_lines,
        "Bank statements reconciled." if imported and not open_lines else
        (f"{open_lines} bank statement line{'s' if open_lines != 1 else ''} not reconciled." if imported else
         "No bank statement imported for the year: reconcile the bank before closing."), "/accounts/bank")
    assets = (await conn.execute(text(
        "SELECT COUNT(*) FROM fixed_assets WHERE organization_id = :org AND acquired_on <= :t "
        "AND (disposed_on IS NULL OR disposed_on > :t)"), {"org": org, "t": end})).scalar()
    posted = (await conn.execute(text(
        "SELECT COUNT(*) FROM journal_entries WHERE organization_id = :org AND source_kind = 'fixed_asset' "
        "AND source_part = :p"), {"org": org, "p": f"dep:{periods.fy_label(start)}"})).scalar()
    if assets:
        add("depreciation", posted > 0, f"Depreciation posted for {posted} asset{'s' if posted != 1 else ''}."
            if posted else "Depreciation is posted once the year is over.", "/accounts/assets")
    else:
        add("depreciation", True, "No fixed assets in the register (add them under Fixed assets if the company owns any).",
            "/accounts/assets")
    return items


async def years(conn: AsyncConnection, org: uuid.UUID, today: datetime.date) -> list[dict[str, Any]]:
    """Every year the books have entries in (and this one), newest first, with its state and profit."""
    first = (await conn.execute(text("SELECT MIN(entry_date) FROM journal_entries WHERE organization_id = :org"),
                                {"org": org})).scalar() or today
    stored = {r["financial_year"]: dict(r) for r in (await conn.execute(text(
        "SELECT y.financial_year, y.status, y.closed_at, cu.full_name AS closed_by, y.reopened_at, "
        "ru.full_name AS reopened_by, y.reopen_reason, y.snapshot FROM accounting_years y "
        "LEFT JOIN users cu ON cu.id = y.closed_by LEFT JOIN users ru ON ru.id = y.reopened_by "
        "WHERE y.organization_id = :org"), {"org": org})).mappings()}
    out = []
    start = periods.fy_start(first)
    while start <= today:
        label = periods.fy_label(start)
        s = stored.get(label, {})
        end = periods.fy_end(start)
        now = await _balances(conn, org, min(end, today))
        snap = s.get("snapshot") or {}
        if isinstance(snap, str):
            snap = json.loads(snap)
        drift = None
        if s.get("status") == "closed" and snap:
            kept = {k: Decimal(v) for k, v in (snap.get("ledgers") or {}).items()}
            drift = sum((abs(now["ledgers"].get(k, _ZERO) - v) for k, v in kept.items()), _ZERO) + sum(
                (abs(v) for k, v in now["ledgers"].items() if k not in kept), _ZERO)
        out.append({"financial_year": label, "starts_on": start, "ends_on": end,
                    "status": s.get("status") or "open", "is_current": start <= today <= end,
                    "over": end < today, "profit": now["profit"], "earlier_profit": now["earlier"], "closed_at": s.get("closed_at"),
                    "closed_by": s.get("closed_by"), "reopened_at": s.get("reopened_at"),
                    "reopened_by": s.get("reopened_by"), "reopen_reason": s.get("reopen_reason"),
                    "carried_profit": Decimal(snap["profit"]) if snap.get("profit") is not None else None,
                    "drift": drift})
        start = end + datetime.timedelta(days=1)
    return sorted(out, key=lambda y: y["starts_on"], reverse=True)


async def closed_years(conn: AsyncConnection, org: uuid.UUID) -> list[tuple[datetime.date, datetime.date]]:
    return [(r[0], r[1]) for r in (await conn.execute(text(
        "SELECT starts_on, ends_on FROM accounting_years WHERE organization_id = :org AND status = 'closed'"),
        {"org": org}))]


async def close(conn: AsyncConnection, org: uuid.UUID, user_id: uuid.UUID, start: datetime.date) -> dict[str, Any]:
    """Close every month of the year, keep what it carried forward, lock it."""
    end = periods.fy_end(start)
    months = set()
    m = start
    while m <= end:
        months.add(m)
        m = periods.month_end(m) + datetime.timedelta(days=1)
    await periods.ensure_months(conn, org, months)
    await conn.execute(text(
        "UPDATE accounting_periods SET status = 'closed', closed_by = :u, closed_at = now() "
        "WHERE organization_id = :org AND starts_on BETWEEN :f AND :t AND status = 'open'"),
        {"org": org, "f": start, "t": end, "u": user_id})
    snap = await _balances(conn, org, end)
    payload = json.dumps({"ledgers": {k: str(v) for k, v in snap["ledgers"].items()}, "profit": str(snap["profit"]),
                          "earlier": str(snap["earlier"]), "as_of": end.isoformat()})
    await conn.execute(text(
        "INSERT INTO accounting_years (organization_id, financial_year, starts_on, ends_on, status, closed_by, closed_at, "
        "snapshot) VALUES (:org, :fy, :f, :t, 'closed', :u, now(), CAST(:s AS jsonb)) "
        "ON CONFLICT (organization_id, financial_year) DO UPDATE SET status = 'closed', closed_by = EXCLUDED.closed_by, "
        "closed_at = now(), snapshot = EXCLUDED.snapshot"),
        {"org": org, "fy": periods.fy_label(start), "f": start, "t": end, "u": user_id, "s": payload})
    return snap


async def reopen(conn: AsyncConnection, org: uuid.UUID, user_id: uuid.UUID, start: datetime.date, reason: str) -> None:
    """The year unlocked: its months stay closed; each can then be reopened on its own (Months)."""
    await conn.execute(text(
        "UPDATE accounting_years SET status = 'open', reopened_by = :u, reopened_at = now(), reopen_reason = :r "
        "WHERE organization_id = :org AND financial_year = :fy"),
        {"org": org, "fy": periods.fy_label(start), "u": user_id, "r": reason})


async def carried(conn: AsyncConnection, org: uuid.UUID, start: datetime.date) -> list[dict[str, Any]]:
    """What the year carries into the next: each balance-sheet ledger's closing balance, by group."""
    end = periods.fy_end(start)
    bal = (await _balances(conn, org, end))["ledgers"]
    ledgers = {str(r["id"]): r for r in await chart.ledgers(conn, org)}
    groups = {r["id"]: r for r in await chart.groups(conn, org)}
    rows = []
    for lid, v in bal.items():
        led = ledgers.get(lid)
        if not led:
            continue
        rows.append({"ledger_id": lid, "name": led["name"], "group": groups[led["group_id"]]["name"],
                     "nature": led["nature"], "balance": v})
    return sorted(rows, key=lambda r: (r["nature"], r["group"], r["name"].lower()))
