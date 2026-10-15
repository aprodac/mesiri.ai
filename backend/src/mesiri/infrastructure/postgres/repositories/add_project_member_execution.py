"""PostgreSQL implementation of
mesiri.application.projects.repository.AddProjectMemberExecutionRepository.

Only file permitted to hold SQL for AddProjectMember execution (capability-
boundary convention, mirrors site_execution.py). Every method takes an
externally-supplied connection.

`ExecutionResult.material_row_id` is set to the *user's* id, not the new
project_members row's id (the membership set is what changed).
"""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING

import sqlalchemy as sa

from mesiri.application.projects.add_member_commands import AddProjectMemberCommand
from mesiri.application.projects.repository import AddProjectMemberExecutionRepository
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

_COMMAND_TYPE = "add_project_member"


class PostgresAddProjectMemberExecutionRepository(AddProjectMemberExecutionRepository):
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
        self, conn: AsyncConnection, cmd: AddProjectMemberCommand
    ) -> ExecutionResult:
        if not await self._try_claim(conn, cmd.idempotency_key):
            existing = await self.check_idempotency(conn, cmd.idempotency_key)
            assert existing is not None
            return as_replay(existing)

        organization_id = uuid.UUID(cmd.organization_id)
        project_id = uuid.UUID(cmd.project_id)
        assert cmd.member_user_id is not None, "member_user_id must be resolved before persist"
        user_id = uuid.UUID(cmd.member_user_id)

        # Defense-in-depth re-check: the project resolved at draft-build
        # time may have been deleted/moved orgs before confirmation.
        project_row = (
            await conn.execute(
                sa.text(
                    "SELECT id FROM projects WHERE id = :id AND organization_id = :org_id"
                ),
                {"id": project_id, "org_id": organization_id},
            )
        ).first()
        if project_row is None:
            return await self._reject(
                conn, cmd.idempotency_key, ["that project no longer exists"]
            )

        existing_member = (
            await conn.execute(
                sa.text(
                    "SELECT id FROM project_members "
                    "WHERE project_id = :project_id AND user_id = :user_id"
                ),
                {"project_id": project_id, "user_id": user_id},
            )
        ).first()
        if existing_member is not None:
            return await self._reject(
                conn, cmd.idempotency_key, ["that user is already a member of this project"]
            )

        member_id = uuid.uuid4()
        await conn.execute(
            sa.text(
                "INSERT INTO project_members "
                "(id, project_id, user_id, role, site_access_mode) "
                "VALUES (:id, :project_id, :user_id, :role, 'all_sites')"
            ),
            {
                "id": member_id,
                "project_id": project_id,
                "user_id": user_id,
                "role": cmd.role,
            },
        )

        payload = {"project_id": cmd.project_id, "user_id": cmd.member_user_id, "role": cmd.role}
        await conn.execute(
            sa.text(
                "INSERT INTO outbox_events "
                "(id, aggregate_type, aggregate_id, event_type, payload, correlation_id) "
                "VALUES (:id, 'project_member', :aggregate_id, 'ProjectMemberAdded', "
                "CAST(:payload AS jsonb), :correlation_id)"
            ),
            {
                "id": uuid.uuid4(),
                "aggregate_id": member_id,
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
