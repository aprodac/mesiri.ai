"""BE-01: the M4 context ports, read straight from the main (control-plane) tables.

The only source since BE-01 step 3: the ``context_*`` copy these ports used to
read (and the projection that filled it) is gone. Context IDs are pure
functions of the main UUIDs (``ctx_user_<uuid>``, see identity_bridge.py), so
they are the same IDs the copy held: Redis active context, replies, workflows
and everything downstream are unchanged.

Each rule below reproduces what the copy computed, so the switch changed no
answer (checked side by side in production, BE-01 step 0).

Known behaviours kept on purpose (not fixed here, so the switch changed
nothing):

- A site is authorized whenever its project is, so ``site_access_mode`` ==
  "explicit" does not limit which sites someone can report on over WhatsApp.
  A site is also authorized through site membership even when its project is
  not on track. Both exactly as before.
- A project counts as active only with status ``on_track``.
- Roles, permissions and per-user preferences have no writer anywhere in the
  code, so the copy holds none; these return empty, as the copy does.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from mesiri.authorization.roles import is_org_wide
from mesiri.domains.organizations.lifecycle import is_operational
from mesiri.infrastructure.errors import map_postgres_error

from .identity_bridge import (
    context_organization_id,
    context_project_id,
    context_site_id,
    context_user_id,
)
from .models import (
    ContextPreferences,
    ExternalIdentity,
    Membership,
    Organization,
    Project,
    Site,
    User,
)

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncEngine

_ORG = "ctx_org_"
_USER = "ctx_user_"
_PROJECT = "ctx_proj_"
_SITE = "ctx_site_"


def _uuid(context_id: str | None, prefix: str) -> UUID | None:
    """The main-table UUID inside a context ID, or None if it isn't one."""
    if not context_id or not context_id.startswith(prefix):
        return None
    try:
        return UUID(context_id[len(prefix) :])
    except ValueError:
        return None


def _digits(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def _status_is(value: object, expected: str) -> bool:
    return str(value or "").strip().lower() == expected


class _EngineMixin:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def _rows(self, sql: str, params: dict[str, Any]) -> list[Any]:
        from sqlalchemy import text

        try:
            async with self._engine.connect() as conn:
                return list((await conn.execute(text(sql), params)).mappings().all())
        except Exception as exc:  # noqa: BLE001 -- mapped to the shared contract
            raise map_postgres_error(exc) from exc

    async def _row(self, sql: str, params: dict[str, Any]) -> Any | None:
        rows = await self._rows(sql, params)
        return rows[0] if rows else None


def _project(r: Any) -> Project:
    return Project(
        context_project_id(r["id"]),
        context_organization_id(r["organization_id"]),
        r["name"],
        _status_is(r["status"], "on_track"),
    )


def _site(r: Any) -> Site:
    return Site(
        context_site_id(r["id"]),
        context_project_id(r["project_id"]),
        context_organization_id(r["organization_id"]),
        r["name"],
        _status_is(r["status"], "active"),
    )


class MainExternalIdentityRepository(_EngineMixin):
    async def find_identity(
        self, *, provider: str, external_subject: str
    ) -> ExternalIdentity | None:
        digits = _digits(external_subject)
        if provider != "whatsapp" or not digits:
            return None
        # Inactive users still match (the resolver then reports them as
        # disabled, as before). Since migration 0483 a number's digits belong
        # to one user (BE-04), so the ORDER BY only matters for a bad row.
        row = await self._row(
            "SELECT id FROM users "
            "WHERE whatsapp_number IS NOT NULL "
            "  AND regexp_replace(whatsapp_number, '\\D', '', 'g') = :d "
            "ORDER BY (lower(status) = 'active') DESC, created_at, id LIMIT 1",
            {"d": digits},
        )
        if row is None:
            return None
        return ExternalIdentity(provider, digits, context_user_id(row["id"]))

    async def get_user(self, user_id: str) -> User | None:
        uid = _uuid(user_id, _USER)
        if uid is None:
            return None
        row = await self._row("SELECT status FROM users WHERE id = :id", {"id": uid})
        if row is None:
            return None
        return User(user_id, _status_is(row["status"], "active"), None, None)


class MainMembershipRepository(_EngineMixin):
    async def get_organization(self, organization_id: str) -> Organization | None:
        oid = _uuid(organization_id, _ORG)
        if oid is None:
            return None
        row = await self._row(
            "SELECT status, trial_ends_at FROM organizations WHERE id = :id", {"id": oid}
        )
        if row is None:
            return None
        active = is_operational(row["status"], row["trial_ends_at"], datetime.now(UTC))
        return Organization(organization_id, active)

    async def list_active_memberships(self, user_id: str) -> list[Membership]:
        uid = _uuid(user_id, _USER)
        if uid is None:
            return []
        row = await self._row(
            "SELECT o.id, o.status, o.trial_ends_at FROM users u "
            "JOIN organizations o ON o.id = u.organization_id WHERE u.id = :id",
            {"id": uid},
        )
        if row is None or not is_operational(
            row["status"], row["trial_ends_at"], datetime.now(UTC)
        ):
            return []
        org_ctx = context_organization_id(row["id"])
        return [Membership(f"mbr_{user_id}_{org_ctx}", org_ctx, user_id, True)]


class MainRolePermissionRepository:
    """Nothing in the code assigns context roles, so there are none to return."""

    async def role_ids_for_membership(self, membership_id: str) -> list[str]:
        return []

    async def permissions_for_membership(self, membership_id: str) -> list[str]:
        return []


# Projects this user may report on, as the copy computes them: every active
# project in the org for an org-wide user (role or access policy, see
# mesiri.authorization.roles.is_org_wide), otherwise the projects they are a
# member of. :org_wide is computed in Python from that one shared rule.
_AUTHORIZED_PROJECT_IDS = (
    "SELECT p.id FROM projects p "
    "WHERE p.organization_id = :org AND lower(p.status) = 'on_track' AND ("
    "  :org_wide OR p.id IN (SELECT project_id FROM project_members WHERE user_id = :u)"
    ")"
)


# The sites this user may report on: every site of every project they are a
# member of with site_access_mode "all_sites", their site_members sites in
# their other ("custom_sites") projects, or every site in their org if
# org-wide. Being on a project does not by itself reach a custom_sites
# member's other sites (BE-34): the same rule as AuthorizationService and
# PostgresActorReader. Project
# status plays no part here, so a site can be reachable through this even when
# its project is not on track -- kept as the copy has it.
_MEMBER_SITE_IDS = (
    "SELECT ms.id FROM sites ms "
    "JOIN project_members pm ON pm.project_id = ms.project_id "
    "WHERE NOT :org_wide AND pm.user_id = :u AND pm.site_access_mode = 'all_sites' "
    "UNION SELECT sm.site_id FROM site_members sm "
    "JOIN sites es ON es.id = sm.site_id "
    "JOIN project_members epm ON epm.project_id = es.project_id AND epm.user_id = sm.user_id "
    "WHERE NOT :org_wide AND sm.user_id = :u "
    "  AND epm.site_access_mode IS DISTINCT FROM 'all_sites' "
    "UNION SELECT ws.id FROM sites ws "
    "JOIN projects wp ON wp.id = ws.project_id "
    "JOIN users wu ON wu.id = :u AND wu.organization_id = wp.organization_id "
    "WHERE :org_wide"
)


class _AuthorizedMixin(_EngineMixin):
    async def _scope(self, organization_id: str, user_id: str) -> dict[str, Any] | None:
        oid, uid = _uuid(organization_id, _ORG), _uuid(user_id, _USER)
        if oid is None or uid is None:
            return None
        row = await self._row("SELECT role, access_policy FROM users WHERE id = :id", {"id": uid})
        org_wide = bool(row) and is_org_wide(row["role"], row["access_policy"] or {})
        return {"org": oid, "u": uid, "org_wide": org_wide}


class MainProjectRepository(_AuthorizedMixin):
    _COLUMNS = "SELECT id, organization_id, name, status FROM projects "

    async def get_authorized_project(
        self, *, organization_id: str, user_id: str, project_id: str
    ) -> Project | None:
        scope, pid = await self._scope(organization_id, user_id), _uuid(project_id, _PROJECT)
        if scope is None or pid is None:
            return None
        row = await self._row(
            self._COLUMNS + f"WHERE id = :pid AND id IN ({_AUTHORIZED_PROJECT_IDS})",
            {**scope, "pid": pid},
        )
        return _project(row) if row else None

    async def find_authorized_projects_by_name(
        self, *, organization_id: str, user_id: str, name: str
    ) -> list[Project]:
        scope = await self._scope(organization_id, user_id)
        if scope is None:
            return []
        rows = await self._rows(
            self._COLUMNS + "WHERE name ILIKE '%' || :name || '%' "
            f"AND id IN ({_AUTHORIZED_PROJECT_IDS})",
            {**scope, "name": name.strip()},
        )
        return sorted((_project(r) for r in rows), key=lambda p: p.project_id)

    async def list_authorized_projects(
        self, *, organization_id: str, user_id: str
    ) -> list[Project]:
        scope = await self._scope(organization_id, user_id)
        if scope is None:
            return []
        rows = await self._rows(self._COLUMNS + f"WHERE id IN ({_AUTHORIZED_PROJECT_IDS})", scope)
        return sorted((_project(r) for r in rows), key=lambda p: p.project_id)

    async def get_project_in_org(self, *, organization_id: str, project_id: str) -> Project | None:
        oid, pid = _uuid(organization_id, _ORG), _uuid(project_id, _PROJECT)
        if oid is None or pid is None:
            return None
        row = await self._row(
            self._COLUMNS
            + "WHERE id = :pid AND organization_id = :org AND lower(status) = 'on_track'",
            {"pid": pid, "org": oid},
        )
        return _project(row) if row else None


class MainSiteRepository(_AuthorizedMixin):
    _COLUMNS = "SELECT s.id, s.project_id, s.organization_id, s.name, s.status FROM sites s "

    async def get_authorized_site(
        self, *, organization_id: str, user_id: str, site_id: str
    ) -> Site | None:
        scope, sid = await self._scope(organization_id, user_id), _uuid(site_id, _SITE)
        if scope is None or sid is None:
            return None
        row = await self._row(
            self._COLUMNS + "WHERE s.id = :sid AND s.organization_id = :org "
            "AND lower(s.status) = 'active' "
            f"AND s.id IN ({_MEMBER_SITE_IDS})",
            {**scope, "sid": sid},
        )
        return _site(row) if row else None

    async def find_authorized_sites_by_name(
        self, *, organization_id: str, user_id: str, name: str, project_id: str | None = None
    ) -> list[Site]:
        scope = await self._scope(organization_id, user_id)
        if scope is None:
            return []
        params: dict[str, Any] = {**scope, "name": name.strip()}
        clause = ""
        if project_id is not None:
            pid = _uuid(project_id, _PROJECT)
            if pid is None:
                return []
            clause = " AND s.project_id = :pid"
            params["pid"] = pid
        rows = await self._rows(
            self._COLUMNS + "WHERE lower(s.name) = lower(:name) AND s.organization_id = :org "
            "AND lower(s.status) = 'active'" + clause + " "
            f"AND s.id IN ({_MEMBER_SITE_IDS})",
            params,
        )
        return sorted((_site(r) for r in rows), key=lambda s: s.site_id)

    async def get_site_in_org(self, *, organization_id: str, site_id: str) -> Site | None:
        oid, sid = _uuid(organization_id, _ORG), _uuid(site_id, _SITE)
        if oid is None or sid is None:
            return None
        row = await self._row(
            self._COLUMNS
            + "WHERE s.id = :sid AND s.organization_id = :org AND lower(s.status) = 'active'",
            {"sid": sid, "org": oid},
        )
        return _site(row) if row else None


class MainContextPreferenceRepository:
    """Nothing in the code writes per-user defaults, so there are none to return."""

    async def get_preferences(
        self, *, organization_id: str, user_id: str
    ) -> ContextPreferences | None:
        return None


def _scope_pair(row: Any) -> tuple[str | None, str | None] | None:
    if row is None:
        return None
    project_id = context_project_id(row["project_id"]) if row["project_id"] else None
    site_id = context_site_id(row["site_id"]) if row["site_id"] else None
    if project_id is None and site_id is None:
        return None
    return (project_id, site_id)


class MainReplyContextProvider(_EngineMixin):
    """Scope of the message being replied to (see PostgresReplyContextProvider)."""

    async def context_for_reply(
        self, *, organization_id: str, replied_to_message_id: str
    ) -> tuple[str | None, str | None] | None:
        oid = _uuid(organization_id, _ORG)
        if oid is None:
            return None
        # The copy only maps IDs that exist in it, i.e. projects/sites that
        # still exist; the joins keep that.
        row = await self._row(
            "SELECT p.id AS project_id, s.id AS site_id "
            "FROM inbound_messages im "
            "LEFT JOIN projects p ON p.id = im.project_id "
            "LEFT JOIN sites s ON s.id = im.site_id "
            "WHERE im.organization_id = :org "
            "  AND (im.dedup_key = :wamid OR im.reply_wamid = :wamid) "
            "ORDER BY im.received_at DESC LIMIT 1",
            {"org": oid, "wamid": replied_to_message_id},
        )
        return _scope_pair(row)


class MainWorkflowContextProvider(_EngineMixin):
    """Scope of the user's open workflow (see PostgresWorkflowContextProvider)."""

    _OPEN_PHASES = ("awaiting_confirmation", "collecting_fields")

    async def active_workflow_context(
        self, *, organization_id: str, user_id: str
    ) -> tuple[str | None, str | None] | None:
        oid, uid = _uuid(organization_id, _ORG), _uuid(user_id, _USER)
        if oid is None or uid is None:
            return None
        row = await self._row(
            "SELECT p.id AS project_id, s.id AS site_id "
            "FROM workflow_instances wi "
            "LEFT JOIN projects p ON p.id = NULLIF(wi.state->>'project_id', '')::uuid "
            "LEFT JOIN sites s ON s.id = NULLIF(wi.state->>'site_id', '')::uuid "
            "WHERE wi.organization_id = :org AND wi.user_id = :usr "
            "  AND wi.phase = ANY(:phases) "
            "ORDER BY wi.updated_at DESC LIMIT 1",
            {"org": oid, "usr": uid, "phases": list(self._OPEN_PHASES)},
        )
        return _scope_pair(row)


class MainIdentityBridgeRepository(_EngineMixin):
    """Context ID -> main UUID. Pure, plus an existence check like the copy's."""

    async def _exists(self, table: str, prefix: str, context_id: str) -> str | None:
        uid = _uuid(context_id, prefix)
        if uid is None:
            return None
        row = await self._row(f"SELECT id FROM {table} WHERE id = :id", {"id": uid})
        return str(uid) if row else None

    async def canonical_organization_id(self, context_organization_id: str) -> str | None:
        return await self._exists("organizations", _ORG, context_organization_id)

    async def canonical_user_id(self, context_user_id: str) -> str | None:
        return await self._exists("users", _USER, context_user_id)

    async def canonical_project_id(self, context_project_id: str) -> str | None:
        return await self._exists("projects", _PROJECT, context_project_id)

    async def canonical_site_id(self, context_site_id: str) -> str | None:
        return await self._exists("sites", _SITE, context_site_id)
