"""PostgreSQL repository for notifications (#9 Notifications).

The only file permitted to hold SQL for the notifications table. Two kinds
of method: FINDERS (one per rule_key, returning candidates to notify about)
and the generic QUEUE operations (claim/list/mark) every rule_key shares.

Scope, stated plainly: only ONE finder is implemented in this pass --
find_stuck_confirmations. It is the one check where the recipient is
unambiguous: workflow_instances already carries the user_id whose own
confirmation is stuck, no separate "who manages this site" lookup needed.
The other three checks named in the original brief (missing_dpr,
no_updates_today, unresolved_issue) need exactly that lookup -- this
codebase has no defined concept yet of who is responsible for a site
(project membership exists, but "the person to nudge about site X" is a
product decision, not a query this repository should guess at). Adding
those finders is a mechanical follow-up once that's decided; the queue
mechanics below (claim/list/mark) are already generic enough to support
them without changes.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection

STUCK_CONFIRMATION_RULE_KEY = "stuck_confirmation"


class PostgresNotificationRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn

    async def find_stuck_confirmations(
        self, *, organization_id: uuid.UUID, older_than: timedelta
    ) -> list[dict[str, Any]]:
        """workflow_instances rows still AWAITING_CONFIRMATION after
        ``older_than`` -- the user was asked to confirm something and never
        replied. Each row's own user_id IS the recipient; no separate
        lookup needed (see module docstring)."""
        from sqlalchemy import text

        cutoff = datetime.now(tz=None) - older_than
        rows = (
            (
                await self.conn.execute(
                    text(
                        "SELECT id, user_id, workflow_key, updated_at "
                        "FROM workflow_instances "
                        "WHERE organization_id = :organization_id "
                        "AND phase = 'awaiting_confirmation' "
                        "AND updated_at < :cutoff"
                    ),
                    {"organization_id": organization_id, "cutoff": cutoff},
                )
            )
            .mappings()
            .all()
        )
        return [dict(r) for r in rows]

    async def claim(
        self,
        *,
        organization_id: uuid.UUID,
        rule_key: str,
        subject_id: str,
        occurred_on: date,
        recipient_user_id: uuid.UUID | None,
        project_id: uuid.UUID | None = None,
        site_id: uuid.UUID | None = None,
        payload: dict[str, Any] | None = None,
    ) -> uuid.UUID | None:
        """Claim the (organization_id, rule_key, subject_id, occurred_on)
        slot. Returns the new notification id, or None if it was already
        claimed today -- the UNIQUE constraint (migration 0453) is the real
        guarantee; ON CONFLICT DO NOTHING makes a duplicate claim attempt a
        harmless no-op instead of an error, so a scheduled check that runs
        twice in one day (overlapping cron) never queues a duplicate."""
        import json

        from sqlalchemy import text

        notification_id = uuid.uuid4()
        result = await self.conn.execute(
            text(
                "INSERT INTO notifications "
                "(id, organization_id, project_id, site_id, rule_key, subject_id, "
                "occurred_on, recipient_user_id, payload) "
                "VALUES (:id, :organization_id, :project_id, :site_id, :rule_key, "
                ":subject_id, :occurred_on, :recipient_user_id, CAST(:payload AS jsonb)) "
                "ON CONFLICT ON CONSTRAINT uq_notifications_dedup DO NOTHING"
            ),
            {
                "id": notification_id,
                "organization_id": organization_id,
                "project_id": project_id,
                "site_id": site_id,
                "rule_key": rule_key,
                "subject_id": subject_id,
                "occurred_on": occurred_on,
                "recipient_user_id": recipient_user_id,
                "payload": json.dumps(payload or {}),
            },
        )
        return notification_id if result.rowcount > 0 else None

    async def list_pending(
        self, *, organization_id: uuid.UUID | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Every 'pending' notification, oldest first -- the WhatsApp-side
        sender drains this (see runtime/notification_query.py), applying
        quiet-hours/session-window decisions itself (application/
        notifications/checks.py) before actually sending."""
        from sqlalchemy import text

        where = ["status = 'pending'"]
        params: dict[str, Any] = {"limit": limit}
        if organization_id is not None:
            where.append("organization_id = :organization_id")
            params["organization_id"] = organization_id

        rows = (
            (
                await self.conn.execute(
                    text(
                        "SELECT id, organization_id, project_id, site_id, rule_key, "
                        "subject_id, recipient_user_id, payload, created_at "
                        f"FROM notifications WHERE {' AND '.join(where)} "
                        "ORDER BY created_at ASC "
                        "LIMIT :limit"
                    ),
                    params,
                )
            )
            .mappings()
            .all()
        )
        return [dict(r) for r in rows]

    async def mark_sent(self, *, notification_id: uuid.UUID) -> None:
        from sqlalchemy import text

        await self.conn.execute(
            text(
                "UPDATE notifications SET status = 'sent', sent_at = now() WHERE id = :id"
            ),
            {"id": notification_id},
        )

    async def list_waiting_window(self, *, limit: int = 500) -> list[dict[str, Any]]:
        """SA-37: rows held for the recipient's next message (outside the 24-hour window, no template), oldest
        first. Kept out of 'pending' so they never crowd the pending queue the sender reads."""
        from sqlalchemy import text

        rows = (
            await self.conn.execute(
                text(
                    "SELECT id, organization_id, project_id, site_id, rule_key, subject_id, recipient_user_id, "
                    "payload, created_at FROM notifications WHERE status = 'waiting_window' "
                    "ORDER BY created_at ASC LIMIT :limit"
                ),
                {"limit": limit},
            )
        ).mappings().all()
        return [dict(r) for r in rows]

    async def set_waiting(self, *, notification_id: uuid.UUID, waiting: bool, payload: dict | None = None) -> None:
        """SA-37: hold a row for the recipient's next message (waiting=True), or hand it back to the sender."""
        import json

        from sqlalchemy import text

        await self.conn.execute(
            text(
                "UPDATE notifications SET status = :status, "
                "payload = COALESCE(CAST(:payload AS jsonb), payload) WHERE id = :id"
            ),
            {"status": "waiting_window" if waiting else "pending", "id": notification_id,
             "payload": json.dumps(payload) if payload is not None else None},
        )

    async def mark_skipped(self, *, notification_id: uuid.UUID, reason: str) -> None:
        """Recorded, never silently dropped -- e.g. outside the WhatsApp
        session window with no approved template, or no recipient could be
        resolved. skip_reason makes every non-send explainable later."""
        from sqlalchemy import text

        await self.conn.execute(
            text(
                "UPDATE notifications SET status = 'skipped', skip_reason = :reason "
                "WHERE id = :id"
            ),
            {"id": notification_id, "reason": reason},
        )
