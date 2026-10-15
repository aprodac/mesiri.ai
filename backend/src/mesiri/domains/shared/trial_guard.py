"""Read-only dashboard for a company whose free trial has ended (SS-08).

An HTTP middleware: a change request (POST/PUT/PATCH/DELETE) from a user of
an expired trial company gets `403 {"code": "TRIAL_EXPIRED", ...}`. Reading
keeps working, so the owner can still see their reports while deciding to
continue (decided 15 Oct). Suspended companies are untouched (SS-10 owns
them), and so is everything without a company token.

Like the module gate (modules.py) this is never an authentication check: no
token, a bad token or a platform admin passes straight through, so it can't
turn a working request into a 401. Login, the WhatsApp webhook, health and
the "continue" action itself are exempt by path.

The status read runs in its own short transaction (never the request's
`get_db_conn` one; see modules.py for the 2026-10-13 incident that rule
comes from) and is cached per company for a minute.
"""

from __future__ import annotations

import datetime as dt
import time
import uuid
from typing import Any

import sqlalchemy as sa
from fastapi import Request
from fastapi.responses import JSONResponse

from mesiri.domains.organizations import lifecycle

from .modules import _database_for, organization_from_token

WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
EXEMPT_PREFIXES: tuple[str, ...] = ("/auth", "/webhook", "/health", "/company/trial")
_CACHE_SECONDS = 60.0

TRIAL_EXPIRED_DETAIL = {
    "code": "TRIAL_EXPIRED",
    "message": (
        "Your free trial has ended, so your data is read-only. "
        "Choose 'Continue with Mesiri' to keep editing."
    ),
}

_cache: dict[uuid.UUID, tuple[bool, float]] = {}


def is_guarded(method: str, path: str) -> bool:
    """Whether this request is a change the guard looks at."""
    if method.upper() not in WRITE_METHODS:
        return False
    return not any(path == p or path.startswith(p + "/") for p in EXEMPT_PREFIXES)


async def _trial_expired(request: Request, organization_id: uuid.UUID) -> bool:
    cached = _cache.get(organization_id)
    if cached is not None and time.monotonic() - cached[1] < _CACHE_SECONDS:
        return cached[0]
    database = _database_for(request)
    if database is None:
        return False
    async with database.transaction() as conn:
        row = (
            await conn.execute(
                sa.text("SELECT status, trial_ends_at FROM organizations WHERE id = :id"),
                {"id": organization_id},
            )
        ).first()
    expired = (
        row is not None
        and lifecycle.effective_status(row.status, row.trial_ends_at, dt.datetime.now(dt.UTC))
        == lifecycle.EXPIRED
    )
    _cache[organization_id] = (expired, time.monotonic())
    return expired


async def trial_guard_middleware(request: Request, call_next: Any) -> Any:
    if is_guarded(request.method, request.url.path):
        organization_id = organization_from_token(request.headers.get("authorization"))
        if organization_id is not None:
            try:
                expired = await _trial_expired(request, organization_id)
            except Exception:  # noqa: BLE001 -- unsure: let the request through
                expired = False
            if expired:
                return JSONResponse(status_code=403, content={"detail": TRIAL_EXPIRED_DETAIL})
    return await call_next(request)


def clear_cache() -> None:
    """Tests, and right after a company is extended or converted."""
    _cache.clear()
