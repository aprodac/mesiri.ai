"""Application Handlers for confirmed Progress actions (Daily Reporting).

Owns the orchestration order: map -> validate (pure, no transaction) -> open
the one transaction -> check idempotency -> resolve units against
units_of_measure -> persist success or rejection. Mirrors
application/materials/handlers.py exactly, including where unit resolution
sits (inside the transaction, after idempotency, after structural validation
— a defense-in-depth guard since the workflow's own resolution gate should
normally have already filled unit_id before confirmation).

Two Handlers, not one, matching the two commands: creating an Activity and
appending a Progress Update are different confirmed actions with different
workflow keys (plan ADR-D12), so each gets its own Handler exactly as
Material's receipt/usage or Labour's single action does — never a shared
Handler branching on command type internally.

FAILED is never constructed here: an unhandled exception propagates,
rolling back the transaction (workflow stays at CONFIRMED, recoverable) —
the caller (the ExecutionDispatcher) reports ExecutionStatus.FAILED.
"""

from __future__ import annotations

from mesiri.domains.progress import validation
from mesiri.infrastructure.postgres.database import PostgresDatabase
from mesiri_contracts.application.commands.progress import CreateActivityCommand
from mesiri_contracts.application.results.execution_result import ExecutionResult, as_replay
from mesiri_contracts.assistant.v2.confirmed_action import ConfirmedActionV2

from .mapper import (
    build_add_progress_update_command,
    build_close_site_issue_command,
    build_correct_activity_quantity_command,
    build_create_activity_command,
    build_report_site_issue_command,
)
from .repository import ProgressExecutionRepository
from .resolution import ProgressUnitResolver


class ExecuteConfirmedCreateActivityHandler:
    def __init__(
        self,
        db: PostgresDatabase,
        repo: ProgressExecutionRepository,
        resolver: ProgressUnitResolver,
    ) -> None:
        self._db = db
        self._repo = repo
        self._resolver = resolver

    async def handle(self, confirmed: ConfirmedActionV2) -> ExecutionResult:
        return await self.execute(build_create_activity_command(confirmed))

    async def execute(self, cmd: CreateActivityCommand) -> ExecutionResult:
        """Validate, resolve units and save one Activity. The one save path for a
        WhatsApp confirmation (``handle``) and the API (POST /progress/activities, WA-121)."""
        reasons = validation.validate_create_activity(cmd)

        async with self._db.transaction() as conn:
            existing = await self._repo.check_idempotency(conn, cmd.idempotency_key)
            if existing is not None:
                return as_replay(existing)

            if not reasons:
                resolved_quantities = []
                for q in cmd.quantities:
                    result = await self._resolver.resolve_quantity(conn, q)
                    if result.reason is not None:
                        reasons.append(result.reason)
                        break
                    resolved_quantities.append(q.model_copy(update={"unit_id": str(result.unit_id)}))
                if not reasons:
                    cmd = cmd.model_copy(update={"quantities": resolved_quantities})

            if reasons:
                return await self._repo.persist_rejection(
                    conn, cmd.idempotency_key, "create_activity", reasons
                )
            return await self._repo.persist_create_activity_success(conn, cmd)


class ExecuteConfirmedAddProgressUpdateHandler:
    def __init__(
        self,
        db: PostgresDatabase,
        repo: ProgressExecutionRepository,
        resolver: ProgressUnitResolver,
    ) -> None:
        self._db = db
        self._repo = repo
        self._resolver = resolver

    async def handle(self, confirmed: ConfirmedActionV2) -> ExecutionResult:
        cmd = build_add_progress_update_command(confirmed)
        reasons = validation.validate_add_progress_update(cmd)

        async with self._db.transaction() as conn:
            existing = await self._repo.check_idempotency(conn, cmd.idempotency_key)
            if existing is not None:
                return as_replay(existing)

            if not reasons and cmd.quantity is not None:
                from mesiri_contracts.application.commands.progress import ActivityQuantityInput

                result = await self._resolver.resolve_quantity(
                    conn,
                    ActivityQuantityInput(unit=cmd.unit or "", quantity=cmd.quantity, unit_id=cmd.unit_id),
                )
                if result.reason is not None:
                    reasons.append(result.reason)
                else:
                    cmd = cmd.model_copy(update={"unit_id": str(result.unit_id)})

            if reasons:
                return await self._repo.persist_rejection(
                    conn, cmd.idempotency_key, "add_progress_update", reasons
                )
            return await self._repo.persist_add_progress_update_success(conn, cmd)


class ExecuteConfirmedCorrectActivityQuantityHandler:
    """ADR-D14: "make that 180". Same unit-resolution shape as
    ExecuteConfirmedAddProgressUpdateHandler above -- `new_unit` almost
    always already carries a unit_id by confirmation time (workflows/
    activity_correction/nodes.py's build_draft falls back to the original
    unit when none is restated, and that original was resolved when the
    Progress Update being corrected was itself created), but this Handler
    re-resolves defensively rather than trust that invariant blindly."""

    def __init__(
        self,
        db: PostgresDatabase,
        repo: ProgressExecutionRepository,
        resolver: ProgressUnitResolver,
    ) -> None:
        self._db = db
        self._repo = repo
        self._resolver = resolver

    async def handle(self, confirmed: ConfirmedActionV2) -> ExecutionResult:
        cmd = build_correct_activity_quantity_command(confirmed)
        reasons = validation.validate_correct_activity_quantity(cmd)

        async with self._db.transaction() as conn:
            existing = await self._repo.check_idempotency(conn, cmd.idempotency_key)
            if existing is not None:
                return as_replay(existing)

            if not reasons:
                from mesiri_contracts.application.commands.progress import ActivityQuantityInput

                result = await self._resolver.resolve_quantity(
                    conn,
                    ActivityQuantityInput(
                        unit=cmd.new_unit or "", quantity=cmd.new_quantity, unit_id=cmd.new_unit_id
                    ),
                )
                if result.reason is not None:
                    reasons.append(result.reason)
                else:
                    cmd = cmd.model_copy(update={"new_unit_id": str(result.unit_id)})

            if reasons:
                return await self._repo.persist_rejection(
                    conn, cmd.idempotency_key, "correct_activity_quantity", reasons
                )
            return await self._repo.persist_correct_activity_quantity_success(conn, cmd)


class ExecuteConfirmedReportSiteIssueHandler:
    """No resolver -- issue_type/severity are closed enums with nothing to
    resolve against units_of_measure or any other lookup table (see
    ReportSiteIssueCommand's docstring), unlike the two Handlers above."""

    def __init__(self, db: PostgresDatabase, repo: ProgressExecutionRepository) -> None:
        self._db = db
        self._repo = repo

    async def handle(self, confirmed: ConfirmedActionV2) -> ExecutionResult:
        cmd = build_report_site_issue_command(confirmed)
        reasons = validation.validate_report_site_issue(cmd)

        async with self._db.transaction() as conn:
            existing = await self._repo.check_idempotency(conn, cmd.idempotency_key)
            if existing is not None:
                return as_replay(existing)

            if reasons:
                return await self._repo.persist_rejection(
                    conn, cmd.idempotency_key, "report_site_issue", reasons
                )
            return await self._repo.persist_report_site_issue_success(conn, cmd)


class ExecuteConfirmedCloseSiteIssueHandler:
    """No resolver -- the CURRENT-status re-check is DB-backed but
    self-contained (one row, one column), so it lives inline in
    persist_close_site_issue_success rather than as a separate resolver
    step, unlike Reversal's cross-repository PostgresReverseTargetResolver."""

    def __init__(self, db: PostgresDatabase, repo: ProgressExecutionRepository) -> None:
        self._db = db
        self._repo = repo

    async def handle(self, confirmed: ConfirmedActionV2) -> ExecutionResult:
        cmd = build_close_site_issue_command(confirmed)
        reasons = validation.validate_close_site_issue(cmd)

        async with self._db.transaction() as conn:
            existing = await self._repo.check_idempotency(conn, cmd.idempotency_key)
            if existing is not None:
                return as_replay(existing)

            if reasons:
                return await self._repo.persist_rejection(
                    conn, cmd.idempotency_key, "close_site_issue", reasons
                )
            return await self._repo.persist_close_site_issue_success(conn, cmd)
