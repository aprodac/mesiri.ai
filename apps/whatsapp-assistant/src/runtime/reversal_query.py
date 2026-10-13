"""Reversal target read service (wiring layer only).

Same shape and justification as runtime/money_account_query.py: adapts the
backend's PostgresExpenseRepository.find_latest_confirmed /
PostgresMoneyTransactionRepository.find_latest_reversible_transfer into
plain async methods the inbound journey can call before the graph runs (a
node must never query a repository itself -- see workflows/reverse/nodes.py's
docstring). Never opens a write transaction, never mutates state -- Finance
Module Slice 7's "reverse" itself only ever happens after confirmation, via
application/finance/reverse_execution.py.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal, TypedDict

if TYPE_CHECKING:
    from mesiri.infrastructure.postgres.database import PostgresDatabase

#: Picks one reversible `transfer` row -- see _transfer_target. Typed loosely
#: on the repository because importing PostgresMoneyTransactionRepository at
#: module scope would pull the backend in at import time, which this wiring
#: layer deliberately defers to call time (see the module docstring).
_TransferSelector = Callable[[Any, uuid.UUID], Awaitable[Any]]


class ReversalExpenseTarget(TypedDict):
    expense_id: str
    amount: str
    description: str | None
    occurred_date: str


#: The account type that makes a `transfer` row a petty cash movement --
#: mirrors petty_cash_resolution.py's _ADVANCE_ACCOUNT_TYPE.
ADVANCE_ACCOUNT_TYPE = "employee_advance"

#: Suffix petty_cash_resolution.py gives an auto-created advance account
#: ("Alan Usman — Petty Cash"). Stripped for display so a confirmation reads
#: "issued to Alan Usman" rather than naming the account. Coupled to that
#: module's f-string by nothing stronger than this constant, so the strip is
#: best-effort: an account named any other way falls back to its full name,
#: which is always correct, just less natural.
_ADVANCE_ACCOUNT_NAME_SUFFIX = " — Petty Cash"


def advance_holder_name(account_name: str) -> str:
    """The person an advance account belongs to, for display."""
    if account_name.endswith(_ADVANCE_ACCOUNT_NAME_SUFFIX):
        return account_name[: -len(_ADVANCE_ACCOUNT_NAME_SUFFIX)].strip() or account_name
    return account_name


class ReversalTransferTarget(TypedDict):
    money_transaction_id: str
    amount: str
    from_account_name: str
    to_account_name: str
    # Carried so the seeding layer can tell a petty cash movement from a
    # plain transfer without a second lookup -- both legs are already
    # fetched to get the names, so the type comes along for free.
    from_account_type: str | None
    to_account_type: str | None


class ReversalActivityTarget(TypedDict):
    activity_id: str
    work_type: str | None
    narrative: str | None
    activity_date: str


class ReversalAttendanceTarget(TypedDict):
    attendance_report_id: str
    occurred_date: str
    total_headcount: int
    total_cost: str
    # Shown in the confirmation because the whole point of this undo is a
    # report on the WRONG site -- naming the site is what lets the user see
    # they are withdrawing the one they meant.
    site_name: str | None
    project_name: str | None


class ReversalTargetQueryService:
    def __init__(self, db: PostgresDatabase) -> None:
        self._db = db

    async def find_latest_expense(
        self, *, organization_id: str, project_id: str | None, site_id: str | None
    ) -> ReversalExpenseTarget | None:
        from mesiri.infrastructure.postgres.repositories.expenses import PostgresExpenseRepository

        async with self._db.transaction() as conn:
            repo = PostgresExpenseRepository(conn)
            expense = await repo.find_latest_confirmed(
                uuid.UUID(organization_id),
                project_id=uuid.UUID(project_id) if project_id else None,
                site_id=uuid.UUID(site_id) if site_id else None,
            )
        if expense is None:
            return None
        return ReversalExpenseTarget(
            expense_id=str(expense.id),
            amount=str(expense.amount),
            description=expense.description,
            occurred_date=expense.occurred_date.isoformat(),
        )

    async def _transfer_target(
        self, org_id: uuid.UUID, select: _TransferSelector
    ) -> ReversalTransferTarget | None:
        """Run one of PostgresMoneyTransactionRepository's reversible-transfer
        finders and dress the row with both account names and types.

        Shared by find_latest_transfer and find_latest_petty_cash because
        the two differ only in which row they select -- the row itself is
        the same `transfer` shape, and so is everything the reverse workflow
        needs from it."""
        from mesiri.infrastructure.postgres.repositories.finance import (
            PostgresMoneyAccountRepository,
            PostgresMoneyTransactionRepository,
        )

        async with self._db.transaction() as conn:
            transactions = PostgresMoneyTransactionRepository(conn)
            transaction = await select(transactions, org_id)
            if transaction is None:
                return None
            accounts = PostgresMoneyAccountRepository(conn)
            from_account = (
                await accounts.get_by_id(org_id, transaction.from_account_id)
                if transaction.from_account_id
                else None
            )
            to_account = (
                await accounts.get_by_id(org_id, transaction.to_account_id)
                if transaction.to_account_id
                else None
            )
        return ReversalTransferTarget(
            money_transaction_id=str(transaction.id),
            amount=str(Decimal(transaction.amount)),
            from_account_name=from_account.name if from_account else "unknown account",
            to_account_name=to_account.name if to_account else "unknown account",
            from_account_type=from_account.account_type if from_account else None,
            to_account_type=to_account.account_type if to_account else None,
        )

    async def find_latest_transfer(self, *, organization_id: str) -> ReversalTransferTarget | None:
        """The most recent reversible transfer of ANY kind, petty cash
        included -- see find_latest_reversible_petty_cash on why the two are
        deliberately not mutually exclusive."""
        return await self._transfer_target(
            uuid.UUID(organization_id),
            lambda repo, oid: repo.find_latest_reversible_transfer(oid),
        )

    async def find_latest_petty_cash(
        self, *, organization_id: str
    ) -> ReversalTransferTarget | None:
        """The most recent reversible petty cash movement specifically."""
        return await self._transfer_target(
            uuid.UUID(organization_id),
            lambda repo, oid: repo.find_latest_reversible_petty_cash(oid),
        )

    async def find_latest_activity(
        self,
        *,
        organization_id: str,
        reported_by_user_id: str,
        remembered_activity_id: str | None,
    ) -> ReversalActivityTarget | None:
        """ADR-D15: undo is scoped to the Activity THIS conversation just
        touched (memory/conversation_scope.py's CurrentActivityStore),
        never a broader "most recent in the org" lookup the way expense/
        transfer resolve above -- same-session scoping is what makes
        resolving "undo my last update" safe with no name at all; it is
        never "the most recent activity anyone logged". None when nothing
        is remembered, the remembered id no longer resolves to a real
        (non-deleted) activity, or it belongs to a different reporter --
        ADR-D15's "the reporter just created" is enforced here, not just
        incidentally by session scoping.
        """
        if not remembered_activity_id:
            return None
        from mesiri.infrastructure.postgres.repositories.progress import (
            PostgresProgressReadRepository,
        )

        org_id = uuid.UUID(organization_id)
        try:
            activity_id = uuid.UUID(remembered_activity_id)
        except (TypeError, ValueError):
            return None

        async with self._db.transaction() as conn:
            repo = PostgresProgressReadRepository(conn)
            activity = await repo.get_activity(org_id, activity_id)
        if activity is None:
            return None
        if str(activity.get("reported_by_user_id") or "") != reported_by_user_id:
            return None

        return ReversalActivityTarget(
            activity_id=str(activity["id"]),
            work_type=activity.get("work_type"),
            narrative=activity.get("narrative"),
            activity_date=activity["activity_date"].isoformat(),
        )

    async def find_latest_attendance(
        self, *, organization_id: str, reported_by_user_id: str
    ) -> ReversalAttendanceTarget | None:
        """The most recent live attendance report THIS person filed.

        Reporter-scoped, like find_latest_activity above and for the same
        reason: "cancel that attendance" must mean the report the speaker
        just sent, never whichever site filed one most recently. The
        organization-wide "most recent record" shape that expense and
        transfer use would let one supervisor withdraw another's day.
        """
        from mesiri.infrastructure.postgres.repositories.workforce import (
            PostgresWorkforceReadRepository,
        )

        try:
            reporter_id = uuid.UUID(reported_by_user_id)
        except (TypeError, ValueError):
            return None

        async with self._db.transaction() as conn:
            repo = PostgresWorkforceReadRepository(conn)
            report = await repo.find_latest_voidable_report(
                uuid.UUID(organization_id), reported_by_user_id=reporter_id
            )
        if report is None:
            return None

        return ReversalAttendanceTarget(
            attendance_report_id=str(report["id"]),
            occurred_date=report["occurred_date"].isoformat(),
            total_headcount=int(report.get("total_headcount") or 0),
            total_cost=str(report.get("total_cost") or "0"),
            site_name=report.get("site_name"),
            project_name=report.get("project_name"),
        )

    async def find_latest_of_either_kind(
        self, *, organization_id: str, project_id: str | None, site_id: str | None
    ) -> tuple[Literal["expense", "transfer"], ReversalExpenseTarget | ReversalTransferTarget] | None:
        """Resolve a bare "undo"/"delete that" (#6 Undo) -- the user named no
        kind, so this compares the latest candidate of EACH kind and returns
        whichever actually happened more recently, instead of requiring the
        user to say "reverse my last expense" specifically.

        Comparison is on occurred_date (the business day the report
        describes, the same granularity workflows/reverse/nodes.py's
        confirmation prompt already shows), not row insertion time --
        immune to either write landing in Postgres a few milliseconds
        before the other. A same-day tie resolves to transfer, an
        arbitrary but deterministic tiebreak -- there is no finer-grained
        signal to break it with, and both are equally "correct" undo
        targets at that point.

        Queries the two domain repositories directly (one connection, two
        reads) rather than composing find_latest_expense/find_latest_transfer
        above -- those return the already-stringified TypedDict this method
        also needs to return, but re-deriving the entities here avoids a
        second round trip for the transfer's occurred_date. None when
        neither kind has anything to undo.
        """
        from mesiri.infrastructure.postgres.repositories.expenses import PostgresExpenseRepository
        from mesiri.infrastructure.postgres.repositories.finance import (
            PostgresMoneyAccountRepository,
            PostgresMoneyTransactionRepository,
        )

        org_id = uuid.UUID(organization_id)
        async with self._db.transaction() as conn:
            expense = await PostgresExpenseRepository(conn).find_latest_confirmed(
                org_id,
                project_id=uuid.UUID(project_id) if project_id else None,
                site_id=uuid.UUID(site_id) if site_id else None,
            )
            transactions = PostgresMoneyTransactionRepository(conn)
            transaction = await transactions.find_latest_reversible_transfer(org_id)

            if expense is None and transaction is None:
                return None
            if expense is None:
                assert transaction is not None
                accounts = PostgresMoneyAccountRepository(conn)
                from_account = (
                    await accounts.get_by_id(org_id, transaction.from_account_id)
                    if transaction.from_account_id
                    else None
                )
                to_account = (
                    await accounts.get_by_id(org_id, transaction.to_account_id)
                    if transaction.to_account_id
                    else None
                )
                return "transfer", ReversalTransferTarget(
                    money_transaction_id=str(transaction.id),
                    amount=str(Decimal(transaction.amount)),
                    from_account_name=from_account.name if from_account else "unknown account",
                    to_account_name=to_account.name if to_account else "unknown account",
                )
            if transaction is None or expense.occurred_date >= transaction.occurred_date:
                return "expense", ReversalExpenseTarget(
                    expense_id=str(expense.id),
                    amount=str(expense.amount),
                    description=expense.description,
                    occurred_date=expense.occurred_date.isoformat(),
                )

            accounts = PostgresMoneyAccountRepository(conn)
            from_account = (
                await accounts.get_by_id(org_id, transaction.from_account_id)
                if transaction.from_account_id
                else None
            )
            to_account = (
                await accounts.get_by_id(org_id, transaction.to_account_id)
                if transaction.to_account_id
                else None
            )
            return "transfer", ReversalTransferTarget(
                money_transaction_id=str(transaction.id),
                amount=str(Decimal(transaction.amount)),
                from_account_name=from_account.name if from_account else "unknown account",
                to_account_name=to_account.name if to_account else "unknown account",
            )
