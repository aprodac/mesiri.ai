"""Payments received from the client (END-02): reads and writes. The money is ``receivables.py``.

Every function takes the request's connection and never commits.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.domains.billing import receivables
from mesiri.domains.billing.bills import ref

KINDS = ("bill", "advance", "retention", "other")
KIND_WORDS = {"bill": "Against a bill", "advance": "Advance", "retention": "Retention released", "other": "Other"}

_PAY = ("cp.id, cp.project_id, p.name AS project_name, cp.client_id, cl.name AS client_name, cp.ra_bill_id, "
        "b.number AS bill_number, cp.kind, cp.received_on, cp.amount, cp.mode, cp.reference, cp.notes, cp.created_at")


async def list_payments(conn: AsyncConnection, org: uuid.UUID, project_ids: set | None) -> list[dict[str, Any]]:
    sql = (f"SELECT {_PAY} FROM client_payments cp JOIN projects p ON p.id = cp.project_id "  # noqa: S608
           "LEFT JOIN clients cl ON cl.id = cp.client_id LEFT JOIN ra_bills b ON b.id = cp.ra_bill_id "
           "WHERE cp.organization_id = :org")
    params: dict = {"org": org}
    if project_ids is not None:
        sql += " AND cp.project_id = ANY(:ps)"
        params["ps"] = list(project_ids)
    rows = [dict(r) for r in (await conn.execute(text(sql + " ORDER BY cp.received_on DESC, cp.created_at DESC"),
                                                 params)).mappings()]
    for r in rows:
        r["bill_ref"] = ref(r.pop("bill_number")) if r["bill_number"] else None
        r["kind_label"] = KIND_WORDS[r["kind"]]
    return rows


async def get_payment(conn: AsyncConnection, org: uuid.UUID, payment_id: uuid.UUID) -> dict[str, Any] | None:
    rows = [r for r in await list_payments(conn, org, None) if r["id"] == payment_id]
    return rows[0] if rows else None


async def add_payment(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID, values: dict[str, Any],
                      user_id: uuid.UUID) -> Any:
    client_id = (await conn.execute(text(
        "SELECT client_id FROM project_contracts WHERE organization_id = :org AND project_id = :p"),
        {"org": org, "p": project_id})).scalar()
    return (await conn.execute(text(
        "INSERT INTO client_payments (organization_id, project_id, client_id, ra_bill_id, kind, received_on, amount, "
        "mode, reference, notes, created_by) VALUES (:org, :p, :client, :bill, :kind, :on, :amount, :mode, :ref, "
        ":notes, :by) RETURNING id"),
        {"org": org, "p": project_id, "client": client_id, "bill": values.get("ra_bill_id"), "kind": values["kind"],
         "on": values["received_on"], "amount": values["amount"], "mode": values.get("mode"),
         "ref": values.get("reference"), "notes": values.get("notes"), "by": user_id})).scalar_one()


async def delete_payment(conn: AsyncConnection, payment_id: uuid.UUID) -> None:
    await conn.execute(text("DELETE FROM client_payments WHERE id = :id"), {"id": payment_id})


async def bill_has_payments(conn: AsyncConnection, bill_id: uuid.UUID) -> bool:
    return bool((await conn.execute(text("SELECT 1 FROM client_payments WHERE ra_bill_id = :b LIMIT 1"),
                                    {"b": bill_id})).scalar())


async def project_money(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID,
                        today: datetime.date) -> dict[str, Any]:
    """One project's receivable (``receivables.project_receivable``) with its name, client and contract terms."""
    head = (await conn.execute(text(
        "SELECT p.id, p.name, p.stage, p.handed_over_on, c.contract_value, c.mobilisation_advance, "
        "c.defect_liability_months, cl.id AS client_id, cl.name AS client_name FROM projects p "
        "LEFT JOIN project_contracts c ON c.project_id = p.id LEFT JOIN clients cl ON cl.id = c.client_id "
        "WHERE p.organization_id = :org AND p.id = :p"), {"org": org, "p": project_id})).mappings().first()
    bills = [dict(r) for r in (await conn.execute(text(
        "SELECT id, number, status, bill_date, net, certified_amount, retention FROM ra_bills "
        "WHERE organization_id = :org AND project_id = :p"), {"org": org, "p": project_id})).mappings()]
    for b in bills:
        b["ref"] = ref(b["number"])
    pays = (await conn.execute(text(
        "SELECT kind, amount, ra_bill_id FROM client_payments WHERE organization_id = :org AND project_id = :p"),
        {"org": org, "p": project_id})).mappings().all()
    money = receivables.project_receivable(bills, pays, today, head["mobilisation_advance"], head["handed_over_on"],
                                           head["defect_liability_months"])
    return {"project": {"id": head["id"], "name": head["name"], "stage": head["stage"]},
            "client": {"id": head["client_id"], "name": head["client_name"]} if head["client_id"] else None,
            "contract_value": head["contract_value"], "has_advance": bool(head["mobilisation_advance"]),
            "handed_over_on": head["handed_over_on"], "defect_liability_months": head["defect_liability_months"],
            **money}


async def projects_with_money(conn: AsyncConnection, org: uuid.UUID, project_ids: set | None) -> list[uuid.UUID]:
    """Projects that have a contract, a bill or a payment: the ones a receivables list has something to say about."""
    rows = (await conn.execute(text(
        "SELECT id FROM projects p WHERE organization_id = :org AND (EXISTS (SELECT 1 FROM ra_bills b WHERE "
        "b.project_id = p.id AND b.status IN ('submitted', 'certified')) OR EXISTS (SELECT 1 FROM client_payments cp "
        "WHERE cp.project_id = p.id) OR EXISTS (SELECT 1 FROM project_contracts c WHERE c.project_id = p.id AND "
        "COALESCE(c.mobilisation_advance, 0) > 0)) ORDER BY lower(name)"), {"org": org})).scalars().all()
    return [r for r in rows if project_ids is None or r in project_ids]


def total(rows: list[dict[str, Any]], key: str) -> Decimal:
    return sum((Decimal(r[key]) for r in rows), Decimal(0))
