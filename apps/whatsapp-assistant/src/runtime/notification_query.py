"""Notification send-queue service (#9 Notifications, wiring layer only).

Backend/mesiri.scripts.run_notification_checks finds candidates and queues
them (organization-scoped, at-most-once). This service is the OTHER half:
draining 'pending' rows and resolving what WhatsAppSender needs to actually
send one -- the backend must never talk to Meta's Cloud API directly
(architecture boundary), so the send queue crosses into apps/whatsapp-
assistant/ here, the same way every other backend-computed, WhatsApp-sent
thing in this codebase does.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.ports import ActorReader
    from mesiri.infrastructure.postgres.database import PostgresDatabase

# BE-38: where quiet hours are judged when neither the project nor the
# company has a timezone of its own. V1 is India-only.
DEFAULT_NOTIFICATION_TIMEZONE = "Asia/Kolkata"


def pick_notification_timezone(*, project_timezone: str | None, org_timezone: str | None) -> str:
    """The project's reporting timezone, else the company's, else
    DEFAULT_NOTIFICATION_TIMEZONE. Both columns are NOT NULL with a
    server default of 'UTC' (migrations 0260, 0280), so a stored 'UTC'
    almost always means "never set" and falls through rather than wins."""
    for name in (project_timezone, org_timezone):
        if name and name.strip() and name.strip().upper() != "UTC":
            return name.strip()
    return DEFAULT_NOTIFICATION_TIMEZONE


class NotificationSendQueueService:
    def __init__(self, db: PostgresDatabase, actor_reader: ActorReader) -> None:
        self._db = db
        self._actor_reader = actor_reader

    async def list_pending(self) -> list[dict[str, Any]]:
        from mesiri.infrastructure.postgres.repositories.notifications import (
            PostgresNotificationRepository,
        )

        async with self._db.transaction() as conn:
            repo = PostgresNotificationRepository(conn)
            return await repo.list_pending()

    async def resolve_recipient_wa_id(self, recipient_user_id: str | None) -> str | None:
        """None whenever there's genuinely no one to notify -- a
        notification with no resolvable recipient is skipped (see
        interactions... no, see the sender script's mark_skipped call),
        never sent to nobody and never silently dropped either."""
        if recipient_user_id is None:
            return None
        return await self._actor_reader.resolve_whatsapp_id_by_user_id(recipient_user_id)

    async def consent_state(self, *, organization_id: Any, wa_id: str) -> str | None:
        """The latest WhatsApp opt-in/opt-out recorded for this number in
        this company (BE-15, whatsapp_opt_ins), or None when there is none."""
        if organization_id is None:
            return None
        from mesiri.infrastructure.postgres.repositories.report_recipients import (
            PostgresReportRecipientRepository,
        )

        phone = "".join(ch for ch in str(wa_id) if ch.isdigit())
        async with self._db.transaction() as conn:
            return await PostgresReportRecipientRepository(conn).latest_consent_state(
                organization_id=organization_id, phone=phone
            )

    async def timezone_for(self, *, organization_id: Any, project_id: Any) -> str:
        """BE-38: the timezone a notification's quiet hours are judged in
        (see pick_notification_timezone)."""
        if organization_id is None:
            return DEFAULT_NOTIFICATION_TIMEZONE
        from sqlalchemy import text

        async with self._db.transaction() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            "SELECT o.timezone AS org_timezone, "
                            "p.reporting_timezone AS project_timezone "
                            "FROM organizations o "
                            "LEFT JOIN projects p ON p.id = :project_id "
                            "AND p.organization_id = o.id "
                            "WHERE o.id = :organization_id"
                        ),
                        {"organization_id": organization_id, "project_id": project_id},
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            return DEFAULT_NOTIFICATION_TIMEZONE
        return pick_notification_timezone(
            project_timezone=row["project_timezone"], org_timezone=row["org_timezone"]
        )

    async def last_inbound_at(self, wa_id: str):
        """The recipient's most recent inbound message time, for the
        WhatsApp 24h session-window decision (application/notifications/
        checks.py's is_within_whatsapp_session_window). Reuses
        MessageLogger.list_recent rather than adding new SQL -- it already
        supports filtering by wa_id and ordering newest-first."""
        from backend.postgres.message_logger import PostgresMessageLogger

        logger = PostgresMessageLogger()
        rows, _total = await logger.list_recent(wa_id=wa_id, limit=1, offset=0)
        if not rows:
            return None
        return rows[0].get("received_at")

    async def mark_sent(self, *, notification_id: str) -> None:
        import uuid

        from mesiri.infrastructure.postgres.repositories.notifications import (
            PostgresNotificationRepository,
        )

        async with self._db.transaction() as conn:
            repo = PostgresNotificationRepository(conn)
            await repo.mark_sent(notification_id=uuid.UUID(notification_id))

    async def mark_skipped(self, *, notification_id: str, reason: str) -> None:
        import uuid

        from mesiri.infrastructure.postgres.repositories.notifications import (
            PostgresNotificationRepository,
        )

        async with self._db.transaction() as conn:
            repo = PostgresNotificationRepository(conn)
            await repo.mark_skipped(notification_id=uuid.UUID(notification_id), reason=reason)
