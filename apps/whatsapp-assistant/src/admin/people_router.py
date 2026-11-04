"""Find a person across every company, for the control panel (SA-24).

A company's own Users tab lists only that company, so "where is this number?"
meant opening every company or writing SQL on the Database page. This route
answers it: a name, email or WhatsApp number in, every matching user out,
with the company they belong to.

The number is matched on its digits, the way the unique index matches it
(BE-04, migration 0483): "79077 93657", "+91 7907793657" and "917907793657"
all find the same person, including a deactivated or suspended one, whose
number still blocks a new signup. Read-only and platform-admin only.

SA-25: `/trials` answers "why is this number refused a trial?". A trial start is
kept in the audit log (`company.created`, status trial) and outlives the company,
so a number with no user can still be refused (one trial per number per
`trial_per_phone_days`); no screen showed that record before.
"""

from __future__ import annotations

import datetime as dt
import re
import uuid

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from admin.router import get_engine, organizations_table, users_table
from mesiri.domains.organizations.platform_settings import TRIAL_GUARDRAILS
from mesiri.domains.shared.auth import require_platform_admin
from mesiri.infrastructure.postgres.repositories.admin_audit import admin_audit_log
from mesiri.infrastructure.postgres.repositories.platform_settings import (
    PostgresPlatformSettingsRepository,
)

router = APIRouter(prefix="/admin/people", tags=["admin"])

#: Fewer characters than this match too much to be useful.
MIN_QUERY = 3
#: A number is searched once it has this many digits (the last 4 is how the panel shows one).
MIN_DIGITS = 4
#: An Indian mobile number without its country code.
NATIONAL_DIGITS = 10
LIMIT = 25

_DIGITS = sa.func.regexp_replace(users_table.c.whatsapp_number, r"\D", "", "g")


class PersonMatch(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str | None = None
    whatsapp_number: str | None = None
    role: str
    status: str
    organization_id: uuid.UUID | None = None
    #: None for a platform admin (no company).
    company: str | None = None


class TrialUse(BaseModel):
    """One free trial a number started (SA-25), whether or not its company still exists."""

    number: str | None = None
    company: str
    started_at: dt.datetime
    signup_source: str | None = None
    organization_id: uuid.UUID | None = None
    #: False once the company was deleted; the trial still counts.
    company_exists: bool
    #: When this number may start a new trial; None when the rule is off (0 days).
    new_trial_from: dt.datetime | None = None


def number_digits(q: str) -> str | None:
    """The digits a number is searched by, without the country code; None when too few."""
    digits = re.sub(r"\D", "", q)[-NATIONAL_DIGITS:]
    return digits if len(digits) >= MIN_DIGITS else None


def _like(text: str) -> str:
    """`text` as a contains-pattern, with LIKE's own wildcards taken literally."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def search_clause(q: str) -> sa.ColumnElement[bool] | None:
    """What `q` matches: name or email (contains, any case), or the number's digits.
    None when `q` is too short to search."""
    text = q.strip()
    if len(text) < MIN_QUERY:
        return None
    pattern = _like(text)
    clauses = [
        users_table.c.full_name.ilike(pattern, escape="\\"),
        users_table.c.email.ilike(pattern, escape="\\"),
    ]
    # A full number drops its country code, so "+91 79077 93657" also finds one saved as "7907793657".
    digits = number_digits(text)
    if digits:
        clauses.append(_DIGITS.like(f"%{digits}%"))
    return sa.or_(*clauses)


@router.get("/search", response_model=list[PersonMatch])
async def search_people(
    q: str = Query("", max_length=120),
    _admin: dict = Depends(require_platform_admin),
):
    """Every user whose name, email or WhatsApp number matches `q`, in any company."""
    clause = search_clause(q)
    if clause is None:
        return []
    statement = (
        sa.select(
            users_table.c.id,
            users_table.c.full_name,
            users_table.c.email,
            users_table.c.whatsapp_number,
            users_table.c.role,
            users_table.c.status,
            users_table.c.organization_id,
            organizations_table.c.name.label("company"),
        )
        .select_from(
            users_table.outerjoin(
                organizations_table, organizations_table.c.id == users_table.c.organization_id
            )
        )
        .where(clause)
        .order_by(users_table.c.full_name)
        .limit(LIMIT)
    )
    async with get_engine().connect() as conn:
        rows = (await conn.execute(statement)).fetchall()
    return [
        PersonMatch(
            id=row.id,
            full_name=row.full_name or "",
            email=row.email,
            whatsapp_number=row.whatsapp_number,
            role=row.role or "",
            status=row.status or "active",
            organization_id=row.organization_id,
            company=row.company,
        )
        for row in rows
    ]


_TRIAL_NUMBER = admin_audit_log.c.details["owner_whatsapp_number"].astext
_TRIAL_DIGITS = sa.func.regexp_replace(_TRIAL_NUMBER, r"\D", "", "g")


def trials_statement(digits: str) -> sa.Select:
    """Trial starts whose owner's number has these digits, newest first, with whether the
    company still exists (joined on the audit row's target, which outlives the company)."""
    return (
        sa.select(
            admin_audit_log.c.occurred_at,
            admin_audit_log.c.details["name"].astext.label("company"),
            _TRIAL_NUMBER.label("number"),
            admin_audit_log.c.details["signup_source"].astext.label("signup_source"),
            organizations_table.c.id.label("organization_id"),
        )
        .select_from(
            admin_audit_log.outerjoin(
                organizations_table,
                sa.cast(organizations_table.c.id, sa.String) == admin_audit_log.c.target_id,
            )
        )
        .where(
            admin_audit_log.c.action == "company.created",
            admin_audit_log.c.details["status"].astext == "trial",
            _TRIAL_DIGITS.like(f"%{digits}%"),
        )
        .order_by(admin_audit_log.c.occurred_at.desc())
        .limit(LIMIT)
    )


@router.get("/trials", response_model=list[TrialUse])
async def search_trials(
    q: str = Query("", max_length=120),
    _admin: dict = Depends(require_platform_admin),
):
    """SA-25: the free trials a number started, deleted companies included, and when it may
    start another. Empty unless `q` has at least MIN_DIGITS digits."""
    digits = number_digits(q)
    if digits is None:
        return []
    async with get_engine().connect() as conn:
        rows = (await conn.execute(trials_statement(digits))).fetchall()
        rules = await PostgresPlatformSettingsRepository(conn).get(TRIAL_GUARDRAILS)
    window = int(rules.get("trial_per_phone_days") or 0)
    return [
        TrialUse(
            number=row.number,
            company=row.company or "",
            started_at=row.occurred_at,
            signup_source=row.signup_source,
            organization_id=row.organization_id,
            company_exists=row.organization_id is not None,
            new_trial_from=row.occurred_at + dt.timedelta(days=window) if window else None,
        )
        for row in rows
    ]
