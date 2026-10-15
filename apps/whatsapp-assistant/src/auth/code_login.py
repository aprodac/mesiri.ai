"""Web signup and login by a code sent on WhatsApp (SS-06, WEB-12).

    POST /auth/code/request  {phone, purpose}   send a code (login or signup)
    POST /auth/code/login    {phone, code}      log in with it
    POST /auth/code/verify   {phone, code}      signup: code right -> signup ticket
    POST /auth/signup        {signup_token, owner_name, company_name, site_name}
                                                company created, owner logged in

Signup asks the same questions as the WhatsApp signup (SS-04) and creates
the company through the same step (application/organizations/create_company)
with the same choices: a trial, the site is also the first project, its
automatic DPR on. The rules for codes are in
application/identity/login_codes.py; how a code is sent, in code_senders.py.

A login code goes to any active user whose WhatsApp number it is, owner or
not. For a number nobody has, /auth/code/request answers exactly as for one
that exists (and counts toward the same limits) but sends nothing, so the
page can't be used to find out who uses Mesiri.

Attached to auth/router.py's router, so it is served wherever /auth is.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Literal

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from auth.code_senders import CodeLoginUnavailable, build_login_code_sender
from context.projection_hooks import project_new_company
from mesiri.application.dpr.recipients import RecipientError, normalize_phone
from mesiri.application.identity.login_codes import (
    CODE_TTL,
    PURPOSE_LOGIN,
    PURPOSE_SIGNUP,
    CheckResult,
    LoginCodeError,
    SignupTicketError,
    check_code,
    issue_code,
    issue_signup_ticket,
    read_signup_ticket,
)
from mesiri.application.organizations.create_company import (
    CompanyCreationError,
    NewCompany,
    create_company,
)
from mesiri.application.organizations.signup_guard import (
    SignupAttempt,
    SignupRefused,
    check_signup,
)
from mesiri.infrastructure.postgres.repositories.login_codes import PostgresLoginCodeStore

# No prefix: included into auth/router.py's router, which is /auth.
router = APIRouter()

_log = logging.getLogger("mesiri.auth")

_users = sa.Table(
    "users",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True)),
    sa.Column("organization_id", sa.UUID(as_uuid=True)),
    sa.Column("full_name", sa.String),
    sa.Column("role", sa.String),
    sa.Column("status", sa.String),
    sa.Column("whatsapp_number", sa.String),
)
_organizations = sa.Table(
    "organizations",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True)),
    sa.Column("name", sa.String),
)

_WRONG_CODE = "That code isn't right. Check the WhatsApp message and try again."
_NO_CODE = "This code has expired or was already used. Ask for a new one."


class CodeRequest(BaseModel):
    phone: str
    purpose: Literal["login", "signup"] = PURPOSE_LOGIN


class CodeRequested(BaseModel):
    resend_after_s: int
    expires_in_s: int
    # Only with MESIRI_LOGIN_CODE_SENDER=dev, which sends nothing.
    dev_code: str | None = None


class CodeCheck(BaseModel):
    phone: str
    code: str


class SignupTicket(BaseModel):
    signup_token: str


class SignupRequest(BaseModel):
    signup_token: str
    owner_name: str
    company_name: str
    site_name: str


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _phone(raw: str) -> str:
    try:
        return normalize_phone(raw)
    except RecipientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _client_ip(request: Request) -> str | None:
    # nginx sets X-Forwarded-For to the caller's address (infra/nginx).
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return forwarded or (request.client.host if request.client else None)


def _sender():
    try:
        return build_login_code_sender()
    except CodeLoginUnavailable as exc:
        _log.info("login_code.unavailable reason=%s", exc)
        raise HTTPException(
            status_code=503,
            detail="Login by WhatsApp code isn't available yet. Use your email and password.",
        ) from exc


def _engine():
    from auth.router import get_engine

    return get_engine()


def _token(**claims: str) -> str:
    from auth.router import _create_token

    return _create_token(**claims)


async def _users_with_phone(conn, phone: str, *, active_only: bool) -> list:
    query = (
        sa.select(
            _users.c.id,
            _users.c.organization_id,
            _users.c.full_name,
            _users.c.role,
            _organizations.c.name.label("org_name"),
        )
        .outerjoin(_organizations, _users.c.organization_id == _organizations.c.id)
        # Compared as digits: older rows may hold "+91 98765 43210".
        .where(sa.func.regexp_replace(_users.c.whatsapp_number, r"\D", "", "g") == phone)
        .limit(2)
    )
    if active_only:
        query = query.where(_users.c.status == "active")
    return list((await conn.execute(query)).all())


@router.post("/code/request", response_model=CodeRequested, status_code=202)
async def request_code(body: CodeRequest, request: Request) -> CodeRequested:
    phone = _phone(body.phone)
    sender = _sender()
    now = _now()
    async with _engine().begin() as conn:
        if body.purpose == PURPOSE_SIGNUP:
            try:
                await check_signup(
                    conn,
                    SignupAttempt(phone=phone, signup_source="web", ip_address=_client_ip(request)),
                )
            except SignupRefused as exc:
                raise HTTPException(status_code=403, detail=str(exc)) from exc
            if await _users_with_phone(conn, phone, active_only=False):
                raise HTTPException(
                    status_code=409,
                    detail="This number already has a Mesiri account. Log in instead.",
                )
            deliver = True
        else:
            deliver = bool(await _users_with_phone(conn, phone, active_only=True))
        try:
            issued = await issue_code(PostgresLoginCodeStore(conn), phone, body.purpose, now=now)
        except LoginCodeError as exc:
            raise HTTPException(
                status_code=429,
                detail=str(exc),
                headers={"Retry-After": str(exc.retry_after_s)},
            ) from exc

    # Sent after commit: a code that was sent must exist to be checked.
    if deliver and not await sender.send(phone, issued.code):
        _log.warning("login_code.send_failed purpose=%s", body.purpose)
        raise HTTPException(
            status_code=502,
            detail="Couldn't send the code on WhatsApp. Try again in a minute.",
        )
    return CodeRequested(
        resend_after_s=issued.resend_after_s,
        expires_in_s=int(CODE_TTL.total_seconds()),
        dev_code=issued.code if deliver and sender.echoes_code else None,
    )


async def _check(phone: str, purpose: str, code: str):
    """Check the code in its own transaction, committed even when wrong: a
    wrong try that rolled back would be a free guess."""
    async with _engine().begin() as conn:
        result = await check_code(PostgresLoginCodeStore(conn), phone, purpose, code, now=_now())
        users = (
            await _users_with_phone(conn, phone, active_only=True)
            if result is CheckResult.OK and purpose == PURPOSE_LOGIN
            else []
        )
    if result is CheckResult.WRONG:
        raise HTTPException(status_code=401, detail=_WRONG_CODE)
    if result is CheckResult.NO_CODE:
        raise HTTPException(status_code=401, detail=_NO_CODE)
    return users


@router.post("/code/login")
async def login_with_code(body: CodeCheck) -> dict:
    users = await _check(_phone(body.phone), PURPOSE_LOGIN, body.code)
    if not users:
        raise HTTPException(status_code=401, detail="No Mesiri account uses this number.")
    if len(users) > 1:
        # One person in several companies is BE-04; until then, refuse
        # rather than pick one of them.
        raise HTTPException(
            status_code=409,
            detail="This number is on more than one account. Log in with your email instead.",
        )
    user = users[0]
    token = _token(
        user_id=str(user.id),
        org_id=str(user.organization_id) if user.organization_id else "",
        role=user.role,
        name=user.full_name or "",
        org_name=user.org_name or "Independent",
    )
    return {"access_token": token, "token_type": "bearer"}


@router.post("/code/verify", response_model=SignupTicket)
async def verify_signup_code(body: CodeCheck) -> SignupTicket:
    phone = _phone(body.phone)
    await _check(phone, PURPOSE_SIGNUP, body.code)
    return SignupTicket(signup_token=issue_signup_ticket(phone, now=_now()))


@router.post("/signup")
async def signup(body: SignupRequest, request: Request) -> dict:
    try:
        phone = read_signup_ticket(body.signup_token)
    except SignupTicketError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    new = NewCompany(
        name=body.company_name,
        owner_name=body.owner_name,
        owner_phone=phone,
        # Same shape as the WhatsApp signup (SS-04): the site is the first
        # project too, and its evening DPR is on from day one.
        project_name=body.site_name,
        site_name=body.site_name,
        auto_dpr=True,
        start_as="trial",
        signup_source="web",
    )
    try:
        async with _engine().begin() as conn:
            await check_signup(
                conn,
                SignupAttempt(phone=phone, signup_source="web", ip_address=_client_ip(request)),
            )
            created = await create_company(conn, new)
    except SignupRefused as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except CompanyCreationError as exc:
        raise HTTPException(status_code=409 if exc.conflict else 400, detail=str(exc)) from exc

    await project_new_company(created)
    _log.info("signup.web_created org_id=%s", created.organization_id)

    token = _token(
        user_id=str(created.owner_user_id),
        org_id=str(created.organization_id),
        role="ADMIN",
        name=" ".join(body.owner_name.split()),
        org_name=created.name,
    )
    return {"access_token": token, "token_type": "bearer"}
