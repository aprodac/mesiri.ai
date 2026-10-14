"""Drains and sends #9 Notifications' queued 'pending' rows over WhatsApp.

Invocable manually or via a cron entry -- not a persistent worker, same
convention as backend/src/mesiri/scripts/run_notification_checks.py (which
queues the rows this script sends) and project_timeline_events.py. This is
deliberately a SEPARATE process/script from the backend check, not the same
one: the backend must never talk to Meta's Cloud API directly (architecture
boundary -- only this app holds WhatsApp credentials and the WhatsAppSender
adapter). `drain_and_send()` below is also called directly (same process,
no subprocess) by runtime/automation_runner.py's in-app scheduler, so
automations reuse this exact send/skip logic rather than a second copy.

For each pending row: resolve the recipient's wa_id, check their opt-in /
opt-out (BE-15), quiet hours and
the WhatsApp 24h session window (application/notifications/checks.py, in
the backend package -- pure logic, safe to import from either side), and
either send or skip with a recorded reason. Never sends silently outside
the session window: Meta rejects a free-form send there, and pretending
otherwise would be worse than skipping honestly.

`rule_key`s starting with "automation:" (runtime/automation_runner.py's own
convention) render from the row's own `payload` -- `document_object_key`
when present sends a document (SEND_DPR with a rendered PDF ready),
otherwise `payload["message"]` as plain text. Every other rule_key keeps
using the static `_RULE_KEY_MESSAGES` table.

Outside the session window (WA-12) a row goes out as an approved template
when its payload names one (`payload["template"]`) and that template is
listed in `WHATSAPP_APPROVED_TEMPLATES`; otherwise it is skipped with the
reason saying why (channel/whatsapp/templates.py's `choose_template`).

Recommended VPS crontab entry (ops-managed, not tracked in this repo) --
kept as a manual/backup path now that automation_runner.py drains
automation-sourced rows itself; #9's own stuck-confirmation nudges still
rely on this cron, since nothing else queues or sends those:
    */15 * * * * cd /opt/mesiri/apps/whatsapp-assistant/src && \
        PYTHONPATH=/opt/mesiri/shared/contracts/src:/opt/mesiri/platform/ai/src:/opt/mesiri/backend/src:/opt/mesiri/apps/whatsapp-assistant/src \
        /opt/mesiri/.venv/bin/python -m runtime.send_pending_notifications \
        >> /var/log/mesiri/notification-sender.log 2>&1

Run:  python -m runtime.send_pending_notifications
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from typing import Any

_RULE_KEY_MESSAGES: dict[str, str] = {
    "stuck_confirmation": (
        "⏳ You have a report waiting for your YES/NO reply — "
        "just reply to it to continue, or CANCEL to discard it."
    ),
}

_DOCUMENT_MIME_TYPE = "application/pdf"


def _render(row: dict[str, Any]) -> str:
    rule_key = row["rule_key"]
    payload = row.get("payload") or {}
    # Any row that carries its own message uses it -- BE-16's
    # `project_dpr_send:` rows too, which until WA-12 fell through to the
    # generic line below and sent the DPR PDF under "You have a pending item".
    if payload.get("message"):
        return payload["message"]
    if rule_key.startswith("automation:"):
        return "You have a pending item that needs your attention."
    return _RULE_KEY_MESSAGES.get(
        rule_key, "You have a pending item that needs your attention."
    )


async def _send_one(
    row: dict[str, Any],
    *,
    wa_id: str,
    sender: Any,
    object_storage: Any | None,
) -> bool:
    """Sends the document too when the payload names one and object storage
    is wired -- text is still sent either way (the caption/status line),
    matching how the DPR chat trigger's own document side-channel works
    (runtime/inbound_journey.py): the reply is never JUST a bare document
    with no words around it."""
    text_sent = await sender.send_text(wa_id, _render(row))
    if not text_sent:
        return False

    payload = row.get("payload") or {}
    object_key = payload.get("document_object_key")
    if object_key and object_storage is not None:
        try:
            stored = await object_storage.get_object(object_key)
            await sender.send_document(
                wa_id, stored.data, filename="DPR.pdf", mime_type=_DOCUMENT_MIME_TYPE
            )
        except Exception:  # noqa: BLE001
            # The status text already went out -- a failed document fetch/
            # send degrades to "you got told, but not the file", not a
            # failure of the whole notification.
            import logging

            logging.getLogger("mesiri.notifications").warning(
                "notification.document_send_failed object_key=%s", object_key, exc_info=True
            )
    return True


async def _send_template(
    row: dict[str, Any],
    choice: Any,
    *,
    wa_id: str,
    sender: Any,
    object_storage: Any | None,
) -> bool:
    """WA-12: the out-of-window send. A document-header template cannot go
    without its document (Meta rejects it), so a missing or unreadable
    document fails the send rather than degrading as the in-window path
    does."""
    spec = choice.spec
    header_document = None
    if spec.header == "document":
        object_key = (row.get("payload") or {}).get("document_object_key")
        if not object_key or object_storage is None:
            return False
        try:
            stored = await object_storage.get_object(object_key)
        except Exception:  # noqa: BLE001
            import logging

            logging.getLogger("mesiri.notifications").warning(
                "notification.template_document_failed object_key=%s", object_key, exc_info=True
            )
            return False
        header_document = (stored.data, "DPR.pdf")

    return await sender.send_template(
        wa_id,
        name=spec.name,
        language=spec.language,
        body_params=choice.body_params,
        header_document=header_document,
        mime_type=_DOCUMENT_MIME_TYPE,
    )


async def drain_and_send(
    *,
    db: Any,
    actor_reader: Any,
    sender: Any,
    object_storage: Any | None = None,
    approved_templates: frozenset[str] = frozenset(),
) -> dict[str, int]:
    """The reusable core: drain every 'pending' notification and send or
    skip each with a recorded reason. Shared by this script's own `run()`
    and runtime/automation_runner.py's scheduler tick -- one send/skip
    policy, never two copies drifting apart."""
    from channel.whatsapp.templates import choose_template
    from mesiri.application.dpr.recipients import may_message
    from mesiri.application.notifications.checks import (
        is_quiet_hours,
        is_within_whatsapp_session_window,
    )
    from runtime.notification_query import NotificationSendQueueService

    queue = NotificationSendQueueService(db, actor_reader)
    counts = {"sent": 0, "skipped": 0}

    pending = await queue.list_pending()
    for row in pending:
        notification_id = str(row["id"])
        payload = row.get("payload") or {}
        if row.get("recipient_user_id"):
            wa_id = await queue.resolve_recipient_wa_id(str(row["recipient_user_id"]))
        else:
            # BE-15: an outside contact has no user row; the number is in
            # the payload.
            wa_id = payload.get("to_wa_id") or None
        if wa_id is None:
            await queue.mark_skipped(notification_id=notification_id, reason="no_resolvable_recipient")
            counts["skipped"] += 1
            continue

        # BE-15: an opt-out stops everything; an outside contact also needs
        # an opt-in on record (application/dpr/recipients.py).
        allowed, consent_reason = may_message(
            consent_state=await queue.consent_state(
                organization_id=row.get("organization_id"), wa_id=wa_id
            ),
            requires_opt_in=bool(payload.get("requires_opt_in")),
        )
        if not allowed:
            await queue.mark_skipped(notification_id=notification_id, reason=consent_reason or "no_opt_in")
            counts["skipped"] += 1
            continue

        last_inbound = await queue.last_inbound_at(wa_id)
        now = datetime.now(tz=UTC)
        template_choice = None
        if not is_within_whatsapp_session_window(last_inbound_at=last_inbound, now=now):
            # Outside Meta's free-form window -- a free-form send would be
            # silently rejected. Only an approved template can go (WA-12);
            # with none, skip with the reason rather than pretend.
            template_choice = choose_template(row.get("payload"), approved_templates)
            if template_choice.spec is None:
                await queue.mark_skipped(
                    notification_id=notification_id,
                    reason=template_choice.skip_reason or "outside_whatsapp_session_window_needs_template",
                )
                counts["skipped"] += 1
                continue

        if is_quiet_hours(local_now=now):
            # Left 'pending' on purpose -- not skipped -- so the next drain
            # picks it back up once quiet hours end, rather than losing it.
            continue

        if template_choice is not None:
            sent = await _send_template(
                row, template_choice, wa_id=wa_id, sender=sender, object_storage=object_storage
            )
        else:
            sent = await _send_one(row, wa_id=wa_id, sender=sender, object_storage=object_storage)
        if sent:
            await queue.mark_sent(notification_id=notification_id)
            counts["sent"] += 1
        else:
            await queue.mark_skipped(notification_id=notification_id, reason="send_failed")
            counts["skipped"] += 1

    return counts


async def run() -> dict[str, int]:
    import httpx

    from backend.postgres.actor import PostgresActorReader
    from channel.whatsapp.outbound import WhatsAppSender
    from channel.whatsapp.templates import approved_template_names
    from mesiri.bootstrap.settings import Settings as BackendSettings
    from mesiri.infrastructure.objectstorage import build_object_storage
    from mesiri.infrastructure.postgres.database import PostgresDatabase
    from runtime.dependencies import Settings as WhatsAppSettings

    whatsapp_settings = WhatsAppSettings()  # type: ignore[call-arg]
    backend_settings = BackendSettings()
    db = PostgresDatabase(backend_settings.postgres)
    await db.connect()

    try:
        async with httpx.AsyncClient(timeout=15.0) as http_client:
            sender = WhatsAppSender(
                client=http_client,
                access_token=whatsapp_settings.access_token,
                phone_number_id=whatsapp_settings.phone_number_id,
                api_version=whatsapp_settings.api_version,
                graph_base_url=whatsapp_settings.graph_base_url,
            )
            actor_reader = PostgresActorReader()
            object_storage = build_object_storage(backend_settings)
            counts = await drain_and_send(
                db=db,
                actor_reader=actor_reader,
                sender=sender,
                object_storage=object_storage,
                approved_templates=approved_template_names(whatsapp_settings.approved_templates),
            )
    finally:
        await db.disconnect()

    return counts


def main() -> int:
    counts = asyncio.run(run())
    print(f"notification-sender: sent {counts['sent']}, skipped {counts['skipped']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
