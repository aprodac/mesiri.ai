"""ACC-13 / FB-03: bank reconciliation. A bank statement imported, each line matched to the books.

**The statement** is the CSV net banking gives (SBI, HDFC, ICICI, Axis, Federal and the rest all export one). Banks
put a few lines of account details above the table and name the columns their own way, so ``parse`` finds the header
row by its words and reads:

- the date (``Txn Date``, ``Transaction Date``, ``Value Date``, ``Date``): 05/11/2026, 05-11-2026, 05-Nov-2026,
  05 Nov 26, 2026-11-05 (day first, as Indian banks write it);
- the words (``Description``, ``Narration``, ``Particulars``, ``Remarks``);
- the reference (``Ref No./Cheque No.``, ``Chq./Ref.No.``, ``Reference``, ``UTR``);
- the money: ``Withdrawal``/``Debit`` and ``Deposit``/``Credit`` columns, or one ``Amount`` column with ``Dr``/``Cr``
  beside it (or a minus sign);
- the ``Balance`` after it, when given.

A line's amount is **+ money in, − money out** (the bank account's side).

**The books' side** is every journal line on the account's ledger (the sweep posts every money movement there, and the
accountant's own vouchers land there too), one per entry: + debit (money in), − credit (money out).

**Auto-match** pairs a statement line with a book entry of exactly the same amount, dated within ``DAY_WINDOW`` days
(cheques clear late, the books are dated when the money was recorded); when several fit, the one whose words hold the
line's reference (a cheque or UTR number) wins, then the closest date. One to one: a book entry matches one statement line. What is left is the
accountant's: match by hand, book it (bank charges, interest: a voucher in one tap, then matched), or ignore it with a
reason.

``parse``, ``line_key`` and ``auto_match`` are pure; the rest take the request's connection and never commit.
"""

from __future__ import annotations

import csv
import datetime
import hashlib
import io
import re
import uuid
from collections.abc import Iterable, Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

DAY_WINDOW = 5
MAX_LINES = 5000
_ZERO = Decimal(0)

_DATE_COLS = ("txn date", "transaction date", "tran date", "date", "value date", "posting date", "value dt")
_DESC_COLS = ("description", "narration", "particulars", "remarks", "transaction remarks", "details",
              "transaction details")
_REF_COLS = ("ref no./cheque no.", "chq./ref.no.", "chq/ref number", "cheque no.", "cheque no", "ref no", "ref no.",
             "reference", "reference no", "utr", "chq no", "instrument no", "cheque number")
_OUT_COLS = ("withdrawal", "withdrawals", "withdrawal amt.", "withdrawal amount", "withdrawal amount (inr )",
             "debit", "debit amount", "debits", "dr amount", "withdrawal (dr)", "debit(inr)")
_IN_COLS = ("deposit", "deposits", "deposit amt.", "deposit amount", "deposit amount (inr )", "credit",
            "credit amount", "credits", "cr amount", "deposit (cr)", "credit(inr)")
_AMOUNT_COLS = ("amount", "transaction amount", "amount (inr)", "txn amount")
_DRCR_COLS = ("dr/cr", "cr/dr", "type", "dr / cr", "debit/credit")
_BALANCE_COLS = ("balance", "closing balance", "balance (inr)", "available balance", "running balance")

_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov",
                                       "dec"), start=1)}


class StatementError(ValueError):
    """The file can't be read as a statement; the message says why, in words."""


def _norm(cell: str) -> str:
    return " ".join(str(cell or "").strip().lower().replace("﻿", "").split())


def _find(header: list[str], names: Iterable[str]) -> int | None:
    names = tuple(names)
    for i, h in enumerate(header):
        if h in names:
            return i
    for i, h in enumerate(header):  # "withdrawal amount (inr)" -> withdrawal
        if any(h.startswith(n) for n in names):
            return i
    return None


def parse_date(value: str) -> datetime.date | None:
    v = str(value or "").strip()
    if not v:
        return None
    v = v.split(" ")[0] if re.match(r"^\d{4}-\d{2}-\d{2}[ T]", v) else v
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", v)
    if m:
        y, mo, d = (int(x) for x in m.groups())
        return _safe(y, mo, d)
    m = re.match(r"^(\d{1,2})[/\-. ](\d{1,2})[/\-. ](\d{2,4})$", v)
    if m:
        d, mo, y = (int(x) for x in m.groups())
        return _safe(_year(y), mo, d)
    m = re.match(r"^(\d{1,2})[/\-. ]([A-Za-z]{3})[A-Za-z]*[/\-. ,]+(\d{2,4})$", v)
    if m:
        d, mon, y = m.groups()
        mo = _MONTHS.get(mon.lower())
        return _safe(_year(int(y)), mo, int(d)) if mo else None
    return None


def _year(y: int) -> int:
    return 2000 + y if y < 100 else y


def _safe(y: int, mo: int, d: int) -> datetime.date | None:
    try:
        return datetime.date(y, mo, d)
    except ValueError:
        return None


def parse_amount(value: str) -> Decimal | None:
    """'1,25,000.50' -> 125000.50; '(500)' and '-500' -> -500; '' / '-' -> None. 'Cr' / 'Dr' suffixes are left to the
    caller (they say the side, not the sign)."""
    v = str(value or "").strip().replace(",", "").replace("₹", "").replace("INR", "").strip()
    v = re.sub(r"\s*(cr|dr)\.?$", "", v, flags=re.IGNORECASE)
    if v in ("", "-", "--", "0.00-"):
        return None
    neg = v.startswith("(") and v.endswith(")")
    v = v.strip("()")
    try:
        n = Decimal(v)
    except InvalidOperation:
        return None
    return -n if neg else n


def _side(value: str) -> str | None:
    v = str(value or "").strip().lower().rstrip(".")
    if v.endswith("cr") or v in ("c", "credit", "deposit"):
        return "in"
    if v.endswith("dr") or v in ("d", "debit", "withdrawal"):
        return "out"
    return None


def parse(content: str) -> dict[str, Any]:
    """The statement's lines (``date``, ``description``, ``reference``, ``amount`` +in/−out, ``balance``), the lines
    that could not be read (``skipped``, with the row number and why), and the dates covered."""
    if not content or not content.strip():
        raise StatementError("The file is empty.")
    sample = content[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(content), dialect))
    head_at = None
    for i, row in enumerate(rows[:40]):
        header = [_norm(c) for c in row]
        if _find(header, _DATE_COLS) is not None and (
                _find(header, _OUT_COLS) is not None or _find(header, _IN_COLS) is not None
                or _find(header, _AMOUNT_COLS) is not None):
            head_at = i
            break
    if head_at is None:
        raise StatementError("No table with a date and an amount column was found. Download the statement from net "
                             "banking as CSV (Excel files: save as CSV first).")
    header = [_norm(c) for c in rows[head_at]]
    col = {
        "date": _find(header, _DATE_COLS),
        "desc": _find(header, _DESC_COLS),
        "ref": _find(header, _REF_COLS),
        "out": _find(header, _OUT_COLS),
        "in": _find(header, _IN_COLS),
        "amount": _find(header, _AMOUNT_COLS),
        "drcr": _find(header, _DRCR_COLS),
        "balance": _find(header, _BALANCE_COLS),
    }

    def cell(row: list[str], key: str) -> str:
        i = col[key]
        return row[i].strip() if i is not None and i < len(row) else ""

    lines: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for n, row in enumerate(rows[head_at + 1:], start=head_at + 2):
        if not any(c.strip() for c in row):
            continue
        day = parse_date(cell(row, "date"))
        if day is None:
            # Totals, "closing balance", page footers: not a transaction. Said only when it looks like one.
            if any(parse_amount(cell(row, k)) for k in ("out", "in", "amount")) and cell(row, "date"):
                skipped.append({"row": n, "why": f"'{cell(row, 'date')}' is not a date"})
            continue
        amount = None
        if col["out"] is not None or col["in"] is not None:
            out, inn = parse_amount(cell(row, "out")), parse_amount(cell(row, "in"))
            if out and not inn:
                amount = -abs(out)
            elif inn and not out:
                amount = abs(inn)
        if amount is None and col["amount"] is not None:
            raw = cell(row, "amount")
            a = parse_amount(raw)
            if a:
                side = _side(cell(row, "drcr")) or _side(raw)
                amount = -abs(a) if side == "out" else abs(a) if side == "in" else a
        if not amount:
            skipped.append({"row": n, "why": "no amount in or out"})
            continue
        lines.append({"date": day, "description": " ".join(cell(row, "desc").split()),
                      "reference": cell(row, "ref") or None, "amount": amount,
                      "balance": parse_amount(cell(row, "balance"))})
        if len(lines) > MAX_LINES:
            raise StatementError(f"More than {MAX_LINES} lines: import a shorter period at a time.")
    if not lines:
        raise StatementError("The table has no transactions Mesiri could read.")
    days = [ln["date"] for ln in lines]
    return {"lines": lines, "skipped": skipped, "from": min(days), "to": max(days)}


def line_key(ln: Mapping[str, Any], seen: int = 0) -> str:
    """What makes a statement line the same line when a statement is imported again. ``seen`` tells apart two
    identical lines on one day in one file (two ₹500 charges)."""
    raw = "|".join(str(x) for x in (ln["date"], Decimal(ln["amount"]).quantize(Decimal("0.01")),
                                    (ln.get("description") or "").lower(), ln.get("reference") or "",
                                    ln.get("balance") if ln.get("balance") is not None else "", seen))
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def keyed(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    out = []
    for ln in lines:
        base = line_key(ln)
        n = counts.get(base, 0)
        counts[base] = n + 1
        out.append({**ln, "line_key": base if n == 0 else line_key(ln, n)})
    return out


def _ref_in(ref: str | None, words: str | None) -> bool:
    ref = re.sub(r"\W", "", (ref or "")).lower()
    return len(ref) >= 4 and ref in re.sub(r"\W", "", (words or "")).lower()


def auto_match(statement: Iterable[Mapping[str, Any]], books: Iterable[Mapping[str, Any]],
               window: int = DAY_WINDOW) -> list[tuple[Any, Any]]:
    """(statement line id, book entry key) pairs: same amount, dates within ``window`` days; the line's reference
    found in the entry's words first, then the closest date. One to one; the earliest statement lines choose first."""
    free = list(books)
    taken: set[Any] = set()
    pairs = []
    for s in sorted(statement, key=lambda x: (x["date"], str(x["id"]))):
        amount = Decimal(s["amount"])
        fits = [b for b in free if b["key"] not in taken and Decimal(b["amount"]) == amount
                and abs((b["date"] - s["date"]).days) <= window]
        if not fits:
            continue
        best = min(fits, key=lambda b: (not _ref_in(s.get("reference"), b.get("words")),
                                        abs((b["date"] - s["date"]).days), str(b["key"])))
        taken.add(best["key"])
        pairs.append((s["id"], best["key"]))
    return pairs


# -- Reads and writes ------------------------------------------------------------------------------------------------

async def bank_ledger(conn: AsyncConnection, org: uuid.UUID, account_id: Any) -> uuid.UUID | None:
    return (await conn.execute(text(
        "SELECT id FROM ledgers WHERE organization_id = :org AND link_kind = 'money_account' AND link_id = :a"),
        {"org": org, "a": account_id})).scalar()


async def account(conn: AsyncConnection, org: uuid.UUID, account_id: Any) -> dict[str, Any] | None:
    row = (await conn.execute(text(
        "SELECT id, name, account_type, status FROM money_accounts WHERE organization_id = :org AND id = :a"),
        {"org": org, "a": account_id})).mappings().first()
    return dict(row) if row else None


async def book_entries(conn: AsyncConnection, org: uuid.UUID, ledger_id: Any, date_from: datetime.date,
                       date_to: datetime.date) -> list[dict[str, Any]]:
    """Each journal entry on the bank's ledger in the period: + money in, − money out, its voucher and words."""
    rows = (await conn.execute(text(
        "SELECT e.id AS entry_id, e.source_kind, e.source_id, e.source_part, e.entry_date AS date, e.voucher_type, "
        "e.financial_year, e.number, e.narration AS words, SUM(l.debit - l.credit) AS amount "
        "FROM journal_lines l JOIN journal_entries e ON e.id = l.entry_id "
        "WHERE l.organization_id = :org AND l.ledger_id = :led AND e.entry_date BETWEEN :f AND :t "
        "GROUP BY e.id ORDER BY e.entry_date, e.number"),
        {"org": org, "led": ledger_id, "f": date_from, "t": date_to})).mappings().all()
    out = []
    for r in rows:
        b = dict(r)
        if Decimal(b["amount"]) == 0:
            continue
        b["key"] = _entry_key(b)
        b["ref"] = f"{b['voucher_type'][:3].upper()}/{b['financial_year']}/{b['number']}"
        out.append(b)
    return out


def _entry_key(e: Mapping[str, Any]) -> str:
    """How a match names its entry: by source for a swept entry (a re-post keeps it), by id for a manual voucher."""
    if e["source_kind"] == "manual" or e.get("source_id") is None:
        return f"entry:{e['entry_id']}"
    return f"src:{e['source_kind']}:{e['source_id']}:{e['source_part']}"


def _line_entry_key(ln: Mapping[str, Any]) -> str | None:
    if ln["status"] != "matched":
        return None
    if ln.get("source_kind") and ln["source_kind"] != "manual" and ln.get("source_id"):
        return f"src:{ln['source_kind']}:{ln['source_id']}:{ln['source_part']}"
    return f"entry:{ln['entry_id']}"


async def statement_lines(conn: AsyncConnection, org: uuid.UUID, account_id: Any, date_from: datetime.date | None = None,
                          date_to: datetime.date | None = None) -> list[dict[str, Any]]:
    sql = ("SELECT l.id, l.txn_date AS date, l.description, l.reference, l.amount, l.balance, l.status, l.source_kind, "
           "l.source_id, l.source_part, l.entry_id, l.matched_how, l.note, l.import_id, u.full_name AS decided_by "
           "FROM bank_statement_lines l LEFT JOIN users u ON u.id = l.decided_by "
           "WHERE l.organization_id = :org AND l.account_id = :a")
    params: dict[str, Any] = {"org": org, "a": account_id}
    if date_from is not None:
        sql += " AND l.txn_date >= :f"
        params["f"] = date_from
    if date_to is not None:
        sql += " AND l.txn_date <= :t"
        params["t"] = date_to
    return [dict(r) for r in (await conn.execute(text(sql + " ORDER BY l.txn_date, l.created_at, l.id"),
                                                 params)).mappings()]


async def import_lines(conn: AsyncConnection, org: uuid.UUID, account_id: Any, parsed: dict[str, Any], file_name: str,
                       user_id: uuid.UUID) -> dict[str, Any]:
    """Store the parsed lines; a line already imported (same key) is counted, not added again."""
    lines = keyed(parsed["lines"])
    import_id = (await conn.execute(text(
        "INSERT INTO bank_statement_imports (organization_id, account_id, file_name, from_date, to_date, created_by) "
        "VALUES (:org, :a, :n, :f, :t, :by) RETURNING id"),
        {"org": org, "a": account_id, "n": file_name, "f": parsed["from"], "t": parsed["to"], "by": user_id})).scalar_one()
    added = 0
    for ln in lines:
        res = await conn.execute(text(
            "INSERT INTO bank_statement_lines (organization_id, account_id, import_id, txn_date, description, reference, "
            "amount, balance, line_key) VALUES (:org, :a, :imp, :d, :desc, :ref, :amt, :bal, :key) "
            "ON CONFLICT (account_id, line_key) DO NOTHING"),
            {"org": org, "a": account_id, "imp": import_id, "d": ln["date"], "desc": ln["description"],
             "ref": ln["reference"], "amt": ln["amount"], "bal": ln["balance"], "key": ln["line_key"]})
        added += res.rowcount
    await conn.execute(text("UPDATE bank_statement_imports SET lines_added = :a, lines_repeated = :r WHERE id = :id"),
                       {"a": added, "r": len(lines) - added, "id": import_id})
    return {"import_id": import_id, "added": added, "repeated": len(lines) - added}


async def _set_match(conn: AsyncConnection, line_id: Any, entry: Mapping[str, Any], how: str,
                     user_id: uuid.UUID | None) -> None:
    await conn.execute(text(
        "UPDATE bank_statement_lines SET status = 'matched', source_kind = :k, source_id = :s, source_part = :p, "
        "entry_id = :e, matched_how = :how, note = NULL, decided_by = :by, decided_at = now() WHERE id = :id"),
        {"k": entry["source_kind"], "s": entry["source_id"], "p": entry["source_part"], "e": entry["entry_id"],
         "how": how, "by": user_id, "id": line_id})


async def state(conn: AsyncConnection, org: uuid.UUID, account_id: Any, ledger_id: Any,
                date_from: datetime.date, date_to: datetime.date) -> dict[str, Any]:
    """The statement lines in the period with what each is matched to, the book entries no line is matched to, and
    the balances: the bank's closing balance (its last line's) against the books' at the same date."""
    lines = await statement_lines(conn, org, account_id, date_from, date_to)
    # A match may sit just outside the period (a cheque that cleared late): read the books a window wider.
    books = await book_entries(conn, org, ledger_id, date_from - datetime.timedelta(days=DAY_WINDOW * 3),
                               date_to + datetime.timedelta(days=DAY_WINDOW * 3)) if ledger_id else []
    by_key = {b["key"]: b for b in books}
    # A match whose entry is outside the wider window is still a match: read those entries by key.
    used: set[str] = set()
    for ln in lines:
        key = _line_entry_key(ln)
        ln["entry"] = None
        if key is None:
            continue
        b = by_key.get(key)
        if b is None:
            b = await _entry_by_key(conn, org, ledger_id, ln)
        if b is None:  # the record behind it was deleted: the line is open again
            ln["status"], ln["stale"] = "unmatched", True
            continue
        used.add(b["key"])
        ln["entry"] = {k: b[k] for k in ("entry_id", "ref", "date", "words", "amount")}
    open_books = [b for b in books if b["key"] not in used and date_from <= b["date"] <= date_to]
    closing = next((ln["balance"] for ln in reversed(lines) if ln["balance"] is not None), None)
    last_day = lines[-1]["date"] if lines else date_to
    book_balance = None
    if ledger_id:
        book_balance = (await conn.execute(text(
            "SELECT COALESCE(SUM(debit - credit), 0) FROM journal_lines WHERE organization_id = :org "
            "AND ledger_id = :led AND entry_date <= :d"), {"org": org, "led": ledger_id, "d": last_day})).scalar_one()
    counts = {s: sum(1 for ln in lines if ln["status"] == s) for s in ("unmatched", "matched", "ignored")}
    return {"lines": lines, "books_unmatched": open_books, "counts": counts, "statement_balance": closing,
            "book_balance": book_balance, "as_of": last_day,
            "in_unmatched": sum((Decimal(ln["amount"]) for ln in lines if ln["status"] == "unmatched"
                                 and Decimal(ln["amount"]) > 0), _ZERO),
            "out_unmatched": sum((-Decimal(ln["amount"]) for ln in lines if ln["status"] == "unmatched"
                                  and Decimal(ln["amount"]) < 0), _ZERO)}


async def _entry_by_key(conn: AsyncConnection, org: uuid.UUID, ledger_id: Any, ln: Mapping[str, Any]) -> dict | None:
    if not ledger_id:
        return None
    if ln.get("source_kind") and ln["source_kind"] != "manual" and ln.get("source_id"):
        where, params = ("e.source_kind = :k AND e.source_id = :s AND e.source_part = :p",
                         {"k": ln["source_kind"], "s": ln["source_id"], "p": ln["source_part"]})
    else:
        where, params = "e.id = :e", {"e": ln["entry_id"]}
    row = (await conn.execute(text(
        "SELECT e.id AS entry_id, e.source_kind, e.source_id, e.source_part, e.entry_date AS date, e.voucher_type, "
        "e.financial_year, e.number, e.narration AS words, SUM(l.debit - l.credit) AS amount "
        "FROM journal_lines l JOIN journal_entries e ON e.id = l.entry_id "
        f"WHERE l.organization_id = :org AND l.ledger_id = :led AND {where} GROUP BY e.id"),  # noqa: S608 (fixed)
        {"org": org, "led": ledger_id, **params})).mappings().first()
    if row is None:
        return None
    b = dict(row)
    b["key"] = _entry_key(b)
    b["ref"] = f"{b['voucher_type'][:3].upper()}/{b['financial_year']}/{b['number']}"
    return b


async def run_auto_match(conn: AsyncConnection, org: uuid.UUID, account_id: Any, ledger_id: Any,
                         user_id: uuid.UUID | None) -> int:
    """Match every open statement line that has one clear book entry. Returns how many were matched."""
    lines = await statement_lines(conn, org, account_id)
    if not lines or not ledger_id:
        return 0
    days = [ln["date"] for ln in lines]
    window = datetime.timedelta(days=DAY_WINDOW)
    books = await book_entries(conn, org, ledger_id, min(days) - window, max(days) + window)
    taken = {k for ln in lines if (k := _line_entry_key(ln))}
    free = [b for b in books if b["key"] not in taken]
    by_key = {b["key"]: b for b in free}
    pairs = auto_match([ln for ln in lines if ln["status"] == "unmatched"], free)
    for line_id, key in pairs:
        await _set_match(conn, line_id, by_key[key], "auto", user_id)
    return len(pairs)


async def get_line(conn: AsyncConnection, org: uuid.UUID, line_id: Any) -> dict[str, Any] | None:
    row = (await conn.execute(text(
        "SELECT id, account_id, txn_date AS date, description, reference, amount, status, source_kind, source_id, "
        "source_part, entry_id FROM bank_statement_lines WHERE organization_id = :org AND id = :id"),
        {"org": org, "id": line_id})).mappings().first()
    return dict(row) if row else None


async def match_by_hand(conn: AsyncConnection, org: uuid.UUID, line: Mapping[str, Any], ledger_id: Any,
                        entry_id: uuid.UUID, user_id: uuid.UUID, how: str = "manual") -> None:
    entry = await _entry_by_key(conn, org, ledger_id, {"entry_id": entry_id})
    if entry is None:
        raise StatementError("That voucher is not on this bank account's ledger.")
    if Decimal(entry["amount"]) != Decimal(line["amount"]):
        raise StatementError(f"The voucher is for {_rs(entry['amount'])} and the bank line {_rs(line['amount'])}: "
                             "only the same amount can be matched.")
    others = await statement_lines(conn, org, line["account_id"])
    if any(_line_entry_key(o) == entry["key"] and o["id"] != line["id"] for o in others):
        raise StatementError(f"{entry['ref']} is already matched to another bank line.")
    await _set_match(conn, line["id"], entry, how, user_id)


async def set_status(conn: AsyncConnection, line_id: Any, status: str, note: str | None, user_id: uuid.UUID) -> None:
    await conn.execute(text(
        "UPDATE bank_statement_lines SET status = :s, note = :n, source_kind = NULL, source_id = NULL, "
        "source_part = NULL, entry_id = NULL, matched_how = NULL, decided_by = :by, decided_at = now() WHERE id = :id"),
        {"s": status, "n": note, "by": user_id, "id": line_id})


def _rs(v: Any) -> str:
    n = Decimal(v)
    return f"{'−' if n < 0 else ''}₹{abs(n):,.2f}"
