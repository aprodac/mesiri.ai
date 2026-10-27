"""One reminder, before the report time, for a card nobody tapped (request 124).

A worker's message is held as a draft until they tap Save, so a site whose
workers forget the tap would report empty. Once per draft, in the half hour
before the project's reporting cutoff (and any time after it until the send
deadline, for a card made later), the sender gets "You have 1 card not saved:
tap Save or Cancel." with the card and its two buttons -- the same taps as the
card itself. A card that would expire before that window is reminded an hour
before it expires, in the daytime. ``reminded_at`` makes it one message, never
a nag.

Runs inside automation_runner.py's tick, like site_day_review.py: one
`notifications` row per draft (its UNIQUE key makes it go once), delivered by
the shared send step (24h window, opt-outs, quiet hours: held, not skipped).
Only drafts exist for a company with `draft_v2` on, so for everyone else this
finds nothing.
"""

from __future__ import annotations

import datetime
import logging
import uuid
from typing import Any

from runtime.agent.draft import DRAFT_TTL_SECONDS

logger = logging.getLogger("mesiri.draft_reminder")

#: How long a card is kept without a new item (the existing card expiry).
DRAFT_TTL = datetime.timedelta(seconds=DRAFT_TTL_SECONDS)

#: How long before the reporting cutoff the reminder may go.
LEAD = datetime.timedelta(minutes=30)
#: A card still being built is left alone.
IDLE = datetime.timedelta(minutes=15)
#: A card that would expire before the cutoff window is reminded this long before it does.
EXPIRY_WARNING = datetime.timedelta(hours=1)
#: ... but not in the small hours (the send step holds night messages anyway).
DAY_STARTS = datetime.time(7, 0)

REMINDER_LINE = "You have 1 card not saved: tap Save or Cancel."
RULE_PREFIX = "draft_reminder:"


def reminder_due(
    *,
    local_now: datetime.datetime,
    cutoff: datetime.time,
    deadline: datetime.time,
    updated_local: datetime.datetime,
) -> bool:
    """Whether the card's one reminder is due: it has sat idle a while and has
    not expired, and either it is between half an hour before the cutoff and
    the send deadline (the project's own local time), or the card is within an
    hour of expiring in the daytime (it would be gone before the cutoff)."""
    age = local_now - updated_local
    if age < IDLE or age >= DRAFT_TTL:
        return False
    daytime = DAY_STARTS <= local_now.time() < deadline
    opens = (datetime.datetime.combine(local_now.date(), cutoff) - LEAD).time()
    return (opens <= local_now.time() < deadline) or (age >= DRAFT_TTL - EXPIRY_WARNING and daytime)


def reminder_payload(draft: Any, *, site: str | None = None) -> dict[str, Any]:
    from runtime.agent import draft as dr

    return {
        "message": f"{REMINDER_LINE}\n\n{dr.card_text(draft, site=site)}",
        "buttons": [
            {"id": dr.tap_id(dr.SAVE, draft.id), "title": dr.SAVE_TITLE},
            {"id": dr.tap_id(dr.CANCEL, draft.id), "title": dr.CANCEL_TITLE},
        ],
    }


async def queue_draft_reminders(
    conn: Any, *, now_utc: datetime.datetime | None = None
) -> int:
    """Queue the reminder for every open, unreminded draft whose time has come.
    Returns how many were queued. One draft's failure is rolled back and logged,
    never stopping the rest."""
    import sqlalchemy as sa

    from mesiri.application.automations.scheduling import local_now, parse_time_of_day
    from mesiri.application.projects.auto_dpr import send_deadline_or_default
    from mesiri.domains.organizations.lifecycle import operational_sql
    from mesiri.infrastructure.postgres.repositories.notifications import (
        PostgresNotificationRepository,
    )
    from runtime.agent.draft_store import PostgresDraftStore

    now = now_utc or datetime.datetime.now(datetime.UTC)
    rows = (
        await conn.execute(
            sa.text(
                f"""
                SELECT d.id, d.organization_id, d.user_id, d.project_id, d.site_id,
                       d.source_message_id, d.status, d.items,
                       EXTRACT(EPOCH FROM d.created_at) AS created_epoch,
                       EXTRACT(EPOCH FROM d.updated_at) AS updated_epoch,
                       p.reporting_timezone, p.reporting_cutoff_time, p.dpr_send_deadline
                FROM message_drafts d
                JOIN projects p ON p.id = d.project_id
                JOIN organizations o ON o.id = d.organization_id
                WHERE d.status = 'open' AND d.reminded_at IS NULL
                  AND p.auto_generate_dpr = true AND p.status != 'archived'
                  AND {operational_sql("o")}
                """
            )
        )
    ).mappings().all()

    notifications = PostgresNotificationRepository(conn)
    queued = 0
    for row in rows:
        try:
            zone = row["reporting_timezone"] or "UTC"
            local = local_now(timezone_name=zone, now_utc=now)
            updated = local_now(
                timezone_name=zone,
                now_utc=datetime.datetime.fromtimestamp(float(row["updated_epoch"]), datetime.UTC),
            )
            if not reminder_due(
                local_now=local,
                cutoff=parse_time_of_day(row["reporting_cutoff_time"] or "18:00"),
                deadline=parse_time_of_day(send_deadline_or_default(row["dpr_send_deadline"])),
                updated_local=updated,
            ):
                continue
            draft = PostgresDraftStore._draft(row)
            if not draft.live or draft.expired(now.timestamp()):
                continue
            async with conn.begin_nested():
                claimed = await notifications.claim(
                    organization_id=row["organization_id"],
                    rule_key=f"{RULE_PREFIX}{draft.id}",
                    subject_id=str(row["user_id"]),
                    occurred_on=local.date(),
                    recipient_user_id=uuid.UUID(str(row["user_id"])),
                    project_id=row["project_id"],
                    site_id=row["site_id"],
                    payload=reminder_payload(draft),
                )
                await conn.execute(
                    sa.text(
                        "UPDATE message_drafts SET reminded_at = now() "
                        "WHERE id = :id AND status = 'open' AND reminded_at IS NULL"
                    ),
                    {"id": row["id"]},
                )
            if claimed is not None:
                queued += 1
        except Exception:  # noqa: BLE001
            logger.exception("draft_reminder.failed draft_id=%s", row["id"])
    return queued
