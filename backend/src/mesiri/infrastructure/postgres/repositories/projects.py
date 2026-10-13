"""PostgreSQL implementation of project repository."""

from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.application.projects.dtos import ProjectDTO
from mesiri.application.projects.repository import ProjectRepository


class PostgresProjectRepository(ProjectRepository):
    """PostgreSQL implementation of project repository.

    Queries the projects table according to provided access scope.
    Does not make authorization decisions.
    """

    def __init__(self, conn: AsyncConnection):
        """Initialize with database connection."""
        self._conn = conn

        # Define projects table structure
        self._projects = sa.Table(
            "projects",
            sa.MetaData(),
            sa.Column("id", sa.UUID(as_uuid=True)),
            sa.Column("organization_id", sa.UUID(as_uuid=True)),
            sa.Column("name", sa.String),
            sa.Column("code", sa.String),
            sa.Column("location", sa.String),
            sa.Column("client", sa.String),
            sa.Column("description", sa.String),
            sa.Column("status", sa.String),
            sa.Column("progress", sa.Integer),
            sa.Column("open_issues", sa.Integer),
            sa.Column("reporting_timezone", sa.String),
            sa.Column("reporting_cutoff_time", sa.String),
            sa.Column("auto_generate_dpr", sa.Boolean),
            sa.Column("dpr_send_deadline", sa.String),
            sa.Column("required_report_types", sa.JSON),
        )

    async def list_projects_by_scope(
        self,
        organization_id: UUID,
        *,
        all_projects: bool,
        project_ids: set[UUID] | None = None,
    ) -> list[ProjectDTO]:
        """List projects according to access scope.

        Always filters by organization_id for tenant isolation.
        If all_projects=False, additionally filters by project_ids.

        CRITICAL EMPTY-SCOPE SAFETY:
        If all_projects=False and project_ids is empty, returns empty list
        immediately without querying database. This prevents empty custom
        access scope from accidentally exposing all org projects.
        """
        # Safety check: empty custom scope returns zero projects
        if not all_projects and (project_ids is None or len(project_ids) == 0):
            return []

        # Build query with organization filter
        query = sa.select(
            self._projects.c.id,
            self._projects.c.organization_id,
            self._projects.c.name,
            self._projects.c.code,
            self._projects.c.location,
            self._projects.c.client,
            self._projects.c.description,
            self._projects.c.status,
            self._projects.c.progress,
            self._projects.c.open_issues,
            self._projects.c.reporting_timezone,
            self._projects.c.reporting_cutoff_time,
            self._projects.c.auto_generate_dpr,
            self._projects.c.dpr_send_deadline,
            self._projects.c.required_report_types,
        ).where(self._projects.c.organization_id == organization_id)

        # Add project ID filter for custom access scope
        if not all_projects and project_ids:
            query = query.where(self._projects.c.id.in_(project_ids))

        # Order by name for deterministic results
        query = query.order_by(self._projects.c.name)

        # Execute query
        result = await self._conn.execute(query)
        rows = result.fetchall()

        # Map to DTOs
        return [
            ProjectDTO(
                id=row.id,
                organization_id=row.organization_id,
                name=row.name,
                code=row.code,
                location=row.location,
                client=row.client,
                description=row.description,
                status=row.status or "on_track",
                progress=row.progress or 0,
                open_issues=row.open_issues or 0,
                reporting_timezone=row.reporting_timezone or "UTC",
                reporting_cutoff_time=row.reporting_cutoff_time or "18:00",
                auto_generate_dpr=bool(row.auto_generate_dpr),
                dpr_send_deadline=row.dpr_send_deadline or "21:00",
                required_report_types=row.required_report_types or None,
            )
            for row in rows
        ]
