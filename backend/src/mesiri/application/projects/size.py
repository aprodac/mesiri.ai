"""PS-05 (migration 0564): a project's kind and size, for both project routers (the backend's and the assistant's,
which production serves), so the two cannot drift.

``project_type`` groups projects (reports, cost per sq ft by kind); ``built_up_area_sqft`` gives cost per sq ft;
``floors`` the height. Empty means not said, never zero.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

#: PS-05: what kind of building a project is (free text is refused: reports and cost per sq ft group by it).
PROJECT_TYPES = ("villa", "apartment", "commercial", "industrial", "institutional", "infrastructure", "interior",
                 "renovation", "other")


class ProjectSize(BaseModel):
    """PS-05: the project's kind and size. Empty means not said (never zero)."""

    projectType: str | None = None
    builtUpAreaSqft: float | None = Field(default=None, gt=0, le=100_000_000)
    floors: int | None = Field(default=None, ge=1, le=200)
    #: PS phase 2 (0565): site and office overheads as a % of the BOQ budget cost.
    overheadPct: float | None = Field(default=None, ge=0, le=100)

    @field_validator("projectType")
    @classmethod
    def _known_type(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip().lower()
        if value not in PROJECT_TYPES:
            raise ValueError(f"projectType is one of {', '.join(PROJECT_TYPES)}")
        return value


def size_values(body: ProjectSize, *, sent_only: bool) -> dict:
    """The size columns a create or update writes (an update writes only what was sent)."""
    fields = body.model_fields_set if sent_only else {"projectType", "builtUpAreaSqft", "floors", "overheadPct"}
    out = {}
    if "projectType" in fields:
        out["project_type"] = body.projectType
    if "builtUpAreaSqft" in fields:
        out["built_up_area_sqft"] = body.builtUpAreaSqft
    if "floors" in fields:
        out["floors"] = body.floors
    if "overheadPct" in fields:
        out["overhead_pct"] = body.overheadPct
    return out


def size_of(row: Any) -> dict:
    area = getattr(row, "built_up_area_sqft", None)
    overhead = getattr(row, "overhead_pct", None)
    return {"project_type": getattr(row, "project_type", None),
            "built_up_area_sqft": float(area) if area is not None else None,
            "floors": getattr(row, "floors", None),
            "overhead_pct": float(overhead) if overhead is not None else None}
