"""Read access for activities, progress updates, and site issues -- plus the
dashboard-direct corrections/undo ADR-D14/D15 define.

Companion to progress_execution.py, which owns the *write* path a WhatsApp
confirmation takes for a brand-new Activity/Progress Update. This file is
everything else: reads, Site Issues (dashboard-direct, no confirm step --
see create_issue/acknowledge_issue etc. above), and now corrections/undo of
an already-recorded Activity or Progress Update, per
docs/execution/DAILY_REPORTING_PLAN.md's ADR-D14/D15:

  ADR-D14 (correction) -- a wrong Activity-header field (work_type,
  location_id, contractor, narrative, activity_date) is corrected by a
  direct UPDATE + an activity_corrections audit row
  (`correct_activity_fields`). A wrong Progress Update quantity is
  corrected by *appending* a new row that supersedes the old one -- the old
  row is never edited or deleted (`correct_progress_update`); Progress
  Updates stay append-only (P1) even under correction.

  ADR-D15 (undo) -- removing an Activity/Progress Update entirely
  (`void_activity`/`void_progress_update`) is a soft delete
  (`deleted_at`), and -- unlike correction -- is refused outright once the
  value has been frozen into an APPROVED/PUBLISHED daily_report_versions
  row (P7). Correction is allowed past that point and produces a DPR
  revision instead (see `_revise_dpr_if_frozen`); undo is not, because
  there is no way to "revise a report to remove something" without also
  deciding what replaces it -- that's a correction, not an undo.
"""

from __future__ import annotations

import datetime
import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.application.dpr import fact_review

# site_issue_type / site_issue_status enum members (migration 0430) — kept
# here rather than in domains/progress/validation.py because that file only
# validates the WhatsApp-confirmed command path (CreateActivityCommand /
# AddProgressUpdateCommand); Site Issues are written directly by this
# dashboard-facing REST path (no confirm step), so their own validation lives
# next to the SQL it guards.
VALID_ISSUE_TYPES = frozenset(
    {
        "WEATHER",
        "MATERIAL_SHORTAGE",
        "LABOUR_SHORTAGE",
        "DRAWING_PENDING",
        "EQUIPMENT_BREAKDOWN",
        "INSPECTION_WAITING",
        "ACCESS",
        "SAFETY",
        "QUALITY",
        "OTHER",
    }
)
VALID_ISSUE_SEVERITIES = frozenset({"LOW", "MEDIUM", "HIGH", "CRITICAL"})


class PostgresProgressReadRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def list_activities(
        self,
        *,
        organization_id: uuid.UUID,
        project_ids: set[uuid.UUID] | None,
        site_id: uuid.UUID | None,
        date_from: datetime.date | None,
        date_to: datetime.date | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], int]:
        # WA-77: the site log is what is saved; an unsaved entry isn't in it yet.
        where = [
            "organization_id = :organization_id",
            "deleted_at IS NULL",
            fact_review.counted_sql(fact_review.ACTIVITY, "activities.id"),
        ]
        params: dict[str, Any] = {"organization_id": organization_id, "limit": limit, "offset": offset}

        if project_ids is not None:
            where.append("project_id = ANY(:project_ids)")
            params["project_ids"] = list(project_ids)
        if site_id is not None:
            where.append("site_id = :site_id")
            params["site_id"] = site_id
        if date_from is not None:
            where.append("activity_date >= :date_from")
            params["date_from"] = date_from
        if date_to is not None:
            where.append("activity_date <= :date_to")
            params["date_to"] = date_to
        if status is not None:
            where.append("status = :status")
            params["status"] = status

        where_clause = " AND ".join(where)

        total_row = (
            await self._conn.execute(
                text(f"SELECT COUNT(*) AS total FROM activities WHERE {where_clause}"), params
            )
        ).mappings().first()
        total = total_row["total"] if total_row else 0

        rows = (
            await self._conn.execute(
                text(
                    f"SELECT id, organization_id, project_id, site_id, work_package_id, "
                    f"location_id, work_type, activity_date, started_at, ended_at, status, "
                    f"narrative, contractor, reported_by_user_id, source, created_at, updated_at "
                    f"FROM activities WHERE {where_clause} "
                    f"ORDER BY activity_date DESC, created_at DESC LIMIT :limit OFFSET :offset"
                ),
                params,
            )
        ).mappings().all()
        return [dict(row) for row in rows], total

    async def get_activity(
        self, organization_id: uuid.UUID, activity_id: uuid.UUID
    ) -> dict[str, Any] | None:
        row = (
            (
                await self._conn.execute(
                    text(
                        "SELECT id, organization_id, project_id, site_id, work_package_id, "
                        "location_id, work_type, activity_date, started_at, ended_at, status, "
                        "narrative, contractor, reported_by_user_id, source, created_at, updated_at "
                        "FROM activities WHERE organization_id = :org_id AND id = :id "
                        "AND deleted_at IS NULL"
                    ),
                    {"org_id": organization_id, "id": activity_id},
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            return None

        item = dict(row)

        quantities = (
            (
                await self._conn.execute(
                    text(
                        "SELECT aq.id, aq.work_type, aq.unit_id, u.code AS unit, aq.quantity, "
                        "aq.measurement_type "
                        "FROM activity_quantities aq "
                        "LEFT JOIN units_of_measure u ON u.id = aq.unit_id "
                        "WHERE aq.activity_id = :activity_id ORDER BY aq.created_at ASC"
                    ),
                    {"activity_id": activity_id},
                )
            )
            .mappings()
            .all()
        )
        item["quantities"] = [dict(q) for q in quantities]

        updates = (
            (
                await self._conn.execute(
                    text(
                        "SELECT pu.id, pu.occurred_at, pu.update_kind, pu.narrative, pu.quantity, "
                        "pu.unit_id, u.code AS unit, pu.supersedes_id, pu.reported_by_user_id, "
                        "pu.source, pu.created_at "
                        "FROM progress_updates pu "
                        "LEFT JOIN units_of_measure u ON u.id = pu.unit_id "
                        "WHERE pu.activity_id = :activity_id AND pu.deleted_at IS NULL "
                        "ORDER BY pu.occurred_at ASC"
                    ),
                    {"activity_id": activity_id},
                )
            )
            .mappings()
            .all()
        )
        item["progress_updates"] = [dict(u) for u in updates]

        attachments = (
            (
                await self._conn.execute(
                    text(
                        "SELECT id, media_object_key, attachment_type, mime_type, caption, "
                        "ai_caption, role, captured_at, created_at "
                        "FROM progress_attachments "
                        "WHERE parent_type = 'ACTIVITY' AND parent_id = :activity_id "
                        "ORDER BY created_at ASC"
                    ),
                    {"activity_id": activity_id},
                )
            )
            .mappings()
            .all()
        )
        item["attachments"] = [dict(a) for a in attachments]

        return item

    async def list_issues(
        self,
        *,
        organization_id: uuid.UUID,
        project_ids: set[uuid.UUID] | None,
        site_id: uuid.UUID | None,
        status: str | None,
        severity: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], int]:
        # WA-77: an issue counts once it is saved.
        where = [
            "organization_id = :organization_id",
            fact_review.counted_sql(fact_review.SITE_ISSUE, "site_issues.id"),
        ]
        params: dict[str, Any] = {"organization_id": organization_id, "limit": limit, "offset": offset}

        if project_ids is not None:
            where.append("project_id = ANY(:project_ids)")
            params["project_ids"] = list(project_ids)
        if site_id is not None:
            where.append("site_id = :site_id")
            params["site_id"] = site_id
        if status is not None:
            where.append("status = :status")
            params["status"] = status
        if severity is not None:
            where.append("severity = :severity")
            params["severity"] = severity

        where_clause = " AND ".join(where)

        total_row = (
            await self._conn.execute(
                text(f"SELECT COUNT(*) AS total FROM site_issues WHERE {where_clause}"), params
            )
        ).mappings().first()
        total = total_row["total"] if total_row else 0

        rows = (
            await self._conn.execute(
                text(
                    f"SELECT id, organization_id, project_id, site_id, activity_id, "
                    f"work_package_id, location_id, issue_type, severity, narrative, "
                    f"delay_duration_minutes, occurred_at, resolved_at, status, "
                    f"resolution_notes, assigned_user_id, reported_by_user_id, "
                    f"created_at, updated_at "
                    f"FROM site_issues WHERE {where_clause} "
                    f"ORDER BY occurred_at DESC LIMIT :limit OFFSET :offset"
                ),
                params,
            )
        ).mappings().all()
        return [dict(row) for row in rows], total

    async def get_issue(
        self, organization_id: uuid.UUID, issue_id: uuid.UUID
    ) -> dict[str, Any] | None:
        row = (
            (
                await self._conn.execute(
                    text(
                        "SELECT id, organization_id, project_id, site_id, activity_id, "
                        "work_package_id, location_id, issue_type, severity, narrative, "
                        "delay_duration_minutes, occurred_at, resolved_at, status, "
                        "resolution_notes, assigned_user_id, reported_by_user_id, "
                        "created_at, updated_at "
                        "FROM site_issues WHERE organization_id = :org_id AND id = :id"
                    ),
                    {"org_id": organization_id, "id": issue_id},
                )
            )
            .mappings()
            .first()
        )
        return dict(row) if row is not None else None

    async def find_latest_by_status(
        self,
        organization_id: uuid.UUID,
        project_id: uuid.UUID | None,
        site_id: uuid.UUID | None,
        statuses: tuple[str, ...],
        by_transition_time: bool = False,
    ) -> dict[str, Any] | None:
        """The most recently CREATED site issue in one of `statuses` --
        WhatsApp's "acknowledge/resolve/wont-fix my last issue" close-out
        workflow's target resolution (runtime/site_issue_query.py). Ordered
        by created_at DESC (row-insertion time), not occurred_at (the
        business moment) -- list_issues above orders by occurred_at for its
        own display purposes, but "my last issue" means the one most
        recently reported, matching the precedent
        PostgresExpenseRepository.find_latest_confirmed /
        PostgresMoneyTransactionRepository.find_latest_reversible_transfer
        already set for Reversal's identical "most recent record" need.

        `by_transition_time` flips that to "the issue whose status most
        recently CHANGED," which is what the `reopen` action means: "that's
        not actually fixed" points at the issue the user just closed, not at
        whichever issue happens to have been reported last. With A reported
        Monday, B reported Tuesday and acknowledged, and A resolved
        Wednesday, created_at DESC would hand back B -- an issue nobody was
        talking about. Ordered by COALESCE(resolved_at, updated_at) because
        an ACKNOWLEDGED row has no resolved_at but did have its updated_at
        moved by the acknowledgement."""
        where = ["organization_id = :organization_id", "status = ANY(:statuses)"]
        params: dict[str, Any] = {"organization_id": organization_id, "statuses": list(statuses)}
        if project_id is not None:
            where.append("project_id = :project_id")
            params["project_id"] = project_id
        if site_id is not None:
            where.append("site_id = :site_id")
            params["site_id"] = site_id
        where_clause = " AND ".join(where)
        order_by = (
            "COALESCE(resolved_at, updated_at) DESC" if by_transition_time else "created_at DESC"
        )

        row = (
            (
                await self._conn.execute(
                    text(
                        f"SELECT id, issue_type, severity, narrative, status "
                        f"FROM site_issues WHERE {where_clause} "
                        f"ORDER BY {order_by} LIMIT 1"
                    ),
                    params,
                )
            )
            .mappings()
            .first()
        )
        return dict(row) if row is not None else None

    async def _emit_issue_event(
        self,
        *,
        issue_id: uuid.UUID,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        """INSERT one outbox_events row for a Site Issue lifecycle change,
        the same generic mechanism progress_execution.py uses for
        Activity/Progress Update events. Site Issues have no confirm step
        (dashboard-only, no WhatsApp draft), so there is no
        idempotency_key/correlation_id here — just a plain fact for
        timeline_projector.py to pick up (registered as aggregate_type
        'site_issue' in AGGREGATE_TABLES)."""
        await self._conn.execute(
            text(
                "INSERT INTO outbox_events "
                "(id, aggregate_type, aggregate_id, event_type, payload) "
                "VALUES (:id, 'site_issue', :aggregate_id, :event_type, CAST(:payload AS jsonb))"
            ),
            {
                "id": uuid.uuid4(),
                "aggregate_id": issue_id,
                "event_type": event_type,
                "payload": json.dumps(payload, default=str),
            },
        )

    async def create_issue(
        self, organization_id: uuid.UUID, user_id: uuid.UUID, payload: dict[str, Any]
    ) -> dict[str, Any]:
        issue_id = uuid.uuid4()
        now = datetime.datetime.now(datetime.UTC)
        issue_type = payload.get("issue_type") or "OTHER"
        severity = payload.get("severity") or "MEDIUM"
        if issue_type not in VALID_ISSUE_TYPES:
            raise ValueError(f"invalid issue_type: {issue_type}")
        if severity not in VALID_ISSUE_SEVERITIES:
            raise ValueError(f"invalid severity: {severity}")

        query = """
            INSERT INTO site_issues (
                id, organization_id, project_id, site_id, activity_id, work_package_id,
                location_id, issue_type, severity, narrative, delay_duration_minutes,
                occurred_at, status, assigned_user_id, reported_by_user_id, created_at, updated_at
            ) VALUES (
                :id, :organization_id, :project_id, :site_id, :activity_id, :work_package_id,
                :location_id, :issue_type, :severity, :narrative, :delay_duration_minutes,
                :occurred_at, 'OPEN', :assigned_user_id, :reported_by_user_id, :now, :now
            ) RETURNING id, organization_id, project_id, site_id, activity_id,
                        work_package_id, location_id, issue_type, severity, narrative,
                        delay_duration_minutes, occurred_at, resolved_at, status,
                        resolution_notes, assigned_user_id, reported_by_user_id,
                        created_at, updated_at
        """
        params = {
            "id": issue_id,
            "organization_id": organization_id,
            "project_id": payload["project_id"],
            "site_id": payload["site_id"],
            "activity_id": payload.get("activity_id"),
            "work_package_id": payload.get("work_package_id"),
            "location_id": payload.get("location_id"),
            "issue_type": issue_type,
            "severity": severity,
            "narrative": payload.get("narrative"),
            "delay_duration_minutes": payload.get("delay_duration_minutes"),
            "occurred_at": now,
            "assigned_user_id": payload.get("assigned_user_id"),
            "reported_by_user_id": user_id,
            "now": now,
        }
        res = (await self._conn.execute(text(query), params)).mappings().first()
        result = dict(res)

        await self._emit_issue_event(
            issue_id=issue_id,
            event_type="SiteIssueReported",
            payload={
                "issue_type": issue_type,
                "severity": severity,
                "narrative": payload.get("narrative"),
                "delay_duration_minutes": payload.get("delay_duration_minutes"),
            },
        )
        return result

    async def acknowledge_issue(
        self, organization_id: uuid.UUID, issue_id: uuid.UUID
    ) -> bool:
        """OPEN -> ACKNOWLEDGED only. Mirrors resolve_issue's shape but
        narrower: acknowledging an already-ACKNOWLEDGED/RESOLVED/WONT_FIX
        issue is a no-op (returns False), same as re-resolving one does."""
        now = datetime.datetime.now(datetime.UTC)
        query = """
            UPDATE site_issues
            SET status = 'ACKNOWLEDGED', updated_at = :now
            WHERE organization_id = :org_id AND id = :id AND status = 'OPEN'
        """
        res = await self._conn.execute(text(query), {"org_id": organization_id, "id": issue_id, "now": now})
        if res.rowcount > 0:
            await self._emit_issue_event(issue_id=issue_id, event_type="SiteIssueAcknowledged", payload={})
        return res.rowcount > 0

    async def wont_fix_issue(
        self, organization_id: uuid.UUID, issue_id: uuid.UUID, notes: str | None
    ) -> bool:
        """OPEN/ACKNOWLEDGED -> WONT_FIX. Terminal in the sense that no
        forward action follows it. It is no longer true that it "is not
        later reopened": the WhatsApp `reopen` close-out action can return a
        WONT_FIX issue to OPEN (see progress_execution.py's
        _ALLOWED_CURRENT_STATUS_BY_ACTION). This REST path simply does not
        offer that transition -- the dashboard has no reopen button."""
        now = datetime.datetime.now(datetime.UTC)
        query = """
            UPDATE site_issues
            SET status = 'WONT_FIX', resolved_at = :now, resolution_notes = :notes, updated_at = :now
            WHERE organization_id = :org_id AND id = :id AND status IN ('OPEN', 'ACKNOWLEDGED')
        """
        res = await self._conn.execute(
            text(query), {"org_id": organization_id, "id": issue_id, "notes": notes, "now": now}
        )
        if res.rowcount > 0:
            await self._emit_issue_event(
                issue_id=issue_id, event_type="SiteIssueWontFix", payload={"resolution_notes": notes}
            )
        return res.rowcount > 0

    async def cancel_issue(
        self, organization_id: uuid.UUID, issue_id: uuid.UUID, notes: str | None
    ) -> bool:
        """OPEN/ACKNOWLEDGED -> CANCELLED: the issue was never real (reported
        in error), which migration 0460 keeps distinct from WONT_FIX. The
        REST counterpart of the WhatsApp `cancel` close-out action (same
        allowed statuses, same columns, same event), added for rejecting a
        draft issue (BE-09)."""
        now = datetime.datetime.now(datetime.UTC)
        query = """
            UPDATE site_issues
            SET status = 'CANCELLED', resolved_at = :now, resolution_notes = :notes, updated_at = :now
            WHERE organization_id = :org_id AND id = :id AND status IN ('OPEN', 'ACKNOWLEDGED')
        """
        res = await self._conn.execute(
            text(query), {"org_id": organization_id, "id": issue_id, "notes": notes, "now": now}
        )
        if res.rowcount > 0:
            await self._emit_issue_event(
                issue_id=issue_id, event_type="SiteIssueCancelled", payload={"resolution_notes": notes}
            )
        return res.rowcount > 0

    async def resolve_issue(
        self, organization_id: uuid.UUID, issue_id: uuid.UUID, notes: str | None
    ) -> bool:
        now = datetime.datetime.now(datetime.UTC)
        query = """
            UPDATE site_issues
            SET status = 'RESOLVED', resolved_at = :now, resolution_notes = :notes, updated_at = :now
            WHERE organization_id = :org_id AND id = :id AND status != 'RESOLVED'
        """
        res = await self._conn.execute(text(query), {"org_id": organization_id, "id": issue_id, "notes": notes, "now": now})
        if res.rowcount > 0:
            await self._emit_issue_event(
                issue_id=issue_id, event_type="SiteIssueResolved", payload={"resolution_notes": notes}
            )
        return res.rowcount > 0

    async def list_gallery(
        self,
        organization_id: uuid.UUID,
        project_ids: set[uuid.UUID] | None = None,
        site_id: uuid.UUID | None = None,
        attachment_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        # progress_attachments has no organization/project/site of its own
        # (migration 0430): they come from the parent -- the work item, or the
        # issue -- the same join the DPR photo counts use. The gallery query
        # used to read pa.organization_id etc. directly and failed on every
        # call (WEB-24). Photos of removed work items are left out.
        source = """
            FROM progress_attachments pa
            LEFT JOIN activities a
              ON pa.parent_type = 'ACTIVITY' AND a.id = pa.parent_id AND a.deleted_at IS NULL
            LEFT JOIN site_issues si
              ON pa.parent_type = 'SITE_ISSUE' AND si.id = pa.parent_id
        """
        where = ["COALESCE(a.organization_id, si.organization_id) = :organization_id"]
        params: dict[str, Any] = {"organization_id": organization_id, "limit": limit, "offset": offset}

        if project_ids is not None:
            where.append("COALESCE(a.project_id, si.project_id) = ANY(:project_ids)")
            params["project_ids"] = list(project_ids)
        if site_id is not None:
            where.append("COALESCE(a.site_id, si.site_id) = :site_id")
            params["site_id"] = site_id
        if attachment_type is not None:
            where.append("pa.attachment_type = :attachment_type")
            params["attachment_type"] = attachment_type

        where_clause = " AND ".join(where)

        total_row = (
            await self._conn.execute(text(f"SELECT COUNT(*) AS total {source} WHERE {where_clause}"), params)
        ).mappings().first()
        total = total_row["total"] if total_row else 0

        query = f"""
            SELECT
                pa.id,
                COALESCE(a.organization_id, si.organization_id) AS organization_id,
                COALESCE(a.project_id, si.project_id) AS project_id,
                COALESCE(a.site_id, si.site_id) AS site_id,
                pa.parent_type,
                pa.parent_id,
                pa.media_object_key,
                pa.attachment_type,
                pa.mime_type,
                pa.caption,
                pa.ai_caption,
                pa.role,
                pa.captured_at,
                pa.created_at,
                COALESCE(a.activity_date, (si.occurred_at AT TIME ZONE 'UTC')::date) AS work_date,
                COALESCE(a.work_type, si.narrative) AS parent_title
            {source}
            WHERE {where_clause}
            ORDER BY work_date DESC NULLS LAST, pa.created_at DESC
            LIMIT :limit OFFSET :offset
        """
        rows = (await self._conn.execute(text(query), params)).mappings().all()
        return [dict(r) for r in rows], total

    # ------------------------------------------------------------------
    # Corrections & undo (ADR-D14/D15) -- see module docstring.
    # ------------------------------------------------------------------

    #: ADR-D14's explicit list (work_type, location_id, contractor) plus two
    #: reasonable additions the ADR doesn't exclude: narrative (a typo is as
    #: correctable as any other header field) and activity_date (the day
    #: the work happened, distinct from occurred_at on a Progress Update).
    #: work_package_id/quantities are deliberately not here -- correcting
    #: those needs a picker UI that doesn't exist yet (module audit finding
    #: A: work packages/locations are unused schema in V1).
    _CORRECTABLE_ACTIVITY_FIELDS = frozenset(
        {"work_type", "location_id", "contractor", "narrative", "activity_date"}
    )

    #: A Progress Update is never edited (ADR-D14) -- these are the fields a
    #: *superseding* row may carry a different value for.
    _CORRECTABLE_UPDATE_FIELDS = frozenset({"quantity", "unit_id", "narrative"})

    async def _record_correction(
        self,
        *,
        activity_id: uuid.UUID,
        field_name: str,
        old_value: Any,
        new_value: Any,
        reason: str | None,
        corrected_by_user_id: uuid.UUID | None,
        correlation_id: str | None,
    ) -> None:
        await self._conn.execute(
            text(
                "INSERT INTO activity_corrections "
                "(id, activity_id, field_name, old_value, new_value, reason, "
                "corrected_by_user_id, correlation_id) "
                "VALUES (:id, :activity_id, :field_name, CAST(:old_value AS jsonb), "
                "CAST(:new_value AS jsonb), :reason, :corrected_by_user_id, :correlation_id)"
            ),
            {
                "id": uuid.uuid4(),
                "activity_id": activity_id,
                "field_name": field_name,
                "old_value": json.dumps(old_value, default=str),
                "new_value": json.dumps(new_value, default=str),
                "reason": reason,
                "corrected_by_user_id": corrected_by_user_id,
                "correlation_id": correlation_id,
            },
        )

    async def _revise_dpr_if_frozen(
        self,
        *,
        organization_id: uuid.UUID,
        project_id: uuid.UUID,
        site_id: uuid.UUID,
        report_date: datetime.date,
        reason: str,
    ) -> None:
        """The ADR-D14 consequence: a correction to a value already frozen
        into an APPROVED/PUBLISHED DPR version (P7) does not silently leave
        the report wrong -- it produces a new, visibly different revision
        (the exact mechanism `daily_report_versions`' own docstring
        describes). A DRAFT/IN_REVIEW/NOT_REPORTED report, or no report at
        all yet, needs no action: the next normal generation run picks up
        the correction on its own."""
        from mesiri.infrastructure.postgres.repositories.dpr import PostgresDprRepository

        dpr_repo = PostgresDprRepository(self._conn)
        report = await dpr_repo.find_site_report(
            organization_id=organization_id,
            project_id=project_id,
            site_id=site_id,
            report_date=report_date,
        )
        if report is None or report["status"] not in ("APPROVED", "PUBLISHED"):
            return

        payload = await dpr_repo.assemble_site_report_payload(
            organization_id=organization_id,
            project_id=project_id,
            site_id=site_id,
            report_date=report_date,
        )
        await dpr_repo.revise_version(
            daily_report_id=report["id"],
            payload=payload,
            narrative_summary=None,
            revision_reason=reason,
        )

    async def _is_frozen(
        self,
        *,
        organization_id: uuid.UUID,
        project_id: uuid.UUID,
        site_id: uuid.UUID,
        report_date: datetime.date,
    ) -> bool:
        """ADR-D15: undo is refused once a DPR version has frozen this
        day's report (unlike correction, which is allowed and revises the
        report instead -- see `_revise_dpr_if_frozen`)."""
        from mesiri.infrastructure.postgres.repositories.dpr import PostgresDprRepository

        dpr_repo = PostgresDprRepository(self._conn)
        report = await dpr_repo.find_site_report(
            organization_id=organization_id,
            project_id=project_id,
            site_id=site_id,
            report_date=report_date,
        )
        return report is not None and report["status"] in ("APPROVED", "PUBLISHED")

    async def correct_activity_fields(
        self,
        *,
        organization_id: uuid.UUID,
        activity_id: uuid.UUID,
        changes: dict[str, Any],
        reason: str | None,
        corrected_by_user_id: uuid.UUID | None,
        correlation_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Correct one or more Activity header fields (ADR-D14). Returns the
        updated activity (get_activity shape) or None if not found/deleted.
        Writes one activity_corrections row per field whose value actually
        changed -- a no-op "correction" to the same value writes nothing.
        Allowed even once the day is frozen into an approved DPR (unlike
        undo) -- see `_revise_dpr_if_frozen`."""
        unknown = set(changes) - self._CORRECTABLE_ACTIVITY_FIELDS
        if unknown:
            raise ValueError(f"cannot correct fields: {sorted(unknown)}")
        if not changes:
            return await self.get_activity(organization_id, activity_id)

        current = (
            await self._conn.execute(
                text(
                    "SELECT project_id, site_id, activity_date, work_type, location_id, "
                    "contractor, narrative "
                    "FROM activities WHERE organization_id = :org_id AND id = :id "
                    "AND deleted_at IS NULL"
                ),
                {"org_id": organization_id, "id": activity_id},
            )
        ).mappings().first()
        if current is None:
            return None

        set_clauses: list[str] = []
        params: dict[str, Any] = {"id": activity_id, "now": datetime.datetime.now(datetime.UTC)}
        corrections: list[tuple[str, Any, Any]] = []
        for field, new_value in changes.items():
            old_value = current[field]
            if old_value == new_value:
                continue
            set_clauses.append(f"{field} = :{field}")
            params[field] = new_value
            corrections.append((field, old_value, new_value))

        if not corrections:
            return await self.get_activity(organization_id, activity_id)

        set_clauses.append("updated_at = :now")
        await self._conn.execute(
            text(f"UPDATE activities SET {', '.join(set_clauses)} WHERE id = :id"), params
        )

        for field, old_value, new_value in corrections:
            await self._record_correction(
                activity_id=activity_id,
                field_name=field,
                old_value=old_value,
                new_value=new_value,
                reason=reason,
                corrected_by_user_id=corrected_by_user_id,
                correlation_id=correlation_id,
            )

        await self._revise_dpr_if_frozen(
            organization_id=organization_id,
            project_id=current["project_id"],
            site_id=current["site_id"],
            report_date=current["activity_date"],
            reason=reason or f"Activity corrected: {', '.join(f for f, _, _ in corrections)}",
        )

        return await self.get_activity(organization_id, activity_id)

    async def void_activity(
        self,
        *,
        organization_id: uuid.UUID,
        activity_id: uuid.UUID,
        reason: str,
        corrected_by_user_id: uuid.UUID | None,
        correlation_id: str | None = None,
    ) -> str | None:
        """Soft-delete an Activity (ADR-D15) -- never a hard delete, and
        refused once the day is frozen into an approved DPR (P7). Returns
        None on success, or a short rejection reason string. Voiding the
        parent is enough on its own: every read path (get_activity,
        list_activities, WhatsApp's find_open_activity(ies)) already
        filters `activities.deleted_at IS NULL` / joins through the parent
        lookup, so activity_quantities/progress_updates/
        progress_attachments underneath become invisible without a second
        write."""
        if not reason or not reason.strip():
            return "reason is required to void an activity"

        current = (
            await self._conn.execute(
                text(
                    "SELECT project_id, site_id, activity_date FROM activities "
                    "WHERE organization_id = :org_id AND id = :id AND deleted_at IS NULL"
                ),
                {"org_id": organization_id, "id": activity_id},
            )
        ).mappings().first()
        if current is None:
            return "activity not found"

        if await self._is_frozen(
            organization_id=organization_id,
            project_id=current["project_id"],
            site_id=current["site_id"],
            report_date=current["activity_date"],
        ):
            return "this activity is already part of an approved daily report and cannot be undone"

        now = datetime.datetime.now(datetime.UTC)
        res = await self._conn.execute(
            text(
                "UPDATE activities SET deleted_at = :now, updated_at = :now "
                "WHERE organization_id = :org_id AND id = :id AND deleted_at IS NULL"
            ),
            {"org_id": organization_id, "id": activity_id, "now": now},
        )
        if res.rowcount == 0:
            return "activity not found"

        await self._record_correction(
            activity_id=activity_id,
            field_name="_voided",
            old_value=None,
            new_value=True,
            reason=reason,
            corrected_by_user_id=corrected_by_user_id,
            correlation_id=correlation_id,
        )
        return None

    async def correct_progress_update(
        self,
        *,
        organization_id: uuid.UUID,
        update_id: uuid.UUID,
        changes: dict[str, Any],
        reason: str | None,
        corrected_by_user_id: uuid.UUID | None,
        correlation_id: str | None = None,
        source: str = "dashboard",
    ) -> dict[str, Any] | None:
        """Correct a Progress Update (ADR-D14) by appending a new row that
        supersedes the old one -- Progress Updates stay append-only (P1)
        even under correction; the old row is never edited or deleted.
        Returns the new row's shape, or None if `update_id` doesn't exist /
        belong to this organization / is already deleted. Allowed even
        once the day is frozen (unlike void_progress_update) -- see
        `_revise_dpr_if_frozen`.

        Shared by the dashboard PATCH endpoint and the WhatsApp
        ACTIVITY_CORRECTION workflow's execution handler (`source`
        distinguishes which one wrote it, same convention every other
        operational record uses)."""
        unknown = set(changes) - self._CORRECTABLE_UPDATE_FIELDS
        if unknown:
            raise ValueError(f"cannot correct fields: {sorted(unknown)}")

        old = (
            await self._conn.execute(
                text(
                    "SELECT pu.id, pu.activity_id, pu.occurred_at, pu.update_kind, pu.narrative, "
                    "pu.quantity, pu.unit_id, a.organization_id, a.project_id, a.site_id, "
                    "a.activity_date "
                    "FROM progress_updates pu JOIN activities a ON a.id = pu.activity_id "
                    "WHERE pu.id = :id AND a.organization_id = :org_id AND pu.deleted_at IS NULL "
                    "AND a.deleted_at IS NULL"
                ),
                {"id": update_id, "org_id": organization_id},
            )
        ).mappings().first()
        if old is None:
            return None
        if not changes:
            return dict(old)

        new_quantity = changes.get("quantity", old["quantity"])
        new_unit_id = changes.get("unit_id", old["unit_id"])
        new_narrative = changes.get("narrative", old["narrative"])

        new_id = uuid.uuid4()
        await self._conn.execute(
            text(
                "INSERT INTO progress_updates "
                "(id, activity_id, occurred_at, update_kind, narrative, quantity, unit_id, "
                "supersedes_id, reported_by_user_id, source, correlation_id) "
                "VALUES (:id, :activity_id, :occurred_at, :update_kind, :narrative, :quantity, "
                ":unit_id, :supersedes_id, :reported_by_user_id, :source, :correlation_id)"
            ),
            {
                "id": new_id,
                "activity_id": old["activity_id"],
                "occurred_at": old["occurred_at"],
                "update_kind": old["update_kind"],
                "narrative": new_narrative,
                "quantity": new_quantity,
                "unit_id": new_unit_id,
                "supersedes_id": update_id,
                "reported_by_user_id": corrected_by_user_id,
                "source": source,
                "correlation_id": correlation_id,
            },
        )

        for field, old_value, new_value in (
            ("quantity", old["quantity"], new_quantity),
            ("unit_id", old["unit_id"], new_unit_id),
            ("narrative", old["narrative"], new_narrative),
        ):
            if old_value != new_value:
                await self._record_correction(
                    activity_id=old["activity_id"],
                    field_name=f"progress_update.{field}",
                    old_value=old_value,
                    new_value=new_value,
                    reason=reason,
                    corrected_by_user_id=corrected_by_user_id,
                    correlation_id=correlation_id,
                )

        await self._revise_dpr_if_frozen(
            organization_id=old["organization_id"],
            project_id=old["project_id"],
            site_id=old["site_id"],
            report_date=old["activity_date"],
            reason=reason or "Progress update corrected",
        )

        return {
            "id": new_id,
            "activity_id": old["activity_id"],
            "occurred_at": old["occurred_at"],
            "update_kind": old["update_kind"],
            "narrative": new_narrative,
            "quantity": new_quantity,
            "unit_id": new_unit_id,
            "supersedes_id": update_id,
        }

    async def correct_activity_quantity_row(
        self,
        *,
        organization_id: uuid.UUID,
        quantity_id: uuid.UUID,
        quantity: Any,
        unit_id: uuid.UUID | None,
        reason: str | None,
        corrected_by_user_id: uuid.UUID | None,
        correlation_id: str | None = None,
    ) -> dict[str, Any] | None:
        """WRK-06: correct the quantity an activity was started with
        (``activity_quantities``; "180 sqm plastering", then "that was 150").
        That row has no progress update of its own to supersede, so it is
        changed in place with the old value kept in ``activity_corrections``
        (the audit ADR-D14 describes for header edits), and a frozen DPR gets
        a revision exactly as for a progress update. None when the row does
        not exist, is not this organization's, or its activity is deleted."""
        old = (
            await self._conn.execute(
                text(
                    "SELECT aq.id, aq.activity_id, aq.quantity, aq.unit_id, a.organization_id, "
                    "a.project_id, a.site_id, a.activity_date "
                    "FROM activity_quantities aq JOIN activities a ON a.id = aq.activity_id "
                    "WHERE aq.id = :id AND a.organization_id = :org_id AND a.deleted_at IS NULL"
                ),
                {"id": quantity_id, "org_id": organization_id},
            )
        ).mappings().first()
        if old is None:
            return None
        new_unit_id = unit_id or old["unit_id"]
        await self._conn.execute(
            text("UPDATE activity_quantities SET quantity = :q, unit_id = :u WHERE id = :id"),
            {"q": quantity, "u": new_unit_id, "id": quantity_id},
        )
        for field, old_value, new_value in (
            ("quantity", old["quantity"], quantity),
            ("unit_id", old["unit_id"], new_unit_id),
        ):
            if str(old_value) != str(new_value):
                await self._record_correction(
                    activity_id=old["activity_id"],
                    field_name=f"activity_quantity.{field}",
                    old_value=old_value,
                    new_value=new_value,
                    reason=reason,
                    corrected_by_user_id=corrected_by_user_id,
                    correlation_id=correlation_id,
                )
        await self._revise_dpr_if_frozen(
            organization_id=old["organization_id"],
            project_id=old["project_id"],
            site_id=old["site_id"],
            report_date=old["activity_date"],
            reason=reason or "Activity quantity corrected",
        )
        return {"id": quantity_id, "activity_id": old["activity_id"], "quantity": quantity,
                "unit_id": new_unit_id, "supersedes_id": None}

    async def void_progress_update(
        self,
        *,
        organization_id: uuid.UUID,
        update_id: uuid.UUID,
        reason: str,
        corrected_by_user_id: uuid.UUID | None,
        correlation_id: str | None = None,
    ) -> str | None:
        """Soft-delete a Progress Update (ADR-D15) -- never a hard delete,
        and refused once the day is frozen into an approved DPR (P7).
        Returns None on success, or a short rejection reason string."""
        if not reason or not reason.strip():
            return "reason is required to void a progress update"

        old = (
            await self._conn.execute(
                text(
                    "SELECT pu.activity_id, a.organization_id, a.project_id, a.site_id, "
                    "a.activity_date "
                    "FROM progress_updates pu JOIN activities a ON a.id = pu.activity_id "
                    "WHERE pu.id = :id AND a.organization_id = :org_id AND pu.deleted_at IS NULL"
                ),
                {"id": update_id, "org_id": organization_id},
            )
        ).mappings().first()
        if old is None:
            return "progress update not found"

        if await self._is_frozen(
            organization_id=organization_id,
            project_id=old["project_id"],
            site_id=old["site_id"],
            report_date=old["activity_date"],
        ):
            return "this update is already part of an approved daily report and cannot be undone"

        now = datetime.datetime.now(datetime.UTC)
        res = await self._conn.execute(
            text("UPDATE progress_updates SET deleted_at = :now WHERE id = :id"),
            {"id": update_id, "now": now},
        )
        if res.rowcount == 0:
            return "progress update not found"

        await self._record_correction(
            activity_id=old["activity_id"],
            field_name="progress_update._voided",
            old_value=None,
            new_value=True,
            reason=reason,
            corrected_by_user_id=corrected_by_user_id,
            correlation_id=correlation_id,
        )
        return None

    async def list_corrections(
        self, organization_id: uuid.UUID, activity_id: uuid.UUID
    ) -> list[dict[str, Any]]:
        """The audit trail for one Activity (ADR-D14), newest first --
        every header field correction, progress-update correction, and
        void, in one place so a disputed number can be traced."""
        rows = (
            await self._conn.execute(
                text(
                    "SELECT ac.id, ac.activity_id, ac.field_name, ac.old_value, ac.new_value, "
                    "ac.reason, ac.corrected_by_user_id, ac.correlation_id, ac.created_at "
                    "FROM activity_corrections ac "
                    "JOIN activities a ON a.id = ac.activity_id "
                    "WHERE ac.activity_id = :activity_id AND a.organization_id = :org_id "
                    "ORDER BY ac.created_at DESC"
                ),
                {"activity_id": activity_id, "org_id": organization_id},
            )
        ).mappings().all()
        return [dict(r) for r in rows]

