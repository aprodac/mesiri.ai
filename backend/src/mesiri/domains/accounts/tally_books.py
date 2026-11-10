"""ACC-19: the Tally export from the posted journals, one source of truth (D-ACC3). When the Accounts module is on,
Finance › Tally export reads the books instead of reading expenses, payments, bills and receipts again
(``finance/tally.py``, NXT-12): what the CA imports is exactly what the trial balance shows, manual vouchers,
depreciation, the month-end accrual and changes after close included.

- **Masters**: every ledger used in the period under its group. Seeded groups are Tally's own primary groups, written
  with Tally's names whatever the company renamed them to (so the import finds them); a group the company added is
  sent as a GROUP master under its parent first.
- **Vouchers**: one per journal entry, its type (Journal, Payment, Receipt, Contra, Sales, Purchase), number
  (``JOU/2026-27/14``), date, narration and lines; the party is the supplier or client line when there is one.
  ``REMOTEID`` is the journal's id, which a re-posted entry keeps, so a second import of the same period updates
  rather than duplicates (Tally's "Alter" on the same REMOTEID).
"""

from __future__ import annotations

import datetime
import uuid
from collections import Counter
from decimal import Decimal
from typing import Any
from xml.sax.saxutils import escape

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.domains.accounts import chart
from mesiri.domains.finance.tally import _entry, _ledger

VCHTYPE = {"journal": "Journal", "payment": "Payment", "receipt": "Receipt", "contra": "Contra", "sales": "Sales",
           "purchase": "Purchase"}
#: Seeded group code -> Tally's own name (``chart.GROUPS`` uses Tally's names; this keeps them if renamed).
TALLY_GROUP = {code_: name for code_, name, _, _ in chart.GROUPS}


def _group_master(name: str, parent: str) -> str:
    return (f'<TALLYMESSAGE xmlns:UDF="TallyUDF"><GROUP NAME="{escape(name)}" ACTION="Create">'
            f"<NAME.LIST><NAME>{escape(name)}</NAME></NAME.LIST><PARENT>{escape(parent)}</PARENT>"
            "</GROUP></TALLYMESSAGE>")


def _voucher(e: dict[str, Any], lines: list[dict[str, Any]], party: str) -> str:
    kind = VCHTYPE[e["voucher_type"]]
    entries = "".join(_entry(ln["ledger"], Decimal(ln["debit"] or ln["credit"]), bool(Decimal(ln["debit"]))) for ln in lines)
    return (f'<TALLYMESSAGE xmlns:UDF="TallyUDF"><VOUCHER REMOTEID="mesiri-je-{e["id"]}" VCHTYPE="{kind}" '
            'ACTION="Create">'
            f"<DATE>{e['entry_date']:%Y%m%d}</DATE><VOUCHERTYPENAME>{kind}</VOUCHERTYPENAME>"
            f"<VOUCHERNUMBER>{escape(e['ref'])}</VOUCHERNUMBER><PARTYLEDGERNAME>{escape(party)}</PARTYLEDGERNAME>"
            f"<NARRATION>{escape(e['narration'] or '')}</NARRATION>" + entries + "</VOUCHER></TALLYMESSAGE>")


def build(company: str, groups: list[dict[str, Any]], ledgers: dict[Any, dict[str, Any]],
          entries: list[dict[str, Any]], lines: dict[Any, list[dict[str, Any]]]) -> tuple[str, dict[str, Any]]:
    """Pure: the XML and what it holds."""
    by_id = {g["id"]: g for g in groups}

    def gname(gid: Any) -> str:
        g = by_id[gid]
        return TALLY_GROUP.get(g["code"], g["name"]) if g["code"] else g["name"]

    used_ledgers = {ln["ledger_id"] for ls in lines.values() for ln in ls}
    custom: dict[Any, dict] = {}

    def need(gid: Any) -> None:
        g = by_id.get(gid)
        while g is not None and not g["code"] and g["id"] not in custom:
            custom[g["id"]] = g
            g = by_id.get(g["parent_id"])

    for lid in used_ledgers:
        need(ledgers[lid]["group_id"])
    # Parents before children, so Tally knows each parent when it reads the child.
    order, seen = [], set()

    def visit(g: dict) -> None:
        if g["id"] in seen:
            return
        if g["parent_id"] in custom:
            visit(custom[g["parent_id"]])
        seen.add(g["id"])
        order.append(g)
    for g in custom.values():
        visit(g)
    masters = [_group_master(g["name"], gname(g["parent_id"]) if g["parent_id"] else "Primary") for g in order]
    masters += [_ledger(ledgers[lid]["name"], gname(ledgers[lid]["group_id"]))
                for lid in sorted(used_ledgers, key=lambda x: ledgers[x]["name"].lower())]
    vouchers = []
    kinds: Counter = Counter()
    for e in entries:
        ls = [{**ln, "ledger": ledgers[ln["ledger_id"]]["name"]} for ln in lines.get(e["id"], [])]
        if not ls:
            continue
        party_line = next((ln for ln in ls if ledgers[ln["ledger_id"]]["link_kind"] in ("vendor", "client", "staff")),
                          ls[0])
        vouchers.append(_voucher(e, ls, party_line["ledger"]))
        kinds[e["voucher_type"]] += 1
    xml = ("<ENVELOPE><HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER><BODY><IMPORTDATA>"
           "<REQUESTDESC><REPORTNAME>All Masters</REPORTNAME>"
           f"<STATICVARIABLES><SVCURRENTCOMPANY>{escape(company)}</SVCURRENTCOMPANY></STATICVARIABLES></REQUESTDESC>"
           "<REQUESTDATA>" + "".join(masters) + "".join(vouchers) + "</REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>")
    total = sum((Decimal(ln["debit"]) for ls in lines.values() for ln in ls), Decimal(0))
    return xml, {"source": "books", "ledgers": len(used_ledgers), "groups": len(order), "vouchers": sum(kinds.values()),
                 "by_type": dict(kinds), "total": str(total.quantize(Decimal("0.01"))),
                 # The NXT-12 page's counts, so it reads the same either way.
                 "journals": kinds.get("journal", 0) + kinds.get("purchase", 0), "payments": kinds.get("payment", 0),
                 "sales": kinds.get("sales", 0), "receipts": kinds.get("receipt", 0), "contras": kinds.get("contra", 0),
                 "after_close": sum(1 for e in entries if e.get("after_close"))}


async def export(conn: AsyncConnection, org: uuid.UUID, company: str, date_from: datetime.date,
                 date_to: datetime.date) -> tuple[str, dict[str, Any]]:
    """The period's journals as Tally XML (the caller posts first)."""
    entries = [dict(r) for r in (await conn.execute(text(
        "SELECT id, entry_date, voucher_type, financial_year, number, narration, after_close FROM journal_entries "
        "WHERE organization_id = :org AND entry_date BETWEEN :f AND :t ORDER BY entry_date, voucher_type, number"),
        {"org": org, "f": date_from, "t": date_to})).mappings()]
    for e in entries:
        e["ref"] = f"{e['voucher_type'][:3].upper()}/{e['financial_year']}/{e['number']}"
    lines: dict[Any, list] = {}
    if entries:
        for r in (await conn.execute(text(
                "SELECT entry_id, ledger_id, debit, credit FROM journal_lines WHERE organization_id = :org "
                "AND entry_id = ANY(:ids) ORDER BY entry_id, line_no"), {"org": org, "ids": [e["id"] for e in entries]})).mappings():
            lines.setdefault(r["entry_id"], []).append(dict(r))
    groups = await chart.groups(conn, org)
    ledgers = {r["id"]: r for r in await chart.ledgers(conn, org)}
    return build(company, groups, ledgers, entries, lines)
