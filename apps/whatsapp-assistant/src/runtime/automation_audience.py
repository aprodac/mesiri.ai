"""Resolves an automation's `audience` column into concrete recipient user
ids -- wiring layer only, composes the same membership rules
context/main_table_repositories.py and projects/router.py already use, no new
SQL concept.

Four audiences, four completely different shapes (see migration 0455's
module docstring for why `audience` is a discriminator, not a foreign key):

- SELF: the automation's own creator. No query needed.
- USERS: the row's own explicit `audience_user_ids`. No query needed.
- ROLE: every active user of that role reachable from the automation's
  scope (org-wide if no project_id, that project's members otherwise).
- NON_REPORTERS: SITE_ENGINEERs reachable from whichever sites
  ReportingComplianceQueryService found not-reported.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mesiri.infrastructure.postgres.database import PostgresDatabase

    from .reporting_compliance_query import ReportingComplianceQueryService


async def _active_users_with_role(
    db: PostgresDatabase, *, organization_id: str, project_id: str | None, role: str
) -> list[str]:
    import sqlalchemy as sa

    from mesiri.authorization.roles import is_org_wide

    org_uuid = uuid.UUID(organization_id)
    async with db.transaction() as conn:
        rows = (
            await conn.execute(
                sa.text(
                    "SELECT id, role, access_policy FROM users "
                    "WHERE organization_id = :org_id AND role = :role AND lower(status) = 'active'"
                ),
                {"org_id": org_uuid, "role": role},
            )
        ).mappings().all()
        if not project_id:
            return [str(row["id"]) for row in rows]

        proj_uuid = uuid.UUID(project_id)
        member_rows = (
            await conn.execute(
                sa.text(
                    "SELECT user_id FROM project_members WHERE project_id = :project_id"
                ),
                {"project_id": proj_uuid},
            )
        ).mappings().all()
        member_ids = {row["user_id"] for row in member_rows}

    return [
        str(row["id"])
        for row in rows
        if is_org_wide(row["role"], row["access_policy"]) or row["id"] in member_ids
    ]


async def _site_engineers_for_sites(
    db: PostgresDatabase, *, organization_id: str, site_ids: list[str]
) -> list[str]:
    """Every SITE_ENGINEER (org-wide, or an explicit project/site member)
    who can reach at least one of `site_ids` -- same "all_sites OR explicit
    site_members" rule apps/whatsapp-assistant/src/backend/postgres/
    actor.py's `_MEMBER_SITES_SQL` already applies to a single user; this is
    its set-wide, name-known-in-advance twin."""
    if not site_ids:
        return []
    import sqlalchemy as sa

    from mesiri.authorization.roles import is_org_wide

    org_uuid = uuid.UUID(organization_id)
    site_uuids = [uuid.UUID(s) for s in site_ids]
    async with db.transaction() as conn:
        engineer_rows = (
            await conn.execute(
                sa.text(
                    "SELECT id, role, access_policy FROM users "
                    "WHERE organization_id = :org_id AND role = 'SITE_ENGINEER' "
                    "AND lower(status) = 'active'"
                ),
                {"org_id": org_uuid},
            )
        ).mappings().all()
        org_wide_ids = {
            row["id"] for row in engineer_rows if is_org_wide(row["role"], row["access_policy"])
        }

        project_rows = (
            await conn.execute(
                sa.text("SELECT project_id FROM sites WHERE id = ANY(:site_ids)"),
                {"site_ids": site_uuids},
            )
        ).mappings().all()
        project_ids = {row["project_id"] for row in project_rows}

        all_sites_member_rows = (
            await conn.execute(
                sa.text(
                    "SELECT user_id FROM project_members "
                    "WHERE project_id = ANY(:project_ids) AND site_access_mode = 'all_sites'"
                ),
                {"project_ids": list(project_ids)},
            )
            if project_ids
            else None
        )
        all_sites_member_ids = (
            {row["user_id"] for row in all_sites_member_rows.mappings().all()}
            if all_sites_member_rows is not None
            else set()
        )

        explicit_rows = (
            await conn.execute(
                sa.text("SELECT user_id FROM site_members WHERE site_id = ANY(:site_ids)"),
                {"site_ids": site_uuids},
            )
        ).mappings().all()
        explicit_ids = {row["user_id"] for row in explicit_rows}

    reachable = org_wide_ids | all_sites_member_ids | explicit_ids
    return [str(row["id"]) for row in engineer_rows if row["id"] in reachable]


async def resolve_audience(
    *,
    db: PostgresDatabase,
    compliance_query: ReportingComplianceQueryService,
    automation: dict[str, Any],
) -> list[str]:
    """Returns recipient user id strings for one automation row. Never
    raises on a malformed row (missing audience_role, empty user list,
    etc.) -- an audience that resolves to nobody is a legitimate, if
    useless, outcome for the runner to skip, not a crash."""
    audience = automation["audience"]

    if audience == "SELF":
        return [str(automation["created_by"])]

    if audience == "USERS":
        return [str(u) for u in (automation.get("audience_user_ids") or [])]

    if audience == "ROLE":
        role = automation.get("audience_role")
        if not role:
            return []
        project_id = str(automation["project_id"]) if automation.get("project_id") else None
        return await _active_users_with_role(
            db,
            organization_id=str(automation["organization_id"]),
            project_id=project_id,
            role=role,
        )

    if audience == "NON_REPORTERS":
        import datetime

        from mesiri.application.automations.scheduling import local_now

        project_id = str(automation["project_id"]) if automation.get("project_id") else None
        report_date = local_now(
            timezone_name=automation.get("timezone") or "UTC",
            now_utc=datetime.datetime.now(datetime.UTC),
        ).date()
        result = await compliance_query.check(
            organization_id=str(automation["organization_id"]),
            project_id=project_id,
            report_date=report_date,
        )
        not_reported_site_ids = [s["site_id"] for s in result["sites"] if not s["reported"]]
        return await _site_engineers_for_sites(
            db,
            organization_id=str(automation["organization_id"]),
            site_ids=not_reported_site_ids,
        )

    return []
