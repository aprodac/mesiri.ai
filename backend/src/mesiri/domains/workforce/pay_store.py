"""Wages and advances: reads and writes (LW-03..LW-05). The rules are ``pay.py``; this file only moves rows.

Money leaves an account through the one money path (``money_transactions``, as a client receipt arrives through it):
an advance is an ``expense_payment`` with ``source_type`` ``labour_advance``; a wage payment one with ``wage_payment``;
taking either back is a ``reversal`` with the same source. The accounts sweep posts them (``accounts/sweep.py``).
Days always come from attendance, through the same counting rule as the labour cost (``counted_line_sql``).
"""

from __future__ import annotations

import datetime
import json
import uuid
from collections import defaultdict
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.domains.workforce import pay
from mesiri.infrastructure.postgres.repositories.workforce import counted_line_sql

ADVANCE_SOURCE = "labour_advance"
PAYMENT_SOURCE = "wage_payment"
_NO_SITE = uuid.UUID(int=0)


async def _rows(conn: AsyncConnection, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(r) for r in (await conn.execute(text(sql), params)).mappings()]


async def _record_money(conn: AsyncConnection, org: uuid.UUID, kind: str, amount: Decimal, day: datetime.date,
                        user_id: uuid.UUID, account_id: uuid.UUID | None, source: str, source_id: uuid.UUID,
                        words: str) -> None:
    if account_id is None:
        return
    from mesiri.infrastructure.postgres.repositories.finance import (
        PostgresMoneyTransactionRepository,
    )

    await PostgresMoneyTransactionRepository(conn).record(
        organization_id=org, transaction_type=kind, amount=amount, occurred_date=day, created_by=user_id,
        from_account_id=account_id if kind == "expense_payment" else None,
        to_account_id=account_id if kind == "reversal" else None,
        source_type=source, source_id=source_id, description=words)


# -- who ---------------------------------------------------------------------------------------------------------------

async def worker_team(conn: AsyncConnection, org: uuid.UUID) -> dict[str, Any]:
    """Worker id -> its team's vendor id (D-W2: a team member is paid through the contractor)."""
    return {str(r["id"]): r["vendor_id"] for r in await _rows(conn,
            "SELECT id, vendor_id FROM workforce_workers WHERE organization_id = :org AND vendor_id IS NOT NULL",
            {"org": org})}


async def teams(conn: AsyncConnection, org: uuid.UUID) -> dict[str, Any]:
    """Labour contractors by id and by their name in words (``pay.team_of``)."""
    rows = await _rows(conn, "SELECT id, name FROM vendors WHERE organization_id = :org AND kind = 'labour'", {"org": org})
    return {"by_id": {str(r["id"]): r["name"] for r in rows},
            "by_name": {" ".join(r["name"].lower().split()): r["id"] for r in rows}}


async def payee_names(conn: AsyncConnection, org: uuid.UUID) -> tuple[dict[str, str], dict[str, str]]:
    workers = {str(r["id"]): r["name"] for r in await _rows(conn,
               "SELECT id, name FROM workforce_workers WHERE organization_id = :org", {"org": org})}
    vendors = {str(r["id"]): r["name"] for r in await _rows(conn,
               "SELECT id, name FROM vendors WHERE organization_id = :org", {"org": org})}
    return workers, vendors


# -- attendance --------------------------------------------------------------------------------------------------------

async def attendance_lines(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID, site_id: uuid.UUID | None,
                           date_from: datetime.date, date_to: datetime.date) -> list[dict[str, Any]]:
    return await _rows(conn,
        "SELECT r.occurred_date AS date, r.site_id, l.worker_id, l.worker_name, l.trade, l.headcount, l.daily_wage, "
        "l.contractor, l.vendor_id, v.name AS vendor_name, l.attendance_status, l.overtime_hours "
        "FROM labour_attendance_lines l JOIN labour_attendance_reports r ON r.id = l.report_id "
        "LEFT JOIN vendors v ON v.id = l.vendor_id "
        "WHERE r.organization_id = :org AND r.project_id = :p AND r.occurred_date BETWEEN :f AND :t "
        + ("AND r.site_id = :s " if site_id else "")
        + f"AND {counted_line_sql('l', 'r')} ORDER BY r.occurred_date",
        {"org": org, "p": project_id, "f": date_from, "t": date_to, **({"s": site_id} if site_id else {})})


# -- advances ----------------------------------------------------------------------------------------------------------

_ADVANCE_SELECT = (
    "SELECT a.id, a.project_id, p.name AS project_name, a.site_id, s.name AS site_name, a.worker_id, a.vendor_id, "
    "a.payee_name, a.amount, a.given_on, a.account_id, m.name AS account_name, a.note, a.source, a.created_by, "
    "u.full_name AS created_by_name, a.created_at, a.voided_at, a.void_reason "
    "FROM labour_advances a JOIN projects p ON p.id = a.project_id LEFT JOIN sites s ON s.id = a.site_id "
    "LEFT JOIN money_accounts m ON m.id = a.account_id LEFT JOIN users u ON u.id = a.created_by "
    "WHERE a.organization_id = :org")


def advance_key(a: dict[str, Any], team: dict[str, Any], teams_: dict[str, Any] | None = None) -> str:
    """The payee an advance is recovered from: the same key a wage-sheet row has (a team member's goes to the team)."""
    return pay.payee_of({"worker_id": a.get("worker_id"), "vendor_id": a.get("vendor_id"),
                         "worker_name": a.get("payee_name"), "contractor": None}, team, teams_)[0]


async def list_advances(conn: AsyncConnection, org: uuid.UUID, project_ids: set | None,
                        project_id: uuid.UUID | None = None, site_id: uuid.UUID | None = None) -> list[dict[str, Any]]:
    sql, params = _ADVANCE_SELECT, {"org": org}
    if project_ids is not None:
        sql += " AND a.project_id = ANY(:projects)"
        params["projects"] = list(project_ids)
    if project_id:
        sql += " AND a.project_id = :p"
        params["p"] = project_id
    if site_id:
        sql += " AND a.site_id = :s"
        params["s"] = site_id
    return await _rows(conn, sql + " ORDER BY a.given_on DESC, a.created_at DESC", params)


async def get_advance(conn: AsyncConnection, org: uuid.UUID, advance_id: uuid.UUID) -> dict[str, Any] | None:
    rows = await _rows(conn, _ADVANCE_SELECT + " AND a.id = :id", {"org": org, "id": advance_id})
    return rows[0] if rows else None


async def give_advance(conn: AsyncConnection, org: uuid.UUID, values: dict[str, Any], user_id: uuid.UUID) -> uuid.UUID:
    advance_id = (await conn.execute(text(
        "INSERT INTO labour_advances (organization_id, project_id, site_id, worker_id, vendor_id, payee_name, amount, "
        "given_on, account_id, note, source, created_by) VALUES (:org, :project_id, :site_id, :worker_id, :vendor_id, "
        ":payee_name, :amount, :given_on, :account_id, :note, :source, :by) RETURNING id"),
        {"org": org, "by": user_id, **values})).scalar_one()
    await _record_money(conn, org, "expense_payment", Decimal(values["amount"]), values["given_on"], user_id,
                        values.get("account_id"), ADVANCE_SOURCE, advance_id, f"Advance to {values['payee_name']}")
    return advance_id


async def void_advance(conn: AsyncConnection, org: uuid.UUID, advance_id: uuid.UUID, user_id: uuid.UUID,
                       reason: str | None) -> bool:
    row = (await conn.execute(text(
        "UPDATE labour_advances SET voided_at = now(), voided_by = :u, void_reason = :why "
        "WHERE id = :id AND organization_id = :org AND voided_at IS NULL RETURNING amount, account_id, payee_name"),
        {"id": advance_id, "org": org, "u": user_id, "why": reason})).mappings().first()
    if row is None:
        return False
    await _record_money(conn, org, "reversal", Decimal(row["amount"]), datetime.date.today(), user_id,
                        row["account_id"], ADVANCE_SOURCE, advance_id, f"Advance to {row['payee_name']} taken back")
    return True


async def advance_balances(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID | None = None,
                           exclude_sheet: uuid.UUID | None = None, until: datetime.date | None = None,
                           project_ids: set | None = None) -> dict[str, Decimal]:
    """Payee key -> advances given (to ``until``) less recovered on sheets (other than ``exclude_sheet``), within one
    project or the projects in ``project_ids`` (None: all)."""
    team = await worker_team(conn, org)
    named = await teams(conn, org)
    given: dict[str, Decimal] = defaultdict(Decimal)
    for a in await list_advances(conn, org, project_ids, project_id):
        if a["voided_at"] is None and (until is None or a["given_on"] <= until):
            given[advance_key(a, team, named)] += Decimal(a["amount"])
    rec = await _rows(conn,
        "SELECT r.payee_key, SUM(r.advances_recovered) AS amount FROM wage_sheet_rows r JOIN wage_sheets w ON w.id = r.sheet_id "
        "WHERE w.organization_id = :org AND w.status = 'approved'"
        + (" AND w.project_id = :p" if project_id else "") + (" AND w.id <> :x" if exclude_sheet else "")
        + (" AND w.project_id = ANY(:projects)" if project_ids is not None else "") + " GROUP BY r.payee_key",
        {"org": org, **({"p": project_id} if project_id else {}), **({"x": exclude_sheet} if exclude_sheet else {}),
         **({"projects": list(project_ids)} if project_ids is not None else {})})
    for r in rec:
        given[r["payee_key"]] -= Decimal(r["amount"] or 0)
    return {k: pay.money(v) for k, v in given.items()}


# -- wage sheets -------------------------------------------------------------------------------------------------------

_SHEET_SELECT = (
    "SELECT w.id, w.project_id, p.name AS project_name, w.site_id, s.name AS site_name, w.period_from, w.period_to, "
    "w.status, w.approved_by, ua.full_name AS approved_by_name, w.approved_at, w.created_at, w.updated_at "
    "FROM wage_sheets w JOIN projects p ON p.id = w.project_id LEFT JOIN sites s ON s.id = w.site_id "
    "LEFT JOIN users ua ON ua.id = w.approved_by WHERE w.organization_id = :org")


async def find_sheet(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID, site_id: uuid.UUID | None,
                     period_from: datetime.date, period_to: datetime.date) -> dict[str, Any] | None:
    rows = await _rows(conn, _SHEET_SELECT + " AND w.project_id = :p AND COALESCE(w.site_id, :none) = :s "
                       "AND w.period_from = :f AND w.period_to = :t",
                       {"org": org, "p": project_id, "s": site_id or _NO_SITE, "none": _NO_SITE, "f": period_from,
                        "t": period_to})
    return rows[0] if rows else None


async def get_sheet(conn: AsyncConnection, org: uuid.UUID, sheet_id: uuid.UUID) -> dict[str, Any] | None:
    rows = await _rows(conn, _SHEET_SELECT + " AND w.id = :id", {"org": org, "id": sheet_id})
    return rows[0] if rows else None


async def list_sheets(conn: AsyncConnection, org: uuid.UUID, project_ids: set | None,
                      project_id: uuid.UUID | None = None, site_id: uuid.UUID | None = None) -> list[dict[str, Any]]:
    sql = (_SHEET_SELECT.replace("SELECT w.id,", "SELECT w.id, (SELECT COALESCE(SUM(net), 0) FROM wage_sheet_rows x "
           "WHERE x.sheet_id = w.id) AS net, (SELECT COALESCE(SUM(paid), 0) FROM wage_sheet_rows x WHERE x.sheet_id = w.id) "
           "AS paid, (SELECT COUNT(*) FROM wage_sheet_rows x WHERE x.sheet_id = w.id) AS payees,"))
    params: dict[str, Any] = {"org": org}
    if project_ids is not None:
        sql += " AND w.project_id = ANY(:projects)"
        params["projects"] = list(project_ids)
    if project_id:
        sql += " AND w.project_id = :p"
        params["p"] = project_id
    if site_id:
        sql += " AND w.site_id = :s"
        params["s"] = site_id
    return await _rows(conn, sql + " ORDER BY w.period_to DESC, p.name, s.name", params)


async def sheet_rows(conn: AsyncConnection, sheet_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = await _rows(conn, "SELECT * FROM wage_sheet_rows WHERE sheet_id = :id ORDER BY net DESC, payee_name",
                       {"id": sheet_id})
    for r in rows:
        if isinstance(r["deductions"], str):
            r["deductions"] = json.loads(r["deductions"])
    return rows


async def computed_rows(conn: AsyncConnection, org: uuid.UUID, sheet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """What attendance says the sheet's rows are now (before any recovery or deduction)."""
    lines = await attendance_lines(conn, org, sheet["project_id"], sheet["site_id"], sheet["period_from"], sheet["period_to"])
    return pay.build_rows(lines, await worker_team(conn, org), await teams(conn, org))


async def carry_ins(conn: AsyncConnection, org: uuid.UUID, sheet: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Differences from earlier weeks of the same site that were paid (so cannot be reopened) and whose attendance
    changed after approval, not yet carried anywhere: payee key -> carry entries for this draft's deductions. Earned
    more -> a negative deduction (added to pay); earned less -> a deduction. Each is carried once (``carry_from``)."""
    earlier = await _rows(conn, _SHEET_SELECT + " AND w.project_id = :p AND COALESCE(w.site_id, :none) = :s "
                          "AND w.status = 'approved' AND w.period_to < :f",
                          {"org": org, "p": sheet["project_id"], "s": sheet["site_id"] or _NO_SITE, "none": _NO_SITE,
                           "f": sheet["period_from"]})
    if not earlier:
        return {}
    done = {(c.get("carry_from"), r["payee_key"]) for r in await _rows(conn,
            "SELECT x.payee_key, x.deductions FROM wage_sheet_rows x JOIN wage_sheets w ON w.id = x.sheet_id "
            "WHERE w.organization_id = :org AND w.project_id = :p", {"org": org, "p": sheet["project_id"]})
            for c in (json.loads(r["deductions"]) if isinstance(r["deductions"], str) else r["deductions"] or [])
            if c.get("carry_from")}
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in earlier:
        rows = await sheet_rows(conn, e["id"])
        if not any(Decimal(r["paid"]) > 0 for r in rows):
            continue  # nothing paid: that week is reopened and corrected itself, not carried
        for c in await changed_since_approval(conn, org, e, rows):
            if (str(e["id"]), c["payee_key"]) in done or not c["difference"]:
                continue
            words = f"Week {e['period_from']:%d %b}–{e['period_to']:%d %b}: attendance changed after paying"
            out[c["payee_key"]].append({"reason": words, "amount": str(pay.money(-c["difference"])),
                                        "carry_from": str(e["id"]), "payee_name": c["payee_name"]})
    return out


async def refresh(conn: AsyncConnection, org: uuid.UUID, sheet: dict[str, Any]) -> None:
    """A draft sheet follows attendance: rows recomputed, the payer's deductions and recovery kept, paid rows kept,
    and differences from earlier paid weeks carried in once."""
    fresh = await computed_rows(conn, org, sheet)
    kept = {r["payee_key"]: r for r in await sheet_rows(conn, sheet["id"])}
    owed = await advance_balances(conn, org, sheet["project_id"], exclude_sheet=sheet["id"], until=sheet["period_to"])
    carried = await carry_ins(conn, org, sheet)
    for key in set(fresh) | set(kept) | set(carried):
        base = kept.get(key) or {"worker_id": None, "vendor_id": key.split(":", 1)[1] if key.startswith("vendor:") else None,
                                 "payee_name": (carried.get(key) or [{}])[0].get("payee_name") or key, "trades": None}
        if key.startswith("worker:") and not kept.get(key):
            base["worker_id"] = key.split(":", 1)[1]
        row = fresh.get(key) or {**{k: base[k] for k in ("worker_id", "vendor_id", "payee_name")}, "payee_key": key,
                                 "trades": base["trades"], "days": 0, "man_days": 0, "unpriced_man_days": 0,
                                 "overtime_hours": 0, "gross": Decimal(0), "overtime_amount": Decimal(0)}
        old = kept.get(key)
        deductions = (old["deductions"] if old else []) + [
            {k: v for k, v in c.items() if k != "payee_name"} for c in carried.get(key, [])]
        if not fresh.get(key) and old and not Decimal(old["paid"] or 0) and not deductions:
            await conn.execute(text("DELETE FROM wage_sheet_rows WHERE id = :id"), {"id": old["id"]})
            continue
        values_ded = json.dumps(deductions)
        recovered = Decimal(old["advances_recovered"]) if old and old["recovery_set"] else None
        money = pay.settle({**row, "deductions": deductions}, owed.get(key, Decimal(0)), recovered)
        values = {"org": org, "sheet": sheet["id"], "key": key, "worker_id": row["worker_id"], "vendor_id": row["vendor_id"],
                  "name": row["payee_name"], "trades": row["trades"], "days": row["days"], "man_days": row["man_days"],
                  "unpriced": row["unpriced_man_days"], "ot_hours": row["overtime_hours"], "gross": row["gross"],
                  "ot": row["overtime_amount"], "rec": money["advances_recovered"], "net": money["net"], "ded": values_ded}
        await conn.execute(text(
            "INSERT INTO wage_sheet_rows (organization_id, sheet_id, payee_key, worker_id, vendor_id, payee_name, trades, "
            "days, man_days, unpriced_man_days, overtime_hours, gross, overtime_amount, advances_recovered, net, deductions) "
            "VALUES (:org, :sheet, :key, :worker_id, :vendor_id, :name, :trades, :days, :man_days, :unpriced, :ot_hours, "
            ":gross, :ot, :rec, :net, CAST(:ded AS jsonb)) ON CONFLICT (sheet_id, payee_key) DO UPDATE SET "
            "deductions = EXCLUDED.deductions, worker_id = EXCLUDED.worker_id, "
            "vendor_id = EXCLUDED.vendor_id, payee_name = EXCLUDED.payee_name, trades = EXCLUDED.trades, days = EXCLUDED.days, "
            "man_days = EXCLUDED.man_days, unpriced_man_days = EXCLUDED.unpriced_man_days, "
            "overtime_hours = EXCLUDED.overtime_hours, gross = EXCLUDED.gross, overtime_amount = EXCLUDED.overtime_amount, "
            "advances_recovered = EXCLUDED.advances_recovered, net = EXCLUDED.net, updated_at = now()"), values)
    await conn.execute(text("UPDATE wage_sheets SET updated_at = now() WHERE id = :id"), {"id": sheet["id"]})


async def open_sheet(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID, site_id: uuid.UUID | None,
                     period_from: datetime.date, period_to: datetime.date, user_id: uuid.UUID) -> dict[str, Any]:
    """The period's sheet, made on first open; a draft is brought up to date with attendance each time."""
    sheet = await find_sheet(conn, org, project_id, site_id, period_from, period_to)
    if sheet is None:
        await conn.execute(text(
            "INSERT INTO wage_sheets (organization_id, project_id, site_id, period_from, period_to, created_by) "
            "VALUES (:org, :p, :s, :f, :t, :u) ON CONFLICT DO NOTHING"),
            {"org": org, "p": project_id, "s": site_id, "f": period_from, "t": period_to, "u": user_id})
        sheet = await find_sheet(conn, org, project_id, site_id, period_from, period_to)
    assert sheet is not None
    if sheet["status"] == "draft":
        await refresh(conn, org, sheet)
    return sheet


async def changed_since_approval(conn: AsyncConnection, org: uuid.UUID, sheet: dict[str, Any],
                                 rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """An approved sheet whose attendance changed: each payee whose wages would now differ, and by how much."""
    if sheet["status"] != "approved":
        return []
    fresh = await computed_rows(conn, org, sheet)
    have = {r["payee_key"]: r for r in rows}
    out = []
    for key in set(fresh) | set(have):
        now = pay.money(fresh[key]["gross"] + fresh[key]["overtime_amount"]) if key in fresh else Decimal(0)
        was = pay.money(Decimal(have[key]["gross"]) + Decimal(have[key]["overtime_amount"])) if key in have else Decimal(0)
        if now != was:
            name = (fresh.get(key) or have.get(key) or {}).get("payee_name")
            out.append({"payee_key": key, "payee_name": name, "was": was, "now": now, "difference": now - was})
    return out


async def set_row(conn: AsyncConnection, org: uuid.UUID, sheet: dict[str, Any], row_id: uuid.UUID,
                  recovered: Decimal | None, reset_recovery: bool, deductions: list[dict[str, Any]] | None) -> None:
    sets, params = ["updated_at = now()"], {"id": row_id, "sheet": sheet["id"]}
    if reset_recovery:
        sets.append("recovery_set = false")
    elif recovered is not None:
        sets += ["advances_recovered = :rec", "recovery_set = true"]
        params["rec"] = pay.money(recovered)
    if deductions is not None:
        # Carried differences from earlier weeks are the system's, not the payer's: an edit keeps them.
        current = next((r for r in await sheet_rows(conn, sheet["id"]) if r["id"] == row_id), None)
        carries = [d for d in (current["deductions"] if current else []) if d.get("carry_from")]
        sets.append("deductions = CAST(:ded AS jsonb)")
        params["ded"] = json.dumps(carries + [{"reason": d["reason"], "amount": str(pay.money(d["amount"]))}
                                              for d in deductions if not d.get("carry_from")])
    await conn.execute(text(f"UPDATE wage_sheet_rows SET {', '.join(sets)} WHERE id = :id AND sheet_id = :sheet"), params)
    await refresh(conn, org, sheet)


async def set_status(conn: AsyncConnection, sheet_id: uuid.UUID, status: str, user_id: uuid.UUID) -> None:
    await conn.execute(text(
        "UPDATE wage_sheets SET status = :st, approved_by = CASE WHEN :st = 'approved' THEN CAST(:u AS uuid) END, "
        "approved_at = CASE WHEN :st = 'approved' THEN now() END, updated_at = now() WHERE id = :id"),
        {"id": sheet_id, "st": status, "u": str(user_id)})


async def pay_row(conn: AsyncConnection, org: uuid.UUID, sheet: dict[str, Any], row: dict[str, Any], amount: Decimal,
                  paid_on: datetime.date, account_id: uuid.UUID | None, note: str | None, source: str,
                  user_id: uuid.UUID) -> uuid.UUID:
    payment_id = (await conn.execute(text(
        "INSERT INTO wage_payments (organization_id, sheet_id, row_id, amount, paid_on, account_id, note, source, created_by) "
        "VALUES (:org, :sheet, :row, :amount, :on, :acct, :note, :source, :by) RETURNING id"),
        {"org": org, "sheet": sheet["id"], "row": row["id"], "amount": amount, "on": paid_on, "acct": account_id,
         "note": note, "source": source, "by": user_id})).scalar_one()
    await conn.execute(text("UPDATE wage_sheet_rows SET paid = paid + :a, updated_at = now() WHERE id = :id"),
                       {"a": amount, "id": row["id"]})
    period = f"{sheet['period_from']:%d %b}–{sheet['period_to']:%d %b}"
    await _record_money(conn, org, "expense_payment", amount, paid_on, user_id, account_id, PAYMENT_SOURCE, payment_id,
                        f"Wages {row['payee_name']} · {period}")
    return payment_id


async def payments(conn: AsyncConnection, row_ids: list) -> list[dict[str, Any]]:
    if not row_ids:
        return []
    return await _rows(conn,
        "SELECT w.id, w.row_id, w.amount, w.paid_on, w.account_id, m.name AS account_name, w.note, w.source, "
        "u.full_name AS created_by_name, w.created_at FROM wage_payments w LEFT JOIN money_accounts m ON m.id = w.account_id "
        "LEFT JOIN users u ON u.id = w.created_by WHERE w.row_id = ANY(:ids) ORDER BY w.paid_on, w.created_at",
        {"ids": row_ids})


async def owed_summary(conn: AsyncConnection, org: uuid.UUID, project_ids: set | None) -> dict[str, Any]:
    """For Home and the project hub: wages approved and not paid, drafts waiting, advances outstanding."""
    scope = " AND w.project_id = ANY(:projects)" if project_ids is not None else ""
    params: dict[str, Any] = {"org": org, **({"projects": list(project_ids)} if project_ids is not None else {})}
    row = (await conn.execute(text(
        "SELECT COALESCE(SUM(CASE WHEN w.status = 'approved' THEN GREATEST(r.net - r.paid, 0) END), 0) AS due, "
        "COUNT(DISTINCT CASE WHEN w.status = 'approved' AND r.net > r.paid THEN r.id END) AS due_rows, "
        "COUNT(DISTINCT CASE WHEN w.status = 'draft' AND r.net > 0 THEN w.id END) AS drafts "
        "FROM wage_sheets w JOIN wage_sheet_rows r ON r.sheet_id = w.id WHERE w.organization_id = :org" + scope),
        params)).mappings().one()
    balances = await advance_balances(conn, org, project_ids=project_ids)
    out = sum((v for v in balances.values() if v > 0), Decimal(0))
    return {"due": pay.money(row["due"]), "due_rows": int(row["due_rows"] or 0), "drafts": int(row["drafts"] or 0),
            "advances_outstanding": pay.money(out), "advance_payees": sum(1 for v in balances.values() if v > 0)}
