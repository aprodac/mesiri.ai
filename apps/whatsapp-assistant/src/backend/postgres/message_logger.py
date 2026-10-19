"""PostgreSQL implementation of runtime.logging_ports.MessageLogger.

Best-effort: swallows all exceptions and logs them. A logging failure must
never break the inbound pipeline.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

_log = logging.getLogger("mesiri.message_logger")

_BODY_PREVIEW_LEN = 500


def _build_engine():
    import os

    from sqlalchemy.ext.asyncio import create_async_engine

    host = os.environ.get("MESIRI_POSTGRES__HOST", "localhost")
    port = os.environ.get("MESIRI_POSTGRES__PORT", "5432")
    user = os.environ.get("MESIRI_POSTGRES__USER", "mesiri")
    password = os.environ.get("MESIRI_POSTGRES__PASSWORD", "mesiri_local_dev")
    database = os.environ.get("MESIRI_POSTGRES__DATABASE", "mesiri")
    dsn = f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{database}"
    return create_async_engine(dsn, echo=False, pool_pre_ping=True)


class PostgresMessageLogger:
    """Writes inbound_messages rows. Best-effort — never raises into the pipeline."""

    def __init__(self, engine=None) -> None:
        self._engine = engine

    def _get_engine(self):
        if self._engine is None:
            self._engine = _build_engine()
        return self._engine

    async def log_received(
        self,
        *,
        correlation_id: str,
        sender_wa_id: str,
        message_type: str,
        raw_payload: dict[str, Any],
        normalized_message: dict[str, Any] | None,
        body_text: str | None,
        media_object_key: str | None,
        dedup_key: str,
        retry_of_id: str | None = None,
        organization_id: str | None = None,
    ) -> None:
        import json

        from sqlalchemy import text

        try:
            async with self._get_engine().begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO inbound_messages "
                        "(id, correlation_id, sender_wa_id, message_type, raw_payload, "
                        "normalized_message, body_text, media_object_key, dedup_key, "
                        "raw_payload_captured, retry_of_id, organization_id) "
                        "VALUES (:id, :correlation_id, :sender_wa_id, :message_type, "
                        "CAST(:raw_payload AS jsonb), CAST(:normalized_message AS jsonb), "
                        ":body_text, :media_object_key, :dedup_key, "
                        ":raw_payload_captured, :retry_of_id, CAST(:organization_id AS uuid)) "
                        "ON CONFLICT (dedup_key) DO NOTHING"
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "correlation_id": correlation_id,
                        "sender_wa_id": sender_wa_id,
                        "message_type": message_type,
                        "raw_payload": json.dumps(raw_payload),
                        "normalized_message": (
                            json.dumps(normalized_message) if normalized_message else None
                        ),
                        "body_text": body_text,
                        "media_object_key": media_object_key,
                        "dedup_key": dedup_key,
                        "raw_payload_captured": bool(raw_payload),
                        "retry_of_id": retry_of_id,
                        "organization_id": organization_id,
                    },
                )
        except Exception:  # noqa: BLE001
            _log.exception("message_logger.log_received failed correlation_id=%s", correlation_id)

    async def update_context(
        self,
        *,
        correlation_id: str,
        organization_id: str | None = None,
        project_id: str | None = None,
        site_id: str | None = None,
    ) -> None:
        from sqlalchemy import text

        try:
            async with self._get_engine().begin() as conn:
                updates = []
                params = {"correlation_id": correlation_id}
                if organization_id is not None:
                    updates.append("organization_id = CAST(:organization_id AS uuid)")
                    params["organization_id"] = organization_id
                if project_id is not None:
                    updates.append("project_id = CAST(:project_id AS uuid)")
                    params["project_id"] = project_id
                if site_id is not None:
                    updates.append("site_id = CAST(:site_id AS uuid)")
                    params["site_id"] = site_id

                if updates:
                    await conn.execute(
                        text(
                            f"UPDATE inbound_messages SET {', '.join(updates)} "
                            "WHERE correlation_id = :correlation_id"
                        ),
                        params,
                    )
        except Exception:  # noqa: BLE001
            _log.exception("message_logger.update_context failed correlation_id=%s", correlation_id)

    async def link_workflow_instance(
        self, *, correlation_id: str, workflow_instance_id: str
    ) -> None:
        """UPDATE the row's workflow_instance_id -- called whenever this
        message started or resumed a workflow, so the logs viewer can group
        the multi-turn interaction (e.g. voice expense -> confirmation)."""
        from sqlalchemy import text

        try:
            async with self._get_engine().begin() as conn:
                await conn.execute(
                    text(
                        "UPDATE inbound_messages "
                        "SET workflow_instance_id = CAST(:workflow_instance_id AS uuid) "
                        "WHERE correlation_id = :correlation_id"
                    ),
                    {
                        "correlation_id": correlation_id,
                        "workflow_instance_id": workflow_instance_id,
                    },
                )
        except Exception:  # noqa: BLE001
            _log.exception(
                "message_logger.link_workflow_instance failed correlation_id=%s", correlation_id
            )

    async def set_interaction_group(self, *, correlation_id: str, group_id: str) -> None:
        """UPDATE the row's interaction_group_id -- the originating report's
        own correlation_id, stamped on every message that's part of the same
        multi-turn interaction (a gate-clarification tap, or the report
        itself), even before any workflow_instances row exists. See
        list_recent/get_message_detail below for how this resolves to a real
        workflow once one is eventually created."""
        from sqlalchemy import text

        try:
            async with self._get_engine().begin() as conn:
                await conn.execute(
                    text(
                        "UPDATE inbound_messages "
                        "SET interaction_group_id = :group_id "
                        "WHERE correlation_id = :correlation_id"
                    ),
                    {"correlation_id": correlation_id, "group_id": group_id},
                )
        except Exception:  # noqa: BLE001
            _log.exception(
                "message_logger.set_interaction_group failed correlation_id=%s", correlation_id
            )

    async def set_reply_wamid(self, *, correlation_id: str, reply_wamid: str) -> None:
        from sqlalchemy import text

        try:
            async with self._get_engine().begin() as conn:
                await conn.execute(
                    text(
                        "UPDATE inbound_messages "
                        "SET reply_wamid = :reply_wamid "
                        "WHERE correlation_id = :correlation_id"
                    ),
                    {"correlation_id": correlation_id, "reply_wamid": reply_wamid},
                )
        except Exception:  # noqa: BLE001
            _log.exception(
                "message_logger.set_reply_wamid failed correlation_id=%s", correlation_id
            )

    async def mark_completed(self, *, correlation_id: str) -> None:
        from sqlalchemy import text

        try:
            async with self._get_engine().begin() as conn:
                await conn.execute(
                    text(
                        "UPDATE inbound_messages "
                        "SET processing_status = 'completed', processed_at = now() "
                        "WHERE correlation_id = :correlation_id"
                    ),
                    {"correlation_id": correlation_id},
                )
        except Exception:  # noqa: BLE001
            _log.exception("message_logger.mark_completed failed correlation_id=%s", correlation_id)

    async def mark_failed(self, *, correlation_id: str, error_code: str) -> None:
        from sqlalchemy import text

        try:
            async with self._get_engine().begin() as conn:
                await conn.execute(
                    text(
                        "UPDATE inbound_messages "
                        "SET processing_status = 'failed', processed_at = now(), "
                        "error_code = :error_code "
                        "WHERE correlation_id = :correlation_id"
                    ),
                    {"correlation_id": correlation_id, "error_code": error_code},
                )
        except Exception:  # noqa: BLE001
            _log.exception("message_logger.mark_failed failed correlation_id=%s", correlation_id)

    async def list_recent(
        self,
        *,
        wa_id: str | None = None,
        status: str | None = None,
        provider: str | None = None,
        since_received_at: datetime | None = None,
        since_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
        organization_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
        site_id: uuid.UUID | None = None,
    ) -> tuple[list[dict[str, Any]], int | None]:
        """Read path for the control-panel logs viewer.

        Two shapes: with no cursor, `limit`/`offset` history paging (newest
        first) alongside a `total` count. With `since_received_at`
        (+`since_id` as a tiebreaker), only messages strictly after that
        point, oldest first — a proper cursor for live polling that's immune
        to new inserts shifting an OFFSET out from under the caller (this
        mode ignores `offset`/`total` — it's a different, correct UX for
        tailing). `body_preview` is a short hint only; the full body is only
        ever returned by `get_message_detail`. Unlike the write methods
        above, a query failure here is NOT swallowed — the caller (an
        authenticated API endpoint) should see a real error.

        `workflow_instance_id`/`workflow_key`/`workflow_phase` resolve
        through two paths: `im.workflow_instance_id` directly when this
        message itself started or resumed the workflow, or -- via
        `wi_origin` -- by matching `im.interaction_group_id` (the
        originating report's own correlation_id, stamped on every
        material/unit/project gate-clarification tap along the way, see
        inbound_journey.py's `_complete_resume_leg`) against
        `workflow_instances.correlation_id`. This lets an entire multi-turn
        report resolve to one interaction even though most of its messages
        never touch workflow_instance_id directly.
        """
        from sqlalchemy import String, bindparam, text

        where = [
            "(:wa_id IS NULL OR im.sender_wa_id = :wa_id)",
            "(:status IS NULL OR im.processing_status = :status)",
        ]
        params: dict[str, Any] = {"wa_id": wa_id, "status": status, "limit": limit}
        bind_types = [bindparam("wa_id", type_=String), bindparam("status", type_=String)]

        # BE-26: per company / project / site, and per user (the sender is
        # matched to a user of the message's company by WhatsApp number digits).
        for column, value in (
            ("organization_id", organization_id),
            ("project_id", project_id),
            ("site_id", site_id),
        ):
            if value is not None:
                where.append(f"im.{column} = :{column}")
                params[column] = value
        if user_id is not None:
            where.append(
                "EXISTS (SELECT 1 FROM users fu WHERE fu.id = :user_id "
                "AND fu.organization_id = im.organization_id "
                "AND regexp_replace(fu.whatsapp_number, '\\D', '', 'g') "
                "= regexp_replace(im.sender_wa_id, '\\D', '', 'g'))"
            )
            params["user_id"] = user_id

        if provider is not None:
            where.append(
                "EXISTS (SELECT 1 FROM provider_executions pe "
                "WHERE pe.correlation_id = im.correlation_id AND pe.provider = :provider)"
            )
            params["provider"] = provider
            bind_types.append(bindparam("provider", type_=String))

        is_live_cursor = since_received_at is not None
        if is_live_cursor:
            where.append(
                "(im.received_at > :since_received_at "
                "OR (im.received_at = :since_received_at AND im.id > :since_id))"
            )
            params["since_received_at"] = since_received_at
            params["since_id"] = uuid.UUID(since_id) if since_id else uuid.UUID(int=0)
            order_by = "im.received_at ASC, im.id ASC"
        else:
            order_by = "im.received_at DESC, im.id DESC"
            params["offset"] = offset

        query = (
            "SELECT im.id, im.correlation_id, im.sender_wa_id, im.message_type, "
            f"LEFT(COALESCE(im.body_text, ''), {_BODY_PREVIEW_LEN}) AS body_preview, "
            "im.processing_status, im.error_code, im.received_at, im.processed_at, "
            "im.acknowledged_at, im.acknowledged_by, im.raw_payload_captured, im.assistant_reply, "
            "im.project_id, p.name AS project_name, im.site_id, s.name AS site_name, "
            "COALESCE(im.workflow_instance_id, wi_origin.id) AS workflow_instance_id, "
            "COALESCE(wi.workflow_key, wi_origin.workflow_key) AS workflow_key, "
            "COALESCE(wi.phase, wi_origin.phase) AS workflow_phase, "
            # BE-26: whose message, in which company, and how many records it
            # created (domain events carry the message's correlation_id).
            "im.organization_id, o.name AS organization_name, "
            "su.id AS sender_user_id, su.full_name AS sender_name, "
            "(SELECT COUNT(*) FROM outbox_events oe "
            " WHERE oe.correlation_id = im.correlation_id) AS created_count "
            "FROM inbound_messages im "
            "LEFT JOIN projects p ON p.id = im.project_id "
            "LEFT JOIN sites s ON s.id = im.site_id "
            "LEFT JOIN organizations o ON o.id = im.organization_id "
            "LEFT JOIN LATERAL (SELECT u.id, u.full_name FROM users u "
            " WHERE u.organization_id = im.organization_id "
            " AND regexp_replace(u.whatsapp_number, '\\D', '', 'g') "
            " = regexp_replace(im.sender_wa_id, '\\D', '', 'g') LIMIT 1) su ON true "
            "LEFT JOIN workflow_instances wi ON wi.id = im.workflow_instance_id "
            "LEFT JOIN workflow_instances wi_origin ON wi_origin.correlation_id = im.interaction_group_id "
            f"WHERE {' AND '.join(where)} "
            f"ORDER BY {order_by} "
            "LIMIT :limit" + ("" if is_live_cursor else " OFFSET :offset")
        )
        stmt = text(query).bindparams(*bind_types)

        async with self._get_engine().connect() as conn:
            rows = (await conn.execute(stmt, params)).mappings().all()
            total: int | None = None
            if not is_live_cursor:
                count_query = f"SELECT COUNT(*) FROM inbound_messages im WHERE {' AND '.join(where)}"
                count_stmt = text(count_query).bindparams(*bind_types)
                count_params = {k: v for k, v in params.items() if k not in ("limit", "offset")}
                total = (await conn.execute(count_stmt, count_params)).scalar_one()
        return [dict(row) for row in rows], total

    async def list_created(self, correlation_id: str) -> list[dict[str, Any]]:
        """What one message created (BE-26): the domain events written under
        its correlation_id, plus those of the taps/answers that continued it
        (inbound_messages.interaction_group_id), oldest first. Read-only; the
        events table is written by each domain's own repository."""
        from sqlalchemy import text

        async with self._get_engine().connect() as conn:
            rows = (
                (
                    await conn.execute(
                        text(
                            "SELECT oe.event_type, oe.aggregate_type, oe.aggregate_id, "
                            "oe.correlation_id, oe.created_at "
                            "FROM outbox_events oe "
                            "WHERE oe.correlation_id = :cid "
                            "OR oe.correlation_id IN (SELECT im.correlation_id FROM inbound_messages im "
                            " WHERE im.interaction_group_id = :cid) "
                            "ORDER BY oe.created_at, oe.id LIMIT 200"
                        ),
                        {"cid": correlation_id},
                    )
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]

    async def list_for_review(self, *, since: datetime, limit: int) -> list[dict[str, Any]]:
        """Read path for the assistant review export (admin/review_router.py).

        Every message received after `since`, oldest first, with the full
        body and reply -- the reviewer judges whole conversations, so a
        preview is not enough. Callers MUST gate this behind platform-admin
        auth and anonymise before returning it (admin/review_export.py);
        `sender_wa_id`/`organization_id` come back raw here. Workflow
        resolution is the same two-path join as `list_recent`. A query
        failure is NOT swallowed.
        """
        from sqlalchemy import text

        async with self._get_engine().connect() as conn:
            rows = (
                (
                    await conn.execute(
                        text(
                            "SELECT im.correlation_id, im.sender_wa_id, im.organization_id, "
                            "im.message_type, im.body_text, im.assistant_reply, "
                            "im.processing_status, im.error_code, im.received_at, im.processed_at, "
                            "COALESCE(wi.workflow_key, wi_origin.workflow_key) AS workflow_key, "
                            "COALESCE(wi.phase, wi_origin.phase) AS workflow_phase "
                            "FROM inbound_messages im "
                            "LEFT JOIN workflow_instances wi ON wi.id = im.workflow_instance_id "
                            "LEFT JOIN workflow_instances wi_origin "
                            "ON wi_origin.correlation_id = im.interaction_group_id "
                            "WHERE im.received_at > :since "
                            "ORDER BY im.received_at ASC, im.id ASC "
                            "LIMIT :limit"
                        ),
                        {"since": since, "limit": limit},
                    )
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]

    async def get_message_detail(self, message_id: str) -> dict[str, Any] | None:
        """Full record for the log detail view — the only place full
        `body_text` and `raw_payload` are ever returned."""
        from sqlalchemy import text

        async with self._get_engine().connect() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            "SELECT im.id, im.correlation_id, im.sender_wa_id, im.message_type, "
                            "im.body_text, im.raw_payload, im.normalized_message, im.media_object_key, "
                            "im.processing_status, im.error_code, im.received_at, im.processed_at, "
                            "im.raw_payload_captured, im.acknowledged_at, im.acknowledged_by, im.retry_of_id, im.assistant_reply, "
                            "im.project_id, p.name AS project_name, im.site_id, s.name AS site_name, "
                            "COALESCE(im.workflow_instance_id, wi_origin.id) AS workflow_instance_id, "
                            "COALESCE(wi.workflow_key, wi_origin.workflow_key) AS workflow_key, "
                            "COALESCE(wi.phase, wi_origin.phase) AS workflow_phase "
                            "FROM inbound_messages im "
                            "LEFT JOIN projects p ON p.id = im.project_id "
                            "LEFT JOIN sites s ON s.id = im.site_id "
                            "LEFT JOIN workflow_instances wi ON wi.id = im.workflow_instance_id "
                            "LEFT JOIN workflow_instances wi_origin ON wi_origin.correlation_id = im.interaction_group_id "
                            "WHERE im.id = :id"
                        ),
                        {"id": uuid.UUID(message_id)},
                    )
                )
                .mappings()
                .first()
            )
        return dict(row) if row is not None else None

    async def acknowledge(self, *, message_id: str, acknowledged_by: str) -> bool:
        """Mark a (typically failed) message as reviewed. Purely a triage
        marker — does not touch processing_status or re-run anything."""
        from sqlalchemy import text

        async with self._get_engine().begin() as conn:
            result = await conn.execute(
                text(
                    "UPDATE inbound_messages "
                    "SET acknowledged_at = now(), acknowledged_by = :acknowledged_by "
                    "WHERE id = :id"
                ),
                {"id": uuid.UUID(message_id), "acknowledged_by": acknowledged_by},
            )
        return result.rowcount > 0

    async def log_reply(self, *, correlation_id: str, reply: str) -> None:
        """UPDATE the row to add the assistant_reply."""
        from sqlalchemy import text

        try:
            async with self._get_engine().begin() as conn:
                await conn.execute(
                    text(
                        "UPDATE inbound_messages "
                        "SET assistant_reply = :reply "
                        "WHERE correlation_id = :correlation_id"
                    ),
                    {"correlation_id": correlation_id, "reply": reply},
                )
        except Exception:  # noqa: BLE001
            _log.exception("message_logger.log_reply failed correlation_id=%s", correlation_id)

    async def get_wall_time_summary(self, since: datetime) -> list[dict[str, Any]]:
        """Read path for the control-panel Performance page's per-modality
        wall-clock summary (received_at -> processed_at), worst-avg first.

        This is a real end-to-end number (unlike any single stage), and it's
        also the one most likely to be inflated by something outside the
        pipeline's own control -- e.g. a held image's wall time includes
        however long the sender took to answer "what is this photo for?"
        (see the image-purpose picker), not just processing. Read alongside
        get_stage_summary, not instead of it.
        """
        from sqlalchemy import text

        async with self._get_engine().connect() as conn:
            rows = (
                (
                    await conn.execute(
                        text(
                            "SELECT message_type, "
                            "count(*) AS n, "
                            "avg(EXTRACT(EPOCH FROM (processed_at - received_at)) * 1000) AS avg_ms, "
                            "percentile_cont(0.5) WITHIN GROUP ("
                            "  ORDER BY EXTRACT(EPOCH FROM (processed_at - received_at)) * 1000"
                            ") AS p50_ms, "
                            "percentile_cont(0.95) WITHIN GROUP ("
                            "  ORDER BY EXTRACT(EPOCH FROM (processed_at - received_at)) * 1000"
                            ") AS p95_ms, "
                            "max(EXTRACT(EPOCH FROM (processed_at - received_at)) * 1000) AS max_ms "
                            "FROM inbound_messages "
                            "WHERE received_at > :since AND processed_at IS NOT NULL "
                            "GROUP BY message_type "
                            "ORDER BY avg_ms DESC NULLS LAST"
                        ),
                        {"since": since},
                    )
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]

    async def get_worst_offenders(self, since: datetime, limit: int) -> list[dict[str, Any]]:
        """Read path for the control-panel Performance page's slowest-message
        list -- the entry point for drilling into one correlation_id's full
        trace via the existing per-message endpoints."""
        from sqlalchemy import text

        async with self._get_engine().connect() as conn:
            rows = (
                (
                    await conn.execute(
                        text(
                            "SELECT correlation_id, message_type, received_at, processed_at, "
                            "EXTRACT(EPOCH FROM (processed_at - received_at)) * 1000 AS wall_ms "
                            "FROM inbound_messages "
                            "WHERE received_at > :since AND processed_at IS NOT NULL "
                            "ORDER BY wall_ms DESC "
                            "LIMIT :limit"
                        ),
                        {"since": since, "limit": limit},
                    )
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]

    async def update_body_text(self, *, correlation_id: str, body_text: str) -> None:
        from sqlalchemy import text

        try:
            async with self._get_engine().begin() as conn:
                await conn.execute(
                    text(
                        "UPDATE inbound_messages SET body_text = :body_text "
                        "WHERE correlation_id = :correlation_id"
                    ),
                    {"correlation_id": correlation_id, "body_text": body_text},
                )
        except Exception:  # noqa: BLE001
            _log.exception(
                "message_logger.update_body_text failed correlation_id=%s", correlation_id
            )
