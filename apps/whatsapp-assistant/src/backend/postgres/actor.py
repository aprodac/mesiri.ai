"""PostgreSQL implementation of the ActorReader port.

THIS IS THE ONLY FILE IN THE ASSISTANT THAT IS ALLOWED TO:
  - know about the users, organizations, projects, or sites tables
  - write JOIN conditions against the backend schema
  - hold a raw SQLAlchemy engine / connection
  - apply raw tenant-filtering SQL

If the backend schema changes, change this file. Nothing else in the assistant
should need to change.
"""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime

from backend.ports import ActorIdentity, ProjectSummary, SiteSummary
from mesiri.authorization.roles import is_org_wide
from mesiri.domains.organizations.lifecycle import is_operational

# Who reaches every project in their org (an org-wide role, or an
# all_projects access policy) is defined once in
# mesiri/authorization/roles.py. It used to be copied into each of the five
# surfaces that ask the question; one copy silently omitted the role half,
# so the control panel reported admins as having no project access at all.

# A user reaches a project via a direct project_members row, or via a
# site_members row on one of its sites (site access implies its project --
# same rule the M4 context layer applies in context/postgres_repositories.py's
# _AUTHORIZED_PROJECT_IDS). Non-admins get exactly this and nothing more.
_MEMBER_PROJECTS_SQL = """
SELECT p.id, p.name, p.location, p.code, p.status, p.progress, p.open_issues
FROM projects p
WHERE p.organization_id = :org
  AND (
    p.id IN (SELECT pm.project_id FROM project_members pm WHERE pm.user_id = :uid)
    OR p.id IN (
      SELECT s.project_id FROM site_members sm
      JOIN sites s ON s.id = sm.site_id
      WHERE sm.user_id = :uid
    )
  )
ORDER BY p.name
"""

_ALL_ORG_PROJECTS_SQL = """
SELECT id, name, location, code, status, progress, open_issues
FROM projects
WHERE organization_id = :org
ORDER BY name
"""

# Sites follow project_members.site_access_mode: 'all_sites' (the default)
# exposes every site under a project the user is a member of; 'custom_sites'
# narrows to explicit site_members rows. Deliberately NOT expanded into
# site_members rows at write time -- that would go stale the moment a new site
# is added to the project (see migration 0350's note).
_MEMBER_SITES_SQL = """
SELECT s.id, s.name, s.project_id
FROM sites s
WHERE s.organization_id = :org
  AND s.status = 'active'
  AND (
    s.project_id IN (
      SELECT pm.project_id FROM project_members pm
      WHERE pm.user_id = :uid AND pm.site_access_mode = 'all_sites'
    )
    OR s.id IN (SELECT sm.site_id FROM site_members sm WHERE sm.user_id = :uid)
  )
ORDER BY s.name
"""

_ALL_ORG_SITES_SQL = """
SELECT id, name, project_id
FROM sites
WHERE organization_id = :org
  AND status = 'active'
ORDER BY name
"""


def _digits(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def _build_engine():
    # SQLAlchemy imported lazily to avoid the platform/ shadow-package issue
    # during test collection (see pyproject notes in the repo root).
    from sqlalchemy.ext.asyncio import create_async_engine

    host = os.environ.get("MESIRI_POSTGRES__HOST", "localhost")
    port = os.environ.get("MESIRI_POSTGRES__PORT", "5432")
    user = os.environ.get("MESIRI_POSTGRES__USER", "mesiri")
    password = os.environ.get("MESIRI_POSTGRES__PASSWORD", "mesiri_local_dev")
    database = os.environ.get("MESIRI_POSTGRES__DATABASE", "mesiri")
    dsn = f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{database}"
    return create_async_engine(dsn, echo=False, pool_pre_ping=True)


class PostgresActorReader:
    """Satisfies the ActorReader Protocol by querying the backend control-plane.

    Resolves a WhatsApp sender to their ActorIdentity in a single round-trip
    (user + org JOIN) followed by two additional queries for projects and sites.
    All SQL is tenant-scoped on organization_id.

    Lifecycle: create once at process startup; the underlying engine maintains
    a connection pool for the process lifetime. The engine is built lazily on
    the first query so unit tests that never make DB calls don't need SQLAlchemy.
    """

    def __init__(self, engine=None) -> None:
        # None → built on first resolve call (lazy so unit tests don't need sqlalchemy)
        self._engine = engine

    def _get_engine(self):
        if self._engine is None:
            self._engine = _build_engine()
        return self._engine

    async def resolve_by_whatsapp_id(self, wa_id: str) -> ActorIdentity | None:
        from sqlalchemy import text

        digits = _digits(wa_id)
        if not digits:
            return None

        async with self._get_engine().connect() as conn:
            # ----------------------------------------------------------------
            # 1. Resolve the user + organization in one query.
            # ----------------------------------------------------------------
            # u.status = 'active' excludes a deactivated/suspended user (see
            # users/router.py's PATCH /users/{id}/status) from resolving at
            # all -- without it, this query only ever checked org status,
            # so deactivating a user from the dashboard had zero effect on
            # their WhatsApp access: they'd still resolve to a full
            # ActorIdentity and reach whoami, the project/site pickers, and
            # report recording. Falling through to `row is None` below reuses
            # the existing "unregistered sender" reply -- no new branch
            # needed, and no distinct wording that would tell a deactivated
            # user *why* they were locked out.
            row = (
                (
                    await conn.execute(
                        text(
                            "SELECT u.id, u.full_name, u.role, u.organization_id,"
                            "       u.access_policy, o.name AS org_name, o.status AS org_status, "
                            "       o.trial_ends_at AS org_trial_ends_at "
                            "FROM users u "
                            "LEFT JOIN organizations o ON o.id = u.organization_id "
                            "WHERE u.whatsapp_number IS NOT NULL "
                            "  AND regexp_replace(u.whatsapp_number, '\\D', '', 'g') = :d "
                            # lower(): the control panel's reactivate wrote
                            # "Active" (capitalized) while users are
                            # stored lowercase, so a case-sensitive match silently
                            # failed and the sender was told their number
                            # wasn't recognized. Reactivating someone locked
                            # them out of WhatsApp entirely.
                            "  AND lower(u.status) = 'active' "
                            "LIMIT 1"
                        ),
                        {"d": digits},
                    )
                )
                .mappings()
                .first()
            )

            if row is None:
                return None

            org_id = row["organization_id"]
            user_id = str(row["id"])
            access_policy = row["access_policy"] or {}
            # access_policy is a live standing bypass here, same as an
            # org-wide role -- NOT materialized as project_members rows (see
            # mesiri/authorization/roles.py). A project created after this grant
            # is made must still be visible without re-saving the grant.
            org_wide = is_org_wide(row["role"], access_policy)

            # ----------------------------------------------------------------
            # 2. Projects THIS USER can reach -- not every project in the org.
            #
            # This used to be a bare `WHERE organization_id = :org`, which made
            # every reply built from ActorIdentity (whoami, the project picker,
            # the site picker, and the actor_profile injected into the planner
            # prompt) show every project in the organization to every member of
            # it, regardless of whether access had been granted in the
            # dashboard. Membership is the filter now, matching what
            # AuthorizationService already enforces on the REST side.
            # ----------------------------------------------------------------
            project_rows: list = []
            site_rows: list = []

            if org_id is not None:
                params = {"org": str(org_id), "uid": user_id}
                project_rows = (
                    (
                        await conn.execute(
                            text(_ALL_ORG_PROJECTS_SQL if org_wide else _MEMBER_PROJECTS_SQL),
                            {"org": str(org_id)} if org_wide else params,
                        )
                    )
                    .mappings()
                    .all()
                )

                # ------------------------------------------------------------
                # 3. Sites the user can reach, from the control-plane sites
                #    table. Falls back gracefully if the migration hasn't run.
                # ------------------------------------------------------------
                try:
                    site_rows = (
                        (
                            await conn.execute(
                                text(_ALL_ORG_SITES_SQL if org_wide else _MEMBER_SITES_SQL),
                                {"org": str(org_id)} if org_wide else params,
                            )
                        )
                        .mappings()
                        .all()
                    )
                except Exception:  # noqa: BLE001 — table may not exist yet
                    site_rows = []

        return ActorIdentity(
            user_id=str(row["id"]),
            full_name=row["full_name"],
            role=str(row["role"]),
            organization_id=str(org_id) if org_id is not None else None,
            org_name=row["org_name"],
            # lifecycle.is_operational: active, or a trial that hasn't
            # ended (SS-02). Case-insensitive, so a row written "Active"
            # before migration 0463 doesn't silently suspend a tenant.
            org_active=is_operational(
                row["org_status"], row.get("org_trial_ends_at"), datetime.now(UTC)
            )
            if row["org_status"] is not None
            else False,
            projects=[
                ProjectSummary(
                    id=str(p["id"]),
                    name=p["name"],
                    location=p.get("location"),
                    code=p.get("code"),
                    status=p.get("status"),
                    progress=p.get("progress"),
                    open_issues=p.get("open_issues"),
                )
                for p in project_rows
            ],
            sites=[
                SiteSummary(
                    id=str(s["id"]),
                    name=s["name"],
                    project_id=str(s["project_id"]) if s.get("project_id") else None,
                )
                for s in site_rows
            ],
        )

    async def resolve_whatsapp_id_by_user_id(self, user_id: str) -> str | None:
        """The reverse of resolve_by_whatsapp_id -- #9 Notifications needs
        this to turn a notification's recipient_user_id (a canonical user,
        resolved on the backend side which has no notion of WhatsApp
        numbers) into the wa_id WhatsAppSender actually sends to. Returns
        None for a user with no whatsapp_number on file or who is not
        active -- same exclusion reasoning as resolve_by_whatsapp_id above,
        a deactivated user must not receive a notification either."""
        import uuid

        from sqlalchemy import text

        try:
            uid = uuid.UUID(user_id)
        except (TypeError, ValueError):
            return None

        async with self._get_engine().connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT whatsapp_number FROM users "
                        "WHERE id = :id AND whatsapp_number IS NOT NULL "
                        "AND lower(status) = 'active'"
                    ),
                    {"id": uid},
                )
            ).mappings().first()
        return str(row["whatsapp_number"]) if row else None
