"""Response shapes for the Progress (Daily Reporting) REST API."""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from .validation import ISSUE_SEVERITIES, ISSUE_TYPES


class ActivityQuantityResponse(BaseModel):
    id: uuid.UUID
    work_type: str | None = None
    unit_id: uuid.UUID | None = None
    unit: str | None = None
    quantity: Decimal
    measurement_type: str


class ProgressUpdateResponse(BaseModel):
    id: uuid.UUID
    occurred_at: datetime.datetime
    update_kind: str
    narrative: str | None = None
    quantity: Decimal | None = None
    unit_id: uuid.UUID | None = None
    unit: str | None = None
    # Set when this row was created by correct_progress_update (ADR-D14) to
    # fix a wrong quantity/unit/narrative on the row it points at -- that
    # old row is never edited or deleted, so both remain visible here.
    supersedes_id: uuid.UUID | None = None
    reported_by_user_id: uuid.UUID | None = None
    source: str
    created_at: datetime.datetime


class ActivityAttachmentResponse(BaseModel):
    id: uuid.UUID
    media_object_key: str
    attachment_type: str
    mime_type: str | None = None
    caption: str | None = None
    ai_caption: str | None = None
    role: str | None = None
    captured_at: datetime.datetime | None = None
    created_at: datetime.datetime


class ActivitySummaryResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    project_id: uuid.UUID
    site_id: uuid.UUID
    work_package_id: uuid.UUID | None = None
    location_id: uuid.UUID | None = None
    work_type: str | None = None
    activity_date: datetime.date
    started_at: datetime.time | None = None
    ended_at: datetime.time | None = None
    status: str
    narrative: str | None = None
    contractor: str | None = None
    reported_by_user_id: uuid.UUID | None = None
    source: str
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ActivitiesListResponse(BaseModel):
    items: list[ActivitySummaryResponse]
    total: int


class ActivityDetailResponse(ActivitySummaryResponse):
    quantities: list[ActivityQuantityResponse]
    progress_updates: list[ProgressUpdateResponse]
    attachments: list[ActivityAttachmentResponse]


class SiteIssueResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    project_id: uuid.UUID
    site_id: uuid.UUID
    activity_id: uuid.UUID | None = None
    work_package_id: uuid.UUID | None = None
    location_id: uuid.UUID | None = None
    issue_type: str
    severity: str
    narrative: str | None = None
    delay_duration_minutes: int | None = None
    occurred_at: datetime.datetime
    resolved_at: datetime.datetime | None = None
    status: str
    resolution_notes: str | None = None
    assigned_user_id: uuid.UUID | None = None
    #: GM-06: who is on it (name) and by when they said it would be sorted.
    assigned_user_name: str | None = None
    due_on: datetime.date | None = None
    reported_by_user_id: uuid.UUID | None = None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class SiteIssuesListResponse(BaseModel):
    items: list[SiteIssueResponse]
    total: int


class CreateSiteIssueRequest(BaseModel):
    project_id: uuid.UUID
    site_id: uuid.UUID
    # WA-119: the valid values are shown in the schema; validation is unchanged (400 on another value).
    issue_type: str = Field(json_schema_extra={"enum": sorted(ISSUE_TYPES)})
    severity: str = Field(json_schema_extra={"enum": sorted(ISSUE_SEVERITIES)})
    narrative: str | None = None
    delay_duration_minutes: int | None = None


class ResolveSiteIssueRequest(BaseModel):
    resolution_notes: str | None = None


class WontFixSiteIssueRequest(BaseModel):
    resolution_notes: str | None = None


class OperationsSettingsResponse(BaseModel):
    auto_approve_dprs: bool = False
    require_photo_evidence: bool = True
    allow_overrun_quantities: bool = False
    default_shift: str = "DAY"
    whatsapp_nudge_hours: int = 18
    auto_flag_weather_delays: bool = True
    supervisor_phone_numbers: list[str] = []


class UpdateOperationsSettingsRequest(BaseModel):
    auto_approve_dprs: bool | None = None
    require_photo_evidence: bool | None = None
    allow_overrun_quantities: bool | None = None
    default_shift: str | None = None
    whatsapp_nudge_hours: int | None = None
    auto_flag_weather_delays: bool | None = None
    supervisor_phone_numbers: list[str] | None = None


class CorrectActivityRequest(BaseModel):
    """ADR-D14: only the fields listed here (matching
    PostgresProgressReadRepository._CORRECTABLE_ACTIVITY_FIELDS) may be
    corrected; anything left unset is untouched. `reason` is optional --
    written to the audit trail when given, but never required the way a
    void's reason is (a correction is inherently self-explaining via its
    old/new values; a void of an entire record benefits from a stated
    reason)."""

    work_type: str | None = None
    location_id: uuid.UUID | None = None
    contractor: str | None = None
    narrative: str | None = None
    activity_date: datetime.date | None = None
    reason: str | None = None


class VoidActivityRequest(BaseModel):
    reason: str


class CorrectProgressUpdateRequest(BaseModel):
    quantity: Decimal | None = None
    unit_id: uuid.UUID | None = None
    narrative: str | None = None
    reason: str | None = None


class VoidProgressUpdateRequest(BaseModel):
    reason: str


class ActivityCorrectionResponse(BaseModel):
    id: uuid.UUID
    activity_id: uuid.UUID
    field_name: str
    old_value: Any = None
    new_value: Any = None
    reason: str | None = None
    corrected_by_user_id: uuid.UUID | None = None
    correlation_id: str | None = None
    created_at: datetime.datetime


class ActivityCorrectionsListResponse(BaseModel):
    items: list[ActivityCorrectionResponse]
