"""Application Handler for confirmed Labour attendance actions (M8).

Owns the orchestration order: map -> validate (pure, no transaction) -> open
the one transaction -> check idempotency -> persist success or rejection.
This is the only place a transaction is opened (Requirement 7 — transaction
ownership is centralized here, not scattered across repositories). Mirrors
application/materials/handlers.py.

No resolution step between validation and persistence, unlike Material: a
line's worker_id (if any) was already resolved by the workflow's
match_workers node before the user ever confirmed (Labour plan principle
P4), and attendance never writes the workforce register regardless (P1) — so
there is nothing left to look up at execution time.

FAILED is never constructed here: an unhandled exception from anything below
propagates out of this method, rolling back the transaction (workflow stays
at CONFIRMED, recoverable) — the caller (LabourExecutionDispatcher) is
responsible for catching it and reporting ExecutionStatus.FAILED.
"""

from __future__ import annotations

from mesiri.domains.workforce import validation
from mesiri.infrastructure.postgres.database import PostgresDatabase
from mesiri_contracts.application.commands.labour import RecordLabourAttendanceCommand
from mesiri_contracts.application.results.execution_result import ExecutionResult, as_replay
from mesiri_contracts.assistant.v2.confirmed_action import ConfirmedActionV2

from .mapper import build_command
from .repository import LabourExecutionRepository


class ExecuteConfirmedLabourAttendanceHandler:
    def __init__(self, db: PostgresDatabase, repo: LabourExecutionRepository) -> None:
        self._db = db
        self._repo = repo

    async def handle(self, confirmed: ConfirmedActionV2) -> ExecutionResult:
        return await self.execute(build_command(confirmed))

    async def execute(self, cmd: RecordLabourAttendanceCommand) -> ExecutionResult:
        """Validate and save one attendance report. The one save path for a
        WhatsApp confirmation (``handle``) and the API (POST /labour/attendance, WA-121)."""
        reasons = validation.validate(cmd)

        async with self._db.transaction() as conn:
            existing = await self._repo.check_idempotency(conn, cmd.idempotency_key)
            if existing is not None:
                return as_replay(existing)

            if reasons:
                return await self._repo.persist_rejection(conn, cmd, reasons)
            return await self._repo.persist_success(conn, cmd)
