"""Petty cash running low, said on WhatsApp (approved in session by the owner, 7 Nov 2026).

When money leaves a site's cash box or a person's advance (``cash`` / ``employee_advance`` accounts) and the balance
ends below the company's line (Finance settings ``low_float_threshold``, ₹50,000 by default), the person who holds
the cash and the owner / admins / finance hear it once a day per box. Queued as notifications (the same queue that
tells an engineer about their material request): outside the 24-hour window it waits for their next message, so no
Meta template is needed. Called from ``PostgresMoneyTransactionRepository.record``, the one place money moves; a
failure here never stops the payment.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.roles import MONEY_MANAGE_ROLES

RULE_KEY = "petty_cash_low"
DEFAULT_LINE = Decimal("50000")
_PETTY = ("cash", "employee_advance")


def _rupees(v: Decimal) -> str:
    """Indian grouping: ₹1,50,000."""
    n = str(int(v))
    head, tail = n[:-3], n[-3:]
    while len(head) > 2:
        tail = f"{head[-2:]},{tail}"
        head = head[:-2]
    return f"₹{head},{tail}" if head else f"₹{tail}"


def message(box: str, balance: Decimal, line: Decimal, holder: str | None) -> str:
    who = f" ({holder} holds it)" if holder else ""
    return (f"⚠️ {box}{who} is low on cash: {_rupees(balance)} left, below {_rupees(line)}. "
            "Top it up from the bank: Finance › Money on the dashboard.")


async def notify_if_low(conn: AsyncConnection, organization_id: uuid.UUID, account_id: uuid.UUID) -> int:
    """Queue the low-cash note when this account is a cash box now under the line. Returns how many were queued."""
    from mesiri.infrastructure.postgres.repositories.finance import PostgresMoneyAccountRepository
    from mesiri.infrastructure.postgres.repositories.notifications import (
        PostgresNotificationRepository,
    )
    from mesiri.infrastructure.postgres.repositories.organization_settings import (
        PostgresOrganizationSettingsRepository,
    )

    acc = (await conn.execute(text(
        "SELECT a.id, a.name, a.account_type, a.status, a.project_id, a.site_id, a.owner_user_id, u.full_name AS holder "
        "FROM money_accounts a LEFT JOIN users u ON u.id = a.owner_user_id "
        "WHERE a.id = :id AND a.organization_id = :org"), {"id": account_id, "org": organization_id})).mappings().first()
    if acc is None or acc["account_type"] not in _PETTY or acc["status"] != "active":
        return 0
    settings = await PostgresOrganizationSettingsRepository(conn).get(organization_id, "finance_settings")
    line = Decimal(str((settings or {}).get("low_float_threshold") or DEFAULT_LINE)) if isinstance(settings, dict) else DEFAULT_LINE
    balance = await PostgresMoneyAccountRepository(conn).get_balance(organization_id, account_id)
    if balance >= line:
        return 0
    people = (await conn.execute(text(
        "SELECT id FROM users WHERE organization_id = :org AND status = 'active' "
        "AND (id = :holder OR upper(role) = ANY(:roles))"),
        {"org": organization_id, "holder": acc["owner_user_id"], "roles": sorted(MONEY_MANAGE_ROLES)})).scalars().all()
    repo = PostgresNotificationRepository(conn)
    queued = 0
    for user_id in people:
        claimed = await repo.claim(
            organization_id=organization_id, rule_key=RULE_KEY, subject_id=f"{account_id}:{user_id}",
            occurred_on=datetime.date.today(), recipient_user_id=user_id, project_id=acc["project_id"],
            site_id=acc["site_id"],
            payload={"message": message(acc["name"], balance, line, acc["holder"]), "hold_until_window": True, "hold_days": 2},
        )
        queued += 1 if claimed else 0
    return queued
