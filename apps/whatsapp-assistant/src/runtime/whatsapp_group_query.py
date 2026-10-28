"""Reads and writes of a site's WhatsApp group (WA-87, migration 0492).

Same shape as runtime/dpr_request_query.py: plain async methods over the
assistant's PostgresDatabase, so groups/ and the journey never write SQL.

Webhook lookups (by Meta's group id or create request id) run with no company
bound -- Meta's event names no company -- so they open their transaction in
``tenant_scope(None)``, as runtime/ops_alerts.py does; every row they return
carries its ``organization_id`` and callers act within that company only.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

if TYPE_CHECKING:
    from mesiri.infrastructure.postgres.database import PostgresDatabase

_GROUP_COLUMNS = (
    "g.id, g.organization_id, g.project_id, g.site_id, g.wa_group_id, g.create_request_id, "
    "g.subject, g.invite_link, g.status, g.created_by_user_id, "
    "s.name AS site_name, o.name AS org_name"
)
_GROUP_FROM = (
    "FROM whatsapp_groups g JOIN sites s ON s.id = g.site_id "
    "JOIN organizations o ON o.id = g.organization_id"
)


def _uuid(value: Any) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _row(mapping: Any) -> dict[str, Any] | None:
    if mapping is None:
        return None
    row = dict(mapping)
    for key in ("id", "organization_id", "project_id", "site_id", "group_id", "created_by_user_id"):
        if row.get(key) is not None:
            row[key] = str(row[key])
    return row


class WhatsAppGroupQueryService:
    def __init__(self, db: PostgresDatabase) -> None:
        self._db = db

    async def _one(self, sql: str, params: dict[str, Any], *, unscoped: bool = False) -> dict[str, Any] | None:
        from mesiri.infrastructure.postgres.tenant import tenant_scope

        if unscoped:
            with tenant_scope(None):
                async with self._db.transaction() as conn:
                    return _row((await conn.execute(text(sql), params)).mappings().first())
        async with self._db.transaction() as conn:
            return _row((await conn.execute(text(sql), params)).mappings().first())

    # -- groups ------------------------------------------------------------------

    async def live_for_site(self, *, organization_id: str, site_id: str) -> dict[str, Any] | None:
        """The site's `creating` or `active` group, if it has one."""
        return await self._one(
            f"SELECT {_GROUP_COLUMNS} {_GROUP_FROM} WHERE g.organization_id = :org "
            "AND g.site_id = :site AND g.status IN ('creating', 'active')",
            {"org": _uuid(organization_id), "site": _uuid(site_id)},
        )

    async def by_wa_group_id(self, wa_group_id: str) -> dict[str, Any] | None:
        return await self._one(
            f"SELECT {_GROUP_COLUMNS} {_GROUP_FROM} WHERE g.wa_group_id = :gid",
            {"gid": str(wa_group_id)},
            unscoped=True,
        )

    async def by_request_id(self, request_id: str) -> dict[str, Any] | None:
        return await self._one(
            f"SELECT {_GROUP_COLUMNS} {_GROUP_FROM} WHERE g.create_request_id = :rid "
            "ORDER BY g.created_at DESC LIMIT 1",
            {"rid": str(request_id)},
            unscoped=True,
        )

    async def creating_by_subject(self, subject: str) -> dict[str, Any] | None:
        """The newest group still being made with this name, for a "created"
        webhook that names neither a group nor a request we know."""
        return await self._one(
            f"SELECT {_GROUP_COLUMNS} {_GROUP_FROM} WHERE g.subject = :subject "
            "AND g.status = 'creating' ORDER BY g.created_at DESC LIMIT 1",
            {"subject": str(subject)},
            unscoped=True,
        )

    async def by_id(self, group_id: str) -> dict[str, Any] | None:
        return await self._one(
            f"SELECT {_GROUP_COLUMNS} {_GROUP_FROM} WHERE g.id = :id",
            {"id": _uuid(group_id)},
            unscoped=True,
        )

    async def start(
        self,
        *,
        organization_id: str,
        project_id: str | None,
        site_id: str,
        subject: str,
        created_by_user_id: str | None,
    ) -> dict[str, Any] | None:
        """A new `creating` row, or None when the site already has a live
        group (the partial unique index decides, so two taps can't make two)."""
        async with self._db.transaction() as conn:
            row = (
                await conn.execute(
                    text(
                        "INSERT INTO whatsapp_groups (organization_id, project_id, site_id, subject, "
                        "created_by_user_id) VALUES (:org, :project, :site, :subject, :by) "
                        "ON CONFLICT (site_id) WHERE status IN ('creating', 'active') DO NOTHING "
                        "RETURNING id"
                    ),
                    {
                        "org": _uuid(organization_id),
                        "project": _uuid(project_id) if project_id else None,
                        "site": _uuid(site_id),
                        "subject": subject,
                        "by": _uuid(created_by_user_id) if created_by_user_id else None,
                    },
                )
            ).first()
        if row is None:
            return None
        return await self.by_id(str(row[0]))

    async def update(self, group_id: str, **values: Any) -> None:
        """Set any of wa_group_id, create_request_id, invite_link, status."""
        allowed = {"wa_group_id", "create_request_id", "invite_link", "status"}
        fields = {k: v for k, v in values.items() if k in allowed}
        if not fields:
            return
        assignments = ", ".join(f"{k} = :{k}" for k in fields)
        from mesiri.infrastructure.postgres.tenant import tenant_scope

        with tenant_scope(None):
            async with self._db.transaction() as conn:
                await conn.execute(
                    text(f"UPDATE whatsapp_groups SET {assignments}, updated_at = now() WHERE id = :id"),
                    {**fields, "id": _uuid(group_id)},
                )

    async def active_for_project(self, *, organization_id: str, project_id: str) -> list[dict[str, Any]]:
        async with self._db.transaction() as conn:
            rows = (
                await conn.execute(
                    text(
                        f"SELECT {_GROUP_COLUMNS} {_GROUP_FROM} WHERE g.organization_id = :org "
                        "AND g.project_id = :project AND g.status = 'active' AND g.wa_group_id IS NOT NULL"
                    ),
                    {"org": _uuid(organization_id), "project": _uuid(project_id)},
                )
            ).mappings().all()
        return [r for r in (_row(m) for m in rows) if r is not None]

    async def site_team(self, *, organization_id: str, site_id: str) -> list[dict[str, str]]:
        """Active people of the company who reach this site and have a
        WhatsApp number: site members, project members with every site, and
        everyone whose role or access policy reaches every project
        (mesiri.authorization.roles: the same rule as actor.py)."""
        from mesiri.authorization.roles import ALL_PROJECTS_MODE, ORG_WIDE_ROLES

        async with self._db.transaction() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT u.id, u.full_name, u.whatsapp_number, u.role FROM users u "
                        "JOIN sites s ON s.id = :site AND s.organization_id = u.organization_id "
                        "WHERE u.organization_id = :org AND u.status = 'active' "
                        "AND u.whatsapp_number IS NOT NULL AND u.whatsapp_number <> '' AND ("
                        " upper(u.role) = ANY(:org_wide)"
                        " OR u.access_policy ->> 'mode' = :all_projects"
                        " OR EXISTS (SELECT 1 FROM site_members sm WHERE sm.site_id = s.id AND sm.user_id = u.id)"
                        " OR EXISTS (SELECT 1 FROM project_members pm WHERE pm.project_id = s.project_id"
                        "   AND pm.user_id = u.id AND coalesce(pm.site_access_mode, 'all_sites') = 'all_sites')"
                        ") ORDER BY u.full_name"
                    ),
                    {
                        "org": _uuid(organization_id),
                        "site": _uuid(site_id),
                        "org_wide": sorted(ORG_WIDE_ROLES),
                        "all_projects": ALL_PROJECTS_MODE,
                    },
                )
            ).mappings().all()
        return [
            {
                "user_id": str(r["id"]),
                "name": r["full_name"] or "",
                "wa_id": str(r["whatsapp_number"]),
                "role": str(r["role"] or "").upper(),
            }
            for r in rows
        ]

    async def company_sites(self, *, organization_id: str) -> list[dict[str, str]]:
        """The company's open sites with their project, for "make a group for <site>"."""
        async with self._db.transaction() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT s.id, s.name, s.project_id, p.name AS project_name FROM sites s "
                        "LEFT JOIN projects p ON p.id = s.project_id WHERE s.organization_id = :org "
                        "AND coalesce(s.status, 'active') <> 'archived' "
                        "AND coalesce(p.status, '') <> 'archived' ORDER BY s.name"
                    ),
                    {"org": _uuid(organization_id)},
                )
            ).mappings().all()
        return [
            {
                "site_id": str(r["id"]),
                "site_name": r["name"] or "",
                "project_id": str(r["project_id"]) if r["project_id"] else "",
                "project_name": r["project_name"] or "",
            }
            for r in rows
        ]

    async def companies(self) -> list[dict[str, str]]:
        """Every active company (a super admin names one)."""
        from mesiri.infrastructure.postgres.tenant import tenant_scope

        with tenant_scope(None):
            async with self._db.transaction() as conn:
                rows = (
                    await conn.execute(
                        text("SELECT id, name FROM organizations WHERE coalesce(status, 'active') = 'active'")
                    )
                ).mappings().all()
        return [{"organization_id": str(r["id"]), "name": r["name"] or ""} for r in rows]

    async def is_super_admin(self, wa_id: str) -> dict[str, str] | None:
        """A super admin (ADMIN with no company, as runtime/ops_alerts.py
        counts them) with this WhatsApp number: their user id and name."""
        from mesiri.infrastructure.postgres.tenant import tenant_scope

        digits = "".join(ch for ch in str(wa_id) if ch.isdigit())
        if not digits:
            return None
        with tenant_scope(None):
            async with self._db.transaction() as conn:
                row = (
                    await conn.execute(
                        text(
                            "SELECT id, full_name FROM users WHERE role = 'ADMIN' "
                            "AND organization_id IS NULL AND status = 'active' "
                            "AND regexp_replace(coalesce(whatsapp_number, ''), '[^0-9]', '', 'g') = :n "
                            "LIMIT 1"
                        ),
                        {"n": digits},
                    )
                ).mappings().first()
        return {"user_id": str(row["id"]), "name": row["full_name"] or ""} if row else None

    # -- join requests -----------------------------------------------------------

    async def record_join_request(
        self, *, group: dict[str, Any], join_request_id: str, wa_id: str, status: str
    ) -> dict[str, Any] | None:
        """The request as stored; None when this request was already recorded
        (a webhook delivered twice)."""
        from mesiri.infrastructure.postgres.tenant import tenant_scope

        with tenant_scope(None):
            async with self._db.transaction() as conn:
                row = (
                    await conn.execute(
                        text(
                            "INSERT INTO whatsapp_group_join_requests (organization_id, group_id, "
                            "join_request_id, wa_id, status, decided_at) VALUES (:org, :group, :rid, "
                            ":wa, :status, CASE WHEN :status = 'pending' THEN NULL ELSE now() END) "
                            "ON CONFLICT (group_id, join_request_id) DO NOTHING RETURNING id"
                        ),
                        {
                            "org": _uuid(group["organization_id"]),
                            "group": _uuid(group["id"]),
                            "rid": str(join_request_id),
                            "wa": str(wa_id),
                            "status": status,
                        },
                    )
                ).first()
        if row is None:
            return None
        return {"id": str(row[0]), "join_request_id": str(join_request_id), "wa_id": str(wa_id), "status": status}

    async def join_request(self, request_row_id: str) -> dict[str, Any] | None:
        try:
            row_id = _uuid(request_row_id)
        except ValueError:
            return None
        return await self._one(
            "SELECT id, organization_id, group_id, join_request_id, wa_id, status "
            "FROM whatsapp_group_join_requests WHERE id = :id",
            {"id": row_id},
            unscoped=True,
        )

    async def decide_join_request(self, request_row_id: str, *, status: str, user_id: str | None) -> bool:
        """Pending -> approved/rejected. False when it was decided already."""
        from mesiri.infrastructure.postgres.tenant import tenant_scope

        with tenant_scope(None):
            async with self._db.transaction() as conn:
                row = (
                    await conn.execute(
                        text(
                            "UPDATE whatsapp_group_join_requests SET status = :status, "
                            "decided_by_user_id = :by, decided_at = now() "
                            "WHERE id = :id AND status = 'pending' RETURNING id"
                        ),
                        {"status": status, "by": _uuid(user_id) if user_id else None, "id": _uuid(request_row_id)},
                    )
                ).first()
        return row is not None
