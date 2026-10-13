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

Shares the request's connection with the route: FastAPI caches `get_db_conn`
per request, so the gate costs one indexed settings read on the same
transaction, not a second connection.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncConnection  # noqa: TC002 — FastAPI resolves it at runtime

from mesiri.domains.organizations import settings as org_settings
from mesiri.infrastructure.postgres.dependency import get_db_conn
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


def require_module(module: str) -> Callable[..., Awaitable[None]]:
    """Build the gate for `module`. Raises at import time for an unknown name,
    so a typo in a router declaration fails the test suite, not a customer."""
    if module not in org_settings.MODULES:
        raise ValueError(f"unknown module: {module}")

    async def _gate(
        authorization: str | None = Header(None),
        conn: AsyncConnection = Depends(get_db_conn),
    ) -> None:
        organization_id = organization_from_token(authorization)
        if organization_id is None:
            return
        stored = await PostgresOrganizationSettingsRepository(conn).get(
            organization_id, org_settings.ENABLED_MODULES
        )
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
