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
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from admin.router import get_engine, organizations_table, users_table
from mesiri.application.audit.record import record_admin_action
from mesiri.domains.audit import actions as audit
from mesiri.domains.audit.actions import actor_from_admin
from mesiri.domains.organizations.guardrails import MIN_TRIAL_LEFT
from mesiri.domains.organizations.platform_settings import TRIAL_GUARDRAILS
from mesiri.domains.shared.auth import require_platform_admin
from mesiri.infrastructure.postgres.repositories.admin_audit import (
    PostgresAdminAuditRepository,
    admin_audit_log,
    iso_moment,
)
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
    #: SA-26: a platform admin allowed a new trial after this one started (it no longer limits).
    allowed_at: dt.datetime | None = None
    #: SS-24: when the company was deleted (the Delete Tenant entry), if it was.
    deleted_at: dt.datetime | None = None
    #: SS-24: what was left of the trial at that delete, which a new signup carries on with;
    #: 0 when used up, None when the company wasn't deleted (or the end isn't known).
    trial_left_seconds: int | None = None


class AllowTrial(BaseModel):
    #: The number as the trial row shows it; its digits are what the trial check compares.
    number: str


class TrialAllowed(BaseModel):
    number: str
    allowed_at: dt.datetime


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
            admin_audit_log.c.details["trial_ends_at"].astext.label("trial_ends_at"),
            admin_audit_log.c.target_id,
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
        allows = {r.phone: r.at for r in (await conn.execute(allows_statement(digits))).fetchall()}
        rules = await PostgresPlatformSettingsRepository(conn).get(TRIAL_GUARDRAILS)
        audit_log = PostgresAdminAuditRepository(conn)
        deletions = {
            row.target_id: await audit_log.company_deleted(row.target_id)
            for row in rows
            if row.organization_id is None and row.target_id
        }
    window = int(rules.get("trial_per_phone_days") or 0)
    found = []
    for row in rows:
        allowed = allows.get(re.sub(r"\D", "", row.number or ""))
        allowed = allowed if allowed is not None and allowed > row.occurred_at else None
        new_from = row.occurred_at + dt.timedelta(days=window) if window else None
        # SS-24: a deleted company's trial carries on: what was left when it was deleted.
        deleted = deletions.get(row.target_id)
        ends = (deleted.trial_ends_at if deleted else None) or iso_moment(row.trial_ends_at)
        left = ends - deleted.deleted_at if deleted and ends else None
        if left is not None and left < MIN_TRIAL_LEFT:
            left = dt.timedelta(0)
        if deleted and left and new_from:
            new_from = min(new_from, deleted.deleted_at)
        found.append(
            TrialUse(
                number=row.number,
                company=row.company or "",
                started_at=row.occurred_at,
                signup_source=row.signup_source,
                organization_id=row.organization_id,
                company_exists=row.organization_id is not None,
                # Allowed early: possible from the moment it was allowed.
                new_trial_from=min(new_from, allowed) if new_from and allowed else new_from,
                allowed_at=allowed,
                deleted_at=deleted.deleted_at if deleted else None,
                trial_left_seconds=int(left.total_seconds()) if left is not None else None,
            )
        )
    return found


def allows_statement(digits: str) -> sa.Select:
    """SA-26: the latest "Allow a new trial" per number with these digits."""
    phone = admin_audit_log.c.details["phone"].astext
    return (
        sa.select(phone.label("phone"), sa.func.max(admin_audit_log.c.occurred_at).label("at"))
        .where(admin_audit_log.c.action == audit.SIGNUP_TRIAL_ALLOWED, phone.like(f"%{digits}%"))
        .group_by(phone)
    )


@router.post("/trials/allow", response_model=TrialAllowed)
async def allow_trial(body: AllowTrial, admin: dict = Depends(require_platform_admin)):
    """SA-26: let one number start one more free trial (a test company deleted by the team,
    a mistake). Recorded in the audit log, which is what the trial check reads; the
    trial it then starts limits the number again. The rule itself is unchanged."""
    phone = re.sub(r"\D", "", body.number)
    if len(phone) < NATIONAL_DIGITS:
        raise HTTPException(status_code=422, detail="Send the full number, with its country code.")
    async with get_engine().begin() as conn:
        entry = await record_admin_action(
            conn,
            actor=actor_from_admin(admin),
            action=audit.SIGNUP_TRIAL_ALLOWED,
            target_type="phone",
            target_id=phone,
            summary=f"Allowed a new free trial for +{phone}",
            details={"phone": phone},
        )
    return TrialAllowed(number=phone, allowed_at=entry.occurred_at)
