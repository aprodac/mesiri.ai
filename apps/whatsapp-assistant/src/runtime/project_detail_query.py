"""Project team-size lookup for the project.detail_query workflow
("give me all details of this project").

Everything else that workflow needs (project/site name, code, location,
status, the site list) comes for free off `ActorIdentity.projects`/`.sites`
-- already resolved once per inbound message (see backend/postgres/actor.py)
-- and every operational rollup (open issues, labour, activities, stock,
spend) is composed from the existing runtime/*_query.py services. The one
genuinely new read is this: nothing in the codebase counts a project's
`project_members` rows today.

Same shape and justification as runtime/dpr_request_query.py: a plain async
method the assistant can call so a node/seed step never queries a
repository itself.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mesiri.infrastructure.postgres.database import PostgresDatabase


class ProjectDetailQueryService:
    def __init__(self, db: PostgresDatabase) -> None:
        self._db = db

    async def count_other_members(self, *, project_id: str, user_id: str) -> int | None:
        """Explicit project_members rows other than ``user_id``, to know whether
        anyone besides the sender is on the project ([111]: "doesn't have a team
        yet" was said to an admin who was on it). None when it cannot be read."""
        import sqlalchemy as sa

        try:
            proj_uuid, user_uuid = uuid.UUID(project_id), uuid.UUID(user_id)
        except (TypeError, ValueError):
            return None
        try:
            async with self._db.transaction() as conn:
                count = (
                    await conn.execute(
                        sa.text(
                            "SELECT count(*) FROM project_members "
                            "WHERE project_id = :project_id AND user_id <> :user_id"
                        ),
                        {"project_id": proj_uuid, "user_id": user_uuid},
                    )
                ).scalar_one()
        except Exception:  # noqa: BLE001 -- the offer is only a nudge
            return None
        return int(count)

    async def count_members(self, *, project_id: str) -> int:
        """Explicit project_members rows for this project. Deliberately NOT
        the same as "everyone who can reach this project" -- an org-wide
        role or an access_policy 'all_projects' bypass never gets a
        project_members row (see mesiri.authorization.roles.is_org_wide),
        so this is a lower bound ("N assigned team members"), not a claim
        about total reach. Good enough for a WhatsApp summary line; the
        dashboard's Members tab is the source of truth for exact access."""
        import sqlalchemy as sa

        try:
            proj_uuid = uuid.UUID(project_id)
        except (TypeError, ValueError):
            return 0

        async with self._db.transaction() as conn:
            count = (
                await conn.execute(
                    sa.text("SELECT count(*) FROM project_members WHERE project_id = :project_id"),
                    {"project_id": proj_uuid},
                )
            ).scalar_one()
        return int(count)

    async def list_members(self, *, organization_id: str, project_ids: list[str]) -> list[tuple[str, str, str]]:
        """(project_id, full name, role) of the people on ``project_ids`` (WA-84: "ente
        team-il aarokke und?"), read only, for the sender's own projects in their own
        company -- the dashboard's Members tab shows the same rows to any member."""
        import sqlalchemy as sa

        try:
            org = uuid.UUID(str(organization_id))
            ids = [uuid.UUID(str(p)) for p in project_ids]
        except (TypeError, ValueError):
            return []
        if not ids:
            return []
        async with self._db.transaction() as conn:
            rows = (
                await conn.execute(
                    sa.text(
                        "SELECT pm.project_id, u.full_name, pm.role FROM project_members pm "
                        "JOIN projects p ON p.id = pm.project_id "
                        "JOIN users u ON u.id = pm.user_id "
                        "WHERE p.organization_id = :org AND pm.project_id = ANY(:ids) "
                        "AND coalesce(u.status, 'active') NOT IN ('deleted', 'removed', 'disabled', 'inactive') "
                        "ORDER BY u.full_name"
                    ),
                    {"org": org, "ids": ids},
                )
            ).all()
        return [(str(r[0]), str(r[1] or "").strip() or "(no name)", str(r[2] or "")) for r in rows]
