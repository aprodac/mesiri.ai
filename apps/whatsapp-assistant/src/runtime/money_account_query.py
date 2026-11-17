"""Money account read/bootstrap service (wiring layer only).

Same shape and justification as runtime/expense_category_query.py: adapts
the backend's PostgresMoneyAccountRepository into a plain async method the
assistant can call directly (in-process import, no HTTP -- domains/finance/
has no REST router in this phase, see docs/execution/FINANCE_MODULE_PLAN.md).

`list_accounts` lazily bootstraps one default 'cash' account the first time
an org has none, mirroring PostgresExpenseCategoryRepository.get_or_create_default's
create-on-first-use pattern -- a migration backfill can't invent a
`created_by`, so the account is created by whichever real user's finance
action first needs a candidate list. Not yet called by any workflow (Finance
Module Slice 1 wires it into the "which account?" slot-fill); exercised
directly by Slice 0's own tests until then.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from mesiri.domains.shared import clock

if TYPE_CHECKING:
    from mesiri.domains.finance.entities import MoneyAccount
    from mesiri.infrastructure.postgres.database import PostgresDatabase

_DEFAULT_ACCOUNT_NAME = "Site Cash"


class MoneyAccountQueryService:
    """Reads active money accounts and their balances; only ever creates the
    org's default account, never mutates an existing one."""

    def __init__(self, db: PostgresDatabase) -> None:
        self._db = db

    async def list_accounts(
        self, *, organization_id: str, created_by: str
    ) -> list[MoneyAccount]:
        """Active accounts for the org. Bootstraps one default 'cash' account
        if none exist yet -- callers (e.g. a slot-fill candidate list) must
        never be handed an empty list for an org that simply hasn't been set
        up, since that would silently collapse every choice down to
        "my own pocket"."""
        from mesiri.infrastructure.postgres.repositories.finance import (
            PostgresMoneyAccountRepository,
        )

        org_id = uuid.UUID(organization_id)
        async with self._db.transaction() as conn:
            repo = PostgresMoneyAccountRepository(conn)
            accounts = await repo.list_accounts(org_id, status="active")
            if accounts:
                return accounts
            # Re-check under the same connection right before creating to
            # narrow (not eliminate) the first-use race window -- an
            # occasional duplicate default account is a low-cost edge case,
            # not one worth a DB-level uniqueness guard for V1.
            accounts = await repo.list_accounts(org_id, status="active")
            if accounts:
                return accounts
            bootstrapped = await repo.create(
                organization_id=org_id,
                name=_DEFAULT_ACCOUNT_NAME,
                account_type="cash",
                currency="INR",
                opening_balance=Decimal("0"),
                opening_balance_date=clock.today(),
                created_by=uuid.UUID(created_by),
            )
            return [bootstrapped]

    async def get_balance(self, *, organization_id: str, account_id: str) -> Decimal:
        from mesiri.infrastructure.postgres.repositories.finance import (
            PostgresMoneyAccountRepository,
        )

        async with self._db.transaction() as conn:
            repo = PostgresMoneyAccountRepository(conn)
            return await repo.get_balance(uuid.UUID(organization_id), uuid.UUID(account_id))

    async def find_matching_accounts(
        self, *, organization_id: str, created_by: str, account_name: str | None
    ) -> list[MoneyAccount]:
        """Finance Module Slice 2: resolve a balance query's optional
        `account_name` against the org's accounts. No name -> every account
        (e.g. "how much cash do I have?"); a name -> whichever single
        account matches (reuses workflows.slots' numbered/free-text matcher
        so "site cash" matches "Site Cash" the same way an expense-capture
        slot answer would -- one matching rule for the whole finance module,
        not two)."""
        accounts = await self.list_accounts(organization_id=organization_id, created_by=created_by)
        if not account_name:
            return accounts

        from workflows.slots import SlotCandidate, match_slot_answer

        candidates = [SlotCandidate(value=str(account.id), label=account.name) for account in accounts]
        matched_id = match_slot_answer(account_name, candidates)
        if matched_id is None:
            return []
        return [account for account in accounts if str(account.id) == matched_id]

    async def get_balances(
        self, *, organization_id: str, accounts: list[MoneyAccount]
    ) -> dict[uuid.UUID, Decimal]:
        """Balance for each given account, in one transaction. Callers pass
        the accounts they already resolved (find_matching_accounts/
        list_accounts) rather than this method re-listing them."""
        from mesiri.infrastructure.postgres.repositories.finance import (
            PostgresMoneyAccountRepository,
        )

        org_id = uuid.UUID(organization_id)
        async with self._db.transaction() as conn:
            repo = PostgresMoneyAccountRepository(conn)
            return {account.id: await repo.get_balance(org_id, account.id) for account in accounts}
