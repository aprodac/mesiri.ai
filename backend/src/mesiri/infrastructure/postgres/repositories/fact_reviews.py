"""PostgreSQL side of save-first / confirm-later (BE-09, migration 0470).

Writes `extractions` (what the AI read) and the append-only `fact_reviews`
log, reads a fact's review state, and confirms or rejects drafts. Rejecting
never writes another module's table directly (P3/P12): it calls that
module's own undo -- `void_activity`, `cancel_issue`, `void_attendance_report`,
`reverse_material_record` -- and then records why.

`created_at` is written with clock_timestamp(), not the column default
now(): a draft and its confirmation can land in the same transaction, and
now() would give both the same time and make "latest row" ambiguous.
"""

from __future__ import annotations

import datetime
import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.application.dpr import fact_review
from mesiri.application.dpr.fact_review import FactReviewError

# Where each fact lives, and the date column that puts it on a site's day.
_FACT_SOURCES: dict[str, tuple[str, str]] = {
    fact_review.ACTIVITY: ("activities", "activity_date"),
    fact_review.SITE_ISSUE: ("site_issues", "occurred_at::date"),
    fact_review.LABOUR_REPORT: ("labour_attendance_reports", "occurred_date"),
    fact_review.MATERIAL_RECEIPT: ("material_receipts", "occurred_date"),
    fact_review.MATERIAL_USAGE: ("material_usage", "occurred_date"),
}


class PostgresFactReviewRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------

    async def record_extraction(
        self,
        *,
        organization_id: uuid.UUID,
        extracted: dict[str, Any],
        correlation_id: str | None = None,
        inbound_message_id: uuid.UUID | None = None,
        provider_execution_id: uuid.UUID | None = None,
        provider: str | None = None,
        model: str | None = None,
        confidence: str | None = None,
    ) -> uuid.UUID:
        """What the AI read from one message. Returns the extraction id, to
        pass to `mark_draft` for each fact saved from it."""
        extraction_id = uuid.uuid4()
        await self._conn.execute(
            text(
                """
                INSERT INTO extractions (
                    id, organization_id, correlation_id, inbound_message_id,
                    provider_execution_id, provider, model, extracted, confidence
                ) VALUES (
                    :id, :org_id, :correlation_id, :inbound_message_id,
                    :provider_execution_id, :provider, :model, CAST(:extracted AS JSONB), :confidence
                )
                """
            ),
            {
                "id": extraction_id,
                "org_id": organization_id,
                "correlation_id": correlation_id,
                "inbound_message_id": inbound_message_id,
                "provider_execution_id": provider_execution_id,
                "provider": provider,
                "model": model,
                "extracted": json.dumps(extracted, default=str),
                "confidence": confidence,
            },
        )
        return extraction_id

    async def mark_draft(
        self,
        *,
        organization_id: uuid.UUID,
        fact_type: str,
        fact_id: uuid.UUID,
        extraction_id: uuid.UUID | None = None,
        actor_user_id: uuid.UUID | None = None,
    ) -> None:
        """Mark a just-saved fact as a draft awaiting the engineer (WA-01
        calls this right after saving)."""
        located = await self._locate(organization_id, fact_type, fact_id)
        await self._append(
            organization_id=organization_id,
            fact_type=fact_type,
            fact_id=fact_id,
            located=located,
            state=fact_review.DRAFT,
            extraction_id=extraction_id,
            actor_user_id=actor_user_id,
            note=None,
        )

    async def confirm(
        self,
        *,
        organization_id: uuid.UUID,
        fact_type: str,
        fact_id: uuid.UUID,
        actor_user_id: uuid.UUID | None,
    ) -> bool:
        """Confirm a draft. False when it was already confirmed."""
        located = await self._locate(organization_id, fact_type, fact_id)
        current = (await self.states_for(fact_type, [fact_id]))[fact_id]
        if not fact_review.check_confirm(current):
            return False
        await self._append(
            organization_id=organization_id,
            fact_type=fact_type,
            fact_id=fact_id,
            located=located,
            state=fact_review.CONFIRMED,
            extraction_id=None,
            actor_user_id=actor_user_id,
            note=None,
        )
        return True

    async def reject(
        self,
        *,
        organization_id: uuid.UUID,
        fact_type: str,
        fact_id: uuid.UUID,
        actor_user_id: uuid.UUID | None,
        reason: str,
    ) -> None:
        """Reject a draft: withdraw it through its module's own undo, then
        record the rejection. Refused for a confirmed day (P7)."""
        if not reason or not reason.strip():
            raise FactReviewError("a reason is required to reject an item")
        reason = reason.strip()
        located = await self._locate(organization_id, fact_type, fact_id)
        fact_review.check_reject((await self.states_for(fact_type, [fact_id]))[fact_id])
        # BE-13: a late entry was never in the confirmed version, so
        # withdrawing it can't change what was confirmed.
        from mesiri.application.dpr.late_entries import is_recorded_late

        if not await is_recorded_late(self._conn, fact_type=fact_type, fact_id=fact_id):
            await self._refuse_if_day_frozen(organization_id, located)

        await self._undo(organization_id, fact_type, fact_id, actor_user_id, reason)
        await self._append(
            organization_id=organization_id,
            fact_type=fact_type,
            fact_id=fact_id,
            located=located,
            state=fact_review.REJECTED,
            extraction_id=None,
            actor_user_id=actor_user_id,
            note=reason,
        )

    async def confirm_drafts_for_day(
        self,
        *,
        organization_id: uuid.UUID,
        site_id: uuid.UUID,
        report_date: datetime.date,
        actor_user_id: uuid.UUID | None,
    ) -> int:
        """Confirm every draft still on a site's day -- what confirming the
        day does (approved 13 Oct: the engineer has just looked at them).
        Returns how many were confirmed."""
        rows = (
            await self._conn.execute(
                text(
                    """
                    SELECT fact_type, fact_id, project_id, site_id, fact_date FROM (
                        SELECT DISTINCT ON (fact_type, fact_id)
                               fact_type, fact_id, project_id, site_id, fact_date, state
                        FROM fact_reviews
                        WHERE organization_id = :org_id AND site_id = :site_id
                          AND fact_date = :report_date
                        ORDER BY fact_type, fact_id, created_at DESC
                    ) latest
                    WHERE state = 'draft'
                    """
                ),
                {"org_id": organization_id, "site_id": site_id, "report_date": report_date},
            )
        ).mappings().all()
        for row in rows:
            await self._append(
                organization_id=organization_id,
                fact_type=row["fact_type"],
                fact_id=row["fact_id"],
                located=dict(row),
                state=fact_review.CONFIRMED,
                extraction_id=None,
                actor_user_id=actor_user_id,
                note="confirmed with the day",
            )
        return len(rows)

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    async def states_for(self, fact_type: str, fact_ids: list[Any]) -> dict[Any, str]:
        """Review state of each fact; a fact with no row is confirmed."""
        if fact_type not in fact_review.FACT_TYPES:
            raise FactReviewError(f"unknown fact type: {fact_type}")
        states: dict[Any, str] = {fact_id: fact_review.CONFIRMED for fact_id in fact_ids}
        if not fact_ids:
            return states
        rows = (
            await self._conn.execute(
                text(
                    """
                    SELECT DISTINCT ON (fact_id) fact_id, state
                    FROM fact_reviews
                    WHERE fact_type = :fact_type AND fact_id = ANY(:fact_ids)
                    ORDER BY fact_id, created_at DESC
                    """
                ),
                {"fact_type": fact_type, "fact_ids": list(fact_ids)},
            )
        ).mappings().all()
        for row in rows:
            key = row["fact_id"]
            # Callers may pass ids as strings or UUIDs; answer in their form.
            match = next((f for f in fact_ids if str(f) == str(key)), key)
            states[match] = fact_review.state_of(row["state"])
        return states

    async def draft_counts_by_site(
        self, *, organization_id: uuid.UUID, report_date: datetime.date
    ) -> dict[Any, int]:
        """Drafts still waiting on each site's day."""
        rows = (
            await self._conn.execute(
                text(
                    """
                    SELECT site_id, count(*) AS drafts FROM (
                        SELECT DISTINCT ON (fact_type, fact_id) site_id, state
                        FROM fact_reviews
                        WHERE organization_id = :org_id AND fact_date = :report_date
                        ORDER BY fact_type, fact_id, created_at DESC
                    ) latest
                    WHERE state = 'draft'
                    GROUP BY site_id
                    """
                ),
                {"org_id": organization_id, "report_date": report_date},
            )
        ).mappings().all()
        return {row["site_id"]: int(row["drafts"]) for row in rows}

    async def locate(
        self, organization_id: uuid.UUID, fact_type: str, fact_id: uuid.UUID
    ) -> dict[str, Any]:
        """project_id / site_id / fact_date of a fact (FactReviewError if unknown)."""
        return await self._locate(organization_id, fact_type, fact_id)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _locate(
        self, organization_id: uuid.UUID, fact_type: str, fact_id: uuid.UUID
    ) -> dict[str, Any]:
        source = _FACT_SOURCES.get(fact_type)
        if source is None:
            raise FactReviewError(f"unknown fact type: {fact_type}")
        table, date_expr = source
        row = (
            await self._conn.execute(
                text(
                    f"SELECT project_id, site_id, {date_expr} AS fact_date FROM {table} "
                    "WHERE organization_id = :org_id AND id = :id"
                ),
                {"org_id": organization_id, "id": fact_id},
            )
        ).mappings().first()
        if row is None:
            raise FactReviewError("that item was not found")
        return dict(row)

    async def _append(
        self,
        *,
        organization_id: uuid.UUID,
        fact_type: str,
        fact_id: Any,
        located: dict[str, Any],
        state: str,
        extraction_id: uuid.UUID | None,
        actor_user_id: uuid.UUID | None,
        note: str | None,
    ) -> None:
        await self._conn.execute(
            text(
                """
                INSERT INTO fact_reviews (
                    id, organization_id, fact_type, fact_id, project_id, site_id, fact_date,
                    state, extraction_id, actor_user_id, note, created_at
                ) VALUES (
                    :id, :org_id, :fact_type, :fact_id, :project_id, :site_id, :fact_date,
                    :state, :extraction_id, (SELECT id FROM users WHERE id = :actor_user_id),
                    :note, clock_timestamp()
                )
                """
            ),
            {
                "id": uuid.uuid4(),
                "org_id": organization_id,
                "fact_type": fact_type,
                "fact_id": fact_id,
                "project_id": located.get("project_id"),
                "site_id": located.get("site_id"),
                "fact_date": located.get("fact_date"),
                "state": state,
                "extraction_id": extraction_id,
                "actor_user_id": actor_user_id,
                "note": note,
            },
        )

    async def _refuse_if_day_frozen(self, organization_id: uuid.UUID, located: dict[str, Any]) -> None:
        if located.get("site_id") is None or located.get("fact_date") is None:
            return
        from mesiri.application.dpr import site_day
        from mesiri.infrastructure.postgres.repositories.dpr import PostgresDprRepository

        day = await PostgresDprRepository(self._conn).find_site_report(
            organization_id=organization_id,
            project_id=located["project_id"],
            site_id=located["site_id"],
            report_date=located["fact_date"],
        )
        if day is not None and day["status"] in site_day.FROZEN:
            raise FactReviewError("this day's DPR is already confirmed; revise it instead")

    async def _undo(
        self,
        organization_id: uuid.UUID,
        fact_type: str,
        fact_id: uuid.UUID,
        actor_user_id: uuid.UUID | None,
        reason: str,
    ) -> None:
        """The owning module's own withdrawal. Each returns or raises its own
        reason when it refuses; that reason is passed on unchanged."""
        if fact_type == fact_review.ACTIVITY:
            from mesiri.infrastructure.postgres.repositories.progress import (
                PostgresProgressReadRepository,
            )

            refusal = await PostgresProgressReadRepository(self._conn).void_activity(
                organization_id=organization_id,
                activity_id=fact_id,
                reason=reason,
                corrected_by_user_id=actor_user_id,
            )
            if refusal:
                raise FactReviewError(refusal)
        elif fact_type == fact_review.SITE_ISSUE:
            from mesiri.infrastructure.postgres.repositories.progress import (
                PostgresProgressReadRepository,
            )

            if not await PostgresProgressReadRepository(self._conn).cancel_issue(
                organization_id, fact_id, reason
            ):
                raise FactReviewError("that issue is no longer open")
        elif fact_type == fact_review.LABOUR_REPORT:
            from mesiri.infrastructure.postgres.repositories.workforce import (
                PostgresWorkforceReadRepository,
            )

            refusal = await PostgresWorkforceReadRepository(self._conn).void_attendance_report(
                organization_id=organization_id,
                report_id=fact_id,
                reason=reason,
                voided_by_user_id=actor_user_id,
            )
            if refusal:
                raise FactReviewError(refusal)
        else:
            from fastapi import HTTPException

            from mesiri.domains.materials.router import reverse_material_record

            try:
                await reverse_material_record(
                    self._conn,
                    kind="receipt" if fact_type == fact_review.MATERIAL_RECEIPT else "usage",
                    record_id=fact_id,
                    organization_id=organization_id,
                    user_id=actor_user_id,
                    reason_note=reason,
                )
            except HTTPException as exc:
                raise FactReviewError(str(exc.detail)) from exc
