"""Create a company: the one step every onboarding path uses (SS-03).

The superadmin's "Provision tenant", the API and (later) WhatsApp and web
self-serve signup all create a company here, so a company can't come out
differently depending on which door it came through. Before this there were
two copies in the admin routers (BE-02), and they had already drifted apart.

One call makes everything a company needs to start sending updates:

    organizations   the company, `active` or on a free trial
    users           the owner (ADMIN), by email, WhatsApp number or both
    projects/sites  optionally the first project and its first site
    materials       the starter catalogue (BE-24, domains/materials/defaults)

Takes an externally-supplied connection and never commits, so the caller's
transaction makes it all-or-nothing: a refused owner leaves no company behind.
Telling the WhatsApp assistant about the new rows (context projection) is the
caller's job after commit; that layer lives in the assistant app.
"""

from __future__ import annotations

import datetime as dt
import secrets
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

import sqlalchemy as sa

from mesiri.application.audit.record import record_admin_action
from mesiri.application.dpr.recipients import RecipientError, normalize_phone
from mesiri.application.materials.starter_catalog import seed_starter_materials
from mesiri.domains.audit import actions as audit
from mesiri.domains.organizations import lifecycle
from mesiri.domains.organizations.platform_settings import TRIAL_POLICY
from mesiri.infrastructure.postgres.repositories.platform_settings import (
    PostgresPlatformSettingsRepository,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection

# Mesiri's customers are Indian construction companies; a company created in
# UTC sends its 7 pm report at 12:30 am.
DEFAULT_TIMEZONE = "Asia/Kolkata"
DEFAULT_DEPLOYMENT_TYPE = "SaaS"
DEFAULT_DB_ROUTE = "shared-cluster-01"

START_ACTIVE = lifecycle.ACTIVE
START_TRIAL = lifecycle.TRIAL
_START_AS = (START_ACTIVE, START_TRIAL)

_NAME_MAX = 120

_md = sa.MetaData()
_organizations = sa.Table(
    "organizations",
    _md,
    sa.Column("id", sa.UUID(as_uuid=True)),
    sa.Column("name", sa.String),
    sa.Column("deployment_type", sa.String),
    sa.Column("db_route", sa.String),
    sa.Column("status", sa.String),
    sa.Column("timezone", sa.String),
    sa.Column("trial_started_at", sa.DateTime(timezone=True)),
    sa.Column("trial_ends_at", sa.DateTime(timezone=True)),
    sa.Column("signup_source", sa.String),
    sa.Column("created_at", sa.DateTime(timezone=True)),
    sa.Column("updated_at", sa.DateTime(timezone=True)),
)
_users = sa.Table(
    "users",
    _md,
    sa.Column("id", sa.UUID(as_uuid=True)),
    sa.Column("organization_id", sa.UUID(as_uuid=True)),
    sa.Column("email", sa.String),
    sa.Column("hashed_password", sa.String),
    sa.Column("full_name", sa.String),
    sa.Column("role", sa.String),
    sa.Column("status", sa.String),
    sa.Column("whatsapp_number", sa.String),
)
_projects = sa.Table(
    "projects",
    _md,
    sa.Column("id", sa.UUID(as_uuid=True)),
    sa.Column("organization_id", sa.UUID(as_uuid=True)),
    sa.Column("name", sa.String),
    sa.Column("reporting_timezone", sa.String),
    sa.Column("auto_generate_dpr", sa.Boolean),
)
_sites = sa.Table(
    "sites",
    _md,
    sa.Column("id", sa.UUID(as_uuid=True)),
    sa.Column("project_id", sa.UUID(as_uuid=True)),
    sa.Column("organization_id", sa.UUID(as_uuid=True)),
    sa.Column("name", sa.String),
    sa.Column("status", sa.String),
)


class CompanyCreationError(ValueError):
    """A company that can't be created; the message says why.

    `conflict` is True when the request was fine but something it names is
    already taken (owner email or WhatsApp number), so routes can answer 409
    rather than 400."""

    def __init__(self, message: str, *, conflict: bool = False) -> None:
        super().__init__(message)
        self.conflict = conflict


@dataclass(frozen=True, slots=True)
class NewCompany:
    name: str
    owner_name: str
    owner_email: str | None = None
    owner_phone: str | None = None
    # None: the owner can't log in to the dashboard with a password (a
    # WhatsApp-only owner); a login code (WEB-12/SS-06) comes later.
    owner_password: str | None = None
    project_name: str | None = None
    # Defaults to the project's name when a project is given without one.
    site_name: str | None = None
    # Switch the first project's automatic DPR on (cutoff and send deadline
    # keep their column defaults). Self-serve signups want a report the
    # first evening; the superadmin keeps choosing per project.
    auto_dpr: bool = False
    start_as: str = START_ACTIVE
    signup_source: str = "superadmin"
    deployment_type: str = DEFAULT_DEPLOYMENT_TYPE
    db_route: str = DEFAULT_DB_ROUTE
    timezone: str = DEFAULT_TIMEZONE


@dataclass(frozen=True, slots=True)
class CreatedCompany:
    organization_id: uuid.UUID
    name: str
    deployment_type: str
    db_route: str
    status: str
    signup_source: str
    timezone: str
    created_at: dt.datetime
    trial_started_at: dt.datetime | None
    trial_ends_at: dt.datetime | None
    owner_user_id: uuid.UUID
    owner_email: str | None
    owner_whatsapp_number: str | None
    project_id: uuid.UUID | None
    site_id: uuid.UUID | None
    materials_seeded: int = 0


def _clean_name(label: str, value: object, *, required: bool) -> str | None:
    text = " ".join(str(value or "").split())
    if not text:
        if required:
            raise CompanyCreationError(f"{label} is required")
        return None
    if len(text) > _NAME_MAX:
        raise CompanyCreationError(f"{label} is longer than {_NAME_MAX} characters")
    return text


def validate(new: NewCompany) -> NewCompany:
    """`new` with every field trimmed and checked; raises CompanyCreationError.
    Pure, so the rules are testable without a database."""
    name = _clean_name("Company name", new.name, required=True)
    owner_name = _clean_name("Owner name", new.owner_name, required=True)

    email = (new.owner_email or "").strip().lower() or None
    if email is not None and ("@" not in email or " " in email):
        raise CompanyCreationError("Owner email is not a valid email address")

    phone = None
    if (new.owner_phone or "").strip():
        try:
            phone = normalize_phone(new.owner_phone)
        except RecipientError as exc:
            raise CompanyCreationError(f"Owner WhatsApp number: {exc}") from exc

    if email is None and phone is None:
        raise CompanyCreationError("The owner needs an email or a WhatsApp number")

    password = new.owner_password or None
    if password is not None and email is None:
        # Dashboard login is by email; a password with nothing to log in
        # with is a mistake in the request, not something to store.
        raise CompanyCreationError("A password needs an owner email to log in with")

    project = _clean_name("Project name", new.project_name, required=False)
    site = _clean_name("Site name", new.site_name, required=False)
    if site is not None and project is None:
        raise CompanyCreationError("A site needs a project")
    if project is not None and site is None:
        site = project

    start_as = (new.start_as or "").strip().lower()
    if start_as not in _START_AS:
        raise CompanyCreationError(f"start_as must be one of {list(_START_AS)}")

    source = (new.signup_source or "").strip().lower()
    if source not in lifecycle.SIGNUP_SOURCES:
        raise CompanyCreationError(f"signup_source must be one of {list(lifecycle.SIGNUP_SOURCES)}")

    return NewCompany(
        name=name,
        owner_name=owner_name,
        owner_email=email,
        owner_phone=phone,
        owner_password=password,
        project_name=project,
        site_name=site,
        auto_dpr=bool(new.auto_dpr),
        start_as=start_as,
        signup_source=source,
        deployment_type=(new.deployment_type or "").strip() or DEFAULT_DEPLOYMENT_TYPE,
        db_route=(new.db_route or "").strip() or DEFAULT_DB_ROUTE,
        timezone=(new.timezone or "").strip() or DEFAULT_TIMEZONE,
    )


def _hash_password(plain: str) -> str:
    # bcrypt directly, like the assistant's admin router: passlib breaks on
    # bcrypt 5.0.
    import bcrypt

    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


async def _assert_owner_free(conn: AsyncConnection, email: str | None, phone: str | None) -> None:
    if email is not None:
        taken = await conn.execute(
            sa.select(_users.c.id).where(sa.func.lower(_users.c.email) == email)
        )
        if taken.first() is not None:
            raise CompanyCreationError("Owner email is already registered", conflict=True)
    if phone is not None:
        # Compared as digits: older rows may hold "+91 98765 43210".
        taken = await conn.execute(
            sa.select(_users.c.id).where(
                sa.func.regexp_replace(_users.c.whatsapp_number, r"\D", "", "g") == phone
            )
        )
        if taken.first() is not None:
            # One person in several companies is BE-04; until then a number
            # belongs to one user, or inbound messages can't be routed.
            raise CompanyCreationError(
                "That WhatsApp number already belongs to another user", conflict=True
            )


def _default_actor(new: NewCompany, owner_id: uuid.UUID) -> audit.AuditActor:
    if new.signup_source in ("whatsapp", "web"):
        # The new owner signed themselves up.
        return audit.AuditActor(
            kind=audit.ACTOR_SELF_SIGNUP,
            user_id=owner_id,
            label=new.owner_phone or new.owner_email,
        )
    return audit.SYSTEM


async def create_company(
    conn: AsyncConnection,
    new: NewCompany,
    *,
    now: dt.datetime | None = None,
    actor: audit.AuditActor | None = None,
) -> CreatedCompany:
    """Create the company, its owner and optionally its first project and
    site, inside the caller's transaction. Raises CompanyCreationError.

    `actor` is who is creating it, for the audit log (BE-05): the platform
    admin on /provision. Left out, a self-serve signup is recorded as the
    owner signing up and anything else as the system."""
    new = validate(new)
    now = now or dt.datetime.now(dt.UTC)

    await _assert_owner_free(conn, new.owner_email, new.owner_phone)

    trial_started_at = trial_ends_at = None
    if new.start_as == START_TRIAL:
        policy = await PostgresPlatformSettingsRepository(conn).get(TRIAL_POLICY)
        trial_started_at, trial_ends_at = lifecycle.trial_window(now, int(policy["trial_days"]))

    org_id = uuid.uuid4()
    await conn.execute(
        _organizations.insert().values(
            id=org_id,
            name=new.name,
            deployment_type=new.deployment_type,
            db_route=new.db_route,
            status=new.start_as,
            timezone=new.timezone,
            trial_started_at=trial_started_at,
            trial_ends_at=trial_ends_at,
            signup_source=new.signup_source,
            created_at=now,
            updated_at=now,
        )
    )

    owner_id = uuid.uuid4()
    # No password: a random one nobody is told, so the column's NOT NULL holds
    # and no password can match.
    password = new.owner_password or secrets.token_urlsafe(32)
    await conn.execute(
        _users.insert().values(
            id=owner_id,
            organization_id=org_id,
            email=new.owner_email,
            hashed_password=_hash_password(password),
            full_name=new.owner_name,
            role="ADMIN",
            status="active",
            whatsapp_number=new.owner_phone,
        )
    )

    project_id = site_id = None
    if new.project_name is not None:
        # The owner is ADMIN, which reaches every project by role, so no
        # project_members row is needed.
        project_id = uuid.uuid4()
        await conn.execute(
            _projects.insert().values(
                id=project_id,
                organization_id=org_id,
                name=new.project_name,
                reporting_timezone=new.timezone,
                auto_generate_dpr=new.auto_dpr,
            )
        )
        site_id = uuid.uuid4()
        await conn.execute(
            _sites.insert().values(
                id=site_id,
                project_id=project_id,
                organization_id=org_id,
                name=new.site_name,
                status="active",
            )
        )

    # Starter materials (BE-24), so a supervisor's first "40 bags cement"
    # resolves instead of "ask your admin". Units, issue types and trades are
    # platform-wide already; only the materials catalogue is per company.
    materials_seeded = await seed_starter_materials(conn, org_id, created_by=owner_id)

    await record_admin_action(
        conn,
        actor=actor or _default_actor(new, owner_id),
        action=audit.COMPANY_CREATED,
        organization_id=org_id,
        target_type="organization",
        target_id=org_id,
        summary=f"Created {new.name} ({new.start_as}, via {new.signup_source})",
        details={
            "name": new.name,
            "status": new.start_as,
            "signup_source": new.signup_source,
            "trial_ends_at": trial_ends_at,
            "owner_user_id": owner_id,
            "owner_email": new.owner_email,
            "owner_whatsapp_number": new.owner_phone,
            "project_id": project_id,
            "site_id": site_id,
        },
        now=now,
    )

    return CreatedCompany(
        organization_id=org_id,
        name=new.name,
        deployment_type=new.deployment_type,
        db_route=new.db_route,
        status=new.start_as,
        signup_source=new.signup_source,
        timezone=new.timezone,
        created_at=now,
        trial_started_at=trial_started_at,
        trial_ends_at=trial_ends_at,
        owner_user_id=owner_id,
        owner_email=new.owner_email,
        owner_whatsapp_number=new.owner_phone,
        project_id=project_id,
        site_id=site_id,
        materials_seeded=materials_seeded,
    )
