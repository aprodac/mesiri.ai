"""Auth router — login and account endpoints for the Mesiri apps."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import bcrypt as _bcrypt
import jwt
import sqlalchemy as sa
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import create_async_engine

from mesiri.domains.identity.auth_service import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    ALGORITHM,
    SECRET_KEY,
)

router = APIRouter(prefix="/auth", tags=["auth"])

# ---------------------------------------------------------------------------
# Shared crypto config
# ---------------------------------------------------------------------------
# SECRET_KEY, ALGORITHM and ACCESS_TOKEN_EXPIRE_MINUTES come from
# mesiri.domains.identity.auth_service (imported above): one definition, so
# the two apps can never sign with different secrets.


def _hash_pw(plain: str) -> str:
    return _bcrypt.hashpw(plain.encode(), _bcrypt.gensalt()).decode()


def _verify_pw(plain: str, hashed: str) -> bool:
    return _bcrypt.checkpw(plain.encode(), hashed.encode())


def _get_engine():
    host = os.environ.get("MESIRI_POSTGRES__HOST", "localhost")
    port = os.environ.get("MESIRI_POSTGRES__PORT", "5432")
    user = os.environ.get("MESIRI_POSTGRES__USER", "mesiri")
    password = os.environ.get("MESIRI_POSTGRES__PASSWORD", "mesiri_local_dev")
    database = os.environ.get("MESIRI_POSTGRES__DATABASE", "mesiri")
    dsn = f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{database}"
    return create_async_engine(dsn, echo=False, pool_pre_ping=True)


_engine = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = _get_engine()
    return _engine


# Raw table reference
users_table = sa.Table(
    "users",
    sa.MetaData(),
    sa.Column("id", sa.UUID, primary_key=True),
    sa.Column("organization_id", sa.UUID),
    sa.Column("email", sa.String),
    sa.Column("username", sa.String),
    sa.Column("hashed_password", sa.String),
    sa.Column("full_name", sa.String),
    sa.Column("role", sa.String),
    sa.Column("whatsapp_number", sa.String),
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class UserLogin(BaseModel):
    # Field kept named `email` for backward compatibility with the existing
    # dashboard login form -- it accepts either an email or a username
    # (see login() below), so no frontend change is required for a
    # WhatsApp-created user (whose username is their WhatsApp number) to log
    # in with what they were told to type.
    email: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class CompanyStatus(BaseModel):
    # trial / active / expired / suspended, by the one lifecycle rule (a
    # trial past its end reads expired, as the read-only guard sees it).
    status: str
    trial_ends_at: datetime | None = None
    trial_days_left: int | None = None
    # An owner already asked to continue (POST /company/trial/continue or
    # CONTINUE on WhatsApp) and the team hasn't closed it yet.
    continue_requested: bool = False


class Me(BaseModel):
    user_id: str
    org_id: str
    role: str
    name: str
    org_name: str
    is_platform_admin: bool
    # Product modules switched on for the caller's company (V1 tracker
    # BE-06), so the dashboard can show only what the company has. A platform
    # admin has no company and sees every module.
    enabled_modules: list[str] = Field(default_factory=list)
    # The company's trial status (SS-15), so every page can show the "trial
    # ended, read-only" banner. None for a platform admin, or if unreadable.
    company: CompanyStatus | None = None


class ChangePassword(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _create_token(user_id: str, org_id: str, role: str, name: str = "", org_name: str = "") -> str:
    expire = datetime.now(UTC) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": user_id,
        "org": org_id,
        "role": role,
        "name": name,
        "org_name": org_name,
        "exp": expire,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.post("/login", response_model=Token)
async def login(creds: UserLogin):
    engine = get_engine()

    # We need the organizations table for the join
    metadata = sa.MetaData()
    organizations_table = sa.Table(
        "organizations",
        metadata,
        sa.Column("id", sa.UUID, primary_key=True),
        sa.Column("name", sa.String),
    )

    async with engine.connect() as conn:
        # Join users with organizations to get the org name
        query = (
            sa.select(
                users_table.c.id,
                users_table.c.organization_id,
                users_table.c.hashed_password,
                users_table.c.role,
                users_table.c.full_name,
                organizations_table.c.name.label("org_name"),
            )
            .outerjoin(
                organizations_table, users_table.c.organization_id == organizations_table.c.id
            )
            .where(
                sa.or_(
                    users_table.c.email == creds.email,
                    users_table.c.username == creds.email,
                )
            )
        )

        result = await conn.execute(query)
        row = result.first()

    if not row:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not _verify_pw(creds.password, row.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = _create_token(
        user_id=str(row.id),
        org_id=str(row.organization_id) if row.organization_id else "",
        role=row.role,
        name=row.full_name or "",
        org_name=row.org_name or "Independent",
    )
    return Token(access_token=token)


@router.get("/me", response_model=Me)
async def me(authorization: str = Header(None)) -> Me:
    """Confirms a stored token is still valid and returns the server-verified
    identity — the frontend must never authorize UI behavior off a
    client-decoded JWT, only off this response."""
    from mesiri.domains.shared.auth import get_current_user

    payload = await get_current_user(authorization)
    org = payload.get("org") or ""
    role = (payload.get("role") or "").upper()
    return Me(
        user_id=payload.get("sub", ""),
        org_id=org,
        role=role,
        name=payload.get("name", ""),
        org_name=payload.get("org_name", ""),
        is_platform_admin=role == "ADMIN" and not org,
        enabled_modules=await _enabled_modules_for(org),
        company=await _company_status_for(org),
    )


async def _company_status_for(org: str) -> CompanyStatus | None:
    """The company's trial status for the banner. Never raises, for the same
    reason as `_enabled_modules_for`: an unreadable status shows no banner
    rather than logging the user out."""
    if not org:
        return None
    try:
        from mesiri.domains.organizations import lifecycle
        from mesiri.domains.organizations import settings as org_settings
        from mesiri.domains.organizations.trial_notices import OPEN
        from mesiri.infrastructure.postgres.repositories.organization_settings import (
            PostgresOrganizationSettingsRepository,
        )

        org_id = uuid.UUID(org)
        async with get_engine().connect() as conn:
            row = (
                await conn.execute(
                    sa.text("SELECT status, trial_ends_at FROM organizations WHERE id = :id"),
                    {"id": org_id},
                )
            ).first()
            if row is None:
                return None
            requests = await PostgresOrganizationSettingsRepository(conn).get(
                org_id, org_settings.CONTINUE_REQUESTS
            )
        now = datetime.now(UTC)
        status = lifecycle.effective_status(row.status, row.trial_ends_at, now)
        return CompanyStatus(
            status=status,
            trial_ends_at=row.trial_ends_at,
            trial_days_left=(
                lifecycle.trial_days_left(row.trial_ends_at, now)
                if status == lifecycle.TRIAL
                else None
            ),
            continue_requested=isinstance(requests, list)
            and any(isinstance(r, dict) and r.get("status") == OPEN for r in requests),
        )
    except Exception:  # noqa: BLE001 — see docstring: /me must not fail on this
        import logging

        logging.getLogger("mesiri.auth").exception("auth.me.company_status_lookup_failed")
        return None


async def _enabled_modules_for(org: str) -> list[str]:
    """The company's enabled modules; every module for a platform admin.

    Never raises: /auth/me gates every dashboard page load, so a settings
    lookup failure degrades to the default (every module on, the same as a
    company that never changed the setting) instead of logging the user out.
    """
    from mesiri.domains.organizations import settings as org_settings

    if not org:
        return list(org_settings.MODULES)
    try:
        from mesiri.infrastructure.postgres.repositories.organization_settings import (
            PostgresOrganizationSettingsRepository,
        )

        async with get_engine().connect() as conn:
            stored = await PostgresOrganizationSettingsRepository(conn).get(
                uuid.UUID(org), org_settings.ENABLED_MODULES
            )
        return org_settings.enabled_modules(stored)
    except Exception:  # noqa: BLE001 — see docstring: /me must not fail on this
        import logging

        logging.getLogger("mesiri.auth").exception("auth.me.enabled_modules_lookup_failed")
        return list(org_settings.DEFAULT_ENABLED_MODULES)


@router.post("/change-password", status_code=204)
async def change_password(body: ChangePassword, authorization: str = Header(None)) -> None:
    """Self-service password change for any authenticated user, tenant or
    platform admin — requires the current password, not just a valid
    session, mirroring api.ts's rule that a token's mere presence proves
    nothing on its own."""
    from mesiri.domains.shared.auth import get_current_user

    payload = await get_current_user(authorization)
    user_id = uuid.UUID(payload["sub"])

    engine = get_engine()
    async with engine.begin() as conn:
        result = await conn.execute(
            sa.select(users_table.c.hashed_password).where(users_table.c.id == user_id)
        )
        row = result.first()
        if row is None:
            raise HTTPException(status_code=401, detail="User not found")
        if not _verify_pw(body.current_password, row.hashed_password):
            raise HTTPException(status_code=401, detail="Current password is incorrect")

        await conn.execute(
            users_table.update()
            .where(users_table.c.id == user_id)
            .values(hashed_password=_hash_pw(body.new_password))
        )


# There is deliberately no public /auth/register. It accepted any `role` and
# `organization_id` without authentication, so anyone could mint a platform-
# admin token (role ADMIN, no org). Users are created only by an authenticated
# admin (admin/router.py, admin/platform_users_router.py) or by provisioning.


# Login by WhatsApp code and web signup (SS-06, WEB-12), served under the same
# /auth prefix. Imported last: auth.code_login reads this module's helpers.
from auth.code_login import router as _code_login_router  # noqa: E402

router.include_router(_code_login_router)
