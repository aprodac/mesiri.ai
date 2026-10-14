"""PostgreSQL side of DPR recipients and WhatsApp opt-ins (BE-15, migration 0471).

The only file holding SQL for `report_recipients` and `whatsapp_opt_ins`.
Rules (phone format, who needs an opt-in) are in application/dpr/recipients.py.

Opt-in rows are written with clock_timestamp(), not the column default now():
an opt-in and an opt-out can land in one transaction, and now() would give
both the same time and make "latest row" ambiguous (same as fact_reviews).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

# Latest consent for a phone within the company; joined into the list so the
# dashboard can show "waiting for opt-in" next to each contact.
_LATEST_CONSENT = (
    "SELECT o.state, o.method, o.created_at FROM whatsapp_opt_ins o "
    "WHERE o.organization_id = :org_id AND o.phone = {phone} "
    "ORDER BY o.created_at DESC, o.id DESC LIMIT 1"
)

_RECIPIENT_COLUMNS = (
    "r.id, r.project_id, r.user_id, r.label, r.created_at, "
    "COALESCE(u.full_name, r.name) AS name, "
    "COALESCE(r.phone, regexp_replace(u.whatsapp_number, '[^0-9]', '', 'g')) AS phone, "
    "u.role AS user_role, c.state AS consent_state, c.method AS consent_method, "
    "c.created_at AS consent_at"
)


class PostgresReportRecipientRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    # ------------------------------------------------------------------
    # Recipients
    # ------------------------------------------------------------------

    async def list_active(
        self, *, organization_id: uuid.UUID, project_id: uuid.UUID
    ) -> list[dict[str, Any]]:
        rows = (
            await self._conn.execute(
                text(
                    f"SELECT {_RECIPIENT_COLUMNS} FROM report_recipients r "
                    "LEFT JOIN users u ON u.id = r.user_id "
                    "LEFT JOIN LATERAL ("
                    + _LATEST_CONSENT.format(
                        phone="COALESCE(r.phone, regexp_replace(u.whatsapp_number, '[^0-9]', '', 'g'))"
                    )
                    + ") c ON true "
                    "WHERE r.organization_id = :org_id AND r.project_id = :project_id "
                    "AND r.removed_at IS NULL "
                    "ORDER BY r.created_at, r.id"
                ),
                {"org_id": organization_id, "project_id": project_id},
            )
        ).mappings().all()
        return [dict(row) for row in rows]

    async def find_active(
        self, *, organization_id: uuid.UUID, project_id: uuid.UUID, recipient_id: uuid.UUID
    ) -> dict[str, Any] | None:
        for row in await self.list_active(organization_id=organization_id, project_id=project_id):
            if row["id"] == recipient_id:
                return row
        return None

    async def project_exists(self, *, organization_id: uuid.UUID, project_id: uuid.UUID) -> bool:
        row = (
            await self._conn.execute(
                text("SELECT 1 FROM projects WHERE id = :project_id AND organization_id = :org_id"),
                {"org_id": organization_id, "project_id": project_id},
            )
        ).first()
        return row is not None

    async def active_user_in_org(self, *, organization_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        row = (
            await self._conn.execute(
                text(
                    "SELECT 1 FROM users WHERE id = :user_id AND organization_id = :org_id "
                    "AND lower(status) = 'active'"
                ),
                {"org_id": organization_id, "user_id": user_id},
            )
        ).first()
        return row is not None

    async def has_active(
        self,
        *,
        project_id: uuid.UUID,
        user_id: uuid.UUID | None = None,
        phone: str | None = None,
    ) -> bool:
        column, value = ("user_id", user_id) if user_id is not None else ("phone", phone)
        row = (
            await self._conn.execute(
                text(
                    f"SELECT 1 FROM report_recipients WHERE project_id = :project_id "
                    f"AND {column} = :value AND removed_at IS NULL"
                ),
                {"project_id": project_id, "value": value},
            )
        ).first()
        return row is not None

    async def add(
        self,
        *,
        organization_id: uuid.UUID,
        project_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        user_id: uuid.UUID | None = None,
        name: str | None = None,
        phone: str | None = None,
        label: str | None = None,
    ) -> uuid.UUID:
        recipient_id = uuid.uuid4()
        await self._conn.execute(
            text(
                "INSERT INTO report_recipients "
                "(id, organization_id, project_id, user_id, name, phone, label, created_by_user_id) "
                "VALUES (:id, :org_id, :project_id, :user_id, :name, :phone, :label, :actor)"
            ),
            {
                "id": recipient_id,
                "org_id": organization_id,
                "project_id": project_id,
                "user_id": user_id,
                "name": name,
                "phone": phone,
                "label": label,
                "actor": actor_user_id,
            },
        )
        return recipient_id

    async def remove(
        self,
        *,
        organization_id: uuid.UUID,
        project_id: uuid.UUID,
        recipient_id: uuid.UUID,
        actor_user_id: uuid.UUID,
    ) -> bool:
        result = await self._conn.execute(
            text(
                "UPDATE report_recipients SET removed_at = now(), removed_by_user_id = :actor "
                "WHERE id = :id AND organization_id = :org_id AND project_id = :project_id "
                "AND removed_at IS NULL"
            ),
            {
                "id": recipient_id,
                "org_id": organization_id,
                "project_id": project_id,
                "actor": actor_user_id,
            },
        )
        return (result.rowcount or 0) > 0

    # ------------------------------------------------------------------
    # Opt-ins
    # ------------------------------------------------------------------

    async def record_consent(
        self,
        *,
        organization_id: uuid.UUID,
        phone: str,
        state: str,
        method: str,
        note: str | None = None,
        actor_user_id: uuid.UUID | None = None,
    ) -> None:
        await self._conn.execute(
            text(
                "INSERT INTO whatsapp_opt_ins "
                "(id, organization_id, phone, state, method, note, recorded_by_user_id, created_at) "
                "VALUES (:id, :org_id, :phone, :state, :method, :note, :actor, clock_timestamp())"
            ),
            {
                "id": uuid.uuid4(),
                "org_id": organization_id,
                "phone": phone,
                "state": state,
                "method": method,
                "note": note,
                "actor": actor_user_id,
            },
        )

    async def latest_consent_state(self, *, organization_id: uuid.UUID, phone: str) -> str | None:
        row = (
            await self._conn.execute(
                text(_LATEST_CONSENT.format(phone=":phone")),
                {"org_id": organization_id, "phone": phone},
            )
        ).mappings().first()
        return row["state"] if row else None
