"""PRC-11 / CC-09 (8 Nov 2026): the office hears, on WhatsApp, what is waiting with suppliers.

Once a day, to the people who pay suppliers (owner, admin, super admin, finance: ``MONEY_MANAGE_ROLES``), when there is
something to act on: bills past their due date (the supplier's credit days) and deliveries with no bill for more than
``UNBILLED_DAYS`` days. One short note with the biggest ones; nothing when all is in order. Queued like the other
reminders (outside the 24-hour window it waits for their next message: no Meta template). Called from the one
scheduled check (``application/procurement/alerts.queue_reminders``).
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.roles import MONEY_MANAGE_ROLES
from mesiri.domains.vendors import ledger

RULE_KEY = "suppliers_waiting"
UNBILLED_DAYS = 15


def message(overdue: list[tuple[str, Decimal]], unbilled: list[tuple[str, Decimal | None]]) -> str | None:
    parts = []
    if overdue:
        total = sum((x for _, x in overdue), Decimal(0))
        top = ", ".join(f"{n} ₹{_rupees(x)}" for n, x in sorted(overdue, key=lambda t: -t[1])[:3])
        parts.append(f"₹{_rupees(total)} of supplier bills is overdue ({top}{', …' if len(overdue) > 3 else ''}).")
    if unbilled:
        priced = sum((x for _, x in unbilled if x is not None), Decimal(0))
        parts.append(f"{len(unbilled)} {'delivery has' if len(unbilled) == 1 else 'deliveries have'} had no bill for over "
                     f"{UNBILLED_DAYS} days{f' (₹{_rupees(priced)})' if priced else ''}: ask the suppliers for their bills.")
    if not parts:
        return None
    return "📋 Suppliers: " + " ".join(parts) + " Finance › Suppliers on the dashboard."


def _rupees(v: Decimal) -> str:
    n = str(int(v))
    head, tail = n[:-3], n[-3:]
    while len(head) > 2:
        tail = f"{head[-2:]},{tail}"
        head = head[:-2]
    return f"{head},{tail}" if head else tail


async def queue_supplier_reminders(conn: AsyncConnection, organization_id: uuid.UUID, today: datetime.date) -> int:
    from mesiri.infrastructure.postgres.repositories.notifications import (
        PostgresNotificationRepository,
    )

    entries, state = await ledger.fetch_entries(conn, organization_id, vendor_id=None, projects=None)
    overdue: dict = {}
    for v in state["vendors"].values():
        s = ledger.summarise(v, entries, state, today)
        if Decimal(s["overdue"]) > 0:
            overdue[v["name"]] = Decimal(s["overdue"])
    old = [(e["title"], e["owe"]) for e in entries if e["kind"] == "delivery" and (today - e["date"]).days > UNBILLED_DAYS]
    note = message(list(overdue.items()), old)
    if note is None:
        return 0
    people = (await conn.execute(text(
        "SELECT id FROM users WHERE organization_id = :org AND status = 'active' AND upper(role) = ANY(:roles)"),
        {"org": organization_id, "roles": sorted(MONEY_MANAGE_ROLES)})).scalars().all()
    repo = PostgresNotificationRepository(conn)
    queued = 0
    for user_id in people:
        async with conn.begin_nested():
            claimed = await repo.claim(
                organization_id=organization_id, rule_key=RULE_KEY, subject_id=f"{organization_id}:{user_id}",
                occurred_on=today, recipient_user_id=user_id, project_id=None, site_id=None,
                payload={"message": note, "hold_until_window": True, "hold_days": 2})
        queued += 1 if claimed else 0
    return queued
