"""Trial reminders and "continue" requests (SS-08).

`queue_trial_reminders` runs on the assistant's in-app scheduler tick
(runtime/automation_runner.py), next to the project auto-DPR queueing. It
only *queues* notification rows: sending, the 24-hour window, the template
and quiet hours are the notification sender's job
(runtime/send_pending_notifications.py), so there is one send policy.
At most once per owner per reminder: the notifications table's UNIQUE
(organization, rule, subject, day) slot, with the subject naming the owner
and the reminder and the day being the trial's end date.

`record_continue_request` is shared by WhatsApp and the dashboard.

Takes an externally-supplied connection and never commits.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa

from mesiri.domains.organizations import lifecycle
from mesiri.domains.organizations import settings as org_settings
from mesiri.domains.organizations import trial_notices as notices
from mesiri.domains.organizations.platform_settings import TRIAL_POLICY
from mesiri.infrastructure.postgres.repositories.notifications import (
    PostgresNotificationRepository,
)
from mesiri.infrastructure.postgres.repositories.organization_settings import (
    PostgresOrganizationSettingsRepository,
)
from mesiri.infrastructure.postgres.repositories.platform_settings import (
    PostgresPlatformSettingsRepository,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection


async def queue_trial_reminders(conn: AsyncConnection, *, now: dt.datetime | None = None) -> int:
    """Queue today's trial reminders; returns how many were newly queued."""
    now = now or dt.datetime.now(dt.UTC)
    rows = (
        (
            await conn.execute(
                sa.text(
                    "SELECT id, name, timezone, trial_ends_at FROM organizations "
                    "WHERE lower(status) = :trial AND trial_ends_at IS NOT NULL "
                    "AND trial_ends_at > :now AND trial_ends_at <= :horizon"
                ),
                {"trial": lifecycle.TRIAL, "now": now, "horizon": now + dt.timedelta(days=2)},
            )
        )
        .mappings()
        .all()
    )

    repo = PostgresNotificationRepository(conn)
    queued = 0
    for org in rows:
        kind = notices.reminder_due(org["trial_ends_at"], now)
        if kind is None:
            continue
        end_day = notices.end_day_label(org["trial_ends_at"], org["timezone"])
        reports = await _reports_made(conn, org["id"])
        message = notices.reminder_message(
            kind, company=org["name"], end_day=end_day, reports_sent=reports
        )
        for owner_id in await _owner_ids(conn, org["id"]):
            claimed = await repo.claim(
                organization_id=org["id"],
                rule_key=notices.TRIAL_REMINDER_RULE,
                subject_id=f"{owner_id}:{kind}",
                occurred_on=org["trial_ends_at"].date(),
                recipient_user_id=owner_id,
                payload={
                    "message": message,
                    "kind": kind,
                    "template": {
                        "name": notices.TEMPLATE_NAME,
                        "body_params": notices.reminder_template_params(
                            company=org["name"], end_day=end_day
                        ),
                    },
                },
            )
            if claimed is not None:
                queued += 1
    return queued


async def expiry_details(conn: AsyncConnection, organization_id: Any) -> dict[str, Any] | None:
    """What the expired-trial replies need: status, end day, retention, owner."""
    org = (
        (
            await conn.execute(
                sa.text(
                    "SELECT name, status, timezone, trial_ends_at FROM organizations WHERE id = :id"
                ),
                {"id": organization_id},
            )
        )
        .mappings()
        .first()
    )
    if org is None:
        return None
    now = dt.datetime.now(dt.UTC)
    policy = await PostgresPlatformSettingsRepository(conn).get(TRIAL_POLICY)
    owner = (
        await conn.execute(
            sa.text(
                "SELECT full_name FROM users WHERE organization_id = :org AND upper(role) = 'ADMIN' "
                "AND lower(status) = 'active' ORDER BY created_at LIMIT 1"
            ),
            {"org": organization_id},
        )
    ).first()
    return {
        "company": org["name"],
        "effective_status": lifecycle.effective_status(org["status"], org["trial_ends_at"], now),
        "end_day": notices.end_day_label(org["trial_ends_at"], org["timezone"]),
        "retention_days": int(policy.get("retention_days_after_expiry") or 30),
        "owner_name": owner.full_name if owner else None,
    }


async def record_continue_request(
    conn: AsyncConnection, organization_id: Any, *, user_id: str, via: str
) -> bool:
    """Record "this company wants to continue"; False if one is already open."""
    repo = PostgresOrganizationSettingsRepository(conn)
    requests, added = notices.add_continue_request(
        await repo.get(organization_id, org_settings.CONTINUE_REQUESTS),
        user_id=user_id,
        via=via,
        now=dt.datetime.now(dt.UTC),
    )
    if added:
        await repo.set(
            organization_id,
            org_settings.CONTINUE_REQUESTS,
            requests,
            updated_by=_uuid_or_none(user_id),
        )
    return added


async def _owner_ids(conn: AsyncConnection, organization_id: Any) -> list[uuid.UUID]:
    rows = await conn.execute(
        sa.text(
            "SELECT id FROM users WHERE organization_id = :org AND upper(role) = 'ADMIN' "
            "AND lower(status) = 'active' AND whatsapp_number IS NOT NULL"
        ),
        {"org": organization_id},
    )
    return [r.id for r in rows]


async def _reports_made(conn: AsyncConnection, organization_id: Any) -> int:
    count = await conn.execute(
        sa.text("SELECT count(*) FROM daily_reports WHERE organization_id = :org"),
        {"org": organization_id},
    )
    return int(count.scalar() or 0)


def _uuid_or_none(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None
