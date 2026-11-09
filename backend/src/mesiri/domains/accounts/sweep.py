"""ACC-04: the posting sweep (D-ACC1). Reads the records the site and office already make, works out the journal
entries each should have (``posting.py``), and writes only what changed. No write path in Expenses, Finance,
Vendors, Billing or Subcontracts changes: the books follow the records, so a missed hook can never leave them behind.

Runs before every Accounts read (and on ``POST /accounts/post``), under a per-company advisory lock so two at once
never post twice.

**Closed months (D-ACC2).** An entry dated in a closed month is never changed or deleted. When its record changes (or
a new record is dated in a closed month), the difference between what the record should post and what the closed
months hold is posted as one entry on the first open day after them, marked ``after_close``. Open months are simply
re-posted (keeping the entry's number when its voucher type and year are unchanged).
"""

from __future__ import annotations

import datetime
import logging
import uuid
from collections import defaultdict
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.domains.accounts import chart, periods, posting
from mesiri.domains.finance.costs import CLAIMABLE_GST_SQL

_log = logging.getLogger(__name__)
_ZERO = Decimal(0)

#: Source kinds (``journal_entries.source_kind``).
EXPENSE, MONEY, RA_BILL, OPENING_ACCOUNT, OPENING_VENDOR = "expense", "money", "ra_bill", "opening_account", "opening_vendor"


def _s(v: Any) -> str | None:
    return str(v) if v is not None else None


async def _rows(conn: AsyncConnection, sql: str, org: uuid.UUID) -> list[dict[str, Any]]:
    return [dict(r) for r in (await conn.execute(text(sql), {"org": org})).mappings()]


# --- reading the records -------------------------------------------------------------------------------------------

async def read_sources(conn: AsyncConnection, org: uuid.UUID) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """Every source record's desired entries, keyed by (source kind, source id)."""
    from mesiri.domains.billing.bills import ref as bill_ref
    from mesiri.domains.subcontracts.store import TDS_ACCOUNT

    vendors = {str(r["id"]): r for r in await _rows(conn,
        "SELECT id, name, opening_balance, opening_balance_date FROM vendors WHERE organization_id = :org", org)}
    accounts = {str(r["id"]): r for r in await _rows(conn,
        "SELECT id, name, account_type, opening_balance, opening_balance_date, project_id, site_id "
        "FROM money_accounts WHERE organization_id = :org", org)}
    expenses = {str(r["id"]): r for r in await _rows(conn,
        f"SELECT e.id, e.expense_number AS number, e.occurred_date AS date, e.amount, ({CLAIMABLE_GST_SQL}) AS claimable_gst, "
        "e.category_id, c.cost_centre, c.name AS category, e.vendor_id, v.name AS vendor, e.payment_status, "
        "e.created_by AS staff_id, u.full_name AS staff, e.project_id, e.site_id, e.description, e.workflow_status "
        "FROM expenses e LEFT JOIN expense_categories c ON c.id = e.category_id LEFT JOIN vendors v ON v.id = e.vendor_id "
        "LEFT JOIN users u ON u.id = e.created_by WHERE e.organization_id = :org", org)}
    payments = {str(r["id"]): r for r in await _rows(conn,
        "SELECT id, expense_id, vendor_id, project_id, reference_number, payment_method FROM expense_payments "
        "WHERE organization_id = :org", org)}
    receipts = {str(r["id"]): r for r in await _rows(conn,
        "SELECT r.id, r.kind, COALESCE(r.client_id, pc.client_id) AS client_id, cl.name AS client, r.project_id, "
        "b.number AS bill_number FROM client_receipts r "
        "LEFT JOIN project_contracts pc ON pc.project_id = r.project_id AND pc.organization_id = r.organization_id "
        "LEFT JOIN clients cl ON cl.id = COALESCE(r.client_id, pc.client_id) "
        "LEFT JOIN ra_bills b ON b.id = r.ra_bill_id WHERE r.organization_id = :org", org)}
    moves = {str(r["id"]): r for r in await _rows(conn,
        "SELECT id, transaction_type AS type, amount, occurred_date AS date, from_account_id, to_account_id, "
        "source_type, source_id, description FROM money_transactions WHERE organization_id = :org", org)}
    bills = await _rows(conn,
        "SELECT b.id, b.number, b.bill_date AS date, b.status, COALESCE(b.client_id, pc.client_id) AS client_id, "
        "b.gross, b.gst, b.net, b.tds, b.retention, b.advance_recovery, b.project_id, p.name AS project "
        "FROM ra_bills b JOIN projects p ON p.id = b.project_id "
        "LEFT JOIN project_contracts pc ON pc.project_id = b.project_id AND pc.organization_id = b.organization_id "
        "WHERE b.organization_id = :org", org)

    def vendor_start(vendor_id: Any) -> datetime.date | None:
        v = vendors.get(_s(vendor_id)) if vendor_id else None
        return v["opening_balance_date"] if v and v["opening_balance"] else None

    out: dict[tuple[str, str], list[dict[str, Any]]] = {}

    for e in expenses.values():
        if e["workflow_status"] != "confirmed":
            continue
        words = " · ".join(x for x in (e["number"], e["description"] or e["category"], e["vendor"]) if x)
        if (e["payment_status"] or "") in posting.STAFF_PAID and e["staff"]:
            words += f" · paid by {e['staff']}"
        out[(EXPENSE, str(e["id"]))] = posting.expense_entries(
            {**e, "vendor_start": vendor_start(e["vendor_id"]), "words": words})

    def payment_counter(p: dict[str, Any] | None, expense_id: Any, day: datetime.date) -> dict[str, Any]:
        e = expenses.get(_s(expense_id)) if expense_id else None
        vendor_id = (p or {}).get("vendor_id") or (e or {}).get("vendor_id")
        who = posting.party(vendor_id, (e or {}).get("payment_status"), (e or {}).get("staff_id"), day,
                            vendor_start(vendor_id))
        name = (vendors.get(_s(vendor_id)) or {}).get("name") if vendor_id else None
        if who[0] == "link" and who[1] == "staff":
            name = f"{(e or {}).get('staff') or 'staff'} (own pocket)"
        what = f"for {e['number']}" if e and e.get("number") else ("on account" if p and not expense_id else None)
        return {"ledger": who, "project_id": (p or {}).get("project_id") or (e or {}).get("project_id"),
                "site_id": (e or {}).get("site_id"),
                "words": " · ".join(x for x in ("Paid", name, what, (p or {}).get("reference_number")) if x)}

    def receipt_counter(r: dict[str, Any]) -> dict[str, Any]:
        if r["kind"] == "advance":
            ledger = posting.code("advance_received")
        else:
            ledger = posting.link("client", r["client_id"]) if r["client_id"] else posting.code("no_client")
        what = {"bill": f"against {bill_ref(r['bill_number'])}" if r["bill_number"] else "against a bill",
                "on_account": "on account", "advance": "mobilisation advance"}[r["kind"]]
        return {"ledger": ledger, "project_id": r["project_id"], "site_id": None,
                "words": " · ".join(x for x in ("Received", r["client"], what) if x)}

    def counter_of(m: dict[str, Any], depth: int = 0) -> dict[str, Any] | None:
        src, sid = m.get("source_type"), _s(m.get("source_id"))
        if m["type"] == "transfer":
            return None
        if src == "client_receipt":
            if sid in receipts:
                return receipt_counter(receipts[sid])
            # The receipt is gone (its project was deleted) but the money came in: still a client's, never capital.
            return {"ledger": posting.code("no_client"), "words": "Received from a client (receipt removed)"}
        if src == "expense_payment" and sid in payments:
            p = payments[sid]
            c = payment_counter(p, p["expense_id"], m["date"])
            acct = accounts.get(_s(m.get("from_account_id") or m.get("to_account_id"))) or {}
            if acct.get("name") == TDS_ACCOUNT:
                c = {**c, "voucher_type": "journal", "words": c["words"].replace("Paid", "TDS deducted", 1)}
            return c
        if src == "expense" and sid in expenses:
            return payment_counter(None, sid, m["date"])
        if m["type"] == "reversal" and src == "money_transaction" and sid in moves and depth < 3:
            c = counter_of(moves[sid], depth + 1)
            return {**c, "words": f"Undone: {c['words']}"} if c else None
        if m["type"] == "fund_received":
            return {"ledger": posting.code("funds_introduced"), "words": "Funds received"}
        if m["type"] == "expense_payment":
            return {"ledger": posting.code("expenses_payable"), "words": "Paid"}
        return {"ledger": posting.code("balance_adjustments"), "words": "Balance adjustment"}

    for m in moves.values():
        where = {}
        for side in ("from", "to"):
            a = accounts.get(_s(m[f"{side}_account_id"])) or {}
            where[f"{side}_project_id"] = a.get("project_id")
            where[f"{side}_site_id"] = a.get("site_id")
        tx = {**m, **where}
        if m["type"] == "transfer":
            names = [(accounts.get(_s(m[f"{s}_account_id"])) or {}).get("name") for s in ("from", "to")]
            tx["description"] = m["description"] or f"Transfer {names[0]} → {names[1]}"
        counter = counter_of(m)
        if m["type"] == "reversal" and counter and m.get("source_type") == "expense_payment":
            counter = {**counter, "words": f"Payment undone · {counter['words']}"}
        if m["type"] == "reversal" and counter and m.get("source_type") == "client_receipt":
            counter = {**counter, "words": f"Receipt cancelled · {counter['words']}"}
        if counter and (m["type"] == "reversal" or m.get("source_type") == "client_receipt"):
            tx["description"] = None  # the counter's words already say it
        out[(MONEY, str(m["id"]))] = posting.money_entries(tx, counter)

    for b in bills:
        ref = bill_ref(b["number"])
        out[(RA_BILL, str(b["id"]))] = posting.ra_bill_entries(
            {**b, "ref": ref, "words": " · ".join(x for x in (f"{ref} running bill", b["project"]) if x)})
    for a in accounts.values():
        out[(OPENING_ACCOUNT, str(a["id"]))] = posting.opening_account_entries(a)
    for v in vendors.values():
        out[(OPENING_VENDOR, str(v["id"]))] = posting.opening_vendor_entries(v)
    return out


# --- ledgers -------------------------------------------------------------------------------------------------------

_LINK_NAMES = {
    "vendor": "SELECT id, name FROM vendors WHERE organization_id = :org",
    "client": "SELECT id, name FROM clients WHERE organization_id = :org",
    "money_account": "SELECT id, name, account_type FROM money_accounts WHERE organization_id = :org",
    "expense_category": "SELECT id, name FROM expense_categories WHERE organization_id = :org",
    "staff": "SELECT id, COALESCE(full_name, 'Staff') || ' (own pocket)' AS name FROM users WHERE organization_id = :org",
}


async def _resolver(conn: AsyncConnection, org: uuid.UUID, refs: set[tuple]) -> dict[tuple, uuid.UUID]:
    """Ledger id per reference, making the linked ledgers that do not exist yet (named after their record)."""
    groups = {r["code"]: r["id"] for r in await chart.groups(conn, org) if r["code"]}
    found: dict[tuple, uuid.UUID] = {}
    for r in await chart.ledgers(conn, org):
        if r["code"]:
            found[("code", r["code"])] = r["id"]
        if r["link_kind"]:
            found[("link", r["link_kind"], str(r["link_id"]))] = r["id"]
    missing = [ref for ref in refs if ref not in found]
    if missing:
        names: dict[str, dict[str, dict]] = {}
        for kind in {ref[1] for ref in missing if ref[0] == "link"}:
            names[kind] = {str(r["id"]): r for r in await _rows(conn, _LINK_NAMES[kind], org)}
        for ref in missing:
            if ref[0] != "link":
                raise LookupError(f"seeded ledger {ref[1]} missing")
            kind, rid = ref[1], ref[2]
            rec = names[kind].get(rid) or {"name": f"{kind} {rid[:8]}"}
            group = (chart.account_group(rec.get("account_type"), rec["name"]) if kind == "money_account"
                     else chart.LINK_GROUP[kind])
            found[ref] = (await conn.execute(text(
                "INSERT INTO ledgers (organization_id, group_id, name, link_kind, link_id) VALUES (:org, :g, :n, :k, :id) "
                "ON CONFLICT (organization_id, link_kind, link_id) WHERE link_kind IS NOT NULL "
                "DO UPDATE SET updated_at = now() RETURNING id"),
                {"org": org, "g": groups[group], "n": rec["name"], "k": kind, "id": uuid.UUID(rid)})).scalar_one()
    return found


async def sync_names(conn: AsyncConnection, org: uuid.UUID) -> None:
    """A linked ledger is named after its record: a supplier renamed in Vendors is renamed in the books."""
    for kind, sql in _LINK_NAMES.items():
        await conn.execute(text(
            f"UPDATE ledgers l SET name = x.name, updated_at = now() FROM ({sql}) x "  # noqa: S608 (fixed SQL)
            "WHERE l.organization_id = :org AND l.link_kind = :k AND l.link_id = x.id AND l.name <> x.name"),
            {"org": org, "k": kind})


# --- writing -------------------------------------------------------------------------------------------------------

def _key(ln: dict[str, Any]) -> tuple:
    return (ln["ledger"], ln.get("project_id"), ln.get("site_id"), ln.get("cost_centre"))


def adjustment(desired_closed: list[dict[str, Any]], kept_lines: list[dict[str, Any]], day: datetime.date,
               narration: str) -> dict[str, Any] | None:
    """What the closed months should hold for a source, less what they hold: one balanced entry, or None."""
    net: dict[tuple, Decimal] = defaultdict(Decimal)
    for e in desired_closed:
        for ln in e["lines"]:
            net[_key(ln)] += ln["debit"] - ln["credit"]
    for ln in kept_lines:
        net[_key(ln)] -= ln["debit"] - ln["credit"]
    lines = [posting.line(k[0], v, True, project_id=k[1], site_id=k[2], cost_centre=k[3]) for k, v in net.items() if v]
    if not lines:
        return None
    projects = {ln["project_id"] for ln in lines}
    return posting.entry(f"after_close:{day.isoformat()}", day, "journal", narration, lines,
                         next(iter(projects)) if len(projects) == 1 else None)


async def sweep(conn: AsyncConnection, org: uuid.UUID) -> dict[str, int]:
    """Post every record that is new or changed since it was posted. Returns counts of what it did."""
    await conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"mesiri-accounts:{org}"})
    await chart.ensure_chart(conn, org)
    await sync_names(conn, org)
    desired = await read_sources(conn, org)
    fps = {k: posting.fingerprint(v) for k, v in desired.items()}

    existing: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in await _rows(conn,
            "SELECT id, source_kind, source_id, source_part, fingerprint, entry_date, voucher_type, financial_year, "
            "number FROM journal_entries WHERE organization_id = :org AND source_kind <> 'manual'", org):
        existing[(r["source_kind"], str(r["source_id"]))].append(r)
    empty = posting.fingerprint([])
    def first_day(k: tuple[str, str]) -> datetime.date:
        days = [e["date"] for e in desired.get(k, [])] + [x["entry_date"] for x in existing.get(k, [])]
        return min(days) if days else datetime.date.max

    # Oldest first, so a first posting numbers the vouchers in date order (later ones follow, as in Tally).
    todo = sorted((k for k in set(desired) | set(existing)
            if not (existing.get(k) and all(x["fingerprint"] == fps.get(k, empty) for x in existing[k]))
            and (desired.get(k) or existing.get(k))), key=lambda k: (first_day(k), k))
    stats = {"posted": 0, "reposted": 0, "removed": 0, "after_close": 0, "skipped": 0, "sources": len(desired)}
    if not todo:
        return stats

    refs = {ln["ledger"] for k in todo for e in desired.get(k, []) for ln in e["lines"]}
    ledger_of = await _resolver(conn, org, refs)
    closed = await periods.closed_spans(conn, org)

    def is_closed(d: datetime.date) -> bool:
        return any(s <= d <= e for s, e in closed)

    numbers: dict[tuple[str, str], int] = {(r["voucher_type"], r["financial_year"]): r["n"] for r in await _rows(conn,
        "SELECT voucher_type, financial_year, MAX(number) AS n FROM journal_entries WHERE organization_id = :org "
        "GROUP BY voucher_type, financial_year", org)}
    ledger_ref = {v: k for k, v in ledger_of.items()}
    touched_days: set[datetime.date] = set()

    async def write_lines(entry_id: uuid.UUID, e: dict[str, Any]) -> None:
        await conn.execute(text("DELETE FROM journal_lines WHERE entry_id = :id"), {"id": entry_id})
        await conn.execute(text(
            "INSERT INTO journal_lines (organization_id, entry_id, line_no, entry_date, ledger_id, debit, credit, "
            "project_id, site_id, cost_centre) VALUES (:org, :entry, :no, :d, :ledger, :dr, :cr, CAST(:p AS uuid), "
            "CAST(:s AS uuid), :cc)"),
            [{"org": org, "entry": entry_id, "no": i, "d": e["date"], "ledger": ledger_of[ln["ledger"]],
              "dr": ln["debit"], "cr": ln["credit"], "p": ln["project_id"], "s": ln["site_id"], "cc": ln["cost_centre"]}
             for i, ln in enumerate(e["lines"], start=1)])

    for key in todo:
        kind, sid = key
        want = [e for e in desired.get(key, []) if e["lines"]]
        bad = [e for e in want if not posting.balanced(e)]
        if bad:
            _log.error("accounts: %s %s does not balance; not posted", kind, sid)
            stats["skipped"] += 1
            continue
        have = existing.get(key, [])
        kept = [x for x in have if is_closed(x["entry_date"])]
        open_have = {(x["source_part"], x["voucher_type"], x["financial_year"]): x
                     for x in have if not is_closed(x["entry_date"])}
        new_open = [e for e in want if not is_closed(e["date"])]
        want_closed = [e for e in want if is_closed(e["date"])]
        if kept or want_closed:
            kept_lines = []
            if kept:
                kept_lines = [{**r, "ledger": ledger_ref.get(r["ledger_id"]) or ("id", str(r["ledger_id"])),
                               "project_id": _s(r["project_id"]), "site_id": _s(r["site_id"])}
                              for r in (await conn.execute(text(
                                  "SELECT ledger_id, debit, credit, project_id, site_id, cost_centre FROM journal_lines "
                                  "WHERE entry_id = ANY(:ids)"), {"ids": [x["id"] for x in kept]})).mappings()]
                for r in kept_lines:  # a ledger no longer referenced by the record still needs an id to reverse
                    if r["ledger"][0] == "id":
                        ledger_of[r["ledger"]] = uuid.UUID(r["ledger"][1])
            first = min([x["entry_date"] for x in kept] + [e["date"] for e in want_closed])
            day = periods.first_open_day(closed, first)
            label = f"{first:%b %Y}"
            words = (want[0]["narration"] if want else (kept and "Record removed")) or "Record changed"
            adj = adjustment(want_closed, kept_lines, day, f"Changed after {label} was closed · {words}")
            if adj:
                adj["after_close"] = True
                new_open.append(adj)
                stats["after_close"] += 1
            if kept:
                await conn.execute(text("UPDATE journal_entries SET fingerprint = :fp WHERE id = ANY(:ids)"),
                                   {"fp": fps.get(key, empty), "ids": [x["id"] for x in kept]})
        for e in new_open:
            fy = periods.fy_label(e["date"])
            reuse = open_have.pop((e["part"], e["voucher_type"], fy), None)
            touched_days.add(e["date"])
            params = {"d": e["date"], "n": e["narration"], "fp": fps.get(key, empty), "p": e["project_id"],
                      "ac": bool(e.get("after_close"))}
            if reuse is not None:
                await conn.execute(text(
                    "UPDATE journal_entries SET entry_date = :d, narration = :n, fingerprint = :fp, "
                    "project_id = CAST(:p AS uuid), after_close = :ac, updated_at = now() WHERE id = :id"),
                    {**params, "id": reuse["id"]})
                await write_lines(reuse["id"], e)
                stats["reposted"] += 1
                continue
            numbers[(e["voucher_type"], fy)] = numbers.get((e["voucher_type"], fy), 0) + 1
            entry_id = (await conn.execute(text(
                "INSERT INTO journal_entries (organization_id, entry_date, voucher_type, financial_year, number, "
                "narration, source_kind, source_id, source_part, fingerprint, after_close, project_id) VALUES "
                "(:org, :d, :t, :fy, :no, :n, :k, :sid, :part, :fp, :ac, CAST(:p AS uuid)) RETURNING id"),
                {**params, "org": org, "t": e["voucher_type"], "fy": fy, "no": numbers[(e["voucher_type"], fy)],
                 "k": kind, "sid": uuid.UUID(sid), "part": e["part"]})).scalar_one()
            await write_lines(entry_id, e)
            stats["posted"] += 1
        if open_have:
            await conn.execute(text("DELETE FROM journal_entries WHERE id = ANY(:ids)"),
                               {"ids": [x["id"] for x in open_have.values()]})
            stats["removed"] += len(open_have)
    await periods.ensure_months(conn, org, touched_days)
    return stats
