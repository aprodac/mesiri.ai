"""The superadmin's companies list: status and setup progress (SA-02).

One read for both admin routers (the assistant's, which is deployed, and the
backend's), so the list can't answer differently depending on which serves it.

Per company:

    effective_status   trial / active / expired / suspended, by the one
                       lifecycle rule (a trial past its end reads expired)
    trial_days_left    whole days, for a company that is still on trial
    setup              how far the company got with Mesiri:
                         has_team           someone active besides the owner
                         has_site           at least one site
                         first_update_at    first confirmed site record: work
                                            reported (activities) or a material
                                            or issue (timeline_entries)
                         first_dpr_sent_at  first report sent (PUBLISHED)
                         has_logo           a letterhead logo is uploaded
                         report_time_set    a project's report time was
                                            changed from the default, or the
                                            owner answered the report-time
                                            question (setup_progress, SS-14:
                                            on WhatsApp or the dashboard)

Read-only, one query; at our number of companies the per-company subqueries
cost nothing worth caching. The same setup block is the owner's
getting-started checklist in the dashboard (SS-07, `company_setup`) and tells
the WhatsApp setup questions (SS-14) what is still missing, so all three agree
on what "done" means.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

import sqlalchemy as sa

from mesiri.domains.organizations import lifecycle

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection


@dataclass(frozen=True, slots=True)
class SetupProgress:
    has_team: bool
    has_site: bool
    first_update_at: dt.datetime | None
    first_dpr_sent_at: dt.datetime | None
    has_logo: bool = False
    report_time_set: bool = False


@dataclass(frozen=True, slots=True)
class CompanyOverview:
    id: uuid.UUID
    name: str
    deployment_type: str
    db_route: str
    status: str
    effective_status: str
    trial_started_at: dt.datetime | None
    trial_ends_at: dt.datetime | None
    trial_days_left: int | None
    converted_at: dt.datetime | None
    signup_source: str
    created_at: dt.datetime | None
    updated_at: dt.datetime | None
    setup: SetupProgress
    # Owner's letterhead photos the Mesiri team hasn't finished (SA-09).
    open_branding_requests: int = 0
    # SA-10: the owner asked to continue with Mesiri (from SS-08), not yet
    # answered by a convert / extend; and when the request came.
    open_continue_requests: int = 0
    continue_requested_at: str | None = None
    # SA-10: trial ended more than retention_days_after_expiry ago and never
    # converted. A flag only: nothing is deleted automatically.
    eligible_for_deletion: bool = False


# A project's report times when nobody has changed them (the column defaults,
# migrations 0260 / 0469).
DEFAULT_CUTOFF_TIME = "18:00"
DEFAULT_SEND_TIME = "21:00"

_SELECT = """
    SELECT o.id, o.name, o.deployment_type, o.db_route, o.status,
           o.trial_started_at, o.trial_ends_at, o.converted_at, o.signup_source,
           o.created_at, o.updated_at,
           (SELECT count(*) FROM users u
             WHERE u.organization_id = o.id AND lower(u.status) = 'active') AS active_users,
           EXISTS (SELECT 1 FROM sites s WHERE s.organization_id = o.id) AS has_site,
           LEAST(
             (SELECT min(a.created_at) FROM activities a
               WHERE a.organization_id = o.id AND a.deleted_at IS NULL),
             (SELECT min(t.occurred_at) FROM timeline_entries t
               WHERE t.organization_id = o.id)
           ) AS first_update_at,
           (SELECT min(d.updated_at) FROM daily_reports d
             WHERE d.organization_id = o.id AND d.status = 'PUBLISHED') AS first_dpr_sent_at,
           EXISTS (SELECT 1 FROM organization_settings st
             WHERE st.organization_id = o.id AND st.key = 'branding'
               AND st.value ->> 'logo_object_key' IS NOT NULL) AS has_logo,
           (EXISTS (SELECT 1 FROM projects p
              WHERE p.organization_id = o.id
                AND (p.reporting_cutoff_time <> :default_cutoff
                     OR p.dpr_send_deadline <> :default_send))
            OR EXISTS (SELECT 1 FROM organization_settings st
              WHERE st.organization_id = o.id AND st.key = 'setup_progress'
                AND st.value -> 'report_time' ->> 'state' = 'answered')) AS report_time_set,
           (SELECT count(*) FROM organization_settings st,
                   jsonb_array_elements(
                     CASE WHEN jsonb_typeof(st.value) = 'array' THEN st.value ELSE '[]' END
                   ) AS r
             WHERE st.organization_id = o.id AND st.key = 'branding_requests'
               AND r ->> 'status' = 'open') AS open_branding_requests,
           (SELECT count(*) FROM organization_settings st,
                   jsonb_array_elements(
                     CASE WHEN jsonb_typeof(st.value) = 'array' THEN st.value ELSE '[]' END
                   ) AS r
             WHERE st.organization_id = o.id AND st.key = 'continue_requests'
               AND r ->> 'status' = 'open') AS open_continue_requests,
           (SELECT max(r ->> 'created_at') FROM organization_settings st,
                   jsonb_array_elements(
                     CASE WHEN jsonb_typeof(st.value) = 'array' THEN st.value ELSE '[]' END
                   ) AS r
             WHERE st.organization_id = o.id AND st.key = 'continue_requests'
               AND r ->> 'status' = 'open') AS continue_requested_at
    FROM organizations o
"""
_DEFAULTS = {"default_cutoff": DEFAULT_CUTOFF_TIME, "default_send": DEFAULT_SEND_TIME}
DEFAULT_RETENTION_DAYS = 30


async def _retention_days(conn: AsyncConnection) -> int:
    """retention_days_after_expiry from the trial policy (SS-08 setting)."""
    from mesiri.domains.organizations.platform_settings import TRIAL_POLICY
    from mesiri.infrastructure.postgres.repositories.platform_settings import (
        PostgresPlatformSettingsRepository,
    )

    policy = await PostgresPlatformSettingsRepository(conn).get(TRIAL_POLICY)
    try:
        return int((policy or {}).get("retention_days_after_expiry") or DEFAULT_RETENTION_DAYS)
    except (TypeError, ValueError):
        return DEFAULT_RETENTION_DAYS
_QUERY = sa.text(_SELECT + "ORDER BY o.created_at DESC NULLS LAST, o.name")
_ONE_QUERY = sa.text(_SELECT + "WHERE o.id = :organization_id")


def to_overview(
    row: sa.RowMapping, now: dt.datetime, *, retention_days: int = DEFAULT_RETENTION_DAYS
) -> CompanyOverview:
    """One query row as the list shows it. Pure, so testable without a database."""
    effective = lifecycle.effective_status(row["status"], row["trial_ends_at"], now)
    eligible = (
        effective == lifecycle.EXPIRED
        and row["converted_at"] is None
        and row["trial_ends_at"] is not None
        and now - row["trial_ends_at"] > dt.timedelta(days=retention_days)
    )
    days_left = (
        lifecycle.trial_days_left(row["trial_ends_at"], now)
        if effective == lifecycle.TRIAL
        else None
    )
    return CompanyOverview(
        id=row["id"],
        name=row["name"],
        deployment_type=row["deployment_type"],
        db_route=row["db_route"],
        status=row["status"],
        effective_status=effective,
        trial_started_at=row["trial_started_at"],
        trial_ends_at=row["trial_ends_at"],
        trial_days_left=days_left,
        converted_at=row["converted_at"],
        signup_source=row["signup_source"] or "superadmin",
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        open_branding_requests=int(row.get("open_branding_requests") or 0),
        open_continue_requests=int(row.get("open_continue_requests") or 0),
        continue_requested_at=row.get("continue_requested_at"),
        eligible_for_deletion=eligible,
        setup=SetupProgress(
            # The owner alone isn't a team.
            has_team=(row["active_users"] or 0) >= 2,
            has_site=bool(row["has_site"]),
            first_update_at=row["first_update_at"],
            first_dpr_sent_at=row["first_dpr_sent_at"],
            has_logo=bool(row.get("has_logo")),
            report_time_set=bool(row.get("report_time_set")),
        ),
    )


async def list_companies(
    conn: AsyncConnection, *, now: dt.datetime | None = None
) -> list[CompanyOverview]:
    """Every company, newest first, with its status and setup progress."""
    now = now or dt.datetime.now(dt.UTC)
    rows = (await conn.execute(_QUERY, _DEFAULTS)).mappings().all()
    retention = await _retention_days(conn)
    return [to_overview(row, now, retention_days=retention) for row in rows]


async def company_setup(
    conn: AsyncConnection, organization_id: uuid.UUID, *, now: dt.datetime | None = None
) -> CompanyOverview | None:
    """One company's status and setup progress, or None if it doesn't exist."""
    now = now or dt.datetime.now(dt.UTC)
    row = (
        (await conn.execute(_ONE_QUERY, {**_DEFAULTS, "organization_id": organization_id}))
        .mappings()
        .first()
    )
    if row is None:
        return None
    return to_overview(row, now, retention_days=await _retention_days(conn))
