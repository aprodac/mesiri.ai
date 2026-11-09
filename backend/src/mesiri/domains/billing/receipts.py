"""Money received from clients (NXT-03): the ``client_receipts`` table (migration 0529) and what clients owe.

Reads ``ra_bills`` (``bills.list_bills``: the stored net of each bill sent) and the receipts, and settles them with
``receivables.py``. No balance is stored: what is owed is always worked out from the bills and the money received.

**The money lands in the account (ACC, 9 Nov 2026).** A receipt is money into a company account, so it also writes
the account's money movement (``money_transactions``, ``fund_received`` with ``source_type`` ``client_receipt``), the
one place account balances come from; cancelling it writes the reversal. Before, the bank balance on Finance › Money
never showed what clients paid (migration 0530 wrote the movements for receipts recorded until then).
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.domains.billing import bills as bill_store
from mesiri.domains.billing import receivables

_SELECT = (
    "SELECT r.id, r.project_id, p.name AS project, r.client_id, cl.name AS client, r.ra_bill_id, b.number AS bill_number, "
    "r.kind, r.amount, r.received_on, r.account_id, a.name AS account, a.account_type, r.method, r.reference, r.notes, "
    "r.status, r.created_at, u.full_name AS recorded_by FROM client_receipts r JOIN projects p ON p.id = r.project_id "
    "LEFT JOIN clients cl ON cl.id = r.client_id LEFT JOIN ra_bills b ON b.id = r.ra_bill_id "
    "JOIN money_accounts a ON a.id = r.account_id LEFT JOIN users u ON u.id = r.created_by "
    "WHERE r.organization_id = :org"
)


async def list_receipts(conn: AsyncConnection, org: uuid.UUID, project_ids: set | None, *,
                        date_from: datetime.date | None = None, date_to: datetime.date | None = None,
                        confirmed_only: bool = False) -> list[dict[str, Any]]:
    sql, params = _SELECT, {"org": org}
    if project_ids is not None:
        sql += " AND r.project_id = ANY(:ps)"
        params["ps"] = list(project_ids)
    if date_from is not None:
        sql += " AND r.received_on >= :f"
        params["f"] = date_from
    if date_to is not None:
        sql += " AND r.received_on <= :t"
        params["t"] = date_to
    if confirmed_only:
        sql += " AND r.status = 'confirmed'"
    rows = [dict(r) for r in (await conn.execute(text(sql + " ORDER BY r.received_on DESC, r.created_at DESC"),
                                                 params)).mappings()]
    for r in rows:
        r["bill_ref"] = bill_store.ref(r["bill_number"]) if r["bill_number"] else None
    return rows


async def get_receipt(conn: AsyncConnection, org: uuid.UUID, receipt_id: uuid.UUID) -> dict[str, Any] | None:
    rows = (await conn.execute(text(_SELECT + " AND r.id = :id"), {"org": org, "id": receipt_id})).mappings().all()
    return dict(rows[0]) if rows else None


#: ``money_transactions.source_type`` of a receipt's money movement (and its reversal).
MONEY_SOURCE = "client_receipt"


def _words(client: str | None, bill_ref: str | None, kind: str) -> str:
    what = {"bill": f"against {bill_ref}", "on_account": "on account", "advance": "mobilisation advance"}[kind]
    return " · ".join(x for x in ("Received from client", client, what) if x)


async def record(conn: AsyncConnection, org: uuid.UUID, values: dict[str, Any], user_id: uuid.UUID) -> uuid.UUID:
    from mesiri.infrastructure.postgres.repositories.finance import (
        PostgresMoneyTransactionRepository,
    )

    receipt_id = (await conn.execute(text(
        "INSERT INTO client_receipts (organization_id, project_id, client_id, ra_bill_id, kind, amount, received_on, "
        "account_id, method, reference, notes, created_by) VALUES (:org, :project_id, :client_id, :ra_bill_id, :kind, "
        ":amount, :received_on, :account_id, :method, :reference, :notes, :by) RETURNING id"),
        {"org": org, "by": user_id, **values})).scalar_one()
    row = await get_receipt(conn, org, receipt_id)
    await PostgresMoneyTransactionRepository(conn).record(
        organization_id=org, transaction_type="fund_received", amount=Decimal(values["amount"]),
        occurred_date=values["received_on"], created_by=user_id, to_account_id=values["account_id"],
        source_type=MONEY_SOURCE, source_id=receipt_id,
        description=_words(row["client"] if row else None,
                           bill_store.ref(row["bill_number"]) if row and row["bill_number"] else None, values["kind"]))
    return receipt_id


async def cancel(conn: AsyncConnection, receipt_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Marked cancelled (kept), and the money taken back out of the account it went into."""
    from mesiri.infrastructure.postgres.repositories.finance import (
        PostgresMoneyTransactionRepository,
    )

    row = (await conn.execute(text(
        "UPDATE client_receipts SET status = 'cancelled', cancelled_by = :u, cancelled_at = now() "
        "WHERE id = :id AND status = 'confirmed' RETURNING organization_id, amount, account_id"),
        {"id": receipt_id, "u": user_id})).mappings().first()
    if row is None:
        return
    moved = (await conn.execute(text(
        "SELECT 1 FROM money_transactions WHERE source_type = :s AND source_id = :id AND transaction_type = 'fund_received'"),
        {"s": MONEY_SOURCE, "id": receipt_id})).first()
    if moved:
        await PostgresMoneyTransactionRepository(conn).record(
            organization_id=row["organization_id"], transaction_type="reversal", amount=Decimal(row["amount"]),
            occurred_date=datetime.date.today(), created_by=user_id, from_account_id=row["account_id"],
            source_type=MONEY_SOURCE, source_id=receipt_id, description="Client receipt cancelled")


async def owed(conn: AsyncConnection, org: uuid.UUID, project_ids: set | None, today: datetime.date) -> dict[str, Any]:
    """Bills settled against the money received, and the clients' rows (``receivables.by_client``)."""
    from mesiri.domains.billing import contracts

    bills = await bill_store.list_bills(conn, org, project_ids)
    receipts = await list_receipts(conn, org, project_ids, confirmed_only=True)
    settled = receivables.settle(
        [{"id": b["id"], "number": b["number"], "ref": b["ref"], "project_id": b["project_id"],
          "project": b.get("project_name"), "client_id": b.get("client_id"), "bill_date": b["bill_date"],
          "net": Decimal(b["net"] or 0), "status": b["status"]} for b in bills],
        receipts, today)
    clients = {c["id"]: c for c in await contracts.list_clients(conn, org)}
    project_client = {r["project_id"]: r["client_id"] for r in (await conn.execute(text(
        "SELECT project_id, client_id FROM project_contracts WHERE organization_id = :org"), {"org": org})).mappings()}
    rows = receivables.by_client(settled, clients, project_client)
    last = {}
    for r in receipts:
        key = r["client_id"] or project_client.get(r["project_id"])
        last.setdefault(key, r["received_on"])
    for row in rows:
        row["last_received_on"] = last.get(row["client_id"])
    return {"bills": settled["bills"], "clients": rows}
