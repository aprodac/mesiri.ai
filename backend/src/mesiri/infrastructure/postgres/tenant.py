"""Which company the current request or WhatsApp message is for (BE-03).

Row-level security policies (migration 0484, BE-03 step 2) let a transaction
see only its company's rows once `mesiri.organization_id` is set on it, and
leave a transaction with nothing set unchanged -- system jobs (the automation
runner, the webhook finding a sender by phone, login, the control panel)
legitimately read across companies.

Two halves:
- a context variable holding the company for this request/message
  (`bind_tenant`, `tenant_scope`), set once the company is known: the
  dashboard's `get_auth_context`, the WhatsApp journey once the sender is
  resolved, the WhatsApp app's own dashboard routers;
- `apply_tenant(conn)`, which copies it onto a transaction with
  `set_config(..., true)` -- transaction-local, so a pooled connection never
  carries it into another request. `PostgresDatabase.transaction()` and
  `TenantScopedEngine` call it on every transaction they open.

`TenantResetMiddleware` clears the variable at the start of every HTTP
request, so a keep-alive connection served by one task can't carry one
request's company into the next.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

TENANT_SETTING = "mesiri.organization_id"

_current: ContextVar[uuid.UUID | None] = ContextVar("mesiri_tenant", default=None)


def _as_uuid(value: object) -> uuid.UUID | None:
    if value is None or value == "":
        return None
    if isinstance(value, uuid.UUID):
        return value
    text_value = str(value)
    if text_value.startswith("ctx_org_"):
        text_value = text_value[len("ctx_org_") :]
    try:
        return uuid.UUID(text_value)
    except ValueError:
        return None


def current_tenant() -> uuid.UUID | None:
    return _current.get()


def bind_tenant(organization_id: object) -> None:
    """Set the company for the rest of this request/message. Something that
    isn't a company id clears it rather than guessing."""
    _current.set(_as_uuid(organization_id))


@contextmanager
def tenant_scope(organization_id: object = None) -> Iterator[None]:
    """The company for the block, restored afterwards."""
    token = _current.set(_as_uuid(organization_id))
    try:
        yield
    finally:
        _current.reset(token)


async def apply_tenant(conn: AsyncConnection, organization_id: object = None) -> None:
    """Scope this transaction to the given company, or to the bound one. A
    no-op (no statement) when there is none."""
    org = _as_uuid(organization_id) if organization_id is not None else _current.get()
    if org is None:
        return
    await conn.execute(
        text("SELECT set_config(:setting, :org, true)"),
        {"setting": TENANT_SETTING, "org": str(org)},
    )


@asynccontextmanager
async def unscoped(conn: AsyncConnection) -> AsyncIterator[AsyncConnection]:
    """Inside a company-scoped transaction, briefly see every company -- only
    for checks that must ("is this number or email taken anywhere?"). The
    company is restored afterwards. RLS here guards against a forgotten
    filter, not against our own code, so this is allowed by design."""
    previous = (
        await conn.execute(
            text("SELECT current_setting(:setting, true)"), {"setting": TENANT_SETTING}
        )
    ).scalar_one_or_none()
    if not previous:
        yield conn
        return
    await conn.execute(
        text("SELECT set_config(:setting, '', true)"), {"setting": TENANT_SETTING}
    )
    restore = text("SELECT set_config(:setting, :org, true)")
    params = {"setting": TENANT_SETTING, "org": previous}
    try:
        yield conn
    except BaseException:
        # The transaction may already be aborted; the original error matters.
        try:
            await conn.execute(restore, params)
        except Exception:  # noqa: BLE001
            pass
        raise
    await conn.execute(restore, params)


class TenantScopedEngine:
    """An AsyncEngine whose begin()/connect() scope each transaction to the
    bound company. For code that opens its own engine instead of using
    PostgresDatabase (the WhatsApp app's projects and users routers)."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[AsyncConnection]:
        async with self._engine.begin() as conn:
            await apply_tenant(conn)
            yield conn

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[AsyncConnection]:
        async with self._engine.connect() as conn:
            await apply_tenant(conn)
            yield conn

    def __getattr__(self, name: str) -> Any:
        return getattr(self._engine, name)


class TenantResetMiddleware:
    """ASGI middleware: every HTTP request starts with no company bound."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        with tenant_scope(None):
            await self.app(scope, receive, send)
