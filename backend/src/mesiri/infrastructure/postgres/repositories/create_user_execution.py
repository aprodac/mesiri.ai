"""PostgreSQL implementation of
mesiri.application.identity.repository.CreateUserExecutionRepository.

Only file permitted to hold SQL for CreateUser execution (capability-
boundary convention, mirrors add_project_member_execution.py).

The new row gets `username` set to its WhatsApp number's digits (already
unique via ux_users_whatsapp_digits, so reusing it as the login identifier
sidesteps inventing a separate slug/dedupe scheme -- see migration 0457's
docstring) and `email` left NULL. `hashed_password` is a bcrypt hash of a
random secret nobody is ever told -- the column is NOT NULL and auth/
router.py's login() calls bcrypt.checkpw against it, so it must be a
well-formed hash (never a placeholder string, which would raise on the
first login attempt against this user's WhatsApp number/username instead of
just failing the password check like any other wrong password). The person
gets no dashboard access until an admin sets a real email + password later
from the dashboard's own users/router.py update_user endpoint.
"""

from __future__ import annotations

import json
import secrets
import uuid
from typing import TYPE_CHECKING

import bcrypt
import sqlalchemy as sa

from mesiri.application.identity.create_user_commands import CreateUserCommand
from mesiri.application.identity.phone_numbers import (
    NUMBER_TAKEN_MESSAGE,
    whatsapp_number_taken,
)
from mesiri.application.identity.repository import CreateUserExecutionRepository
from mesiri.infrastructure.postgres.workflow_instance import (
    get_by_id_on_connection,
    transition_on_connection,
)
from mesiri_contracts.application.results.execution_result import (
    ExecutionResult,
    ExecutionStatus,
    as_replay,
)
from mesiri_contracts.context.enums import WorkflowPhase

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection

_COMMAND_TYPE = "create_user"

# Matches users/router.py's own _DEFAULT_ACCESS_POLICY exactly -- kept in
# sync manually (that module lives in apps/whatsapp-assistant, this one in
# backend, and the two packages must not import across that boundary).
# access_policy is legacy/GET-me-only per migration 0350's docstring; not
# consulted for authorization anywhere, but every existing user row carries
# one, so a new row does too rather than being the first to omit it.
_DEFAULT_ACCESS_POLICY = {"mode": "custom_projects", "projects": []}


def _random_password_hash() -> str:
    secret = secrets.token_urlsafe(32)
    return bcrypt.hashpw(secret.encode(), bcrypt.gensalt()).decode()


class PostgresCreateUserExecutionRepository(CreateUserExecutionRepository):
    async def check_idempotency(self, conn: AsyncConnection, key: str) -> ExecutionResult | None:
        row = (
            await conn.execute(
                sa.text("SELECT status, result FROM idempotency_keys WHERE key = :key"),
                {"key": key},
            )
        ).mappings().first()
        if row is None or row["status"] != "completed" or row["result"] is None:
            return None
        result_json = row["result"]
        if not isinstance(result_json, str):
            result_json = json.dumps(result_json)
        return ExecutionResult.model_validate_json(result_json)

    async def _try_claim(self, conn: AsyncConnection, idempotency_key: str) -> bool:
        """INSERT ... ON CONFLICT DO NOTHING — True if this call won the claim."""
        claimed = (
            await conn.execute(
                sa.text(
                    "INSERT INTO idempotency_keys (key, command_type, status) "
                    "VALUES (:key, :command_type, 'in_progress') "
                    "ON CONFLICT (key) DO NOTHING RETURNING key"
                ),
                {"key": idempotency_key, "command_type": _COMMAND_TYPE},
            )
        ).first()
        return claimed is not None

    async def _reject(
        self, conn: AsyncConnection, idempotency_key: str, reasons: list[str]
    ) -> ExecutionResult:
        result = ExecutionResult(
            status=ExecutionStatus.REJECTED,
            idempotency_key=idempotency_key,
            rejection_reasons=reasons,
        )
        await conn.execute(
            sa.text(
                "UPDATE idempotency_keys "
                "SET status = 'completed', result = CAST(:result AS jsonb), completed_at = now() "
                "WHERE key = :key"
            ),
            {"result": result.model_dump_json(), "key": idempotency_key},
        )
        await self._transition(conn, idempotency_key, WorkflowPhase.EXECUTION_REJECTED)
        return result

    async def persist_success(
        self, conn: AsyncConnection, cmd: CreateUserCommand
    ) -> ExecutionResult:
        if not await self._try_claim(conn, cmd.idempotency_key):
            existing = await self.check_idempotency(conn, cmd.idempotency_key)
            assert existing is not None
            return as_replay(existing)

        organization_id = uuid.UUID(cmd.organization_id)

        # Defense-in-depth re-check: the number may have been registered to
        # someone else between draft-build and confirmation (also enforced
        # by ux_users_whatsapp_digits/ix_users_username, but a friendly
        # rejection beats a raw IntegrityError reaching the user). Compared on
        # digits, and never naming the holder: they may be in another company.
        username_taken = (
            await conn.execute(
                sa.text("SELECT 1 FROM users WHERE username = :number"),
                {"number": cmd.whatsapp_number},
            )
        ).first() is not None
        if username_taken or await whatsapp_number_taken(conn, cmd.whatsapp_number):
            return await self._reject(conn, cmd.idempotency_key, [NUMBER_TAKEN_MESSAGE])

        user_id = uuid.uuid4()
        await conn.execute(
            sa.text(
                "INSERT INTO users "
                "(id, organization_id, email, username, hashed_password, full_name, role, "
                "whatsapp_number, status, access_policy) "
                "VALUES (:id, :org_id, NULL, :username, :hashed_password, :full_name, :role, "
                ":whatsapp_number, 'active', CAST(:access_policy AS jsonb))"
            ),
            {
                "id": user_id,
                "org_id": organization_id,
                "username": cmd.whatsapp_number,
                "hashed_password": _random_password_hash(),
                "full_name": cmd.full_name.strip(),
                "role": cmd.role,
                "whatsapp_number": cmd.whatsapp_number,
                "access_policy": json.dumps(_DEFAULT_ACCESS_POLICY),
            },
        )

        payload = {
            "full_name": cmd.full_name.strip(),
            "whatsapp_number": cmd.whatsapp_number,
            "role": cmd.role,
        }
        await conn.execute(
            sa.text(
                "INSERT INTO outbox_events "
                "(id, aggregate_type, aggregate_id, event_type, payload, correlation_id) "
                "VALUES (:id, 'user', :aggregate_id, 'UserCreated', "
                "CAST(:payload AS jsonb), :correlation_id)"
            ),
            {
                "id": uuid.uuid4(),
                "aggregate_id": user_id,
                "payload": json.dumps(payload),
                "correlation_id": cmd.correlation_id,
            },
        )

        result = ExecutionResult(
            status=ExecutionStatus.SUCCEEDED,
            idempotency_key=cmd.idempotency_key,
            material_row_id=str(user_id),
        )
        await conn.execute(
            sa.text(
                "UPDATE idempotency_keys "
                "SET status = 'completed', result = CAST(:result AS jsonb), completed_at = now() "
                "WHERE key = :key"
            ),
            {"result": result.model_dump_json(), "key": cmd.idempotency_key},
        )
        await self._transition(conn, cmd.idempotency_key, WorkflowPhase.COMPLETED)
        return result

    async def persist_rejection(
        self, conn: AsyncConnection, idempotency_key: str, reasons: list[str]
    ) -> ExecutionResult:
        if not await self._try_claim(conn, idempotency_key):
            existing = await self.check_idempotency(conn, idempotency_key)
            assert existing is not None
            return as_replay(existing)
        return await self._reject(conn, idempotency_key, reasons)

    async def _transition(
        self, conn: AsyncConnection, workflow_instance_id: str, new_phase: WorkflowPhase
    ) -> None:
        """Move workflow_instances to `new_phase` on the same connection as the
        domain write. No-op when `workflow_instance_id` doesn't match any row
        (mirrors project_execution.py's docstring on this same mechanic)."""
        try:
            loaded = await get_by_id_on_connection(conn, workflow_instance_id)
        except ValueError:
            return
        if loaded is None:
            return
        new_state = loaded.state.model_copy(update={"phase": new_phase})
        await transition_on_connection(conn, workflow_instance_id, loaded.version, new_state)
