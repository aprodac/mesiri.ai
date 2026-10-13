"""Runs #9 Notifications' scheduled checks and queues due notifications.

Invocable manually or via a cron entry -- not a persistent worker service,
same convention as project_timeline_events.py and run_event_consumers.py.
This is the BACKEND half only: it finds candidates and claims the
at-most-once slot (migration 0453's UNIQUE constraint). It never sends a
WhatsApp message itself -- the backend must not know about Meta's Cloud API
(architecture boundary: only apps/whatsapp-assistant/ talks to WhatsApp).
The assistant-side half (draining 'pending' rows and actually sending) is a
separate script in that app.

Scope: only find_stuck_confirmations runs today -- see
infrastructure/postgres/repositories/notifications.py's module docstring
for why the other three checks named in the original brief aren't
implemented yet.

Recommended VPS crontab entry (ops-managed, not tracked in this repo):
    */15 * * * * cd /opt/mesiri/backend && \
        PYTHONPATH=/opt/mesiri/shared/contracts/src:/opt/mesiri/platform/ai/src:/opt/mesiri/backend/src \
        /opt/mesiri/.venv/bin/python -m mesiri.scripts.run_notification_checks \
        >> /var/log/mesiri/notification-checks.log 2>&1

Run:  python -m mesiri.scripts.run_notification_checks
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import UTC, datetime

from ..application.notifications.checks import DEFAULT_STUCK_CONFIRMATION_AFTER
from ..bootstrap.settings import Settings
from ..domains.organizations.lifecycle import operational_sql
from ..infrastructure.postgres.database import PostgresDatabase
from ..infrastructure.postgres.repositories.notifications import (
    STUCK_CONFIRMATION_RULE_KEY,
    PostgresNotificationRepository,
)


async def _run_for_organization(
    repo: PostgresNotificationRepository, *, organization_id: uuid.UUID
) -> int:
    queued = 0
    stuck = await repo.find_stuck_confirmations(
        organization_id=organization_id, older_than=DEFAULT_STUCK_CONFIRMATION_AFTER
    )
    today = datetime.now(tz=UTC).date()
    for row in stuck:
        claimed = await repo.claim(
            organization_id=organization_id,
            rule_key=STUCK_CONFIRMATION_RULE_KEY,
            subject_id=str(row["id"]),
            occurred_on=today,
            recipient_user_id=row["user_id"],
            payload={"workflow_key": row["workflow_key"], "workflow_instance_id": str(row["id"])},
        )
        if claimed is not None:
            queued += 1
    return queued


async def run() -> int:
    """Runs every check for every active organization. Returns total queued."""
    from sqlalchemy import text

    settings = Settings()
    db = PostgresDatabase(settings.postgres)
    await db.connect()
    total = 0
    try:
        async with db.transaction() as conn:
            org_rows = (
                await conn.execute(text(f"SELECT id FROM organizations WHERE {operational_sql('')}"))
            ).mappings().all()
            repo = PostgresNotificationRepository(conn)
            for org_row in org_rows:
                total += await _run_for_organization(repo, organization_id=org_row["id"])
    finally:
        await db.disconnect()
    return total


def main() -> int:
    total = asyncio.run(run())
    print(f"notification-checks: queued {total} notification(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
