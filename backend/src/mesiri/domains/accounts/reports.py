"""ACC-05 (and ACC-22's scope): trial balance, day book and ledger statement, from the journal lines. Every figure
opens the entries behind it, and every entry the record it came from.

**Scope (plan §5.8).** Each report reads the whole company, one project, or one site: the lines carry the project and
site of their record. A project's or site's lines need not balance on their own (a transfer from the head office
bank to the site's petty cash has one side on the site, one off it), so a scoped trial balance shows the difference as
"Head office and other projects": what moved between this project and the rest of the company.

**Years.** Income and expense ledgers start each financial year at zero (April, D-ACC7); what they added up to before
is one line, "Profit or loss of earlier years", until the year-end close (ACC-17) moves it for real.

Balances are signed: positive is a debit, negative a credit (shown "Dr" / "Cr").
"""

from __future__ import annotations

import datetime
import uuid
from collections import defaultdict
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.domains.accounts import chart, periods

_ZERO = Decimal(0)
EARLIER_PL = "earlier_pl"
HEAD_OFFICE = "head_office"


def _scope(project_id: uuid.UUID | None, site_id: uuid.UUID | None, alias: str = "jl") -> tuple[str, dict]:
    sql, params = "", {}
    if project_id is not None:
        sql += f" AND {alias}.project_id = :p"
        params["p"] = project_id
    if site_id is not None:
        sql += f" AND {alias}.site_id = :s"
        params["s"] = site_id
    return sql, params


def trial_rows(raw: list[dict[str, Any]], ledgers: dict, groups: dict, scoped: bool) -> dict[str, Any]:
    """Rows and totals from per-ledger sums (pure, for tests). ``raw``: ledger_id, nature, opening (balance-sheet
    ledgers: all before the period; P&L ledgers: from the year's start), earlier (P&L ledgers before the year),
    debit, credit."""
    rows, earlier = [], _ZERO
    for r in raw:
        earlier += Decimal(r["earlier"] or 0)
        opening, dr, cr = Decimal(r["opening"] or 0), Decimal(r["debit"] or 0), Decimal(r["credit"] or 0)
        if not (opening or dr or cr):
            continue
        led = ledgers[r["ledger_id"]]
        rows.append({"ledger_id": str(r["ledger_id"]), "name": led["name"], "group_id": str(led["group_id"]),
                     "nature": led["nature"], "code": led["code"], "link_kind": led["link_kind"],
                     "link_id": str(led["link_id"]) if led["link_id"] else None,
                     "opening": opening, "debit": dr, "credit": cr, "closing": opening + dr - cr})
    reserves = next((g for g in groups.values() if g["code"] == "reserves"), None)
    if earlier and reserves:
        rows.append({"ledger_id": None, "name": "Profit or loss of earlier years", "group_id": str(reserves["id"]),
                     "nature": "equity", "code": EARLIER_PL, "link_kind": None, "link_id": None,
                     "opening": earlier, "debit": _ZERO, "credit": _ZERO, "closing": earlier})
    gap_open = -sum((r["opening"] for r in rows), _ZERO)
    gap_dr = sum((r["credit"] for r in rows), _ZERO) - sum((r["debit"] for r in rows), _ZERO)
    liabilities = next((g for g in groups.values() if g["code"] == "current_liabilities"), None)
    if scoped and (gap_open or gap_dr) and liabilities:
        rows.append({"ledger_id": None, "name": "Head office and other projects", "group_id": str(liabilities["id"]),
                     "nature": "liability", "code": HEAD_OFFICE, "link_kind": None, "link_id": None,
                     "opening": gap_open, "debit": max(gap_dr, _ZERO), "credit": max(-gap_dr, _ZERO),
                     "closing": gap_open + gap_dr})
    rows.sort(key=lambda r: r["name"].lower())

    def side(values, positive: bool) -> Decimal:
        return sum((v for v in values if (v > 0) == positive and v), _ZERO)

    totals = {
        "opening_debit": side([r["opening"] for r in rows], True), "opening_credit": -side([r["opening"] for r in rows], False),
        "debit": sum((r["debit"] for r in rows), _ZERO), "credit": sum((r["credit"] for r in rows), _ZERO),
        "closing_debit": side([r["closing"] for r in rows], True), "closing_credit": -side([r["closing"] for r in rows], False),
    }
    totals["balanced"] = totals["closing_debit"] == totals["closing_credit"] and totals["debit"] == totals["credit"]
    return {"rows": rows, "totals": totals}


async def trial_balance(conn: AsyncConnection, org: uuid.UUID, date_from: datetime.date, date_to: datetime.date,
                        project_id: uuid.UUID | None = None, site_id: uuid.UUID | None = None) -> dict[str, Any]:
    scope, params = _scope(project_id, site_id)
    raw = [dict(r) for r in (await conn.execute(text(
        "SELECT jl.ledger_id, g.nature, "
        "SUM(CASE WHEN jl.entry_date < :f AND (g.nature NOT IN ('income', 'expense') OR jl.entry_date >= :fy) "
        "    THEN jl.debit - jl.credit ELSE 0 END) AS opening, "
        "SUM(CASE WHEN jl.entry_date < :fy AND g.nature IN ('income', 'expense') THEN jl.debit - jl.credit ELSE 0 END) AS earlier, "
        "SUM(CASE WHEN jl.entry_date >= :f THEN jl.debit ELSE 0 END) AS debit, "
        "SUM(CASE WHEN jl.entry_date >= :f THEN jl.credit ELSE 0 END) AS credit "
        "FROM journal_lines jl JOIN ledgers l ON l.id = jl.ledger_id JOIN ledger_groups g ON g.id = l.group_id "
        "WHERE jl.organization_id = :org AND jl.entry_date <= :t" + scope + " GROUP BY jl.ledger_id, g.nature"),
        {"org": org, "f": date_from, "t": date_to, "fy": periods.fy_start(date_from), **params})).mappings()]
    groups = {g["id"]: g for g in await chart.groups(conn, org)}
    ledgers = {r["id"]: r for r in await chart.ledgers(conn, org)}
    out = trial_rows(raw, ledgers, groups, project_id is not None or site_id is not None)
    return {"groups": [{**g, "id": str(g["id"]), "parent_id": str(g["parent_id"]) if g["parent_id"] else None}
                       for g in groups.values()], **out}


def _source(r: dict[str, Any]) -> dict[str, Any]:
    """Where an entry came from, for the page to open it: the record kind and the ids it needs."""
    kind = r["source_kind"]
    out: dict[str, Any] = {"kind": kind, "id": str(r["source_id"]) if r["source_id"] else None}
    if kind == "money":
        out["money_source"] = r.get("money_source_type")
        if r.get("expense_id"):
            out["expense_id"] = str(r["expense_id"])
        if r.get("vendor_id"):
            out["vendor_id"] = str(r["vendor_id"])
        if r.get("money_source_type") == "client_receipt":
            out["receipt_id"] = str(r["money_source_id"])
    return out


async def entries(conn: AsyncConnection, org: uuid.UUID, *, date_from: datetime.date, date_to: datetime.date,
                  voucher_type: str | None = None, ledger_id: uuid.UUID | None = None,
                  project_id: uuid.UUID | None = None, site_id: uuid.UUID | None = None, q: str | None = None,
                  entry_id: uuid.UUID | None = None, after_close: bool = False, limit: int = 200,
                  offset: int = 0) -> dict[str, Any]:
    """The day book: entries in the period (newest day last, as a book reads), each with its lines and source."""
    where = ["j.organization_id = :org", "j.entry_date BETWEEN :f AND :t"]
    params: dict[str, Any] = {"org": org, "f": date_from, "t": date_to, "lim": limit, "off": offset}
    if entry_id is not None:
        where = ["j.organization_id = :org", "j.id = :id"]
        params["id"] = entry_id
    if voucher_type:
        where.append("j.voucher_type = :vt")
        params["vt"] = voucher_type
    if after_close:
        where.append("j.after_close")
    line_filter, lp = _scope(project_id, site_id, "x")
    if ledger_id is not None:
        line_filter += " AND x.ledger_id = :led"
        lp["led"] = ledger_id
    if line_filter:
        where.append("EXISTS (SELECT 1 FROM journal_lines x WHERE x.entry_id = j.id" + line_filter + ")")
        params.update(lp)
    if q and q.strip():
        where.append("(j.narration ILIKE :q OR EXISTS (SELECT 1 FROM journal_lines y JOIN ledgers yl ON yl.id = y.ledger_id "
                     "WHERE y.entry_id = j.id AND yl.name ILIKE :q) OR CAST(j.number AS text) = :qn)")
        params["q"] = f"%{q.strip()}%"
        params["qn"] = q.strip().lstrip("#")
    cond = " AND ".join(where)
    head = [dict(r) for r in (await conn.execute(text(
        "SELECT j.id, j.entry_date, j.voucher_type, j.financial_year, j.number, j.narration, j.source_kind, j.source_id, "
        "j.after_close, j.project_id, pr.name AS project, j.created_at, j.updated_at, "
        "m.source_type AS money_source_type, m.source_id AS money_source_id, "
        "COALESCE(ep.expense_id, CASE WHEN m.source_type = 'expense' THEN m.source_id END) AS expense_id, "
        "CASE WHEN ep.expense_id IS NULL THEN ep.vendor_id END AS vendor_id "
        "FROM journal_entries j LEFT JOIN projects pr ON pr.id = j.project_id "
        "LEFT JOIN money_transactions m ON j.source_kind = 'money' AND m.id = j.source_id "
        "LEFT JOIN expense_payments ep ON m.source_type = 'expense_payment' AND ep.id = m.source_id "
        f"WHERE {cond} ORDER BY j.entry_date, j.voucher_type, j.number LIMIT :lim OFFSET :off"),  # noqa: S608
        params)).mappings()]
    count, total = (await conn.execute(text(
        "SELECT COUNT(*), COALESCE(SUM((SELECT SUM(debit) FROM journal_lines z WHERE z.entry_id = j.id)), 0) "
        f"FROM journal_entries j WHERE {cond}"), params)).one()  # noqa: S608
    lines: dict[Any, list] = defaultdict(list)
    if head:
        for r in (await conn.execute(text(
                "SELECT jl.entry_id, jl.line_no, jl.ledger_id, l.name AS ledger, l.link_kind, l.link_id, jl.debit, "
                "jl.credit, jl.project_id, pr.name AS project, jl.site_id, s.name AS site, jl.cost_centre "
                "FROM journal_lines jl JOIN ledgers l ON l.id = jl.ledger_id LEFT JOIN projects pr ON pr.id = jl.project_id "
                "LEFT JOIN sites s ON s.id = jl.site_id WHERE jl.entry_id = ANY(:ids) ORDER BY jl.line_no"),
                {"ids": [h["id"] for h in head]})).mappings():
            lines[r["entry_id"]].append({
                "ledger_id": str(r["ledger_id"]), "ledger": r["ledger"], "link_kind": r["link_kind"],
                "link_id": str(r["link_id"]) if r["link_id"] else None, "debit": r["debit"], "credit": r["credit"],
                "project_id": str(r["project_id"]) if r["project_id"] else None, "project": r["project"],
                "site_id": str(r["site_id"]) if r["site_id"] else None, "site": r["site"], "cost_centre": r["cost_centre"]})
    return {
        "entries": [{
            "id": str(h["id"]), "date": h["entry_date"], "voucher_type": h["voucher_type"],
            "number": h["number"], "financial_year": h["financial_year"],
            "ref": f"{h['voucher_type'][:3].upper()}/{h['financial_year']}/{h['number']}",
            "narration": h["narration"], "after_close": h["after_close"], "project": h["project"],
            "project_id": str(h["project_id"]) if h["project_id"] else None, "source": _source(h),
            "amount": sum((ln["debit"] for ln in lines[h["id"]]), _ZERO), "lines": lines[h["id"]],
            "posted_at": h["updated_at"]} for h in head],
        "count": count, "total": Decimal(total), "limit": limit, "offset": offset,
    }


async def ledger_statement(conn: AsyncConnection, org: uuid.UUID, ledger_id: uuid.UUID, date_from: datetime.date,
                           date_to: datetime.date, project_id: uuid.UUID | None = None,
                           site_id: uuid.UUID | None = None) -> dict[str, Any] | None:
    """One ledger: opening, each line with what it was against and the running balance, closing."""
    led = (await conn.execute(text(
        "SELECT l.id, l.name, l.code, l.link_kind, l.link_id, l.notes, g.id AS group_id, g.name AS group_name, g.nature "
        "FROM ledgers l JOIN ledger_groups g ON g.id = l.group_id WHERE l.organization_id = :org AND l.id = :id"),
        {"org": org, "id": ledger_id})).mappings().first()
    if led is None:
        return None
    scope, params = _scope(project_id, site_id)
    pl = led["nature"] in chart.PL_NATURES
    start = max(periods.fy_start(date_from), datetime.date.min) if pl else None
    opening = Decimal((await conn.execute(text(
        "SELECT COALESCE(SUM(jl.debit - jl.credit), 0) FROM journal_lines jl WHERE jl.organization_id = :org "
        "AND jl.ledger_id = :id AND jl.entry_date < :f" + (" AND jl.entry_date >= :fy" if pl else "") + scope),
        {"org": org, "id": ledger_id, "f": date_from, **({"fy": start} if pl else {}), **params})).scalar())
    rows = [dict(r) for r in (await conn.execute(text(
        "SELECT jl.id, jl.entry_id, jl.entry_date, jl.debit, jl.credit, jl.cost_centre, pr.name AS project, s.name AS site, "
        "j.voucher_type, j.financial_year, j.number, j.narration, j.after_close, j.source_kind, j.source_id, "
        "(SELECT string_agg(DISTINCT ol.name, ', ') FROM journal_lines o JOIN ledgers ol ON ol.id = o.ledger_id "
        " WHERE o.entry_id = jl.entry_id AND o.ledger_id <> jl.ledger_id "
        " AND (o.debit > 0) = (jl.credit > 0)) AS against "
        "FROM journal_lines jl JOIN journal_entries j ON j.id = jl.entry_id LEFT JOIN projects pr ON pr.id = jl.project_id "
        "LEFT JOIN sites s ON s.id = jl.site_id WHERE jl.organization_id = :org AND jl.ledger_id = :id "
        "AND jl.entry_date BETWEEN :f AND :t" + scope + " ORDER BY jl.entry_date, j.voucher_type, j.number, jl.line_no"),
        {"org": org, "id": ledger_id, "f": date_from, "t": date_to, **params})).mappings()]
    balance = opening
    out = []
    for r in rows:
        balance += Decimal(r["debit"]) - Decimal(r["credit"])
        out.append({"line_id": str(r["id"]), "entry_id": str(r["entry_id"]), "date": r["entry_date"],
                    "ref": f"{r['voucher_type'][:3].upper()}/{r['financial_year']}/{r['number']}",
                    "voucher_type": r["voucher_type"], "narration": r["narration"], "against": r["against"],
                    "debit": r["debit"], "credit": r["credit"], "balance": balance, "project": r["project"],
                    "site": r["site"], "cost_centre": r["cost_centre"], "after_close": r["after_close"],
                    "source_kind": r["source_kind"]})
    debit = sum((Decimal(r["debit"]) for r in rows), _ZERO)
    credit = sum((Decimal(r["credit"]) for r in rows), _ZERO)
    return {"ledger": {**{k: v for k, v in led.items() if k not in ("id", "group_id", "link_id")},
                       "id": str(led["id"]), "group_id": str(led["group_id"]),
                       "link_id": str(led["link_id"]) if led["link_id"] else None},
            "opening": opening, "debit": debit, "credit": credit, "closing": opening + debit - credit,
            "lines": out, "year_start": start}


async def balances(conn: AsyncConnection, org: uuid.UUID, as_of: datetime.date) -> dict[uuid.UUID, Decimal]:
    """Each ledger's balance on a day (P&L ledgers from the year's start)."""
    return {r[0]: Decimal(r[1]) for r in (await conn.execute(text(
        "SELECT jl.ledger_id, SUM(jl.debit - jl.credit) FROM journal_lines jl JOIN ledgers l ON l.id = jl.ledger_id "
        "JOIN ledger_groups g ON g.id = l.group_id WHERE jl.organization_id = :org AND jl.entry_date <= :t "
        "AND (g.nature NOT IN ('income', 'expense') OR jl.entry_date >= :fy) GROUP BY jl.ledger_id"),
        {"org": org, "t": as_of, "fy": periods.fy_start(as_of)}))}


async def checks(conn: AsyncConnection, org: uuid.UUID, as_of: datetime.date) -> dict[str, Any]:
    """Do the books agree with the modules? Each money account against Finance › Money (opening + movements), each
    supplier against the supplier ledger (bills and payments; deliveries not billed are not in the books until the
    month-end accrual, ACC-15), and the client ledgers against Receivables."""
    from mesiri.domains.billing import receipts as receipt_store
    from mesiri.domains.vendors import ledger as vendor_ledger

    bal = await balances(conn, org, as_of)
    links = {(r["link_kind"], str(r["link_id"])): r for r in await chart.ledgers(conn, org) if r["link_kind"]}

    def book(kind: str, rid: Any) -> Decimal:
        led = links.get((kind, str(rid)))
        return bal.get(led["id"], _ZERO) if led else _ZERO

    accounts = []
    for a in (await conn.execute(text(
            "SELECT a.id, a.name, a.opening_balance + COALESCE((SELECT SUM(CASE WHEN m.to_account_id = a.id THEN m.amount "
            " ELSE -m.amount END) FROM money_transactions m WHERE (m.to_account_id = a.id OR m.from_account_id = a.id) "
            " AND m.occurred_date <= :t), 0) AS module FROM money_accounts a WHERE a.organization_id = :org "
            "ORDER BY a.name"), {"org": org, "t": as_of})).mappings():
        books = book("money_account", a["id"])
        accounts.append({"id": str(a["id"]), "name": a["name"], "module": Decimal(a["module"]), "books": books,
                         "difference": books - Decimal(a["module"])})

    entries_, state = await vendor_ledger.fetch_entries(conn, org, vendor_id=None, projects=None, until=as_of)
    owed: dict[str, Decimal] = defaultdict(Decimal)
    for e in entries_:
        if e["kind"] != "delivery":
            owed[str(e["vendor_id"])] += Decimal(e["owe"]) - Decimal(e["paid"])
    suppliers = []
    for vid, v in state["vendors"].items():
        books = -book("vendor", vid)  # a credit balance is what we owe
        module = owed.get(str(vid), _ZERO)
        if books or module:
            suppliers.append({"id": str(vid), "name": v["name"], "module": module, "books": books,
                              "difference": books - module})

    settled = await receipt_store.owed(conn, org, None, as_of)
    clients = []
    no_client = next((r for r in await chart.ledgers(conn, org) if r["code"] == "no_client"), None)
    for c in settled["clients"]:
        cid = c.get("client_id")
        books = book("client", cid) if cid else (bal.get(no_client["id"], _ZERO) if no_client else _ZERO)
        module = Decimal(str(c.get("outstanding") or 0)) - Decimal(str(c.get("unapplied") or 0))
        clients.append({"id": str(cid) if cid else None, "name": c.get("client") or c.get("name") or "Client",
                        "module": module, "books": books, "difference": books - module})

    def summary(rows):
        off = [r for r in rows if r["difference"]]
        return {"rows": rows, "agree": len(rows) - len(off), "differ": len(off)}

    return {"as_of": as_of, "accounts": summary(accounts), "suppliers": summary(suppliers),
            "clients": summary(clients)}
