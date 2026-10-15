"""Record a superadmin action (BE-05): the one call every admin change makes.

    await record_admin_action(
        conn,
        actor=actor_from_admin(admin),
        action=COMPANY_TRIAL_EXTENDED,
        organization_id=org_id,
        target_type="organization",
        target_id=org_id,
        summary="Trial extended by 7 days",
        details={"before": {...}, "after": {...}},
    )

Call it with the same connection, inside the same transaction, as the change
itself: the entry is saved if and only if the change is, and if the entry
can't be written the change fails too (an unrecorded admin change is the
thing this log exists to prevent). Secrets in `details` are replaced with
"[changed]" before anything is stored.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import TYPE_CHECKING, Any

from mesiri.domains.audit.actions import (
    AuditActor,
    clip_label,
    clip_summary,
    redact,
    validate_entry,
)
from mesiri.infrastructure.postgres.repositories.admin_audit import (
    AuditEntry,
    PostgresAdminAuditRepository,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection


async def record_admin_action(
    conn: AsyncConnection,
    *,
    actor: AuditActor,
    action: str,
    organization_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: uuid.UUID | str | None = None,
    summary: str | None = None,
    details: dict[str, Any] | None = None,
    now: dt.datetime | None = None,
) -> AuditEntry:
    """Write one audit entry in the caller's transaction; returns it.
    Raises ValueError for an unknown action or actor kind."""
    validate_entry(action, actor)
    entry = AuditEntry(
        id=uuid.uuid4(),
        occurred_at=now or dt.datetime.now(dt.UTC),
        actor_kind=actor.kind,
        actor_user_id=actor.user_id,
        actor_label=clip_label(actor.label),
        action=action,
        organization_id=organization_id,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        summary=clip_summary(summary),
        details=redact(details or {}),
    )
    await PostgresAdminAuditRepository(conn).insert(entry)
    return entry
