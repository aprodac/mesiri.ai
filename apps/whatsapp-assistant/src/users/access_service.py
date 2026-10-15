"""Setting a user's project/site access — the one implementation.

Two surfaces grant access: the web dashboard (a tenant admin editing their
own org, scoped by the JWT's `org` claim) and the control panel (a platform
admin editing any org, scoped by an explicit org_id in the path). They must
apply identical rules, because the result decides which project a WhatsApp
report is filed against and what the dashboard lets someone read and write.

Duplicating the logic per surface is exactly how the org-wide role rule
ended up written out five times with one copy silently wrong (see
mesiri/authorization/roles.py). So it lives here once, and both routers
call it.

Three things happen together, and all three matter:

  1. ``users.access_policy`` is written — still read by GET /me, and read
     live as the org-wide bypass for a non-admin (roles.policy_is_org_wide).
  2. ``project_members`` / ``site_members`` are fully replaced — this is
     what AuthorizationService and the WhatsApp context resolver actually
     consult (migration 0350). Writing only access_policy made an earlier
     version of this a no-op: the dashboard showed the change while the
     user's real access was untouched.

"all_projects" deliberately writes zero project_members rows: it is a live
standing bypass, so a project created after the grant is still reachable
without re-saving it.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from fastapi import HTTPException
from pydantic import BaseModel

# Table shims mirror the house style used by each router (see users/router.py
# and projects/router.py) -- only the columns this module touches.
_users = sa.Table(
    "users",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
    sa.Column("organization_id", sa.UUID(as_uuid=True)),
    sa.Column("role", sa.String),
    sa.Column("access_policy", sa.JSON),
)

_projects = sa.Table(
    "projects",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
    sa.Column("organization_id", sa.UUID(as_uuid=True)),
)

_sites = sa.Table(
    "sites",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
    sa.Column("organization_id", sa.UUID(as_uuid=True)),
    sa.Column("project_id", sa.UUID(as_uuid=True)),
)

_project_members = sa.Table(
    "project_members",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
    sa.Column("project_id", sa.UUID(as_uuid=True)),
    sa.Column("user_id", sa.UUID(as_uuid=True)),
    sa.Column("role", sa.String),
    sa.Column("site_access_mode", sa.String),
)

_site_members = sa.Table(
    "site_members",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
    sa.Column("site_id", sa.UUID(as_uuid=True)),
    sa.Column("user_id", sa.UUID(as_uuid=True)),
)

ALL_PROJECTS = "all_projects"
CUSTOM_PROJECTS = "custom_projects"
DEFAULT_ACCESS_POLICY: dict = {"mode": CUSTOM_PROJECTS, "projects": []}


class AccessPolicy(BaseModel):
    mode: str
    projects: list[dict] | None = None


def as_uuid(value: object, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {field}") from exc


async def validate_access_policy(conn, org_id, policy: AccessPolicy) -> None:
    """Reject anything that names a project or site outside `org_id`.

    Cross-tenant leakage is the risk being closed here: without this a
    caller could grant a user access to another organization's project by
    id.
    """
    if policy.mode not in (ALL_PROJECTS, CUSTOM_PROJECTS):
        raise HTTPException(
            status_code=400, detail="mode must be 'all_projects' or 'custom_projects'"
        )

    project_grants = policy.projects or []
    if policy.mode == ALL_PROJECTS and not project_grants:
        return

    project_ids: set[uuid.UUID] = set()
    site_ids_by_project: dict[uuid.UUID, set[uuid.UUID]] = {}

    for grant in project_grants:
        if not isinstance(grant, dict):
            raise HTTPException(status_code=400, detail="Invalid project access entry")

        project_id = as_uuid(grant.get("projectId"), "projectId")
        project_ids.add(project_id)

        site_access = grant.get("siteAccess") or {}
        if not isinstance(site_access, dict):
            raise HTTPException(status_code=400, detail="Invalid siteAccess")

        site_mode = site_access.get("mode")
        if site_mode not in ("all_sites", "custom_sites"):
            raise HTTPException(
                status_code=400, detail="siteAccess.mode must be 'all_sites' or 'custom_sites'"
            )

        if site_mode == "custom_sites":
            site_ids = site_access.get("siteIds") or []
            if not isinstance(site_ids, list):
                raise HTTPException(status_code=400, detail="siteIds must be a list")
            site_ids_by_project[project_id] = {as_uuid(s, "siteId") for s in site_ids}

    if not project_ids:
        return

    project_result = await conn.execute(
        sa.select(_projects.c.id).where(
            _projects.c.organization_id == org_id,
            _projects.c.id.in_(project_ids),
        )
    )
    found_project_ids = {row.id for row in project_result.fetchall()}
    if found_project_ids != project_ids:
        raise HTTPException(status_code=400, detail="Project access contains unknown project")

    site_ids = {s for ids in site_ids_by_project.values() for s in ids}
    if not site_ids:
        return

    site_result = await conn.execute(
        sa.select(_sites.c.id, _sites.c.project_id).where(
            _sites.c.organization_id == org_id,
            _sites.c.id.in_(site_ids),
        )
    )
    found_sites = {row.id: row.project_id for row in site_result.fetchall()}
    if set(found_sites) != site_ids:
        raise HTTPException(status_code=400, detail="Site access contains unknown site")

    for project_id, expected_site_ids in site_ids_by_project.items():
        for site_id in expected_site_ids:
            if found_sites[site_id] != project_id:
                raise HTTPException(
                    status_code=400, detail="Site access contains site outside project"
                )


async def apply_access_policy(
    conn,
    *,
    user_id: uuid.UUID,
    org_id,
    user_role: str,
    policy: AccessPolicy,
) -> None:
    """Write the policy and rebuild the user's membership rows.

    Caller owns the transaction. WhatsApp reads these rows directly, so the
    change applies to the next message.
    """
    await validate_access_policy(conn, org_id, policy)

    await conn.execute(
        _users.update()
        .where(_users.c.id == user_id, _users.c.organization_id == org_id)
        .values(access_policy=policy.model_dump())
    )

    # Full replace: a user's grants are a set, and removing a project has to
    # work as reliably as adding one.
    existing = await conn.execute(
        sa.select(_project_members.c.project_id).where(_project_members.c.user_id == user_id)
    )
    project_ids_to_clear = [r.project_id for r in existing.fetchall()]
    if project_ids_to_clear:
        await conn.execute(
            _site_members.delete().where(
                _site_members.c.user_id == user_id,
                _site_members.c.site_id.in_(
                    sa.select(_sites.c.id).where(_sites.c.project_id.in_(project_ids_to_clear))
                ),
            )
        )
    await conn.execute(_project_members.delete().where(_project_members.c.user_id == user_id))

    # ALL_PROJECTS writes no rows on purpose -- the bypass is read live from
    # access_policy. Clearing the old explicit grants above is correct: the
    # bypass supersedes them.
    if policy.mode != CUSTOM_PROJECTS:
        return

    for grant in policy.projects or []:
        project_id = as_uuid(grant["projectId"], "projectId")
        site_access = grant.get("siteAccess") or {}
        site_mode = site_access.get("mode", "all_sites")
        await conn.execute(
            _project_members.insert().values(
                id=uuid.uuid4(),
                project_id=project_id,
                user_id=user_id,
                role=user_role,
                site_access_mode=site_mode,
            )
        )
        if site_mode == "custom_sites":
            for site_id in site_access.get("siteIds") or []:
                await conn.execute(
                    _site_members.insert().values(
                        id=uuid.uuid4(),
                        site_id=as_uuid(site_id, "siteId"),
                        user_id=user_id,
                    )
                )
