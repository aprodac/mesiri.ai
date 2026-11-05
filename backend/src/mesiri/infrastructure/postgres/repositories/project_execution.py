"""PostgreSQL implementation of
mesiri.application.projects.repository.CreateProjectExecutionRepository.

Only file permitted to hold SQL for CreateProject execution (capability-
boundary convention, mirrors account_admin_execution.py). Every method takes
an externally-supplied connection.

`persist_success` mirrors apps/whatsapp-assistant/src/projects/router.py's
create_project REST endpoint in one respect that matters: a creator whose
role isn't org-wide (PROJECT_MANAGER, the one role in
create_validation.py's _PROJECT_CREATE_ROLES that isn't) needs an explicit
project_members row for their own new project -- without one,
list_projects/get_project's membership scoping hides the project from the
person who just created it. See mesiri.authorization.roles.is_org_wide.
"""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING

import sqlalchemy as sa

from mesiri.application.projects.create_commands import CreateProjectCommand
from mesiri.application.projects.defaults import new_project_settings
from mesiri.application.projects.repository import CreateProjectExecutionRepository
from mesiri.authorization.roles import is_org_wide
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

_COMMAND_TYPE = "create_project"


class PostgresCreateProjectExecutionRepository(CreateProjectExecutionRepository):
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

    async def persist_success(
        self, conn: AsyncConnection, cmd: CreateProjectCommand
    ) -> ExecutionResult:
        if not await self._try_claim(conn, cmd.idempotency_key):
            existing = await self.check_idempotency(conn, cmd.idempotency_key)
            assert existing is not None
            return as_replay(existing)

        organization_id = uuid.UUID(cmd.organization_id)
        created_by = uuid.UUID(cmd.created_by)
        project_id = uuid.uuid4()

        company = await new_project_settings(conn, organization_id)  # [259]: never UTC / no report
        await conn.execute(
            sa.text(
                "INSERT INTO projects "
                "(id, organization_id, name, location, client, description, status, "
                "progress, open_issues, reporting_timezone, auto_generate_dpr, "
                "reporting_cutoff_time, dpr_send_deadline) "
                "VALUES (:id, :org_id, :name, :location, :client, :description, "
                "'on_track', 0, 0, :zone, :auto_dpr, :cutoff, :deadline)"
            ),
            {
                "id": project_id,
                "org_id": organization_id,
                "name": cmd.name.strip(),
                "location": cmd.location,
                "client": cmd.client,
                "description": cmd.description,
                "zone": company.reporting_timezone,
                "auto_dpr": company.auto_generate_dpr,
                "cutoff": company.reporting_cutoff_time,
                "deadline": company.dpr_send_deadline,
            },
        )

        # See module docstring -- a PROJECT_MANAGER creator needs an explicit
        # membership row to see their own new project.
        creator_row = (
            await conn.execute(
                sa.text("SELECT role, access_policy FROM users WHERE id = :id"),
                {"id": created_by},
            )
        ).mappings().first()
        creator_role = creator_row["role"] if creator_row else cmd.created_by_role
        creator_access_policy = creator_row["access_policy"] if creator_row else None
        if not is_org_wide(creator_role, creator_access_policy):
            await conn.execute(
                sa.text(
                    "INSERT INTO project_members (id, project_id, user_id, role, site_access_mode) "
                    "VALUES (:id, :project_id, :user_id, :role, 'all_sites')"
                ),
                {
                    "id": uuid.uuid4(),
                    "project_id": project_id,
                    "user_id": created_by,
                    "role": creator_role or "PROJECT_MANAGER",
                },
            )

        payload = {"name": cmd.name.strip(), "location": cmd.location, "client": cmd.client}
        await conn.execute(
            sa.text(
                "INSERT INTO outbox_events "
                "(id, aggregate_type, aggregate_id, event_type, payload, correlation_id) "
                "VALUES (:id, 'project', :aggregate_id, 'ProjectCreated', "
                "CAST(:payload AS jsonb), :correlation_id)"
            ),
            {
                "id": uuid.uuid4(),
                "aggregate_id": project_id,
                "payload": json.dumps(payload),
                "correlation_id": cmd.correlation_id,
            },
        )

        result = ExecutionResult(
            status=ExecutionStatus.SUCCEEDED,
            idempotency_key=cmd.idempotency_key,
            material_row_id=str(project_id),
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

    async def _transition(
        self, conn: AsyncConnection, workflow_instance_id: str, new_phase: WorkflowPhase
    ) -> None:
        """Move workflow_instances to `new_phase` on the same connection as the
        domain write. No-op when `workflow_instance_id` doesn't match any row
        (mirrors account_admin_execution.py's docstring on this same mechanic)."""
        try:
            loaded = await get_by_id_on_connection(conn, workflow_instance_id)
        except ValueError:
            return
        if loaded is None:
            return
        new_state = loaded.state.model_copy(update={"phase": new_phase})
        await transition_on_connection(conn, workflow_instance_id, loaded.version, new_state)
