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

    async def sources(
        self, *, organization_id: uuid.UUID, fact_type: str, fact_id: uuid.UUID
    ) -> dict[str, Any]:
        """Where one item came from (WEB-04's sources panel): the WhatsApp
        message(s) behind it with who sent them, what the AI read and how
        sure it was, its photos, and its draft/confirm/reject history.
        Media come back as object keys; the router signs them. An item typed
        on the dashboard simply has no messages."""
        if fact_type not in _FACT_SOURCES:
            raise FactReviewError(f"unknown fact type {fact_type!r}")
        params = {"org": organization_id, "type": fact_type, "id": fact_id}
        history = (
            await self._conn.execute(
                text(
                    "SELECT fr.state, fr.note, fr.created_at, u.full_name AS actor_name "
                    "FROM fact_reviews fr LEFT JOIN users u ON u.id = fr.actor_user_id "
                    "WHERE fr.organization_id = :org AND fr.fact_type = :type "
                    "AND fr.fact_id = :id ORDER BY fr.created_at, fr.id"
                ),
                params,
            )
        ).mappings().all()
        readings = (
            await self._conn.execute(
                text(
                    "SELECT DISTINCT ON (e.id) e.id, e.correlation_id, e.inbound_message_id, "
                    "e.provider, e.model, e.confidence, e.extracted, e.created_at "
                    "FROM fact_reviews fr JOIN extractions e ON e.id = fr.extraction_id "
                    "WHERE fr.organization_id = :org AND fr.fact_type = :type "
                    "AND fr.fact_id = :id AND e.organization_id = :org"
                ),
                params,
            )
        ).mappings().all()
        message_ids = [r["inbound_message_id"] for r in readings if r["inbound_message_id"]]
        correlation_ids = [r["correlation_id"] for r in readings if r["correlation_id"]]
        messages: list[Any] = []
        if message_ids or correlation_ids:
            messages = (
                await self._conn.execute(
                    text(
                        "SELECT im.id, im.message_type, im.body_text, im.body_text_en, "
                        "im.media_object_key, "
                        "im.received_at, im.sender_wa_id, u.full_name AS sender_name, "
                        # Where it came in: "dashboard" for Tell Mesiri (WEB-36), else WhatsApp.
                        "COALESCE(im.raw_payload::jsonb ->> 'source', 'whatsapp') AS source "
                        "FROM inbound_messages im "
                        "LEFT JOIN users u ON u.organization_id = im.organization_id "
                        "  AND u.whatsapp_number IS NOT NULL "
                        "  AND regexp_replace(u.whatsapp_number, '\\D', '', 'g') "
                        "      = regexp_replace(im.sender_wa_id, '\\D', '', 'g') "
                        "WHERE im.organization_id = :org "
                        "AND (im.id = ANY(:ids) OR im.correlation_id = ANY(:cids)) "
                        "ORDER BY im.received_at, im.id"
                    ),
                    {"org": organization_id, "ids": message_ids, "cids": correlation_ids},
                )
            ).mappings().all()
        photos: list[Any] = []
        if fact_type == fact_review.ACTIVITY:
            photos = (
                await self._conn.execute(
                    text(
                        "SELECT pa.media_object_key, pa.mime_type, "
                        "COALESCE(pa.caption, pa.ai_caption) AS caption, pa.created_at "
                        "FROM progress_attachments pa JOIN activities a ON a.id = pa.parent_id "
                        "WHERE pa.parent_type = 'ACTIVITY' AND pa.parent_id = :id "
                        "AND a.organization_id = :org AND pa.media_object_key IS NOT NULL "
                        "ORDER BY pa.created_at"
                    ),
                    {"org": organization_id, "id": fact_id},
                )
            ).mappings().all()

        def when(value: Any) -> str | None:
            return value.isoformat() if value is not None else None

        return {
            "messages": [
                {
                    "id": str(m["id"]),
                    "type": m["message_type"],
                    "text": m["body_text"],
                    # A voice note's English, from the speech step (WEB-37); None for text.
                    "translated_text": m.get("body_text_en"),
                    "media_object_key": m["media_object_key"],
                    "received_at": when(m["received_at"]),
                    "sender_name": m["sender_name"],
                    "sender_number": m["sender_wa_id"],
                    "source": m.get("source") or "whatsapp",
                }
                for m in messages
            ],
            "readings": [
                {
                    "provider": r["provider"],
                    "model": r["model"],
                    "confidence": r["confidence"],
                    "extracted": r["extracted"] if not isinstance(r["extracted"], str)
                    else json.loads(r["extracted"]),
                    "created_at": when(r["created_at"]),
                }
                for r in readings
            ],
            "photos": [
                {
                    "media_object_key": p["media_object_key"],
                    "mime_type": p["mime_type"],
                    "caption": p["caption"],
                }
                for p in photos
            ],
            "history": [
                {
                    "state": h["state"],
                    "note": h["note"],
                    "at": when(h["created_at"]),
                    "by": h["actor_name"],
                }
                for h in history
            ],
        }

    async def questions(
        self,
        *,
        organization_id: uuid.UUID,
        project_id: uuid.UUID,
        site_id: uuid.UUID,
        since: datetime.datetime,
        until: datetime.datetime,
        workflow_keys: list[str],
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        """Questions asked about one site (or its whole project) in a window,
        with Mesiri's reply (WEB-37's Live report). A message is a question
        when the workflow it started is one of ``workflow_keys``; its
        workflow resolves as the message log does (directly, or through the
        interaction group)."""
        rows = (
            await self._conn.execute(
                text(
                    "SELECT * FROM ("
                    " SELECT im.id, im.message_type, im.body_text, im.body_text_en, "
                    " im.assistant_reply, im.received_at, im.site_id, su.full_name AS sender_name, "
                    " COALESCE(im.raw_payload::jsonb ->> 'source', 'whatsapp') AS source, "
                    " COALESCE(wi.workflow_key, wi_origin.workflow_key) AS workflow_key "
                    " FROM inbound_messages im "
                    # One name per message, even if two people share a number.
                    " LEFT JOIN LATERAL (SELECT u.full_name FROM users u "
                    "   WHERE u.organization_id = im.organization_id "
                    "   AND regexp_replace(u.whatsapp_number, '\\D', '', 'g') "
                    "       = regexp_replace(im.sender_wa_id, '\\D', '', 'g') LIMIT 1) su ON true "
                    " LEFT JOIN workflow_instances wi ON wi.id = im.workflow_instance_id "
                    " LEFT JOIN workflow_instances wi_origin "
                    "   ON wi_origin.correlation_id = im.interaction_group_id "
                    " WHERE im.organization_id = :org "
                    " AND im.received_at >= :since AND im.received_at < :until "
                    " AND (im.site_id = :site OR (im.site_id IS NULL AND im.project_id = :project))"
                    ") q WHERE q.workflow_key = ANY(:keys) "
                    "ORDER BY q.received_at, q.id LIMIT :limit"
                ),
                {
                    "org": organization_id,
                    "project": project_id,
                    "site": site_id,
                    "since": since,
                    "until": until,
                    "keys": workflow_keys,
                    "limit": limit,
                },
            )
        ).mappings().all()
        return [
            {
                "id": str(r["id"]),
                "type": r["message_type"],
                "text": r["body_text"],
                "translated_text": r["body_text_en"],
                "reply": r["assistant_reply"],
                "received_at": r["received_at"].isoformat() if r["received_at"] else None,
                "sender_name": r["sender_name"],
                "source": r["source"] or "whatsapp",
                "workflow_key": r["workflow_key"],
                "whole_project": r["site_id"] is None,
            }
            for r in rows
        ]

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

            from mesiri.domains.materials.router import (
                reverse_material_record,
                reverse_transfer_record,
            )

            try:
                # A transfer's outflow is the reviewable fact: rejecting it
                # takes back both halves, never one (stock at both sites).
                transfer_id = None
                if fact_type == fact_review.MATERIAL_USAGE:
                    transfer_id = (
                        await self._conn.execute(
                            text(
                                "SELECT transfer_id FROM material_usage "
                                "WHERE id = :id AND organization_id = :org"
                            ),
                            {"id": fact_id, "org": organization_id},
                        )
                    ).scalar()
                if transfer_id is not None:
                    await reverse_transfer_record(
                        self._conn,
                        transfer_id=transfer_id,
                        organization_id=organization_id,
                        user_id=actor_user_id,
                        reason_note=reason,
                    )
                    return
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
