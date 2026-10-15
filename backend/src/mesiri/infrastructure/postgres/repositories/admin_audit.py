"""PostgreSQL store for the superadmin audit log (migration 0475, BE-05).

Append-only: insert and read, nothing else. Takes an externally-supplied
connection and never commits, so an entry is saved exactly when the change
it describes is.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection

admin_audit_log = sa.Table(
    "admin_audit_log",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
    sa.Column("occurred_at", sa.DateTime(timezone=True)),
    sa.Column("actor_kind", sa.String),
    sa.Column("actor_user_id", sa.UUID(as_uuid=True)),
    sa.Column("actor_label", sa.String),
    sa.Column("action", sa.String),
    sa.Column("organization_id", sa.UUID(as_uuid=True)),
    sa.Column("target_type", sa.String),
    sa.Column("target_id", sa.String),
    sa.Column("summary", sa.String),
    sa.Column("details", JSONB),
)


@dataclass(frozen=True, slots=True)
class AuditEntry:
    id: uuid.UUID
    occurred_at: dt.datetime
    actor_kind: str
    actor_user_id: uuid.UUID | None
    actor_label: str | None
    action: str
    organization_id: uuid.UUID | None
    target_type: str | None
    target_id: str | None
    summary: str | None
    details: dict[str, Any]


class PostgresAdminAuditRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def insert(self, entry: AuditEntry) -> None:
        await self._conn.execute(
            admin_audit_log.insert().values(
                id=entry.id,
                occurred_at=entry.occurred_at,
                actor_kind=entry.actor_kind,
                actor_user_id=entry.actor_user_id,
                actor_label=entry.actor_label,
                action=entry.action,
                organization_id=entry.organization_id,
                target_type=entry.target_type,
                target_id=entry.target_id,
                summary=entry.summary,
                details=entry.details,
            )
        )

    async def list_for_organization(
        self,
        organization_id: uuid.UUID,
        *,
        limit: int = 50,
        before: dt.datetime | None = None,
    ) -> list[AuditEntry]:
        """Newest first. `before` pages back from an entry's `occurred_at`."""
        stmt = sa.select(admin_audit_log).where(
            admin_audit_log.c.organization_id == organization_id
        )
        if before is not None:
            stmt = stmt.where(admin_audit_log.c.occurred_at < before)
        stmt = stmt.order_by(admin_audit_log.c.occurred_at.desc()).limit(limit)
        rows = (await self._conn.execute(stmt)).mappings().all()
        return [AuditEntry(**{**row, "details": row["details"] or {}}) for row in rows]
