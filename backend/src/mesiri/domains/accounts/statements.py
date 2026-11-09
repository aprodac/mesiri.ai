"""Phase B (ACC-06..09, ACC-22): the statements, all read from the journal lines, never a second calculation.

- **P&L** (ACC-06): income and costs by the chart's top groups, Tally's layout: Sales and direct income, less
  purchases and direct expenses, is the **gross profit**; plus indirect income, less indirect expenses, the **net
  profit**. For the company, a project or a site (the lines' project and site). A project's head-office share
  (ACC-23, when switched on) is shown apart, so its profit is read before and after overheads.
- **Balance sheet** (ACC-06): on a day, what the company owns (assets) against what it owes and its capital, the
  year's profit and earlier years' added to capital. Company only: a project has no balance sheet, it has a
  **project position**.
- **Cash and bank** (ACC-07): each cash box and bank account, opening, in, out, closing, and the days.
- **Project position** (ACC-08, plan §5.8): what the project billed, received, is owed (and held back as retention
  and TDS by the client), advances, what it owes suppliers, what it cost, from its own lines.
- **Accounts home** (ACC-09): the figures the owner looks at, company-wide or for one project.

Signs: a natural amount is positive (income as earned, an expense as spent, an asset held, a liability owed).
"""

from __future__ import annotations

import datetime
import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.domains.accounts import chart, periods

_ZERO = Decimal(0)
#: Where each top group sits in the P&L (custom groups follow their top group).
PL_SECTION = {"sales": "income", "direct_income": "income", "purchases": "direct", "direct_expenses": "direct",
              "indirect_income": "other_income", "indirect_expenses": "indirect"}
OVERHEADS = "overheads_allocated"


def pct(part: Decimal, whole: Decimal) -> Decimal | None:
    return (part * 100 / whole).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP) if whole else None


def _roots(groups: list[dict[str, Any]]) -> dict[Any, dict[str, Any]]:
    """Each group's top group (the one with no parent)."""
    by = {g["id"]: g for g in groups}

    def top(g):
        seen = 0
        while g["parent_id"] and g["parent_id"] in by and seen < 20:
            g = by[g["parent_id"]]
            seen += 1
        return g
    return {gid: top(g) for gid, g in by.items()}


def _scope(project_id: uuid.UUID | None, site_id: uuid.UUID | None) -> tuple[str, dict]:
    sql, params = "", {}
    if project_id is not None:
        sql += " AND jl.project_id = :p"
        params["p"] = project_id
    if site_id is not None:
        sql += " AND jl.site_id = :s"
        params["s"] = site_id
    return sql, params


async def _sums(conn: AsyncConnection, org: uuid.UUID, date_from: datetime.date, date_to: datetime.date,
                project_id=None, site_id=None) -> dict[Any, Decimal]:
    """Debit − credit per ledger over a period."""
    scope, params = _scope(project_id, site_id)
    return {r[0]: Decimal(r[1]) for r in (await conn.execute(text(
        "SELECT jl.ledger_id, SUM(jl.debit - jl.credit) FROM journal_lines jl WHERE jl.organization_id = :org "
        "AND jl.entry_date BETWEEN :f AND :t" + scope + " GROUP BY jl.ledger_id"),
        {"org": org, "f": date_from, "t": date_to, **params}))}


def pl_layout(sums: dict[Any, Decimal], ledgers: dict[Any, dict], groups: list[dict], prior: dict[Any, Decimal] | None
              ) -> dict[str, Any]:
    """The P&L from per-ledger sums (pure, for tests)."""
    roots = _roots(groups)
    by_id = {g["id"]: g for g in groups}
    sections: dict[str, dict[Any, dict]] = {k: {} for k in ("income", "direct", "other_income", "indirect")}
    overheads = _ZERO
    for lid in set(sums) | set(prior or {}):
        led = ledgers.get(lid)
        if led is None or led["nature"] not in chart.PL_NATURES:
            continue
        top = roots.get(led["group_id"])
        section = PL_SECTION.get(top["code"] if top else None) or ("income" if led["nature"] == "income" else "indirect")
        sign = -1 if led["nature"] == "income" else 1
        amount = sign * sums.get(lid, _ZERO)
        before = sign * (prior or {}).get(lid, _ZERO) if prior is not None else None
        if led["code"] == OVERHEADS:
            overheads += amount
        if not amount and not before:
            continue
        group = by_id.get(led["group_id"], {"id": None, "name": "Other"})
        g = sections[section].setdefault(group["id"], {"group_id": str(group["id"]) if group["id"] else None,
                                                        "name": group["name"], "amount": _ZERO,
                                                        "prior": _ZERO if prior is not None else None, "ledgers": []})
        g["amount"] += amount
        if prior is not None:
            g["prior"] += before
        g["ledgers"].append({"ledger_id": str(lid), "name": led["name"], "amount": amount, "prior": before,
                             "is_overheads": led["code"] == OVERHEADS})

    def total(key: str, field: str = "amount") -> Decimal | None:
        if field == "prior" and prior is None:
            return None
        return sum((g[field] for g in sections[key].values()), _ZERO)

    def figures(field: str):
        if field == "prior" and prior is None:
            return None
        income, direct = total("income", field), total("direct", field)
        gross = income - direct
        net = gross + total("other_income", field) - total("indirect", field)
        return {"income": income, "direct": direct, "gross_profit": gross, "other_income": total("other_income", field),
                "indirect": total("indirect", field), "net_profit": net,
                "gross_margin": pct(gross, income), "net_margin": pct(net, income)}

    out = {k: sorted(v.values(), key=lambda g: -abs(g["amount"])) for k, v in sections.items()}
    for groups_ in out.values():
        for g in groups_:
            g["ledgers"].sort(key=lambda x: -abs(x["amount"]))
    now = figures("amount")
    return {"sections": out, "totals": now, "prior_totals": figures("prior"), "overheads": overheads,
            "net_before_overheads": now["net_profit"] + overheads}


async def profit_and_loss(conn: AsyncConnection, org: uuid.UUID, date_from: datetime.date, date_to: datetime.date,
                          project_id=None, site_id=None, compare: str | None = None) -> dict[str, Any]:
    groups = await chart.groups(conn, org)
    ledgers = {r["id"]: r for r in await chart.ledgers(conn, org)}
    sums = await _sums(conn, org, date_from, date_to, project_id, site_id)
    prior, prior_period = None, None
    if compare == "previous":
        days = (date_to - date_from).days + 1
        prior_period = (date_from - datetime.timedelta(days=days), date_from - datetime.timedelta(days=1))
    elif compare == "last_year":
        prior_period = (date_from.replace(year=date_from.year - 1) if not (date_from.month == 2 and date_from.day == 29)
                        else date_from.replace(year=date_from.year - 1, day=28),
                        date_to.replace(year=date_to.year - 1) if not (date_to.month == 2 and date_to.day == 29)
                        else date_to.replace(year=date_to.year - 1, day=28))
    if prior_period:
        prior = await _sums(conn, org, prior_period[0], prior_period[1], project_id, site_id)
    out = pl_layout(sums, ledgers, groups, prior)
    out["compare"] = {"kind": compare, "date_from": prior_period[0], "date_to": prior_period[1]} if prior_period else None
    return out


async def monthly(conn: AsyncConnection, org: uuid.UUID, date_from: datetime.date, date_to: datetime.date,
                  project_id=None, site_id=None) -> list[dict[str, Any]]:
    """Income, costs and profit per month (for the home's chart)."""
    scope, params = _scope(project_id, site_id)
    rows = (await conn.execute(text(
        "SELECT date_trunc('month', jl.entry_date)::date AS m, "
        "SUM(CASE WHEN g.nature = 'income' THEN jl.credit - jl.debit ELSE 0 END) AS income, "
        "SUM(CASE WHEN g.nature = 'expense' THEN jl.debit - jl.credit ELSE 0 END) AS cost "
        "FROM journal_lines jl JOIN ledgers l ON l.id = jl.ledger_id JOIN ledger_groups g ON g.id = l.group_id "
        "WHERE jl.organization_id = :org AND jl.entry_date BETWEEN :f AND :t" + scope + " GROUP BY 1 ORDER BY 1"),
        {"org": org, "f": date_from, "t": date_to, **params})).mappings().all()
    have = {r["m"]: r for r in rows}
    out, m = [], date_from.replace(day=1)
    while m <= date_to:
        r = have.get(m)
        income, cost = Decimal(r["income"]) if r else _ZERO, Decimal(r["cost"]) if r else _ZERO
        out.append({"month": m.strftime("%Y-%m"), "income": income, "cost": cost, "profit": income - cost})
        m = (m.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    return out


async def balances_on(conn: AsyncConnection, org: uuid.UUID, as_of: datetime.date, project_id=None) -> dict[Any, Decimal]:
    """Every ledger's balance (debit − credit) on a day, all history (P&L ledgers too)."""
    scope, params = _scope(project_id, None)
    return {r[0]: Decimal(r[1]) for r in (await conn.execute(text(
        "SELECT jl.ledger_id, SUM(jl.debit - jl.credit) FROM journal_lines jl WHERE jl.organization_id = :org "
        "AND jl.entry_date <= :t" + scope + " GROUP BY jl.ledger_id"), {"org": org, "t": as_of, **params}))}


def bs_layout(all_time: dict[Any, Decimal], before_year: dict[Any, Decimal], ledgers: dict[Any, dict],
              groups: list[dict]) -> dict[str, Any]:
    """The balance sheet from balances (pure, for tests). ``all_time``: balances on the day; ``before_year``:
    balances on the day before the year started (for earlier years' profit)."""
    roots = _roots(groups)
    by_id = {g["id"]: g for g in groups}
    sides: dict[str, dict[Any, dict]] = {"liabilities": {}, "assets": {}}
    year_profit, earlier = _ZERO, _ZERO
    for lid, bal in all_time.items():
        led = ledgers.get(lid)
        if led is None:
            continue
        if led["nature"] in chart.PL_NATURES:
            earlier_part = before_year.get(lid, _ZERO)
            earlier -= earlier_part
            year_profit -= bal - earlier_part
            continue
        if not bal:
            continue
        top = roots.get(led["group_id"]) or by_id.get(led["group_id"])
        side = "assets" if top["nature"] == "asset" else "liabilities"
        amount = bal if side == "assets" else -bal
        g = sides[side].setdefault(top["id"], {"group_id": str(top["id"]), "name": top["name"], "code": top["code"],
                                               "nature": top["nature"], "amount": _ZERO, "sort": top.get("sort", 0),
                                               "subgroups": {}})
        g["amount"] += amount
        sub = by_id.get(led["group_id"])
        sg = g["subgroups"].setdefault(sub["id"], {"group_id": str(sub["id"]), "name": sub["name"], "amount": _ZERO,
                                                   "ledgers": []})
        sg["amount"] += amount
        sg["ledgers"].append({"ledger_id": str(lid), "name": led["name"], "amount": amount})
    capital = next((g for g in sides["liabilities"].values() if g["code"] == "capital"), None)
    cap_group = next((g for g in groups if g["code"] == "capital"), None)
    if capital is None and cap_group is not None and (year_profit or earlier):
        capital = sides["liabilities"].setdefault(cap_group["id"], {
            "group_id": str(cap_group["id"]), "name": cap_group["name"], "code": "capital", "nature": "equity",
            "amount": _ZERO, "sort": cap_group.get("sort", 0), "subgroups": {}})
    if capital is not None:
        for key, name, amount in (("earlier_pl", "Profit or loss of earlier years", earlier),
                                  ("year_pl", "Profit or loss this year", year_profit)):
            if amount:
                capital["amount"] += amount
                capital["subgroups"][key] = {"group_id": None, "name": name, "amount": amount, "ledgers": []}
    out = {}
    for side, gs in sides.items():
        rows = sorted(gs.values(), key=lambda g: g["sort"])
        for g in rows:
            g["subgroups"] = sorted(g["subgroups"].values(), key=lambda s: -abs(s["amount"]))
            for s in g["subgroups"]:
                s["ledgers"].sort(key=lambda x: -abs(x["amount"]))
            g.pop("sort", None)
        out[side] = rows
    assets = sum((g["amount"] for g in out["assets"]), _ZERO)
    liabilities = sum((g["amount"] for g in out["liabilities"]), _ZERO)
    return {**out, "total_assets": assets, "total_liabilities": liabilities, "balanced": assets == liabilities,
            "year_profit": year_profit, "earlier_profit": earlier}


async def balance_sheet(conn: AsyncConnection, org: uuid.UUID, as_of: datetime.date) -> dict[str, Any]:
    groups = await chart.groups(conn, org)
    ledgers = {r["id"]: r for r in await chart.ledgers(conn, org)}
    start = periods.fy_start(as_of)
    out = bs_layout(await balances_on(conn, org, as_of), await balances_on(conn, org, start - datetime.timedelta(days=1)),
                    ledgers, groups)
    return {**out, "as_of": as_of, "year_start": start}


async def cash_bank(conn: AsyncConnection, org: uuid.UUID, date_from: datetime.date, date_to: datetime.date,
                    project_id=None, site_id=None) -> dict[str, Any]:
    """Each cash box and bank account (linked money-account ledgers held as assets): opening, in, out, closing;
    and every day's money in and out."""
    scope, params = _scope(project_id, site_id)
    rows = (await conn.execute(text(
        "SELECT l.id, l.name, l.link_id, g.name AS group_name, "
        "SUM(CASE WHEN jl.entry_date < :f THEN jl.debit - jl.credit ELSE 0 END) AS opening, "
        "SUM(CASE WHEN jl.entry_date >= :f THEN jl.debit ELSE 0 END) AS money_in, "
        "SUM(CASE WHEN jl.entry_date >= :f THEN jl.credit ELSE 0 END) AS money_out, "
        "COUNT(*) FILTER (WHERE jl.entry_date >= :f) AS lines "
        "FROM journal_lines jl JOIN ledgers l ON l.id = jl.ledger_id JOIN ledger_groups g ON g.id = l.group_id "
        "WHERE jl.organization_id = :org AND jl.entry_date <= :t AND l.link_kind = 'money_account' "
        "AND g.nature = 'asset'" + scope + " GROUP BY l.id, l.name, l.link_id, g.name ORDER BY l.name"),
        {"org": org, "f": date_from, "t": date_to, **params})).mappings().all()
    accounts = [{"ledger_id": str(r["id"]), "name": r["name"], "account_id": str(r["link_id"]), "group": r["group_name"],
                 "opening": Decimal(r["opening"]), "in": Decimal(r["money_in"]), "out": Decimal(r["money_out"]),
                 "closing": Decimal(r["opening"]) + Decimal(r["money_in"]) - Decimal(r["money_out"]),
                 "lines": r["lines"]} for r in rows]
    days = [{"date": r["d"], "in": Decimal(r["i"]), "out": Decimal(r["o"])} for r in (await conn.execute(text(
        "SELECT jl.entry_date AS d, SUM(jl.debit) AS i, SUM(jl.credit) AS o FROM journal_lines jl "
        "JOIN ledgers l ON l.id = jl.ledger_id JOIN ledger_groups g ON g.id = l.group_id "
        "JOIN journal_entries j ON j.id = jl.entry_id "
        "WHERE jl.organization_id = :org AND jl.entry_date BETWEEN :f AND :t AND l.link_kind = 'money_account' "
        "AND g.nature = 'asset' AND j.voucher_type <> 'contra'" + scope + " GROUP BY 1 ORDER BY 1"),
        {"org": org, "f": date_from, "t": date_to, **params})).mappings()]
    total = {k: sum((a[k] for a in accounts), _ZERO) for k in ("opening", "in", "out", "closing")}
    return {"accounts": accounts, "days": days, "total": total}


async def position(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID, as_of: datetime.date) -> dict[str, Any]:
    """A project's position on a day, from its own lines (plan §5.8)."""
    ledgers = {r["id"]: r for r in await chart.ledgers(conn, org)}
    bal = await balances_on(conn, org, as_of, project_id)

    def by(pred) -> Decimal:
        return sum((v for lid, v in bal.items() if lid in ledgers and pred(ledgers[lid])), _ZERO)

    flows = (await conn.execute(text(
        "SELECT COALESCE(SUM(CASE WHEN j.voucher_type = 'receipt' THEN jl.debit ELSE 0 END), 0), "
        "COALESCE(SUM(CASE WHEN j.voucher_type = 'payment' THEN jl.credit ELSE 0 END), 0) "
        "FROM journal_lines jl JOIN journal_entries j ON j.id = jl.entry_id JOIN ledgers l ON l.id = jl.ledger_id "
        "WHERE jl.organization_id = :org AND jl.project_id = :p AND jl.entry_date <= :t AND l.link_kind = 'money_account'"),
        {"org": org, "p": project_id, "t": as_of})).one()
    billed = -by(lambda r: r["code"] == "contract_revenue")
    cost = by(lambda r: r["nature"] == "expense" and r["code"] != OVERHEADS)
    overheads = by(lambda r: r["code"] == OVERHEADS)
    return {
        "as_of": as_of,
        "billed": billed,
        "gst_billed": -by(lambda r: r["code"] == "output_gst"),
        "receivable": by(lambda r: r["link_kind"] == "client" or r["code"] == "no_client"),
        "retention_held_by_client": by(lambda r: r["code"] == "retention_receivable"),
        "tds_deducted_by_client": by(lambda r: r["code"] == "tds_receivable"),
        "advance_received": -by(lambda r: r["code"] == "advance_received"),
        "received": Decimal(flows[0]),
        "paid_out": Decimal(flows[1]),
        "owed_to_suppliers": -by(lambda r: r["link_kind"] == "vendor"),
        "owed_to_staff": -by(lambda r: r["link_kind"] == "staff" or r["code"] == "expenses_payable"),
        "cost": cost,
        "overheads": overheads,
        "profit": billed - cost - overheads,
        "margin": pct(billed - cost - overheads, billed),
        "cash_in_hand": Decimal(flows[0]) - Decimal(flows[1]),
    }


async def projects_table(conn: AsyncConnection, org: uuid.UUID, date_from: datetime.date, date_to: datetime.date,
                         project_ids: set | None) -> list[dict[str, Any]]:
    """Every project's P&L in the period and what it is owed and owes today: the "which site makes money" list."""
    rows = (await conn.execute(text(
        "SELECT p.id, p.name, "
        "COALESCE(SUM(CASE WHEN l.code = 'contract_revenue' AND jl.entry_date BETWEEN :f AND :t THEN jl.credit - jl.debit END), 0) AS billed, "
        "COALESCE(SUM(CASE WHEN g.nature = 'expense' AND COALESCE(l.code, '') <> :oh AND jl.entry_date BETWEEN :f AND :t "
        "    THEN jl.debit - jl.credit END), 0) AS cost, "
        "COALESCE(SUM(CASE WHEN l.code = :oh AND jl.entry_date BETWEEN :f AND :t THEN jl.debit - jl.credit END), 0) AS overheads, "
        "COALESCE(SUM(CASE WHEN (l.link_kind = 'client' OR l.code = 'no_client') AND jl.entry_date <= :t "
        "    THEN jl.debit - jl.credit END), 0) AS receivable, "
        "COALESCE(SUM(CASE WHEN l.link_kind = 'vendor' AND jl.entry_date <= :t THEN jl.credit - jl.debit END), 0) AS payable "
        "FROM projects p JOIN journal_lines jl ON jl.project_id = p.id AND jl.organization_id = p.organization_id "
        "JOIN ledgers l ON l.id = jl.ledger_id JOIN ledger_groups g ON g.id = l.group_id "
        "WHERE p.organization_id = :org AND (CAST(:all AS boolean) OR p.id = ANY(:ids)) "
        "GROUP BY p.id, p.name ORDER BY p.name"),
        {"org": org, "f": date_from, "t": date_to, "oh": OVERHEADS, "all": project_ids is None,
         "ids": list(project_ids or [])})).mappings().all()
    out = []
    for r in rows:
        billed, cost, oh = Decimal(r["billed"]), Decimal(r["cost"]), Decimal(r["overheads"])
        profit = billed - cost - oh
        out.append({"project_id": str(r["id"]), "name": r["name"], "billed": billed, "cost": cost, "overheads": oh,
                    "profit": profit, "margin": pct(profit, billed), "receivable": Decimal(r["receivable"]),
                    "payable": Decimal(r["payable"])})
    return sorted(out, key=lambda r: -r["profit"])


async def gst_for(conn: AsyncConnection, org: uuid.UUID, date_from: datetime.date, date_to: datetime.date) -> dict:
    """Output GST, input GST claimable and the net payable for a period (the summary; registers are ACC-10)."""
    row = (await conn.execute(text(
        "SELECT COALESCE(SUM(CASE WHEN l.code = 'output_gst' THEN jl.credit - jl.debit END), 0), "
        "COALESCE(SUM(CASE WHEN l.code = 'input_gst' THEN jl.debit - jl.credit END), 0) "
        "FROM journal_lines jl JOIN ledgers l ON l.id = jl.ledger_id WHERE jl.organization_id = :org "
        "AND jl.entry_date BETWEEN :f AND :t"), {"org": org, "f": date_from, "t": date_to})).one()
    out_, in_ = Decimal(row[0]), Decimal(row[1])
    return {"output": out_, "input": in_, "payable": out_ - in_}


async def attention(conn: AsyncConnection, org: uuid.UUID, today: datetime.date) -> list[dict[str, Any]]:
    """What needs the accountant: balances waiting to be classified, money from clients not on a client, changes
    after close this year."""
    ledgers = {r["id"]: r for r in await chart.ledgers(conn, org)}
    bal = await balances_on(conn, org, today)
    out = []
    for key, words, to in (("opening_difference", "Opening balance difference is not nil: the opening balances do not match each other yet.", "/accounts/ledgers"),
                           ("balance_adjustments", "Money balance adjustments to classify.", "/accounts/ledgers"),
                           ("no_client", "Bills or money with no client set on their project.", "/billing/clients")):
        lid = next((i for i, r in ledgers.items() if r["code"] == key), None)
        if lid and bal.get(lid):
            out.append({"key": key, "words": words, "amount": abs(bal[lid]), "ledger_id": str(lid), "to": to})
    late = (await conn.execute(text(
        "SELECT COUNT(*) FROM journal_entries WHERE organization_id = :org AND after_close AND entry_date >= :fy"),
        {"org": org, "fy": periods.fy_start(today)})).scalar()
    if late:
        out.append({"key": "after_close", "words": f"{late} change{'s' if late != 1 else ''} to closed months this year.",
                    "amount": None, "ledger_id": None, "to": "/accounts/day-book?late=1"})
    return out
