"""PostgreSQL implementation of mesiri.application.progress.repository.ProgressExecutionRepository.

The only file permitted to hold SQL for activities/activity_quantities/
progress_updates execution (capability-boundary convention, mirrors
material_execution.py and labour_execution.py). Every method takes an
externally-supplied connection — the Application Handler opens the one
transaction; this repository never commits.

Emits generic `outbox_events` rows for both Activity creation and Progress
Update append, the same mechanism every other operational module already
uses. **Not yet registered** in
`mesiri.events.consumers.timeline_projector.AGGREGATE_TABLES` — that
registration is Phase 6.0 of docs/execution/DAILY_REPORTING_PLAN.md, tracked
there alongside the pre-existing Labour/Finance projection gaps. Note for
whoever does that registration: `activities` uses `activity_date` /
`started_at` rather than the `occurred_date` / `occurred_time` names
`AGGREGATE_TABLES`'s other entries use — either alias those columns in the
registration or extend the projector to accept a column-name mapping per
aggregate type, whichever is less invasive at the time.
"""

from __future__ import annotations

import datetime
import json
import uuid
from typing import TYPE_CHECKING

from mesiri.application.progress.repository import ProgressExecutionRepository
from mesiri.infrastructure.postgres.workflow_instance import (
    get_by_id_on_connection,
    transition_on_connection,
)
from mesiri_contracts.application.commands.progress import (
    AddProgressUpdateCommand,
    AttachEvidenceCommand,
    CloseSiteIssueCommand,
    CorrectActivityQuantityCommand,
    CreateActivityCommand,
    ReportSiteIssueCommand,
)
from mesiri_contracts.application.results.execution_result import (
    ExecutionResult,
    ExecutionStatus,
    as_replay,
)
from mesiri_contracts.context.enums import WorkflowPhase

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection


def _optional_uuid(value: str | None) -> uuid.UUID | None:
    return uuid.UUID(value) if value is not None else None


class PostgresProgressExecutionRepository(ProgressExecutionRepository):
    async def check_idempotency(self, conn: AsyncConnection, key: str) -> ExecutionResult | None:
        from sqlalchemy import text

        row = (
            (
                await conn.execute(
                    text("SELECT status, result FROM idempotency_keys WHERE key = :key"),
                    {"key": key},
                )
            )
            .mappings()
            .first()
        )
        if row is None or row["status"] != "completed" or row["result"] is None:
            return None
        result_json = row["result"]
        if not isinstance(result_json, str):
            result_json = json.dumps(result_json)
        return ExecutionResult.model_validate_json(result_json)

    async def _try_claim(self, conn: AsyncConnection, idempotency_key: str, command_type: str) -> bool:
        """INSERT ... ON CONFLICT DO NOTHING — True if this call won the claim."""
        from sqlalchemy import text

        claimed = (
            await conn.execute(
                text(
                    "INSERT INTO idempotency_keys (key, command_type, status) "
                    "VALUES (:key, :command_type, 'in_progress') "
                    "ON CONFLICT (key) DO NOTHING RETURNING key"
                ),
                {"key": idempotency_key, "command_type": command_type},
            )
        ).first()
        return claimed is not None

    async def persist_create_activity_success(
        self, conn: AsyncConnection, cmd: CreateActivityCommand
    ) -> ExecutionResult:
        from sqlalchemy import text

        if not await self._try_claim(conn, cmd.idempotency_key, "create_activity"):
            existing = await self.check_idempotency(conn, cmd.idempotency_key)
            assert existing is not None
            return as_replay(existing)

        organization_id = uuid.UUID(cmd.organization_id)
        project_id = _optional_uuid(cmd.project_id)
        site_id = _optional_uuid(cmd.site_id)
        created_by = uuid.UUID(cmd.created_by)

        if project_id is None or site_id is None:
            # domains/progress/validation.py already rejects this before
            # persist_create_activity_success is ever called; defensive
            # guard against calling this method directly with an unvalidated
            # command, matching material_execution.py's equivalent check.
            raise RuntimeError("project_id and site_id are required to persist an activity")

        activity_id = uuid.uuid4()
        await conn.execute(
            text(
                "INSERT INTO activities "
                "(id, organization_id, project_id, site_id, work_package_id, location_id, "
                "work_type, activity_date, started_at, ended_at, status, narrative, contractor, "
                "reported_by_user_id, source, correlation_id) "
                "VALUES (:id, :organization_id, :project_id, :site_id, :work_package_id, :location_id, "
                ":work_type, :activity_date, :started_at, :ended_at, 'IN_PROGRESS', :narrative, "
                ":contractor, :reported_by_user_id, :source, :correlation_id)"
            ),
            {
                "id": activity_id,
                "organization_id": organization_id,
                "project_id": project_id,
                "site_id": site_id,
                "work_package_id": _optional_uuid(cmd.work_package_id),
                "location_id": _optional_uuid(cmd.location_id),
                "work_type": cmd.work_type,
                "activity_date": cmd.activity_date,
                "started_at": cmd.started_at,
                "ended_at": cmd.ended_at,
                "narrative": cmd.narrative,
                "contractor": cmd.contractor,
                "reported_by_user_id": created_by,
                "source": cmd.source,
                "correlation_id": cmd.correlation_id,
            },
        )

        for q in cmd.quantities:
            await conn.execute(
                text(
                    "INSERT INTO activity_quantities "
                    "(id, activity_id, work_type, unit_id, quantity, measurement_type) "
                    "VALUES (:id, :activity_id, :work_type, :unit_id, :quantity, :measurement_type)"
                ),
                {
                    "id": uuid.uuid4(),
                    "activity_id": activity_id,
                    "work_type": q.work_type,
                    "unit_id": uuid.UUID(q.unit_id) if q.unit_id else None,
                    "quantity": q.quantity,
                    "measurement_type": q.measurement_type,
                },
            )

        payload = {
            "activity_date": cmd.activity_date.isoformat(),
            "occurred_date_source": cmd.occurred_date_source,
            "source": cmd.source,
            "work_type": cmd.work_type,
            "quantity_count": len(cmd.quantities),
        }
        await conn.execute(
            text(
                "INSERT INTO outbox_events "
                "(id, aggregate_type, aggregate_id, event_type, payload, correlation_id) "
                "VALUES (:id, :aggregate_type, :aggregate_id, :event_type, "
                "CAST(:payload AS jsonb), :correlation_id)"
            ),
            {
                "id": uuid.uuid4(),
                "aggregate_type": "activity",
                "aggregate_id": activity_id,
                "event_type": "ActivityCreated",
                "payload": json.dumps(payload),
                "correlation_id": cmd.correlation_id,
            },
        )

        result = ExecutionResult(
            status=ExecutionStatus.SUCCEEDED,
            idempotency_key=cmd.idempotency_key,
            # Shared contract field name (see labour_execution.py's identical
            # comment) — here it is activities.id.
            material_row_id=str(activity_id),
        )
        await conn.execute(
            text(
                "UPDATE idempotency_keys "
                "SET status = 'completed', result = CAST(:result AS jsonb), completed_at = now() "
                "WHERE key = :key"
            ),
            {"result": result.model_dump_json(), "key": cmd.idempotency_key},
        )

        await self._transition(conn, cmd.idempotency_key, WorkflowPhase.COMPLETED)
        return result

    async def persist_add_progress_update_success(
        self, conn: AsyncConnection, cmd: AddProgressUpdateCommand
    ) -> ExecutionResult:
        from sqlalchemy import text

        if not await self._try_claim(conn, cmd.idempotency_key, "add_progress_update"):
            existing = await self.check_idempotency(conn, cmd.idempotency_key)
            assert existing is not None
            return as_replay(existing)

        activity_id = uuid.UUID(cmd.activity_id)
        created_by = uuid.UUID(cmd.created_by)

        update_id = uuid.uuid4()
        await conn.execute(
            text(
                "INSERT INTO progress_updates "
                "(id, activity_id, occurred_at, update_kind, narrative, quantity, unit_id, "
                "reported_by_user_id, source, correlation_id) "
                "VALUES (:id, :activity_id, :occurred_at, :update_kind, :narrative, :quantity, "
                ":unit_id, :reported_by_user_id, :source, :correlation_id)"
            ),
            {
                "id": update_id,
                "activity_id": activity_id,
                "occurred_at": cmd.occurred_at,
                "update_kind": cmd.update_kind,
                "narrative": cmd.narrative,
                "quantity": cmd.quantity,
                "unit_id": uuid.UUID(cmd.unit_id) if cmd.unit_id else None,
                "reported_by_user_id": created_by,
                "source": cmd.source,
                "correlation_id": cmd.correlation_id,
            },
        )

        # STARTED/PAUSED/RESUMED/COMPLETED move the parent Activity's status.
        # This is the one field on activities this repository ever mutates
        # outside of creation -- it is a status transition, not a correction
        # (ADR-D14 governs corrections; this is ordinary lifecycle movement,
        # same as Work Package status), so no activity_corrections row is
        # written for it.
        #
        # Conflict Resolution (#12): this is the one place two concurrent
        # WhatsApp messages ("paused" from one engineer, "completed" from
        # another) can race on the SAME mutable field with no natural
        # append-only escape hatch. SELECT ... FOR UPDATE serializes the two
        # transactions on this row -- the second to arrive sees the first's
        # already-committed status, not the stale value it started with, so
        # this is a genuine lock-based prevention, not an after-the-fact
        # version compare that could still miss a race.
        _STATUS_BY_KIND = {
            "STARTED": "IN_PROGRESS",
            "RESUMED": "IN_PROGRESS",
            "PAUSED": "STOPPED",
            "COMPLETED": "COMPLETED",
        }
        new_status = _STATUS_BY_KIND.get(cmd.update_kind)
        conflict_note: str | None = None
        if new_status is not None:
            current_row = (
                await conn.execute(
                    text("SELECT status FROM activities WHERE id = :id FOR UPDATE"),
                    {"id": activity_id},
                )
            ).mappings().first()
            current_status = current_row["status"] if current_row is not None else None

            if current_status == new_status:
                # Two reports converging on the same status (e.g. both
                # engineers said "completed") is not a conflict -- it is
                # agreement. Nothing to write, nothing to flag.
                pass
            elif current_status == "COMPLETED":
                # COMPLETED is terminal in V1 -- no update_kind un-completes
                # an activity (there is no "reopen"). A status message that
                # arrives after someone else already completed it is the
                # genuine conflict case: applying it would silently revert a
                # finished activity back to in-progress/stopped. The
                # narrative/quantity above was still recorded (P1 -- an
                # append-only Progress Update is always safe to keep) --
                # only the status mutation is held back.
                conflict_note = (
                    "Note: this activity was already marked Completed by someone "
                    f"else, so its status was not changed to {new_status.replace('_', ' ').title()}."
                )
            else:
                await conn.execute(
                    text(
                        "UPDATE activities SET status = :status, updated_at = now() WHERE id = :id"
                    ),
                    {"status": new_status, "id": activity_id},
                )

        payload = {
            "update_kind": cmd.update_kind,
            "occurred_at": cmd.occurred_at.isoformat(),
            "quantity": str(cmd.quantity) if cmd.quantity is not None else None,
            "source": cmd.source,
            "status_conflict": conflict_note is not None,
        }
        await conn.execute(
            text(
                "INSERT INTO outbox_events "
                "(id, aggregate_type, aggregate_id, event_type, payload, correlation_id) "
                "VALUES (:id, :aggregate_type, :aggregate_id, :event_type, "
                "CAST(:payload AS jsonb), :correlation_id)"
            ),
            {
                "id": uuid.uuid4(),
                "aggregate_type": "activity",
                "aggregate_id": activity_id,
                "event_type": "ActivityProgressUpdateAdded",
                "payload": json.dumps(payload),
                "correlation_id": cmd.correlation_id,
            },
        )

        result = ExecutionResult(
            status=ExecutionStatus.SUCCEEDED,
            idempotency_key=cmd.idempotency_key,
            # Here it is progress_updates.id -- the row this confirmation
            # actually created, not the parent activity.
            material_row_id=str(update_id),
            conflict_note=conflict_note,
        )
        await conn.execute(
            text(
                "UPDATE idempotency_keys "
                "SET status = 'completed', result = CAST(:result AS jsonb), completed_at = now() "
                "WHERE key = :key"
            ),
            {"result": result.model_dump_json(), "key": cmd.idempotency_key},
        )

        await self._transition(conn, cmd.idempotency_key, WorkflowPhase.COMPLETED)
        return result

    async def persist_correct_activity_quantity_success(
        self, conn: AsyncConnection, cmd: CorrectActivityQuantityCommand
    ) -> ExecutionResult:
        """ADR-D14: "make that 180". Composes
        `PostgresProgressReadRepository.correct_progress_update` (same
        connection, same transaction) for the actual append-a-superseding-
        row write + activity_corrections audit + DPR revision-if-frozen --
        same reasoning as reverse_execution.py's use of
        PostgresProgressReadRepository.void_activity: duplicating that SQL
        here would be worse than the minor capability-boundary bend of
        calling out to another repository. This method only owns the
        idempotency claim, the outbox event, and the workflow transition."""
        from sqlalchemy import text

        from mesiri.infrastructure.postgres.repositories.progress import (
            PostgresProgressReadRepository,
        )

        if not await self._try_claim(conn, cmd.idempotency_key, "correct_activity_quantity"):
            existing = await self.check_idempotency(conn, cmd.idempotency_key)
            assert existing is not None
            return as_replay(existing)

        organization_id = uuid.UUID(cmd.organization_id)
        created_by = uuid.UUID(cmd.created_by)

        changes: dict[str, object] = {"quantity": cmd.new_quantity}
        new_unit_id = _optional_uuid(cmd.new_unit_id)
        if new_unit_id is not None:
            changes["unit_id"] = new_unit_id

        repo = PostgresProgressReadRepository(conn)
        if cmd.progress_update_id is None:
            # WRK-06: the quantity the activity was started with.
            corrected = await repo.correct_activity_quantity_row(
                organization_id=organization_id,
                quantity_id=uuid.UUID(str(cmd.activity_quantity_id)),
                quantity=cmd.new_quantity,
                unit_id=new_unit_id,
                reason=cmd.reason,
                corrected_by_user_id=created_by,
                correlation_id=cmd.correlation_id,
            )
        else:
            corrected = await repo.correct_progress_update(
                organization_id=organization_id,
                update_id=uuid.UUID(str(cmd.progress_update_id)),
                changes=changes,
                reason=cmd.reason,
                corrected_by_user_id=created_by,
                correlation_id=cmd.correlation_id,
                source=cmd.source,
            )

        if corrected is None:
            # The target no longer exists (deleted/undone) by confirm time
            # -- time can pass between the draft being built and the user
            # replying YES, same "recheck, then reject via the same
            # idempotency-keys bookkeeping" shape as
            # persist_close_site_issue_success above.
            result = ExecutionResult(
                status=ExecutionStatus.REJECTED,
                idempotency_key=cmd.idempotency_key,
                rejection_reasons=["that progress update no longer exists"],
            )
            await conn.execute(
                text(
                    "UPDATE idempotency_keys "
                    "SET status = 'completed', result = CAST(:result AS jsonb), completed_at = now() "
                    "WHERE key = :key"
                ),
                {"result": result.model_dump_json(), "key": cmd.idempotency_key},
            )
            await self._transition(conn, cmd.idempotency_key, WorkflowPhase.EXECUTION_REJECTED)
            return result

        await conn.execute(
            text(
                "INSERT INTO outbox_events "
                "(id, aggregate_type, aggregate_id, event_type, payload, correlation_id) "
                "VALUES (:id, 'activity', :aggregate_id, 'ActivityProgressUpdateCorrected', "
                "CAST(:payload AS jsonb), :correlation_id)"
            ),
            {
                "id": uuid.uuid4(),
                "aggregate_id": corrected["activity_id"],
                "payload": json.dumps(
                    {
                        "progress_update_id": str(corrected["id"]),
                        "supersedes_id": str(corrected["supersedes_id"] or ""),
                        "quantity": str(corrected["quantity"]),
                        "reason": cmd.reason,
                    },
                    default=str,
                ),
                "correlation_id": cmd.correlation_id,
            },
        )

        result = ExecutionResult(
            status=ExecutionStatus.SUCCEEDED,
            idempotency_key=cmd.idempotency_key,
            material_row_id=str(corrected["id"]),
        )
        await conn.execute(
            text(
                "UPDATE idempotency_keys "
                "SET status = 'completed', result = CAST(:result AS jsonb), completed_at = now() "
                "WHERE key = :key"
            ),
            {"result": result.model_dump_json(), "key": cmd.idempotency_key},
        )
        await self._transition(conn, cmd.idempotency_key, WorkflowPhase.COMPLETED)
        return result

    async def persist_report_site_issue_success(
        self, conn: AsyncConnection, cmd: ReportSiteIssueCommand
    ) -> ExecutionResult:
        """Insert a new site_issues row (status OPEN) + outbox event. Emits
        the same 'SiteIssueReported' event type the REST-only direct-write
        path (infrastructure/postgres/repositories/progress.py's create_issue)
        already emits -- both paths write the same aggregate, registered as
        'site_issue' in timeline_projector.py's AGGREGATE_TABLES, so they
        must produce identical event_type strings for the Timeline
        projection to treat them uniformly."""
        from sqlalchemy import text

        if not await self._try_claim(conn, cmd.idempotency_key, "report_site_issue"):
            existing = await self.check_idempotency(conn, cmd.idempotency_key)
            assert existing is not None
            return as_replay(existing)

        organization_id = uuid.UUID(cmd.organization_id)
        project_id = _optional_uuid(cmd.project_id)
        site_id = _optional_uuid(cmd.site_id)
        created_by = uuid.UUID(cmd.created_by)

        if project_id is None or site_id is None:
            # domains/progress/validation.py already rejects a missing
            # project before this is ever called; defensive guard against
            # calling this method directly with an unvalidated command,
            # matching persist_create_activity_success's identical check
            # (site_issues.project_id/site_id are NOT NULL).
            raise RuntimeError("project_id and site_id are required to persist a site issue")

        issue_id = uuid.uuid4()
        occurred_at = datetime.datetime.combine(cmd.occurred_date, datetime.time.min)
        await conn.execute(
            text(
                "INSERT INTO site_issues "
                "(id, organization_id, project_id, site_id, activity_id, issue_type, severity, "
                "narrative, delay_duration_minutes, occurred_at, status, reported_by_user_id, "
                "correlation_id) "
                "VALUES (:id, :organization_id, :project_id, :site_id, :activity_id, :issue_type, "
                ":severity, :narrative, :delay_duration_minutes, :occurred_at, 'OPEN', "
                ":reported_by_user_id, :correlation_id)"
            ),
            {
                "id": issue_id,
                "organization_id": organization_id,
                "project_id": project_id,
                "site_id": site_id,
                "activity_id": _optional_uuid(cmd.activity_id),
                "issue_type": cmd.issue_type,
                "severity": cmd.severity,
                "narrative": cmd.narrative,
                "delay_duration_minutes": cmd.delay_duration_minutes,
                "occurred_at": occurred_at,
                "reported_by_user_id": created_by,
                "correlation_id": cmd.correlation_id,
            },
        )

        payload = {
            "issue_type": cmd.issue_type,
            "severity": cmd.severity,
            "narrative": cmd.narrative,
            "delay_duration_minutes": cmd.delay_duration_minutes,
            "source": cmd.source,
        }
        await conn.execute(
            text(
                "INSERT INTO outbox_events "
                "(id, aggregate_type, aggregate_id, event_type, payload, correlation_id) "
                "VALUES (:id, 'site_issue', :aggregate_id, 'SiteIssueReported', "
                "CAST(:payload AS jsonb), :correlation_id)"
            ),
            {
                "id": uuid.uuid4(),
                "aggregate_id": issue_id,
                "payload": json.dumps(payload, default=str),
                "correlation_id": cmd.correlation_id,
            },
        )

        result = ExecutionResult(
            status=ExecutionStatus.SUCCEEDED,
            idempotency_key=cmd.idempotency_key,
            material_row_id=str(issue_id),
        )
        await conn.execute(
            text(
                "UPDATE idempotency_keys "
                "SET status = 'completed', result = CAST(:result AS jsonb), completed_at = now() "
                "WHERE key = :key"
            ),
            {"result": result.model_dump_json(), "key": cmd.idempotency_key},
        )

        await self._transition(conn, cmd.idempotency_key, WorkflowPhase.COMPLETED)
        return result

    #: Which CURRENT status still allows each close-out action -- mirrors
    #: infrastructure/postgres/repositories/progress.py's REST-only
    #: acknowledge_issue (OPEN only) / resolve_issue / wont_fix_issue
    #: (OPEN/ACKNOWLEDGED) WHERE clauses, re-checked here instead of trusted
    #: from draft-build time since time can pass before the user replies YES.
    #: `cancel` matches resolve/wont_fix: an issue is withdrawable while it
    #: is still live, and once it is terminal the honest record is whatever
    #: terminal state it already reached.
    #:
    #: `reopen` is the only backwards transition. It deliberately excludes
    #: CANCELLED -- reviving a report that was withdrawn as never-real would
    #: erase the distinction migration 0460 exists to keep; re-reporting is
    #: the route back from a cancellation. It includes ACKNOWLEDGED so
    #: "actually that's still open, nobody is on it" is expressible without
    #: first having to resolve the issue.
    _ALLOWED_CURRENT_STATUS_BY_ACTION = {
        "acknowledge": {"OPEN"},
        "resolve": {"OPEN", "ACKNOWLEDGED"},
        "wont_fix": {"OPEN", "ACKNOWLEDGED"},
        "cancel": {"OPEN", "ACKNOWLEDGED"},
        "reopen": {"ACKNOWLEDGED", "RESOLVED", "WONT_FIX"},
    }

    async def persist_close_site_issue_success(
        self, conn: AsyncConnection, cmd: CloseSiteIssueCommand
    ) -> ExecutionResult:
        from sqlalchemy import text

        if not await self._try_claim(conn, cmd.idempotency_key, "close_site_issue"):
            existing = await self.check_idempotency(conn, cmd.idempotency_key)
            assert existing is not None
            return as_replay(existing)

        issue_id = uuid.UUID(cmd.site_issue_id)
        organization_id = uuid.UUID(cmd.organization_id)

        # Defense-in-depth re-check, inline rather than a separate resolver
        # step (unlike reverse_resolution.py's cross-repository lookup, this
        # is a single self-contained status check on the row this same
        # transaction is about to update) -- SELECT ... FOR UPDATE so a
        # racing second confirmation can't both pass this check for the
        # same row.
        current = (
            await conn.execute(
                text(
                    "SELECT status FROM site_issues "
                    "WHERE organization_id = :org_id AND id = :id FOR UPDATE"
                ),
                {"org_id": organization_id, "id": issue_id},
            )
        ).mappings().first()
        current_status = current["status"] if current is not None else None
        allowed = self._ALLOWED_CURRENT_STATUS_BY_ACTION.get(cmd.action, set())
        if current_status not in allowed:
            reasons = (
                ["that issue no longer exists"]
                if current_status is None
                else [f"that issue is already {current_status.lower()}"]
            )
            result = ExecutionResult(
                status=ExecutionStatus.REJECTED,
                idempotency_key=cmd.idempotency_key,
                rejection_reasons=reasons,
            )
            await conn.execute(
                text(
                    "UPDATE idempotency_keys "
                    "SET status = 'completed', result = CAST(:result AS jsonb), completed_at = now() "
                    "WHERE key = :key"
                ),
                {"result": result.model_dump_json(), "key": cmd.idempotency_key},
            )
            await self._transition(conn, cmd.idempotency_key, WorkflowPhase.EXECUTION_REJECTED)
            return result

        now = datetime.datetime.now(datetime.UTC)
        if cmd.action == "acknowledge":
            await conn.execute(
                text(
                    "UPDATE site_issues SET status = 'ACKNOWLEDGED', updated_at = :now "
                    "WHERE organization_id = :org_id AND id = :id"
                ),
                {"org_id": organization_id, "id": issue_id, "now": now},
            )
            event_type = "SiteIssueAcknowledged"
            payload = {}
        elif cmd.action == "wont_fix":
            await conn.execute(
                text(
                    "UPDATE site_issues SET status = 'WONT_FIX', resolved_at = :now, "
                    "resolution_notes = :notes, updated_at = :now "
                    "WHERE organization_id = :org_id AND id = :id"
                ),
                {"org_id": organization_id, "id": issue_id, "now": now, "notes": cmd.resolution_notes},
            )
            event_type = "SiteIssueWontFix"
            payload = {"resolution_notes": cmd.resolution_notes}
        elif cmd.action == "cancel":
            # resolved_at is set even though nothing was resolved: the column
            # means "when this issue stopped being live," which is exactly
            # what a withdrawal is. Leaving it NULL would make a cancelled
            # issue read as still-open to every query that tests it, and
            # `status` already carries the distinction.
            await conn.execute(
                text(
                    "UPDATE site_issues SET status = 'CANCELLED', resolved_at = :now, "
                    "resolution_notes = :notes, updated_at = :now "
                    "WHERE organization_id = :org_id AND id = :id"
                ),
                {"org_id": organization_id, "id": issue_id, "now": now, "notes": cmd.resolution_notes},
            )
            event_type = "SiteIssueCancelled"
            payload = {"resolution_notes": cmd.resolution_notes}
        elif cmd.action == "reopen":
            # resolved_at and resolution_notes are cleared, not kept: they
            # describe a close-out that is being retracted, and leaving them
            # behind would leave the row asserting it was resolved at a time
            # it demonstrably was not. The retraction itself stays visible in
            # the outbox/timeline, so nothing about the history is lost.
            await conn.execute(
                text(
                    "UPDATE site_issues SET status = 'OPEN', resolved_at = NULL, "
                    "resolution_notes = NULL, updated_at = :now "
                    "WHERE organization_id = :org_id AND id = :id"
                ),
                {"org_id": organization_id, "id": issue_id, "now": now},
            )
            event_type = "SiteIssueReopened"
            # The reason for reopening, when the user gave one -- carried on
            # the event rather than the row, which is now back to describing
            # a live issue with no close-out to annotate.
            payload = {"reopen_notes": cmd.resolution_notes}
        else:  # resolve
            await conn.execute(
                text(
                    "UPDATE site_issues SET status = 'RESOLVED', resolved_at = :now, "
                    "resolution_notes = :notes, updated_at = :now "
                    "WHERE organization_id = :org_id AND id = :id"
                ),
                {"org_id": organization_id, "id": issue_id, "now": now, "notes": cmd.resolution_notes},
            )
            event_type = "SiteIssueResolved"
            payload = {"resolution_notes": cmd.resolution_notes}

        await conn.execute(
            text(
                "INSERT INTO outbox_events "
                "(id, aggregate_type, aggregate_id, event_type, payload, correlation_id) "
                "VALUES (:id, 'site_issue', :aggregate_id, :event_type, "
                "CAST(:payload AS jsonb), :correlation_id)"
            ),
            {
                "id": uuid.uuid4(),
                "aggregate_id": issue_id,
                "event_type": event_type,
                "payload": json.dumps(payload, default=str),
                "correlation_id": cmd.correlation_id,
            },
        )

        result = ExecutionResult(
            status=ExecutionStatus.SUCCEEDED,
            idempotency_key=cmd.idempotency_key,
            material_row_id=str(issue_id),
        )
        await conn.execute(
            text(
                "UPDATE idempotency_keys "
                "SET status = 'completed', result = CAST(:result AS jsonb), completed_at = now() "
                "WHERE key = :key"
            ),
            {"result": result.model_dump_json(), "key": cmd.idempotency_key},
        )
        await self._transition(conn, cmd.idempotency_key, WorkflowPhase.COMPLETED)
        return result

    async def persist_attach_evidence(
        self, conn: AsyncConnection, cmd: AttachEvidenceCommand
    ) -> list[str]:
        """Insert one progress_attachments row per media_object_key (#2 Batch
        Media). No idempotency_keys claim -- see AttachEvidenceCommand's
        docstring for why this never goes through the confirm/execute path
        every other persist_* method here does. Still emits one outbox
        event per photo (same "everything worth knowing about later flows
        through the outbox" convention as every other write in this file),
        carrying the activity_id so a future Search Index consumer can
        index "this activity now has N photos" without querying
        progress_attachments directly.
        """
        from sqlalchemy import text

        activity_id = uuid.UUID(cmd.activity_id)
        uploaded_by = uuid.UUID(cmd.uploaded_by)
        created_ids: list[str] = []

        for media_object_key in cmd.media_object_keys:
            attachment_id = uuid.uuid4()
            await conn.execute(
                text(
                    "INSERT INTO progress_attachments "
                    "(id, parent_type, parent_id, media_object_key, attachment_type, "
                    "mime_type, caption, uploaded_by_user_id, created_at) "
                    # clock_timestamp(), not the transaction's now(): a batch keeps
                    # the order the photos were sent in.
                    "VALUES (:id, 'ACTIVITY', :parent_id, :media_object_key, "
                    "'site_photo', :mime_type, :caption, :uploaded_by, clock_timestamp())"
                ),
                {
                    "id": attachment_id,
                    "parent_id": activity_id,
                    "media_object_key": media_object_key,
                    "mime_type": cmd.mime_type,
                    "caption": cmd.caption,
                    "uploaded_by": uploaded_by,
                },
            )
            await conn.execute(
                text(
                    "INSERT INTO outbox_events "
                    "(id, aggregate_type, aggregate_id, event_type, payload, correlation_id) "
                    "VALUES (:id, :aggregate_type, :aggregate_id, :event_type, "
                    "CAST(:payload AS jsonb), :correlation_id)"
                ),
                {
                    "id": uuid.uuid4(),
                    "aggregate_type": "activity",
                    "aggregate_id": activity_id,
                    "event_type": "ActivityEvidenceAttached",
                    "payload": json.dumps({"attachment_id": str(attachment_id)}),
                    "correlation_id": cmd.correlation_id,
                },
            )
            created_ids.append(str(attachment_id))

        return created_ids

    async def persist_rejection(
        self,
        conn: AsyncConnection,
        idempotency_key: str,
        command_type: str,
        reasons: list[str],
    ) -> ExecutionResult:
        from sqlalchemy import text

        if not await self._try_claim(conn, idempotency_key, command_type):
            existing = await self.check_idempotency(conn, idempotency_key)
            assert existing is not None
            return as_replay(existing)

        result = ExecutionResult(
            status=ExecutionStatus.REJECTED,
            idempotency_key=idempotency_key,
            rejection_reasons=reasons,
        )
        await conn.execute(
            text(
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
        domain write, using the current version read fresh from this connection."""
        loaded = await get_by_id_on_connection(conn, workflow_instance_id)
        if loaded is None:
            return  # nothing to transition (shouldn't happen; defensive, not fatal)
        new_state = loaded.state.model_copy(update={"phase": new_phase})
        await transition_on_connection(conn, workflow_instance_id, loaded.version, new_state)
