"""Module gate: a FastAPI dependency that blocks a switched-off module's API.

Attach it to a module's router (V1 tracker BE-06):

    router = APIRouter(
        prefix="/finance",
        dependencies=[Depends(require_module("finance"))],
    )

A request from a company that has the module switched off gets
``403 {"code": "MODULE_DISABLED", "module": "finance", ...}``.

Deliberately *not* an authentication check. Every route keeps its own auth
dependencies exactly as before; this gate only acts when it can tell which
company is asking. No token, an invalid token, or a platform admin (no
company) passes straight through, so adding it to a router can never turn a
working request into a 401.

The settings read runs in its own short transaction that is closed before
the route starts. It must NOT share the request's `get_db_conn` transaction:
that context maps every exception raised while it is open -- including the
route's own HTTPException(401) -- to a 500 "postgres unavailable", which is
exactly what the first version of this gate did to unauthenticated requests
in production on 2026-10-13.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import jwt
from fastapi import Header, HTTPException, Request

from mesiri.domains.organizations import settings as org_settings
from mesiri.infrastructure.postgres.repositories.organization_settings import (
    PostgresOrganizationSettingsRepository,
)

from ..identity.auth_service import ALGORITHM, SECRET_KEY

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


def organization_from_token(authorization: str | None) -> uuid.UUID | None:
    """The company a bearer token belongs to, or None when there isn't one.

    None covers: no header, a malformed or expired token, and a platform
    admin (whose token carries an empty `org`). Never raises.
    """
    if not authorization or not authorization.startswith("Bearer "):
        return None
    try:
        payload = jwt.decode(authorization[7:], SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    org = payload.get("org")
    if not org:
        return None
    try:
        return uuid.UUID(str(org))
    except ValueError:
        return None


def _database_for(request: Request) -> Any | None:
    """The app's Postgres, resolved the same way `get_db_conn` does
    (infrastructure/postgres/dependency.py), or None when the app has none
    wired (a bare test app), in which case the gate uses the default."""
    state = request.app.state
    if hasattr(state, "lifecycle"):
        return state.lifecycle.container.postgres
    if hasattr(state, "container"):
        return state.container.material_db
    return None


async def read_enabled_modules(request: Request, organization_id: uuid.UUID) -> object:
    """The company's stored `enabled_modules` value (or the default), read in
    a transaction that is fully closed when this returns."""
    database = _database_for(request)
    if database is None:
        return org_settings.default_for(org_settings.ENABLED_MODULES)
    async with database.transaction() as conn:
        return await PostgresOrganizationSettingsRepository(conn).get(
            organization_id, org_settings.ENABLED_MODULES
        )


def require_module(module: str) -> Callable[..., Awaitable[None]]:
    """Build the gate for `module`. Raises at import time for an unknown name,
    so a typo in a router declaration fails the test suite, not a customer."""
    if module not in org_settings.MODULES:
        raise ValueError(f"unknown module: {module}")

    async def _gate(request: Request, authorization: str | None = Header(None)) -> None:
        organization_id = organization_from_token(authorization)
        if organization_id is None:
            return
        stored = await read_enabled_modules(request, organization_id)
        if not org_settings.module_enabled(module, stored):
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "MODULE_DISABLED",
                    "module": module,
                    "message": f"The {module} module is not switched on for this company.",
                },
            )

    _gate.__name__ = f"require_module_{module}"
    return _gate
