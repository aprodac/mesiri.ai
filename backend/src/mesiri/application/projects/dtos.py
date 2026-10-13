"""Data transfer objects for the projects application layer.

DTOs represent internal project data structures used by the application
layer. They are distinct from HTTP response schemas and database models.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class ProjectDTO:
    """Internal project data transfer object.

    Represents a project as returned from the repository layer.
    Contains database-native status values (on_track, at_risk, critical).
    """

    id: UUID
    organization_id: UUID
    name: str
    code: str | None
    location: str | None
    client: str | None
    description: str | None
    status: str  # Database value: on_track | at_risk | critical
    progress: int
    open_issues: int
    reporting_timezone: str = "UTC"
    reporting_cutoff_time: str = "18:00"
    auto_generate_dpr: bool = False
    dpr_send_deadline: str = "21:00"
    required_report_types: list[str] | None = None
