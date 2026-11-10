"""ACC-13: bank reconciliation. The bank statement against the money movements Mesiri has for that account.

**Import.** An Excel or CSV statement as the bank gives it. The header row is found by its words (Date, Narration /
Particulars / Description, Chq / Ref No, Withdrawal / Debit, Deposit / Credit, or one Amount with a Dr / Cr column,
Balance); the columns found are kept with the statement and offered first for that account's next one. Dates in the
forms Indian banks use (15/10/2026, 15-10-26, 15-Oct-2026, 2026-10-15, Excel dates). A line already imported (an
overlapping statement) is skipped by its date, amount, reference, words and its place among identical lines.

**Matching** (on import, and again whenever the page is read): a statement line is matched to a money movement on
that account with the same amount and direction, dated within three days, not matched to another line. One candidate
is matched at once; with several, the one whose reference (UTR, cheque number) appears in the line, else the nearest
date, else it waits for a tap. Nothing is matched across accounts.

**What the bank has and Mesiri does not** (charges, interest, a payment nobody recorded) is **booked** with one tap:
a money movement is made in Finance › Money for it (an adjustment on that account, the same write path Finance
uses), on the ledger chosen (kept with the movement in ``bank_bookings``) (Bank charges, Bank interest received, a supplier ...). The posting sweep posts it, so the
bank ledger and Finance keep agreeing by construction. Undoing a booking records a reversal, as Finance does.

**What Mesiri has and the bank does not** (a cheque not yet presented, a deposit not yet credited) is listed, and the
reconciliation statement explains the difference: balance in the books − movements not in the statement = the
statement's balance.
"""

from __future__ import annotations

import csv
import datetime
import hashlib
import io
import re
import uuid
from collections import Counter
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

_ZERO = Decimal(0)
MATCH_DAYS = 3
SOURCE = "bank_statement_line"

#: Column -> the words a bank's header uses for it (lower case, compared after removing punctuation).
HEADERS: dict[str, tuple[str, ...]] = {
    "date": ("txn date", "transaction date", "tran date", "value date", "date", "posting date"),
    "description": ("narration", "particulars", "description", "remarks", "transaction details", "details",
                    "transaction remarks"),
    "reference": ("chq ref no", "chq no", "cheque no", "ref no", "reference no", "chqref no", "reference",
                  "utr", "chq ref number", "cheque number", "instrument id"),
    "withdrawal": ("withdrawal amt", "withdrawal amount", "withdrawals", "withdrawal", "debit amount", "debit",
                   "dr amount", "amount dr"),
    "deposit": ("deposit amt", "deposit amount", "deposits", "deposit", "credit amount", "credit", "cr amount",
                "amount cr"),
    "amount": ("amount", "transaction amount", "amount inr", "amt"),
    "drcr": ("dr cr", "drcr", "type", "cr dr", "debit credit"),
    "balance": ("closing balance", "balance", "running balance", "balance amt", "balance inr"),
}
_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov",
                                       "dec"), start=1)}


class StatementError(ValueError):
    pass


def _norm(v: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(v or "").lower()).strip()


def read_table(content: bytes, filename: str) -> list[list[Any]]:
    """The statement's cells, row by row (Excel's first sheet, or CSV)."""
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xlsm")) or content[:2] == b"PK":
        from openpyxl import load_workbook

        try:
            book = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        except Exception as exc:  # noqa: BLE001 -- a broken file is the user's to fix
            raise StatementError("That Excel file could not be opened. Download the statement again as Excel or CSV.") from exc
        sheet = book.worksheets[0]
        return [list(r) for r in sheet.iter_rows(values_only=True)]
    if name.endswith(".xls"):
        raise StatementError("Old Excel (.xls) files cannot be read: save it as .xlsx or CSV and upload that.")
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            raw = content.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    dialect = csv.Sniffer().sniff(raw[:4096], delimiters=",;\t|") if raw.strip() else csv.excel
    return [row for row in csv.reader(io.StringIO(raw), dialect)]


def find_columns(rows: list[list[Any]], mapping: dict[str, int] | None = None) -> tuple[int, dict[str, int]]:
    """The header row and the column of each field. A saved ``mapping`` (field -> column) is tried first."""
    for i, row in enumerate(rows[:40]):
        cells = [_norm(c) for c in row]
        if mapping and all(0 <= c < len(cells) for c in mapping.values()) and "date" in mapping:
            if any(w in cells[mapping["date"]] for w in ("date",)):
                return i, dict(mapping)
        found: dict[str, int] = {}
        for field, words in HEADERS.items():
            for word in words:  # most specific first
                hit = next((j for j, c in enumerate(cells) if c == word and j not in found.values()), None)
                if hit is None:
                    hit = next((j for j, c in enumerate(cells) if c.startswith(word) and j not in found.values()), None)
                if hit is not None:
                    found[field] = hit
                    break
        has_money = ("withdrawal" in found and "deposit" in found) or "amount" in found
        if "date" in found and has_money:
            if "withdrawal" in found and "deposit" in found:
                found.pop("amount", None)
                found.pop("drcr", None)
            return i, found
    raise StatementError("The header row was not found: the statement needs a Date column and either Withdrawal and "
                         "Deposit columns or an Amount column.")


def parse_date(v: Any) -> datetime.date | None:
    if isinstance(v, datetime.datetime):
        return v.date()
    if isinstance(v, datetime.date):
        return v
    if isinstance(v, (int, float)) and 20000 < v < 80000:  # an Excel serial date
        return datetime.date(1899, 12, 30) + datetime.timedelta(days=int(v))
    s = str(v or "").strip()
    if not s:
        return None
    s = s.split(" ")[0] if re.match(r"^\d{4}-\d{2}-\d{2} ", s) else s
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", s)
    if m:
        return _safe(int(m[1]), int(m[2]), int(m[3]))
    m = re.match(r"^(\d{1,2})[/\-. ](\d{1,2})[/\-. ](\d{2,4})$", s)
    if m:
        year = int(m[3]) + (2000 if len(m[3]) == 2 else 0)
        return _safe(year, int(m[2]), int(m[1]))
    m = re.match(r"^(\d{1,2})[/\-. ]?([A-Za-z]{3})[A-Za-z]*[/\-. ,]*(\d{2,4})$", s)
    if m and m[2].lower() in _MONTHS:
        year = int(m[3]) + (2000 if len(m[3]) == 2 else 0)
        return _safe(year, _MONTHS[m[2].lower()], int(m[1]))
    return None


def _safe(y: int, m: int, d: int) -> datetime.date | None:
    try:
        return datetime.date(y, m, d)
    except ValueError:
        return None


def parse_money(v: Any) -> Decimal | None:
    if v is None:
        return None
    if isinstance(v, (int, float, Decimal)):
        return Decimal(str(v)).quantize(Decimal("0.01"))
    s = str(v).strip().replace(",", "").replace("₹", "").replace("INR", "").replace("Rs.", "").strip()
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").strip()
    suffix = s[-2:].lower() if len(s) > 2 else ""
    if suffix in ("dr", "cr"):
        s = s[:-2].strip()
    if not s or s in ("-", "--"):
        return None
    try:
        out = Decimal(s).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None
    if neg or suffix == "dr":
        out = -abs(out)
    return out


def parse(content: bytes, filename: str, mapping: dict[str, int] | None = None) -> dict[str, Any]:
    """Pure: the statement's lines (amount signed: + money in, − money out) and the columns read."""
    rows = read_table(content, filename)
    head, cols = find_columns(rows, mapping)
    lines = []
    for row in rows[head + 1:]:
        def cell(field: str, row: list[Any] = row) -> Any:
            j = cols.get(field)
            return row[j] if j is not None and j < len(row) else None
        day = parse_date(cell("date"))
        if day is None:
            continue
        if "withdrawal" in cols:
            out_ = parse_money(cell("withdrawal")) or _ZERO
            in_ = parse_money(cell("deposit")) or _ZERO
            amount = abs(in_) - abs(out_)
        else:
            amount = parse_money(cell("amount"))
            if amount is None:
                continue
            side = _norm(cell("drcr"))
            if side.startswith(("dr", "debit", "d", "withdraw")):
                amount = -abs(amount)
            elif side.startswith(("cr", "credit", "c", "deposit")):
                amount = abs(amount)
        if not amount:
            continue
        desc = " ".join(str(cell("description") or "").split()) or None
        ref = str(cell("reference") or "").strip() or None
        if ref and re.fullmatch(r"0+", ref):
            ref = None
        lines.append({"date": day, "description": desc, "reference": ref, "amount": amount,
                      "balance": parse_money(cell("balance"))})
    if not lines:
        raise StatementError("No dated lines with an amount were found under the header row.")
    return {"lines": lines, "columns": cols, "header_row": head + 1}


def dedupe_keys(lines: list[dict[str, Any]]) -> list[str]:
    """One key per line: the same line twice in a statement (two ₹10 charges on a day) keeps both, by its place."""
    seen: Counter = Counter()
    out = []
    for ln in lines:
        base = "|".join(str(x) for x in (ln["date"], ln["amount"], ln.get("reference") or "",
                                         _norm(ln.get("description"))[:120]))
        seen[base] += 1
        out.append(hashlib.sha1(f"{base}|{seen[base]}".encode(), usedforsecurity=False).hexdigest())
    return out


def best_match(line: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pure: the one movement a line is matched to on its own, or None when it is not clear."""
    fits = [c for c in candidates if c["amount"] == abs(line["amount"]) and c["inflow"] == (line["amount"] > 0)
            and abs((c["date"] - line["date"]).days) <= MATCH_DAYS]
    if len(fits) <= 1:
        return fits[0] if fits else None
    words = _norm(f"{line.get('description') or ''} {line.get('reference') or ''}")
    by_ref = [c for c in fits if c.get("reference") and _norm(c["reference"]) and _norm(c["reference"]) in words]
    if len(by_ref) == 1:
        return by_ref[0]
    nearest = sorted(fits, key=lambda c: abs((c["date"] - line["date"]).days))
    if abs((nearest[0]["date"] - line["date"]).days) < abs((nearest[1]["date"] - line["date"]).days):
        return nearest[0]
    return None


async def account(conn: AsyncConnection, org: uuid.UUID, account_id: uuid.UUID) -> dict[str, Any]:
    row = (await conn.execute(text(
        "SELECT id, name, account_type, opening_balance, opening_balance_date FROM money_accounts "
        "WHERE id = :a AND organization_id = :org"), {"a": account_id, "org": org})).mappings().first()
    if row is None:
        raise StatementError("Account not found.")
    return dict(row)


async def movements(conn: AsyncConnection, org: uuid.UUID, account_id: uuid.UUID,
                    date_from: datetime.date | None = None, date_to: datetime.date | None = None) -> list[dict[str, Any]]:
    """The money movements on the account (what the books have), each with what it was for and the line it matched."""
    rows = (await conn.execute(text(
        "SELECT m.id, m.occurred_date AS date, m.amount, m.transaction_type AS type, m.description, m.source_type, "
        "COALESCE(m.to_account_id = :a, false) AS inflow, ep.reference_number AS reference, "
        "COALESCE(v.name, cl.name) AS party, b.id AS line_id, "
        # A movement undone (reversed) and its reversal cancel out: never offered for matching or counted as missing.
        "(EXISTS (SELECT 1 FROM money_transactions r WHERE r.transaction_type = 'reversal' "
        "  AND r.source_type = 'money_transaction' AND r.source_id = m.id) "
        " OR (m.transaction_type = 'reversal' AND m.source_type = 'money_transaction')) AS undone "
        "FROM money_transactions m "
        "LEFT JOIN expense_payments ep ON m.source_type = 'expense_payment' AND ep.id = m.source_id "
        "LEFT JOIN vendors v ON v.id = ep.vendor_id "
        "LEFT JOIN client_receipts cr ON m.source_type = 'client_receipt' AND cr.id = m.source_id "
        "LEFT JOIN clients cl ON cl.id = cr.client_id "
        "LEFT JOIN bank_statement_lines b ON b.money_transaction_id = m.id "
        "WHERE m.organization_id = :org AND (m.to_account_id = :a OR m.from_account_id = :a) "
        "AND (CAST(:f AS date) IS NULL OR m.occurred_date >= :f) AND (CAST(:t AS date) IS NULL OR m.occurred_date <= :t) "
        "ORDER BY m.occurred_date, m.created_at"),
        {"org": org, "a": account_id, "f": date_from, "t": date_to})).mappings()
    return [{**dict(r), "amount": Decimal(r["amount"])} for r in rows]


async def auto_match(conn: AsyncConnection, org: uuid.UUID, account_id: uuid.UUID, user_id: uuid.UUID | None) -> int:
    """Match every open line that has one clear movement (see ``best_match``). Returns how many were matched."""
    open_lines = [dict(r) for r in (await conn.execute(text(
        "SELECT id, line_date AS date, amount, description, reference FROM bank_statement_lines "
        "WHERE organization_id = :org AND money_account_id = :a AND status = 'open' ORDER BY line_date, line_no"),
        {"org": org, "a": account_id})).mappings()]
    if not open_lines:
        return 0
    lo = min(ln["date"] for ln in open_lines) - datetime.timedelta(days=MATCH_DAYS)
    hi = max(ln["date"] for ln in open_lines) + datetime.timedelta(days=MATCH_DAYS)
    free = [m for m in await movements(conn, org, account_id, lo, hi) if m["line_id"] is None and not m["undone"]]
    done = 0
    for ln in open_lines:
        ln["amount"] = Decimal(ln["amount"])
        hit = best_match(ln, free)
        if hit is None:
            continue
        free.remove(hit)
        await conn.execute(text(
            "UPDATE bank_statement_lines SET status = 'matched', money_transaction_id = :m, matched_by = :u, "
            "matched_at = now() WHERE id = :id"), {"m": hit["id"], "u": user_id, "id": ln["id"]})
        done += 1
    return done


async def last_mapping(conn: AsyncConnection, org: uuid.UUID, account_id: uuid.UUID) -> dict[str, int] | None:
    row = (await conn.execute(text(
        "SELECT mapping FROM bank_statements WHERE organization_id = :org AND money_account_id = :a "
        "ORDER BY created_at DESC LIMIT 1"), {"org": org, "a": account_id})).scalar()
    return dict(row) if row else None


async def import_statement(conn: AsyncConnection, org: uuid.UUID, user_id: uuid.UUID, account_id: uuid.UUID,
                           content: bytes, filename: str, preview: bool = False,
                           mapping: dict[str, int] | None = None) -> dict[str, Any]:
    await account(conn, org, account_id)
    parsed = parse(content, filename, mapping or await last_mapping(conn, org, account_id))
    lines = parsed["lines"]
    keys = dedupe_keys(lines)
    have = {r[0] for r in (await conn.execute(text(
        "SELECT dedupe_key FROM bank_statement_lines WHERE organization_id = :org AND money_account_id = :a "
        "AND dedupe_key = ANY(:k)"), {"org": org, "a": account_id, "k": keys}))}
    new = [(ln, k) for ln, k in zip(lines, keys, strict=True) if k not in have]
    summary = {"lines": len(lines), "new": len(new), "already_imported": len(lines) - len(new),
               "columns": parsed["columns"], "header_row": parsed["header_row"],
               "date_from": min(ln["date"] for ln in lines), "date_to": max(ln["date"] for ln in lines),
               "money_in": sum((ln["amount"] for ln in lines if ln["amount"] > 0), _ZERO),
               "money_out": -sum((ln["amount"] for ln in lines if ln["amount"] < 0), _ZERO),
               "closing_balance": next((ln["balance"] for ln in reversed(lines) if ln["balance"] is not None), None),
               "sample": lines[:8]}
    if preview:
        return summary
    sid = (await conn.execute(text(
        "INSERT INTO bank_statements (organization_id, money_account_id, file_name, period_from, period_to, "
        "closing_balance, mapping, lines, skipped, created_by) VALUES (:org, :a, :fn, :f, :t, :cb, CAST(:m AS jsonb), "
        ":n, :sk, :u) RETURNING id"),
        {"org": org, "a": account_id, "fn": (filename or "")[:200], "f": summary["date_from"], "t": summary["date_to"],
         "cb": summary["closing_balance"], "m": __import__("json").dumps(parsed["columns"]), "n": len(new),
         "sk": summary["already_imported"], "u": user_id})).scalar_one()
    if new:
        await conn.execute(text(
            "INSERT INTO bank_statement_lines (organization_id, statement_id, money_account_id, line_no, line_date, "
            "description, reference, amount, balance, dedupe_key) VALUES (:org, :s, :a, :no, :d, :desc, :ref, :amt, "
            ":bal, :k)"),
            [{"org": org, "s": sid, "a": account_id, "no": i, "d": ln["date"], "desc": ln["description"],
              "ref": ln["reference"], "amt": ln["amount"], "bal": ln["balance"], "k": k}
             for i, (ln, k) in enumerate(new, start=1)])
    summary["statement_id"] = sid
    summary["matched"] = await auto_match(conn, org, account_id, user_id)
    return summary


async def _line(conn: AsyncConnection, org: uuid.UUID, line_id: uuid.UUID) -> dict[str, Any]:
    row = (await conn.execute(text(
        "SELECT * FROM bank_statement_lines WHERE id = :id AND organization_id = :org"),
        {"id": line_id, "org": org})).mappings().first()
    if row is None:
        raise StatementError("Statement line not found.")
    return dict(row)


async def match(conn: AsyncConnection, org: uuid.UUID, user_id: uuid.UUID, line_id: uuid.UUID,
                money_id: uuid.UUID) -> None:
    ln = await _line(conn, org, line_id)
    if ln["status"] != "open":
        raise StatementError("That line is already settled; undo it first.")
    m = next((x for x in await movements(conn, org, ln["money_account_id"]) if x["id"] == money_id), None)
    if m is None:
        raise StatementError("That movement is not on this account.")
    if m["line_id"] is not None:
        raise StatementError("That movement is already matched to another statement line.")
    if m["undone"]:
        raise StatementError("That movement was undone in Finance; it never reached the bank.")
    if m["amount"] != abs(Decimal(ln["amount"])) or m["inflow"] != (Decimal(ln["amount"]) > 0):
        raise StatementError("The amounts differ: match a movement of the same amount and direction, or book the line.")
    await conn.execute(text(
        "UPDATE bank_statement_lines SET status = 'matched', money_transaction_id = :m, matched_by = :u, matched_at = now() "
        "WHERE id = :id"), {"m": money_id, "u": user_id, "id": line_id})


async def book(conn: AsyncConnection, org: uuid.UUID, user_id: uuid.UUID, line_id: uuid.UUID, ledger_id: uuid.UUID,
               project_id: uuid.UUID | None) -> uuid.UUID:
    """Record what the bank has and Mesiri does not: a money movement on the account (Finance's own write path),
    posted to ``ledger_id`` by the sweep."""
    from mesiri.infrastructure.postgres.repositories.finance import (
        PostgresMoneyTransactionRepository,
    )

    ln = await _line(conn, org, line_id)
    if ln["status"] != "open":
        raise StatementError("That line is already settled; undo it first.")
    led = (await conn.execute(text(
        "SELECT name, link_kind, is_active FROM ledgers WHERE id = :l AND organization_id = :org"),
        {"l": ledger_id, "org": org})).mappings().first()
    if led is None:
        raise StatementError("That ledger is not in your chart of accounts.")
    if led["link_kind"] == "money_account":
        raise StatementError("Money between your own accounts is a transfer: record it in Finance › Money, then match.")
    if not led["is_active"]:
        raise StatementError(f"{led['name']} is switched off.")
    amount = Decimal(ln["amount"])
    booking_id = uuid.uuid4()
    words = " · ".join(x for x in (led["name"], ln["description"]) if x)[:300]
    tx = await PostgresMoneyTransactionRepository(conn).record(
        organization_id=org, transaction_type="adjustment", amount=abs(amount), occurred_date=ln["line_date"],
        created_by=user_id, to_account_id=ln["money_account_id"] if amount > 0 else None,
        from_account_id=ln["money_account_id"] if amount < 0 else None, source_type=SOURCE, source_id=booking_id,
        description=words)
    await conn.execute(text(
        "INSERT INTO bank_bookings (id, money_transaction_id, organization_id, line_id, ledger_id, project_id) "
        "VALUES (:b, :m, :org, :id, :l, :p)"),
        {"b": booking_id, "m": tx.id, "org": org, "id": line_id, "l": ledger_id, "p": project_id})
    await conn.execute(text(
        "UPDATE bank_statement_lines SET status = 'booked', money_transaction_id = :m, booked_ledger_id = :l, "
        "project_id = :p, matched_by = :u, matched_at = now() WHERE id = :id"),
        {"m": tx.id, "l": ledger_id, "p": project_id, "u": user_id, "id": line_id})
    return tx.id


async def undo(conn: AsyncConnection, org: uuid.UUID, user_id: uuid.UUID, line_id: uuid.UUID) -> None:
    """Back to open: a match is dropped; a booking is reversed in Finance (a reversal movement, as Finance undoes)."""
    from mesiri.infrastructure.postgres.repositories.finance import (
        PostgresMoneyTransactionRepository,
    )

    ln = await _line(conn, org, line_id)
    if ln["status"] == "booked" and ln["money_transaction_id"]:
        amount = Decimal(ln["amount"])
        await PostgresMoneyTransactionRepository(conn).record(
            organization_id=org, transaction_type="reversal", amount=abs(amount), occurred_date=ln["line_date"],
            created_by=user_id, to_account_id=ln["money_account_id"] if amount < 0 else None,
            from_account_id=ln["money_account_id"] if amount > 0 else None, source_type="money_transaction",
            source_id=ln["money_transaction_id"], description="Booked from the bank statement, undone")
    await conn.execute(text(
        "UPDATE bank_statement_lines SET status = 'open', money_transaction_id = NULL, booked_ledger_id = NULL, "
        "project_id = NULL, matched_by = NULL, matched_at = NULL WHERE id = :id"), {"id": line_id})


async def ignore(conn: AsyncConnection, org: uuid.UUID, user_id: uuid.UUID, line_id: uuid.UUID) -> None:
    ln = await _line(conn, org, line_id)
    if ln["status"] != "open":
        raise StatementError("That line is already settled; undo it first.")
    await conn.execute(text(
        "UPDATE bank_statement_lines SET status = 'ignored', matched_by = :u, matched_at = now() WHERE id = :id"),
        {"u": user_id, "id": line_id})


async def overview(conn: AsyncConnection, org: uuid.UUID, account_id: uuid.UUID, today: datetime.date) -> dict[str, Any]:
    """One account: the lines by state, the movements the bank has not shown, suggestions for open lines, and the
    reconciliation statement on the last statement day."""
    await auto_match(conn, org, account_id, None)
    acct = await account(conn, org, account_id)
    lines = [dict(r) for r in (await conn.execute(text(
        "SELECT b.id, b.line_date AS date, b.description, b.reference, b.amount, b.balance, b.status, "
        "b.money_transaction_id, l.name AS booked_ledger, b.statement_id, u.full_name AS settled_by, b.matched_at "
        "FROM bank_statement_lines b LEFT JOIN ledgers l ON l.id = b.booked_ledger_id "
        "LEFT JOIN users u ON u.id = b.matched_by WHERE b.organization_id = :org AND b.money_account_id = :a "
        "ORDER BY b.line_date, b.line_no"), {"org": org, "a": account_id})).mappings()]
    statements = [dict(r) for r in (await conn.execute(text(
        "SELECT s.id, s.file_name, s.period_from, s.period_to, s.closing_balance, s.lines, s.skipped, s.created_at, "
        "u.full_name AS uploaded_by FROM bank_statements s LEFT JOIN users u ON u.id = s.created_by "
        "WHERE s.organization_id = :org AND s.money_account_id = :a ORDER BY s.period_to DESC, s.created_at DESC"),
        {"org": org, "a": account_id})).mappings()]
    moves = await movements(conn, org, account_id)
    by_id = {m["id"]: m for m in moves}
    for ln in lines:
        ln["amount"] = Decimal(ln["amount"])
        m = by_id.get(ln["money_transaction_id"])
        ln["movement"] = ({"id": m["id"], "date": m["date"], "description": m["description"], "party": m["party"],
                           "type": m["type"]} if m else None)
        ln["suggestions"] = []
        if ln["status"] == "open":
            ln["suggestions"] = [
                {"id": c["id"], "date": c["date"], "amount": c["amount"], "description": c["description"],
                 "party": c["party"]}
                for c in moves if c["line_id"] is None and not c["undone"] and c["amount"] == abs(ln["amount"])
                and c["inflow"] == (ln["amount"] > 0) and abs((c["date"] - ln["date"]).days) <= 15][:5]
    last_day = max((ln["date"] for ln in lines), default=None)
    first_day = min((ln["date"] for ln in lines), default=None)
    opening = Decimal(acct["opening_balance"] or 0)
    start = acct["opening_balance_date"]

    def books_on(day: datetime.date) -> Decimal:
        bal = opening if (start is None or start <= day) else _ZERO
        for m in moves:
            if m["date"] <= day:
                bal += m["amount"] if m["inflow"] else -m["amount"]
        return bal

    not_in_bank = [m for m in moves if m["line_id"] is None and not m["undone"] and first_day is not None and first_day <= m["date"]
                   and (last_day is None or m["date"] <= last_day)]
    reco = None
    if last_day is not None:
        stated = next((s["closing_balance"] for s in statements if s["period_to"] == last_day
                       and s["closing_balance"] is not None), None)
        if stated is None:
            stated = next((ln["balance"] for ln in reversed(lines) if ln["balance"] is not None), None)
        books = books_on(last_day)
        out_not_shown = sum((m["amount"] for m in not_in_bank if not m["inflow"]), _ZERO)
        in_not_shown = sum((m["amount"] for m in not_in_bank if m["inflow"]), _ZERO)
        open_in = sum((ln["amount"] for ln in lines if ln["status"] == "open" and ln["amount"] > 0), _ZERO)
        open_out = -sum((ln["amount"] for ln in lines if ln["status"] == "open" and ln["amount"] < 0), _ZERO)
        explained = books + out_not_shown - in_not_shown + open_in - open_out
        reco = {"as_of": last_day, "books": books, "paid_not_in_bank": out_not_shown,
                "received_not_in_bank": in_not_shown, "bank_only_in": open_in, "bank_only_out": open_out,
                "explained_bank": explained, "statement": Decimal(stated) if stated is not None else None,
                "difference": (Decimal(stated) - explained) if stated is not None else None}
    counts = Counter(ln["status"] for ln in lines)
    total = len(lines)
    return {"account": {"id": acct["id"], "name": acct["name"], "type": acct["account_type"]},
            "statements": statements, "lines": lines, "not_in_bank": not_in_bank,
            "counts": {k: counts.get(k, 0) for k in ("open", "matched", "booked", "ignored")}, "total": total,
            "reconciled_pct": round(100 * (total - counts.get("open", 0)) / total) if total else None,
            "reconciliation": reco, "books_today": books_on(today)}


async def accounts_summary(conn: AsyncConnection, org: uuid.UUID) -> list[dict[str, Any]]:
    """Each bank account (and cash box) with its statement lines: open, and the last statement day. The TDS payable
    account holds money owed to the government, not money in a bank: it has no statement."""
    from mesiri.domains.subcontracts.store import TDS_ACCOUNT

    return [dict(r) for r in (await conn.execute(text(
        "SELECT a.id, a.name, a.account_type, "
        "(SELECT COUNT(*) FROM bank_statement_lines b WHERE b.money_account_id = a.id) AS lines, "
        "(SELECT COUNT(*) FROM bank_statement_lines b WHERE b.money_account_id = a.id AND b.status = 'open') AS open, "
        "(SELECT MAX(b.line_date) FROM bank_statement_lines b WHERE b.money_account_id = a.id) AS last_line "
        "FROM money_accounts a WHERE a.organization_id = :org AND a.status = 'active' AND a.name <> :tds "
        "ORDER BY (a.account_type = 'bank') DESC, a.name"), {"org": org, "tds": TDS_ACCOUNT})).mappings()]
