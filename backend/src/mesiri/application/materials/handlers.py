"""Application Handler for confirmed Material actions (M8).

Owns the orchestration order: map -> validate (pure, no transaction) -> open
the one transaction -> check idempotency -> resolve material/unit against the
catalog -> persist success or rejection. This is the only place a
transaction is opened (Requirement 7 — transaction ownership is centralized
here, not scattered across repositories).

Catalog/unit resolution needs a connection, so it runs inside the
transaction, after idempotency is checked (a replay short-circuits before
touching the catalog at all) and after the pure structural validation. It is
a defense-in-depth guard — the WhatsApp assistant's deterministic gate chain
(runtime/inbound_journey.py) should normally have already resolved
material_id/unit_id before the user ever confirms; this resolver just
refuses to persist against anything that turns out to be missing, inactive,
or the wrong Stock Unit (see application/materials/resolution.py).

FAILED is never constructed here: an unhandled exception from anything below
propagates out of this method, rolling back the transaction (workflow stays
at CONFIRMED, recoverable) — the caller (the interactions ExecutionDispatcher
adapter) is responsible for catching it and reporting ExecutionStatus.FAILED.
"""

from __future__ import annotations

from mesiri.domains.materials import validation
from mesiri.infrastructure.postgres.database import PostgresDatabase
from mesiri_contracts.application.results.execution_result import ExecutionResult, as_replay
from mesiri_contracts.assistant.v2.confirmed_action import ConfirmedActionV2

from .mapper import build_command
from .repository import MaterialExecutionRepository
from .resolution import MaterialResolver


class ExecuteConfirmedMaterialActionHandler:
    def __init__(
        self, db: PostgresDatabase, repo: MaterialExecutionRepository, resolver: MaterialResolver
    ) -> None:
        self._db = db
        self._repo = repo
        self._resolver = resolver

    async def handle(self, confirmed: ConfirmedActionV2) -> ExecutionResult:
        cmd = build_command(confirmed)
        reasons = validation.validate(cmd)

        async with self._db.transaction() as conn:
            existing = await self._repo.check_idempotency(conn, cmd.idempotency_key)
            if existing is not None:
                return as_replay(existing)

            if not reasons:
                resolved = await self._resolver.resolve(conn, cmd)
                reasons = resolved.reasons
                if not reasons:
                    cmd = cmd.model_copy(
                        update={
                            "material_id": str(resolved.material_id),
                            "unit_id": str(resolved.unit_id),
                        }
                    )

            if not reasons:
                reasons = await self._repo.check_rules(conn, cmd)

            if reasons:
                return await self._repo.persist_rejection(conn, cmd, reasons)
            return await self._repo.persist_success(conn, cmd)
