"""Resolve a petty cash recipient's name into their employee-advance account.

Finance Module Slice 5: "give ₹20,000 petty cash to Alan" needs to know
which money_accounts row is "Alan's petty cash" -- auto-created on first
issuance, per docs/execution/FINANCE_MODULE_PLAN.md and Linear STA-147, the
one case in V1 where a non-admin action (a PROJECT_MANAGER issuing petty
cash, not ADMIN/FINANCE creating an account) can create an account, because
the account is for the recipient, not the actor.

Unlike application/expenses/resolution.py's category resolver, an unmatched
recipient_name is never defaulted to anything -- there is no meaningful
"unknown recipient" advance account. It returns None, and the caller
(runtime/petty_cash_query.py) leaves that leg of the transfer unresolved;
the existing transfer_validation.py rejects a draft missing either account
rather than this module guessing who was meant.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import TYPE_CHECKING

from mesiri.domains.finance.entities import MoneyAccount
from mesiri.domains.shared import clock
from mesiri.infrastructure.postgres.repositories.finance import PostgresMoneyAccountRepository
from mesiri.infrastructure.postgres.repositories.users import PostgresUserRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection

_ADVANCE_ACCOUNT_TYPE = "employee_advance"


class PettyCashRecipientResolver(ABC):
    @abstractmethod
    async def resolve_or_create_advance_account(
        self,
        conn: AsyncConnection,
        organization_id: uuid.UUID,
        recipient_name: str,
        *,
        created_by: uuid.UUID,
    ) -> MoneyAccount | None: ...


class PostgresPettyCashRecipientResolver(PettyCashRecipientResolver):
    async def resolve_or_create_advance_account(
        self,
        conn: AsyncConnection,
        organization_id: uuid.UUID,
        recipient_name: str,
        *,
        created_by: uuid.UUID,
    ) -> MoneyAccount | None:
        users = PostgresUserRepository(conn)
        user = await users.find_by_full_name_active(organization_id, recipient_name)
        if user is None:
            return None

        accounts = PostgresMoneyAccountRepository(conn)
        existing = await self._find_advance_account(accounts, organization_id, user.id)
        if existing is not None:
            return existing
        # Re-check right before creating to narrow (not eliminate) the
        # first-issuance race window -- mirrors
        # runtime/money_account_query.py's default-account bootstrap; an
        # occasional duplicate advance account is a low-cost edge case, not
        # one worth a DB-level uniqueness guard for V1.
        existing = await self._find_advance_account(accounts, organization_id, user.id)
        if existing is not None:
            return existing

        return await accounts.create(
            organization_id=organization_id,
            name=f"{user.full_name} — Petty Cash",
            account_type=_ADVANCE_ACCOUNT_TYPE,
            currency="INR",
            opening_balance=Decimal("0"),
            opening_balance_date=clock.today(),
            created_by=created_by,
            owner_user_id=user.id,
        )

    @staticmethod
    async def _find_advance_account(
        accounts: PostgresMoneyAccountRepository, organization_id: uuid.UUID, owner_user_id: uuid.UUID
    ) -> MoneyAccount | None:
        candidates = await accounts.list_accounts(
            organization_id, account_type=_ADVANCE_ACCOUNT_TYPE, status="active"
        )
        for account in candidates:
            if account.owner_user_id == owner_user_id:
                return account
        return None
